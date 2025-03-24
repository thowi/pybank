import datetime
import logging

import importer
import model

DATE_FORMAT_ISO = '%Y-%m-%d'
DATE_FORMAT_DE = '%d.%m.%Y'

logger = logging.getLogger(__name__)


def _parse_date(date_str):
    try:
        return datetime.datetime.strptime(date_str, DATE_FORMAT_ISO)
    except ValueError:
        return datetime.datetime.strptime(date_str, DATE_FORMAT_DE)


def _parse_float(string):
    return float(string.replace('\'', ''))


class _PostFinanceImporter(importer.Importer):
    # This base method is generic enough for both checking and credit card.
    def import_transactions(self, file=None, filename=None, currency=None):
        metadata, rows = importer.read_csv_with_header(file, filename)
        # TODO: Support different currencies.
        currency = 'CHF'
        credit_col = 'Gutschrift in ' + currency
        debit_col = 'Lastschrift in ' + currency

        # Get transactions.
        transactions = []
        for row in rows:
            date_str = row.get('Buchungsdatum') or row.get('Datum')
            date = _parse_date(date_str)
            
            credit = _parse_float(row[credit_col]) if row[credit_col] else None
            debit = -abs(_parse_float(row[debit_col])) if row[debit_col] \
                    else None
            amount = credit if credit else debit
            
            memo_str = row.get('Buchungsdetails') or row.get('Bezeichnung') or \
                    row.get('Avisierungstext')
            memo = importer.normalize_text(memo_str)

            # Skip "Total" row.
            if memo == 'Total' and not amount:
                continue
            
            transactions.append(model.Payment(date, amount, memo=memo))
        logger.info("Imported %d transactions." % len(transactions))
        return transactions


class PostFinanceCheckingImporter(_PostFinanceImporter):
    """Importer for PostFinance checking accounts (http://www.postfincance.ch/).
    """


class PostFinanceCreditCardImporter(_PostFinanceImporter):
    """Importer for PostFinance credit cards (http://www.postfincance.ch/).
    """
