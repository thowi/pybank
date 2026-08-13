import csv
import datetime
import logging
from typing import TextIO

from .. import importer, model, text

DATE_FORMAT = "%m/%d/%Y"

logger = logging.getLogger(__name__)


class SchwabBrokerageImporter(importer.Importer):
    """Importer for Schwab brokerage accounts (http://www.schwab.com/)."""

    def import_transactions(
        self, file: TextIO, currency: str | None = None
    ) -> list[model.Transaction]:
        reader = csv.reader(file, delimiter=",", quotechar='"')

        # Read header.
        next(reader)
        next(reader)

        # Get transactions.
        transactions = []
        for row in reader:
            if len(row) < 8 or row[0] == "Transactions Total":
                continue
            date = datetime.datetime.strptime(row[0], DATE_FORMAT)
            action = row[1]
            _symbol = row[2]
            description = text.normalize_text(row[3])
            _quantity = row[4]
            _price = row[5]
            _fees = row[6]
            amount = parse_dollar_amount(row[7])
            memo = f"{action}. {description}"

            if action in (
                "Journal",
                "Misc Cash Entry",
                "Wire Funds",
                "Wire Funds Adj",
                "Wire Funds Received",
            ):
                transaction = model.Payment(date=date, amount=amount, memo=memo)
            elif action == "Credit Interest":
                transaction = model.InvestmentInterestIncome(date=date, amount=amount, memo=memo)
            elif action == "Service Fee":
                transaction = model.InvestmentMiscExpense(date=date, amount=amount, memo=memo)
            else:
                # TODO: Add support for purchases, sales, dividends etc.
                raise ValueError("Unknown action: " + action)
            transactions.append(transaction)
        logger.debug("Imported %d transactions.", len(transactions))
        return transactions


class SchwabEacImporter(importer.Importer):
    """Importer for Schwab Equity Awards Center accounts
    (http://www.schwab.com/).
    """

    def import_transactions(
        self, file: TextIO, currency: str | None = None
    ) -> list[model.Transaction]:
        reader = csv.reader(file, delimiter=",", quotechar='"')

        # Read header.
        next(reader)
        next(reader)

        # Get transactions.
        transactions = []
        for row in reader:
            # TODO. Add support for these reports. They're a little complex.
            pass
        logger.debug("Imported %d transactions.", len(transactions))
        return transactions


def parse_dollar_amount(string: str) -> float:
    return importer.parse_decimal_number(string.replace("$", ""), "en_US")
