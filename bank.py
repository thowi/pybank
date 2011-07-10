#!/usr/bin/python

"""Downloads bank account data from banking websites.

Supported banks:
* Deutsche Kreditbank http://www.dkb.de/

With inspiration from Jens Herrmann's web_bank.py (http://qoli.de).

For more information see http://github.com/thowi/pybank.
"""

import datetime
import logging
import getopt
import re
import sys

import model
import fetch
import qif

BANK_BY_NAME = {
    'dkb': fetch.DeutscheKreditBank,
    'postfinance': fetch.PostFinance,
}
DATE_FORMAT = '%Y-%m-%d'
INVALID_FILENAME_CHARACTERS_PATTERN = re.compile(r'[^a-zA-Z0-9-_.]')
LOG_FORMAT = '%(message)s'
LOG_FORMAT_DEBUG = '%(levelname)s %(name)s: %(message)s'

logger = logging.getLogger(__name__)


class Usage(Exception):
    """Usage: bank.py
    [-h|--help]
    [-b bank|--bank=bank]
    [-u username|--username=username]
    [-p password|--password=password]
    [-a account|--account=account]     Can be repeated. Default: All accounts.
    [-f YYYY-MM-DD|--from=YYYY-MM-DD]  Default: First day of this month.
    [-t YYYY-MM-DD|--till=YYYY-MM-DD]  Default: Today.
    [-o outfile|--outfile=outfile]     Default: STDOUT.
        Variables will be replaced: %(bank)s %(account)s %(from)s %(till)s
    [-v|--verbose]
    """
    def __init__(self, msg=''):
        self.msg = msg
    
    def __str__(self):
        banks = 'Available banks: %s.' % ', '.join(sorted(BANK_BY_NAME.keys()))
        return '\n'.join((self.__doc__, self.msg, banks))


def _parse_args(argv):
    bank_name = None
    username = None
    password = None
    accounts = []
    from_date = None
    till_date = None
    output_filename = None
    debug = False
    
    options = 'hb:u:a:p:f:t:o:v'
    options_long = [
            'help', 'bank=', 'username=', 'password=', 'account=', 'from=',
            'till=', 'outfile=', 'verbose']
    try:
        opts, args = getopt.getopt(argv[1:], options, options_long)
    except getopt.error, msg:
        raise Usage(msg)
    for opt, arg in opts:
        if opt in ('-h', '--help'):
            print Usage()
            return 0
        if opt in ('-b', '--bank'):
            bank_name = arg
        if opt in ('-u', '--username'):
            username = arg
        if opt in ('-p', '--password'):
            password = arg
        if opt in ('-a', '--account'):
            accounts.append(arg)
        if opt in ('-f', '--from'):
            from_date = arg
        if opt in ('-t', '--till'):
            till_date = arg
        if opt in ('-o', '--outfile'):
            output_filename = arg
        if opt in ('-v', '--verbose'):
            debug = True
        
    if not bank_name:
        raise Usage('Must specify a bank.')
    if bank_name not in BANK_BY_NAME:
        raise Usage('Unknown bank: %s.', bank_name)

    if from_date:
        try:
            from_date = datetime.datetime.strptime(from_date, DATE_FORMAT)
        except ValueError:
            raise Usage('Invalid from date: %s.', from_date)
    else:
        # Beginning of this month.
        now = datetime.datetime.now()
        from_date = datetime.datetime(now.year, now.month, 1)

    if till_date:
        try:
            till_date = datetime.datetime.strptime(till_date, DATE_FORMAT)
        except ValueError:
            raise Usage('Invalid until date: %s.', till_date)
    else:
        till_date = datetime.datetime.now()
    
    return (
        bank_name, username, password, accounts, from_date, till_date,
        output_filename, debug)


def _fetch_accounts(
        bank_name, username, password, account_names, from_date, till_date,
        output_filename):
    bank_class = BANK_BY_NAME[bank_name]
    bank = bank_class()

    bank.login(username=username, password=password)
    
    available_accounts = bank.get_accounts()
    if not available_accounts:
        logger.warning('No accounts found.')
        return
    
    logger.info(
            'Available accounts: %s.',
            ', '.join(unicode(a) for a in available_accounts))
    
    if not account_names:
        # Download all accounts by default.
        accounts = available_accounts
    else:
        accounts_by_name = {}
        for account in available_accounts:
            accounts_by_name[account.name] = account
        accounts = []
        for account_name in account_names:
            try:
                accounts.append(accounts_by_name[account_name])
            except KeyError:
                logger.error('Account not found: %s.', account_name)
    
    for account in accounts:
        logger.info('Fetching account: %s.', account.name)
        account.transactions = bank.get_transactions(
                account, from_date, till_date)
        output = _open_file(
                output_filename, bank_name, account.name, from_date, till_date)
        print >>output, qif.serialize_account(account).encode('utf-8')


def _open_file(output_filename, bank_name, account_name, from_date, till_date):
    if not output_filename:
        return sys.stdout
    filename_vars = {
        'bank': bank_name, 'account': account_name,
        'from': from_date.strftime(DATE_FORMAT),
        'till': till_date.strftime(DATE_FORMAT),
    }
    formatted_filename = output_filename % filename_vars
    escaped_filename = INVALID_FILENAME_CHARACTERS_PATTERN.sub(
            '_', formatted_filename)
    try:
        logger.info('Writing to file: %s.', escaped_filename)
        return open(escaped_filename, 'w')
    except IOError, err:
        print >>sys.stderr, err.msg


def main(argv=None):
    if argv is None:
        argv = sys.argv
    try:
        (bank_name, username, password, accounts, from_date, till_date,
        output_filename, debug) = _parse_args(argv)
    except Usage, err:
        print >>sys.stderr, err
        return 2

    if debug:
        logging.basicConfig(format=LOG_FORMAT_DEBUG, level=logging.DEBUG)
    else:
        logging.basicConfig(format=LOG_FORMAT, level=logging.INFO)

    try:
        _fetch_accounts(
                bank_name, username, password, accounts, from_date, till_date,
                output_filename)
    except fetch.FetchError, e:
        logger.error('Error while fetching transactions: %s' % e)
        return 2

    return 0


if __name__ == '__main__':
    sys.exit(main())
