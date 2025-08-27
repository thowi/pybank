import csv
import io
import locale
import logging
import re
import string

from .. import model


WHITESPACE_PATTERN = re.compile(r' +')

logger = logging.getLogger(__name__)


class Importer:
    """Base class for an importer for financial transactions."""

    def __init__(self, debug: bool = False):
        """Create a new importer.

        :param debug: Whether to run in debug mode
        """
        self._debug = debug

    def import_transactions(
            self, file: io.IOBase, currency: str | None = None) \
            -> list[model.Transaction]:
        """Imports transactions from a file and returns Model data.

        :param file: The file object to read from
        :param currency: Optionally filter the transactions for a currency
        :return: The imported transactions
        :raises Exception: If any import error occurs
        """
        raise NotImplementedError()

    def can_import(self, file: io.IOBase) -> bool:
        """Returns whether the importer can import the given file.

        :param file: The file object to read from
        :return: Whether the importer can import the given file
        """
        raise NotImplementedError()


def normalize_text(text: str | None) -> str | None:
    """Returns a normalized version of the input text.

    Removes double spaces and "Capitalizes All Words" if they are "ALL CAPS".

    :param text: The input text.
    :return: A normalized version of the input text.
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

    :param number_string: The decimal number as a string.
    :param lang: The locale of the format.
    :return: The parsed number.
    :raises ValueError: If the string is not a valid decimal number.
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


def read_csv_with_header(file: io.IOBase) \
        -> tuple[dict[str, str], list[dict[str, str]]]:
    """Processes a CSV file with a header and returns metadata and transactions.

    Some CSV files are a bit special and have a multi-line header, body, and
    perhaps a footer.

    Using this intermediate data structure allows for easier processing of some
    CSV files.

    :param file: The file object to read from.
    :return: The metadata as a dict and the rows as a list of dicts, each
    mapping from the columen name to the value (similar to `DictReader`).
    """
    # In case the file was read before, e.g. in the can_import pass.
    file.seek(0)
    reader = csv.reader(file, delimiter=';', quotechar='"')
    # Read metadata.
    metadata = {}
    col_names = None
    rows = []
    for row in reader:
        # Clean up the row.
        # Some CSVs wrap the values in a formula syntax.
        clean_row = []
        for col in row:
            if col.startswith('="') and col.endswith('"'):
                col = col[2:-1]  # strip ="
            clean_row.append(col)
        row = clean_row

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


def get_value(row: dict[str, str], keys: list[str]) -> str | None:
    """Returns the first value found in the row dict for the given keys.

    :param row: The row to search.
    :param keys: The keys to search for.
    :return: The first value found in the row for the given keys.
    """
    for key in keys:
        if key in row:
            return row[key]
    return None
