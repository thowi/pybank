#!/usr/bin/python

"""Bank account model."""


class Bank(object):
    """A bank."""


class Account(object):
    """An account.

    @type name: unicode
    @param name: Account name.

    @type currency: unicode or None
    @param currency: Currency symbol (usually 3-letter uppercase).

    @type balance: float or None
    @param balance: Balance.

    @type balance_date: datetime.datetime or None
    @param balance_date: Balance date.

    @type transactions: (Transaction,) or None
    @param transactions: The transactions.
    """
    def __init__(
            self, name, currency=None, balance=None, balance_date=None,
            transactions=None):
        self.name = name
        self.currency = currency
        self.balance = balance
        self.balance_date = balance_date
        if transactions:
            self.transactions = transactions
        else:
            self.transactions = ()

    def __str__(self):
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

    @type date: datetime.datetime
    @param date: The date of the transaction.

    @type amount: num
    @param amount: The amount of the transaction.

    @type memo: unicode or None
    @param memo: The memo of the transaction, if any.

    @type category: unicode or None
    @param category: The category of the transaction, if any.
    """
    def __init__(self, date, amount, memo=None, category=None):
        self.date = date
        self.amount = amount
        self.memo = memo
        self.category = category

    def __str__(self):
        return 'Date: %s. Amount: %.2f. Memo: %s. Category: %s.' % (
                self.date, self.amount, self.memo, self.category)


class Payment(Transaction):
    """A payment.

    @type date: datetime.datetime
    @param date: The date of the payment.

    @type amount: num
    @param amount: The amount of the payment.

    @type payer: unicode or None
    @param payer: The payer of the payment, if any.

    @type payee: unicode or None
    @param payee: The payee of the payment, if any.

    @type memo: unicode or None
    @param memo: The memo of the payment, if any.

    @type category: unicode or None
    @param category: The category of the payment, if any.
    """
    def __init__(
            self, date, amount, payer=None, payee=None, memo=None,
            category=None):
        super(Payment, self).__init__(date, amount, memo, category)
        self.payer = payer
        self.payee = payee

    def __str__(self):
        return (
                'Date: %s. Amount: %.2f. Payer: %s. Payee: %s. Memo: %s. '
                'Category: %s.' % (
                        self.date, self.amount, self.payer, self.payee,
                        self.memo, self.category))


class InvestmentSecurityTransaction(Transaction):
    """A security transaction.

    Base class for SecurityPurchase and SecuritySale.

    @type date: datetime.datetime
    @param date: The date of the transaction.

    @type symbol: str
    @param symbol: The symbol of the security of the transaction.

    @type quantity: int
    @param quantity: The quantity of the transaction.

    @type price: float
    @param price: The price of the security of the transaction.

    @type commissions: float
    @param commissions: The commissions of the transaction.

    @type amount: float
    @param amount: The total amount of the transaction incl. commissions.

    @type memo: unicode or None
    @param memo: The memo of the transaction, if any.

    @type category: unicode or None
    @param category: The category of the transaction, if any.
    """
    def __init__(
            self, date, symbol, quantity, price, commissions, amount, memo=None,
            category=None):
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
            self, date, symbol, quantity, price, commissions, amount, memo=None,
            category=None):
        super(InvestmentSecurityPurchase, self).__init__(
                date, symbol, quantity, price, commissions, amount, memo,
                category)


class InvestmentSecuritySale(InvestmentSecurityTransaction):
    """A security sale.

    See SecurityTransaction for parameters.
    """
    def __init__(
            self, date, symbol, quantity, price, commissions, amount, memo=None,
            category=None):
        super(InvestmentSecuritySale, self).__init__(
                date, symbol, quantity, price, commissions, amount, memo,
                category)


class InvestmentDividend(Transaction):
    """A dividend.

    @type date: datetime.datetime
    @param date: The date of the dividend.

    @type symbol: str
    @param symbol: The symbol of the security of the dividend.

    @type amount: float
    @param amount: The total amount of the dividend.

    @type memo: unicode or None
    @param memo: The memo of the dividend, if any.

    @type category: unicode or None
    @param category: The category of the dividend, if any.
    """
    def __init__(
            self, date, symbol, amount, memo=None, category=None):
        super(InvestmentDividend, self).__init__(
                date, amount, memo, category)
        self.symbol = symbol


class InvestmentInterestExpense(Transaction):
    """An interest expense.

    @type date: datetime.datetime
    @param date: The date of the dividend.

    @type amount: float
    @param amount: The total amount of the dividend.

    @type memo: unicode or None
    @param memo: The memo of the dividend, if any.

    @type category: unicode or None
    @param category: The category of the dividend, if any.
    """
    def __init__(
            self, date, amount, memo=None, category=None):
        super(InvestmentInterestExpense, self).__init__(
                date, amount, memo, category)


class InvestmentInterestIncome(Transaction):
    """An interest income.

    @type date: datetime.datetime
    @param date: The date of the dividend.

    @type amount: float
    @param amount: The total amount of the dividend.

    @type memo: unicode or None
    @param memo: The memo of the dividend, if any.

    @type category: unicode or None
    @param category: The category of the dividend, if any.
    """
    def __init__(
            self, date, amount, memo=None, category=None):
        super(InvestmentInterestIncome, self).__init__(
                date, amount, memo, category)


class InvestmentMiscExpense(Transaction):
    """A misc expense.

    @type date: datetime.datetime
    @param date: The date of the dividend.

    @type amount: float
    @param amount: The total amount of the expense.

    @type symbol: str or None
    @param symbol: The symbol of the security of the expense.

    @type memo: unicode or None
    @param memo: The memo of the expense, if any.

    @type category: unicode or None
    @param category: The category of the expense, if any.
    """
    def __init__(
            self, date, amount, symbol=None, memo=None, category=None):
        super(InvestmentMiscExpense, self).__init__(
                date, amount, memo, category)
        self.symbol = symbol


class InvestmentMiscIncome(Transaction):
    """A misc income.

    @type date: datetime.datetime
    @param date: The date of the dividend.

    @type amount: float
    @param amount: The total amount of the dividend.

    @type symbol: str or None
    @param symbol: The symbol of the security of the income.

    @type memo: unicode or None
    @param memo: The memo of the dividend, if any.

    @type category: unicode or None
    @param category: The category of the dividend, if any.
    """
    def __init__(
            self, date, amount, symbol=None, memo=None, category=None):
        super(InvestmentMiscIncome, self).__init__(
                date, amount, memo, category)
        self.symbol = symbol
