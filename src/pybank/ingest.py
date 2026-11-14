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

from pybank.importer.beancount import (
    dkb,
    ibkr,
    postfinance,
    qif,
    qif_sidecar,
    routing,
    transfer_hints,
    transfer_matcher,
)

# beangulp reports progress a file at a time and leaves the line open until
# the file is done, so a log record written meanwhile lands mid-line.
_LOG_FORMAT = "\n%(message)s"

# The answers on transfer pairs, kept next to the config file.
_ANSWERS_FILE = "transfer-pairs.toml"


# Config that only an importer can find fault with raises the same type, so
# one `except` covers a bad file and a file the config does not cover.
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
}


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
            answers = transfer_matcher.load_answers(
                os.path.join(os.path.dirname(config), _ANSWERS_FILE)
            )
            ctx.obj = beangulp.Ingest(_importers(loaded), hooks=_hooks(loaded, answers))
        except _ConfigError as err:
            raise click.ClickException(str(err)) from err

    group.callback = configure
    return group


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
