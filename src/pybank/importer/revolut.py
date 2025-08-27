import csv
import datetime
import logging
from typing import TextIO

from .. import importer
from .. import model


DATE_TIME_FORMAT = '%Y-%m-%d %H:%M:%S'

logger = logging.getLogger(__name__)


class RevolutImporter(importer.Importer):
    """Importer for Revolut (http://www.revolut.com/).
    """

    def import_transactions(self, file: TextIO, currency: str | None = None) \
                -> list[model.Payment]:
        reader = csv.reader(file, delimiter=',', quotechar='"')

        # Read header.
        headers_row = next(reader)

        # Get transactions.
        transactions = []
        for row in reader:
            if len(row) < 10:
                continue
            row = [c.strip() if c is not None else None for c in row]
            date = datetime.datetime.strptime(row[3], DATE_TIME_FORMAT)
            description = row[4]
            amount = importer.parse_decimal_number(row[5], 'en_GB') \
                    if row[5] else None
            fee = importer.parse_decimal_number(row[6], 'en_GB') \
                    if row[6] else None
            curr = row[7]
            if currency != None and currency != curr:
                logger.debug("Skipping transaction with wrong currency: " +
                        str(row))
                continue
            state = row[8]
            balance = importer.parse_decimal_number(row[9], 'en_GB') \
                    if row[9] else None
            if state != 'COMPLETED':
                logger.debug("Skipping incomplete transaction: " + str(row))

            memo_parts = (description, 'Fee: %.2f' % fee if fee else None)
            memo = '. '.join(filter(bool, memo_parts))

            transactions.append(
                    model.Payment(date=date, amount=amount, memo=memo))
        logger.debug("Imported %d transactions." % len(transactions))
        return transactions
