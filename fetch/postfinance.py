#!/usr/bin/python

import datetime
import getpass
import logging
import re

from selenium import webdriver
from selenium.common import exceptions
from selenium.webdriver.support import ui

import fetch.bank
import model


logger = logging.getLogger(__name__)


class PostFinance(fetch.bank.Bank):
    """Fetcher for PostFinance (http://www.postfincance.ch/)."""
    _LOGIN_URL = (
            'https://e-finance.postfinance.ch/secure/fp/html/'
            'e-finance?login&p_spr_cd=4')
    _OVERVIEW_URL_ENGLISH = (
            'https://e-finance.postfinance.ch/secure/fp/html/e-finance?lang=en')
    _DATE_FORMAT = '%d.%m.%Y'
    _CREDIT_CARD_JS_LINK_PATTERN = re.compile(
            r'.*detailbew\(\'(\d+)\',\'(\d+)\'\)')
    _CREDIT_CARD_TX_HEADER_PATTERN = re.compile(
            r'Transactions in the (current|previous billing|'
            'last-but-one billing) period')

    def login(self, username=None, password=None):
        if self._debug:
            self._browser = webdriver.Firefox()
        else:
            self._browser = webdriver.PhantomJS()
        self._browser.implicitly_wait(10)
        self._browser.set_window_size(800, 800)
        self._logged_in = False
        self._accounts = None

        browser = self._browser
        browser.get(self._LOGIN_URL)

        if not username:
            username = raw_input('E-Finance number: ')

        if not password:
            password = getpass.getpass('Password: ')

        # First login phase: User and password.
        try:
            login_form = browser.find_element_by_name('login')
        except exceptions.NoSuchElementException:
            raise fetch.FetchError('Login form not found.')
        login_form.find_element_by_name('p_et_nr').send_keys(username)
        login_form.find_element_by_name('p_passw').send_keys(password)
        login_form.submit()

        # Login successful?
        try:
            error_element = browser.find_element_by_class_name('error')
            logger.error('Login failed:\n%s' % error_element.text)
            raise fetch.FetchError('Login failed.')
        except exceptions.NoSuchElementException:
            pass

        # Second login phase: Challenge and security token.
        try:
            challenge_element = browser.find_element_by_id('challenge')
        except exceptions.NoSuchElementException:
            raise fetch.FetchError('Security challenge not found.')
        print 'Challenge:', challenge_element.text
        token = raw_input('Login token: ')
        try:
            login_form = browser.find_element_by_name('login')
        except exceptions.NoSuchElementException:
            raise fetch.FetchError('Login token form not found.')
        login_form.find_element_by_name('p_si_nr').send_keys(token)
        login_form.submit()

        # Logout warning?
        if 'Logout reminder' in browser.page_source:
            logger.info('Confirming logout reminder...')
            try:
                login_form = browser.find_element_by_name('login')
            except exceptions.NoSuchElementException:
                raise fetch.FetchError('Logout reminder form not found.')
            login_form.submit()

        # Ensure we're using the English interface.
        selected_language = self._extract_language_from_page()
        if selected_language != 'en':
            raise fetch.FetchError(
                    'Wrong display language "%s" instead of "en".'
                    % selected_language)

        # Login successful?
        try:
            browser.find_element_by_link_text('Accounts and assets')
        except exceptions.NoSuchElementException:
            raise fetch.FetchError('Login failed.')

        self._logged_in = True
        logger.info('Log-in sucessful.')

    def logout(self):
        self._browser.find_element_by_id('logoutLink').click()
        self._browser.quit()
        self._logged_in = False
        self._accounts = None

    def get_accounts(self):
        if self._accounts is not None:
            return self._accounts

        accounts = []
        accounts += self._fetch_accounts()
        accounts += self._fetch_credit_cards()
        self._accounts = accounts

        logger.info('Found %i accounts.' % len(self._accounts))
        return self._accounts

    def _fetch_accounts(self):
        self._check_logged_in()

        browser = self._browser

        logger.info('Loading accounts overview...')
        browser.find_element_by_link_text('Accounts and assets').click()
        content = browser.find_element_by_id('content')
        
        # Expand Assets list, if required.
        asset_accounts = content.find_element_by_class_name('assetaccounts')
        if 'multiple-items-minimized' in asset_accounts.get_attribute('class'):
            asset_accounts.find_element_by_class_name('aa-button-open').click()

        accounts = []
        try:
            assets_widget = content.find_element_by_class_name('assets-widget')
            account_tables = assets_widget.find_elements_by_class_name(
                'table-total')
            payment_accounts_table = account_tables[0]
            asset_accounts_table = account_tables[1]
            for account_table in payment_accounts_table, asset_accounts_table:
                tbody = account_table.find_element_by_tag_name('tbody')
                account_rows = tbody.find_elements_by_tag_name('tr')
                for account_row in account_rows:
                    cells = account_row.find_elements_by_tag_name('td')
                    name_and_type = cells[2].text
                    name = name_and_type.split()[0]
                    acc_type = ' '.join(name_and_type.split()[1:])
                    currency = cells[4].text.strip()
                    balance = self._parse_balance(cells[5].text.strip())
                    balance_date = datetime.datetime.now()
                    if acc_type == 'Private':
                        account = model.CheckingAccount(
                                name, balance, balance_date)
                    elif acc_type == 'E-Deposito':
                        account = model.SavingsAccount(
                                name, balance, balance_date)
                    elif acc_type in ('E-trading', 'Safe custody deposit'):
                        account = model.InvestmentsAccount(
                                name, balance, balance_date)
                    else:
                        logger.warning(
                                'Skipping account %s with unknown type %s.' %
                                (name, acc_type))
                        continue
                    accounts.append(account)
        except (exceptions.NoSuchElementException, AttributeError, IndexError):
            raise fetch.FetchError('Couldn\'t load accounts.')
        return accounts

    def _fetch_credit_cards(self):
        self._check_logged_in()

        browser = self._browser

        logger.info('Loading credit cards overview...')
        browser.find_element_by_link_text('Credit cards').click()
        content = browser.find_element_by_id('content')

        accounts = []
        try:
            account_table = content.find_element_by_class_name('table-total')
            tbody = account_table.find_element_by_tag_name('tbody')
            account_rows = tbody.find_elements_by_tag_name('tr')
            for account_row in account_rows:
                cells = account_row.find_elements_by_tag_name('td')
                name = cells[1].text.replace(' ', '')
                acc_type = cells[2].text.strip()
                currency = cells[4].text.strip()
                balance = self._parse_balance(cells[5].text.strip())
                balance_date = datetime.datetime.now()
                if (acc_type.startswith('Visa') or
                    acc_type.startswith('Master')):
                    account = model.CreditCard(name, balance, balance_date)
                elif acc_type == 'Account number':
                    # This is the account associated with the credit card.
                    # We intentionally skip it, as it pretty much contains the
                    # same data as the credit card.
                    continue
                else:
                    logger.warning(
                            'Skipping account %s with unknown type %s.' %
                            (name, acc_type))
                    continue
                accounts.append(account)
        except (exceptions.NoSuchElementException, AttributeError, IndexError):
            raise fetch.FetchError('Couldn\'t load accounts.')
        return accounts

    def get_transactions(self, account, start, end):
        self._check_logged_in()

        if (isinstance(account, model.CheckingAccount) or
            isinstance(account, model.SavingsAccount)):
            return self._get_account_transactions(account, start, end)
        elif isinstance(account, model.CreditCard):
            return self._get_credit_card_transactions(account, start, end)
        else:
            raise fetch.FetchError('Unsupported account type: %s.', type(account))

    def _get_account_transactions(self, account, start, end):
        browser = self._browser

        logger.info('Opening transactions search form...')
        browser.find_element_by_link_text('Accounts and assets').click()
        browser.find_element_by_link_text('Transactions').click()

        logger.info('Performing transactions search...')
        formatted_start = start.strftime(self._DATE_FORMAT)
        end_inclusive = end - datetime.timedelta(1)
        formatted_end = end_inclusive.strftime(self._DATE_FORMAT)
        form = browser.find_element_by_name('bewegungen')
        form.find_element_by_name('p_buchdat_von').send_keys(formatted_start)
        form.find_element_by_name('p_buchdat_bis').send_keys(formatted_end)
        account_select = ui.Select(form.find_element_by_name('p_lkto_nr'))
        account_select.select_by_value(account.name.replace('-', ''))
        # 100 entries per page.
        form.find_element_by_id('p_anz_buchungen_4').click()

        transactions = []
        while True:
            form.submit()
            transactions += self._extract_transactions_from_result_page(
                    account.name)
            # Next page?
            try:
                form = browser.find_element_by_name('forward')
                logger.info('Loading next transactions page.')
            except exceptions.NoSuchElementException:
                break

        logger.info('Found %i transactions.' % len(transactions))

        return transactions

    def _extract_transactions_from_result_page(self, account_name):
        browser = self._browser

        try:
            headline = browser.find_element_by_class_name(
                    'ef-chapter-title-grey').text
            if account_name not in headline:
                raise fetch.FetchError('Transactions search failed.')
        except exceptions.NoSuchElementException:
            try:
                error_element = browser.find_element_by_id('ef-error-message')
                logging.info('Search failed: %s' % error_element.text)
                return []
            except exceptions.NoSuchElementException:
                raise fetch.FetchError('Transactions search failed.')

        content = browser.find_element_by_id('content')
        try:
            table = content.find_element_by_tag_name('table')
            tbody = table.find_element_by_tag_name('tbody')
            table_rows = tbody.find_elements_by_tag_name('tr')
        except exceptions.NoSuchElementException:
            raise fetch.FetchError('Couldn\'t find transactions table.')
        transactions = []
        for table_row in table_rows:
            cells = table_row.find_elements_by_tag_name('td')
            date = cells[1].text.strip()
            memo = cells[2].text.strip()
            credit = cells[3].text.replace('&nbsp;', '').strip()
            debit = cells[4].text.replace('&nbsp;', '').strip()
            transaction = self._parse_transaction_from_text(
                    date, memo, credit, debit)
            if transaction:
                transactions.append(transaction)

        return transactions

    def _get_credit_card_transactions(self, account, start, end):
        browser = self._browser

        logger.info('Opening credit cards overview...')
        browser.find_element_by_link_text('Credit cards').click()
        content = browser.find_element_by_id('content')

        logger.debug('Finding credit card account...')
        # Find the table row for that account.
        account_table = content.find_element_by_class_name('table-total')
        tbody = account_table.find_element_by_tag_name('tbody')
        account_rows = tbody.find_elements_by_tag_name('tr')
        account_found = False
        for account_row in account_rows:
            cells = account_row.find_elements_by_tag_name('td')
            details_link = cells[0].find_element_by_tag_name('a')
            name = cells[1].text.replace(' ', '')
            if name == account.name:
                details_link.click()
                account_found = True
                break
        if not account_found:
            raise fetch.FetchError('Couldn\'t find account %s.' % account)

        # You can see the transactions for three periods:
        # Current, previous and last-but-one.
        # We always load all and post-filter.
        content = browser.find_element_by_id('content')
        transactions = []
        while True:
            # Get the period of the current page.
            page_title = content.find_element_by_class_name('page-title').text
            match = self._CREDIT_CARD_TX_HEADER_PATTERN.search(page_title)
            if match:
                current_period = match.group(1)
            else:
                raise fetch.FetchError(
                        'Not a credit card transactions page %s.' %
                        account.name)
            logger.debug('Current period: ' + current_period)

            transactions_on_page = self._extract_cc_transactions()
            transactions += transactions_on_page
            logger.debug(
                    'Found %i transactions on the current page.' %
                    len(transactions_on_page))

            # Add a marker transaction for the page break.
            if (current_period in ('current', 'previous billing') and
                len(transactions) > 0):
                logger.debug('Adding marker transaction for page break.')
                transactions.append(model.Payment(
                        transactions[-1].date, amount=0,
                        memo='[Next billing cycle]'))

            # Go to the next page.
            # You can navigate to the previous period using the "beweg1" form,
            # and to the last-but-one period using the "beweg2" form.
            if current_period == 'current':
                form_name = 'beweg1'
            elif current_period == 'previous billing':
                form_name = 'beweg2'
            else:
                logger.debug('Hit last transactions page. Exiting loop.')
                break
            try:
                forward_form = browser.find_element_by_name(form_name)
                logger.info('Loading earlier transactions page...')
                forward_form.submit()
            except exceptions.NoSuchElementException:
                logger.info('No more earlier transactions.')
                break

        # Filter the transactions for the requested date range.
        logger.debug(
                'Found %i transactions before filtering for date range.' %
                len(transactions))
        transactions = filter(lambda t: start <= t.date < end, transactions)

        # They should be sorted in reverse chronological order already, but
        # let's make this explicit.
        transactions.sort(key=lambda t: t.date, reverse=True)

        logger.info('Found %i transactions.' % len(transactions))

        return transactions

    def _extract_cc_transactions(self):
        browser = self._browser
        content = browser.find_element_by_id('content')
        try:
            table = content.find_element_by_class_name('table-total')
        except exceptions.NoSuchElementException:
            raise fetch.FetchError('Couldn\'t find transactions.')
        try:
            tbody = table.find_element_by_tag_name('tbody')
        except exceptions.NoSuchElementException:
            logger.debug('No transactions on current page.')
            return []
        table_rows = tbody.find_elements_by_tag_name('tr')
        transactions = []
        for table_row in table_rows:
            cells = table_row.find_elements_by_tag_name('td')
            date = cells[0].text.strip()
            billing_month = cells[1].text.strip()
            memo = cells[2].text.strip()
            credit = cells[3].text.replace('&nbsp;', '').strip()
            debit = cells[4].text.replace('&nbsp;', '').strip()
            transaction = self._parse_transaction_from_text(
                    date, memo, credit, debit)
            if transaction:
                transactions.append(transaction)

        return transactions

    def _parse_transaction_from_text(self, date, memo, credit, debit):
        try:
            date = datetime.datetime.strptime(date, self._DATE_FORMAT)
        except ValueError:
            logger.warning(
                    'Skipping transaction with invalid date %s.', date)
            return

        memo = fetch.normalize_text(memo)
        if credit:
            amount = credit
        else:
            amount = '-' + debit
        try:
            amount = fetch.parse_decimal_number(amount, 'de_CH')
        except ValueError:
            logger.warning(
                    'Skipping transaction with invalid amount %s.', amount)
            return

        return model.Payment(date, amount, memo=memo)

    def _extract_language_from_page(self):
        browser = self._browser
        try:
            selector_element = browser.find_element_by_id('languageSelector')
            selected_lang = selector_element.find_element_by_class_name(
                    'selected')
            return selected_lang.text.strip()
        except exceptions.NoSuchElementException:
            raise fetch.FetchError('Couldn\'t find selected language.')

    def _parse_balance(self, balance):
        # Sign is at the end.
        balance = balance[-1] + balance[:-1]
        return fetch.parse_decimal_number(balance, 'de_CH')

    def _check_logged_in(self):
        if not self._logged_in:
            raise fetch.FetchError('Not logged in.')
