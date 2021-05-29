import re
import string


WHITESPACE_PATTERN = re.compile(r' +')


class Importer(object):
    """Base class for an importer for financial transactions."""

    def __init__(self, debug=False):
        """Create a new importer.

        @type debug: bool
        @param debug: Whether to run in debug mode.
        """
        self._debug = debug

    def import_transactions(self, file=None, filename=None):
        """Imports transactions from a file or filename and returns Model data.

        @type file: io.IOBase or None
        @param file: The file object to read from.

        @type filename: str or None
        @param filename: The filename to read from.

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
