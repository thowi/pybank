"""SEE Finance importer for beangulp.

Reads the database inside a SEE Finance document, the `.scsf` folder, at
`Database/Database.sqlite`. It holds what the app's QIF export holds, with
memos in full, and with a link from each linked transfer to its other leg.

Call `Importer`, a `qif.Importer` that reads the database instead of the
export.
"""

import collections
import contextlib
import datetime
import decimal
import logging
import pathlib
import sqlite3
from collections.abc import Iterable, Mapping

from beancount.core import data

from ... import text
from . import META_CONVERSION_ID, identity, qif, routing

_SUFFIX = ".sqlite"
_SQLITE_HEADER = b"SQLite format 3\x00"
# A column of the app's own schema, which tells its database from any other.
_LINK_COLUMN = "LinkedTransferID_UK_FK"

# `Categories.TypeNumber` values. Others are the app's own: An account's
# category, the split marker, the root of the untracked accounts.
_EXPENSE = 1
_INCOME = 2
_SPLIT = 101
# An own account the app does not track. The QIF export labels it with the
# name after `_UNTRACKED_PREFIX`, and so does this importer, so one category
# mapping serves both.
_UNTRACKED = 112
_UNTRACKED_PREFIX = "*"

_CENT = decimal.Decimal("0.01")

_TRANSACTIONS = """
    SELECT TransactionID_PK, ParentID_FK, AccountID_FK, Date, Amount, Memo,
        PayeeID_FK, CategoryID_FK, LinkedTransferID_UK_FK,
        InvestmentTransactionDetailsID_UK_FK
    FROM Transactions
    ORDER BY Date, Position, TransactionID_PK
"""

logger = logging.getLogger(__name__)


def _connect(filepath: str) -> sqlite3.Connection:
    """Opens the database read-only. The app may have it open too."""
    uri = pathlib.Path(filepath).absolute().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _number(value: float) -> decimal.Decimal:
    """Returns a stored amount in whole cents, as the app shows it."""
    # The app stores floats, and a computed one carries float noise, such as
    # 0.1 + 0.2 = 0.30000000000000004.
    return decimal.Decimal(repr(value)).quantize(_CENT)


def _date(value: float) -> datetime.date:
    # The app stores a day as noon UTC, so the UTC date is the booked day.
    return datetime.datetime.fromtimestamp(value, datetime.UTC).date()


def _labels(con: sqlite3.Connection) -> tuple[dict[str, str], dict[str, bool]]:
    """Returns the QIF label of each category, and the income flag per label.

    A label is what the QIF export writes: The category path joined by `:`,
    `[Name]` for an own account, `*Name` for an untracked one.
    """
    categories = {
        row["CategoryID_PK"]: row
        for row in con.execute(
            "SELECT CategoryID_PK, ParentID_FK, Name, TypeNumber FROM Categories"
        )
    }
    accounts = dict(con.execute("SELECT CategoryID_NN_UK_FK, Name FROM Accounts").fetchall())

    def path(category_id: str) -> str:
        row = categories[category_id]
        parent = row["ParentID_FK"]
        return f"{path(parent)}:{row['Name']}" if parent else row["Name"]

    labels, income = {}, {}
    for category_id, row in categories.items():
        kind = row["TypeNumber"]
        if category_id in accounts:
            labels[category_id] = f"[{accounts[category_id]}]"
        elif kind == _UNTRACKED:
            labels[category_id] = _UNTRACKED_PREFIX + row["Name"]
        elif kind == _SPLIT:
            labels[category_id] = qif.SPLIT_MARKER
        else:
            labels[category_id] = path(category_id)
            if kind in (_EXPENSE, _INCOME):
                income[labels[category_id]] = kind == _INCOME
    return labels, income


def _legs(
    row: sqlite3.Row, children: list[sqlite3.Row], labels: Mapping[str, str]
) -> tuple[qif.Leg, ...]:
    """Returns the split legs, or one leg carrying the whole amount."""
    total = _number(row["Amount"])
    if children:
        legs = [
            qif.Leg(
                labels.get(child["CategoryID_FK"], ""),
                text.normalize_text(child["Memo"]) or None,
                _number(child["Amount"]),
            )
            for child in children
        ]
        # An uncategorized leg for the rest keeps the transaction balanced.
        rest = total - sum(leg.number for leg in legs)
        if rest:
            logger.warning(
                "The split on %s does not add up to its total. Leaving the rest uncategorized.",
                _date(row["Date"]),
            )
            legs.append(qif.Leg("", None, rest))
        return tuple(legs)
    label = labels.get(row["CategoryID_FK"], "")
    if label == qif.SPLIT_MARKER:
        logger.warning(
            "The split on %s carries no legs. Leaving it uncategorized.", _date(row["Date"])
        )
        label = ""
    return (qif.Leg(label, None, total),)


class Importer(qif.Importer):
    """A SEE Finance database covering every account the app tracked.

    Config, category labels, metadata and booking are the QIF importer's, so
    the two are interchangeable, and `qif_sidecar.donate` folds both alike.
    """

    def identify(self, filepath: str) -> bool:
        if not filepath.lower().endswith(_SUFFIX):
            return False
        try:
            with open(filepath, "rb") as f:
                if f.read(len(_SQLITE_HEADER)) != _SQLITE_HEADER:
                    return False
            with contextlib.closing(_connect(filepath)) as con:
                columns = {row["name"] for row in con.execute("PRAGMA table_info(Transactions)")}
        except (OSError, sqlite3.Error):
            return False
        return _LINK_COLUMN in columns

    def extract(self, filepath: str, existing: data.Entries) -> data.Entries:
        """Books each transaction of a mapped account, the way `qif` does.

        A transaction linked to its other leg carries a `conversion-id` shared
        with that leg. Rows with investment details are skipped: Their cash
        alone would book a purchase of shares as spending.
        """
        with contextlib.closing(_connect(filepath)) as con:
            labels, income = _labels(con)
            accounts = {
                row["AccountID_PK"]: row
                for row in con.execute("SELECT AccountID_PK, Name, CurrencyCode FROM Accounts")
            }
            payees = dict(con.execute("SELECT PayeeID_PK, Name FROM Payees").fetchall())
            rows = con.execute(_TRANSACTIONS).fetchall()
        self._check_currencies(accounts.values())

        children = collections.defaultdict(list)
        for row in rows:
            if row["ParentID_FK"]:
                children[row["ParentID_FK"]].append(row)

        parsed: list[tuple[qif.Transaction, sqlite3.Row]] = []
        skipped: collections.Counter[str] = collections.Counter()
        investment: collections.Counter[str] = collections.Counter()
        for row in rows:
            if row["ParentID_FK"]:
                continue
            source = accounts[row["AccountID_FK"]]["Name"]
            if source not in self._targets:
                skipped[source] += 1
                continue
            if row["InvestmentTransactionDetailsID_UK_FK"]:
                investment[source] += 1
                continue
            transaction = qif.Transaction(
                date=_date(row["Date"]),
                legs=_legs(row, children[row["TransactionID_PK"]], labels),
                narration=text.normalize_text(row["Memo"]),
                number=_number(row["Amount"]),
                payee=text.normalize_text(payees.get(row["PayeeID_FK"])),
                reference=None,
                source=source,
            )
            parsed.append((transaction, row))
        for source, count in sorted(skipped.items()):
            logger.info("Skipping %d transactions of unmapped account %s.", count, source)
        for source, count in sorted(investment.items()):
            logger.warning("Skipping %d investment transactions of %s.", count, source)

        # The app's own ID survives edits to the memo, which the QIF's
        # fields do not.
        ids = identity.import_ids(
            [
                identity.IdFields(
                    str(transaction.date),
                    identity.canonical_amount(transaction.number),
                    (row["TransactionID_PK"],),
                )
                for transaction, row in parsed
            ]
        )

        meta = data.new_metadata(filepath, 0)
        entries: data.Entries = []
        for (transaction, row), import_id in zip(parsed, ids):
            entry_meta = meta.copy()
            entry_meta[identity.META_KEY] = import_id
            linked = row["LinkedTransferID_UK_FK"]
            # The transfer matcher pairs two legs sharing this before any other
            # fit. A link to a split leg stays unpaired: A split is no leg.
            if linked:
                entry_meta[META_CONVERSION_ID] = min(row["TransactionID_PK"], linked)
            entries.append(self._entry(transaction, entry_meta, income))
        self._warn_undeclared([transaction for transaction, _ in parsed], income)
        return entries

    def _check_currencies(self, accounts: Iterable[sqlite3.Row]) -> None:
        """Raises if a target's currency is not its account's in the app."""
        for row in accounts:
            target = self._targets.get(row["Name"])
            if target is not None and target.currency != row["CurrencyCode"]:
                raise routing.ConfigError(
                    f"{row['Name']!r} is in {row['CurrencyCode']}, not {target.currency}"
                )
