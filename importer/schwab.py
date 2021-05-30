import csv
import datetime
import logging

import importer
import model

DATE_FORMAT = '%m/%d/%Y'

logger = logging.getLogger(__name__)


class SchwabBrokerageImporter(importer.Importer):
    """Importer for Schwab brokerage accounts (http://www.schwab.com/).
    """

    def import_transactions(self, file=None, filename=None, currency=None):
        with importer.open_input_file(file, filename) as file:
            reader = csv.reader(file, delimiter=',', quotechar='"')

            # Read header.
            next(reader)
            headers_row = next(reader)

            # Get transactions.
            transactions = []
            for row in reader:
                if len(row) < 8 or row[0] == 'Transactions Total':
                    continue
                date = datetime.datetime.strptime(row[0], DATE_FORMAT)
                action = row[1]
                symbol = row[2]
                description = importer.normalize_text(row[3])
                quantity = row[4]
                price = row[5]
                fees = row[6]
                amount = parse_dollar_amount(row[7])
                memo = '. '.join((action, description))

                if action in (
                        'Journal', 'Misc Cash Entry', 'Wire Funds',
                        'Wire Funds Adj', 'Wire Funds Received'):
                    transaction = model.Payment(date, amount, memo=memo)
                elif action == 'Credit Interest':
                    transaction = model.InvestmentInterestIncome(
                            date, amount, memo=memo)
                elif action == 'Service Fee':
                    transaction = model.InvestmentMiscExpense(
                            date, amount, memo=memo)
                else:
                    # TODO: Add support for purchases, sales, dividends etc.
                    raise Exception('Unknown action: ' + action)
                transactions.append(transaction)
            logger.debug("Imported %d transactions." % len(transactions))
            return transactions


class SchwabEacImporter(importer.Importer):
    """Importer for Schwab Equity Awards Center accounts
    (http://www.schwab.com/).
    """

    def import_transactions(self, file=None, filename=None, currency=None):
        with importer.open_input_file(file, filename) as file:
            reader = csv.reader(file, delimiter=',', quotechar='"')

            # Read header.
            next(reader)
            headers_row = next(reader)

            # Get transactions.
            transactions = []
            for row in reader:
                # TODO. Add support for these reports. They're a little complex.
                pass
            logger.debug("Imported %d transactions." % len(transactions))
            return transactions


def parse_dollar_amount(string):
    return importer.parse_decimal_number(string.replace('$', ''), 'en_US')
