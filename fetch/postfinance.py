#!/usr/bin/python

import datetime
import getpass
import logging
import re
import urlparse

from selenium import webdriver
from selenium.common import exceptions
from selenium.webdriver.support import ui

import fetch.bank
import model


logger = logging.getLogger(__name__)


class PostFinance(fetch.bank.Bank):
    """Fetcher for PostFinance (http://www.postfincance.ch/)."""
    _BASE_URL = 'https://www.postfinance.ch/ap/ba/fp/html/e-finance/'
    _LOGIN_URL = _BASE_URL + 'home?login&p_spr_cd=4'
    _ASSETS_URL = _BASE_URL + 'assets'
    _DATE_FORMAT = '%d.%m.%Y'
    _CREDIT_CARD_JS_LINK_PATTERN = re.compile(
            r'.*detailbew\(\'(\d+)\',\'(\d+)\'\)')
    _CREDIT_CARD_DATE_RANGE_PATTERN = re.compile(
            r'(\d\d\.\d\d\.\d\d\d\d) - (\d\d\.\d\d\.\d\d\d\d)')
    _AMOUNT_SANITIZER_PATTERN = re.compile(u'&nbsp;|\u2212|-|\+| ')

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

        # Second login phase: Challenge and security token.
        try:
            challenge_element = browser.find_element_by_id('challenge')
        except exceptions.NoSuchElementException:
            try:
                error_element = browser.find_element_by_class_name('error')
                logger.error('Login failed:\n%s' % error_element.text)
                raise fetch.FetchError('Login failed.')
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
        if 'Increased security when logging out' in browser.page_source:
            logger.info('Confirming logout reminder...')
            try:
                login_form = browser.find_element_by_name('login')
            except exceptions.NoSuchElementException:
                raise fetch.FetchError('Logout reminder form not found.')
            login_form.submit()

        # Ensure we're using the English interface.
        self._select_english_language()

        # Login successful?
        try:
            browser.find_element_by_link_text('Logout')
        except exceptions.NoSuchElementException:
            raise fetch.FetchError('Login failed.')

        self._logged_in = True
        logger.info('Log-in sucessful.')

    def logout(self):
        self._browser.find_element_by_link_text('Logout').click()
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
        self._go_to_assets()
        assets_overview = self._get_tile_by_title('Overview of your assets')
        assets_overview.find_element_by_link_text('Detailed overview').click()
        content = browser.find_element_by_class_name('detail_page')

        accounts = []
        try:
            account_rows = content.find_elements_by_tag_name('tr')
            for account_row in account_rows:
                cells = account_row.find_elements_by_tag_name('td')
                if len(cells) != 7:
                    continue
                acc_number = cells[2].text
                acc_type = cells[4].text
                name = acc_number.replace(' ', '')
                currency = cells[5].text.strip()
                balance = self._parse_balance(cells[6].text.strip())
                balance_date = datetime.datetime.now()
                if acc_type == 'Private':
                    account = model.CheckingAccount(
                            name, currency, balance, balance_date)
                elif acc_type == 'E-savings':
                    account = model.SavingsAccount(
                            name, currency, balance, balance_date)
                elif acc_type in ('E-trading', 'Safe custody deposit'):
                    account = model.InvestmentsAccount(
                            name, currency, balance, balance_date)
                else:
                    logger.warning(
                            'Skipping account %s with unknown type %s.' %
                            (name, acc_type))
                    continue
                accounts.append(account)
        except (exceptions.NoSuchElementException, AttributeError, IndexError):
            raise fetch.FetchError('Couldn\'t load accounts.')
        self._close_tile()
        return accounts

    def _fetch_credit_cards(self):
        self._check_logged_in()

        browser = self._browser

        logger.info('Loading credit cards overview...')
        self._go_to_assets()
        assets_overview = self._get_tile_by_title('Credit card')
        assets_overview.find_element_by_link_text('Detailed overview').click()
        content = browser.find_element_by_class_name('detail_page')

        accounts = []
        try:
            account_table = content.find_element_by_id('kreditkarte_u1')
            tbody = account_table.find_element_by_tag_name('tbody')
            account_rows = tbody.find_elements_by_tag_name('tr')
            for account_row in account_rows:
                cells = account_row.find_elements_by_tag_name('td')
                acc_type = cells[1].text.strip()
                name = cells[2].text.replace(' ', '')
                currency = cells[5].text.strip()
                balance = self._parse_balance(cells[6].text.strip())
                balance_date = datetime.datetime.now()
                if (acc_type.startswith('Visa') or
                    acc_type.startswith('Master')):
                    account = model.CreditCard(
                            name, currency, balance, balance_date)
                else:
                    logger.warning(
                            'Skipping account %s with unknown type %s.' %
                            (name, acc_type))
                    continue
                accounts.append(account)
        except (exceptions.NoSuchElementException, AttributeError, IndexError):
            raise fetch.FetchError('Couldn\'t load accounts.')
        self._close_tile()
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
        self._go_to_assets()
        # We can go to any payment account to proceed to the custom search.
        assets_overview = self._get_tile_by_title('Payment account')
        assets_overview.find_element_by_link_text('Transactions').click()
        content = browser.find_element_by_class_name('detail_page')
        content.find_element_by_link_text('Search options').click()

        logger.info('Performing transactions search...')
        formatted_start = start.strftime(self._DATE_FORMAT)
        end_inclusive = end - datetime.timedelta(1)
        formatted_end = end_inclusive.strftime(self._DATE_FORMAT)
        form = browser.find_element_by_id('pfform-bewegungen')
        form.find_element_by_name('p_buchdat_von').send_keys(formatted_start)
        form.find_element_by_name('p_buchdat_bis').send_keys(formatted_end)
        # The search form is not using a standard <select>, but some custom
        # HTML. Luckily, they use a hidden <input> to store the selected
        # account.
        browser.execute_script(
                'document.getElementsByName("p_lkto_nr")[0].value = "%s"' %
                account.name[-9:])
        # 100 entries per page.
        form.find_element_by_id('p_anz_buchungen_4').click()

        transactions = []
        self._get_button_by_text('Search').click()
        while True:
            self._wait_to_finish_loading()
            transactions += self._extract_transactions_from_result_page(
                    account.name)
            # Next page?
            try:
                logger.info('Loading next transactions page.')
                self._get_button_by_text('Next').click()
                #content.find_element_by_id('Button1').click()  # Next
            except exceptions.NoSuchElementException:
                break

        logger.info('Found %i transactions.' % len(transactions))

        self._close_tile()
        return transactions

    def _extract_transactions_from_result_page(self, account_name):
        browser = self._browser

        try:
            heading = browser.find_element_by_class_name('paragraph-title')
            if self._format_iban(account_name) not in heading.text:
                raise fetch.FetchError(
                        'Transactions search failed: Wrong account.')
        except exceptions.NoSuchElementException:
            try:
                error_element = browser.find_element_by_id('ef-error-message')
                logging.info('Search failed: %s' % error_element.text)
                return []
            except exceptions.NoSuchElementException:
                raise fetch.FetchError('Transactions search failed.')

        content = browser.find_element_by_class_name('detail_page')
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
            credit = self._sanitize_amount(cells[3].text)
            debit = self._sanitize_amount(cells[4].text)
            transaction = self._parse_transaction_from_text(
                    date, memo, credit, debit)
            if transaction:
                transactions.append(transaction)

        return transactions

    def _get_credit_card_transactions(self, account, start, end):
        browser = self._browser

        logger.info('Opening credit cards overview...')
        self._go_to_assets()
        assets_overview = self._get_tile_by_title('Credit card')
        assets_overview.find_element_by_link_text('Detailed overview').click()
        content = browser.find_element_by_class_name('detail_page')

        logger.debug('Finding credit card account...')
        # Find the table row for that account.
        try:
            table = content.find_element_by_id('kreditkarte_u1')
            formatted_account_name = self._format_cc_account_name(account.name)
            row = table.find_element_by_xpath(
                    "//td[text() = '%s']/ancestor::tr" % formatted_account_name)
            row.find_element_by_tag_name('a').click()
        except exceptions.NoSuchElementException:
            raise fetch.FetchError('Couldn\'t find account %s.' % account)

        # You can see the transactions for three periods:
        # Current, previous and last-but-one.
        # We always load all and post-filter.
        transactions = []
        while True:
            self._wait_to_finish_loading()
            # Also wait for the content to load.
            content.find_element_by_xpath(
                    "//h1[@class = 'page-title page-title-top']"
                    "/span[text() = 'Transactions']")
            content.find_element_by_class_name('content-pane') \
                    .find_element_by_tag_name('table')

            # Get the period of the current page.
            period = content.find_element_by_class_name('page-title') \
                .find_element_by_class_name('add-information').text
            if period == 'Current accounting period':
                # Just use "now", which is an inaccurate hack, but works for our
                # purposes.
                start_date = end_date = datetime.datetime.now()
            else:
                match = self._CREDIT_CARD_DATE_RANGE_PATTERN.search(period)
                if match:
                    start_date_str = match.group(1)
                    end_date_str = match.group(2)
                    start_date = datetime.datetime.strptime(
                            start_date_str, self._DATE_FORMAT)
                    end_date = datetime.datetime.strptime(
                            end_date_str, self._DATE_FORMAT)
                else:
                    raise fetch.FetchError(
                            'Not a credit card transactions page %s.' %
                            account.name)
            logger.debug('Current period: ' + period)

            transactions_on_page = self._extract_cc_transactions()
            transactions += transactions_on_page
            logger.debug(
                    'Found %i transactions on the current page.' %
                    len(transactions_on_page))

            # Are we done yet?
            if start_date <= start:
                logger.info('Should have loaded enough transaction pages.')
                break
            else:
                logger.debug('Adding marker transaction for page break.')
                transactions.append(model.Payment(
                        transactions[-1].date, amount=0,
                        memo='[Next billing cycle]'))

            # Load earlier transactions.
            date_select_el = content.find_element_by_class_name('buttons') \
                    .find_element_by_tag_name('select')
            next_option = date_select_el.find_element_by_xpath(
                    "option[text() = '%s']/following-sibling::option" % period)
            if not next_option:
                logger.info('No more earlier transactions.')
                break
            logger.info('Loading earlier transactions page...')
            date_select = ui.Select(date_select_el)
            date_select.select_by_value(next_option.get_attribute('value'))

        # Filter the transactions for the requested date range.
        logger.debug(
                'Found %i transactions before filtering for date range.' %
                len(transactions))
        transactions = filter(lambda t: start <= t.date < end, transactions)

        # They should be sorted in reverse chronological order already, but
        # let's make this explicit.
        transactions.sort(key=lambda t: t.date, reverse=True)

        logger.info('Found %i transactions.' % len(transactions))

        self._close_tile()
        return transactions

    def _extract_cc_transactions(self):
        browser = self._browser
        content = browser.find_element_by_class_name('content-pane')
        try:
            table = content.find_element_by_tag_name('table')
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
            date = table_row.find_elements_by_tag_name('th')[0].text.strip()
            cells = table_row.find_elements_by_tag_name('td')
            memo = cells[0].text.strip()
            credit = self._sanitize_amount(cells[1].text)
            debit = self._sanitize_amount(cells[2].text)
            transaction = self._parse_transaction_from_text(
                    date, memo, credit, debit)
            if transaction:
                transactions.append(transaction)

        return transactions

    def _sanitize_amount(self, amount_text):
        return self._AMOUNT_SANITIZER_PATTERN.sub('', amount_text)

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

    def _select_english_language(self):
        browser = self._browser
        url = urlparse.urlparse(browser.current_url)
        english_url = urlparse.urlunparse(url[:3] + ('', 'lang=en', ''))
        browser.get(english_url)

    def _go_to_assets(self):
        self._browser.get(self._ASSETS_URL)

    def _close_tile(self):
        self._browser.find_element_by_link_text('Close').click()

    def _wait_to_finish_loading(self):
        """Waits for the loading indicator to disappear on the current page."""
        loader = self._browser.find_element_by_id('loader')
        ui_is_unblocked = lambda: not loader.is_displayed()
        fetch.wait_until(ui_is_unblocked)

    def _parse_balance(self, balance):
        # A Unicode minus might be used.
        balance = balance.replace(u'\u2212', '-')
        # Sign is at the end.
        balance = balance[-1] + balance[:-1]
        return fetch.parse_decimal_number(balance, 'de_CH')

    def _format_iban(self, iban):
        return self._format_string_into_blocks(iban, 4)

    def _format_cc_account_name(self, account_name):
        return self._format_string_into_blocks(account_name, 4)

    def _format_string_into_blocks(self, string, block_length, separator=' '):
        parts = []
        index = 0
        while index < len(string):
            parts.append(string[index:index + block_length])
            index += block_length
        return separator.join(parts)

    def _check_logged_in(self):
        if not self._logged_in:
            raise fetch.FetchError('Not logged in.')

    def _get_button_by_text(self, text):
        return self._browser.find_element_by_xpath(
                "//input[@type = 'button' and normalize-space(@value) = '%s']" %
                text)

    def _get_tile_by_title(self, title):
        return self._browser.find_element_by_xpath(
                "//*[normalize-space(text()) = '%s']/ancestor::li" % title)
