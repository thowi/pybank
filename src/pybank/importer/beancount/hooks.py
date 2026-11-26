"""Shapes the beangulp hooks share."""

import beangulp
from beancount.core import data

from . import CATEGORY_SOURCE_SUGGESTED, UNCATEGORIZED, qif

# What beangulp hands to a hook, one per imported file.
Group = tuple[str, data.Entries, data.Account, beangulp.Importer]


def open_slot(
    txn: data.Transaction, open_accounts: tuple[data.Account, ...] | None = (UNCATEGORIZED,)
) -> data.Posting | None:
    """Returns the booked posting, if the other one is in `open_accounts`.

    A row that only holds a suggestion is open too.

    `None` opens every account, which leaves the shape check alone.
    """
    # A statement importer books one account and leaves one posting open. Any
    # other shape already says where the money went.
    if len(txn.postings) != 2:
        return None
    booked, contra = txn.postings
    suggested = txn.meta.get(qif.META_CATEGORY_SOURCE) == CATEGORY_SOURCE_SUGGESTED
    if open_accounts is not None and contra.account not in open_accounts and not suggested:
        return None
    if booked.units is None:
        return None
    return booked
