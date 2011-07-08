#!/usr/bin/python

"""Downloads bank account data from banking websites."""

import csv
import datetime
import getpass
import locale
import logging
import re
import string
import urllib
import urlparse

import BeautifulSoup
import mechanize

import model


CONTENT_TYPE_HEADER = 'Content-Type'
EXTRACT_HTTP_CHARSET_PATTERN = re.compile(r'charset=["\']?([a-zA-Z0-9-_]+)')
WHITESPACE_PATTERN = re.compile(r' +')

logger = logging.getLogger(__name__)


class FetchError(Exception):
    """An error while fetching the account data."""


class Browser(mechanize.Browser):
    def __init__(self):
        mechanize.Browser.__init__(self)
        
        self.set_handle_equiv(True)
        # Still experimental.
        #self.set_handle_gzip(True)
        self.set_handle_redirect(True)
        self.set_handle_referer(True)
        self.set_handle_robots(False)
        
        # Follows refresh 0 but not hangs on refresh > 0
        #br.set_handle_refresh(mechanize._http.HTTPRefreshProcessor(), max_time=1)
        
        # Want debugging messages?
        #br.set_debug_http(True)
        #br.set_debug_redirects(True)
        #br.set_debug_responses(True)
        
        self.addheaders = [('User-agent', (
                'Mozilla/5.0 (X11; U; Linux i686; en-US; rv:1.9.0.1) '
                'Gecko/2008071615 Fedora/3.0.1-1.fc9 Firefox/3.0.1'))]


class Bank(object):
    """Logs into a bank account website.

    Will prompt the user if either user name or password are not defined.
    
    @type username: unicode
    @param username: The user name.
    
    @type password: unicode
    @param password: The password.
    """
    def login(self, username=None, password=None):
        raise NotImplementedError()

    """Returns the names of all accounts.

    @rtype: [unicode]
    @return: The names of all accounts.
    """
    def get_account_names(self):
        raise NotImplementedError()

    """Returns all transactions within the given date range.

    @type name: unicode
    @param name: The account name.

    @type start: datetime.datetime
    @param start: Start date, inclusive.

    @type end: datetime.datetime
    @param end: End date, exclusive.

    @rtype: [model.Transaction]
    @return: The matching transactions.
    """
    def get_transactions(self, name, start, end):
        raise NotImplementedError()


"""Fetcher for Deutsche Kreditbank (http://www.dkb.de/).

The accounts for a user will be identified by the bank account number (digits)
or the obfuscated credit card number (1234******5678).
"""
class DeutscheKreditBank(Bank):
    _BASE_URL = 'https://banking.dkb.de/dkb/-'
    _OVERVIEW_PATH = (
            '?$part=DkbTransactionBanking.index.menu'
            '&treeAction=selectNode'
            '&node=1'
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

    def __init__(self):
        self._browser = Browser()
        self._logged_in = False
        self._account_names = None

    def login(self, username=None, password=None):
        self._logged_in = False
        self._account_names = None
        
        if not username:
            username = raw_input('User: ')
        
        if not password:
            password = getpass.getpass('PIN: ')
        
        browser = self._browser
        
        logger.info('Loading login page...')
        browser.open(self._BASE_URL)
        
        forms = list(browser.forms())
        if len(forms) < 1:
            raise FetchError('Login form not found')
        
        browser.select_form(nr=0)
        form = browser.form
        form['j_username'] = username
        form['j_password'] = password
        logger.info('Logging in with user name %s...' % username)
        response = browser.submit()
        content_type_header = response.info().getheader(CONTENT_TYPE_HEADER)
        html = _decode_content(response.read(), content_type_header)
        
        if 'Finanzstatus' not in html:
            raise FetchError('Login failed.')
        
        self._logged_in = True
        logger.info('Log-in sucessful.')

    def get_account_names(self):
        self._check_logged_in()
        
        if self._account_names is not None:
            return self._account_names
        
        browser = self._browser
        
        overview_url = urlparse.urljoin(self._BASE_URL, self._OVERVIEW_PATH)
        logger.info('Loading accounts overview...')
        response = browser.open(overview_url)
        content_type_header = response.info().getheader(CONTENT_TYPE_HEADER)
        html = _decode_content(response.read(), content_type_header)
        
        soup = BeautifulSoup.BeautifulSoup(html)
        details_icons = soup.findAll('img', {'alt': 'Details'})
        if not details_icons:
            raise FetchError('No accounts found.')
        
        self._account_names = []
        for details_icon in details_icons:
            details_row = details_icon.parent.parent.parent
            account_name = details_row.find('td').text
            self._account_names.append(account_name)
        
        logger.info('Found %i accounts.' % len(self._account_names))
        return self._account_names

    def get_transactions(self, name, start, end):
        self._check_logged_in()
        
        account_names = self.get_account_names()
        try:
            account_index = account_names.index(name)
        except ValueError:
            raise FetchError('Unknown account: %s' % name)
        is_credit_card = self._is_credit_card(name)
        
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
        response = browser.open(csv_url)
        content_type_header = response.info().getheader(CONTENT_TYPE_HEADER)
        csv_data = _decode_content(response.read(), content_type_header)
        if name not in csv_data:
            raise FetchError('Account name not found in CSV.')
        
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
            payee = _normalize_text(row[3])
            memo = _normalize_text(row[4])
            
            account = row[5]
            if account:
                account = int(account)
                memo += '\nAccount: %i' % account
            
            clearing = row[6]
            if clearing:
                clearing = int(clearing)
                memo += '\nClearing: %i' % clearing
            
            amount = _parse_decimal_number(row[7], 'de_DE')
            
            return model.Transaction(date, amount, payee, memo)
        except ValueError, e:
            logger.debug('Skipping invalid row: %s' % row)
            return
    
    def _get_transaction_from_credit_card_row(self, row):
        if len(row) != 7:
            return

        try:
            date = datetime.datetime.strptime(row[2], self._DATE_FORMAT)
            memo = _normalize_text(row[3])
            amount = _parse_decimal_number(row[4], 'de_DE')
            
            orig_amount = row[5]
            if orig_amount:
                memo += '\nOriginal amount: %s' % orig_amount
            
            return model.Transaction(date, amount, memo=memo)
        except ValueError, e:
            logger.debug('Skipping invalid row: %s' % row)
            return

    def _check_logged_in(self):
        if not self._logged_in:
            raise FetchError('Not logged in.')
        


"""Fetcher for PostFinance (http://www.postfincance.ch/).

The accounts for a user will be identified by the bank account number (digits)
or the obfuscated credit card number (1234******5678).
"""
class PostFinance(Bank):
    _BASE_URL = 'https://e-finance.postfinance.ch/ef/secure/html/'
    _LOGIN_PATH = '?login&p_spr_cd=4'  # 4 = English.
    _DATE_FORMAT = '%d.%m.%Y'

    def __init__(self):
        self._browser = Browser()
        self._logged_in = False
        self._account_names = None

    def login(self, username=None, password=None):
        self._logged_in = False
        self._account_names = None

        if not username:
            username = raw_input('E-Finance number: ')

        if not password:
            password = getpass.getpass('Password: ')

        browser = self._browser
        
        # First login phase: E-Finance number and password.
        logger.info('Loading login page...')
        browser.open(self._BASE_URL + self._LOGIN_PATH)

        forms = list(browser.forms())
        if len(forms) != 1:
            raise FetchError('Login form not found')

        browser.select_form(nr=0)
        form = browser.form
        form['p_et_nr'] = username
        form['p_passw'] = password
        logger.info('Logging in with user name %s...' % username)
        response = browser.submit()
        content_type_header = response.info().getheader(CONTENT_TYPE_HEADER)
        xhtml = _decode_content(response.read(), content_type_header)

        # Second login phase: Challenge and security token.
        soup = BeautifulSoup.BeautifulStoneSoup(xhtml)
        challengeElement = soup.find('span', {'id': 'challenge'})
        if not challengeElement:
            raise FetchError('Security challenge not found.')
        print 'Please enter your login token.'
        print 'Challenge:', challengeElement.getText()
        token = raw_input('Login token: ')
        
        forms = list(browser.forms())
        if len(forms) != 1:
            raise FetchError('Login token form not found.')
        
        browser.select_form(nr=0)
        browser.form['p_si_nr'] = token
        logger.info('Logging in with token %s...' % token)
        response = browser.submit()

        # Login successful?
        accounts_links = browser.links(text='Accounts and assets')
        if not accounts_links:
            raise FetchError('Login failed.')
        
        self._logged_in = True
        logger.info('Log-in sucessful.')

    def get_account_names(self):
        self._check_logged_in()

        if self._account_names is not None:
            return self._account_names

        browser = self._browser

        logger.info('Loading accounts overview...')
        accounts_link = browser.find_link(text='Accounts and assets')
        response = browser.follow_link(accounts_link)
        content_type_header = response.info().getheader(CONTENT_TYPE_HEADER)
        xhtml = _decode_content(response.read(), content_type_header)

        soup = BeautifulSoup.BeautifulStoneSoup(xhtml)
        account_names = []
        try:
            payment_accounts_headline = soup.find(
                    'h2', text='Payment accounts').parent
            payment_accounts_table = payment_accounts_headline.findNext('table')
            asset_accounts_headline = soup.find('h2', text='Assets').parent
            asset_accounts_table = asset_accounts_headline.findNext('table')
            for account_table in payment_accounts_table, asset_accounts_table:
                account_rows = account_table.find('tbody').findAll('tr')
                for account_row in account_rows:
                    account_name = account_row.findAll('td')[2].getText()
                    account_names.append(account_name)
        except (AttributeError, IndexError):
            raise FetchError('Couldn\'t load account names.')
        self._account_names = account_names
        
        logger.info('Found %i account_namess.' % len(self._account_names))
        return self._account_names

    def get_transactions(self, name, start, end):
        self._check_logged_in()

        account_names = self.get_account_names()
        if name not in account_names:
            raise FetchError('Unknown account: %s' % name)

        browser = self._browser
        
        # Open transactions search form.
        logger.info('Opening transactions search form...')
        accounts_link = browser.find_link(text='Accounts and assets')
        browser.follow_link(accounts_link)
        transactions_link = browser.find_link(text='Transactions')
        browser.follow_link(transactions_link)
    
        # Perform search.
        logger.info('Performing transactions search...')
        formatted_start = start.strftime(self._DATE_FORMAT)
        end_inclusive = end - datetime.timedelta(1)
        formatted_end = end_inclusive.strftime(self._DATE_FORMAT)
        try:
            browser.select_form(name="bewegungen")
        except mechanize.FormNotFoundError, e:
            raise FetchError('Transactions form not found.')
        form = browser.form
        form['p_buchdat_von'] = formatted_start
        form['p_buchdat_bis'] = formatted_end
        form['p_buch_art'] = '9',  # 9 = All transaction types.
        form['p_lkto_nr'] = name.replace('-', ''),
        form['p_anz_buchungen'] = '100',  # 100 entries per page.
        response = browser.submit()
        content_type_header = response.info().getheader(CONTENT_TYPE_HEADER)
        xhtml = _decode_content(response.read(), content_type_header)

        # Parse response.
        if name not in xhtml:
            raise FetchError('Transactions search failed.')
        if 'No booking entry found' in xhtml:
            logging.info('Couldn\'t find any transactions.')
            return []
        soup = BeautifulSoup.BeautifulStoneSoup(xhtml)
        try:
            table_rows = soup.find('table').find('tbody').findAll('tr')
        except AttributeError:
            raise FetchError('Couldn\'t find transactions table.')
        transactions = []
        for table_row in table_rows:
            cells = table_row.findAll('td')
        
            date = cells[1].getText()
            try:
                date = datetime.datetime.strptime(date, self._DATE_FORMAT)
            except ValueError, e:
                logger.warning(
                        'Skipping transaction with invalid date %s.', date)
                continue
        
            memo = _normalize_text(cells[2].getText())
            
            credit = cells[3].getText().replace('&nbsp;', '')
            debit = cells[4].getText().replace('&nbsp;', '')
            if credit:
                amount = credit
            else:
                amount = '-' + debit
            try:
                amount = _parse_decimal_number(amount, 'de_CH')
            except ValueError, e:
                logger.warning(
                        'Skipping transaction with invalid amount %s.', amount)
                continue
            
            transaction = model.Transaction(date, amount, memo=memo)
            transactions.append(transaction)

        # More than 100 transactions?
        try:
            browser.select_form(name="forward")
            logging.warning(
                    'Found more than 100 transactions. '
                    'Please be more specific with the dates.')
        except mechanize.FormNotFoundError, e:
            pass
        
        logger.info('Found %i transactions.' % len(transactions))

        return transactions

    def _check_logged_in(self):
        if not self._logged_in:
            raise FetchError('Not logged in.')


def _decode_content(content, content_type_header):
    """Returns the decoded content of a urlfetch.fetch() response as unicode.

    @type content: str
    @param content: The encoded content.
    
    @type content_type_header: str or None
    @param content_type_header: The Content-Type header, if exists.

    @rtype: unicode
    @return: The decoded content.

    @raise UnicodeDecodeError: If the content could not be decoded.
    """
    encoding = None
    if content_type_header:
        match = EXTRACT_HTTP_CHARSET_PATTERN.search(content_type_header)
        if match:
            encoding = match.group(1)
            logger.debug('Charset from content-type header: %s.' % encoding)
        else:
            logger.debug(
                    'Couldn\'t extract encoding from Content-Type header: %s.' %
                    content_type_header)
    else:
        logger.info('No Content-Type header.')

    if not encoding:
        logger.info(
                'Couldn\'t determine content encoding. Fallback to latin-1.')
        encoding = 'iso-8859-1'

    try:
        return content.decode(encoding, 'replace')
    except LookupError:
        logger.info('Unknown encoding %s. Fallback to latin-1.' % encoding)
        encoding = 'iso-8859-1'
        return content.decode(encoding, 'replace')


def _normalize_text(text):
    """Returns a normalized version of the input text.
    
    Removes double spaces and "Capitalizes All Words" if they are "ALL CAPS".
    
    @type text: unicode
    @param text: The input text.
    
    @rtype: unicode
    @return: A normalized version of the input text.
    """
    text = WHITESPACE_PATTERN.sub(' ', text)
    if text.isupper():
        text = string.capwords(text)
    return text


def _parse_decimal_number(number_string, lang):
    """Parses a decimal number string into a float.
    
    Can also handle thousands separators.
    
    @type number_string: unicode
    @param number_string: The decimal number as a string.
    
    @type lang: str
    @param lang: The locale of the format.
    
    @rtype: float
    @return: The parsed number.
    
    @raise ValueError: If the string is not a valid decimal number.
    """
    orig_locale = locale.getlocale(locale.LC_ALL)
    locale.setlocale(locale.LC_ALL, lang)
    thousands_sep = locale.localeconv()['mon_thousands_sep']
    if lang == 'de_CH':  # Buggy Swiss locale.
        locale.setlocale(locale.LC_ALL, 'en_US')
        thousands_sep = "'"
    try:
        return locale.atof(number_string.replace(thousands_sep, ''))
    finally:
        locale.setlocale(locale.LC_ALL, orig_locale)


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
