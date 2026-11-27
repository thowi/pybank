"""Builds a beangulp run from the config: The importers and the hooks.

Call `ingest` with the path of the config file. A front end runs the result
through its `cli`, or through its `importers` and `hooks`.
"""

import functools

import beangulp

from pybank import config

from . import (
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
    wise,
)


def _accounts(section: dict, key: str, table: str) -> dict | None:
    """Returns the fragment-to-account table under `key`, if it is there."""
    accounts = section.get(key)
    if accounts is None:
        return None
    if not isinstance(accounts, dict):
        raise routing.ConfigError(
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
        raise routing.ConfigError(f"[ibkr]: {err}") from err
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
            raise routing.ConfigError(
                f"[{table}.targets] {name!r} needs account and currency"
            ) from err
    if not targets:
        raise routing.ConfigError(
            f"[{table}] needs at least one target, or the export imports nothing"
        )
    return targets


def _qif(section: dict) -> list[beangulp.Importer]:
    return [qif.Importer(_qif_targets(section, "qif"), section.get("categories", {}))]


def _revolut(section: dict) -> list[beangulp.Importer]:
    accounts = _accounts(section, "accounts", "revolut.accounts")
    if not accounts:
        raise routing.ConfigError("[revolut.accounts] must map at least one currency to an account")
    return [revolut.Importer(accounts)]


def _see(section: dict) -> list[beangulp.Importer]:
    # The database holds what the QIF export holds, so the config is the same.
    return [see.Importer(_qif_targets(section, "see"), section.get("categories", {}))]


def _wise(section: dict) -> list[beangulp.Importer]:
    accounts = _accounts(section, "accounts", "wise.accounts")
    if not accounts:
        raise routing.ConfigError("[wise.accounts] must map at least one currency to an account")
    return [wise.Importer(accounts)]


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


def _importers(loaded: dict) -> list[beangulp.Importer]:
    """Returns one importer per configured source.

    Raises `routing.ConfigError` on a bad section.
    """
    unknown = sorted(set(loaded) - set(_BUILDERS) - {"categorize", "transfers"})
    if unknown:
        raise routing.ConfigError(f"Unknown config sections: {', '.join(unknown)}")
    result = []
    for name, build in _BUILDERS.items():
        if name in loaded:
            result.extend(build(loaded[name]))
    if not result:
        raise routing.ConfigError(
            f"No importers configured. Expected one of: {', '.join(_BUILDERS)}"
        )
    return result


def _hooks(
    hints: list[transfer_hints.Hint],
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
        functools.partial(transfer_hints.book, hints),
        functools.partial(transfer_matcher.book, answers),
        functools.partial(rules.book, categorization),
        functools.partial(refunds.book, refund),
        functools.partial(categorize.book, categories, suggested),
    ]


def ingest(config_path: str) -> beangulp.Ingest:
    """Returns the beangulp run for this config file.

    Raises `routing.ConfigError` on a bad config, rules or answers file.
    """
    loaded = config.load(config_path)
    rules_path = config.rules_path(config_path)
    hooks = _hooks(
        config.hints(loaded),
        transfer_matcher.load_answers(config.answers_path(config_path)),
        config.load_rules(rules_path),
        config.load_refunds(rules_path),
        categorize.load_answers(config.category_answers_path(config_path)),
        categorize.load_suggested(config.suggestions_path(config_path)),
    )
    return beangulp.Ingest(_importers(loaded), hooks=hooks)
