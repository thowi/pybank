#!/usr/bin/python

import collections
import datetime
import getpass
import logging
import tempfile
import time

import BeautifulSoup
from selenium import webdriver
from selenium.common import exceptions
from selenium.webdriver.support import ui
import fetch
import fetch.bank
import model


logger = logging.getLogger(__name__)


class InteractiveBrokers(fetch.bank.Bank):
    """Fetcher for Interactive Brokers (https://www.interactivebrokers.com/)."""
    _LOGIN_URL = 'https://gdcdyn.interactivebrokers.com/sso/Login'
    _MAIN_URL = (
            'https://gdcdyn.interactivebrokers.com/AccountManagement/'
            'AmAuthentication')
    _ACTIVITY_FORM_DATE_FORMAT = '%Y-%m-%d'
    _DATE_TIME_FORMAT = '%Y-%m-%d, %H:%M:%S'
    _DATE_FORMAT = '%Y-%m-%d'
    _WEBDRIVER_TIMEOUT = 30

    def login(self, username=None, password=None):
        if self._debug:
            self._browser = webdriver.Firefox()
        else:
            # TODO: Fix the login and enable PhantomJs.
            #self._browser = webdriver.PhantomJS()
            self._browser = webdriver.Firefox()
        self._browser.implicitly_wait(self._WEBDRIVER_TIMEOUT)
        # The user menu is only visible if the window is min 992px wide.
        self._browser.set_window_size(1000, 800)

        self._logged_in = False
        self._accounts_cache = None
        self._transactions_cache = {}

        browser = self._browser
        browser.get(self._LOGIN_URL)

        if not username:
            username = raw_input('User name: ')

        if self.ask_and_restore_cookies(browser, username):
            browser.get(self._MAIN_URL)

        if not self._is_logged_in():
            if not password:
                password = getpass.getpass('Password: ')

            # First login phase: User and password.
            try:
                login_form = browser.find_element_by_name('loginform')
            except exceptions.NoSuchElementException:
                raise fetch.FetchError('Login form not found.')
            login_form.find_element_by_name('user_name').send_keys(username)
            login_form.find_element_by_name('password').send_keys(password)
            # Weirldy, the login button has to be clicked twice.
            login_form.find_element_by_id('submitForm').click()
            login_form.find_element_by_id('submitForm').click()

            raw_input("Please follow the log-in instructions and press enter.")

            if not self._is_logged_in():
                raise fetch.FetchError('Login failed.')

        # It is a bit silly to just sleep here, but other approaches failed, so
        # this is a simple fix.
        time.sleep(10)

        self.save_cookies(browser, username)
        self._logged_in = True
        self._main_window_handle = browser.current_window_handle
        logger.info('Log-in sucessful.')

    def _is_logged_in(self):
        self._browser.implicitly_wait(5)
        is_logged_in = fetch.is_element_present(
                lambda: fetch.find_element_by_text(
                        self._browser, 'Account Management'))
        self._browser.implicitly_wait(self._WEBDRIVER_TIMEOUT)
        return is_logged_in

    def logout(self):
        browser = self._browser
        browser.find_element_by_css_selector(
                '#userSettings user-options a').click()
        browser.find_element_by_link_text('Log Out').click()
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

        logger.debug('Getting account name...')
        self._navigate_to('Settings', 'Account Settings')
        account_name = browser.find_element_by_css_selector(
                '.page-content .account-numbers').text.strip()

        logger.debug('Getting balances from activity statement...')
        yesterday = datetime.datetime.today() - datetime.timedelta(1)
        accounts = []
        self._open_activity_statement(account_name, yesterday, yesterday)
        currencies_and_balances = \
                self._get_currencies_and_balances_from_activity_statement(
                        account_name)
        for currency, balance in currencies_and_balances:
            name = '%s.%s' % (account_name, currency)
            accounts.append(model.InvestmentsAccount(
                    name, currency, balance, yesterday))

        return accounts

    def _get_currencies_and_balances_from_activity_statement(
            self, account_name):
        logger.debug('Extracting currencies and balances...')

        table_rows = self._find_cash_rows(account_name)
        rows_by_currency = self._group_rows_by_currency(
                table_rows, expected_num_columns=6)
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
        # TODO: Actually store data in the cache. This is a no-op right now.
        cached_transactions = self._transactions_cache.get(cache_key)
        if cached_transactions:
            return cached_transactions[currency]

        self._check_logged_in()

        end_inclusive = end - datetime.timedelta(1)
        self._open_activity_statement(account_name, start, end_inclusive)

        transfers = self._get_transfers_from_activity_statement(account_name)
        trades = self._get_trades_from_activity_statement(account_name)
        withholding_tax = self._get_withholding_tax_from_activity_statement(
                account_name)
        dividends = self._get_dividends_from_activity_statement(account_name)
        interest = self._get_interest_from_activity_statement(account_name)
        other_fees = self._get_other_fees_from_activity_statement(account_name)

        # We're only interested in the current currency.
        transactions = []
        for category in (
                transfers, trades, withholding_tax, dividends, interest,
                other_fees):
            transactions_by_currency = category.get(currency)
            if transactions_by_currency:
                transactions += transactions_by_currency

        logger.info('Found %i transactions.' % len(transactions))
        return transactions

    def _get_transfers_from_activity_statement(self, account_name):
        logger.debug('Extracting transfers...')

        table_rows = self._find_transfer_rows(account_name)
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
                            'Skipping transfer with invalid date %s.', date)
                    continue
                description = cells[1].getText()
                amount = self._parse_float(cells[2].getText())
                unused_code = cells[3].getText()

                transaction = model.Payment(date, amount, payee=account_name)
                transactions.append(transaction)

        return transactions_by_currency

    def _get_trades_from_activity_statement(self, account_name):
        logger.debug('Extracting trades...')

        table_rows = self._find_trade_rows(account_name)
        rows_by_currency = self._group_rows_by_currency(
                table_rows, expected_num_columns=10)
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
                quantity = self._parse_int(cells[2].getText())
                price = self._parse_float(cells[3].getText())
                proceeds = self._parse_float(cells[4].getText())
                commissions_and_tax = self._parse_float(cells[5].getText())
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

        table_rows = self._find_withholding_tax_rows(account_name)
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

        dividend_rows = self._find_dividend_rows(account_name)
        div_lieu_rows = self._find_in_lieu_of_dividend_rows(account_name)
        table_rows = dividend_rows + div_lieu_rows
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
                        date, symbol, amount, memo)
                transactions.append(transaction)

        return transactions_by_currency

    def _get_interest_from_activity_statement(self, account_name):
        logger.debug('Extracting interest...')

        paid_rows = self._find_broker_interest_paid_rows(account_name)
        received_rows = self._find_broker_interest_received_rows(account_name)
        rows = paid_rows + received_rows
        rows_by_currency = self._group_rows_by_currency(
                rows, expected_num_columns=4)
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
                memo = cells[1].getText()
                amount = self._parse_float(cells[2].getText())

                if amount < 0:
                    transactions.append(model.InvestmentInterestExpense(
                            date, amount, memo))
                else:
                    transactions.append(model.InvestmentInterestIncome(
                            date, amount, memo))

        return transactions_by_currency

    def _get_other_fees_from_activity_statement(self, account_name):
        logger.debug('Extracting other fees...')

        table_rows = self._find_other_fee_rows(account_name)
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
        self._navigate_to('Reports', 'Statements')

    def _navigate_to(self, section, page):
        browser = self._browser
        nav = browser.find_element_by_class_name('side-navigation')
        menu_item = fetch.find_element_by_text(nav, section) \
                .find_element_by_xpath('../..')
        if 'nav-active' not in menu_item.get_attribute('class').split():
            menu_item.find_element_by_tag_name('a').click()
        nav.find_element_by_link_text(page).click()
        self._wait_to_finish_loading()

    def _open_activity_statement(self, account_name, start, end):
        self._go_to_activity_statements()
        browser = self._browser

        # Get activity statements form.
        try:
            body = browser.find_element_by_css_selector('section.panel')
        except exceptions.NoSuchElementException:
            raise fetch.FetchError('Activity statements form not found.')

        # Check statement type.
        if (body.find_element_by_id('statementCategory').get_attribute('value')
            != 'string:DEFAULT_STATEMENT' or
            body.find_element_by_id('statementType').get_attribute('value')
            != 'string:DEFAULT_ACTIVITY'):
            raise fetch.FetchError('Expected activity statement type.')

        # Select date range.
        period_select = fetch.find_element_by_text(body, 'Period') \
                .find_element_by_xpath('../..//select')
        ui.Select(period_select).select_by_value('string:DATE_RANGE')
        # Switching period will refresh the form.
        self._wait_to_finish_loading()
        body = browser.find_element_by_css_selector('section.panel')
        self._select_date_in_activity_statement('fromDate', start)
        self._select_date_in_activity_statement('toDate', end)

        # Open report.
        logger.debug('Opening activity statement report...')
        body.find_element_by_link_text('RUN STATEMENT').click()
        self._wait_to_finish_loading()

        # Expand all sections.
        try:
            body = browser.find_element_by_css_selector('section.panel')
        except exceptions.NoSuchElementException:
            raise fetch.FetchError('Activity statement failed to load.')
        body.find_element_by_link_text('Expand All').click()

    def _select_date_in_activity_statement(self, input_name, date):
        assert input_name in ('fromDate', 'toDate')
        # The date picker is a bit tricky. It's a jQuery Bootstrap date pickers
        # and it will only open when the <input> is focused while the browser
        # window is in the foreground.
        # See e.g. https://stackoverflow.com/questions/21689309.
        # So instead, we manipulate it directly.

        # Weekends are not allowed.
        if date.weekday() > 4:
            if input_name == 'fromDate':
                date = date + datetime.timedelta(7 - date.weekday())
            elif input_name == 'toDate':
                date = date - datetime.timedelta(date.weekday() - 4)

        # January 1st is not allowed.
        if date.month == 1 and date.day == 1:
            date = date.replace(day=2)

        formatted_date = date.strftime(self._ACTIVITY_FORM_DATE_FORMAT)
        self._browser.execute_script(
                '$("input[name=\'%s\']")'
                '.datepicker("show")'
                '.datepicker("update", "%s")'
                '.datepicker("hide")' % (input_name, formatted_date))

    def _wait_to_finish_loading(self):
        """Waits for the loading indicator to disappear on the current page."""
        browser = self._browser
        # Disable waiting for elements to speed up the operation.
        browser.implicitly_wait(0)

        overlay = lambda: browser.find_element_by_tag_name('loading-overlay')
        fetch.wait_for_element_to_appear_and_disappear(overlay)

        browser.implicitly_wait(self._WEBDRIVER_TIMEOUT)

    def _find_transfer_rows(self, account_name):
        return self._find_transaction_rows(
                'tblDepositsWithdrawals_%sBody' % account_name, account_name)

    def _find_cash_rows(self, account_name):
        return self._find_transaction_rows(
                'tblCashReport_%sBody' % account_name, account_name)

    def _find_trade_rows(self, account_name):
        return self._find_transaction_rows(
                'tblTransactions_%sBody' % account_name, account_name)

    def _find_withholding_tax_rows(self, account_name):
        return self._find_transaction_rows(
                'tblWithholdingTax_%sBody' % account_name, account_name)

    def _find_dividend_rows(self, account_name):
        return self._find_transaction_rows(
                'tblDividends_%sBody' % account_name, account_name)

    def _find_in_lieu_of_dividend_rows(self, account_name):
        return self._find_transaction_rows(
                'tblPaymentInLieuOfDividends_%sBody' % account_name,
                account_name)

    def _find_broker_interest_paid_rows(self, account_name):
        return self._find_transaction_rows(
                'tblBrokerInterestPaid_%sBody' % account_name, account_name)

    def _find_broker_interest_received_rows(self, account_name):
        return self._find_transaction_rows(
                'tblBrokerInterestReceived_%sBody' % account_name, account_name)

    def _find_other_fee_rows(self, account_name):
        return self._find_transaction_rows(
                'tblOtherFees_%sBody' % account_name, account_name)

    def _find_transaction_rows(self, table_container_id, account_name):
        # Make sure the page is loaded.
        self._browser.find_element_by_id(
                'tblAccountInformation_' + account_name + 'Body')

        # We're using BeautifulSoup to parse the HTML directly, as using
        # WebDriver proved to be unreliable (hidden elements) and slow.
        html = self._browser.page_source
        soup = BeautifulSoup.BeautifulSoup(html)

        table_container = soup.find('div', {'id': table_container_id})
        if not table_container:
            logger.debug(
                    'Couldn\'t find %s table. Maybe there are no transactions '
                    'of that type?' % table_container_id)
            return []
        return table_container.find('table').findAll('tr')

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
                logger.debug('Skipping empty table or header row.')
                continue

            # New currency?
            if (len(cells) == 1 and
                    'header-currency' in cells[0]['class'].split()):
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
            logger.debug('Added new row for currency %s.' % currency)

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
