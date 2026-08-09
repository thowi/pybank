import re
import string

WHITESPACE_PATTERN = re.compile(r' +')


def normalize_text(text: str | None) -> str | None:
    """Returns a normalized version of the input text.

    Removes double spaces and "Capitalizes All Words" if they are "ALL CAPS".

    Part of the import-id contract, see docs/importing.md: changing this
    changes every hash, which is what the version prefix exists for.

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
