#!/usr/bin/python

import csv
import datetime
import getpass
import logging
import urlparse

import BeautifulSoup

import fetch
import fetch.bank
import fetch.browser
import model


logger = logging.getLogger(__name__)


class DeutscheKreditBank(fetch.bank.Bank):
    """Fetcher for Deutsche Kreditbank (http://www.dkb.de/).

    The accounts for a user will be identified by the bank account number
    (digits) or the obfuscated credit card number (1234******5678).
    """
    _BASE_URL = 'https://banking.dkb.de/dkb/-'
    _OVERVIEW_PATH = (
            '?$part=DkbTransactionBanking.index.menu'
            '&treeAction=selectNode'
            '&node=0'
            '&tree=menu')
    _ACCOUNT_PATH_PATTERN = (
            '?$part=DkbTransactionBanking.content.banking.FinancialStatus.'
            'FinancialStatus'
            '&$event=paymentTransaction'
            '&row=%i'
            '&table=cashTable')
    _CHECKING_ACCOUNT_SEARCH_PATTERN = (
            '?slBankAccount=0'
            '&slTransactionStatus=0'
            '&slSearchPeriod=3'
            '&searchPeriodRadio=1'
            '&transactionDate=%s'
            '&toTransactionDate=%s'
            '&$part=DkbTransactionBanking.content.banking.Transactions.Search'
            '&$event=search')
    _CHECKING_ACCOUNT_CSV_PATH = (
            '?$part=DkbTransactionBanking.content.banking.Transactions.Search'
            '&$event=csvExport')
    _CREDIT_CARD_SEARCH_PATTERN = (
            '?slCreditCard=0'
            '&searchPeriod=0'
            '&postingDate=%s'
            '&toPostingDate=%s'
            '&$part=DkbTransactionBanking.content.creditcard.'
            'CreditcardTransactionSearch'
            '&$event=search')
    _CREDIT_CARD_CSV_PATH = (
            '?$part=DkbTransactionBanking.content.creditcard.'
            'CreditcardTransactionSearch'
            '&$event=csvExport')
    _DATE_FORMAT = '%d.%m.%Y'

    def login(self, username=None, password=None):
        self._browser = fetch.browser.Browser()
        self._logged_in = False
        self._accounts = None

        if not username:
            username = raw_input('User: ')

        if not password:
            password = getpass.getpass('PIN: ')

        browser = self._browser

        logger.info('Loading login page...')
        browser.open(self._BASE_URL)

        try:
            browser.select_form(name='login')
        except mechanize.FormNotFoundError, e:
            raise fetch.FetchError('Login form not found.')
        form = browser.form
        form['j_username'] = username
        form['j_password'] = password
        logger.info('Logging in with user name %s...' % username)
        browser.submit()
        html = browser.get_decoded_content()

        if 'Finanzstatus' not in html:
            raise fetch.FetchError('Login failed.')

        self._logged_in = True
        logger.info('Log-in sucessful.')

    def logout(self):
        self._browser.close()
        self._logged_in = False
        self._accounts = None

    def get_accounts(self):
        self._check_logged_in()

        if self._accounts is not None:
            return self._accounts

        browser = self._browser

        overview_url = urlparse.urljoin(self._BASE_URL, self._OVERVIEW_PATH)
        logger.info('Loading accounts overview...')
        browser.open(overview_url)
        html = browser.get_decoded_content()
        soup = BeautifulSoup.BeautifulSoup(html)

        accounts_table = soup.find(
                'table', {'class': 'financialStatusTable dropdownAnchor'})
        account_rows = accounts_table.find('tbody').findAll('tr')
        self._accounts = []
        for account_row in account_rows:
            try:
                if 'sum' in account_row.get('class', ''):
                    continue
                headers = account_row.findAll('th')
                cells = account_row.findAll('td')
                name = headers[0].getText()
                acc_type = cells[0].getText()
                balance = self._parse_balance(headers[1].getText())
                balance_date_text = cells[1].getText()
                balance_date = datetime.datetime.strptime(
                        balance_date_text, self._DATE_FORMAT)
                if self._is_credit_card(name):
                    account = model.CreditCard(name, balance, balance_date)
                else:
                    account = model.CheckingAccount(name, balance, balance_date)
                self._accounts.append(account)
            except ValueError:
                logging.error('Invalid account row. %s' % details_row)

        logger.info('Found %i accounts.' % len(self._accounts))
        return self._accounts

    def get_transactions(self, account, start, end):
        self._check_logged_in()

        accounts = self.get_accounts()
        try:
            account_index = accounts.index(account)
        except ValueError:
            raise fetch.FetchError('Unknown account: %s' % account)
        is_credit_card = isinstance(account, model.CreditCard)

        browser = self._browser

        # Open account.
        logger.info('Loading account info...')
        account_url = urlparse.urljoin(
                self._BASE_URL, self._ACCOUNT_PATH_PATTERN % account_index)
        browser.open(account_url)

        # Perform search.
        logger.info('Performing transactions search...')
        formatted_start = start.strftime(self._DATE_FORMAT)
        end_inclusive = end - datetime.timedelta(1)
        formatted_end = end_inclusive.strftime(self._DATE_FORMAT)
        if is_credit_card:
            search_url_pattern = self._CREDIT_CARD_SEARCH_PATTERN
        else:
            search_url_pattern = self._CHECKING_ACCOUNT_SEARCH_PATTERN
        search_url = urlparse.urljoin(
                self._BASE_URL, search_url_pattern % (
                        formatted_start, formatted_end))
        browser.open(search_url)

        # Download CSV.
        logger.info('Downloading transactions CSV...')
        if is_credit_card:
            csv_path = self._CREDIT_CARD_CSV_PATH
        else:
            csv_path = self._CHECKING_ACCOUNT_CSV_PATH
        csv_url = urlparse.urljoin(self._BASE_URL, csv_path)
        browser.open(csv_url)
        csv_data = browser.get_decoded_content()
        if account.name not in csv_data:
            raise fetch.FetchError('Account name not found in CSV.')

        # Parse CSV into transactions.
        transactions = self._get_transactions_account_csv(
                csv_data, is_credit_card)
        logger.info('Found %i transactions.' % len(transactions))

        return transactions

    def _is_credit_card(self, name):
        return '******' in name

    def _get_transactions_account_csv(self, csv_data, is_credit_card):
        reader = _unicode_csv_reader(csv_data.splitlines(), delimiter=';')

        transactions = []
        for row in reader:
            if is_credit_card:
                transaction = self._get_transaction_from_credit_card_row(row)
            else:
                transaction = self._get_transaction_from_checking_account_row(
                        row)
            if transaction:
                transactions.append(transaction)

        return transactions

    def _get_transaction_from_checking_account_row(self, row):
        if len(row) != 9:
            return

        try:
            date = datetime.datetime.strptime(row[0], self._DATE_FORMAT)
            payee = fetch.normalize_text(row[3])
            memo = fetch.normalize_text(row[4])

            account = row[5]
            if account:
                memo += '\nAccount: %s' % account

            clearing = row[6]
            if clearing:
                memo += '\nClearing: %s' % clearing

            amount = fetch.parse_decimal_number(row[7], 'de_DE')

            return model.Transaction(date, amount, payee, memo)
        except ValueError, e:
            logger.debug('Skipping invalid row: %s' % row)
            return

    def _get_transaction_from_credit_card_row(self, row):
        if len(row) != 7:
            return

        try:
            date = datetime.datetime.strptime(row[1], self._DATE_FORMAT)
            memo = fetch.normalize_text(row[3])
            amount = fetch.parse_decimal_number(row[4], 'de_DE')

            orig_amount = row[5]
            if orig_amount:
                memo += '\nOriginal amount: %s' % orig_amount

            return model.Transaction(date, amount, memo=memo)
        except ValueError, e:
            logger.debug('Skipping invalid row: %s' % row)
            return

    def _parse_balance(self, balance):
        if balance.endswith('S'):  # Debit.
            balance = '-' + balance
        balance = balance.replace(' S', '').replace(' H', '')
        return fetch.parse_decimal_number(balance, 'de_DE')

    def _check_logged_in(self):
        if not self._logged_in:
            raise fetch.FetchError('Not logged in.')


def _unicode_csv_reader(unicode_csv_data, dialect=csv.excel, **kwargs):
    # csv.py doesn't do Unicode; encode temporarily as UTF-8.
    csv_reader = csv.reader(
            _utf_8_encoder(unicode_csv_data), dialect=dialect, **kwargs)
    for row in csv_reader:
        # Decode UTF-8 back to Unicode, cell by cell.
        yield [unicode(cell, 'utf-8') for cell in row]


def _utf_8_encoder(unicode_csv_data):
    for line in unicode_csv_data:
        yield line.encode('utf-8')
