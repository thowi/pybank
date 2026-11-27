"""Ingest entry point. Wires the importers to beangulp's CLI.

Accounts are configured in a TOML file passed as `--config`.
"""

import datetime
import functools
import itertools
import logging
import os
import re
import shutil
import sys
import textwrap
import threading
import tomllib
import webbrowser

import beangulp
import click
from beancount import loader
from beancount.core import data
from beancount.parser import printer

from pybank.importer.beancount import (
    IN_TRANSIT,
    META_COUNTERPARTY_ACCOUNT,
    categorize,
    dkb,
    ibkr,
    postfinance,
    qif,
    qif_sidecar,
    refunds,
    revolut,
    routing,
    rules,
    see,
    transfer_hints,
    transfer_matcher,
    transfer_review,
    wise,
)

# beangulp reports progress a file at a time and leaves the line open until
# the file is done, so a log record written meanwhile lands mid-line.
_LOG_FORMAT = "\n%(message)s"

# The answers on transfer pairs, kept next to the config file.
_ANSWERS_FILE = "transfer-pairs.toml"

# The approved categories of open rows, kept next to the config file.
_CATEGORY_ANSWERS_FILE = "categories.toml"

# The model's suggestions, kept next to the config file so a rerun does not pay
# for them again.
_SUGGESTIONS_FILE = "category-suggestions.jsonl"

_CATEGORIZE_KEYS = {"country", "cutoff", "effort", "examples", "model"}

# The categorization rules, kept next to the config file. Optional.
_RULES_FILE = "rules.toml"

_RULE_KEYS = {"account", "book", "from", "labels", "text", "until"}

# Below the minimum a transaction column wraps too much to read. Above the
# maximum the eye loses the row between two columns.
_MAX_COLUMN_WIDTH = 60
_MIN_COLUMN_WIDTH = 24

# The rows of a group of suggestions shown before it is approved in bulk.
_GROUP_SHOWN = 5

# beangulp skips any input above 8 MiB before an importer sees it. A SEE
# Finance database passes that after a few years of use.
_MAX_FILE_SIZE = 1024 * 1024 * 1024


# Config that only an importer can find fault with raises the same type. Here
# it stops the run. Inside beangulp it skips one file and prints the message.
_ConfigError = routing.ConfigError


def _accounts(section: dict, key: str, table: str) -> dict | None:
    """Returns the fragment-to-account table under `key`, if it is there."""
    accounts = section.get(key)
    if accounts is None:
        return None
    if not isinstance(accounts, dict):
        raise _ConfigError(
            f"[{table}] must be a table mapping a fragment of the account "
            f"identifier to an account, not a bare account name."
        )
    return accounts


def _dkb(section: dict) -> list[beangulp.Importer]:
    # The library is EUR-only in practice, but the account decides, not us.
    currency = section.get("currency", "EUR")
    importers = []
    card = _accounts(section, "card", "dkb.card")
    if card is not None:
        importers.append(dkb.CreditCardImporter(card, currency))
    checking = _accounts(section, "checking", "dkb.checking")
    if checking is not None:
        importers.append(dkb.CheckingImporter(checking, currency))
    return importers


def _ibkr(section: dict) -> list[beangulp.Importer]:
    try:
        accounts = ibkr.Accounts(**section)
    except TypeError as err:
        raise _ConfigError(f"[ibkr]: {err}") from err
    return [ibkr.Importer(accounts)]


def _postfinance(section: dict) -> list[beangulp.Importer]:
    importers = []
    card = _accounts(section, "card", "postfinance.card")
    if card is not None:
        importers.append(postfinance.CreditCardImporter(card))
    checking = _accounts(section, "checking", "postfinance.checking")
    if checking is not None:
        importers.append(postfinance.CheckingImporter(checking))
    return importers


def _qif_targets(section: dict, table: str) -> dict[str, qif.Target]:
    targets = {}
    for name, target in section.get("targets", {}).items():
        try:
            targets[name] = qif.Target(target["account"], target["currency"])
        except (KeyError, TypeError) as err:
            raise _ConfigError(f"[{table}.targets] {name!r} needs account and currency") from err
    if not targets:
        raise _ConfigError(f"[{table}] needs at least one target, or the export imports nothing")
    return targets


def _qif(section: dict) -> list[beangulp.Importer]:
    return [qif.Importer(_qif_targets(section, "qif"), section.get("categories", {}))]


def _revolut(section: dict) -> list[beangulp.Importer]:
    accounts = _accounts(section, "accounts", "revolut.accounts")
    if not accounts:
        raise _ConfigError("[revolut.accounts] must map at least one currency to an account")
    return [revolut.Importer(accounts)]


def _see(section: dict) -> list[beangulp.Importer]:
    # The database holds what the QIF export holds, so the config is the same.
    return [see.Importer(_qif_targets(section, "see"), section.get("categories", {}))]


def _wise(section: dict) -> list[beangulp.Importer]:
    accounts = _accounts(section, "accounts", "wise.accounts")
    if not accounts:
        raise _ConfigError("[wise.accounts] must map at least one currency to an account")
    return [wise.Importer(accounts)]


def _hints(config: dict) -> list[transfer_hints.Hint]:
    """Returns the `[[transfers]]` hints, or raises `_ConfigError`."""
    hints = []
    for i, hint in enumerate(config.get("transfers", [])):
        try:
            # Banks change the case of their own text between export formats.
            text = re.compile(hint["text"], re.IGNORECASE)
            hints.append(transfer_hints.Hint(hint["account"], text))
        except (KeyError, TypeError) as err:
            raise _ConfigError(f"[[transfers]] #{i + 1} needs account and text") from err
        except re.error as err:
            raise _ConfigError(f"[[transfers]] #{i + 1}: Bad text pattern: {err}") from err
    return hints


def _rule(i: int, entry: dict) -> rules.Rule:
    where = f"{_RULES_FILE} rule #{i + 1}"
    unknown = sorted(set(entry) - _RULE_KEYS)
    if unknown:
        raise _ConfigError(f"{where}: Unknown keys: {', '.join(unknown)}")
    if "book" not in entry or "text" not in entry:
        raise _ConfigError(f"{where} needs book and text")
    try:
        text = re.compile(entry["text"], re.IGNORECASE)
    except TypeError as err:
        raise _ConfigError(f"{where}: text must be a string") from err
    except re.error as err:
        raise _ConfigError(f"{where}: Bad text pattern: {err}") from err
    if not isinstance(entry.get("labels", []), list):
        raise _ConfigError(f"{where}: labels must be a list")
    # A quoted date loads as a string, and a datetime never compares to a date.
    if any(
        type(entry.get(key, datetime.date.min)) is not datetime.date for key in ("from", "until")
    ):
        raise _ConfigError(f"{where}: from and until must be dates")
    return rules.Rule(
        account=entry.get("account"),
        book=entry["book"],
        end=entry.get("until"),
        labels=frozenset(entry.get("labels", [])),
        start=entry.get("from"),
        text=text,
    )


def _rules(path: str) -> list[rules.Rule]:
    """Returns the rules in `path`, none if absent, or raises `_ConfigError`."""
    if not os.path.exists(path):
        return []
    loaded = _load_config(path)
    unknown = sorted(set(loaded) - {"refunds", "rules"})
    if unknown:
        raise _ConfigError(f"Unknown {_RULES_FILE} sections: {', '.join(unknown)}")
    return [_rule(i, entry) for i, entry in enumerate(loaded.get("rules", []))]


def _refunds(path: str) -> refunds.Config:
    """Returns the `[refunds]` table in `path`, or raises `_ConfigError`."""
    if not os.path.exists(path):
        return refunds.Config()
    table = _load_config(path).get("refunds", {})
    if not isinstance(table, dict):
        raise _ConfigError(f"{_RULES_FILE} [refunds] must be a table")
    unknown = sorted(set(table) - {"accounts", "labels", "prefixes"})
    if unknown:
        raise _ConfigError(f"{_RULES_FILE} [refunds]: Unknown keys: {', '.join(unknown)}")
    if not all(isinstance(table.get(key, []), list) for key in ("accounts", "labels", "prefixes")):
        raise _ConfigError(f"{_RULES_FILE} [refunds]: accounts, labels and prefixes must be lists")
    try:
        prefixes = tuple(re.compile(p, re.IGNORECASE) for p in table.get("prefixes", []))
    except TypeError as err:
        raise _ConfigError(f"{_RULES_FILE} [refunds]: prefixes must be strings") from err
    except re.error as err:
        raise _ConfigError(f"{_RULES_FILE} [refunds]: Bad prefix pattern: {err}") from err
    return refunds.Config(
        accounts=tuple(table.get("accounts", [])),
        labels=frozenset(table.get("labels", [])),
        prefixes=prefixes,
    )


def _categorize_settings(config: dict) -> categorize.Settings:
    """Returns the `[categorize]` settings, or raises `_ConfigError`."""
    table = config.get("categorize", {})
    if not isinstance(table, dict):
        raise _ConfigError("[categorize] must be a table")
    unknown = sorted(set(table) - _CATEGORIZE_KEYS)
    if unknown:
        raise _ConfigError(f"[categorize]: Unknown keys: {', '.join(unknown)}")
    settings = categorize.Settings(**table)
    if not isinstance(settings.cutoff, int | float) or not isinstance(settings.examples, int):
        raise _ConfigError("[categorize]: cutoff must be a number, examples a whole number")
    return settings


def _hooks(
    config: dict,
    answers: transfer_matcher.Answers,
    categorization: list[rules.Rule],
    refund: refunds.Config,
    categories: dict[str, str],
    suggested: dict[str, str],
) -> list:
    """Returns the beangulp hooks, in the order they must run."""
    # `donate` and the hints change only rows that are still uncategorized.
    # A row hinted first would hide from `donate`, which then keeps the export's
    # copy of it as a second transaction. The rules run last, so a transfer is
    # booked before a rule sees it. A pair that still waits for an answer is
    # not booked yet, so a rule that matches one of its legs takes it. The
    # refunds run after the rules, so a refund follows its purchase's account.
    # The approved and suggested categories run last, so they book only what
    # is still open.
    return [
        qif_sidecar.donate,
        functools.partial(transfer_hints.book, _hints(config)),
        functools.partial(transfer_matcher.book, answers),
        functools.partial(rules.book, categorization),
        functools.partial(refunds.book, refund),
        functools.partial(categorize.book, categories, suggested),
    ]


# One builder per config section. A section that is absent contributes no
# importer, which is how an institution gets turned off.
_BUILDERS = {
    "dkb": _dkb,
    "ibkr": _ibkr,
    "postfinance": _postfinance,
    "qif": _qif,
    "revolut": _revolut,
    "see": _see,
    "wise": _wise,
}


def _answers_path(config: str) -> str:
    return os.path.join(os.path.dirname(config), _ANSWERS_FILE)


def _rules_path(config: str) -> str:
    return os.path.join(os.path.dirname(config), _RULES_FILE)


def _category_answers_path(config: str) -> str:
    return os.path.join(os.path.dirname(config), _CATEGORY_ANSWERS_FILE)


def _suggestions_path(config: str) -> str:
    return os.path.join(os.path.dirname(config), _SUGGESTIONS_FILE)


def _load_config(path: str) -> dict:
    """Reads the config file, or raises `_ConfigError`."""
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except OSError as err:
        raise _ConfigError(f"Cannot read {path}: {err}") from err
    except tomllib.TOMLDecodeError as err:
        raise _ConfigError(f"Cannot parse {path}: {err}") from err


def _importers(config: dict) -> list[beangulp.Importer]:
    """Returns one importer per configured source, or raises `_ConfigError`."""
    unknown = sorted(set(config) - set(_BUILDERS) - {"categorize", "transfers"})
    if unknown:
        raise _ConfigError(f"Unknown config sections: {', '.join(unknown)}")
    result = []
    for name, build in _BUILDERS.items():
        if name in config:
            result.extend(build(config[name]))
    if not result:
        raise _ConfigError(f"No importers configured. Expected one of: {', '.join(_BUILDERS)}")
    return result


def _cli() -> click.Group:
    """Returns beangulp's CLI, with `--config` in front of it."""
    # beangulp takes its importer list at construction time, before click
    # parses anything, so the group cannot be handed a path the normal way.
    # A throwaway Ingest donates the group and its subcommands, and the
    # replaced callback puts a configured one in the context instead.
    group = beangulp.Ingest([]).cli
    group.params.append(
        click.Option(
            ["--config"],
            help="TOML file naming the accounts to import into.",
            required=True,
            type=click.Path(dir_okay=False, exists=True),
        )
    )

    @click.pass_context
    def configure(ctx: click.Context, config: str) -> None:
        try:
            loaded = _load_config(config)
            answers = transfer_matcher.load_answers(_answers_path(config))
            path = _rules_path(config)
            categories = categorize.load_answers(_category_answers_path(config))
            suggested = categorize.load_suggested(_suggestions_path(config))
            hooks = _hooks(loaded, answers, _rules(path), _refunds(path), categories, suggested)
            ctx.obj = beangulp.Ingest(_importers(loaded), hooks=hooks)
        except _ConfigError as err:
            raise click.ClickException(str(err)) from err

    group.callback = configure
    group.add_command(_categorize)
    group.add_command(_confirm_transfers)
    group.add_command(_review_ui)
    group.add_command(_unpaired)
    return group


def _load_ledger(ledger: str) -> data.Entries:
    entries, errors, _options = loader.load_file(ledger)
    # An entry the loader drops takes its leg along, which skews what pairs up.
    printer.print_errors(errors, file=sys.stderr)
    return entries


def _echo_clearing(txn: data.Transaction, posting: data.Posting, indent: str = "") -> None:
    # A QIF split carries the clearing leg next to category legs, so the
    # amount comes from the clearing posting, seen from the own account.
    own = next(p for p in txn.postings if p.account != IN_TRANSIT)
    text = " | ".join(filter(None, (txn.payee, txn.narration)))
    counterparty = txn.meta.get(META_COUNTERPARTY_ACCOUNT)
    suffix = f"  [{counterparty}]" if counterparty else ""
    click.echo(f"{indent}{txn.date}  {own.account}  {-posting.units}  {text}{suffix}")


def _txn_fields(txn: data.Transaction) -> dict[str, str]:
    return {
        "Date": str(txn.date),
        "Account": txn.postings[0].account,
        "Amount": str(txn.postings[0].units),
        "Payee": txn.payee or "",
        "Text": txn.narration or "",
        "Their acct": txn.meta.get(META_COUNTERPARTY_ACCOUNT, ""),
    }


def _rate_fields(check: transfer_review.RateCheck | None) -> dict[str, str]:
    if check is None:
        return {}
    fields = {"Rate": f"1 {check.base} = {check.implied:.4f} {check.quote}"}
    if check.market is None:
        fields["Market"] = "no rate"
        return fields
    fields["Market"] = f"1 {check.base} = {check.market:.4f} {check.quote} on {check.market_date}"
    fields["Spread"] = f"{check.spread} ({check.spread_share:.1%})"
    return fields


def _echo_columns(titles: list[str], columns: list[dict[str, str]]) -> None:
    """Echoes each column side by side, one field per row, wrapped to fit."""
    labels = [
        label
        for label in dict.fromkeys(label for column in columns for label in column)
        if any(column.get(label) for column in columns)
    ]
    label_width = max(map(len, labels)) + 2
    gap = 2
    terminal = shutil.get_terminal_size().columns
    fit = (terminal - label_width) // len(columns) - gap
    width = min(_MAX_COLUMN_WIDTH, max(_MIN_COLUMN_WIDTH, fit))

    def row(label: str, cells: list[str]) -> None:
        click.echo(
            (label.ljust(label_width) + "".join(c.ljust(width + gap) for c in cells)).rstrip()
        )

    row("", titles)
    for label in labels:
        wrapped = [textwrap.wrap(column.get(label, ""), width) or [""] for column in columns]
        for i, cells in enumerate(itertools.zip_longest(*wrapped, fillvalue="")):
            row(label if i == 0 else "", list(cells))


@click.command("confirm-transfers")
@click.argument("ledger", type=click.Path(dir_okay=False, exists=True))
@click.pass_context
def _confirm_transfers(ctx: click.Context, ledger: str) -> None:
    """Ask about each candidate transfer pair in LEDGER that has no answer.

    A pair already booked is no candidate, and one a rebuild books unasked is
    skipped. Then, for each transfer no candidate settles, ask which leg is
    its partner. The answers go to the answers file next to the config, and a
    rebuild of the ledger from its sources books the confirmed pairs.
    """
    session = transfer_review.Session(
        _answers_path(ctx.find_root().params["config"]), _load_ledger(ledger)
    )
    pairs = session.pending_pairs()
    answered = 0
    for i, pair in enumerate(pairs, start=1):
        click.echo(f"\nPair {i} of {len(pairs)}:")
        sent, received = (_txn_fields(leg.txn) for leg in pair)
        check = transfer_review.rate_check(pair, session.price_map)
        _echo_columns(["Sent", "Received"], [sent, received | _rate_fields(check)])
        choice = click.prompt(
            "Same transfer? [y]es, [n]o, [s]kip, [q]uit",
            type=click.Choice(["y", "n", "s", "q"], case_sensitive=False),
            show_choices=False,
        )
        if choice == "q":
            click.echo(f"Answered {answered} of {len(pairs)} pairs.")
            return
        if choice != "s":
            session.answer_pair(pair, choice == "y")
            answered += 1
    click.echo(f"Answered {answered} of {len(pairs)} pairs.")
    _pick_partners(session)


def _pick_partners(session: transfer_review.Session) -> None:
    """Asks for the partner of each transfer no candidate settles."""
    asked = picked = 0
    for choice in session.choices():
        options = session.open_options(choice)
        if not options:
            continue
        asked += 1
        click.echo("\nWhich leg is the partner of this transfer?")
        transfer = _txn_fields(choice.leg.txn)
        columns = [
            _txn_fields(option.txn)
            | _rate_fields(
                transfer_review.rate_check(
                    transfer_matcher.pair_of(choice.leg, option), session.price_map
                )
            )
            for option in options
        ]
        # The transfer repeats in each block, so every option sits next to it.
        per_block = max(1, shutil.get_terminal_size().columns // (_MIN_COLUMN_WIDTH + 2) - 1)
        for start in range(0, len(columns), per_block):
            block = columns[start : start + per_block]
            titles = [f"{n})" for n in range(start + 1, start + len(block) + 1)]
            _echo_columns(["Transfer", *titles], [transfer, *block])
        numbers = [str(n) for n in range(1, len(options) + 1)]
        pick = click.prompt(
            f"[1-{len(options)}], [n]one, [s]kip, [q]uit",
            type=click.Choice([*numbers, "n", "s", "q"], case_sensitive=False),
            show_choices=False,
        )
        if pick == "q":
            break
        if pick == "s":
            continue
        partner = None if pick == "n" else options[int(pick) - 1]
        session.answer_choice(choice.leg, options, partner)
        picked += partner is not None
    if asked:
        click.echo(f"Picked a partner for {picked} of {asked} transfers.")


@click.command("categorize")
@click.argument("ledger", type=click.Path(dir_okay=False, exists=True))
@click.option("--year", type=int, help="Ask and review only the rows of this year.")
@click.pass_context
def _categorize(ctx: click.Context, ledger: str, year: int | None) -> None:
    """Suggest a category for each open row in LEDGER, and ask which to book.

    The model of `[categorize]` in the config suggests. First come the sure
    suggestions, grouped by payee. Each group is approved as a whole. Then the
    rest come one by one, with a pick from the top 3. The answers go to the
    answers file next to the config, and a rebuild of the ledger books them.
    The model's suggestions are cached next to the config, so a rerun asks
    only about new rows. A rebuild books each row without an answer to its
    top suggestion, flagged `!` for review.
    """
    config = ctx.find_root().params["config"]
    answers_path = _category_answers_path(config)
    try:
        settings = _categorize_settings(_load_config(config))
        answers = categorize.load_answers(answers_path)
    except _ConfigError as err:
        raise click.ClickException(str(err)) from err
    if not settings.model:
        raise click.ClickException("[categorize] needs a model")

    def progress(done: int, total: int) -> None:
        click.echo(f"\rAsked the model about {done} of {total} rows.", nl=done == total)

    try:
        suggestions = categorize.suggest(
            _load_ledger(ledger),
            answers,
            categorize.openai_ask(settings.model, settings.effort),
            _suggestions_path(config),
            settings,
            progress,
            year,
        )
    except ImportError as err:
        raise click.ClickException(f"{err}. Install the extra: uv sync --extra categorize") from err
    except _ConfigError as err:
        raise click.ClickException(str(err)) from err
    sure, unsure = categorize.bands(suggestions, settings.cutoff)
    approved, quit = _approve_groups(answers_path, sure, unsure)
    if not quit:
        approved += _pick_categories(answers_path, unsure)
    click.echo(f"Approved {approved} of {len(suggestions)} rows. A rebuild books them.")


def _approve_groups(
    path: str, groups: list[list[categorize.Suggestion]], unsure: list[categorize.Suggestion]
) -> tuple[int, bool]:
    """Asks to approve each group, adds the declined ones to `unsure`.

    Returns how many rows were approved, and whether the person quit.
    """
    approved = 0
    for i, group in enumerate(groups, start=1):
        account = group[0].choices[0].account
        click.echo(f"\nGroup {i} of {len(groups)}: {len(group)} rows of {group[0].payee!r}")
        click.echo(f"Suggested: {account}")
        for suggestion in group[:_GROUP_SHOWN]:
            txn = suggestion.txn
            text = " | ".join(filter(None, (txn.payee, txn.narration)))
            click.echo(f"  {txn.date}  {txn.postings[0].units}  {text}")
        if len(group) > _GROUP_SHOWN:
            click.echo(f"  and {len(group) - _GROUP_SHOWN} more")
        choice = click.prompt(
            "Book all to it? [y]es, [n]o (ask one by one), [s]kip, [q]uit",
            type=click.Choice(["y", "n", "s", "q"], case_sensitive=False),
            show_choices=False,
        )
        if choice == "q":
            return approved, True
        if choice == "y":
            categorize.save_answers(path, {s.import_id: account for s in group})
            approved += len(group)
        elif choice == "n":
            unsure.extend(group)
    return approved, False


def _pick_categories(path: str, suggestions: list[categorize.Suggestion]) -> int:
    """Asks for the category of each row, from its top choices."""
    picked = 0
    for i, suggestion in enumerate(suggestions, start=1):
        click.echo()
        _echo_columns([f"Row {i} of {len(suggestions)}"], [_txn_fields(suggestion.txn)])
        for n, choice in enumerate(suggestion.choices, start=1):
            click.echo(f"  {n}) {choice.account}  {choice.probability:.0%}")
        numbers = [str(n) for n in range(1, len(suggestion.choices) + 1)]
        pick = click.prompt(
            f"[1-{len(numbers)}], [s]kip, [q]uit",
            type=click.Choice([*numbers, "s", "q"], case_sensitive=False),
            show_choices=False,
        )
        if pick == "q":
            break
        if pick != "s":
            account = suggestion.choices[int(pick) - 1].account
            categorize.save_answers(path, {suggestion.import_id: account})
            picked += 1
    return picked


@click.command("review-ui")
@click.argument("ledger", type=click.Path(dir_okay=False, exists=True))
@click.option("--port", default=8780, show_default=True, help="The local port to serve on.")
@click.option("--year", type=int, help="Review only the rows of this year.")
@click.pass_context
def _review_ui(ctx: click.Context, ledger: str, port: int, year: int | None) -> None:
    """Review the cached category suggestions for LEDGER on a local web page.

    Shows only rows that `categorize` already asked the model about, and asks
    it nothing. Answers go to the same file as in `categorize`, and a rebuild
    books them. Stops with Ctrl-C.
    """
    try:
        import uvicorn

        from pybank.web import review
    except ImportError as err:
        raise click.ClickException(f"{err}. Install the extra: uv sync --extra ui") from err
    config = ctx.find_root().params["config"]
    try:
        settings = _categorize_settings(_load_config(config))
    except _ConfigError as err:
        raise click.ClickException(str(err)) from err
    app = review.app(
        _load_ledger(ledger),
        _category_answers_path(config),
        _suggestions_path(config),
        settings.cutoff,
        year,
    )
    url = f"http://127.0.0.1:{port}"
    click.echo(f"Reviewing at {url}")
    # Opens once the server is likely up, uvicorn.run blocks until Ctrl-C.
    threading.Timer(1, webbrowser.open, [url]).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


@click.command("unpaired")
@click.argument("ledger", type=click.Path(dir_okay=False, exists=True))
def _unpaired(ledger: str) -> None:
    """List the clearing postings in LEDGER that no other one cancels."""
    entries = _load_ledger(ledger)
    legs = transfer_matcher.unpaired(entries)
    for leg in legs:
        _echo_clearing(*leg)
        others = transfer_matcher.alike(entries, leg)
        if others:
            click.echo(f"  1 of {len(others) + 1} with this amount. Any may be the one:")
            for other in others:
                _echo_clearing(*other, indent="    ")
    click.echo(f"Clearing postings without a partner: {len(legs)}")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(format=_LOG_FORMAT, level=logging.WARNING)
    beangulp.identify.FILE_TOO_LARGE_THRESHOLD = _MAX_FILE_SIZE
    # click exits rather than returning, and that is what prints usage errors.
    try:
        _cli().main(args=argv)
    except SystemExit as exit_status:
        return exit_status.code or 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
