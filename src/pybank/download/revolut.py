import collections
import csv
import datetime
import glob
import itertools
import logging
import re

from .. import download
from .. import model


logger = logging.getLogger(__name__)


class Revolut(download.bank.Bank):
    """Fetcher for Revolut (https://www.revolut.com/).

    Revolut doesn't have a Web interface, so we're just working with downloaded
    CSV files.
    """
    _DATE_FORMAT = '%b %d, %Y'
    _DATE_HEADER = 'Completed Date'
    _DESCRIPTION_HEADER = 'Description'
    _BALANCE_HEADER_PATTERN = 'Balance (%s)'
    _PAID_OUT_HEADER = 'Paid Out (%s)'
    _PAID_OUT_HEADER_REGEX = re.compile(r'Paid Out \((.+)\)')
    _PAID_IN_HEADER = 'Paid In (%s)'
    _EXCHANGE_OUT_HEADER = 'Exchange Out'
    _EXCHANGE_IN_HEADER = 'Exchange In'
    _NOTES_HEADER = 'Notes'

    def login(
            self,
            username: str | None = None,
            password: str | None = None,
            statements: list[str] = []) -> None:
        self._accounts_cache = None

        # Collect readable statement files.
        filenames = list(itertools.chain(*(glob.glob(s) for s in statements)))
        logger.info('Scanning statment files: %s.' % ', '.join(filenames))
        self._statement_file_names = []
        for filename in filenames:
            try:
                with open(filename, 'r') as f:
                    self._statement_file_names.append(filename)
            except (FileNotFoundError, OSError):
                logger.error('Couln\'t read file: ' + filename)
                pass
        if len(self._statement_file_names) > 0:
            logger.info(
                    'Using statment files: %s.' %
                    ', '.join(self._statement_file_names))
        else:
            raise download.FetchError('Couldn\'t read any statement files.')

    def logout(self) -> None:
        pass

    def get_accounts(self) -> list[model.Account]:
        if self._accounts_cache is not None:
            return self._accounts_cache

        self._accounts_cache = self._fetch_accounts()
        logger.info('Found %i accounts.' % len(self._accounts_cache))
        return self._accounts_cache

    def _fetch_accounts(self):
        logger.debug('Getting accounts from statement files…')
        transactions_by_currency = collections.defaultdict(list)
        balance_by_currency = {}
        for statement_filename in self._statement_file_names:
            # Get currency.
            currency = None
            with open(statement_filename, 'r') as csvfile:
                reader = csv.reader(csvfile, delimiter=';', quotechar='"')
                header_row = next(reader)
                for cell in header_row:
                    match = self._PAID_OUT_HEADER_REGEX.match(cell.strip())
                    if match:
                        currency = match.group(1)
            if not currency:
                logger.error(
                    'Couldn\'t find currency in statement: ' +
                    statement_filename)
                continue
            # Get balance and all transactions.
            balance = None
            balance_date = None
            transactions = []
            with open(statement_filename, 'r') as csvfile:
                reader = csv.DictReader(csvfile, delimiter=';', quotechar='"')
                strip_or_none = lambda s: s.strip() if s is not None else None
                rows = [{strip_or_none(k): strip_or_none(v) for k, v in row.items()}
                        for row in reader]
                if rows and not (len(rows) == 1 and rows[0]['Description'] == 'No Transactions'):
                    # Get balance.
                    balance_str = rows[0][
                            self._BALANCE_HEADER_PATTERN % currency]
                    balance = self._parse_float(balance_str)
                    balance_date_str = rows[0][self._DATE_HEADER]
                    balance_date = datetime.datetime.strptime(
                            balance_date_str, self._DATE_FORMAT)
                    if (currency not in balance_by_currency or
                            balance_date > balance_by_currency[currency][0]):
                        balance_by_currency[currency] = balance_date, balance
                    # Get all transactions.
                    for row in rows:
                        transactions_by_currency[currency].append(
                                self._get_transaction_from_row(row, currency))

        accounts = []
        for currency, transactions in transactions_by_currency.items():
            balance_date, balance = balance_by_currency[currency]
            accounts.append(model.CreditCard(
                    name=currency, currency=currency, balance=balance,
                    balance_date=balance_date, transactions=transactions))
        return accounts

    def _get_transaction_from_row(self, row, currency):
        date = datetime.datetime.strptime(
                row[self._DATE_HEADER], self._DATE_FORMAT)
        description = row[self._DESCRIPTION_HEADER]
        credit_str = row[self._PAID_IN_HEADER % currency]
        debit_str = row[self._PAID_OUT_HEADER % currency]
        exchange_in_str = row[self._EXCHANGE_IN_HEADER]
        exchange_out_str = row[self._EXCHANGE_OUT_HEADER]
        notes = row[self._NOTES_HEADER]
        credit = self._parse_float(credit_str) if credit_str else None
        debit = self._parse_float(debit_str) if debit_str else None
        amount = credit if credit else -debit
        memo = '. '.join(
                (v for v in (description, exchange_in_str, exchange_out_str,
                notes) if v))
        return model.Payment(date=date, amount=amount, memo=memo)

    def get_transactions(
            self,
            account: model.Account,
            start: datetime.datetime,
            end: datetime.datetime) -> list[model.Transaction]:
        # Filter transactions in matching account for date range.
        transactions = []
        for acc in self.get_accounts():
            if acc.name == account.name:
                for transaction in acc.transactions:
                    if transaction.date >= start and transaction.date < end:
                        transactions.append(transaction)
        logger.info('Found %i transactions for account %s.' % (
                len(transactions), account.name))
        return transactions

    def _parse_float(self, string):
        return float(string.replace(',', ''))
