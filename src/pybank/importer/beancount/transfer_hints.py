"""Books the rows that match a hint as transfers to the clearing account.

A `Hint` names an account and a text pattern that mark a row as a transfer.
`pybank-import` reads hints from the `[[transfers]]` tables of its `--config`.
`book` is the beangulp hook that applies them.
"""

import logging
import re
from typing import NamedTuple

from beancount.core import data, flags

from . import IN_TRANSIT, qif
from .hooks import Group, open_slot

CATEGORY_SOURCE_HINT = "hint"

logger = logging.getLogger(__name__)


class Hint(NamedTuple):
    """Rows on `account`, or on an account below it, whose text matches.

    The other side is always `IN_TRANSIT`.
    """

    # The statement's own account.
    account: data.Account
    # Searches the payee and the narration, joined by a space.
    text: re.Pattern


def _matches(hint: Hint, booked: data.Posting, txn: data.Transaction) -> bool:
    if booked.account != hint.account and not booked.account.startswith(hint.account + ":"):
        return False
    return bool(hint.text.search(" ".join(filter(None, [txn.payee, txn.narration]))))


def _booked(hints: list[Hint], entry: data.Directive) -> data.Directive | None:
    """Returns the entry booked to the clearing account, if a hint names it."""
    if not isinstance(entry, data.Transaction):
        return None
    booked = open_slot(entry)
    if booked is None or not any(_matches(hint, booked, entry) for hint in hints):
        return None
    meta = {**entry.meta, qif.META_CATEGORY_SOURCE: CATEGORY_SOURCE_HINT}
    contra = entry.postings[1]._replace(account=IN_TRANSIT)
    return entry._replace(meta=meta, flag=flags.FLAG_OKAY, postings=[booked, contra])


def book(hints: list[Hint], extracted: list[Group], existing: data.Entries) -> list[Group]:
    """Books every uncategorized row that matches a hint to `IN_TRANSIT`.

    There the row waits for the other leg. Run it after `qif_sidecar.donate`:
    Both hooks change only rows that are still uncategorized, so if `book` ran
    first, `donate` would skip a hinted row and keep the export's copy of it as
    a second transaction.
    """
    if not hints:
        return extracted
    result, count = [], 0
    for filepath, entries, account, importer in extracted:
        kept = []
        for entry in entries:
            hinted = _booked(hints, entry)
            count += hinted is not None
            kept.append(entry if hinted is None else hinted)
        result.append((filepath, kept, account, importer))
    logger.info("Booked %d rows to %s by hint.", count, IN_TRANSIT)
    return result
