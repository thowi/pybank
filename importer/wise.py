import csv
import datetime
import logging

import importer
import model

DATE_FORMAT = '%d-%m-%Y'

logger = logging.getLogger(__name__)


class WiseImporter(importer.Importer):
    """Importer for Wise accounts (http://www.wise.com/).
    """

    def import_transactions(self, file=None, filename=None, currency=None):
        with importer.open_input_file(file, filename) as file:
            reader = csv.reader(file, delimiter=',', quotechar='"')

            # Read header.
            headers_row = next(reader)

            # Get transactions.
            transactions = []
            for row in reader:
                print(len(row))
                if len(row) < 15:
                    continue
                wise_id = row[0]
                date = datetime.datetime.strptime(row[1], DATE_FORMAT)
                amount = importer.parse_decimal_number(row[2], 'en_GB')
                currency = row[3]
                description = row[4]
                payment_reference = row[5]
                running_balance = row[6]
                exchange_from = row[7]
                exchange_to = row[8]
                exchange_rate = row[9]
                payer_name = row[10]
                payee_name = row[11]
                payee_acc = row[12]
                merchant = row[13]
                fees = importer.parse_decimal_number(row[14], 'en_GB')

                memo_parts = [description]
                if exchange_rate:
                    memo_parts.append('Exchange rate: ' + exchange_rate)
                if merchant:
                    memo_parts.append('Merchant: ' + merchant)
                if fees:
                    memo_parts.append('Fees: ' + str(fees))
                memo_parts.append('ID: ' + wise_id)
                memo = '. '.join(memo_parts)

                payee = ', '.join(filter(bool, (payee_name, payee_acc)))

                transactions.append(
                        model.Payment(
                                date, amount, payer=payer_name, payee=payee,
                                memo=memo))
            logger.debug("Imported %d transactions." % len(transactions))
            return transactions
