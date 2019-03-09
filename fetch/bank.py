import logging
import os
import os.path
import pickle
import time

logger = logging.getLogger(__name__)


class Bank(object):
    """Base class for a fetcher that logs into a bank account website."""

    def __init__(self, debug=False):
        """Create a new Bank instance.

        @type debug: bool
        @param debug: Whether to run in debug mode.
        """
        self._debug = debug

    def login(self, username=None, password=None):
        """Will prompt the user if either user name or password are not defined.

        @type username: unicode
        @param username: The user name.

        @type password: unicode
        @param password: The password.
        """
        raise NotImplementedError()

    def logout(self):
        """Will log out of the bank account."""
        raise NotImplementedError()

    def get_accounts(self):
        """Returns the names of all accounts.

        @rtype: [model.Account]
        @return: The available accounts on this bank.
        """
        raise NotImplementedError()

    def get_transactions(self, name, start, end):
        """Returns all transactions within the given date range.

        @type name: unicode
        @param name: The account name.

        @type start: datetime.datetime
        @param start: Start date, inclusive.

        @type end: datetime.datetime
        @param end: End date, exclusive.

        @rtype: [model.Transaction]
        @return: The matching transactions.
        """
        raise NotImplementedError()

    def _get_cookies_filename(self, username):
        return self.__class__.__name__ + '_' + username + '.cookies'

    def save_cookies(self, browser, username):
        """Saves the seesion cookies into a file.

        @type browser: selenium.webdriver
        @param browser: The browser instance.

        @type username: str
        @param str: The username that owns the session.
        """
        cookies_filename = self._get_cookies_filename(username)
        logger.info('Saving cookies to %s...' % cookies_filename)
        pickle.dump(browser.get_cookies(), open(cookies_filename, 'wb'))

    def ask_and_restore_cookies(self, browser, username, timeout_secs=None):
        """Checks if cookies were found for a session and asks to restore them.

        @type browser: selenium.webdriver
        @param browser: The browser instance.

        @type username: str
        @param str: The username that owned the session.

        @type timeout_secs: int or None
        @param str: The timeout in seconds after which cookies are invalid.

        @rtype bool
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
                browser.add_cookie(cookie)
            return True
        return False

    def delete_cookies(self, username):
        """Deletes any cookies for a session.

        @type username: str
        @param str: The username that owned the session.
        """
        cookies_filename = self._get_cookies_filename(username)
        logger.info('Deleting cookies in %s...' % cookies_filename)
        try:
            os.remove(cookies_filename)
        except IOError:
            logger.info('No cookies found.')
