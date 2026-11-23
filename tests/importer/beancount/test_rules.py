"""All values here are invented. Never derive a fixture from a real export."""

import datetime
import logging
import re

from beancount.core import amount, data, flags
from beangulp import extract

from pybank.importer.beancount import IN_TRANSIT, UNCATEGORIZED, postfinance, qif, rules

CHECKING = "Assets:Bank:Checking"
DINING = "Expenses:Leisure:Dining"
GROCERIES = "Expenses:Living:Groceries"
MEALS = "Expenses:Living:Meals"

DAY = datetime.date(2024, 3, 4)


def _rule(book, text, **filters):
    return rules.Rule(book=book, text=re.compile(text, re.IGNORECASE), **filters)


def _txn(narration, contra=UNCATEGORIZED, label=None, day=DAY, account=CHECKING, payee=None):
    units = amount.Amount(data.Decimal("-20"), "CHF")
    counter_units = None if contra == UNCATEGORIZED and label is None else -units
    counter_meta = {qif.META_QIF_CATEGORY: label} if label else None
    postings = [
        data.Posting(account, units, None, None, None, None),
        data.Posting(contra, counter_units, None, None, None, counter_meta),
    ]
    return data.Transaction(
        {}, day, flags.FLAG_WARNING, payee, narration, data.EMPTY_SET, data.EMPTY_SET, postings
    )


def _book(rule_list, entries):
    groups = [("statement.csv", entries, CHECKING, postfinance.CheckingImporter({}))]
    return rules.book(rule_list, groups, [])[0][1]


def test_an_uncategorized_row_books_to_the_rule_account():
    (booked,) = _book([_rule(GROCERIES, "corner shop")], [_txn("Corner Shop 12")])

    assert booked.postings[1].account == GROCERIES
    assert booked.flag == flags.FLAG_OKAY
    assert booked.meta[qif.META_CATEGORY_SOURCE] == rules.CATEGORY_SOURCE_RULE


def test_the_payee_counts_as_text():
    (booked,) = _book([_rule(GROCERIES, "corner shop")], [_txn("12", payee="Corner Shop")])

    assert booked.postings[1].account == GROCERIES


def test_a_label_wins_over_a_rule_that_does_not_name_it():
    row = _txn("Meal Box", contra=DINING, label="Dining")

    (kept,) = _book([_rule(GROCERIES, "meal box")], [row])

    assert kept is row


def test_a_rule_overrides_a_label_it_names_and_keeps_the_label():
    row = _txn("Meal Box", contra=DINING, label="Dining")

    (booked,) = _book([_rule(GROCERIES, "meal box", labels=frozenset({"Dining"}))], [row])

    assert booked.postings[1].account == GROCERIES
    assert booked.postings[1].units == row.postings[1].units
    assert booked.postings[1].meta[qif.META_QIF_CATEGORY] == "Dining"


def test_a_mixed_label_on_uncategorized_is_open_to_every_rule():
    row = _txn("Phone Co", label="Bills")

    (booked,) = _book([_rule("Expenses:Telecom:Mobile", "phone co")], [row])

    assert booked.postings[1].account == "Expenses:Telecom:Mobile"


def test_a_transfer_is_closed_to_rules():
    row = _txn("Burger Stop", contra=IN_TRANSIT)

    (kept,) = _book([_rule(MEALS, "burger")], [row])

    assert kept is row


def test_a_duplicate_is_left_alone(caplog):
    row = _txn("Corner Shop")
    row.meta[extract.DUPLICATE] = True

    with caplog.at_level(logging.WARNING):
        (kept,) = _book([_rule(GROCERIES, "corner shop")], [row])

    assert kept is row
    assert "matched no row" in caplog.text


def test_a_split_row_is_left_alone():
    row = _txn("Corner Shop")
    split = row._replace(postings=[*row.postings, row.postings[1]._replace(account=MEALS)])

    (kept,) = _book([_rule(GROCERIES, "corner shop")], [split])

    assert kept is split


def test_the_first_matching_rule_wins():
    narrow = _rule("Expenses:Mobility:Car:Fuel", "corner shop fuel")
    broad = _rule(GROCERIES, "corner shop")

    fuel, food = _book([narrow, broad], [_txn("Corner Shop Fuel"), _txn("Corner Shop")])

    assert fuel.postings[1].account == "Expenses:Mobility:Car:Fuel"
    assert food.postings[1].account == GROCERIES


def test_the_date_bounds_are_inclusive():
    rule = _rule(GROCERIES, "bakery", start=DAY, end=DAY)
    before, on, after = (_txn("Bakery", day=DAY + datetime.timedelta(days=d)) for d in (-1, 0, 1))

    booked = _book([rule], [before, on, after])

    assert [txn.postings[1].account for txn in booked] == [UNCATEGORIZED, GROCERIES, UNCATEGORIZED]


def test_the_account_filter_covers_the_accounts_below_it():
    rule = _rule(GROCERIES, "shop", account="Assets:Bank")

    below, other = _book([rule], [_txn("Shop"), _txn("Shop", account="Assets:Bankrupt")])

    assert below.postings[1].account == GROCERIES
    assert other.postings[1].account == UNCATEGORIZED


def test_a_rule_can_send_a_labeled_row_back_to_review():
    row = _txn("Cafe Works", contra=DINING, label="Dining")
    rule = _rule(UNCATEGORIZED, "cafe works", labels=frozenset({"Dining"}))

    (booked,) = _book([rule], [row])

    assert booked.postings[1].account == UNCATEGORIZED
    assert booked.flag == flags.FLAG_WARNING


def test_a_rule_that_matches_no_row_is_reported(caplog):
    with caplog.at_level(logging.WARNING):
        _book([_rule(GROCERIES, "nowhere")], [_txn("Corner Shop")])

    assert "Rule #1 (nowhere) matched no row" in caplog.text
