import datetime
import locale
import logging
import re
import string
import time
from typing import List, Optional, Any, Callable

from selenium.common import exceptions
from selenium.webdriver.remote.webelement import WebElement


WHITESPACE_PATTERN = re.compile(r' +')

logger = logging.getLogger(__name__)


class FetchError(Exception):
    """An error while fetching the account data."""


def normalize_text(text: str) -> str:
    """Returns a normalized version of the input text.

    Removes double spaces and "Capitalizes All Words" if they are "ALL CAPS".

    :param text: The input text
    :return: A normalized version of the input text
    """
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
    :param: The parsed number.
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


def format_iban(iban: str) -> str:
    return format_string_into_blocks(iban, 4)


def format_cc_account_name(account_name: str) -> str:
    return format_string_into_blocks(account_name, 4)


def format_string_into_blocks(
        string: str, block_length: int, separator: str = ' ') -> str:
    parts = []
    index = 0
    while index < len(string):
        parts.append(string[index:index + block_length])
        index += block_length
    return separator.join(parts)


def find_element_by_title(parent: WebElement, title: str) -> WebElement:
    return parent.find_element_by_xpath(
            ".//*[normalize-space(@title) = '%s']" % title)


def find_element_by_tag_name_and_text(
        parent: WebElement, tag_name: str, text: str) -> WebElement:
    return parent.find_element_by_xpath(
            ".//%s[normalize-space(text()) = '%s']" % (tag_name, text))


def find_elements_by_tag_name_and_text(
        parent: WebElement, tag_name: str, text: str) -> List[WebElement]:
    return parent.find_elements_by_xpath(
            ".//%s[normalize-space(text()) = '%s']" % (tag_name, text))


def find_element_by_text(parent: WebElement, text: str) -> WebElement:
    return find_element_by_tag_name_and_text(parent, '*', text)


def find_elements_by_text(parent: WebElement, text: str) -> List[WebElement]:
    return find_elements_by_tag_name_and_text(parent, '*', text)


def get_first_displayed(elements: List[WebElement]) -> Optional[WebElement]:
    for e in elements:
        if e.is_displayed():
            return e


def find_element_by_tag_name_and_text(
        parent: WebElement, tag_name: str, text: str) -> WebElement:
    return parent.find_element_by_xpath(
            ".//%s[normalize-space(text()) = '%s']" % (tag_name, text))


def find_button_by_text(parent: WebElement, text: str) -> WebElement:
    return find_element_by_tag_name_and_text(parent, 'button', text)


def find_input_button_by_text(parent: WebElement, text: str) -> WebElement:
    return parent.find_element_by_xpath(
            ".//input[@type = 'button' and normalize-space(@value) = '%s']" %
            text)


def get_element_or_none(
        lookup_callable: Callable[[], WebElement]) -> Optional[WebElement]:
    """Returns the element for the lookup or None if not found.

    :param lookup_callable: The lookup to execute
    :return: The element for the lookup or None if not found
    """
    try:
        return lookup_callable()
    except exceptions.NoSuchElementException:
        return None


def is_element_present(lookup_callable: Callable[[], WebElement]) -> bool:
    """Returns whether the lookup was successful or a NoSuchElementException was
    caught.

    :param lookup_callable: The lookup to execute
    :return: Returns whether the lookup was successful
    """
    return get_element_or_none(lookup_callable) is not None


def is_element_displayed(lookup_callable: Callable[[], WebElement]) -> bool:
    """Returns whether the lookup was successful, the element was found, and it
    is displayed.

    :param lookup_callable: The lookup to execute
    :return: Returns whether the was found and is displayed
    """
    element = get_element_or_none(lookup_callable)
    return element is not None and element.is_displayed()


def wait_for_element_to_appear_and_disappear(
        lookup_callable: Callable[[], WebElement], timeout_s: int = 10) -> None:
    """Waits for an element to appear and then disappear.

    If the element doesn't appear it is assumed to be gone already.

    :param lookup_callable: The lookup to find the element.
    :param timeout_s: The timeout to wait for the element to disappear.
    """
    element_displayed = lambda: is_element_displayed(lookup_callable)
    try:
        wait_until(element_displayed, timeout_s=2)
    except OperationTimeoutError:
        # The element probably never showed up or disappeared already.
        pass
    element_disappeared = lambda: not element_displayed()
    try:
        wait_until(element_disappeared, timeout_s=timeout_s)
    except OperationTimeoutError:
        # The element probably never showed up or disappeared already.
        pass


# Mostly copied from https://github.com/wiredrive/wtframework/blob/master/wtframework/wtf/utils/wait_utils.py
def wait_until(
        condition: Callable[[], bool],
        timeout_s: int = 10,
        sleep_s: float = 0.5,
        raise_exceptions: bool = False) -> None:
    """Waits for the condition to become true.

    :param condition: The condition to check periodically.
    :param timeout_s: The timeout.
    :param sleep_s: The time to sleep between the tries.
    :param raise_exceptions: Whether to raise any caught exceptions.
    """
    end_time = datetime.datetime.now() + datetime.timedelta(seconds=timeout_s)
    while datetime.datetime.now() < end_time:
        try:
            if condition():
                return
        except Exception as e:
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
