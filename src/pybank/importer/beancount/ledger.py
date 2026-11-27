"""Changes to the ledger files themselves, next to the lines they relate to.

Call `open_account` to add a category to the chart of accounts.
"""

import collections
import re

from beancount.core import account as account_lib
from beancount.core import data

from . import UNCATEGORIZED

_ROOTS = ("Expenses", "Income")


def _shared_levels(a: data.Account, b: data.Account) -> int:
    count = 0
    for x, y in zip(account_lib.split(a), account_lib.split(b), strict=False):
        if x != y:
            break
        count += 1
    return count


def open_account(entries: data.Entries, account: data.Account) -> data.Open:
    """Writes an `open` line for the category `account`, and returns it.

    The line goes into the file of its closest relatives, next to them, with
    the earliest date among them and `UNCATEGORIZED`. Raises `ValueError`,
    with a message for the user, if the name is no valid category, is in the
    ledger already, or has no open relative.
    """
    if not account_lib.is_valid(account) or account_lib.root(1, account) not in _ROOTS:
        raise ValueError(f"Not a category name: {account}")
    opens = [e for e in entries if isinstance(e, data.Open)]
    if any(e.account == account for e in opens):
        raise ValueError(f"Already in the ledger: {account}")
    best = max((_shared_levels(e.account, account) for e in opens), default=0)
    if not best:
        raise ValueError(f"No open account under {account_lib.root(1, account)}")
    relatives = [e for e in opens if _shared_levels(e.account, account) == best]
    # Relatives in several files: The file that holds most of them.
    files = collections.Counter(e.meta["filename"] for e in relatives)
    filename = files.most_common(1)[0][0]
    names = {e.account for e in relatives if e.meta["filename"] == filename}
    # Every row under review books to `UNCATEGORIZED`, so a row from before
    # all relatives still falls after the new account's date.
    uncategorized = [e for e in opens if e.account == UNCATEGORIZED]
    date = min(e.date for e in relatives + uncategorized)

    with open(filename, encoding="utf-8", newline="") as f:
        lines = f.readlines()
    pattern = re.compile(r"\d{4}-\d{2}-\d{2}\s+open\s+(\S+)")
    found = [
        (i, m[1]) for i, line in enumerate(lines) if (m := pattern.match(line)) and m[1] in names
    ]
    if not found:
        raise ValueError(f"No open line of {min(names)} in {filename}")
    children = [i for i, name in found if name.startswith(account + ":")]
    if children:
        # A parent goes above its first child.
        at = children[0]
    else:
        at = found[-1][0] + 1
        # Past the metadata lines of the last relative.
        while at < len(lines) and lines[at][:1] in (" ", "\t") and lines[at].strip():
            at += 1
    if at and not lines[at - 1].endswith("\n"):
        lines[at - 1] += "\n"
    lines.insert(at, f"{date} open {account}\n")
    with open(filename, "w", encoding="utf-8", newline="") as f:
        f.writelines(lines)
    return data.Open(data.new_metadata(filename, at + 1), date, account, None, None)
