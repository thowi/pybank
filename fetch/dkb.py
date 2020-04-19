# coding: utf-8

import datetime
import getpass
import logging
import re
import time

from selenium import webdriver
from selenium.common import exceptions
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import ui

import fetch.bank
import model


logger = logging.getLogger(__name__)


class DeutscheKreditBank(fetch.bank.Bank):
    """Fetcher for Deutsche Kreditbank (http://www.dkb.de/).

    The accounts for a user will be identified by the bank account number
    (digits) or the obfuscated credit card number (1234******5678).
    """
    _BASE_URL = 'https://www.dkb.de/banking'
    _DATE_FORMAT = '%d.%m.%Y'
    _DATE_FORMAT_SHORT = '%d.%m.%y'
    _WEBDRIVER_TIMEOUT = 10
    _SESSION_TIMEOUT_S = 12 * 60

    def login(self, username=None, password=None):
        if self._debug:
            self._browser = webdriver.Chrome()
        else:
            import selenium.webdriver.chrome.options
            chrome_options = selenium.webdriver.chrome.options.Options()
            chrome_options.add_argument("--headless")
            self._browser = webdriver.Chrome(chrome_options=chrome_options)

        self._browser.implicitly_wait(self._WEBDRIVER_TIMEOUT)
        self._browser.set_window_size(1000, 800)
        browser = self._browser

        self._logged_in = False
        self._accounts = None

        logger.info('Loading login page…')
        browser.get(self._BASE_URL)

        if not username:
            username = input('User: ')

        if self.ask_and_restore_cookies(
                browser, username, self._SESSION_TIMEOUT_S):
            browser.refresh()

        if not self._is_logged_in():
            if not password:
                password = getpass.getpass('PIN: ')
            try:
                login_form = browser.find_element_by_id('login')
            except exceptions.NoSuchElementException:
                raise fetch.FetchError('Login form not found.')
            username_input = login_form.find_element_by_id('loginInputSelector')
            username_input.send_keys(username)
            password_input = login_form.find_element_by_id('pinInputSelector')
            password_input.send_keys(password)
            logger.info('Logging in with user name %s…' % username)
            submit_button = login_form.find_element_by_id('buttonlogin')
            submit_button.click()
            self._wait_to_finish_loading()

            if not self._is_logged_in():
                raise fetch.FetchError('Login failed.')

        self.save_cookies(browser, username)
        self._logged_in = True
        self._username = username
        self._main_window_handle = browser.current_window_handle
        logger.info('Log-in sucessful.')

    def _is_logged_in(self):
        return fetch.is_element_present(
                lambda: self._browser.find_element_by_link_text('Finanzstatus'))

    def logout(self):
        self._browser.find_element_by_id('logout').click()
        self._browser.quit()
        self._logged_in = False
        self._accounts = None
        self.delete_cookies(self._username)
        self._username = None

    def get_accounts(self):
        self._check_logged_in()

        if self._accounts is not None:
            return self._accounts

        browser = self._browser

        logger.info('Loading accounts overview…')
        browser.find_element_by_link_text('Finanzstatus').click()
        self._wait_to_finish_loading()

        account_rows = browser.find_elements_by_css_selector(
                '.financialStatusModule tbody tr.mainRow')
        self._accounts = []
        for account_row in account_rows:
            try:
                cells = account_row.find_elements_by_tag_name('td')
                name = cells[0].find_elements_by_tag_name('div')[1].text \
                        .replace(' ', '')
                unused_acc_type = cells[1].text
                balance_date = self._parse_date(cells[2].text)
                balance = self._parse_balance(cells[3].text)
                if self._is_credit_card(name):
                    account = model.CreditCard(
                            name, 'EUR', balance, balance_date)
                else:
                    account = model.CheckingAccount(
                            name, 'EUR', balance, balance_date)
                self._accounts.append(account)
            except ValueError:
                logging.error('Invalid account row. %s' % account_row)

        logger.info('Found %i accounts.' % len(self._accounts))
        return self._accounts

    def get_transactions(self, account, start, end):
        is_credit_card = isinstance(account, model.CreditCard)
        if is_credit_card:
            return self._get_credit_card_transactions(account, start, end)
        else:
            return self._get_checking_account_transactions(account, start, end)

    def _get_checking_account_transactions(self, account, start, end):
        self._check_logged_in()
        browser = self._browser

        self._perform_transactions_search(account, start, end)
        self._switch_to_print_view_window()

        # Wait for page to be loaded.
        browser.find_element_by_tag_name('table')

        # Check that we're on the correct page.
        body_text = browser.find_element_by_tag_name('body').text
        if 'Kontoumsätze' not in body_text:
            raise fetch.FetchError('Not an account search result page.')
        if account.name not in body_text:
            raise fetch.FetchError('Account name not found in result page.')

        # Parse result page into transactions.
        logger.info('Extracting transaction…')
        transactions = self._get_transactions_from_checking_account_statement()
        logger.info('Found %i transactions.' % len(transactions))
        browser.close()
        browser.switch_to_window(self._main_window_handle)

        return transactions

    def _get_credit_card_transactions(self, account, start, end):
        self._check_logged_in()
        browser = self._browser

        self._perform_transactions_search(account, start, end)
        self._switch_to_print_view_window()

        body_text = browser.find_element_by_tag_name('body').text
        if 'Kreditkartenumsätze' not in body_text:
            raise fetch.FetchError('Not a credit card search result page.')
        # The full credit card number is shown on the transactions page. Until
        # here we only have a partially anonymized number.
        pattern = re.compile('Kreditkarte ' + account.name.replace('*', '.'))
        if not pattern.search(body_text):
            raise fetch.FetchError('Wrong credit card search result page.')

        # Parse result page into transactions.
        logger.info('Extracting transaction…')
        transactions = self._get_transactions_from_credit_card_statement()
        logger.info('Found %i transactions.' % len(transactions))
        browser.close()
        browser.switch_to_window(self._main_window_handle)

        return transactions

    def _perform_transactions_search(self, account, start, end):
        browser = self._browser
        is_credit_card = isinstance(account, model.CreditCard)
        logger.info('Opening account transactions page…')
        browser.find_element_by_link_text('Finanzstatus').click()
        self._wait_to_finish_loading()
        browser.find_element_by_link_text('Umsätze').click()
        self._wait_to_finish_loading()

        # Perform search.
        logger.info('Performing transactions search…')
        content = browser.find_element_by_class_name('content')
        form = content.find_element_by_tag_name('form')
        account_select_element = form.find_element_by_name('slAllAccounts')
        account_select = ui.Select(account_select_element)
        if is_credit_card:
            account_text = account.name + ' / Kreditkarte'
        else:
            account_text = fetch.format_iban(account.name) + ' / Girokonto'
        account_select.select_by_visible_text(account_text)
        # Selecting an account will reload the page.
        # Wait a little. Load the form again.
        time.sleep(5)
        content = browser.find_element_by_class_name('content')
        form = content.find_element_by_tag_name('form')
        formatted_start = start.strftime(self._DATE_FORMAT)
        end_inclusive = end - datetime.timedelta(1)
        formatted_end = end_inclusive.strftime(self._DATE_FORMAT)
        content = browser.find_element_by_class_name('content')
        form = content.find_element_by_tag_name('form')
        if is_credit_card:
            form.find_element_by_css_selector('input[value="DATE_RANGE"]') \
                    .click()
        else:
            form.find_element_by_css_selector('input[value="1"]').click()
        from_name = 'postingDate' if is_credit_card else 'transactionDate'
        from_input = form.find_element_by_name(from_name)
        from_input.click()
        from_input.clear()
        from_input.send_keys(formatted_start)
        to_name = 'toPostingDate' if is_credit_card else 'toTransactionDate'
        to_input = form.find_element_by_name(to_name)
        to_input.click()
        to_input.clear()
        to_input.send_keys(formatted_end)
        form.find_element_by_id('searchbutton').click()
        self._wait_to_finish_loading()

    def _get_transactions_from_checking_account_statement(self):
        transactions = []
        rows = self._browser.find_elements_by_css_selector(
                'table tbody tr.mainRow')
        for row in rows:
            try:
                cells = row.find_elements_by_tag_name('td')

                # Date. First row is entry date, second is value date.
                date_text = cells[0].text.split('\n')[1]
                date = self._parse_date(date_text)

                # Payee and memo.
                details_lines = fetch.normalize_text(cells[1].text).split('\n')
                unused_transaction_type = details_lines[0]
                payee = '\n'.join(details_lines[1:2])  # This line might not exist.
                memo = '\n'.join(details_lines[2:])  # Might be empty.
                payee_lines = cells[2].text.split('\n') + ['']
                payee_account, payee_clearing = payee_lines[:2]
                if payee_account:
                    memo += '\nAccount: %s' % payee_account
                if payee_clearing:
                    memo += '\nClearing: %s' % payee_clearing

                # Amount
                amount = fetch.parse_decimal_number(cells[3].text, 'de_DE')

                transactions.append(model.Payment(date, amount, payee, memo))
            except ValueError as e:
                logger.warning(
                        'Skipping invalid row: %s. Error: %s' % (row.text, e))
                raise

        return transactions

    def _get_transactions_from_credit_card_statement(self):
        transactions = []
        rows = self._browser.find_elements_by_css_selector('table tr')
        # Skip header row.
        rows = rows[1:]
        for row in rows:
            try:
                cells = row.find_elements_by_tag_name('td')

                # Date. First row is value date, second is voucher date.
                date_text = cells[1].text.split('\n')[0]
                date = self._parse_date(date_text)

                # Memo.
                memo = fetch.normalize_text(cells[2].text)

                # Amount.
                amounts = cells[3].text.split('\n')
                amount = fetch.parse_decimal_number(amounts[0], 'de_DE')

                # Currency.
                currencies = cells[4].text.split('\n')
                if len(currencies) > 1 and len(amounts) > 1:
                    original_amount = fetch.parse_decimal_number(
                            amounts[1], 'de_DE')
                    original_currency = currencies[1]
                    memo += '\nOriginal amount: %s %.2f' % (
                            original_currency, original_amount)

                transactions.append(model.Payment(date, amount, memo=memo))
            except ValueError as e:
                logger.warning(
                        'Skipping invalid row: %s. Error: %s' % (row.text, e))
                raise

        return transactions

    def _switch_to_print_view_window(self):
        logger.debug('Switching to print view…')
        browser = self._browser
        browser.find_element_by_css_selector('[title="Drucken"]').click()
        for handle in browser.window_handles:
            if handle != self._main_window_handle:
                browser.switch_to_window(handle)
                break
        if browser.current_window_handle == self._main_window_handle:
            raise fetch.FetchError('Print view window not found.')

    def _is_credit_card(self, name):
        return '******' in name

    def _parse_balance(self, balance):
        if balance.endswith('S'):  # Debit.
            balance = '-' + balance
        balance = balance.replace(' S', '').replace(' H', '')
        return fetch.parse_decimal_number(balance, 'de_DE')

    def _parse_date(self, date_string):
        try:
            return datetime.datetime.strptime(date_string, self._DATE_FORMAT)
        except ValueError:
            return datetime.datetime.strptime(
                    date_string, self._DATE_FORMAT_SHORT)

    def _check_logged_in(self):
        if not self._logged_in:
            raise fetch.FetchError('Not logged in.')

    def _get_element_or_none(self, lookup_callable, wait_time=None):
        if wait_time is not None:
            self._browser.implicitly_wait(0)
        result = fetch.get_element_or_none(lookup_callable)
        if wait_time is not None:
            self._browser.implicitly_wait(self._WEBDRIVER_TIMEOUT)
        return result

    def _wait_to_finish_loading(self):
        """Waits for the loading indicator to disappear on the current page."""
        browser = self._browser
        # Disable waiting for elements to speed up the operation.
        browser.implicitly_wait(0)

        overlay = lambda: browser.find_element_by_class_name('ajax_loading')
        fetch.wait_for_element_to_appear_and_disappear(overlay)

        browser.implicitly_wait(self._WEBDRIVER_TIMEOUT)
