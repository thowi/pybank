"""Import identity. See docs/importing.md for the reasoning."""

import decimal
import hashlib
import logging
from collections.abc import Sequence
from typing import NamedTuple

from beancount.core import data
from beangulp import extract, similar

# We store the import ID as metadata on the entries to later identify them.
META_KEY = "import-id"
VERSION = "v1"

FIELD_SEP = "\x1f"
DIGEST_LEN = 12
SIMILAR_WINDOW_DAYS = 2

logger = logging.getLogger(__name__)


class IdFields(NamedTuple):
    """The identifying fields of one source row.

    Date and amount are carried in the clear, so an ID can be read without
    re-running the import, and so a collision needs all three parts to
    match. Both are already visible in the postings below. Account and card
    numbers are not, and belong in `hashed`.
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

    Rows yielding the same ID get increasing occurrence indices. Two
    identical rows on one day are legitimate, two coffees at the same shop,
    and without the index the second would be silently dropped.

    :param rows: The normalized identifying fields of each source row.
    :return: The import-ids.
    """
    counts: dict[str, int] = {}
    ids = []
    for row in rows:
        raw = FIELD_SEP.join(row.hashed).encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()[:DIGEST_LEN]
        key = f"{VERSION}:{row.date}:{row.amount}:{digest}"
        occurrence = counts.get(key, 0)
        counts[key] = occurrence + 1
        ids.append(f"{key}:{occurrence}")
    return ids


def mark_duplicates(entries: data.Entries, existing: data.Entries) -> None:
    """Marks entries already present in the ledger, and warns on near misses.

    We store the import ID as metadata on the entries to later identify them.
    An identical ID marks a duplicate entry.

    Changing the field normalization changes every digest, so IDs stop
    matching and everything looks new. The version prefix is the recovery
    path: Old IDs stay tagged `v1`, new ones are `v2`, they cannot collide,
    and a migration can rewrite or grandfather the old generation.

    The similarity check only warns, as it might need confirmation as dupe.

    :param entries: The freshly extracted entries, marked in place.
    :param existing: The entries already in the ledger.
    """
    if not existing:
        return
    known = {entry.meta[META_KEY] for entry in existing if entry.meta and META_KEY in entry.meta}
    fresh = []
    for entry in entries:
        if entry.meta.get(META_KEY) in known:
            entry.meta[extract.DUPLICATE] = True
        else:
            fresh.append(entry)

    for entry, match in similar.find_similar_entries(
        fresh,
        sorted(existing, key=lambda e: e.date),
        window_days=SIMILAR_WINDOW_DAYS,
    ):
        logger.warning(
            "New import-id but %s %s looks like %s %s already in the ledger. "
            "Check for a re-issued statement.",
            entry.date,
            entry.narration,
            match.date,
            match.narration,
        )
