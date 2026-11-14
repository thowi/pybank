"""All values here are invented. Never derive a fixture from a real export."""

import datetime
import re

from beancount.core import amount, data, flags

from pybank.importer.beancount import IN_TRANSIT, UNCATEGORIZED, postfinance, qif, transfer_hints

CARD = "Liabilities:Bank:Card"
CASH = "Assets:Broker:Cash"
CHECKING = "Assets:Bank:Checking"
GROCERIES = "Expenses:Shopping:Groceries"

DAY = datetime.date(2019, 3, 4)

REPAYMENT = transfer_hints.Hint(CARD, re.compile("card repayment", re.IGNORECASE))


def _txn(account, narration, contra=UNCATEGORIZED, payee=None):
    postings = [
        data.Posting(account, amount.Amount(data.Decimal("50"), "CHF"), None, None, None, None),
        data.Posting(contra, None, None, None, None, None),
    ]
    return data.Transaction(
        {}, DAY, flags.FLAG_WARNING, payee, narration, data.EMPTY_SET, data.EMPTY_SET, postings
    )


def _book(hints, entries):
    groups = [("statement.csv", entries, CHECKING, postfinance.CheckingImporter({}))]
    return transfer_hints.book(hints, groups, [])[0][1]


def test_a_row_a_hint_names_books_to_the_clearing_account():
    (booked,) = _book([REPAYMENT], [_txn(CARD, "Card Repayment March")])

    assert [posting.account for posting in booked.postings] == [CARD, IN_TRANSIT]
    assert booked.flag == flags.FLAG_OKAY
    assert booked.meta[qif.META_CATEGORY_SOURCE] == transfer_hints.CATEGORY_SOURCE_HINT


def test_the_payee_counts_as_text():
    (booked,) = _book([REPAYMENT], [_txn(CARD, "March", payee="Card repayment")])

    assert booked.postings[1].account == IN_TRANSIT


def test_a_hint_covers_the_accounts_below_its_account():
    hint = transfer_hints.Hint(CASH, re.compile("deposit"))

    (booked,) = _book([hint], [_txn(f"{CASH}:USD", "deposit")])

    assert booked.postings[1].account == IN_TRANSIT


def test_a_hint_skips_an_account_that_only_shares_its_prefix():
    hint = transfer_hints.Hint(CASH, re.compile("deposit"))
    row = _txn(f"{CASH}Out", "deposit")

    assert _book([hint], [row]) == [row]


def test_a_row_on_another_account_stays_uncategorized():
    row = _txn(CHECKING, "Card repayment")

    assert _book([REPAYMENT], [row]) == [row]


def test_a_row_whose_text_does_not_match_stays_uncategorized():
    row = _txn(CARD, "Corner Shop")

    assert _book([REPAYMENT], [row]) == [row]


def test_a_categorized_row_keeps_its_category():
    row = _txn(CARD, "Card repayment", contra=GROCERIES)

    assert _book([REPAYMENT], [row]) == [row]
