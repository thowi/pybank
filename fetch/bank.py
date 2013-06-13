#!/usr/bin/python

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

