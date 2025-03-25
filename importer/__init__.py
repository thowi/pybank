import codecs
import csv
import io
import locale
import logging
import re
import string
import sys
from typing import Optional, List, Tuple, Dict, Union

import chardet

import model


WHITESPACE_PATTERN = re.compile(r' +')

logging.getLogger('chardet.charsetprober').setLevel(logging.INFO)
logger = logging.getLogger(__name__)


class Importer(object):
    """Base class for an importer for financial transactions."""

    def __init__(self, debug: bool = False):
        """Create a new importer.

        @param debug: Whether to run in debug mode.
        """
        self._debug = debug

    def import_transactions(
            self,
            file: Optional[io.IOBase] = None,
            filename: Optional[str] = None,
            currency: Optional[str] = None) -> List[model.Transaction]:
        """Imports transactions from a file or filename and returns Model data.

        @param file: The file object to read from.
        @param filename: The filename to read from.
        @param currency: Optionally filter the transactions for a currency.
        @return: The imported transactions.
        """
        raise NotImplementedError()


def normalize_text(text: Optional[str]) -> Optional[str]:
    """Returns a normalized version of the input text.

    Removes double spaces and "Capitalizes All Words" if they are "ALL CAPS".

    @param text: The input text.
    @return: A normalized version of the input text.
    """
    if text is None:
        return None
    text = WHITESPACE_PATTERN.sub(' ', text)
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if line.isupper():
            line = string.capwords(line)
        lines.append(line)
    return '\n'.join(lines)


def parse_decimal_number(number_string: str, lang: str) -> float:
    """Parses a decimal number string into a float.

    Can also handle thousands separators.

    @param number_string: The decimal number as a string.
    @param lang: The locale of the format.
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


def _detect_encoding(
        file: Optional[io.IOBase] = None,
        filename: Optional[str] = None) -> str:
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


def open_input_file(
        file: Optional[io.IOBase] = None,
        filename: Optional[str] = None,
        encoding: Optional[str] = None) -> object:
    encoding = _detect_encoding(file, filename)
    if file:
        return codecs.getreader(encoding)(sys.stdin.detach())
    elif filename:
        return codecs.open(filename, 'r', encoding)
    else:
        raise Exception('Either file or filename must be specified.')


def read_csv_with_header(
        file: Optional[io.IOBase] = None,
        filename: Optional[str] = None) \
        -> Tuple[Dict[str, str], List[Dict[str, str]]]:
    """Processes a CSV file with a header and returns metadata and transactions.

    Some CSV files are a bit special and have a multi-line header, body, and
    perhaps a footer.

    Using this intermediate data structure allows for easier processing of some
    CSV files.

    @param file: The file object to read from.
    @param filename: The filename to read from.
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
            # Remove empty metadata columns.
            if not col_names:
                row = [col for col in row if col]

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

def get_value(row: Dict[str, str], keys: List[str]) -> Optional[str]:
    """Returns the first value found in the row dict for the given keys.
    
    @param row: The row to search.
    @param keys: The keys to search for.
    @return: The first value found in the row for the given keys.
    """
    for key in keys:
        if key in row:
            return row[key]
    return None
