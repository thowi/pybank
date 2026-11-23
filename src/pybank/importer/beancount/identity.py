"""Import identity, which keeps a source row from booking twice.

An import-id identifies a source row across imports. Call `import_ids` to
assign it, and `mark_duplicates` to find what the ledger already holds. See
docs/importing.md for the reasoning.
"""

import decimal
import hashlib
import logging
from collections.abc import Sequence
from typing import NamedTuple

from beancount.core import data
from beangulp import extract, similar

# We store the import ID as metadata on the entries to later identify them.
META_KEY = "import-id"

# Changing the field normalization changes every digest, so IDs stop matching
# and everything looks new. This prefix is the recovery path: Old IDs stay
# tagged `v1`, new ones are `v2`, they cannot collide, and a migration can
# rewrite or grandfather the old generation.
VERSION = "v1"

_FIELD_SEP = "\x1f"
_DIGEST_LEN = 12
_SIMILAR_WINDOW_DAYS = 2

logger = logging.getLogger(__name__)


# Date and amount stay readable so an ID can be read without re-running the
# import, and so a collision needs all three parts to match. Both are already
# visible in the postings anyway.
class IdFields(NamedTuple):
    """The identifying fields of one source row.

    Date and amount are carried in the clear. Account and card numbers are
    not, and belong in `hashed`.
    """

    date: str
    amount: str
    hashed: Sequence[str]


def canonical_amount(number: decimal.Decimal) -> str:
    """Returns an amount in a consistent format for use in an import-id."""
    # Exports are inconsistent about trailing zeros, and `24` and `24.00` must
    # not yield different IDs or a re-download imports twice.
    return format(number.normalize(), "f")


def import_ids(rows: Sequence[IdFields]) -> list[str]:
    """Returns one import-id per source row, in the order given.

    Rows yielding the same ID get increasing occurrence indices. They count
    within one call, so pass all rows of one statement together.
    """
    # Two identical rows on one day are legitimate, two coffees at the same
    # shop, and without the index the second would be silently dropped.
    counts: dict[str, int] = {}
    ids = []
    for row in rows:
        raw = _FIELD_SEP.join(row.hashed).encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()[:_DIGEST_LEN]
        key = f"{VERSION}:{row.date}:{row.amount}:{digest}"
        occurrence = counts.get(key, 0)
        counts[key] = occurrence + 1
        ids.append(f"{key}:{occurrence}")
    return ids


def mark_duplicates(entries: data.Entries, existing: data.Entries) -> None:
    """Marks entries already in the ledger, in place, and warns on near misses.

    An entry whose `import-id` is already present is marked a duplicate, and
    so is a balance the ledger already asserts. A near miss only warns, since
    it may well be a separate transaction.
    """
    if not existing:
        return
    known = {entry.meta[META_KEY] for entry in existing if entry.meta and META_KEY in entry.meta}
    # Balances carry no import-id. A re-import would assert the same one again.
    known_balances = {_balance_key(entry) for entry in existing if isinstance(entry, data.Balance)}
    fresh = []
    for entry in entries:
        if entry.meta.get(META_KEY) in known or (
            isinstance(entry, data.Balance) and _balance_key(entry) in known_balances
        ):
            entry.meta[extract.DUPLICATE] = True
        else:
            fresh.append(entry)

    for entry, match in similar.find_similar_entries(
        fresh,
        sorted(existing, key=lambda e: e.date),
        cmp=_similar,
        window_days=_SIMILAR_WINDOW_DAYS,
    ):
        logger.warning(
            "New import-id but %s %s looks like %s %s already in the ledger. "
            "Check for a re-issued statement.",
            entry.date,
            entry.narration,
            match.date,
            match.narration,
        )


def _balance_key(entry: data.Balance) -> tuple:
    return entry.date, entry.account, entry.amount


_heuristic = similar.heuristic_comparator()


def _similar(entry: data.Directive, existing: data.Directive) -> bool:
    # A fresh entry's open contra leg would fail the heuristic's account-subset
    # check against a categorized twin, so only its booked legs are compared.
    if isinstance(entry, data.Transaction):
        entry = entry._replace(postings=[p for p in entry.postings if p.units is not None])
    return _heuristic(entry, existing)
