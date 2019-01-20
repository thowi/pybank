import collections
import csv
import datetime
import getpass
import logging
import os
import os.path
import re
import tempfile
import time

from bs4 import BeautifulSoup
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
    _MAIN_URL = 'https://gdcdyn.interactivebrokers.com/portal/'
    _ACTIVITY_FORM_DATE_FORMAT = '%Y-%m-%d'
    _DATE_TIME_FORMAT = '%Y-%m-%d, %H:%M:%S'
    _DATE_FORMAT = '%Y-%m-%d'
    _WEBDRIVER_TIMEOUT = 30
    _SESSION_TIMEOUT_S = 30 * 60

    def login(self, username=None, password=None):
        # Download to a custom location. Don't show dialog.
        self._download_dir = tempfile.mkdtemp()
        firefox_profile = webdriver.FirefoxProfile()
        firefox_profile.set_preference('browser.download.folderList', 2)
        firefox_profile.set_preference(
                'browser.download.manager.showWhenStarting', False)
        firefox_profile.set_preference(
                'browser.download.dir', self._download_dir)
        # CSV files are returned as text/plain.
        firefox_profile.set_preference(
                'browser.helperApps.neverAsk.saveToDisk', 'text/plain')

        if self._debug:
            self._browser = webdriver.Firefox(firefox_profile)
        else:
            # TODO: Fix the login and enable PhantomJs.
            #self._browser = webdriver.PhantomJS()
            self._browser = webdriver.Firefox(firefox_profile)

        self._browser.implicitly_wait(self._WEBDRIVER_TIMEOUT)
        # The user menu is only visible if the window is min 992px wide.
        self._browser.set_window_size(1000, 800)

        self._logged_in = False
        self._accounts_cache = None
        self._transactions_cache = {}

        browser = self._browser
        browser.get(self._LOGIN_URL)

        if not username:
            username = input('User name: ')

        if self.ask_and_restore_cookies(
                browser, username, self._SESSION_TIMEOUT_S):
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

            input("Please follow the log-in instructions and press enter.")

            if not self._is_logged_in():
                raise fetch.FetchError('Login failed.')

        # It is a bit silly to just sleep here, but other approaches failed, so
        # this is a simple fix.
        time.sleep(10)

        self.save_cookies(browser, username)
        self._logged_in = True
        self._username = username
        logger.info('Log-in sucessful.')

    def _is_logged_in(self):
        browser = self._browser
        browser.implicitly_wait(5)
        is_logged_in = fetch.is_element_present(
                lambda: fetch.find_element_by_text(browser, 'Client Portal'))
        # Often the portal isn't properly connected to the backend even if the
        # login was successful. Perform an additional check.
        try:
            is_connected = fetch \
                    .find_element_by_text(browser, 'Manage Your Account') \
                    .find_element_by_xpath('../..') \
                    .find_element_by_link_text('Statements') is not None
        except exceptions.NoSuchElementException:
            is_connected = False
        browser.implicitly_wait(self._WEBDRIVER_TIMEOUT)
        return is_logged_in and is_connected

    def logout(self):
        browser = self._browser
        browser.find_element_by_css_selector('nav a[title="User"]').click()
        browser.find_element_by_link_text('Log out').click()
        browser.quit()
        self._logged_in = False
        self._accounts_cache = None
        self._transactions_cache = {}
        self.delete_cookies(self._username)
        self._username = None

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
                '.page-head .account-numbers').text.strip()

        logger.debug('Getting balances from activity statement...')
        yesterday = datetime.datetime.today() - datetime.timedelta(1)
        accounts = []
        csv_dict = self._download_activity_statement(
                account_name, yesterday, yesterday)
        account_data = csv_dict['Account Information']['Data']['Account']
        account_name = account_data['__rows'][0][0]
        ending_cash = csv_dict['Cash Report']['Data']['Ending Cash']
        currencies = [k for k in list(ending_cash.keys()) if len(k) == 3]
        accounts = []
        for currency in currencies:
            name = '%s.%s' % (account_name, currency)
            balance = self._parse_float(ending_cash[currency]['__rows'][0][0])
            accounts.append(model.InvestmentsAccount(
                    name, currency, balance, yesterday))
        return accounts

    def get_transactions(self, account, start, end):
        account_name, currency = self._split_account_name(account.name)
        cache_key = account_name, start, end
        cached_transactions = self._transactions_cache.get(cache_key)
        if cached_transactions:
            transactions = cached_transactions[currency]
            logger.info('Found %i cached transactions for account %s.' % (
                    len(transactions), account))
            return transactions

        self._check_logged_in()

        end_inclusive = end - datetime.timedelta(1)
        csv_dict = self._download_activity_statement(
                account_name, start, end_inclusive)

        transfers = self._get_transfers(csv_dict, account_name)
        trades = self._get_trades(csv_dict, account_name)
        withholding_tax = self._get_withholding_tax(csv_dict, account_name)
        dividends = self._get_dividends(csv_dict, account_name)
        interest = self._get_interest(csv_dict, account_name)
        other_fees = self._get_other_fees(csv_dict, account_name)

        # Collect transactions for all currencies. Later select by currency.
        transactions_by_currency = collections.defaultdict(list)
        for category in (
                transfers, trades, withholding_tax, dividends, interest,
                other_fees):
            for category_currency, transactions in list(category.items()):
                transactions_by_currency[category_currency] += transactions

        self._transactions_cache[cache_key] = transactions_by_currency

        transactions = transactions_by_currency[currency]
        logger.info('Found %i transactions for account %s.' % (
                len(transactions), account))
        return transactions

    def _get_transfers(self, csv_dict, account_name):
        logger.debug('Extracting transfers...')

        transactions_by_currency = collections.defaultdict(list)
        for row in csv_dict['Deposits & Withdrawals']['Data']['__rows']:
            currency = row[0]
            if currency.startswith('Total'):
                continue
            date = datetime.datetime.strptime(row[1], self._DATE_FORMAT)
            kind = row[2]
            amount = self._parse_float(row[3])
            transaction = model.Payment(date, amount, payee=account_name)
            transactions_by_currency[currency].append(transaction)

        return transactions_by_currency

    def _get_trades(self, csv_dict, account_name):
        logger.debug('Extracting trades...')

        transactions_by_currency = collections.defaultdict(list)

        # Stock transactions:
        st = csv_dict['Trades']['Data']['Order']['Stocks'].get('__rows', [])
        for row in st:
            currency = row[0]
            symbol = row[1]
            date = datetime.datetime.strptime(row[2], self._DATE_TIME_FORMAT)
            quantity = self._parse_float(row[3])
            price = self._parse_float(row[4])
            proceeds = self._parse_float(row[6])
            # Commissions are reported as a negative number.
            commissions =  - self._parse_float(row[7])
            amount = proceeds - commissions
            if quantity >= 0:
                transaction = model.InvestmentSecurityPurchase(
                        date, symbol, quantity, price, commissions, amount)
            else:
                transaction = model.InvestmentSecuritySale(
                        date, symbol, -quantity, price, commissions, amount)
            transactions_by_currency[currency].append(transaction)

        # Forex transactions. Treated slightly differently from stocks.
        ft = csv_dict['Trades']['Data']['Order']['Forex'].get('__rows', [])
        for row in ft:
            currency = row[0]
            symbol = row[1]
            to_currency, from_currency = symbol.split('.')
            assert currency == from_currency
            date = datetime.datetime.strptime(row[2], self._DATE_TIME_FORMAT)
            quantity = self._parse_float(row[3])
            price = self._parse_float(row[4])
            proceeds = self._parse_float(row[6])
            # Commissions are reported as a negative number.
            commissions =  - self._parse_float(row[7])

            if quantity >= 0:
                buy_currency, sell_currency = to_currency, from_currency
                buy_amount, sell_amount = quantity, -proceeds
            else:
                buy_currency, sell_currency = from_currency, to_currency
                buy_amount, sell_amount = proceeds, -quantity
            memo = 'Buy %.2f %s, sell %.2f %s' % (
                    buy_amount, buy_currency, sell_amount, sell_currency)
            quantity = abs(quantity)
            transactions_by_currency[buy_currency].append(
                    model.InvestmentSecuritySale(
                            date, symbol, quantity, price, commissions,
                            buy_amount, memo))
            transactions_by_currency[sell_currency].append(
                    model.InvestmentSecurityPurchase(
                            date, symbol, quantity, price, 0, sell_amount,
                            memo))

            # Forex commissions are all billed to the main (CHF) account.
            # TODO: Find out the main currency/account. Don't just hardcode
            # CHF.
            transactions_by_currency['CHF'].append(model.InvestmentMiscExpense(
                    date, symbol, commissions, 'Forex commissions'))

        return transactions_by_currency

    def _get_withholding_tax(self, csv_dict, account_name):
        logger.debug('Extracting withholding tax...')

        transactions_by_currency = collections.defaultdict(list)
        for row in csv_dict['Withholding Tax']['Data']['__rows']:
            currency = row[0]
            if currency.startswith('Total'):
                continue
            date = datetime.datetime.strptime(row[1], self._DATE_FORMAT)
            description = row[2]
            amount = self._parse_float(row[3])
            symbol = re.split('[ (]', description)[0]
            memo = description
            transaction = model.InvestmentMiscExpense(
                   date, symbol, amount, memo)
            transactions_by_currency[currency].append(transaction)

        return transactions_by_currency

    def _get_dividends(self, csv_dict, account_name):
        logger.debug('Extracting dividends...')

        transactions_by_currency = collections.defaultdict(list)
        for row in csv_dict['Dividends']['Data']['__rows']:
            currency = row[0]
            if currency.startswith('Total'):
                continue
            date = datetime.datetime.strptime(row[1], self._DATE_FORMAT)
            description = row[2]
            amount = self._parse_float(row[3])
            symbol = re.split('[ (]', description)[0]
            memo = description
            transaction = model.InvestmentDividend(date, symbol, amount, memo)
            transactions_by_currency[currency].append(transaction)

        return transactions_by_currency

    def _get_interest(self, csv_dict, account_name):
        logger.debug('Extracting interest...')

        transactions_by_currency = collections.defaultdict(list)
        for row in csv_dict['Interest']['Data']['__rows']:
            currency = row[0]
            if currency.startswith('Total'):
                continue
            date = datetime.datetime.strptime(row[1], self._DATE_FORMAT)
            description = row[2]
            amount = self._parse_float(row[3])
            memo = description
            if amount < 0:
                transaction = model.InvestmentInterestExpense(
                        date, amount, memo)
            else:
                transaction = model.InvestmentInterestIncome(date, amount, memo)
            transactions_by_currency[currency].append(transaction)

        return transactions_by_currency

    def _get_other_fees(self, csv_dict, account_name):
        logger.debug('Extracting other fees...')

        transactions_by_currency = collections.defaultdict(list)
        for row in csv_dict['Fees']['Data']['Other Fees']['__rows']:
            currency = row[0]
            date = datetime.datetime.strptime(row[1], self._DATE_FORMAT)
            description = row[2]
            amount = self._parse_float(row[3])
            memo = description
            symbol = ''
            transaction = model.InvestmentMiscExpense(
                    date, symbol, amount, memo)
            transactions_by_currency[currency].append(transaction)

        return transactions_by_currency

    def _go_to_activity_statements(self):
        logger.debug('Opening activity statements page...')
        self._navigate_to('Reports', 'Statements')

    def _navigate_to(self, section, page):
        browser = self._browser
        browser.find_element_by_css_selector(
                'nav a[title="Application Menu"]').click()
        nav = browser.find_element_by_css_selector('nav .bar2-content ul')
        menu_link = nav.find_element_by_partial_link_text(section + '\n')
        menu_item = menu_link.find_element_by_xpath('..')
        if not self._is_element_displayed_now(
                lambda: menu_item.find_element_by_tag_name('ul')):
            # Open sub menu first.
            menu_link.click()
        sub_menu = menu_item.find_element_by_tag_name('ul')
        sub_menu.find_element_by_link_text(page).click()
        self._wait_to_finish_loading()

    def _download_activity_statement(self, account_name, start, end):
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

        # Select CSV format.
        format_select = fetch.find_element_by_text(body, 'Format') \
                .find_element_by_xpath('../..//select')
        ui.Select(format_select).select_by_visible_text('CSV')

        # Download report.
        logger.debug('Downloading activity statement report...')
        before_download_timestamp = time.time()
        body.find_element_by_link_text('Run Statement').click()

        # Find file on disk, load, parse CSV.
        try:
            csv_filename = lambda: self._get_downloaded_filename_newer_than(
                    before_download_timestamp)
            fetch.wait_until(csv_filename)
            filename = csv_filename()
            with open(filename, 'r') as csvfile:
                csv_dict = self._parse_csv_into_dict(csvfile)
                os.remove(filename)
                return csv_dict
        except fetch.OperationTimeoutError:
            raise fetch.FetchError('Activity statement failed to load.')

    def _get_downloaded_filename_newer_than(self, timestamp):
        for root, dirs, files in os.walk(self._download_dir):
            for file in files:
                # Ignore partial files.
                if file.endswith('.part'):
                    return None
                path = os.path.join(root, file)
                last_modified = os.path.getmtime(path)
                if last_modified > timestamp:
                    return path
        return None

    def _parse_csv_into_dict(self, csvfile):
        reader = csv.reader(csvfile, delimiter=',', quotechar='"')
        nested_default_dict = lambda: collections.defaultdict(nested_default_dict)
        csv_dict = nested_default_dict()
        for row in reader:
            cur = csv_dict
            for i, cell in enumerate(row):
                cur = cur[cell]
                if '__rows' not in cur:
                    cur['__rows'] = []
                cur['__rows'].append(row[i+1:])
        return csv_dict

    def _select_date_in_activity_statement(self, input_name, date):
        assert input_name in ('fromDate', 'toDate')
        # The date picker is a bit tricky. It's a jQuery Bootstrap date picker
        # and it will only open when the <input> is focused while the browser
        # window is in the foreground.
        # See e.g. https://stackoverflow.com/questions/21689309.
        # So instead, we manipulate it directly.

        # Weekends are not allowed.
        if date.weekday() > 4:
            if input_name == 'fromDate':
                # Select next week day.
                date = date + datetime.timedelta(7 - date.weekday())
            elif input_name == 'toDate':
                # Select previous week day.
                date = date - datetime.timedelta(date.weekday() - 4)
            # Today and dates in the future are not allowed.
            today = datetime.datetime.today()
            if date >= today:
                date = today - datetime.timedelta(1)
                # Now if today is also a weekend, select previous week day.
                if date.weekday() > 4:
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

    def _is_element_displayed_now(self, lookup_callable):
        """Doesn't wait for an element but returns if it's displayed now."""
        browser = self._browser
        browser.implicitly_wait(0)
        displayed = fetch.is_element_displayed(lookup_callable)
        browser.implicitly_wait(self._WEBDRIVER_TIMEOUT)
        return displayed

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
