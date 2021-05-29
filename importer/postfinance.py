import csv
import datetime
import logging

import importer
import model

DATE_FORMAT = '%Y-%m-%d'

logger = logging.getLogger(__name__)


class PostFinanceCheckingImporter(importer.Importer):
    """Importer for PostFinance checking accounts (http://www.postfincance.ch/).
    """

    def import_transactions(self, file=None, filename=None, currency=None):
        with importer.open_input_file(file, filename, 'iso-8859-1') as file:
            reader = csv.reader(file, delimiter=';', quotechar='"')

            # Read header.
            from_date_row = next(reader)
            to_date_row = next(reader)
            types_row = next(reader)
            account_row = next(reader)
            currency_row = next(reader)
            currency = currency_row[1]
            headers_row = next(reader)

            # Get transactions.
            transactions = []
            for row in reader:
                if len(row) < 6:
                    continue
                settled_date = row[0]
                memo = importer.normalize_text(row[1].strip())
                credit = float(row[2]) if row[2] else None
                debit = float(row[3]) if row[3] else None
                value_date = row[4]
                date = datetime.datetime.strptime(settled_date, DATE_FORMAT)
                amount = credit if credit else debit
                transactions.append(model.Payment(date, amount, memo=memo))
            logger.debug("Imported %d transactions." % len(transactions))
            return transactions


class PostFinanceCreditCardImporter(importer.Importer):
    """Importer for PostFinance credit cards (http://www.postfincance.ch/).
    """

    _DATE_FORMAT = '%Y-%m-%d'

    def import_transactions(self, file=None, filename=None):
        with importer.open_input_file(file, filename, 'iso-8859-1') as file:
            reader = csv.reader(file, delimiter=';', quotechar='"')

            # Read header.
            card_account_row = next(reader)
            card_row = next(reader)
            date_range_row = next(reader)
            headers_row = next(reader)

            # Get transactions.
            transactions = []
            for row in reader:
                print(row)
                if len(row) != 4:
                    continue
                date = datetime.datetime.strptime(row[0], DATE_FORMAT)
                memo =  importer.normalize_text(row[1].strip())
                credit = float(row[2]) if row[2] else None
                debit = float(row[3]) if row[3] else None
                amount = credit if credit else debit
                transactions.append(model.Payment(date, amount, memo=memo))
            logger.debug("Imported %d transactions." % len(transactions))
            return transactions
