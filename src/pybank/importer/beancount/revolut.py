"""Revolut CSV account statement importer for beangulp.

One export covers one currency balance. Call `Importer` with the account of
each currency.
"""

import csv
import datetime
import decimal
import logging
import os
from collections.abc import Mapping
from typing import NamedTuple

import beangulp
from beancount.core import amount, data, flags
from beangulp import exceptions

from ... import csvfile, text
from . import (
    BANK_FEES,
    CATEGORY_SOURCE_STATEMENT,
    FX_FEES,
    IN_TRANSIT,
    META_BANK_TYPE,
    META_CONVERSION_ID,
    UNCATEGORIZED,
    identity,
    qif,
    routing,
)

_REQUIRED_COLS = (
    "Amount",
    "Balance",
    "Completed Date",
    "Currency",
    "Description",
    "Fee",
    "Product",
    "Started Date",
    "State",
    "Type",
)

_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
_COMPLETED = "COMPLETED"
# Older exports write types as `CARD_PAYMENT`, newer ones as `Card Payment`.
_EXCHANGE = "EXCHANGE"
# A savings product keeps a balance of its own, which no currency account holds.
_PRODUCT = "Current"

# When the row started, if on another day than it completed and booked. For a
# card payment this is the purchase date.
META_STARTED_DATE = "started-date"

# Distinguishes the fee's import-id from that of the row it came with.
_FEE_ID_MARKER = "fee"

logger = logging.getLogger(__name__)


class _Row(NamedTuple):
    balance: decimal.Decimal
    completed: datetime.datetime
    currency: str
    description: str
    fee: decimal.Decimal
    gross: decimal.Decimal
    started: datetime.datetime
    type: str

    @property
    def net(self) -> decimal.Decimal:
        return self.gross - self.fee


def _read(filepath: str) -> list[dict[str, str]]:
    _metadata, rows = csvfile.read_path_with_header(filepath, ",")
    return rows


def _currency(rows: list[dict[str, str]]) -> str:
    currencies = {row["Currency"].strip() for row in rows}
    if len(currencies) != 1:
        raise exceptions.Error(
            f"Expected one currency per Revolut statement, got {sorted(currencies)}"
        )
    return currencies.pop()


def _check_product(rows: list[dict[str, str]]) -> None:
    others = {row["Product"].strip() for row in rows} - {_PRODUCT}
    if others:
        raise exceptions.Error(
            f"Only {_PRODUCT} rows book into a currency account, got {sorted(others)}"
        )


def _type_key(value: str) -> str:
    return value.strip().upper().replace(" ", "_")


def _parse_datetime(value: str) -> datetime.datetime:
    return datetime.datetime.strptime(value.strip(), _DATETIME_FORMAT)


def _parse_number(value: str) -> decimal.Decimal:
    return decimal.Decimal(value.strip() or "0")


def _parse_row(row: dict[str, str]) -> _Row | None:
    """Returns the parsed row, or None if it never moved money."""
    state = row["State"].strip()
    if state != _COMPLETED:
        logger.debug("Skipping a %s row.", state)
        return None
    return _Row(
        balance=_parse_number(row["Balance"]),
        completed=_parse_datetime(row["Completed Date"]),
        currency=row["Currency"].strip(),
        description=text.normalize_text(row["Description"]) or "",
        fee=_parse_number(row["Fee"]),
        gross=_parse_number(row["Amount"]),
        started=_parse_datetime(row["Started Date"]),
        type=_type_key(row["Type"]),
    )


def _closing_row(rows: list[_Row]) -> _Row | None:
    """Returns the row whose balance closes the statement."""
    if not rows:
        return None
    newest = max(row.completed for row in rows)
    tied = [row for row in rows if row.completed == newest]
    # Rows sharing a timestamp give no order, the running balance does: The
    # closing row is the one no other tied row continues from.
    for row in reversed(tied):
        if not any(other is not row and other.balance - other.net == row.balance for other in tied):
            return row
    return tied[-1]


class Importer(beangulp.Importer):
    """Revolut account statements, one currency per file.

    The caller maps each currency to the account its balance books into.

    Only completed rows book. A row with a fee yields a second transaction
    that books the fee, and the row itself keeps the gross amount the other
    side of a transfer sees. An exchange between two currency balances books
    to `IN_TRANSIT` and carries a `conversion-id`, by which the transfer
    matcher pairs its legs.
    """

    def __init__(self, accounts: Mapping[str, data.Account]):
        self._accounts = dict(accounts)

    def identify(self, filepath: str) -> bool:
        if not filepath.lower().endswith(".csv"):
            return False
        try:
            rows = _read(filepath)
        except (OSError, UnicodeDecodeError, csv.Error):
            return False
        # A statement without rows names no currency, and has nothing to book.
        return bool(rows) and all(col in rows[0] for col in _REQUIRED_COLS)

    def account(self, filepath: str) -> data.Account:
        return self._account_for(_currency(_read(filepath)))

    def extract(self, filepath: str, existing: data.Entries) -> data.Entries:
        rows = _read(filepath)
        account = self._account_for(_currency(rows))
        _check_product(rows)
        parsed = [row for row in map(_parse_row, rows) if row is not None]

        ids = identity.import_ids(
            [
                identity.IdFields(
                    str(row.completed.date()),
                    identity.canonical_amount(row.gross),
                    (row.currency, row.description),
                )
                for row in parsed
            ]
        )
        fee_ids = iter(
            identity.import_ids(
                [
                    identity.IdFields(
                        str(row.completed.date()),
                        identity.canonical_amount(-row.fee),
                        (row.currency, row.description, _FEE_ID_MARKER),
                    )
                    for row in parsed
                    if row.fee
                ]
            )
        )

        meta = data.new_metadata(filepath, 0)
        entries: data.Entries = []
        for row, import_id in zip(parsed, ids):
            entries.append(self._transaction(account, row, {**meta, identity.META_KEY: import_id}))
            if row.fee:
                fee_meta = {**meta, identity.META_KEY: next(fee_ids)}
                entries.append(self._fee(account, row, fee_meta))

        closing = _closing_row(parsed)
        if closing is not None:
            date = closing.completed.date() + datetime.timedelta(days=1)
            units = amount.Amount(closing.balance, closing.currency)
            entries.append(data.Balance(meta.copy(), date, account, units, None, None))
        else:
            logger.info("No completed row in %s.", os.path.basename(filepath))
        return entries

    def deduplicate(self, entries: data.Entries, existing: data.Entries) -> None:
        identity.mark_duplicates(entries, existing)

    def _account_for(self, currency: str) -> data.Account:
        try:
            return self._accounts[currency]
        except KeyError:
            raise routing.ConfigError(
                f"No account configured for the Revolut {currency} balance. "
                f"Add it to [revolut.accounts]."
            ) from None

    def _transaction(self, account: data.Account, row: _Row, meta: data.Meta) -> data.Transaction:
        meta[META_BANK_TYPE] = row.type
        if row.started.date() != row.completed.date():
            meta[META_STARTED_DATE] = str(row.started.date())
        flag = flags.FLAG_WARNING
        contra = UNCATEGORIZED
        # Both sides of an exchange are own balances, so it is a known transfer.
        if row.type == _EXCHANGE:
            meta[qif.META_CATEGORY_SOURCE] = CATEGORY_SOURCE_STATEMENT
            # Both legs of an exchange complete at the same second.
            meta[META_CONVERSION_ID] = str(row.completed)
            flag = flags.FLAG_OKAY
            contra = IN_TRANSIT
        postings = [
            data.Posting(account, amount.Amount(row.gross, row.currency), None, None, None, None),
            data.Posting(contra, None, None, None, None, None),
        ]
        return data.Transaction(
            meta,
            row.completed.date(),
            flag,
            None,
            row.description,
            data.EMPTY_SET,
            data.EMPTY_SET,
            postings,
        )

    def _fee(self, account: data.Account, row: _Row, meta: data.Meta) -> data.Transaction:
        # A transaction of its own, so the row stays a two-posting leg that the
        # transfer matcher and the QIF sidecar can pair by its gross amount.
        meta[META_BANK_TYPE] = row.type
        meta[qif.META_CATEGORY_SOURCE] = CATEGORY_SOURCE_STATEMENT
        fee_account = FX_FEES if row.type == _EXCHANGE else BANK_FEES
        fee = amount.Amount(row.fee, row.currency)
        postings = [
            data.Posting(account, -fee, None, None, None, None),
            data.Posting(fee_account, fee, None, None, None, None),
        ]
        return data.Transaction(
            meta,
            row.completed.date(),
            flags.FLAG_OKAY,
            None,
            f"Fee: {row.description}",
            data.EMPTY_SET,
            data.EMPTY_SET,
            postings,
        )
