import datetime
import getpass
import logging
import re
import urllib.parse
from typing import Optional, List

from selenium import webdriver
from selenium.common import exceptions
from selenium.webdriver.support import ui

import download.bank
import model


logger = logging.getLogger(__name__)


class PostFinance(download.bank.Bank):
    """Fetcher for PostFinance (http://www.postfincance.ch/)."""
    _BASE_URL = 'https://www.postfinance.ch/ap/ba/fp/html/e-finance/'
    _LOGIN_URL = _BASE_URL + 'home?login&p_spr_cd=4'
    _ASSETS_URL = _BASE_URL + 'assets'
    _DATE_FORMAT = '%d.%m.%Y'
    _CREDIT_CARD_JS_LINK_PATTERN = re.compile(
            r'.*detailbew\(\'(\d+)\',\'(\d+)\'\)')
    _CREDIT_CARD_DATE_RANGE_PATTERN = re.compile(
            r'(\d\d\.\d\d\.\d\d\d\d) - (\d\d\.\d\d\.\d\d\d\d)')
    _CREDIT_CARD_TAB_PATTERN = re.compile(r'(.*Card) (\d\d\d\d)')
    _SPACE_PATTERN = re.compile('&nbsp;| ')
    _MINUS_PATTERN = re.compile('\u2212|-')
    _PLUS_PATTERN = re.compile('\+')
    _WEBDRIVER_TIMEOUT = 10
    _SESSION_TIMEOUT_S = 60 * 60

    def login(
            self, 
            username: Optional[str] = None,
            password: Optional[str] = None, 
            statements: Optional[List[str]] = None) -> None:
        if self._debug:
            self._browser = webdriver.Chrome()
        else:
            import selenium.webdriver.chrome.options
            chrome_options = selenium.webdriver.chrome.options.Options()
            chrome_options.add_argument("--headless")
            self._browser = webdriver.Chrome(chrome_options=chrome_options)

        self._browser.implicitly_wait(self._WEBDRIVER_TIMEOUT)
        self._browser.set_window_size(800, 800)
        self._logged_in = False
        self._accounts = None
        browser = self._browser

        logger.info('Loading login page…')
        browser.get(self._LOGIN_URL)

        if not username:
            username = input('E-Finance number: ')

        if self.ask_and_restore_cookies(
                browser, username, self._SESSION_TIMEOUT_S):
            browser.refresh()

        if not self._is_logged_in():
            if not password:
                password = getpass.getpass('Password: ')

            try:
                login_form = browser.find_element_by_name('login')
            except exceptions.NoSuchElementException:
                raise download.FetchError('Login form not found.')

            use_mobile_login_input = input('Use mobile login? [Yn]: ').lower()
            use_mobile_login = use_mobile_login_input in ('y', '')

            # First login phase: User and password.
            login_form.find_element_by_name('p_username').send_keys(username)
            login_form.find_element_by_name('p_passw').send_keys(password)
            login_form.submit()

            # Second login phase: Mobile ID or challenge/return.
            if use_mobile_login:
                try:
                    browser.find_element_by_class_name('pf-spinner')
                except exceptions.NoSuchElementException:
                    try:
                        error_element = browser.find_element_by_class_name(
                                'error')
                        logger.error('Login failed:\n%s' % error_element.text)
                        raise download.FetchError('Login failed.')
                    except exceptions.NoSuchElementException:
                        raise download.FetchError('Mobile ID login error.')
                print('Please confirm the login on your phone…')
                download.wait_for_element_to_appear_and_disappear(
                        lambda: browser.find_element_by_class_name(
                                'pf-spinner'),
                        timeout_s=60)
            else:
                try:
                    challenge_element = browser.find_element_by_id('challenge')
                except exceptions.NoSuchElementException:
                    try:
                        error_element = browser.find_element_by_class_name(
                                'error')
                        logger.error('Login failed:\n%s' % error_element.text)
                        raise download.FetchError('Login failed.')
                    except exceptions.NoSuchElementException:
                        raise download.FetchError('Security challenge not found.')
                print('Challenge:', challenge_element.text)
                token = input('Login token: ')
                try:
                    login_form = browser.find_element_by_name('login')
                except exceptions.NoSuchElementException:
                    raise download.FetchError('Login token form not found.')
                login_form.find_element_by_name('p_si_nr').send_keys(token)
                login_form.submit()

            # Logout warning?
            if 'Increased security when logging out' in browser.page_source:
                logger.info('Confirming logout reminder…')
                try:
                    login_form = browser.find_element_by_name('login')
                except exceptions.NoSuchElementException:
                    raise download.FetchError('Logout reminder form not found.')
                login_form.submit()

            if not self._is_logged_in():
                raise download.FetchError('Login failed.')

        self.save_cookies(browser, username)
        self._logged_in = True
        self._username = username
        logger.info('Log-in sucessful.')

    def _is_logged_in(self):
        return download.is_element_present(
                lambda: self._browser.find_element_by_css_selector('a.logout'))

    def logout(self) -> None:
        self._browser.find_element_by_css_selector('a.logout').click()
        self._browser.quit()
        self._logged_in = False
        self._accounts = None
        self.delete_cookies(self._username)
        self._username = None

    def get_accounts(self) -> List[model.Account]:
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

        logger.info('Loading accounts overview…')
        self._go_to_assets()
        assets_tile = self._get_tile_by_title('Overview of your assets')
        download.find_element_by_title(assets_tile, 'Detailed overview').click()
        content = browser.find_element_by_class_name('detail_page')

        account_tables = []
        for table_id in (
                'paymentAccounts', 'savingsAccounts', 'investmentAccounts'):
            try:
                account_tables.append(content.find_element_by_id(table_id))
            except exceptions.NoSuchElementException:
                # Not all account types need to be present.
                pass
        accounts = []
        for account_table in account_tables:
            try:
                account_rows = account_table.find_elements_by_css_selector(
                        'tbody tr')
                col_by_text = self._get_column_indizes_by_header_text(
                        account_table)
                for account_row in account_rows:
                    tds = account_row.find_elements_by_tag_name('td')
                    account_name_cell = tds[col_by_text['Account']]
                    acc_number = account_name_cell \
                            .find_element_by_tag_name('div') \
                            .text.replace(' ', '')
                    account_type_cell = tds[col_by_text['Type']]
                    acc_type = account_type_cell.text
                    # TODO: Extract actual currency.
                    currency = 'CHF'
                    balance_cell = tds[col_by_text['Balance in CHF']]
                    balance = self._parse_balance(balance_cell.text.strip())
                    balance_date = datetime.datetime.now()
                    if acc_type == 'Private account':
                        account = model.CheckingAccount(
                                acc_number, currency, balance, balance_date)
                    elif acc_type == 'E-savings account':
                        account = model.SavingsAccount(
                                acc_number, currency, balance, balance_date)
                    elif acc_type in ('E-trading', 'Safe custody deposit'):
                        account = model.InvestmentsAccount(
                                acc_number, currency, balance, balance_date)
                    else:
                        logger.warning(
                                'Skipping account %s with unknown type %s.' %
                                (acc_number, acc_type))
                        continue
                    accounts.append(account)
            except (
                    exceptions.NoSuchElementException, AttributeError,
                    IndexError):
                raise download.FetchError('Couldn\'t load accounts.')
        self._close_tile()
        return accounts

    def _fetch_credit_cards(self):
        self._check_logged_in()

        browser = self._browser

        logger.info('Opening credit cards overview…')
        self._go_to_assets()
        cc_tile = self._get_tile_by_title('Credit card')
        download.find_element_by_title(cc_tile, 'Detailed overview') \
                .find_element_by_xpath('..') \
                .click()
        self._wait_to_finish_loading()
        content = browser.find_element_by_class_name('detail_page')

        accounts = []
        for tab in content.find_elements_by_css_selector('tab-wrapper'):
            match = self._CREDIT_CARD_TAB_PATTERN.match(tab.text)
            if match:
                acc_type = match.group(1)
                name = 'X' * 12 + match.group(2)
                # TODO: Extract balance, if available.
                balance = 0
                balance_date = datetime.datetime.now()
                currency = 'CHF'
                account = model.CreditCard(
                        name, currency, balance, balance_date)
                accounts.append(account)
        self._close_tile()
        return accounts

    def get_transactions(
            self,
            account: model.Account,
            start: datetime.datetime, 
            end: datetime.datetime) -> List[model.Transaction]:
        self._check_logged_in()

        if (isinstance(account, model.CheckingAccount) or
            isinstance(account, model.SavingsAccount)):
            return self._get_account_transactions(account, start, end)
        elif isinstance(account, model.CreditCard):
            return self._get_credit_card_transactions(account, start, end)
        else:
            raise download.FetchError('Unsupported account type: %s.', type(account))

    def _get_account_transactions(self, account, start, end):
        browser = self._browser

        logger.info('Opening transactions search form…')
        self._go_to_assets()
        # We can go to any payment account to proceed to the custom search.
        payment_tile = self._get_tile_by_title('Payment account')
        payment_tile.find_element_by_partial_link_text('Transactions').click()
        self._wait_to_finish_loading()

        logger.info('Performing transactions search…')
        form = browser.find_element_by_css_selector(
                '.detail_content form[name="EfmovementsOverviewForm"]')

        # If there are multiple accounts, select the requested one.
        # The search form is not using a standard <select>, but some custom
        # HTML.
        try:
            account_drop_down_container = form.find_element_by_css_selector(
                    '*[name="pf-detail-efmovements-overview-dropdown-account"]')
            account_drop_down_container.find_element_by_class_name(
                    'ef_select--trigger').click()
            download.find_element_by_text(
                    account_drop_down_container,
                    download.format_iban(account.name)) \
                    .find_element_by_xpath('../../../..') \
                    .click()
        except exceptions.NoSuchElementException:
            # Probably only one account present.
            pass

        # Check that we're looking at the right account.
        current_account = browser.find_element_by_id(
                'pf-detail-efmovements-overview-account-iban').text
        if current_account != download.format_iban(account.name):
            raise download.FetchError(
                    'Transactions search failed: Wrong account: ' +
                    current_account)

        download.find_button_by_text(form, 'Search options').click()
        formatted_start = start.strftime(self._DATE_FORMAT)
        end_inclusive = end - datetime.timedelta(1)
        formatted_end = end_inclusive.strftime(self._DATE_FORMAT)
        from_field = form.find_element_by_name('dateFrom')
        from_field.clear()
        from_field.send_keys(formatted_start)
        to_field = form.find_element_by_name('dateTo')
        to_field.clear()
        to_field.send_keys(formatted_end)

        transactions = []
        form.find_element_by_css_selector('button[label="Search"]').click()
        while True:
            self._wait_to_finish_loading()
            transactions += self._extract_transactions_from_result_page(
                    account.name)
            # More transactions?
            try:
                logger.info('Loading more transactions…')
                browser.find_element_by_link_text('Show more').click()
            except exceptions.NoSuchElementException:
                break

        logger.info('Found %i transactions.' % len(transactions))

        self._close_tile()
        return transactions

    def _extract_transactions_from_result_page(self, account_name):
        browser = self._browser

        content = browser.find_element_by_css_selector(
                '.detail_page '
                '.content-pane:not(.is-hidden-print):not(.ng-hide)')
        try:
            if download.format_iban(account_name) not in content.text:
                raise download.FetchError(
                        'Transactions search failed: Wrong account.')
        except exceptions.NoSuchElementException:
            try:
                error_element = browser.find_element_by_id('ef-error-message')
                logging.info('Search failed: ' + error_element.text)
                return []
            except exceptions.NoSuchElementException:
                raise download.FetchError('Transactions search failed.')

        try:
            no_transactions = download.find_element_by_text(
                content,
                'No transactions were found that match your search options')
            if no_transactions.is_displayed():
                logging.info('No transactions found.')
                return []
        except exceptions.NoSuchElementException:
            pass

        try:
            table_rows = content.find_elements_by_css_selector('table tbody tr')
        except exceptions.NoSuchElementException:
            raise download.FetchError('Couldn\'t find transactions table.')
        transactions = []
        for table_row in table_rows:
            th_cells = table_row.find_elements_by_tag_name('th')
            td_cells = table_row.find_elements_by_tag_name('td')
            date = th_cells[0].text.strip()
            memo = td_cells[0].text.strip()
            credit = self._sanitize_amount(th_cells[1].text)
            debit = self._sanitize_amount(th_cells[2].text)
            amount = credit if credit else debit
            transaction = self._parse_transaction_from_text(date, memo, amount)
            if transaction:
                transactions.append(transaction)

        return transactions

    def _get_credit_card_transactions(self, account, start, end):
        browser = self._browser

        logger.info('Opening credit cards overview…')
        self._go_to_assets()
        cc_tile = self._get_tile_by_title('Credit card')
        download.find_element_by_title(cc_tile, 'Detailed overview').click()
        self._wait_to_finish_loading()
        content = browser.find_element_by_class_name('detail_page')

        logger.debug('Finding credit card account…')
        # Switch to tab for that account.
        for tab in content.find_elements_by_css_selector('tab-wrapper'):
            if tab.text.endswith(account.name[-4:]):
                tab.find_element_by_tag_name('a').click()
                break
        # Verify that the correct card is displayed.
        active_pane = content.find_element_by_css_selector(
                'section.js-tabs--pane.is-active')
        formatted_account_name = download.format_cc_account_name(account.name)
        if formatted_account_name not in active_pane.text:
            raise download.FetchError('Couldn\'t find account %s.' % account)

        # You can see the transactions for one month/period at a time.
        transactions = []
        while True:
            self._wait_to_finish_loading()

            # Get the period of the current page.
            date_select_el = content.find_element_by_css_selector(
                    '.buttons select')
            date_select = ui.Select(date_select_el)
            period = date_select.first_selected_option.text
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
                    raise download.FetchError(
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
                if transactions:
                    transactions.append(model.Payment(
                            transactions[-1].date, amount=0,
                            memo='[Next billing cycle]'))

            # Load earlier transactions.
            next_option = date_select_el.find_element_by_xpath(
                    "option[text() = '%s']/following-sibling::option" % period)
            if not next_option:
                logger.info('No more earlier transactions.')
                break
            logger.info('Loading earlier transactions page…')
            date_select.select_by_value(next_option.get_attribute('value'))
            self._wait_to_finish_loading()

        # Filter the transactions for the requested date range.
        logger.debug(
                'Found %i transactions before filtering for date range.' %
                len(transactions))
        transactions = [t for t in transactions if start <= t.date < end]

        # They should be sorted in reverse chronological order already, but
        # let's make this explicit.
        transactions.sort(key=lambda t: t.date, reverse=True)

        logger.info('Found %i transactions.' % len(transactions))

        self._close_tile()
        return transactions

    def _extract_cc_transactions(self):
        browser = self._browser
        content = browser.find_element_by_class_name('detail_page')
        active_pane = content.find_element_by_css_selector(
                'section.js-tabs--pane.is-active')

        # Check if there are any transactions in the current period.
        try:
            no_transactions = download.find_element_by_text(
                active_pane,
                'There are no transactions in the selected invoicing period '
                'for this card.')
            if no_transactions.is_displayed():
                logging.info('No transactions found.')
                return []
        except exceptions.NoSuchElementException:
            pass

        # Find the transactions table.
        try:
            # Find the "Entries" section, skip the "Reservations" section.
            entries_heading = download.find_element_by_tag_name_and_text(
                    active_pane, 'h3', 'Entries')
            # The transactions are in the next table after that heading.
            table = entries_heading.find_element_by_xpath('following::table')
        except exceptions.NoSuchElementException:
            raise download.FetchError('Couldn\'t find transactions.')
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
            amount = credit if credit else '-' + debit
            transaction = self._parse_transaction_from_text(date, memo, amount)
            if transaction:
                transactions.append(transaction)

        return transactions

    def _sanitize_amount(self, amount_text):
        amount = self._SPACE_PATTERN.sub('', amount_text)
        amount = self._PLUS_PATTERN.sub('', amount)
        amount = self._MINUS_PATTERN.sub('-', amount)
        if amount.endswith('-'):
            amount = '-' + self._MINUS_PATTERN.sub('', amount)
        return amount

    def _parse_transaction_from_text(self, date, memo, amount):
        try:
            date = datetime.datetime.strptime(date, self._DATE_FORMAT)
        except ValueError:
            logger.warning(
                    'Skipping transaction with invalid date %s.', date)
            return

        memo = download.normalize_text(memo)
        try:
            amount = download.parse_decimal_number(amount, 'de_CH')
        except ValueError:
            logger.warning(
                    'Skipping transaction with invalid amount %s.', amount)
            return

        return model.Payment(date, amount, memo=memo)

    def _go_to_assets(self):
        self._browser.get(self._ASSETS_URL)
        self._wait_to_finish_loading()

    def _close_tile(self):
        self._browser.find_element_by_link_text('Close').click()

    def _wait_to_finish_loading(self):
        """Waits for the loading indicator to disappear on the current page."""
        browser = self._browser
        # The loading indicators should be there pretty fast.
        browser.implicitly_wait(1)

        # Wait for global loading overlay.
        overlay = lambda: browser.find_element_by_class_name('page_loader')
        download.wait_for_element_to_appear_and_disappear(overlay)
        # Wait for any individual card overlays.
        overlay = lambda: browser.find_element_by_class_name('widget--loading')
        download.wait_for_element_to_appear_and_disappear(overlay)
        # Wait for data loading inside cards.
        overlay = lambda: browser.find_element_by_class_name('is-loading')
        download.wait_for_element_to_appear_and_disappear(overlay)

        browser.implicitly_wait(self._WEBDRIVER_TIMEOUT)

    def _parse_balance(self, balance):
        # A Unicode minus might be used.
        balance = balance.replace('\u2212', '-')
        # Sign is at the end.
        balance = balance[-1] + balance[:-1]
        return download.parse_decimal_number(balance, 'de_CH')

    def _check_logged_in(self):
        if not self._logged_in:
            raise download.FetchError('Not logged in.')

    def _get_tile_by_title(self, title):
        return self._browser.find_element_by_xpath(
                "//*[normalize-space(text()) = '%s']/ancestor::li" % title)

    def _get_column_indizes_by_header_text(self, table):
        ths = table.find_elements_by_css_selector('thead th')
        th_texts = [th.text for th in ths]
        return dict((i[1], i[0]) for i in enumerate(th_texts))
