import datetime
import io
import logging
from typing import TextIO

from .. import importer
from .. import model


DATE_FORMAT_ISO = '%Y-%m-%d'
DATE_FORMAT_DE = '%d.%m.%Y'

CURRENCY = 'CHF'
DATE_COLS = 'Buchungsdatum', 'Datum'
CREDIT_COL = 'Gutschrift in ' + CURRENCY
DEBIT_COL = 'Lastschrift in ' + CURRENCY
MEMO_COLS = 'Buchungsdetails', 'Bezeichnung', 'Avisierungstext', 'Buchungstext'
AMOUNT_COLS = CREDIT_COL, DEBIT_COL
CATEGORY_COL = 'Kategorie'

logger = logging.getLogger(__name__)


def _parse_date(date_str: str) -> datetime.datetime:
    try:
        return datetime.datetime.strptime(date_str, DATE_FORMAT_ISO)
    except ValueError:
        return datetime.datetime.strptime(date_str, DATE_FORMAT_DE)


def _parse_float(string: str) -> float:
    return importer.parse_decimal_number(string, 'de_CH')


def _has_minimal_columns(rows: list[dict[str, str]]) -> bool:
    return (
        importer.get_value(rows[0], DATE_COLS) is not None and
        importer.get_value(rows[0], AMOUNT_COLS) is not None and
        importer.get_value(rows[0], MEMO_COLS) is not None)


class _PostFinanceImporter(importer.Importer):
    # This base method is generic enough for both checking and credit card.
    def import_transactions(self, file: TextIO, currency: str | None = None) \
            -> list[model.Payment]:
        metadata, rows = importer.read_csv_with_header(file)
        # TODO: Support different currencies.

        # Get transactions.
        transactions = []
        for row in rows:
            date_str = importer.get_value(row, DATE_COLS)
            date = _parse_date(date_str)

            credit = _parse_float(row[CREDIT_COL]) if row.get(CREDIT_COL) \
                    else None
            debit = -abs(_parse_float(row[DEBIT_COL])) if row.get(DEBIT_COL) \
                    else None
            amount = credit if credit else debit

            memo_str = importer.get_value(row, MEMO_COLS)
            memo = importer.normalize_text(memo_str)

            category = row.get(CATEGORY_COL)

            # Skip "Total" row.
            if memo == 'Total' and not amount:
                continue

            transactions.append(
                model.Payment(
                        date=date, amount=amount, memo=memo, category=category))
        logger.info("Imported %d transactions." % len(transactions))
        return transactions


class PostFinanceCheckingImporter(_PostFinanceImporter):
    """Importer for PostFinance checking accounts (http://www.postfincance.ch/).
    """
    def can_import(self, file: TextIO) -> bool:
        metadata, rows = importer.read_csv_with_header(file)
        return (
            'Konto:' in metadata and
            metadata['Konto:'].startswith('CH') and
            _has_minimal_columns(rows))


class PostFinanceCreditCardImporter(_PostFinanceImporter):
    """Importer for PostFinance credit cards (http://www.postfincance.ch/).
    """
    def can_import(self, file: TextIO) -> bool:
        metadata, rows = importer.read_csv_with_header(file)
        return (
            'Kartenkonto:' in metadata and
            'Karte:' in metadata and
            metadata['Karte:'].startswith('XXXX') and
            _has_minimal_columns(rows))
