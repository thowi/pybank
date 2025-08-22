import datetime
import io
import logging

from .. import importer
from .. import model


DATE_FORMAT_ISO = '%Y-%m-%d'
DATE_FORMAT_DE = '%d.%m.%Y'

logger = logging.getLogger(__name__)


def _parse_date(date_str: str) -> datetime.datetime:
    try:
        return datetime.datetime.strptime(date_str, DATE_FORMAT_ISO)
    except ValueError:
        return datetime.datetime.strptime(date_str, DATE_FORMAT_DE)


def _parse_float(string: str) -> float:
    return importer.parse_decimal_number(string, 'de_CH')


class _PostFinanceImporter(importer.Importer):
    # This base method is generic enough for both checking and credit card.
    def import_transactions(
            self,
            file: io.IOBase | None = None,
            filename: str | None = None,
            currency: str | None = None) -> list[model.Payment]:
        metadata, rows = importer.read_csv_with_header(file, filename)
        # TODO: Support different currencies.
        currency = 'CHF'
        credit_col = 'Gutschrift in ' + currency
        debit_col = 'Lastschrift in ' + currency
        category_col = 'Kategorie'

        # Get transactions.
        transactions = []
        for row in rows:
            date_str = row.get('Buchungsdatum') or row.get('Datum')
            date = _parse_date(date_str)

            credit = _parse_float(row[credit_col]) if row.get(credit_col) \
                    else None
            debit = -abs(_parse_float(row[debit_col])) if row.get(debit_col) \
                    else None
            amount = credit if credit else debit

            memo_str = row.get('Buchungsdetails') or row.get('Bezeichnung') or \
                    row.get('Avisierungstext')
            memo = importer.normalize_text(memo_str)

            category = row.get(category_col)

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


class PostFinanceCreditCardImporter(_PostFinanceImporter):
    """Importer for PostFinance credit cards (http://www.postfincance.ch/).
    """
