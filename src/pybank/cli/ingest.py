"""The `pybank-import` command line: The beangulp CLI and the review commands.

Accounts are configured in a TOML file passed as `--config`.
"""

import itertools
import logging
import shutil
import sys
import textwrap
import threading
import webbrowser

import beangulp
import click
from beancount import loader
from beancount.core import data
from beancount.parser import printer

from pybank import config
from pybank.importer.beancount import (
    IN_TRANSIT,
    META_COUNTERPARTY_ACCOUNT,
    categorize,
    pipeline,
    routing,
    transfer_matcher,
    transfer_review,
)

# beangulp reports progress a file at a time and leaves the line open until
# the file is done, so a log record written meanwhile lands mid-line.
_LOG_FORMAT = "\n%(message)s"

# Below the minimum a transaction column wraps too much to read. Above the
# maximum the eye loses the row between two columns.
_MAX_COLUMN_WIDTH = 60
_MIN_COLUMN_WIDTH = 24

# beangulp skips any input above 8 MiB before an importer sees it. A SEE
# Finance database passes that after a few years of use.
_MAX_FILE_SIZE = 1024 * 1024 * 1024


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
            ctx.obj = pipeline.ingest(config)
        # Here a config error stops the run. Inside beangulp it skips one file.
        except routing.ConfigError as err:
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
        config.answers_path(ctx.find_root().params["config"]), _load_ledger(ledger)
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
    """Suggest a category for each open row in LEDGER, for review in review-ui.

    The model of `[categorize]` in the config suggests. The suggestions are
    cached next to the config, so a rerun asks only about new rows. A rebuild
    books each row without an answer to its top suggestion, flagged `!` for
    review.
    """
    config_path = ctx.find_root().params["config"]
    try:
        settings = config.categorize_settings(config.load(config_path))
        answers = categorize.load_answers(config.category_answers_path(config_path))
    except routing.ConfigError as err:
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
            config.suggestions_path(config_path),
            settings,
            progress,
            year,
        )
    except ImportError as err:
        raise click.ClickException(f"{err}. Install the extra: uv sync --extra categorize") from err
    except routing.ConfigError as err:
        raise click.ClickException(str(err)) from err
    click.echo(f"{len(suggestions)} open rows have a suggestion. Review them with review-ui.")


@click.command("review-ui")
@click.argument("ledger", type=click.Path(dir_okay=False, exists=True))
@click.option("--port", default=8780, show_default=True, help="The local port to serve on.")
@click.option("--year", type=int, help="Review only the rows of this year.")
@click.pass_context
def _review_ui(ctx: click.Context, ledger: str, port: int, year: int | None) -> None:
    """Review the cached category suggestions for LEDGER on a local web page.

    Shows only rows that `categorize` already asked the model about, and asks
    it nothing. Answers go to the answers file next to the config, and a
    rebuild books them. Stops with Ctrl-C.
    """
    try:
        import uvicorn

        from pybank.web import review
    except ImportError as err:
        raise click.ClickException(f"{err}. Install the extra: uv sync --extra ui") from err
    config_path = ctx.find_root().params["config"]
    try:
        settings = config.categorize_settings(config.load(config_path))
    except routing.ConfigError as err:
        raise click.ClickException(str(err)) from err
    app = review.app(
        _load_ledger(ledger),
        config.category_answers_path(config_path),
        config.suggestions_path(config_path),
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
