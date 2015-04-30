#!/usr/bin/python
# coding: utf-8

import datetime
import getpass
import logging
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
    _BASE_URL = 'https://banking.dkb.de/dkb/-'
    _CHECKING_ACCOUNT_CSV_PATH = (
            '?$part=DkbTransactionBanking.content.banking.Transactions.Search'
            '&$event=csvExport')
    _CREDIT_CARD_CSV_PATH = (
            '?$part=DkbTransactionBanking.content.creditcard.'
            'CreditcardTransactionSearch'
            '&$event=csvExport')
    _DATE_FORMAT = '%d.%m.%Y'
    _DATE_FORMAT_SHORT = '%d.%m.%y'
    _WEBDRIVER_TIMEOUT = 10

    def login(self, username=None, password=None):
        if self._debug:
            self._browser = webdriver.Firefox()
        else:
            self._browser = webdriver.PhantomJS()
        self._browser.implicitly_wait(self._WEBDRIVER_TIMEOUT)
        self._browser.set_window_size(800, 800)

        self._logged_in = False
        self._accounts = None

        if not username:
            username = raw_input('User: ')

        if not password:
            password = getpass.getpass('PIN: ')

        browser = self._browser

        logger.info('Loading login page...')
        browser.get(self._BASE_URL)

        # Login.
        try:
            login_form = browser.find_element_by_id('login')
        except exceptions.NoSuchElementException:
            raise fetch.FetchError('Login form not found.')
        username_input = login_form.find_element_by_id('loginInputSelector')
        username_input.send_keys(username)
        password_input = login_form.find_element_by_id('pinInputSelector')
        password_input.send_keys(password)
        logger.info('Logging in with user name %s...' % username)
        submit_button = login_form.find_element_by_id('buttonlogin')
        submit_button.click()

        # Login successful?
        status_link = browser.find_element_by_link_text('Finanzstatus')
        if not status_link:
            raise fetch.FetchError('Login failed.')

        self._logged_in = True
        self._main_window_handle = browser.current_window_handle
        logger.info('Log-in sucessful.')

    def logout(self):
        self._browser.find_element_by_id('logout').click()
        self._browser.quit()
        self._logged_in = False
        self._accounts = None

    def get_accounts(self):
        self._check_logged_in()

        if self._accounts is not None:
            return self._accounts

        browser = self._browser

        logger.info('Loading accounts overview...')
        browser.find_element_by_link_text('Finanzstatus').click()

        accounts_section = browser.find_element_by_class_name(
                'financialStatusModule')
        account_rows = accounts_section \
                .find_element_by_tag_name('tbody') \
                .find_elements_by_tag_name('tr')
        # Skip last (summary) row.
        account_rows.pop()
        self._accounts = []
        for account_row in account_rows:
            try:
                cells = account_row.find_elements_by_tag_name('td')
                name = cells[0].find_element_by_tag_name('strong').text
                unused_acc_type = cells[1].text
                balance_date = self._parse_date(cells[2].text)
                balance_cell = account_row.find_element_by_tag_name('th')
                balance = self._parse_balance(balance_cell.text)
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

        logger.info('Opening checking account transactions page...')
        browser.find_element_by_link_text(u'Finanzstatus').click()
        browser.find_element_by_link_text(u'Kontoumsätze').click()

        # Perform search.
        logger.info('Performing transactions search...')
        formatted_start = start.strftime(self._DATE_FORMAT)
        end_inclusive = end - datetime.timedelta(1)
        formatted_end = end_inclusive.strftime(self._DATE_FORMAT)
        # TODO: Support multiple accounts.
        content = browser.find_element_by_class_name('content')
        form = content.find_element_by_tag_name('form')
        from_input = form.find_element_by_name('transactionDate')
        from_input.click()
        from_input.clear()
        from_input.send_keys(formatted_start)
        to_input = form.find_element_by_name('toTransactionDate')
        to_input.click()
        to_input.clear()
        to_input.send_keys(formatted_end)
        form.find_element_by_id('searchbutton').click()

        # Switch to print view to avoid pagination.
        self._switch_to_print_view_window()

        if account.name not in browser.find_element_by_tag_name('body').text:
            raise fetch.FetchError('Account name not found in result page.')

        # Parse result page into transactions.
        logger.info('Extracting transaction...')
        transactions = self._get_transactions_from_checking_account_statement()
        logger.info('Found %i transactions.' % len(transactions))
        browser.close()
        browser.switch_to_window(self._main_window_handle)

        return transactions

    def _get_credit_card_transactions(self, account, start, end):
        self._check_logged_in()
        browser = self._browser

        logger.info('Opening credit card transactions page...')
        browser.find_element_by_link_text('Finanzstatus').click()
        browser.find_element_by_link_text(u'Kreditkartenumsätze').click()

        # Perform search.
        logger.info('Performing transactions search...')
        formatted_start = start.strftime(self._DATE_FORMAT)
        end_inclusive = end - datetime.timedelta(1)
        formatted_end = end_inclusive.strftime(self._DATE_FORMAT)
        content = browser.find_element_by_class_name('content')
        form = content.find_element_by_tag_name('form')
        account_select_element = self._get_element_or_none(
                lambda: form.find_element_by_name('slCreditCard'), wait_time=0)
        if account_select_element:
            account_select = ui.Select(account_select_element)
            account_select.select_by_visible_text(
                    account.name + ' / Kreditkarte')
            # Selecting a credit card will reload the page.
            # Wait a little. Load the form again.
            time.sleep(5)
            content = browser.find_element_by_class_name('content')
            form = content.find_element_by_tag_name('form')
        # Search for a data range.
        form.find_element_by_id('searchPeriod.0').click()
        # Click/send_keys wasn't reliable when the browser window was in the
        # background. Setting the value directly.
        from_input = form.find_element_by_name('postingDate')
        from_input.click()
        browser.execute_script(
                'document.getElementById("%s").value = "%s"' %
                (from_input.get_attribute('id'), formatted_start))
        to_input = form.find_element_by_name('toPostingDate')
        to_input.click()
        browser.execute_script(
                'document.getElementById("%s").value = "%s"' %
                (to_input.get_attribute('id'), formatted_end))
        form.find_element_by_id('searchbutton').click()

        # Switch to print view to avoid pagination.
        self._switch_to_print_view_window()

        body_text = browser.find_element_by_tag_name('body').text
        if u'Kreditkartenumsätze' not in body_text:
            raise fetch.FetchError('Not a credit card search result page.')
        if u'Kreditkarte ' + account.name not in body_text:
            raise fetch.FetchError('Wrong credit card search result page.')

        # Parse result page into transactions.
        logger.info('Extracting transaction...')
        transactions = self._get_transactions_from_credit_card_statement()
        logger.info('Found %i transactions.' % len(transactions))
        browser.close()
        browser.switch_to_window(self._main_window_handle)

        return transactions

    def _get_transactions_from_checking_account_statement(self):
        transactions = []
        table = self._browser.find_element_by_tag_name('table')
        rows = table.find_elements_by_tag_name('tr')
        # Skip header row.
        rows = rows[1:]
        for row in rows:
            try:
                cells = row.find_elements_by_tag_name('td')

                # Date. First row is entry date, second is value date.
                date_text = cells[0].text.split('\n')[1]
                date = self._parse_date(date_text)

                # Payee and memo.
                details_lines = fetch.normalize_text(cells[1].text).split('\n')
                unused_transaction_type = details_lines[0]
                payee = details_lines[1]
                memo = '\n'.join(details_lines[2:])
                payee_lines = cells[2].text.split('\n') + ['']
                payee_account, payee_clearing = payee_lines[:2]
                if payee_account:
                    memo += '\nAccount: %s' % payee_account
                if payee_clearing:
                    memo += '\nClearing: %s' % payee_clearing

                # Amount
                amount = fetch.parse_decimal_number(cells[3].text, 'de_DE')

                transactions.append(model.Payment(date, amount, payee, memo))
            except ValueError, e:
                logger.warning(
                        'Skipping invalid row: %s. Error: %s' % (row.text, e))
                raise

        return transactions

    def _get_transactions_from_credit_card_statement(self):
        transactions = []
        table = self._browser.find_element_by_tag_name('table')
        rows = table.find_elements_by_tag_name('tr')
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
            except ValueError, e:
                logger.warning(
                        'Skipping invalid row: %s. Error: %s' % (row.text, e))
                raise

        return transactions

    def _switch_to_print_view_window(self):
        logger.debug('Switching to print view...')
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
