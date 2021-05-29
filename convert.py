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

import importer.postfinance
import qif

IMPORTER_BY_NAME = {
    'postfinance-checking': importer.postfinance.PostFinanceCheckingImporter,
    'postfinance-credit-card':
            importer.postfinance.PostFinanceCreditCardImporter,
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
    input_filename = None
    debug = False

    options = 'hi:d'
    options_long = ['help', 'importer=', 'debug']
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
        if opt in ('-d', '--debug'):
            debug = True

    if not importer_name:
        raise Usage('Must specify an importer name.')
    if importer_name not in IMPORTER_BY_NAME:
        raise Usage('Unknown importer: %s.' % importer_name)

    if len(other_args) > 1:
        raise Usage('Too many non-option arguments: %s.' % other_args)

    return (importer_name, debug, other_args[0] if other_args else None)


def _convert_file(importer_name, input_filename, debug):
    importer_class = IMPORTER_BY_NAME[importer_name]
    importer = importer_class(debug)
    input_file = None if input_filename else sys.stdin
    transactions = importer.import_transactions(
            file=input_file, filename=input_filename)

    try:
        txns_qif = (qif.serialize_transaction(t) for t in transactions)
        print('\n'.join(txns_qif))
    except qif.SerializationError as e:
        logger.error('Serialization error: %s.', e)
        return


def main(argv=None):
    if argv is None:
        argv = sys.argv
    try:
        (importer_name, debug, input_filename) = _parse_args(argv)
    except Usage as err:
        print(err, file=sys.stderr)
        return 2

    if debug:
        logging.basicConfig(format=LOG_FORMAT_DEBUG, level=logging.DEBUG)
    else:
        logging.basicConfig(format=LOG_FORMAT, level=logging.INFO)

    try:
        _convert_file(importer_name, input_filename, debug)
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
