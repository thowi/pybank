"""Ingest entry point. Wires the importers to beangulp's CLI.

Accounts are configured in a TOML file passed as `--config`.
"""

import logging
import sys
import tomllib

import beangulp
import click

from pybank.importer.beancount import dkb, ibkr, postfinance, qif

_LOG_FORMAT = "%(message)s"


class _ConfigError(Exception):
    """The config file is missing, unreadable, or does not say enough."""


def _dkb(section: dict) -> list[beangulp.Importer]:
    # The library is EUR-only in practice, but the account decides, not us.
    currency = section.get("currency", "EUR")
    importers = []
    if "checking" in section:
        importers.append(dkb.CheckingImporter(section["checking"], currency))
    if "card" in section:
        importers.append(dkb.CreditCardImporter(section["card"], currency))
    return importers


def _ibkr(section: dict) -> list[beangulp.Importer]:
    try:
        accounts = ibkr.Accounts(**section)
    except TypeError as err:
        raise _ConfigError(f"[ibkr]: {err}") from err
    return [ibkr.Importer(accounts)]


def _postfinance(section: dict) -> list[beangulp.Importer]:
    importers = []
    if "cards" in section:
        importers.append(postfinance.CreditCardImporter(section["cards"]))
    if "checking" in section:
        importers.append(postfinance.CheckingImporter(section["checking"]))
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
    unknown = sorted(set(config) - set(_BUILDERS))
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
            ctx.obj = beangulp.Ingest(_importers(_load_config(config)))
        except _ConfigError as err:
            raise click.ClickException(str(err)) from err

    group.callback = configure
    return group


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(format=_LOG_FORMAT, level=logging.INFO)
    # click exits rather than returning, and that is what prints usage errors.
    try:
        _cli().main(args=argv)
    except SystemExit as exit_status:
        return exit_status.code or 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
