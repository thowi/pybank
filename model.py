#!/usr/bin/python

"""Bank account model."""


class Bank(object):
    pass


class Account(object):
    """Creates a new account.
    
    @type name: unicode
    @param name: Account name.
    
    @type transactions: (Transaction,)
    @param transactions: The transactions.
    """
    def __init__(self, name, transactions):
        self.name = name
        self.transactions = transactions
    
    def __repr__(self):
        return '%s. %i transactins.' % (self.name, len(self.transactions))


class Transaction(object):
    """Creates a new transaction.
    
    @type date: datetime.datetime
    @param date: The date of the transaction.
    
    @type amount: num
    @param amount: The amount of the transaction.
    
    @type payee: unicode or None
    @param payee: The payee of the transaction, if any.
    
    @type memo: unicode or None
    @param memo: The memo of the transaction, if any.
    
    @type category: unicode or None
    @param category: The category of the transaction, if any.
    """
    def __init__(self, date, amount, payee=None, memo=None, category=None):
        self.date = date
        self.amount = amount
        self.payee = payee
        self.memo = memo
        self.category = category
    
    def __repr__(self):
        return 'Date: %s. Amount: %.2f. Payee: %s. Memo: %s. Category: %s.' % (
                self.date, self.amount, self.payee, self.memo, self.category)

