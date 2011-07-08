#!/usr/bin/python

"""Serialization to QIF (Quicken Interchange Format).

Not complete.

See http://www.respmech.com/mym2qifw/qif_new.htm for the spec.
"""

import model

DATE_FORMAT = '%x'
AMOUNT_FORMAT = '%.2f'

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
    'price': '!',
    'quantity': 'Q',
    'amount': 'T',
    'cleared status': 'C',
    'payee': 'P',
    'memo': 'M',
    'commission': 'O',
    'category': 'L',
    'account': 'L',
    'amount transferred': '$',
}

ACCOUNT_INFO = {
    'name': 'N',
    'type': 'T',
    'description': 'D',
    'limit': 'L',
    'balance date': '/',
    'balance amount': '$',
}

# CATEGORY_LIST = {}
# CLASS_LIST = {}
# MEMORIZED_TRANSACTION_LIST = {}

END_OF_ENTRY = '^'


"""Serializes an account to the QIF format.

@type account: model.Account
@param account: The account to serialize

@rtype: unicode
@return: The QIF serialization of the account.
"""
def serialize_account(account):
    header = '!Type:' + TYPES['bank']
    txns = '\n'.join(serialize_transaction(t) for t in account.transactions)
    return '\n'.join((header, txns))


"""Serializes a transaction to the QIF format.

@type transaction: model.Transaction
@param transaction: The transaction to serialize

@rtype: unicode
@return: The QIF serialization of the transaction.
"""
def serialize_transaction(transaction):
    fields = []
    
    fields.append(ITEMS['date'] + transaction.date.strftime(DATE_FORMAT))
    fields.append(ITEMS['amount'] + (AMOUNT_FORMAT % transaction.amount))
    if transaction.payee:
        fields.append(ITEMS['payee'] + transaction.payee)
    if transaction.memo:
        fields.append(ITEMS['memo'] + transaction.memo)
    if transaction.category:
        fields.append(ITEMS['category'] + transaction.category)
    fields.append(END_OF_ENTRY)
    
    return '\n'.join(fields) 

