import datetime

from pybank import model
from pybank import qif


def test_serialize_account():
    transactions = (
        model.Payment(
            date=datetime.datetime.now(),
            amount=1000,
            memo='Memo1',
            category='Cat1'),
        model.Payment(
            date=datetime.datetime.now(),
            amount=-300,
            memo='Memo2',
            category='Cat2'),
        model.Payment(
            date=datetime.datetime.now(),
            amount=-200,
            memo='Memo3',
            category='Cat3'),
        model.Payment(
            date=datetime.datetime.now(),
            amount=-100,
            memo='Memo4',
            category='Cat4'),
    )

    account = model.Account(name='Test', transactions=transactions)
    assert 'Memo1' in qif.serialize_account(account)
