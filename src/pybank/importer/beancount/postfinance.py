"""PostFinance CSV importers for beangulp.

The archive holds six header variants in two encodings, so columns are
matched by name and the encoding is sniffed. Only the variants carrying a
`Saldo` column yield a balance assertion, which is a minority of files.
"""

import codecs
import csv
import datetime
import decimal
import io
import logging
import os
from typing import NamedTuple

import beangulp
from beancount.core import amount, data, flags

from ... import csvfile, text
from . import identity

UNCATEGORIZED = "Expenses:Uncategorized"

DATE_COLS = ["Buchungsdatum", "Datum"]
MEMO_COLS = [
    "Buchungsdetails",
    "Bezeichnung",
    "Avisierungstext",
    "Buchungstext",
]

CATEGORY_COL = "Kategorie"
LABEL_COL = "Label"

CREDIT_PREFIX = "Gutschrift in "
DEBIT_PREFIX = "Lastschrift in "
BALANCE_PREFIX = "Saldo in "

DATE_FORMAT_ISO = "%Y-%m-%d"
DATE_FORMAT_DE = "%d.%m.%Y"

TOTAL_MEMO = "Total"

# Only the recent exports carry these, and they are the bank's guess, not a
# decision. Kept as a hint for categorization, never as the answer, and out
# of the import-id so that ids do not depend on the export format.
META_CATEGORY = "bank-category"
META_LABEL = "bank-label"

logger = logging.getLogger(__name__)


class _Row(NamedTuple):
    date: datetime.date
    memo: str
    units: amount.Amount
    balance: amount.Amount | None
    category: str | None
    label: str | None


def _read_text(filepath: str) -> str:
    """Decodes a statement. PostFinance ships either cp1252 or UTF-8 BOM."""
    with open(filepath, "rb") as f:
        raw = f.read()
    if raw.startswith(codecs.BOM_UTF8):
        return raw.decode("utf-8-sig")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


def _read(filepath: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    return csvfile.read_csv_with_header(io.StringIO(_read_text(filepath)))


def _parse_date(date_str: str) -> datetime.date:
    for fmt in (DATE_FORMAT_ISO, DATE_FORMAT_DE):
        try:
            return datetime.datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date format: {date_str!r}")


def _parse_number(number_str: str) -> decimal.Decimal:
    """Swiss format: apostrophe thousands separator, dot decimal point."""
    return decimal.Decimal(number_str.replace("'", "").replace(" ", ""))


def _canonical_number(number: decimal.Decimal) -> str:
    """Returns an amount in one shape, for hashing into an import-id.

    Exports are inconsistent about trailing zeros, and `24` and `24.00` must
    not hash differently or a re-download imports twice.
    """
    return format(number.normalize(), "f")


def _amount_with_prefix(row: dict[str, str], prefix: str) -> amount.Amount | None:
    """Returns the amount in the `<prefix><currency>` column, if filled."""
    for name, value in row.items():
        if name.startswith(prefix) and value:
            return amount.Amount(_parse_number(value), name[len(prefix) :])
    return None


def _parse_row(row: dict[str, str]) -> _Row | None:
    """Returns the parsed row, or None if it is not a transaction."""
    date_str = csvfile.get_value(row, DATE_COLS)
    memo = text.normalize_text(csvfile.get_value(row, MEMO_COLS))
    credit = _amount_with_prefix(row, CREDIT_PREFIX)
    debit = _amount_with_prefix(row, DEBIT_PREFIX)

    if not date_str or (credit is None and debit is None):
        if memo != TOTAL_MEMO:
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
        _amount_with_prefix(row, BALANCE_PREFIX),
        row.get(CATEGORY_COL) or None,
        row.get(LABEL_COL) or None,
    )


class _PostFinanceImporter(beangulp.Importer):
    """Shared logic. Checking and card differ only in how they identify."""

    # Metadata keys that must all be present for a file to be ours.
    _metadata_keys: tuple[str, ...] = ()
    # Metadata key naming the finest-grained source, hashed into import-ids.
    _source_key: str = ""

    def __init__(self, account: data.Account):
        self._account = account

    def identify(self, filepath: str) -> bool:
        if not filepath.lower().endswith(".csv"):
            return False
        try:
            metadata, rows = _read(filepath)
        except (OSError, UnicodeDecodeError, csv.Error):
            return False
        if not rows:
            return False
        if not all(key in metadata for key in self._metadata_keys):
            return False
        row = rows[0]
        return (
            csvfile.get_value(row, DATE_COLS) is not None
            and csvfile.get_value(row, MEMO_COLS) is not None
            and any(name.startswith(CREDIT_PREFIX) for name in row)
        )

    def account(self, filepath: str) -> data.Account:
        return self._account

    def extract(self, filepath: str, existing: data.Entries) -> data.Entries:
        metadata, rows = _read(filepath)
        source_id = metadata.get(self._source_key, "")

        parsed = [row for row in map(_parse_row, rows) if row is not None]
        ids = identity.import_ids(
            [
                (
                    source_id,
                    str(row.date),
                    row.memo,
                    _canonical_number(row.units.number),
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
            entries.append(self._transaction(row, entry_meta))

        balance = self._closing_balance(parsed)
        if balance is not None:
            entries.append(data.Balance(meta.copy(), *balance, None, None))
        else:
            logger.info("No balance column in %s.", os.path.basename(filepath))
        return entries

    def deduplicate(self, entries: data.Entries, existing: data.Entries) -> None:
        identity.mark_duplicates(entries, existing)

    def _transaction(self, row: _Row, meta: data.Meta) -> data.Transaction:
        postings = [
            data.Posting(self._account, row.units, None, None, None, None),
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
        self, parsed: list[_Row]
    ) -> tuple[datetime.date, data.Account, amount.Amount] | None:
        """Returns (date, account, amount) for the newest row with a Saldo.

        One assertion per statement rather than per row. The Saldo is the
        running balance after that transaction, and an assertion evaluates
        at the start of its date, so it is dated the following day.
        """
        if not parsed:
            return None
        # Statements come oldest or newest first. Walk from the newest end.
        oldest_first = parsed[0].date <= parsed[-1].date
        for row in reversed(parsed) if oldest_first else parsed:
            if row.balance is not None:
                return (
                    row.date + datetime.timedelta(days=1),
                    self._account,
                    row.balance,
                )
        return None


class CheckingImporter(_PostFinanceImporter):
    """PostFinance checking account statements."""

    _metadata_keys = ("Konto:",)
    _source_key = "Konto:"


class CreditCardImporter(_PostFinanceImporter):
    """PostFinance credit card statements.

    Several physical cards share one card account, so the card is what
    identifies the source, not the account.
    """

    _metadata_keys = ("Kartenkonto:", "Karte:")
    _source_key = "Karte:"
