"""Ingest entry point. Wires the importers to beangulp's CLI.

Accounts are configured in a TOML file passed as `--config`.
"""

import functools
import logging
import os
import re
import sys
import tomllib

import beangulp
import click
from beancount import loader
from beancount.core import amount, data, prices
from beancount.parser import printer

from pybank.importer.beancount import (
    IN_TRANSIT,
    dkb,
    ibkr,
    postfinance,
    qif,
    qif_sidecar,
    revolut,
    routing,
    transfer_hints,
    transfer_matcher,
    wise,
)

# beangulp reports progress a file at a time and leaves the line open until
# the file is done, so a log record written meanwhile lands mid-line.
_LOG_FORMAT = "\n%(message)s"

# The answers on transfer pairs, kept next to the config file.
_ANSWERS_FILE = "transfer-pairs.toml"


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


def _qif(section: dict) -> list[beangulp.Importer]:
    targets = {}
    for name, target in section.get("targets", {}).items():
        try:
            targets[name] = qif.Target(target["account"], target["currency"])
        except (KeyError, TypeError) as err:
            raise _ConfigError(f"[qif.targets] {name!r} needs account and currency") from err
    if not targets:
        raise _ConfigError("[qif] needs at least one target, or the export imports nothing")
    return [qif.Importer(targets, section.get("categories", {}))]


def _revolut(section: dict) -> list[beangulp.Importer]:
    accounts = _accounts(section, "accounts", "revolut.accounts")
    if not accounts:
        raise _ConfigError("[revolut.accounts] must map at least one currency to an account")
    return [revolut.Importer(accounts)]


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


def _hooks(config: dict, answers: transfer_matcher.Answers) -> list:
    """Returns the beangulp hooks, in the order they must run."""
    # `donate` and the hints change only rows that are still uncategorized.
    # A row hinted first would hide from `donate`, which then keeps the export's
    # copy of it as a second transaction.
    return [
        qif_sidecar.donate,
        functools.partial(transfer_hints.book, _hints(config)),
        functools.partial(transfer_matcher.book, answers),
    ]


# One builder per config section. A section that is absent contributes no
# importer, which is how an institution gets turned off.
_BUILDERS = {
    "dkb": _dkb,
    "ibkr": _ibkr,
    "postfinance": _postfinance,
    "qif": _qif,
    "revolut": _revolut,
    "wise": _wise,
}


def _answers_path(config: str) -> str:
    return os.path.join(os.path.dirname(config), _ANSWERS_FILE)


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
    unknown = sorted(set(config) - set(_BUILDERS) - {"transfers"})
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
            ctx.obj = beangulp.Ingest(_importers(loaded), hooks=_hooks(loaded, answers))
        except _ConfigError as err:
            raise click.ClickException(str(err)) from err

    group.callback = configure
    group.add_command(_confirm_transfers)
    group.add_command(_unpaired)
    return group


def _load_ledger(ledger: str) -> data.Entries:
    entries, errors, _options = loader.load_file(ledger)
    # An entry the loader drops takes its leg along, which skews what pairs up.
    printer.print_errors(errors, file=sys.stderr)
    return entries


def _echo_leg(txn: data.Transaction, units: amount.Amount, account: data.Account) -> None:
    click.echo(f"{txn.date}  {account}  {units}  {txn.narration}")


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
    path = _answers_path(ctx.find_root().params["config"])
    entries = _load_ledger(ledger)
    price_map = prices.build_price_map(entries)
    answers = transfer_matcher.load_answers(path)
    # A leg of a confirmed pair is taken. A fee pair books its receiver beyond
    # what a leg can be, so its sender would otherwise seek a new partner.
    taken = {import_id for key, confirmed in answers.items() if confirmed for import_id in key}
    found = transfer_matcher.candidates(entries, price_map)
    # A rebuild books a sure pair in one currency. One in two currencies needs
    # prices, which `extract` may lack.
    pairs = [
        pair
        for pair in found
        if pair.key not in answers
        and pair.key.isdisjoint(taken)
        and not (
            transfer_matcher.books_unasked(pair)
            and pair.sender.units.currency == pair.receiver.units.currency
        )
    ]
    answered = 0
    for i, pair in enumerate(pairs, start=1):
        click.echo(f"\nPair {i} of {len(pairs)}:")
        for leg in pair:
            _echo_leg(leg.txn, leg.units, leg.txn.postings[0].account)
        choice = click.prompt(
            "Same transfer? [y]es, [n]o, [s]kip, [q]uit",
            type=click.Choice(["y", "n", "s", "q"], case_sensitive=False),
            show_choices=False,
        )
        if choice == "q":
            click.echo(f"Answered {answered} of {len(pairs)} pairs.")
            return
        if choice != "s":
            transfer_matcher.save_answer(path, pair, choice == "y")
            answered += 1
    click.echo(f"Answered {answered} of {len(pairs)} pairs.")
    _pick_partners(path, transfer_matcher.choices(entries, price_map), answers, taken)


def _pick_partners(
    path: str,
    choices: list[transfer_matcher.Choice],
    answers: transfer_matcher.Answers,
    taken: set[str],
) -> None:
    """Asks for the partner of each transfer no candidate settles."""
    asked = picked = 0
    for choice in choices:
        # A pick earlier in this run can take a leg, or settle every option.
        options = [
            option
            for option in choice.options
            if option.import_id not in taken
            and transfer_matcher.pair_of(choice.leg, option).key not in answers
        ]
        if choice.leg.import_id in taken or not options:
            continue
        asked += 1
        click.echo("\nWhich leg is the partner of:")
        _echo_leg(choice.leg.txn, choice.leg.units, choice.leg.txn.postings[0].account)
        for n, option in enumerate(options, start=1):
            click.echo(f"  {n}) ", nl=False)
            _echo_leg(option.txn, option.units, option.txn.postings[0].account)
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
        for n, option in enumerate(options, start=1):
            pair = transfer_matcher.pair_of(choice.leg, option)
            confirmed = pick == str(n)
            # [n]one rejects every option, so a rerun does not ask again.
            if confirmed or pick == "n":
                transfer_matcher.save_answer(path, pair, confirmed)
                answers[pair.key] = confirmed
            if confirmed:
                taken.update(pair.key)
                picked += 1
    if asked:
        click.echo(f"Picked a partner for {picked} of {asked} transfers.")


@click.command("unpaired")
@click.argument("ledger", type=click.Path(dir_okay=False, exists=True))
def _unpaired(ledger: str) -> None:
    """List the clearing postings in LEDGER that no other one cancels."""
    legs = transfer_matcher.unpaired(_load_ledger(ledger))
    for txn, posting in legs:
        # A QIF split carries the clearing leg next to category legs, so the
        # amount comes from the clearing posting, seen from the own account.
        own = next(p for p in txn.postings if p.account != IN_TRANSIT)
        _echo_leg(txn, -posting.units, own.account)
    click.echo(f"Clearing postings without a partner: {len(legs)}")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(format=_LOG_FORMAT, level=logging.WARNING)
    # click exits rather than returning, and that is what prints usage errors.
    try:
        _cli().main(args=argv)
    except SystemExit as exit_status:
        return exit_status.code or 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
