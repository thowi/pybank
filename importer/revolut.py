import csv
import datetime
import logging

import importer
import model

DATE_FORMAT = '%b %d, %Y'

logger = logging.getLogger(__name__)


class RevolutImporter(importer.Importer):
    """Importer for Revolut (http://www.revolut.com/).
    """

    def import_transactions(self, file=None, filename=None, currency=None):
        with importer.open_input_file(file, filename) as file:
            reader = csv.reader(file, delimiter=';', quotechar='"')

            # Read header.
            headers_row = next(reader)

            # Get transactions.
            transactions = []
            for row in reader:
                if len(row) < 9 or row[1] == 'No Transactions':
                    continue
                row = [c.strip() if c is not None else None for c in row]
                date = datetime.datetime.strptime(row[0], DATE_FORMAT)
                description = row[1]
                debit = importer.parse_decimal_number(row[2], 'en_GB') \
                        if row[2] else None
                credit = importer.parse_decimal_number(row[3], 'en_GB') \
                        if row[3] else None
                exchange_out = row[4]
                exchange_in = row[5]
                balance_str = row[6]
                category = row[7]
                notes = row[8]

                amount = credit if credit else -debit
                memo_parts = (description, exchange_in, exchange_out, notes)
                memo = '. '.join(filter(bool, memo_parts))

                transactions.append(model.Payment(date, amount, memo=memo))
            logger.debug("Imported %d transactions." % len(transactions))
            return transactions
