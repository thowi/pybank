"""PostFinance CSV importers for beangulp.

`CheckingImporter` reads checking account statements, `CreditCardImporter`
credit card statements.
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

from ... import csvfile, text
from . import UNCATEGORIZED, identity, routing

# Exports differ in their header columns, so a field matches by any of its
# names. `csvfile` sniffs the encoding, which differs too.
_DATE_COLS = ["Buchungsdatum", "Datum"]
_MEMO_COLS = [
    "Buchungsdetails",
    "Bezeichnung",
    "Avisierungstext",
    "Buchungstext",
]

_CATEGORY_COL = "Kategorie"
_LABEL_COL = "Label"
_RECEIPT_DATE_COL = "Einkaufsdatum"

_CREDIT_PREFIX = "Gutschrift in "
_DEBIT_PREFIX = "Lastschrift in "
_BALANCE_PREFIX = "Saldo in "

_DATE_FORMAT_ISO = "%Y-%m-%d"
_DATE_FORMAT_DE = "%d.%m.%Y"

_TOTAL_MEMO = "Total"

# Only the recent exports carry these, and they are the bank's guess, not a
# decision. Kept as a hint for categorization, never as the answer, and out
# of the import-id so that ids do not depend on the export format.
META_CATEGORY = "bank-category"
META_LABEL = "bank-label"

# Card only. The purchase date, which trails `Buchungsdatum`. Kept in the
# export's own notation, as the DKB importer keeps its own.
META_RECEIPT_DATE = "receipt-date"

logger = logging.getLogger(__name__)


class _Row(NamedTuple):
    date: datetime.date
    memo: str
    units: amount.Amount
    balance: amount.Amount | None
    category: str | None
    label: str | None
    receipt_date: str | None


def _parse_date(date_str: str) -> datetime.date:
    for fmt in (_DATE_FORMAT_ISO, _DATE_FORMAT_DE):
        try:
            return datetime.datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date format: {date_str!r}")


def _parse_number(number_str: str) -> decimal.Decimal:
    """Swiss format: Apostrophe thousands separator, dot decimal point."""
    return decimal.Decimal(number_str.replace("'", "").replace(" ", ""))


def _amount_with_prefix(row: dict[str, str], prefix: str) -> amount.Amount | None:
    """Returns the amount in the `<prefix><currency>` column, if filled."""
    for name, value in row.items():
        if name.startswith(prefix) and value:
            return amount.Amount(_parse_number(value), name[len(prefix) :])
    return None


def _parse_row(row: dict[str, str]) -> _Row | None:
    """Returns the parsed row, or None if it is not a transaction."""
    date_str = csvfile.get_value(row, _DATE_COLS)
    memo = text.normalize_text(csvfile.get_value(row, _MEMO_COLS))
    credit = _amount_with_prefix(row, _CREDIT_PREFIX)
    debit = _amount_with_prefix(row, _DEBIT_PREFIX)

    if not date_str or (credit is None and debit is None):
        if memo != _TOTAL_MEMO:
            logger.debug("Skipping row without a date or an amount.")
        return None

    if credit is not None:
        units = credit
    else:
        units = amount.Amount(-abs(debit.number), debit.currency)
    return _Row(
        _parse_date(date_str),
        memo,
        units,
        _amount_with_prefix(row, _BALANCE_PREFIX),
        row.get(_CATEGORY_COL) or None,
        row.get(_LABEL_COL) or None,
        row.get(_RECEIPT_DATE_COL) or None,
    )


class _PostFinanceImporter(beangulp.Importer):
    """Shared logic. Checking and card differ only in how they identify.

    Only exports carrying a `Saldo` column yield a balance assertion.
    """

    # Metadata keys that must all be present for a file to be ours.
    _metadata_keys: tuple[str, ...] = ()
    # Metadata key naming the finest-grained source, hashed into import-ids.
    _source_key: str = ""
    # Config table this importer takes its accounts from, named in errors.
    _config_table: str = ""

    def __init__(self, accounts: Mapping[str, data.Account]):
        self._router = routing.AccountRouter(accounts, self._config_table)

    def identify(self, filepath: str) -> bool:
        if not filepath.lower().endswith(".csv"):
            return False
        try:
            metadata, rows = csvfile.read_path_with_header(filepath)
        except (OSError, UnicodeDecodeError, csv.Error):
            return False
        if not rows:
            return False
        if not all(key in metadata for key in self._metadata_keys):
            return False
        row = rows[0]
        return (
            csvfile.get_value(row, _DATE_COLS) is not None
            and csvfile.get_value(row, _MEMO_COLS) is not None
            and any(name.startswith(_CREDIT_PREFIX) for name in row)
        )

    def account(self, filepath: str) -> data.Account:
        metadata, _ = csvfile.read_path_with_header(filepath)
        return self._account_for(metadata)

    def extract(self, filepath: str, existing: data.Entries) -> data.Entries:
        metadata, rows = csvfile.read_path_with_header(filepath)
        account = self._account_for(metadata)
        source_id = metadata.get(self._source_key, "")

        parsed = [row for row in map(_parse_row, rows) if row is not None]
        ids = identity.import_ids(
            [
                identity.IdFields(
                    str(row.date),
                    identity.canonical_amount(row.units.number),
                    (source_id, row.memo),
                )
                for row in parsed
            ]
        )

        meta = data.new_metadata(filepath, 0)
        entries: data.Entries = []
        for row, import_id in zip(parsed, ids):
            entry_meta = meta.copy()
            entry_meta[identity.META_KEY] = import_id
            if row.category:
                entry_meta[META_CATEGORY] = row.category
            if row.label:
                entry_meta[META_LABEL] = row.label
            if row.receipt_date:
                entry_meta[META_RECEIPT_DATE] = row.receipt_date
            entries.append(self._transaction(account, row, entry_meta))

        balance = self._closing_balance(account, parsed)
        if balance is not None:
            entries.append(data.Balance(meta.copy(), *balance, None, None))
        else:
            logger.info("No row carries a Saldo in %s.", os.path.basename(filepath))
        return entries

    def deduplicate(self, entries: data.Entries, existing: data.Entries) -> None:
        identity.mark_duplicates(entries, existing)

    def _account_for(self, metadata: Mapping[str, str]) -> data.Account:
        return self._router.account_for(metadata.get(self._source_key, ""))

    def _transaction(self, account: data.Account, row: _Row, meta: data.Meta) -> data.Transaction:
        postings = [
            data.Posting(account, row.units, None, None, None, None),
            data.Posting(UNCATEGORIZED, None, None, None, None, None),
        ]
        return data.Transaction(
            meta,
            row.date,
            flags.FLAG_WARNING,
            None,
            row.memo,
            data.EMPTY_SET,
            data.EMPTY_SET,
            postings,
        )

    def _closing_balance(
        self, account: data.Account, parsed: list[_Row]
    ) -> tuple[datetime.date, data.Account, amount.Amount] | None:
        """Returns the assertion for the newest row carrying a Saldo."""
        # One assertion per statement rather than per row. The Saldo is the
        # running balance after that transaction, and an assertion evaluates at
        # the start of its date, so it is dated the following day.
        if not parsed:
            return None
        # Statements come oldest or newest first. Walk from the newest end.
        oldest_first = parsed[0].date <= parsed[-1].date
        if parsed[0].date == parsed[-1].date and len(parsed) > 1:
            # One date gives no order, the running balance does: Oldest first,
            # the second Saldo is the first plus the second row's amount.
            first, second = parsed[0].balance, parsed[1].balance
            if first is not None and second is not None:
                oldest_first = second.number == first.number + parsed[1].units.number
        for row in reversed(parsed) if oldest_first else parsed:
            if row.balance is not None:
                return (
                    row.date + datetime.timedelta(days=1),
                    account,
                    row.balance,
                )
        return None


class CheckingImporter(_PostFinanceImporter):
    """PostFinance checking account statements."""

    _config_table = "postfinance.checking"
    _metadata_keys = ("Konto:",)
    _source_key = "Konto:"


class CreditCardImporter(_PostFinanceImporter):
    """PostFinance credit card statements.

    One export covers one card, and several cards can share one card account,
    so the caller maps each card to the account it books into.
    """

    _config_table = "postfinance.card"
    _metadata_keys = ("Kartenkonto:", "Karte:")
    # The card, not the card account, is the finest-grained source.
    _source_key = "Karte:"
