"""Wise (formerly TransferWise) CSV importer for beangulp.

Wise writes one statement per currency balance, newest row first. Reads the
flavor with fees split out: Each fee is a row of its own, and the main row
carries the amount the other side sees. The older export with a shorter
header reads the same way, its fee rows just reuse the main row's ID. The
flavor that folds each fee into its main row is refused: Its amounts differ,
so its rows would import a second time next to the split ones.

A conversion between two balances is one row in each currency's statement,
both under the same `BALANCE-` ID. Both legs book to `IN_TRANSIT`, where the
transfer matcher pairs them through the rate.
"""

import csv
import datetime
import decimal
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
    UNCATEGORIZED,
    identity,
    qif,
    routing,
)

_ID_COL = "TransferWise ID"
_AMOUNT_COL = "Amount"
_BALANCE_COL = "Running Balance"
_CURRENCY_COL = "Currency"
_DATE_COL = "Date"
_DESCRIPTION_COL = "Description"
_EXCHANGE_FROM_COL = "Exchange From"
_EXCHANGE_TO_COL = "Exchange To"
_FEES_COL = "Total fees"
# The counterparty, first filled column wins.
_PAYEE_COLS = ("Merchant", "Payee Name", "Payer Name")

_REQUIRED_COLS = (_AMOUNT_COL, _BALANCE_COL, _CURRENCY_COL, _DATE_COL, _ID_COL)

# Source columns kept as metadata, and the key each lands under.
_META_COLS = {
    META_BANK_TYPE: "Transaction Details Type",
    # Same key as the DKB importer. More stable than a payee name.
    "counterparty-account": "Payee Account Number",
    "exchange-rate": "Exchange Rate",
    "note": "Note",
    "payment-reference": "Payment Reference",
}

_DATE_FORMAT = "%d-%m-%Y"

# A conversion between two own balances. Card payments in another currency
# fill the exchange columns too, but carry another ID prefix.
_CONVERSION_PREFIX = "BALANCE-"
# The current export gives a fee its own ID. The older one reuses the main
# row's, and only the description tells the fee apart.
_FEE_PREFIX = "FEE-"
_FEE_MEMO = "Charges for: "

# Wise's own transaction ID, `FEE-<id>` for a fee. Stable across downloads, so
# the import-id hashes it instead of the text.
META_WISE_ID = "wise-id"


class _Row(NamedTuple):
    balance: amount.Amount
    contra: data.Account
    date: datetime.date
    meta: dict[str, str]
    narration: str | None
    payee: str | None
    units: amount.Amount
    wise_id: str


def _read(filepath: str) -> list[dict[str, str]]:
    _metadata, rows = csvfile.read_path_with_header(filepath, ",")
    return rows


def _is_fee(row: dict[str, str]) -> bool:
    wise_id = row[_ID_COL]
    return wise_id.startswith(_FEE_PREFIX) or row.get(_DESCRIPTION_COL, "").endswith(
        _FEE_MEMO + wise_id
    )


def _is_conversion(row: dict[str, str]) -> bool:
    return (
        row[_ID_COL].startswith(_CONVERSION_PREFIX)
        and bool(row.get(_EXCHANGE_FROM_COL))
        and bool(row.get(_EXCHANGE_TO_COL))
        and not _is_fee(row)
    )


def _wise_id(row: dict[str, str]) -> str:
    """Returns the row's ID in the current export's notation."""
    wise_id = row[_ID_COL]
    if _is_fee(row) and not wise_id.startswith(_FEE_PREFIX):
        return _FEE_PREFIX + wise_id
    return wise_id


def _currency(rows: list[dict[str, str]]) -> str:
    currencies = {row[_CURRENCY_COL] for row in rows}
    if len(currencies) != 1:
        raise exceptions.Error(
            f"Expected one currency per Wise statement, got {sorted(currencies)}"
        )
    return currencies.pop()


def _check_fees_split(rows: list[dict[str, str]]) -> None:
    """Raises unless every row that carries a fee has the fee row to match."""
    fees = {_wise_id(row) for row in rows if _is_fee(row)}
    for row in rows:
        charged = decimal.Decimal(row.get(_FEES_COL) or "0")
        if charged and not _is_fee(row) and _FEE_PREFIX + row[_ID_COL] not in fees:
            raise exceptions.Error(
                f"{row[_ID_COL]} carries a fee but the file has no fee row for it. This is "
                f"the export that folds fees into the amount. Download the one with fees "
                f"split out."
            )


def _parse_row(row: dict[str, str], conversions: set[str]) -> _Row:
    currency = row[_CURRENCY_COL]
    wise_id = _wise_id(row)
    if wise_id.startswith(_FEE_PREFIX):
        parent = wise_id.removeprefix(_FEE_PREFIX)
        contra = FX_FEES if parent in conversions else BANK_FEES
    elif _is_conversion(row):
        contra = IN_TRANSIT
    else:
        contra = UNCATEGORIZED
    payee = next((row[col] for col in _PAYEE_COLS if row.get(col)), None)
    meta = {key: row[col] for key, col in _META_COLS.items() if row.get(col)}
    return _Row(
        balance=amount.Amount(decimal.Decimal(row[_BALANCE_COL]), currency),
        contra=contra,
        date=datetime.datetime.strptime(row[_DATE_COL], _DATE_FORMAT).date(),
        meta=meta,
        narration=text.normalize_text(row.get(_DESCRIPTION_COL)) or None,
        payee=text.normalize_text(payee),
        units=amount.Amount(decimal.Decimal(row[_AMOUNT_COL]), currency),
        wise_id=wise_id,
    )


class Importer(beangulp.Importer):
    """Wise balance statements, one file per currency.

    The caller maps each currency to the account its balance books into.
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
        _check_fees_split(rows)
        conversions = {row[_ID_COL] for row in rows if _is_conversion(row)}
        parsed = [_parse_row(row, conversions) for row in rows]
        # One Wise ID can occur twice in a file, a transfer sent and refunded,
        # but never on the same date with the same amount.
        ids = identity.import_ids(
            [
                identity.IdFields(
                    str(row.date),
                    identity.canonical_amount(row.units.number),
                    (row.units.currency, row.wise_id),
                )
                for row in parsed
            ]
        )

        meta = data.new_metadata(filepath, 0)
        entries: data.Entries = []
        for row, import_id in zip(parsed, ids):
            entry_meta = {
                **meta,
                **row.meta,
                META_WISE_ID: row.wise_id,
                identity.META_KEY: import_id,
            }
            entries.append(self._transaction(account, row, entry_meta))

        if parsed:
            # Newest first, so the first row's balance closes the statement. A
            # fee row precedes its main row in time, never follows it. The
            # assertion evaluates at the start of its date, hence the day after.
            newest = parsed[0]
            balance_date = newest.date + datetime.timedelta(days=1)
            entries.append(
                data.Balance(meta.copy(), balance_date, account, newest.balance, None, None)
            )
        return entries

    def deduplicate(self, entries: data.Entries, existing: data.Entries) -> None:
        identity.mark_duplicates(entries, existing)

    def _account_for(self, currency: str) -> data.Account:
        try:
            return self._accounts[currency]
        except KeyError:
            raise routing.ConfigError(
                f"No account configured for the Wise {currency} balance. Add it to [wise.accounts]."
            ) from None

    def _transaction(self, account: data.Account, row: _Row, meta: data.Meta) -> data.Transaction:
        known = row.contra != UNCATEGORIZED
        if known:
            meta[qif.META_CATEGORY_SOURCE] = CATEGORY_SOURCE_STATEMENT
        postings = [
            data.Posting(account, row.units, None, None, None, None),
            data.Posting(row.contra, None, None, None, None, None),
        ]
        return data.Transaction(
            meta,
            row.date,
            flags.FLAG_OKAY if known else flags.FLAG_WARNING,
            row.payee,
            row.narration,
            data.EMPTY_SET,
            data.EMPTY_SET,
            postings,
        )
