import csv
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


def _process_csv(file=None, filename=None):
    """Processes a PostFinance CSV file and returns metadata and transactions.

    The CSV file is a bit special as it has a multi-line header, body, and
    footer.

    Over time, the format has changed and this function tries to support 
    different versions of the CSV file.

    @type file: io.IOBase or None
    @param file: The file object to read from.

    @type filename: str or None
    @param filename: The filename to read from.

    @rtype: (dict, [{str: str}])
    @return: The metadata as a dict and the rows as a list of dicts, each
    mapping from the columen name to the value (similar to `DictReader`).
    """
    with importer.open_input_file(file, filename) as file:
        reader = csv.reader(file, delimiter=';', quotechar='"')
        # Read metadata.
        metadata = {}
        col_names = None
        rows = []
        for row in reader:
            # Skip empty/irrelevant rows.
            if len(row) < 2:
                continue
            
            # Read metadata.
            if len(row) == 2 and not col_names:
                metadata[row[0]] = row[1]
                continue
            
            # Read column names.
            if not col_names:
                col_names = row
                continue
            
            # Read transaction rows.
            rows.append(dict(zip(col_names, row)))
        
        return metadata, rows


def _parse_float(string):
    return float(string.replace('\'', ''))


class _PostFinanceImporter(importer.Importer):
    # This base method is generic enough for both checking and credit card.
    def import_transactions(self, file=None, filename=None, currency=None):
        metadata, rows = _process_csv(file, filename)
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
