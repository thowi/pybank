#!/usr/bin/python

import collections
import datetime
import getpass
import logging
import tempfile

import BeautifulSoup
from selenium import webdriver
from selenium.common import exceptions
from selenium.webdriver.support import ui
import fetch.bank
import model


logger = logging.getLogger(__name__)


class InteractiveBrokers(fetch.bank.Bank):
    """Fetcher for Interactive Brokers (https://www.interactivebrokers.com/)."""
    _LOGIN_URL = 'https://gdcdyn.interactivebrokers.com/sso/Login'
    _ACTIVITY_FORM_DATE_FORMAT = '%Y%m%d'
    _DATE_TIME_FORMAT = '%Y-%m-%d, %H:%M:%S'
    _DATE_FORMAT = '%Y-%m-%d'
    _WEBDRIVER_TIMEOUT = 20

    def login(self, username=None, password=None):
        if self._debug:
            self._browser = webdriver.Firefox()
        else:
            # TODO: Fix the login and enable PhantomJs.
            #self._browser = webdriver.PhantomJS()
            self._browser = webdriver.Firefox()
        self._browser.implicitly_wait(self._WEBDRIVER_TIMEOUT)
        self._browser.set_window_size(800, 800)
        self._logged_in = False
        self._accounts_cache = None
        self._transactions_cache = {}

        browser = self._browser
        browser.get(self._LOGIN_URL)

        if not username:
            username = raw_input('User name: ')

        if not password:
            password = getpass.getpass('Password: ')

        # First login phase: User and password.
        try:
            login_form = browser.find_element_by_name('loginform')
        except exceptions.NoSuchElementException:
            raise fetch.FetchError('Login form not found.')
        login_form.find_element_by_name('user_name').send_keys(username)
        login_form.find_element_by_name('password').send_keys(password)
        login_form.submit()

        # Login successful?
        error_element = browser.find_element_by_class_name('errorMsg')
        error_message = error_element.text
        if error_message:
            logger.error('Login failed:\n%s' % error_message)
            raise fetch.FetchError('Login failed.')

        # Second login phase: Challenge and security token.
        challenge_container = browser.find_element_by_id('chlgtext')
        # Wait for the image to load, take a screenshot.
        unused_challenge_img = challenge_container.find_element_by_tag_name(
                'img')
        screenshot_temp_filename = tempfile.mkstemp()[1]
        browser.get_screenshot_as_file(screenshot_temp_filename)
        print 'See screenshot for challenge:', screenshot_temp_filename
        token = raw_input('Login token: ')
        login_form.find_element_by_name('chlginput').send_keys(token)
        login_form.submit()

        # Login successful?
        try:
            browser.find_element_by_id('mainFrameSet')
        except exceptions.NoSuchElementException:
            raise fetch.FetchError('Login failed.')

        self._logged_in = True
        self._main_window_handle = browser.current_window_handle
        logger.info('Log-in sucessful.')

    def logout(self):
        browser = self._browser
        browser.switch_to_default_content()
        browser.switch_to_frame('header')
        browser.find_element_by_link_text('Logout').click()

        browser.quit()
        self._logged_in = False
        self._accounts_cache = None
        self._transactions_cache = {}

    def get_accounts(self):
        if self._accounts_cache is not None:
            return self._accounts_cache

        self._accounts_cache = self._fetch_accounts()
        logger.info('Found %i accounts.' % len(self._accounts_cache))
        return self._accounts_cache

    def _fetch_accounts(self):
        self._check_logged_in()
        browser = self._browser

        self._go_to_activity_statements()

        # Get activity statements form.
        try:
            form = browser.find_element_by_name('view_stmt')
        except exceptions.NoSuchElementException:
            raise fetch.FetchError('Activity statements form not found.')

        logger.debug('Getting accounts from activity statements form...')
        account_select = form.find_element_by_name('accounts')
        account_options = account_select.find_elements_by_tag_name('option')
        account_names = [o.get_attribute('value') for o in account_options]

        # Get currencies and balances in each account.
        today = datetime.datetime.today()
        accounts = []
        for account_name in account_names:
            self._open_activity_statement(account_name, today, today)
            currencies_and_balances = \
                    self._get_currencies_and_balances_from_activity_statement(
                            account_name)
            for currency, balance in currencies_and_balances:
                name = '%s.%s' % (account_name, currency)
                accounts.append(model.InvestmentsAccount(name, balance, today))
            self._close_activity_statement()

        return accounts

    def _get_currencies_and_balances_from_activity_statement(
            self, account_name):
        logger.debug('Extracting currencies and balances...')

        table_rows = self._find_transaction_rows('CashReport', account_name)
        rows_by_currency = self._group_rows_by_currency(
                table_rows, expected_num_columns=7)
        currencies_and_balances = []
        for currency, rows in rows_by_currency.items():
            if currency == 'Base Currency Summary':
                continue
            for cells in rows:
                if cells[0].getText() == 'Ending Cash':
                    balance = self._parse_float(cells[1].getText())
                    currencies_and_balances.append((currency, balance))

        return currencies_and_balances

    def get_transactions(self, account, start, end):
        account_name, currency = self._split_account_name(account.name)
        cache_key = account_name, start, end
        cached_transactions = self._transactions_cache.get(cache_key)
        if cached_transactions:
            return cached_transactions[currency]

        self._check_logged_in()

        end_inclusive = end - datetime.timedelta(1)
        self._open_activity_statement(account_name, start, end_inclusive)

        trades = self._get_trades_from_activity_statement(account_name)
        withholding_tax = self._get_withholding_tax_from_activity_statement(
                account_name)
        dividends = self._get_dividends_from_activity_statement(account_name)
        other_fees = self._get_other_fees_from_activity_statement(account_name)

        # We're only interested in the current currency.
        transactions = []
        for category in trades, withholding_tax, dividends, other_fees:
            transactions_by_currency = category.get(currency)
            if transactions_by_currency:
                transactions += transactions_by_currency

        self._close_activity_statement()

        logger.info('Found %i transactions.' % len(transactions))
        return transactions

    def _get_trades_from_activity_statement(self, account_name):
        logger.debug('Extracting trades...')

        table_rows = self._find_transaction_rows('Transactions', account_name)
        rows_by_currency = self._group_rows_by_currency(
                table_rows, expected_num_columns=12)
        transactions_by_currency = {}
        for currency, rows in rows_by_currency.items():
            transactions = []
            transactions_by_currency[currency] = transactions
            for cells in rows:
                symbol = cells[0].getText()
                date = cells[1].getText()
                try:
                    date = datetime.datetime.strptime(
                            date, self._DATE_TIME_FORMAT)
                except ValueError:
                    logger.warning(
                            'Skipping transaction with invalid date %s.', date)
                    continue
                quantity = self._parse_int(cells[3].getText())
                price = self._parse_float(cells[4].getText())
                proceeds = self._parse_float(cells[6].getText())
                commissions_and_tax = self._parse_float(cells[7].getText())
                amount = proceeds + commissions_and_tax

                if quantity >= 0:
                    transaction = model.InvestmentSecurityPurchase(
                            date, symbol, quantity, price, commissions_and_tax,
                            amount)
                else:
                    transaction = model.InvestmentSecuritySale(
                            date, symbol, -quantity, price, commissions_and_tax,
                            amount)
                transactions.append(transaction)

        return transactions_by_currency

    def _get_withholding_tax_from_activity_statement(self, account_name):
        logger.debug('Extracting withholding tax...')

        table_rows = self._find_transaction_rows('WithholdingTax', account_name)
        rows_by_currency = self._group_rows_by_currency(
                table_rows, expected_num_columns=4)
        transactions_by_currency = {}
        for currency, rows in rows_by_currency.items():
            transactions = []
            transactions_by_currency[currency] = transactions
            for cells in rows:
                date = cells[0].getText()
                try:
                    date = datetime.datetime.strptime(date, self._DATE_FORMAT)
                except ValueError:
                    logger.warning(
                            'Skipping transaction with invalid date %s.', date)
                    continue
                description = cells[1].getText()
                amount = self._parse_float(cells[2].getText())

                symbol = description.split()[0]
                memo = description

                transaction = model.InvestmentMiscExpense(
                        date, symbol, amount, memo)
                transactions.append(transaction)

        return transactions_by_currency

    def _get_dividends_from_activity_statement(self, account_name):
        logger.debug('Extracting dividends...')

        table_rows = self._find_transaction_rows('Dividends', account_name)
        rows_by_currency = self._group_rows_by_currency(
                table_rows, expected_num_columns=4)
        transactions_by_currency = {}
        for currency, rows in rows_by_currency.items():
            transactions = []
            transactions_by_currency[currency] = transactions
            for cells in rows:
                date = cells[0].getText()
                try:
                    date = datetime.datetime.strptime(date, self._DATE_FORMAT)
                except ValueError:
                    logger.warning(
                            'Skipping transaction with invalid date %s.', date)
                    continue
                description = cells[1].getText()
                amount = self._parse_float(cells[2].getText())

                symbol = description.split()[0]
                memo = description

                transaction = model.InvestmentDividend(
                        date, symbol , amount, memo)
                transactions.append(transaction)

        return transactions_by_currency

    def _get_other_fees_from_activity_statement(self, account_name):
        logger.debug('Extracting other fees...')

        table_rows = self._find_transaction_rows('OtherFees', account_name)
        rows_by_currency = self._group_rows_by_currency(
                table_rows, expected_num_columns=4)
        transactions_by_currency = {}
        for currency, rows in rows_by_currency.items():
            transactions = []
            transactions_by_currency[currency] = transactions
            for cells in rows:
                date = cells[0].getText()
                try:
                    date = datetime.datetime.strptime(date, self._DATE_FORMAT)
                except ValueError:
                    logger.warning(
                            'Skipping transaction with invalid date %s.', date)
                    continue
                description = cells[1].getText()
                amount = self._parse_float(cells[2].getText())

                symbol = ''
                memo = description

                transaction = model.InvestmentMiscExpense(
                        date, symbol, amount, memo)
                transactions.append(transaction)

        return transactions_by_currency

    def _go_to_activity_statements(self):
        logger.debug('Opening activity statements page...')
        browser = self._browser
        browser.switch_to_default_content()
        browser.switch_to_frame('header')
        browser.find_element_by_id('Reports').click()
        browser.find_element_by_link_text('Activity').click()
        browser.switch_to_default_content()
        browser.switch_to_frame('content')

    def _open_activity_statement(self, account_name, start, end):
        self._go_to_activity_statements()
        browser = self._browser

        # Get activity statements form.
        try:
            form = browser.find_element_by_name('view_stmt')
        except exceptions.NoSuchElementException:
            raise fetch.FetchError('Activity statements form not found.')

        # Select account.
        account_select = ui.Select(form.find_element_by_name('accounts'))
        account_select.select_by_value(account_name)

        # Select simple report.
        type_select = ui.Select(form.find_element_by_name('templateId'))
        type_select.select_by_value('S')  # S = simple.

        # Select date range.
        period_select = ui.Select(form.find_element_by_name('activityPeriod'))
        period_select.select_by_value('R')  # R = range.
        from_date_element = form.find_element_by_name('fromDate')
        to_date_element = form.find_element_by_name('toDate')
        self._select_date_in_activity_statement(from_date_element, start)
        self._select_date_in_activity_statement(to_date_element, end)

        logger.debug('Opening activity statement report...')
        browser.find_element_by_css_selector('.button.continue').click()
        browser.switch_to_window('report')

    def _select_date_in_activity_statement(self, select_element, date):
        """Tries to select the specified date.

        If the requested date is not one of the options, goes back in time up to
        7 days until the requested date is found.

        Raises a fetch.FetchError if no date could be selected.
        """
        select = ui.Select(select_element)
        # Disable waiting for elements while checking the available options, in
        # order to speed up the value selection.
        self._browser.implicitly_wait(0)
        for go_back in range(7):
            adjusted_date = date - datetime.timedelta(go_back)
            formatted_adjusted_date = adjusted_date.strftime(
                    self._ACTIVITY_FORM_DATE_FORMAT)
            matching_options = self._browser.find_elements_by_xpath(
                    '//form[@name="view_stmt"]//select[@name="%s"]/'
                    'option[@value="%s"]' % (
                     select_element.get_attribute('name'),
                     formatted_adjusted_date))
            if matching_options:
                select.select_by_value(formatted_adjusted_date)
                break

        self._browser.implicitly_wait(self._WEBDRIVER_TIMEOUT)

    def _close_activity_statement(self):
        self._browser.close()
        self._browser.switch_to_window(self._main_window_handle)

    def _find_transaction_rows(self, table_name, account_name):
        # Wait for the report to load.
        self._browser.find_element_by_id(
                'tblAccountInformation_' + account_name)

        # We're using BeautifulSoup to parse the HTML directly, as using
        # WebDriver proved to be unreliable (hidden elements) and slow.
        html = self._browser.page_source
        soup = BeautifulSoup.BeautifulSoup(html)

        table_id = 'tbl%s_%s' % (table_name, account_name)
        table = soup.find('table', {'id': table_id})
        if not table:
            logger.debug('Couldn\'t find %s table.' % table_id)
            return []
        tbody = table.find('tbody')
        return tbody.findAll('tr')

    def _group_rows_by_currency(self, table_rows, expected_num_columns):
        """Groups the table rows by currency.

        @type table_rows: [BeautifulSoup.Tag]
        @param table_rows: The table rows.

        @type expected_num_columns: int
        @param expected_num_columns: The expected number of columns for each
                data row.

        @rtype: {str: [[BeautifulSoup.Tag],]}
        @returns: A dict which maps from currencies to a list of rows, where
                each row contains a list of cells.
        """
        rows_by_currency = collections.defaultdict(list)

        currency = None
        logger.debug('Scanning %i table rows...' % len(table_rows))
        for table_row in table_rows:
            cells = table_row.findAll('td')

            # Header row?
            if len(cells) == 0:
                logger.debug('Skipping empty table row.')
                continue

            # New currency?
            if len(cells) == 1 and cells[0]['class'] == 'currencyHeader':
                currency = cells[0].getText()
                continue

            # Totals row?
            if 'Total ' in cells[0].getText():
                continue

            # Invalid row?
            if len(cells) != expected_num_columns:
                logger.debug(
                        'Skipping invalid transaction row with %i cells. '
                        'Expected %i cells.' % (
                        len(cells), expected_num_columns))
                continue

            if not currency:
                logger.warning(
                        'Don\'t know the currency yet. '
                        'Skipping transaction row.')
                continue

            rows_by_currency[currency].append(cells)
            logger.debug('Added new row.')

        return rows_by_currency

    def _split_account_name(self, account_name):
        """Splits a combined account name in the form ACCNAME.CUR into the
        account name and currency parts.

        @type account_name: str
        @param account_name: The combined account name in the form ACCNAME.CUR.

        @rtype: (str, str)
        @returns: The account name and currency parts as a tuple.
        """
        last_dot = account_name.rfind('.')
        return account_name[:last_dot], account_name[last_dot + 1:]

    def _parse_float(self, string):
        return float(string.replace(',', ''))

    def _parse_int(self, string):
        return int(string.replace(',', ''))

    def _check_logged_in(self):
        if not self._logged_in:
            raise fetch.FetchError('Not logged in.')
