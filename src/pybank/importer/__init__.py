import locale
import logging
from typing import TextIO

from .. import model

logger = logging.getLogger(__name__)


class Importer:
    """Base class for an importer for financial transactions."""

    def __init__(self, debug: bool = False):
        """Create a new importer.

        :param debug: Whether to run in debug mode
        """
        self._debug = debug

    def import_transactions(
        self, file: TextIO, currency: str | None = None
    ) -> list[model.Transaction]:
        """Imports transactions from a file and returns Model data.

        :param file: The file object to read from
        :param currency: Optionally filter the transactions for a currency
        :return: The imported transactions
        :raises Exception: If any import error occurs
        """
        raise NotImplementedError()

    def can_import(self, file: TextIO) -> bool:
        """Returns whether the importer can import the given file.

        :param file: The file object to read from
        :return: Whether the importer can import the given file
        """
        raise NotImplementedError()


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
