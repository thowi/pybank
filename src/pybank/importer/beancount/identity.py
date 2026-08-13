"""Import identity. See docs/importing.md for the reasoning."""

import hashlib
import logging
from collections.abc import Sequence

from beancount.core import data
from beangulp import extract, similar

# We store the import ID as metadata on the entries to later identify them.
META_KEY = "import-id"
VERSION = "v1"

FIELD_SEP = "\x1f"
DIGEST_LEN = 8
SIMILAR_WINDOW_DAYS = 2

logger = logging.getLogger(__name__)


def import_ids(rows: Sequence[Sequence[str]]) -> list[str]:
    """Returns one import-id per source row, in the order given.

    Rows hashing the same get increasing occurrence indices. Two identical
    rows on one day are legitimate, two coffees at the same shop, and
    without the index the second would be silently dropped.

    :param rows: The normalized identifying fields of each source row.
    :return: The import-ids.
    """
    counts: dict[str, int] = {}
    ids = []
    for fields in rows:
        digest = hashlib.sha256(FIELD_SEP.join(fields).encode("utf-8")).hexdigest()[:DIGEST_LEN]
        occurrence = counts.get(digest, 0)
        counts[digest] = occurrence + 1
        ids.append(f"{VERSION}:{digest}:{occurrence}")
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
