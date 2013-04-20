#!/usr/bin/python

import datetime
import getpass
import logging
import re

import BeautifulSoup

import fetch
import fetch.browser
import model


logger = logging.getLogger(__name__)


class PostFinance(Bank):
    """fetch.FetchErrorr for PostFinance (http://www.postfincance.ch/)."""
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

    def __init__(self):
        self._browser = fetch.browser.Browser()
        self._logged_in = False
        self._accounts = None

    def login(self, username=None, password=None):
        self._logged_in = False
        self._accounts = None

        if not username:
            username = raw_input('E-Finance number: ')

        if not password:
            password = getpass.getpass('Password: ')

        browser = self._browser

        # First login phase: E-Finance number and password.
        logger.info('Loading login page...')
        browser.open(self._LOGIN_URL)

        try:
            browser.select_form(name='login')
        except mechanize.FormNotFoundError, e:
            raise fetch.FetchErrorrror('Login form not found.')
        form = browser.form
        form['p_et_nr'] = username
        form['p_passw'] = password
        logger.info('Logging in with user name %s...' % username)
        browser.submit()
        xhtml = browser.get_decoded_response()

        # Second login phase: Challenge and security token.
        soup = BeautifulSoup.BeautifulSoup(xhtml)
        error_element = soup.find('div', {'class': 'error'})
        if error_element:
            error_text = fetch.soup_to_text(error_element).strip()
            if error_text:
                logger.error('Login failed:\n%s' % error_text)
                raise fetch.FetchErrorrror('Login failed.')
        challenge_element = soup.find('span', {'id': 'challenge'})
        if not challenge_element:
            raise fetch.FetchErrorrror('Security challenge not found.')
        print 'Please enter your login token.'
        print 'Challenge:', challenge_element.getText()
        token = raw_input('Login token: ')

        try:
            browser.select_form(name='login')
        except mechanize.FormNotFoundError, e:
            raise fetch.FetchErrorrror('Login token form not found.')
        browser.form['p_si_nr'] = token
        logger.info('Logging in with token %s...' % token)
        browser.submit()

        # Logout warning?
        xhtml = browser.get_decoded_response()
        if 'Logout reminder' in xhtml:
            logger.info('Confirming logout reminder...')
            try:
                browser.select_form(name='login')
            except mechanize.FormNotFoundError, e:
                raise fetch.FetchErrorrror('Logout reminder form not found.')
            browser.submit()
            xhtml = browser.get_decoded_response()

        # Ensure we're using the English interface.
        selected_language = self._extract_language_from_page(xhtml)
        if selected_language != 'en':
            logger.info(
                    'Wrong display language. Using "%s" instead of "en". '
                    'Trying to switch to English.'
                    % selected_language)
            browser.open(self._OVERVIEW_URL_ENGLISH)
            xhtml = browser.get_decoded_response()
            selected_language = self._extract_language_from_page(xhtml)
            if selected_language != 'en':
                raise fetch.FetchErrorrror(
                        'Wrong display language "%s" instead of "en".'
                        % selected_language)

        # Login successful?
        try:
            browser.find_link(text='Accounts and assets')
        except mechanize.LinkNotFoundError, e:
            raise fetch.FetchErrorrror('Login failed.')

        self._logged_in = True
        logger.info('Log-in sucessful.')

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
        accounts_link = browser.find_link(text='Accounts and assets')
        browser.follow_link(accounts_link)
        xhtml = browser.get_decoded_response()

        soup = BeautifulSoup.BeautifulSoup(xhtml)
        content = soup.find('div', id='content')
        accounts = []
        try:
            account_tables = content.findAll('table', 'table-total')
            payment_accounts_table = account_tables[0]
            asset_accounts_table = account_tables[1]
            for account_table in payment_accounts_table, asset_accounts_table:
                account_rows = account_table.find('tbody').findAll('tr')
                for account_row in account_rows:
                    cells = account_row.findAll('td')
                    name_and_type = cells[2].getText()
                    name = name_and_type.split()[0]
                    acc_type = ' '.join(name_and_type.split()[1:])
                    currency = cells[4].getText()
                    balance = self._parse_balance(cells[5].getText())
                    balance_date = datetime.datetime.now()
                    if acc_type == 'Private':
                        account = model.CheckingAccount(
                                name, balance, balance_date)
                    elif acc_type == 'E-Deposito':
                        account = model.SavingsAccount(
                                name, balance, balance_date)
                    elif acc_type in ('E-Trading', 'Safe custody deposit'):
                        account = model.InvestmentsAccount(
                                name, balance, balance_date)
                    else:
                        logger.warning(
                                'Skipping account %s with unknown type %s.' %
                                (name, acc_type))
                        continue
                    accounts.append(account)
        except (AttributeError, IndexError):
            raise fetch.FetchErrorrror('Couldn\'t load accounts.')
        return accounts

    def _fetch_credit_cards(self):
        self._check_logged_in()

        browser = self._browser

        logger.info('Loading credit cards overview...')
        accounts_link = browser.find_link(text='Credit cards')
        browser.follow_link(accounts_link)
        xhtml = browser.get_decoded_response()

        soup = BeautifulSoup.BeautifulSoup(xhtml)
        content = soup.find('div', id='content')
        accounts = []
        try:
            account_table = content.find('table', {'class': 'table-total'})
            account_rows = account_table.find('tbody').findAll('tr')
            for account_row in account_rows:
                cells = account_row.findAll('td')
                name = cells[1].getText().replace(' ', '')
                acc_type = cells[2].getText()
                currency = cells[4].getText()
                balance = self._parse_balance(cells[5].getText())
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
        except (AttributeError, IndexError):
            raise fetch.FetchErrorrror('Couldn\'t load accounts.')
        return accounts

    def get_transactions(self, account, start, end):
        self._check_logged_in()

        if (isinstance(account, model.CheckingAccount) or
            isinstance(account, model.SavingsAccount)):
            return self._get_account_transactions(account, start, end)
        elif isinstance(account, model.CreditCard):
            return self._get_credit_card_transactions(account, start, end)
        else:
            raise fetch.FetchErrorrror('Unsupported account type: %s.', type(account))

    def _get_account_transactions(self, account, start, end):
        browser = self._browser

        logger.info('Opening transactions search form...')
        accounts_link = browser.find_link(text='Accounts and assets')
        browser.follow_link(accounts_link)
        transactions_link = browser.find_link(text='Transactions')
        browser.follow_link(transactions_link)

        logger.info('Performing transactions search...')
        formatted_start = start.strftime(self._DATE_FORMAT)
        end_inclusive = end - datetime.timedelta(1)
        formatted_end = end_inclusive.strftime(self._DATE_FORMAT)
        try:
            browser.select_form(name='bewegungen')
        except mechanize.FormNotFoundError, e:
            raise fetch.FetchErrorrror('Transactions form not found.')
        form = browser.form
        form['p_buchdat_von'] = formatted_start
        form['p_buchdat_bis'] = formatted_end
        form['p_buch_art'] = '9',  # 9 = All transaction types.
        form['p_lkto_nr'] = account.name.replace('-', ''),
        form['p_anz_buchungen'] = '100',  # 100 entries per page.

        transactions = []
        while True:
            browser.submit()
            xhtml = browser.get_decoded_response()
            transactions += self._extract_transactions_from_result_page(
                    xhtml, account.name)
            # Next page?
            try:
                browser.select_form(name='forward')
                logger.info('Loading next transactions page.')
            except mechanize.FormNotFoundError, e:
                break

        logger.info('Found %i transactions.' % len(transactions))

        return transactions

    def _extract_transactions_from_result_page(self, xhtml, account_name):
        # Parse response.
        if account_name not in xhtml:
            raise fetch.FetchErrorrror('Transactions search failed.')
        if 'No booking entry found' in xhtml:
            logging.info('Couldn\'t find any transactions.')
            return []
        soup = BeautifulSoup.BeautifulSoup(xhtml)
        try:
            table_rows = soup.find('table').find('tbody').findAll('tr')
        except AttributeError:
            raise fetch.FetchErrorrror('Couldn\'t find transactions table.')
        transactions = []
        for table_row in table_rows:
            cells = table_row.findAll('td')

            date = cells[1].getText()
            memo = fetch.soup_to_text(cells[2])
            credit = cells[3].getText().replace('&nbsp;', '')
            debit = cells[4].getText().replace('&nbsp;', '')
            transaction = self._parse_transaction_from_text(
                    date, memo, credit, debit)
            if transaction:
                transactions.append(transaction)

        return transactions

    def _get_credit_card_transactions(self, account, start, end):
        browser = self._browser

        logger.info('Opening credit cards overview...')
        accounts_link = browser.find_link(text='Credit cards')
        browser.follow_link(accounts_link)
        xhtml = browser.get_decoded_response()
        soup = BeautifulSoup.BeautifulSoup(xhtml)
        content = soup.find('div', id='content')

        logger.debug('Finding account reference and level...')
        ref, level = None, None
        # Find the table row for that account.
        account_table = content.find('table', {'class': 'table-total'})
        account_rows = account_table.find('tbody').findAll('tr')
        for account_row in account_rows:
            cells = account_row.findAll('td')
            js_link = cells[0].find('a')
            name = cells[1].getText().replace(' ', '')
            if name == account.name:
                # Extract the account reference number and level from the
                # JavaScript link.
                ref, level = self._extract_cc_ref_and_level(js_link['href'])
                break
        if not ref or not level:
            raise fetch.FetchErrorrror('Couldn\'t find account reference and level.')

        logger.info('Opening transactions...')
        try:
            browser.select_form(name='formbew')
        except mechanize.FormNotFoundError, e:
            raise fetch.FetchErrorrror('Credit card navigation form not found.')
        form = browser.form
        form.set_all_readonly(False)  # To allow changing hidden inputs.
        form['p_acc_ref_nr'] = ref
        form['p_acc_level'] = level

        # You can see the transactions for three periods:
        # Current, previous and last-but-one.
        # We always load all and post-filter.
        transactions = []
        while True:
            browser.submit()
            xhtml = browser.get_decoded_response()

            # Get the period of the current page.
            match = self._CREDIT_CARD_TX_HEADER_PATTERN.search(xhtml)
            if match:
              current_period = match.group(1)
            else:
              raise fetch.FetchErrorrror(
                      'Not a credit card transactions page %s.' % account.name)
            logger.debug('Current period: ' + current_period)

            transactions += self._extract_cc_transactions(xhtml)

            # Add a marker transaction for the page break.
            if (current_period in ('current', 'previous billing') and
                len(transactions) > 0):
                transactions.append(model.Transaction(
                    transactions[-1].date, amount=0, memo='---'))

            # Go to the next page.
            # You can navigate to the previous period using the "beweg1" form,
            # and to the last-but-one period using the "beweg2" form.
            soup = BeautifulSoup.BeautifulSoup(xhtml)
            content = soup.find('div', id='content')
            if current_period == 'current':
              form_name = 'beweg1'
            elif current_period == 'previous billing':
              form_name = 'beweg2'
            else:
              logger.debug('Hit last transactions page. Exiting loop.')
              break
            try:
                browser.select_form(name=form_name)
                logger.info('Loading earlier transactions page...')
            except mechanize.FormNotFoundError, e:
                logger.info('No more earlier transactions.')
                break

        # Filter the transactions for the requested date range.
        transactions = filter(lambda t: start <= t.date < end, transactions)

        # They should be sorted in reverse chronological order already, but
        # let's make this explicit.
        transactions.sort(key=lambda t: t.date, reverse=True)

        logger.info('Found %i transactions.' % len(transactions))

        return transactions

    def _extract_cc_ref_and_level(self, href):
        match = self._CREDIT_CARD_JS_LINK_PATTERN.match(href)
        if match:
            return match.groups()
        else:
            raise fetch.FetchErrorrror(
                    'Couldn\'t extract credit card reference number and level '
                    'from JavaScript link: ' + href)

    def _extract_cc_transactions(self, xhtml):
        # Parse response.
        soup = BeautifulSoup.BeautifulSoup(xhtml)
        content = soup.find('div', id='content')
        try:
            table = soup.find('table', {'class': 'table-total'})
            tbody = table.find('tbody')
            if tbody:
                table_rows = table.find('tbody').findAll('tr')
            else:
                # Empty transaction list.
                table_rows = []
        except AttributeError:
            raise fetch.FetchErrorrror('Couldn\'t find transactions.')
        transactions = []
        for table_row in table_rows:
            cells = table_row.findAll('td')

            date = cells[0].getText()
            memo = fetch.soup_to_text(cells[2])
            credit = cells[3].getText().replace('&nbsp;', '')
            debit = cells[4].getText().replace('&nbsp;', '')
            transaction = self._parse_transaction_from_text(
                    date, memo, credit, debit)
            if transaction:
                transactions.append(transaction)

        return transactions

    def _parse_transaction_from_text(self, date, memo, credit, debit):
        try:
            date = datetime.datetime.strptime(date, self._DATE_FORMAT)
        except ValueError, e:
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
        except ValueError, e:
            logger.warning(
                    'Skipping transaction with invalid amount %s.', amount)
            return

        return model.Transaction(date, amount, memo=memo)

    def _extract_language_from_page(self, xhtml):
        soup = BeautifulSoup.BeautifulSoup(xhtml)
        try:
            selector = soup.find('div', {'id': 'languageSelector'})
            selected_lang = selector.find(
                    'li', {'class': re.compile(r'\bselected\b')})
            return fetch.soup_to_text(selected_lang).strip()
        except AttributeError:
            raise fetch.FetchErrorrror('Couldn\'t find selected language.')

    def _parse_balance(self, balance):
        # Sign is at the end.
        balance = balance[-1] + balance[:-1]
        return fetch.parse_decimal_number(balance, 'de_CH')

    def _check_logged_in(self):
        if not self._logged_in:
            raise fetch.FetchErrorrror('Not logged in.')
