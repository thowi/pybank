"""Serialization to QIF (Quicken Interchange Format).

Not complete.

See http://www.respmech.com/mym2qifw/qif_new.htm for the spec.
"""

import model

DATE_FORMAT = '%x'
AMOUNT_FORMAT = '%.4f'
PRICE_FORMAT = '%.4f'
COMMISSIONS_FORMAT = '%.4f'

TYPES = {
    'bank': 'Bank',
    'cash': 'Cash',
    'credit card': 'CCard',
    'investment': 'Invst',
    'assets': 'Oth A',
    'liabilities': 'Oth L',
    'category list': 'Cat',
    'class list': 'Class',
    'memorized': 'Memorized',
}

ITEMS = {
    'date': 'D',
    'amount': 'T',
    'cleared status': 'C',
    'reference number': 'N',
    'payee': 'P',
    'memo': 'M',
    'address': 'A',
    'category': 'L',
    'split categoty': 'S',
    'split memo': 'E',
    'split dollar amount': '$',
}

INVESTMENT_ITEMS = {
    'date': 'D',
    'action': 'N',
    'security': 'Y',
    'price': 'I',
    'quantity': 'Q',
    'amount': 'T',
    'cleared status': 'C',
    'payee': 'P',
    'memo': 'M',
    'commission': 'O',
    'account': 'L',
    'amount transferred': '$',
}

INVESTMENT_ACTION_TYPES = {
    'buy': 'Buy',
    'sell': 'Sell',
    'transfer cash in': 'XIn',
    'transfer cash out': 'XOut',
    'shares in': 'ShrsIn',
    'shares out': 'ShrsOut',
    'dividend': 'Div',
    'interest income': 'IntInc',
    'misc expense': 'MiscExp',
    'misc income': 'MiscInc',
    'stock split': 'StkSplit',
}

ACCOUNT_HEADER = '!Account'
ACCOUNT_TYPE = '!Type:'

ACCOUNT_INFO = {
    'name': 'N',
    'type': 'T',
    'description': 'D',
    'limit': 'L',
    'balance date': '/',
    'balance amount': '$',  # SEEFinance uses 'B'
}

# CATEGORY_LIST = {}
# CLASS_LIST = {}
# MEMORIZED_TRANSACTION_LIST = {}

END_OF_ENTRY = '^'


class SerializationError(Exception):
    """An error while serializing the data."""


def serialize_account(account):
    """Serializes an account to the QIF format.

    @type account: model.Account
    @param account: The account to serialize

    @rtype: unicode
    @return: The QIF serialization of the account.
    """
    account_fields = []

    account_fields.append(ACCOUNT_HEADER)

    account_fields.append(ACCOUNT_INFO['name'] + account.name)

    if isinstance(account, model.CreditCard):
        acc_type = TYPES['credit card']
    elif isinstance(account, model.InvestmentsAccount):
        acc_type = TYPES['investment']
    else:
        acc_type = TYPES['bank']
    account_fields.append(ACCOUNT_INFO['type'] + acc_type)

    if account.balance is not None:
        account_fields.append(
                ACCOUNT_INFO['balance amount'] +
                (AMOUNT_FORMAT % account.balance))
        if account.balance_date:
            account_fields.append(
                    ACCOUNT_INFO['balance date'] +
                    account.balance_date.strftime(DATE_FORMAT))

    account_fields.append(END_OF_ENTRY)
    account_fields.append(ACCOUNT_TYPE + acc_type)

    txns = '\n'.join(serialize_transaction(t) for t in account.transactions)
    account_fields.append(txns)

    return '\n'.join(account_fields)


def serialize_transaction(transaction):
    """Serializes a transaction to the QIF format.

    @type transaction: model.Transaction
    @param transaction: The transaction to serialize

    @rtype: unicode
    @return: The QIF serialization of the transaction.

    @raise SerializationError: For unknown transaction types.
    """
    if isinstance(transaction, model.Payment):
        return serialize_payment(transaction)
    elif isinstance(transaction, model.InvestmentSecurityPurchase):
        return serialize_investment_transaction(
                transaction, INVESTMENT_ACTION_TYPES['buy'])
    elif isinstance(transaction, model.InvestmentSecuritySale):
        return serialize_investment_transaction(
                transaction, INVESTMENT_ACTION_TYPES['sell'])
    elif isinstance(transaction, model.InvestmentDividend):
        return serialize_investment_transaction(
                transaction, INVESTMENT_ACTION_TYPES['dividend'])
    elif isinstance(transaction, model.InvestmentInterestExpense):
        # Note: There is no "investment interest expense", so we save it as a
        # negative income.
        return serialize_investment_transaction(
                transaction, INVESTMENT_ACTION_TYPES['interest income'])
    elif isinstance(transaction, model.InvestmentInterestIncome):
        return serialize_investment_transaction(
                transaction, INVESTMENT_ACTION_TYPES['interest income'])
    elif isinstance(transaction, model.InvestmentMiscExpense):
        return serialize_investment_transaction(
                transaction, INVESTMENT_ACTION_TYPES['misc expense'])
    elif isinstance(transaction, model.InvestmentMiscIncome):
        return serialize_investment_transaction(
                transaction, INVESTMENT_ACTION_TYPES['misc income'])
    else:
        raise SerializationError('Unknown transaction type: ' + transaction)


def serialize_payment(payment):
    """Serializes a payment to the QIF format.

    @type payment: model.Payment
    @param payment: The payment to serialize

    @rtype: unicode
    @return: The QIF serialization of the payment.
    """
    fields = []

    fields.append(ITEMS['date'] + payment.date.strftime(DATE_FORMAT))
    fields.append(ITEMS['amount'] + (AMOUNT_FORMAT % payment.amount))

    if payment.payee:
        fields.append(ITEMS['payee'] + payment.payee)
    if payment.memo:
        fields.append(ITEMS['memo'] + format_memo_(payment.memo))
    if payment.category:
        fields.append(ITEMS['category'] + payment.category)
    fields.append(END_OF_ENTRY)

    return '\n'.join(fields)


def serialize_investment_transaction(transaction, action):
    """Serializes a investment transaction to the QIF format.

    @type transaction: model.InvestmentTransaction
    @param transaction: The investment transaction to serialize.

    @type action: str
    @param action: The "action" of the transaction to serialize.

    @rtype: unicode
    @return: The QIF serialization of the investment transaction.
    """
    fields = []

    fields.append(INVESTMENT_ITEMS['action'] + action)
    fields.append(
            INVESTMENT_ITEMS['date'] + transaction.date.strftime(DATE_FORMAT))
    fields.append(
            INVESTMENT_ITEMS['amount'] + (AMOUNT_FORMAT % transaction.amount))
    if transaction.memo:
        fields.append(ITEMS['memo'] + format_memo_(transaction.memo))
    if transaction.category:
        fields.append(ITEMS['category'] + transaction.category)
    if hasattr(transaction, 'symbol'):
        fields.append(INVESTMENT_ITEMS['security'] + transaction.symbol)
    if hasattr(transaction, 'quantity'):
        fields.append(
                INVESTMENT_ITEMS['quantity'] + str(transaction.quantity))
    if hasattr(transaction, 'price'):
        fields.append(
                INVESTMENT_ITEMS['price'] + (PRICE_FORMAT % transaction.price))
    if hasattr(transaction, 'commissions'):
        fields.append(
                INVESTMENT_ITEMS['commission'] +
                (COMMISSIONS_FORMAT % transaction.commissions))
    fields.append(END_OF_ENTRY)

    return '\n'.join(fields)


def format_memo_(memo):
    lines = []
    for line in memo.splitlines():
        line = line.strip()
        if not line:
            continue
        if not line.endswith('.') and not line.endswith(':'):
            line += '.'
        lines.append(line)
    return ' '.join(lines)
