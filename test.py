#!/usr/bin/env python

import datetime

import model
import qif


transactions = (
    model.Transaction(datetime.datetime.now(), 1000, 'Payee1', 'Memo1', 'Cat1'),
    model.Transaction(datetime.datetime.now(), -300, 'Payee2', 'Memo2', 'Cat2'),
    model.Transaction(datetime.datetime.now(), -200, 'Payee3', 'Memo3', 'Cat3'),
    model.Transaction(datetime.datetime.now(), -100, 'Payee4', 'Memo4', 'Cat4'),
)

account = model.Account(name='Test', transactions=transactions)

print(qif.serialize_account(account))
