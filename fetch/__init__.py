#!/usr/bin/python

import datetime
import locale
import logging
import re
import string
import time

from selenium.common import exceptions


WHITESPACE_PATTERN = re.compile(r' +')

logger = logging.getLogger(__name__)


class FetchError(Exception):
    """An error while fetching the account data."""


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


def get_element_or_none(lookup_callable):
    """Returns the element for the lookup or None if not found.

    @type lookup_callable: callable
    @param lookup_callable: The lookup to execute.

    @rtype: Element or None
    @return: The element for the lookup or None if not found.
    """
    try:
        return lookup_callable()
    except exceptions.NoSuchElementException:
        return None


def is_element_present(lookup_callable):
    """Returns whether the lookup was successful or a NoSuchElementException was
    caught.

    @type lookup_callable: callable
    @param lookup_callable: The lookup to execute.

    @rtype: bool
    @return: Returns whether the lookup was successful.
    """
    return get_element_or_none(lookup_callable) is not None


def is_element_displayed(lookup_callable):
    """Returns whether the lookup was successful, the element was found, and it
    is displayed.

    @type lookup_callable: callable
    @param lookup_callable: The lookup to execute.

    @rtype: bool
    @return: Returns whether the was found and is displayed.
    """
    element = get_element_or_none(lookup_callable)
    return element is not None and element.is_displayed()


def wait_for_element_to_appear_and_disappear(lookup_callable):
    """Waits for an element to appear and then disappear.

    If the element doesn't appear it is assumed to be gone already.

    @type lookup_callable: callable
    @param lookup_callable: The lookup to find the element.
    """
    element_displayed = lambda: is_element_displayed(lookup_callable)
    try:
        wait_until(element_displayed, timeout_s=2)
    except OperationTimeoutError:
        # The element probably disappeared already.
        pass
    element_disappeared = lambda: not element_displayed()
    wait_until(element_disappeared)


# Mostly copied from https://github.com/wiredrive/wtframework/blob/master/wtframework/wtf/utils/wait_utils.py
def wait_until(condition, timeout_s=10, sleep_s=0.5, raise_exceptions=False):
    """Waits for the condition to become true.

    @type condition: callable
    @param condition: The condition to check periodically.

    @type timeout_s: int
    @param timeout_s: The timeout.

    @type sleep_s: float
    @param sleep_s: The time to sleep between the tries.

    @type raise_exceptions: bool
    @param raise_exceptions: Whether to raise any caught exceptions.
    """
    end_time = datetime.datetime.now() + datetime.timedelta(seconds=timeout_s)
    while datetime.datetime.now() < end_time:
        try:
            if condition():
                return
        except Exception, e:
            if raise_exceptions:
                raise e
            else:
                logger.info('Suppressing exception: ' + str(e))
                pass
        time.sleep(sleep_s)

    raise OperationTimeoutError("Operation timed out.")


class OperationTimeoutError(Exception):
    """Thrown when a wait function times out."""
    pass
