"""Shapes the beangulp hooks share."""

import beangulp
from beancount.core import data

from . import UNCATEGORIZED

# What beangulp hands to a hook, one per imported file.
Group = tuple[str, data.Entries, data.Account, beangulp.Importer]


def open_slot(
    txn: data.Transaction, open_accounts: tuple[data.Account, ...] | None = (UNCATEGORIZED,)
) -> data.Posting | None:
    """Returns the booked posting, if the other one is in `open_accounts`.

    `None` opens every account, which leaves the shape check alone.
    """
    # A statement importer books one account and leaves one posting open. Any
    # other shape already says where the money went.
    if len(txn.postings) != 2:
        return None
    booked, contra = txn.postings
    if open_accounts is not None and contra.account not in open_accounts:
        return None
    if booked.units is None:
        return None
    return booked
