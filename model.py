#!/usr/bin/python

"""Bank account model."""


class Bank(object):
    """A bank."""


class Account(object):
    """An account.
    
    @type name: unicode
    @param name: Account name.
    
    @type balance: float or None
    @param balance: Balance.
    
    @type balance_date: datetime.datetime or None
    @param balance_date: Balance date.
    
    @type transactions: (Transaction,) or None
    @param transactions: The transactions.
    """
    def __init__(
            self, name, balance=None, balance_date=None, transactions=None):
        self.name = name
        self.balance = balance
        self.balance_date = balance_date
        if transactions:
            self.transactions = transactions
        else:
            self.transactions = ()
    
    def __repr__(self):
        repr = [self.name]
        if self.transactions:
            repr.append('%i transactions' % len(self.transactions))
        if self.balance:
            repr.append('Balance: %.2f' % self.balance)
        return '. '.join(repr) + '.'


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

