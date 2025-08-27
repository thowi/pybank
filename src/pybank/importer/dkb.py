import datetime
import logging
from typing import TextIO

from .. import importer
from .. import model


DATE_FORMAT_LONG = '%d.%m.%Y'
DATE_FORMAT_SHORT = '%d.%m.%y'

DATE_COLS = 'Buchungstag', 'Buchungsdatum', 'Belegdatum'
PAYEE_PAYER_COL = 'Auftraggeber / Begünstigter'
PAYER_COL = 'Zahlungspflichtige*r'
PAYEE_COL = 'Zahlungsempfänger*in'
ACC_COL = 'Kontonummer'
ROUTING_COL = 'BLZ'
AMOUNT_COLS = 'Betrag (EUR)', 'Betrag (€)'
ORIG_AMOUNT_COL = 'Ursprünglicher Betrag'
MEMO_COLS = (
    'Verwendungszweck', 'Bezeichnung', 'Avisierungstext', 'Beschreibung')

CC_PREFIXES = '4748', '4917', '499811'


logger = logging.getLogger(__name__)


def _parse_date(date_str: str) -> datetime.datetime:
    """Parse date from string in DKB format"""
    try:
        return datetime.datetime.strptime(date_str, DATE_FORMAT_LONG)
    except ValueError:
        return datetime.datetime.strptime(date_str, DATE_FORMAT_SHORT)


def _has_minimal_columns(rows: list[dict[str, str]]) -> bool:
    return (
        importer.get_value(rows[0], DATE_COLS) is not None and
        importer.get_value(rows[0], AMOUNT_COLS) is not None and
        importer.get_value(rows[0], MEMO_COLS) is not None)


class _DkbImporter(importer.Importer):
    # This base method is generic enough for both checking and credit card.
    def import_transactions(self, file: TextIO, currency: str | None = None) \
                -> list[model.Payment]:
        """Import transactions from DKB CSV file"""
        metadata, rows = importer.read_csv_with_header(file)
        # TODO: Support different currencies.

        # Get transactions.
        transactions = []
        for row in rows:
            date_str = importer.get_value(row, DATE_COLS)
            date = _parse_date(date_str)

            amount_str = importer.get_value(row, AMOUNT_COLS)
            amount = importer.parse_decimal_number(amount_str, 'de_DE')

            # Older DKB CSVs have a single column for payee and payer.
            payer_payee_str = row.get(PAYEE_PAYER_COL)
            if payer_payee_str:
                payer_payee = importer.normalize_text(payer_payee_str)
                if amount < 0:
                    payee = payer_payee
                else:
                    payer = payer_payee
            else:
                payer = importer.normalize_text(row.get(PAYER_COL))
                payee = importer.normalize_text(row.get(PAYEE_COL))

            memo_str = importer.get_value(row, MEMO_COLS)
            memo = importer.normalize_text(memo_str)

            acc = 'Account: ' + row[ACC_COL] if row.get(ACC_COL) else None
            routing = 'Routing: ' + row[ROUTING_COL] if row.get(ROUTING_COL) \
                    else None
            orig_amount = 'Original amount: ' + row[ORIG_AMOUNT_COL] \
                    if row.get(ORIG_AMOUNT_COL) else None

            memo_parts = memo, orig_amount, acc, routing
            memo = '. '.join(filter(bool, memo_parts))

            transactions.append(
                model.Payment(
                        date=date, amount=amount, payer=payer, payee=payee,
                        memo=memo))
        logger.info("Imported %d transactions." % len(transactions))
        return transactions


class DkbCheckingImporter(_DkbImporter):
    def can_import(self, file: TextIO) -> bool:
        metadata, rows = importer.read_csv_with_header(file)
        return (
            'Girokonto' in metadata and
            metadata['Girokonto'].startswith('DE6412030000') and
            _has_minimal_columns(rows))


class DkbCreditCardImporter(_DkbImporter):
    def can_import(self, file: TextIO) -> bool:
        metadata, rows = importer.read_csv_with_header(file)
        return (
            'Kreditkarte:' in metadata and
            any(metadata['Kreditkarte:'].startswith(p) for p in CC_PREFIXES) and
            _has_minimal_columns(rows))
