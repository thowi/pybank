#!/usr/bin/env python3

"""Converts financial transaction statements into the desired output format.

Supported financial institutions:
* Deutsche Kreditbank http://www.dkb.de/. Checking account and credit card.
* PostFinance http://www.postfinance.ch/. Checking account and credit card.
* Interactive Brokers http://www.interactivebrokers.com/. Trades.
* Revolut http://www.revolut.com/. Credit card for all currencies.

For more information see http://github.com/thowi/pybank.
"""

import logging
import getopt
import sys

import charset_normalizer

import pybank.importer.auto
import pybank.importer.dkb
import pybank.importer.ib
import pybank.importer.postfinance
import pybank.importer.revolut
import pybank.importer.schwab
import pybank.importer.wise
from pybank import qif


IMPORTER_BY_NAME = {
    'auto': pybank.importer.auto.AutoImporter,
    'dkb-checking': pybank.importer.dkb.DkbCheckingImporter,
    'dkb-credit-card': pybank.importer.dkb.DkbCreditCardImporter,
    'interactive-brokers': pybank.importer.ib.InteractiveBrokersImporter,
    'postfinance-checking':
            pybank.importer.postfinance.PostFinanceCheckingImporter,
    'postfinance-credit-card':
            pybank.importer.postfinance.PostFinanceCreditCardImporter,
    'revolut': pybank.importer.revolut.RevolutImporter,
    'schwab-brokerage': pybank.importer.schwab.SchwabBrokerageImporter,
    'wise': pybank.importer.wise.WiseImporter,
}
LOG_FORMAT = '%(message)s'
LOG_FORMAT_DEBUG = '%(levelname)s %(name)s: %(message)s'


logger = logging.getLogger(__name__)


class Usage(Exception):
    """Usage: convert.py [options] [inputfile.csv]

    Will read from inputfile.csv if specified, else from STDIN.
    Will write to STDOUT.

    Options:
    [-h|--help]
    [-i importer|--importer=importer]
    [-c currency|--currency=USD]       Filters the transactions for a currency.
    [-d|--debug]
    """
    def __init__(self, msg=''):
        self.msg = msg

    def __str__(self):
        importers = ', '.join(sorted(IMPORTER_BY_NAME.keys()))
        return '\n'.join((
                self.__doc__, self.msg, 'Available importers: %s.' % importers))


def _parse_args(argv):
    importer_name = None
    currency = None
    debug = False

    options = 'hi:c:d'
    options_long = ['help', 'importer=', 'currency=', 'debug']
    try:
        opts, other_args = getopt.getopt(argv[1:], options, options_long)
    except getopt.error as msg:
        raise Usage(msg)
    for opt, arg in opts:
        if opt in ('-h', '--help'):
            print(Usage())
            return 0
        if opt in ('-i', '--importer'):
            importer_name = arg
        if opt in ('-c', '--currency'):
            currency = arg
        if opt in ('-d', '--debug'):
            debug = True

    if not importer_name:
        raise Usage('Must specify an importer name.')
    if importer_name not in IMPORTER_BY_NAME:
        raise Usage('Unknown importer: %s.' % importer_name)

    if len(other_args) > 1:
        raise Usage('Too many non-option arguments: %s.' % other_args)

    return (
            importer_name, currency, debug,
            other_args[0] if other_args else None)


def _convert_file(importer_name, currency, debug, filename):
    importer_class = IMPORTER_BY_NAME[importer_name]
    importer = importer_class(debug)

    if filename:
        with _open_file(filename) as file:
            transactions = importer.import_transactions(
                    file=file, currency=currency)
    else:
        transactions = importer.import_transactions(
                file=sys.stdin, currency=currency)

    try:
        txns_qif = (qif.serialize_transaction(t) for t in transactions)
        print('\n'.join(txns_qif))
    except qif.SerializationError as e:
        logger.error('Serialization error: %s.', e)
        return


def _open_file(filename):
    encoding_guess = charset_normalizer.from_path(filename).best()
    if encoding_guess:
        logger.debug('Detected encoding: %s.' % encoding_guess.encoding)
        encoding = encoding_guess.encoding
        # Strip the BOM from UTF-8 files.
        if encoding.lower() == 'utf_8':
            encoding = 'utf-8-sig'
    else:
        logger.warning('Failed to detect encoding. Falling back to utf-8.')
        encoding = 'utf-8-sig'
    # Use newline='' as suggested by the csv.readerdocs.
    return open(filename, 'r', encoding=encoding, newline='')


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv
    try:
        (importer_name, currency, debug, input_filename) = _parse_args(argv)
    except Usage as err:
        print(err, file=sys.stderr)
        return 2

    if debug:
        logging.basicConfig(format=LOG_FORMAT_DEBUG, level=logging.DEBUG)
    else:
        logging.basicConfig(format=LOG_FORMAT, level=logging.INFO)

    try:
        _convert_file(importer_name, currency, debug, input_filename)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:
        logger.error('Error while converting file: %s' % e)
        if debug:
            import pdb; pdb.post_mortem()
        return 2

    return 0


if __name__ == '__main__':
    sys.exit(main())

