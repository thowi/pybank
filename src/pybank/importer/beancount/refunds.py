"""Tags refunds and links them to the original purchase.

A row is open while its counter posting is on `UNCATEGORIZED`. A refund is
money in on an open row, either on one of the configured accounts (cards,
where money in is nearly always a refund) or with one of the configured
labels, the categories an export carries. Its purchase is money out on the
same account, from the same merchant, a little earlier, for at least as
much. It can be split over several accounts, its parts. `book` is the
beangulp hook that finds them.
"""

import datetime
import decimal
import hashlib
import logging
import re
from typing import NamedTuple

from beancount.core import data, flags
from beangulp import extract

from . import UNCATEGORIZED, identity, qif
from .hooks import Group, open_slot

CATEGORY_SOURCE_REFUND = "refund"

TAG_REFUND = "refund"

logger = logging.getLogger(__name__)

# A shop typically sends the money back within a few months.
_WINDOW = datetime.timedelta(days=120)

# A card refund of a foreign purchase converts at the rate of its own day, so
# it can come out slightly different from the purchase.
_TOLERANCE = decimal.Decimal("1.03")

# Some shops round a refund. Smaller than `_TOLERANCE`, since it picks one of
# several purchases.
_SAME = decimal.Decimal("0.01")

# Stands in for the merchant's name. Skips short words like "12" or "AG".
_WORD = re.compile(r"[^\W\d_]\w{2,}")


class Config(NamedTuple):
    """Which open money-in rows count as refunds, and how to read merchants."""

    # Money in on these accounts, incl. child accounts.
    accounts: tuple[data.Account, ...] = ()
    # Categories in an export that mark a refund on any account.
    labels: frozenset[str] = frozenset()
    # Text to cut in front of the merchant's name, such as a return marker or
    # a payment processor. Several may follow each other.
    prefixes: tuple[re.Pattern, ...] = ()


def _merchant(config: Config, txn: data.Transaction) -> str | None:
    """Returns the merchant's first word, in lower case."""
    text = " ".join(filter(None, [txn.payee, txn.narration])).strip()
    # An empty match cuts nothing, so it ends the loop too.
    while end := max((m.end() for p in config.prefixes if (m := p.match(text))), default=0):
        text = text[end:].lstrip()
    match = _WORD.search(text)
    return match.group(0).lower() if match else None


def _is_refund(config: Config, txn: data.Transaction) -> bool:
    if txn.meta.get(extract.DUPLICATE):
        return False
    # A row that a rule booked is no longer open.
    booked = open_slot(txn)
    if booked is None or booked.units.number <= 0:
        return False
    if any(booked.account == a or booked.account.startswith(f"{a}:") for a in config.accounts):
        return True
    return (txn.postings[1].meta or {}).get(qif.META_QIF_CATEGORY) in config.labels


class _Key(NamedTuple):
    account: data.Account
    currency: str
    merchant: str | None


def _key(config: Config, txn: data.Transaction) -> _Key:
    units = txn.postings[0].units
    return _Key(txn.postings[0].account, units.currency, _merchant(config, txn))


def _purchases(config: Config, entries: data.Entries) -> dict[_Key, list[data.Transaction]]:
    """Returns the money-out rows to an expense, by `_key`."""
    result: dict[_Key, list[data.Transaction]] = {}
    for entry in entries:
        if not isinstance(entry, data.Transaction) or len(entry.postings) < 2:
            continue
        if entry.meta.get(extract.DUPLICATE):
            continue
        booked, *counters = entry.postings
        # A transfer out is no purchase, and a refund must not book to it.
        if not all(c.account.startswith("Expenses:") for c in counters):
            continue
        if booked.units is not None and booked.units.number < 0:
            result.setdefault(_key(config, entry), []).append(entry)
    return result


def _candidates(
    config: Config, refund: data.Transaction, purchases: dict[_Key, list[data.Transaction]]
) -> list[data.Transaction]:
    """Returns the purchases that `refund` can belong to."""
    key = _key(config, refund)
    # With no merchant word, only the amount would match.
    if key.merchant is None:
        return []
    return [
        p
        for p in purchases.get(key, [])
        if refund.date - _WINDOW <= p.date <= refund.date
        and _paid(p) * _TOLERANCE >= _received(refund)
    ]


def _paid(purchase: data.Transaction) -> decimal.Decimal:
    return -purchase.postings[0].units.number


def _received(refund: data.Transaction) -> decimal.Decimal:
    return refund.postings[0].units.number


def _is_close(paid: decimal.Decimal, received: decimal.Decimal) -> bool:
    return abs(paid - received) <= paid * _SAME


def _parts(refund: data.Transaction, purchase: data.Transaction) -> list[data.Account]:
    """Returns the accounts of the purchase's parts with the refund's amount."""
    _, *counters = purchase.postings
    if len(counters) == 1:
        # An open counter posting has no amount of its own.
        parts = [(counters[0].account, _paid(purchase))]
    else:
        currency = refund.postings[0].units.currency
        parts = [
            (c.account, c.units.number)
            for c in counters
            if c.units is not None and c.units.currency == currency
        ]
    return [account for account, paid in parts if _is_close(paid, _received(refund))]


def _pairs(
    config: Config,
    refunds: list[data.Transaction],
    purchases: dict[_Key, list[data.Transaction]],
) -> list[tuple[data.Transaction, data.Transaction]]:
    """Returns each refund that has one clear purchase, with that purchase."""
    # From the clearest sign to the weakest.
    steps = (
        lambda r, p: _paid(p) == _received(r),
        lambda r, p: _is_close(_paid(p), _received(r)),
        lambda r, p: bool(_parts(r, p)),
        lambda r, p: True,
    )
    candidates = {id(r): _candidates(config, r, purchases) for r in refunds}
    claimed = set()
    found = {}
    for fits in steps:
        for refund in sorted(refunds, key=lambda r: r.date):
            if id(refund) in found:
                continue
            clear = [p for p in candidates[id(refund)] if id(p) not in claimed and fits(refund, p)]
            if len(clear) != 1:
                continue
            (purchase,) = clear
            found[id(refund)] = refund, purchase
            # A full refund uses up its purchase.
            if _is_close(_paid(purchase), _received(refund)):
                claimed.add(id(purchase))
    return list(found.values())


def _overdrawn(pairs: list[tuple[data.Transaction, data.Transaction]]) -> set[int]:
    """Returns the ids of the purchases whose refunds exceed them together."""
    left = {id(p): _paid(p) * _TOLERANCE for _, p in pairs}
    for refund, purchase in pairs:
        left[id(purchase)] -= _received(refund)
    return {key for key, number in left.items() if number < 0}


def _link(purchase: data.Transaction) -> str:
    # A link allows no colon, which the import-id holds. Its hash keeps the
    # link stable across rebuilds.
    key = purchase.meta.get(identity.META_KEY) or f"{purchase.date}{purchase.narration}"
    return f"refund-{purchase.date}-{hashlib.sha1(key.encode()).hexdigest()[:8]}"


def _booked(refund: data.Transaction, purchase: data.Transaction | None) -> data.Transaction:
    txn = refund._replace(tags=refund.tags | {TAG_REFUND})
    if purchase is None:
        return txn
    txn = txn._replace(links=txn.links | {_link(purchase)})
    accounts = set(_parts(refund, purchase))
    if len(accounts) != 1 or UNCATEGORIZED in accounts:
        return txn
    booked, counter = txn.postings
    meta = {**txn.meta, qif.META_CATEGORY_SOURCE: CATEGORY_SOURCE_REFUND}
    counter = counter._replace(account=accounts.pop())
    return txn._replace(meta=meta, flag=flags.FLAG_OKAY, postings=[booked, counter])


def book(config: Config, extracted: list[Group], existing: data.Entries) -> list[Group]:
    """Tags each refund, links it to its purchase, and books it there.

    A refund with one clear purchase gets a link to it. If it has the same
    amount as the purchase, or as one part of it, it also books to that
    account, so the two cancel. A refund of any other amount stays open, and
    so does the refund of an open purchase. A refund with no clear purchase
    only gets the tag. So do all refunds of a purchase that they exceed
    together. "The same amount" allows a small difference.

    Run it after the rules, so a refund follows the account they gave its
    purchase. A refund row that a rule booked gets no tag and no link. A
    purchase already in the ledger gets no link, only its refund does.
    """
    if not config.accounts and not config.labels:
        return extracted
    new = [e for _, group, _, _ in extracted for e in group]
    # beangulp's existing entries also hold every row this run extracted,
    # including the rows an earlier hook dropped.
    files = {filepath for filepath, *_ in extracted}
    known = [e for e in existing if e.meta and e.meta.get("filename") not in files]
    purchases = _purchases(config, new + known)
    tagged = [e for e in new if isinstance(e, data.Transaction) and _is_refund(config, e)]
    pairs = _pairs(config, tagged, purchases)
    # At least one of the refunds belongs elsewhere, and nothing shows which.
    overdrawn = _overdrawn(pairs)
    refunds = dict.fromkeys(map(id, tagged))
    refunds.update((id(e), p) for e, p in pairs if id(p) not in overdrawn)
    found = [p for p in refunds.values() if p is not None]
    linked = {id(p): _link(p) for p in found}
    booked = 0
    result = []
    # A hook can change only the imported rows, not the ledger.
    for filepath, group, account, importer in extracted:
        kept = []
        for entry in group:
            if id(entry) in refunds:
                entry = _booked(entry, refunds[id(entry)])
                booked += entry.meta.get(qif.META_CATEGORY_SOURCE) == CATEGORY_SOURCE_REFUND
            elif id(entry) in linked:
                entry = entry._replace(links=entry.links | {linked[id(entry)]})
            kept.append(entry)
        result.append((filepath, kept, account, importer))
    logger.info(
        "Tagged %d refunds, linked %d to a purchase, booked %d.",
        len(refunds),
        len(found),
        booked,
    )
    return result
