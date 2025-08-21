#!/usr/bin/python

"""Bank account model."""


import datetime


class Account(object):
    """An account.

    :param name: Account name.
    :param currency: Currency symbol (usually 3-letter uppercase).
    :param balance: Balance.
    :param balance_date: Balance date.
    :param transactions: The transactions.
    """
    def __init__(
            self,
            name: str,
            currency: str | None = None,
            balance: float | None = None,
            balance_date: datetime.datetime | None = None,
            transactions: tuple['Transaction', ...] | None = None):
        self.name = name
        self.currency = currency
        self.balance = balance
        self.balance_date = balance_date
        if transactions:
            self.transactions = transactions
        else:
            self.transactions = ()

    def __str__(self) -> str:
        repr = [self.name]
        if self.transactions:
            repr.append('%i transactions' % len(self.transactions))
        if self.balance is not None:
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
    """A transaction.

    :param date: The date of the transaction.
    :param amount: The amount of the transaction.
    :param memo: The memo of the transaction, if any.
    :param category: The category of the transaction, if any.
    """
    def __init__(
            self,
            date: datetime.datetime,
            amount: int | float,
            memo: str | None = None,
            category: str | None = None):
        self.date = date
        self.amount = amount
        self.memo = memo
        self.category = category

    def __str__(self) -> str:
        return 'Date: %s. Amount: %.2f. Memo: %s. Category: %s.' % (
                self.date, self.amount, self.memo, self.category)


class Payment(Transaction):
    """A payment.

    :param date: The date of the payment.
    :param amount: The amount of the payment.
    :param payer: The payer of the payment, if any.
    :param payee: The payee of the payment, if any.
    :param memo: The memo of the payment, if any.
    :param category: The category of the payment, if any.
    """
    def __init__(
            self,
            date: datetime.datetime,
            amount: int | float,
            payer: str | None = None,
            payee: str | None = None,
            memo: str | None = None,
            category: str | None = None):
        super(Payment, self).__init__(date, amount, memo, category)
        self.payer = payer
        self.payee = payee

    def __str__(self) -> str:
        return (
                'Date: %s. Amount: %.2f. Payer: %s. Payee: %s. Memo: %s. '
                'Category: %s.' % (
                        self.date, self.amount, self.payer, self.payee,
                        self.memo, self.category))


class InvestmentSecurityTransaction(Transaction):
    """A security transaction.

    Base class for SecurityPurchase and SecuritySale.

    :param date: The date of the transaction.
    :param symbol: The symbol of the security of the transaction.
    :param quantity: The quantity of the transaction.
    :param price: The price of the security of the transaction.
    :param commissions: The commissions of the transaction.
    :param amount: The total amount of the transaction incl. commissions.
    :param memo: The memo of the transaction, if any.
    :param category: The category of the transaction, if any.
    """
    def __init__(
            self,
            date: datetime.datetime,
            symbol: str,
            quantity: int,
            price: float,
            commissions: float,
            amount: float,
            memo: str | None = None,
            category: str | None = None):
        super(InvestmentSecurityTransaction, self).__init__(
                date, amount, memo, category)
        self.symbol = symbol
        self.quantity = quantity
        self.price = price
        self.commissions = commissions


class InvestmentSecurityPurchase(InvestmentSecurityTransaction):
    """A security purchase.

    See SecurityTransaction for parameters.
    """
    def __init__(
            self,
            date: datetime.datetime,
            symbol: str,
            quantity: int,
            price: float,
            commissions: float,
            amount: float,
            memo: str | None = None,
            category: str | None = None):
        super(InvestmentSecurityPurchase, self).__init__(
                date, symbol, quantity, price, commissions, amount, memo,
                category)


class InvestmentSecuritySale(InvestmentSecurityTransaction):
    """A security sale.

    See SecurityTransaction for parameters.
    """
    def __init__(
            self,
            date: datetime.datetime,
            symbol: str,
            quantity: int,
            price: float,
            commissions: float,
            amount: float,
            memo: str | None = None,
            category: str | None = None):
        super(InvestmentSecuritySale, self).__init__(
                date, symbol, quantity, price, commissions, amount, memo,
                category)


class InvestmentDividend(Transaction):
    """A dividend.

    :param date: The date of the dividend.
    :param symbol: The symbol of the security of the dividend.
    :param amount: The total amount of the dividend.
    :param memo: The memo of the dividend, if any.
    :param category: The category of the dividend, if any.
    """
    def __init__(
            self,
            date: datetime.datetime,
            symbol: str,
            amount: float,
            memo: str | None = None,
            category: str | None = None):
        super(InvestmentDividend, self).__init__(
                date, amount, memo, category)
        self.symbol = symbol


class InvestmentInterestExpense(Transaction):
    """An interest expense.

    :param date: The date of the dividend.
    :param amount: The total amount of the dividend.
    :param memo: The memo of the dividend, if any.
    :param category: The category of the dividend, if any.
    """
    def __init__(
            self,
            date: datetime.datetime,
            amount: float,
            memo: str | None = None,
            category: str | None = None):
        super(InvestmentInterestExpense, self).__init__(
                date, amount, memo, category)


class InvestmentInterestIncome(Transaction):
    """An interest income.

    :param date: The date of the dividend.
    :param amount: The total amount of the dividend.
    :param memo: The memo of the dividend, if any.
    :param category: The category of the dividend, if any.
    """
    def __init__(
            self,
            date: datetime.datetime,
            amount: float,
            memo: str | None = None,
            category: str | None = None):
        super(InvestmentInterestIncome, self).__init__(
                date, amount, memo, category)


class InvestmentMiscExpense(Transaction):
    """A misc expense.

    :param date: The date of the dividend.
    :param amount: The total amount of the expense.
    :param symbol: The symbol of the security of the expense.
    :param memo: The memo of the expense, if any.
    :param category: The category of the expense, if any.
    """
    def __init__(
            self,
            date: datetime.datetime,
            amount: float,
            symbol: str | None = None,
            memo: str | None = None,
            category: str | None = None):
        super(InvestmentMiscExpense, self).__init__(
                date, amount, memo, category)
        self.symbol = symbol


class InvestmentMiscIncome(Transaction):
    """A misc income.

    :param date: The date of the dividend.
    :param amount: The total amount of the dividend.
    :param symbol: The symbol of the security of the income.
    :param memo: The memo of the dividend, if any.
    :param category: The category of the dividend, if any.
    """
    def __init__(
            self,
            date: datetime.datetime,
            amount: float,
            symbol: str | None = None,
            memo: str | None = None,
            category: str | None = None):
        super(InvestmentMiscIncome, self).__init__(
                date, amount, memo, category)
        self.symbol = symbol
