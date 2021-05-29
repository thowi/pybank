import csv
import datetime
import logging

import importer
import model

DATE_FORMAT = '%d.%m.%Y'

logger = logging.getLogger(__name__)


class DkbCheckingImporter(importer.Importer):
    """Importer for DKB checking accounts (http://www.dkb.de/).
    """

    def import_transactions(self, file=None, filename=None, currency=None):
        with importer.open_input_file(file, filename, 'iso-8859-1') as file:
            reader = csv.reader(file, delimiter=';', quotechar='"')

            # Read header.
            account_row = next(reader)
            next(reader)
            from_date_row = next(reader)
            to_date_row = next(reader)
            balance_row = next(reader)
            next(reader)
            headers_row = next(reader)

            # Get transactions.
            transactions = []
            for row in reader:
                if len(row) < 8:
                    continue
                settled_date = row[0]
                value_date = row[1]
                booking_type = row[2]
                counterpart = importer.normalize_text(row[3])
                memo = importer.normalize_text(row[4])
                counterpart_account = row[5]
                counterpart_routing = row[6]
                amount = importer.parse_decimal_number(row[7], 'de_DE')
                date = datetime.datetime.strptime(settled_date, DATE_FORMAT)
                memo_parts = (
                        memo, counterpart, counterpart_account,
                        counterpart_routing)
                memo = '. '.join(filter(bool, memo_parts))
                transactions.append(model.Payment(date, amount, memo=memo))
            logger.debug("Imported %d transactions." % len(transactions))
            return transactions


class DkbCreditCardImporter(importer.Importer):
    """Importer for DKB credit cards (http://www.dkb.de/).
    """

    def import_transactions(self, file=None, filename=None):
        with importer.open_input_file(file, filename, 'iso-8859-1') as file:
            reader = csv.reader(file, delimiter=';', quotechar='"')

            # Read header.
            card_row = next(reader)
            next(reader)
            from_date_row = next(reader)
            to_date_row = next(reader)
            balance_row = next(reader)
            date_row = next(reader)
            next(reader)
            headers_row = next(reader)

            # Get transactions.
            transactions = []
            for row in reader:
                print(row)
                if len(row) < 5:
                    continue
                value_missing_from_balance = row[0]
                value_date = row[1]
                receipt_date = row[2]
                date = datetime.datetime.strptime(receipt_date, DATE_FORMAT)
                memo =  importer.normalize_text(row[3].strip())
                amount = importer.parse_decimal_number(row[4], 'de_DE')
                orig_amount = importer.parse_decimal_number(row[5], 'de_DE') \
                        if row[5] else None
                if orig_amount:
                    memo = memo + '. Original amount: ' + orig_amount + '.'
                transactions.append(model.Payment(date, amount, memo=memo))
            logger.debug("Imported %d transactions." % len(transactions))
            return transactions
