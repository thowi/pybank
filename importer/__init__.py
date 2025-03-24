import codecs
import csv
import locale
import logging
import re
import string
import sys

import chardet


WHITESPACE_PATTERN = re.compile(r' +')

logging.getLogger('chardet.charsetprober').setLevel(logging.INFO)
logger = logging.getLogger(__name__)


class Importer(object):
    """Base class for an importer for financial transactions."""

    def __init__(self, debug=False):
        """Create a new importer.

        @type debug: bool
        @param debug: Whether to run in debug mode.
        """
        self._debug = debug

    def import_transactions(self, file=None, filename=None, currency=None):
        """Imports transactions from a file or filename and returns Model data.

        @type file: io.IOBase or None
        @param file: The file object to read from.

        @type filename: str or None
        @param filename: The filename to read from.

        @type currency: str or None
        @param currency: Optionally filter the transactions for a currency.

        @rtype: [model.Transaction]
        @return: The imported transactions.
        """
        raise NotImplementedError()


def normalize_text(text):
    """Returns a normalized version of the input text.

    Removes double spaces and "Capitalizes All Words" if they are "ALL CAPS".

    @type text: unicode
    @param text: The input text.

    @rtype: unicode
    @return: A normalized version of the input text.
    """
    text = WHITESPACE_PATTERN.sub(' ', text)
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if line.isupper():
            line = string.capwords(line)
        lines.append(line)
    return '\n'.join(lines)


def parse_decimal_number(number_string, lang):
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


def _detect_encoding(file=None, filename=None):
    if file is None and filename is not None:
        file = open(filename, 'rb')
    rawdata = file.read()
    file.seek(0)
    result = chardet.detect(rawdata)
    encoding = result['encoding'] if result['confidence'] > 0.5 else None
    if encoding:
        logger.debug('Detected encoding: %s' % encoding)
        return encoding
    else:
        logger.warning('Failed to detect encoding. Falling back to utf-8.')
        return 'utf-8'


def open_input_file(file=None, filename=None, encoding=None):
    encoding = _detect_encoding(file, filename)
    if file:
        return codecs.getreader(encoding)(sys.stdin.detach())
    elif filename:
        return codecs.open(filename, 'r', encoding)
    else:
        raise Exception('Either file or filename must be specified.')


def read_csv_with_header(file=None, filename=None):
    """Processes a CSV file with a header and returns metadata and transactions.

    Some CSV files are a bit special and have a multi-line header, body, and
    perhaps a footer.

    Using this intermediate data structure allows for easier processing of some
    CSV files.

    @type file: io.IOBase or None
    @param file: The file object to read from.

    @type filename: str or None
    @param filename: The filename to read from.

    @rtype: (dict, [{str: str}])
    @return: The metadata as a dict and the rows as a list of dicts, each
    mapping from the columen name to the value (similar to `DictReader`).
    """
    with open_input_file(file, filename) as file:
        reader = csv.reader(file, delimiter=';', quotechar='"')
        # Read metadata.
        metadata = {}
        col_names = None
        rows = []
        for row in reader:
            # Skip empty/irrelevant rows.
            if len(row) < 2:
                continue
            
            # Read metadata.
            if len(row) == 2 and not col_names:
                metadata[row[0]] = row[1]
                continue
            
            # Read column names.
            if not col_names:
                col_names = row
                continue
            
            # Read transaction rows.
            rows.append(dict(zip(col_names, row)))
        
        return metadata, rows

