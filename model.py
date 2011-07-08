#!/usr/bin/python

"""Bank account model."""


class Bank(object):
    """A bank."""


class Account(object):
    """An account.
    
    @type name: unicode
    @param name: Account name.
    
    @type transactions: (Transaction,) or None
    @param transactions: The transactions.
    """
    def __init__(self, name, transactions=None):
        self.name = name
        if transactions:
            self.transactions = transactions
        else:
            self.transactions = ()
    
    def __repr__(self):
        return '%s. %i transactions.' % (self.name, len(self.transactions))


class CheckingAccount(Account):
    """A checking account."""


class SavingsAccount(Account):
    """A savings account."""


class InvestmentsAccount(Account):
    """An investments account."""


class CreditCard(Account):
    """A credit card."""


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

