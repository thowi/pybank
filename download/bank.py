import logging
import os
import os.path
import pickle
import time
from typing import Optional, List

import selenium.webdriver

import model

logger = logging.getLogger(__name__)


class Bank(object):
    """Base class for a fetcher that logs into a bank account website."""

    def __init__(self, debug: bool = False) -> None:
        """Create a new Bank instance.

        @param debug: Whether to run in debug mode.
        """
        self._debug = debug

    def login(
            self, 
            username: Optional[str] = None,
            password: Optional[str] = None, 
            statements: Optional[List[str]] = None) -> None:
        """Will prompt the user if either user name or password are not defined.

        @param username: The user name.
        @param password: The password.
        @param statements: A list of statement files to read for import.
        """
        raise NotImplementedError()

    def logout(self) -> None:
        """Will log out of the bank account."""
        raise NotImplementedError()

    def get_accounts(self) -> List[model.Account]:
        """Returns the names of all accounts.

        @return: The available accounts on this bank.
        """
        raise NotImplementedError()

    def get_transactions(
            self,
            account: model.Account,
            start: datetime.datetime, 
            end: datetime.datetime) -> List[model.Transaction]:
        """Returns all transactions within the given date range.

        @param account: The account.
        @param start: Start date, inclusive.
        @param end: End date, exclusive.
        @return: The matching transactions.
        """
        raise NotImplementedError()

    def _get_cookies_filename(self, username):
        return self.__class__.__name__ + '_' + username + '.cookies'

    def save_cookies(self, browser: selenium.webdriver, username: str) -> None:
        """Saves the seesion cookies into a file.

        @param browser: The browser instance.
        @param str: The username that owns the session.
        """
        cookies_filename = self._get_cookies_filename(username)
        logger.info('Saving cookies to %s...' % cookies_filename)
        pickle.dump(browser.get_cookies(), open(cookies_filename, 'wb'))

    def ask_and_restore_cookies(
            self,
            browser: selenium.webdriver,
            username: str,
            timeout_secs: Optional[int] = None) -> bool:
        """Checks if cookies were found for a session and asks to restore them.

        @param browser: The browser instance.
        @param str: The username that owned the session.
        @param str: The timeout in seconds after which cookies are invalid.
        @return: True if any cookies were restored. False otherwise.
        """
        cookies_filename = self._get_cookies_filename(username)
        if not os.path.exists(cookies_filename):
            logger.info('No cookies found.')
            return False
        if timeout_secs is not None:
            mtime = os.path.getmtime(cookies_filename)
            if mtime + timeout_secs < time.time():
                logger.info(
                        'Cookies from %s expired. Deleting.' % cookies_filename)
                os.remove(cookies_filename)
                return False
        logger.info('Reading cookies from %s...' % cookies_filename)
        try:
            cookies = pickle.load(open(cookies_filename, 'rb'))
        except IOError:
            logger.info('Invalid cookies file. Deleting.')
            os.remove(cookies_filename)
            return False
        restore = input(
                'A previous session was found for this user. Restore? [Yn] ')
        if restore.lower() in ('y', ''):
            logger.info('Restoring cookies...')
            for cookie in cookies:
                if 'expiry' in cookie:
                    # Float values throw an error in ChromeDriver.
                    cookie['expiry'] = int(cookie['expiry'])
                browser.add_cookie(cookie)
            return True
        return False

    def delete_cookies(self, username: str) -> None:
        """Deletes any cookies for a session.

        @param str: The username that owned the session.
        """
        cookies_filename = self._get_cookies_filename(username)
        logger.info('Deleting cookies in %s...' % cookies_filename)
        try:
            os.remove(cookies_filename)
        except IOError:
            logger.info('No cookies found.')
