#!/usr/bin/python

class Bank(object):
    """Base class for a fetcher that logs into a bank account website.

    Will prompt the user if either user name or password are not defined.

    @type username: unicode
    @param username: The user name.

    @type password: unicode
    @param password: The password.
    """
    def login(self, username=None, password=None):
        raise NotImplementedError()

    """Returns the names of all accounts.

    @rtype: [model.Account]
    @return: The available accounts on this bank.
    """
    def get_accounts(self):
        raise NotImplementedError()

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
    def get_transactions(self, name, start, end):
        raise NotImplementedError()

