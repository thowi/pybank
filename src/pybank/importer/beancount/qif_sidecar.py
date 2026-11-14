"""Folds a QIF export into the statements that cover the same transactions.

Based on output from an older QIF exporter, whose data we want to leverage.

Used to merge a regular bank statement with data from a QIF export.
Both sources hold entries for the same transactions. We treat the bank statement
as source of truth, but augment it with categories and notes from the QIF.

`donate` is a beangulp hook. Use it to import the statements and the QIF
export in one run.
"""

import datetime
import logging
import re

import beangulp
from beancount.core import data

from . import UNCATEGORIZED, qif

# How far apart the two sources may date the same transaction.
_WINDOW = datetime.timedelta(days=5)

# A memo the export carries and the statement does not. It stays here, out of
# the narration, because the statement's own text is the better description.
META_NOTE = "qif-note"

# What counts as one word when two texts are compared. Unicode, so an umlaut
# keeps its word whole instead of splitting it in two.
_WORD = re.compile(r"[^\W_]+")

# How many of a memo's words the statement may already carry. At or above this
# the memo only rewords the statement's own text.
_MAX_OVERLAP = 0.4

# How many of a memo's words may be bare numbers. A memo built mostly of card
# and reference numbers is the bank's own text, so `4111 1111 1111 1111 CARD
# PAYMENT REF 99` is a description and `Repaid by Sam` is not.
#
# Word overlap misses these on its own. The statement puts those numbers in
# its own columns, so the two texts share no word at all.
_MAX_NUMBERS = 0.5

# The old scraper appended these labels to the memo, which the other two rules
# see as ordinary words. Each one repeats a field the statement holds in full,
# the way `Original amount:` repeats what the statement carries as
# `original-amount`.
_SCRAPER_LABELS = ("account:", "exchange rate:", "original amount:")

logger = logging.getLogger(__name__)

# What beangulp hands a hook, one per imported file.
_Group = tuple[str, data.Entries, data.Account, beangulp.Importer]

# Where a statement transaction sits, so folding can write it back.
_Slot = tuple[data.Entries, int]


def _words(value: str | None) -> set[str]:
    """Returns the words in the text, lowercased, for comparing."""
    return set(_WORD.findall((value or "").casefold()))


def open_slot(
    txn: data.Transaction, open_accounts: tuple[data.Account, ...] = (UNCATEGORIZED,)
) -> data.Posting | None:
    """Returns the booked posting, if the other one is in `open_accounts`."""
    # A statement importer books one account and leaves one posting open. Any
    # other shape already says where the money went.
    if len(txn.postings) != 2:
        return None
    booked, contra = txn.postings
    if contra.account not in open_accounts or booked.units is None:
        return None
    return booked


def _extra_note(txn: data.Transaction, exported: data.Transaction) -> str | None:
    """Returns the export's memo, if it says what the statement does not.

    The checks below rule out text a machine wrote. What survives is most
    likely a note somebody typed, which the file itself cannot prove.
    """
    memo = exported.narration
    if not memo:
        return None
    if any(label in memo.casefold() for label in _SCRAPER_LABELS):
        return None
    memo_words = _words(memo)
    if not memo_words:
        return None
    if sum(word.isdigit() for word in memo_words) / len(memo_words) >= _MAX_NUMBERS:
        return None
    # What is left can still be the bank's own text. The two sources word a
    # description differently, so shared words find the copy where an exact
    # match does not.
    statement_words = _words(" ".join(filter(None, [txn.payee, txn.narration])))
    if len(memo_words & statement_words) / len(memo_words) >= _MAX_OVERLAP:
        return None
    return memo


def _donated(txn: data.Transaction, exported: data.Transaction) -> data.Transaction:
    """Returns the statement transaction, now carrying the export's labels."""
    counters = exported.postings[1:]
    if all(posting.account == UNCATEGORIZED for posting in counters):
        return txn
    meta = dict(txn.meta)
    meta[qif.META_CATEGORY_SOURCE] = qif.CATEGORY_SOURCE_QIF
    note = _extra_note(txn, exported)
    if note:
        meta[META_NOTE] = note
    kept = [posting for posting in txn.postings if posting.account != UNCATEGORIZED]
    return txn._replace(meta=meta, flag=exported.flag, postings=[*kept, *counters])


class _Statements:
    """Statement transactions, keyed by the account and amount they book.

    A row pairs with the nearest one inside `_WINDOW` that no other row took.
    """

    def __init__(self, groups: list[_Group]):
        self._slots: dict[tuple[data.Account, data.Amount], list[_Slot]] = {}
        self._claimed: set[tuple[int, int]] = set()
        for _filepath, entries, _account, _importer in groups:
            for position, entry in enumerate(entries):
                if not isinstance(entry, data.Transaction):
                    continue
                booked = open_slot(entry)
                if booked is not None:
                    key = (booked.account, booked.units)
                    self._slots.setdefault(key, []).append((entries, position))

    def fold(self, exported: data.Transaction) -> bool:
        """Hands the row to the statement that repeats it. True if one did."""
        # The QIF importer books the account first and the legs after it.
        booked = exported.postings[0]
        slot = self._nearest(exported.date, self._slots.get((booked.account, booked.units), []))
        if slot is None:
            return False
        entries, position = slot
        self._claimed.add((id(entries), position))
        entries[position] = _donated(entries[position], exported)
        return True

    def _nearest(self, date: datetime.date, slots: list[_Slot]) -> _Slot | None:
        """Returns the closest free slot inside the window, or None."""
        # One statement transaction takes one row. Two coffees on one day are
        # two events in both sources, and stay two.
        #
        # Nothing tells two alike rows apart, so they pair in file order and
        # their categories can end up swapped. A row left without a free slot
        # stays a transaction of its own.
        best, best_distance = None, None
        for entries, position in slots:
            if (id(entries), position) in self._claimed:
                continue
            distance = abs(entries[position].date - date)
            if distance <= _WINDOW and (best_distance is None or distance < best_distance):
                best, best_distance = (entries, position), distance
        return best


def donate(extracted: list[_Group], existing: data.Entries) -> list[_Group]:
    """Drops every exported transaction a statement already covers."""
    # An importer cannot do this itself: beangulp adds a run's own entries to
    # `existing` only after every importer has extracted.
    statements = [group for group in extracted if not isinstance(group[3], qif.Importer)]
    if len(statements) == len(extracted):
        return extracted
    index = _Statements(statements)

    result, folded = [], 0
    for group in extracted:
        filepath, entries, account, importer = group
        if not isinstance(importer, qif.Importer):
            result.append(group)
            continue
        kept = [
            entry
            for entry in entries
            if not (isinstance(entry, data.Transaction) and index.fold(entry))
        ]
        folded += len(entries) - len(kept)
        result.append((filepath, kept, account, importer))
    logger.info("Folded %d exported transactions into the statements.", folded)
    return result
