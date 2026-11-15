"""All values here are invented. Never derive a fixture from a real export."""

import datetime

import pytest
from beancount.core import amount, data, flags, prices
from beangulp import extract

from pybank.importer.beancount import (
    IN_TRANSIT,
    UNCATEGORIZED,
    postfinance,
    qif,
    routing,
    transfer_matcher,
)

CHECKING = "Assets:Bank:Checking"
SAVINGS = "Assets:Other:Savings"
BROKER = "Assets:Broker:Cash"

DAY = datetime.date(2019, 3, 4)

# 1 EUR buys 1.10 CHF.
PRICES = prices.build_price_map(
    [data.Price({}, DAY, "EUR", amount.Amount(data.Decimal("1.10"), "CHF"))]
)
NO_PRICES = prices.build_price_map([])


def _leg(import_id, account, number, currency="CHF", contra=UNCATEGORIZED, days=0):
    postings = [
        data.Posting(
            account, amount.Amount(data.Decimal(number), currency), None, None, None, None
        ),
        data.Posting(contra, None, None, None, None, None),
    ]
    date = DAY + datetime.timedelta(days=days)
    meta = {"import-id": import_id}
    return data.Transaction(
        meta, date, flags.FLAG_WARNING, None, "Transfer", data.EMPTY_SET, data.EMPTY_SET, postings
    )


def _ids(pairs):
    return [(pair.sender.import_id, pair.receiver.import_id) for pair in pairs]


def test_opposite_amounts_on_two_accounts_pair_up():
    entries = [_leg("out", CHECKING, "-100"), _leg("in", SAVINGS, "100", days=3)]

    assert _ids(transfer_matcher.candidates(entries, NO_PRICES)) == [("out", "in")]


def test_one_account_does_not_pair_with_itself():
    entries = [_leg("out", CHECKING, "-100"), _leg("in", CHECKING, "100")]

    assert transfer_matcher.candidates(entries, NO_PRICES) == []


def test_legs_too_far_apart_do_not_pair():
    entries = [_leg("out", CHECKING, "-100"), _leg("in", SAVINGS, "100", days=8)]

    assert transfer_matcher.candidates(entries, NO_PRICES) == []


def test_a_leg_with_two_partners_pairs_with_neither():
    entries = [
        _leg("out", CHECKING, "-100"),
        _leg("in", SAVINGS, "100"),
        _leg("also-in", BROKER, "100"),
    ]

    assert transfer_matcher.candidates(entries, NO_PRICES) == []


def test_two_legs_that_already_cancel_out_need_no_answer():
    entries = [
        _leg("out", CHECKING, "-100", contra=IN_TRANSIT),
        _leg("in", SAVINGS, "100", contra=IN_TRANSIT),
    ]

    assert transfer_matcher.candidates(entries, NO_PRICES) == []


def test_a_categorized_row_is_no_leg():
    entries = [_leg("out", CHECKING, "-100"), _leg("in", SAVINGS, "100", contra="Income:Salary")]

    assert transfer_matcher.candidates(entries, NO_PRICES) == []


def test_currencies_pair_up_at_a_rate_near_the_market():
    entries = [_leg("out", CHECKING, "-100", "EUR"), _leg("in", SAVINGS, "107.50")]

    assert _ids(transfer_matcher.candidates(entries, PRICES)) == [("out", "in")]


def test_currencies_far_off_the_market_rate_do_not_pair():
    entries = [_leg("out", CHECKING, "-100", "EUR"), _leg("in", SAVINGS, "100")]

    assert transfer_matcher.candidates(entries, PRICES) == []


def test_currencies_without_a_market_rate_do_not_pair():
    entries = [_leg("out", CHECKING, "-100", "EUR"), _leg("in", SAVINGS, "107.50")]

    assert transfer_matcher.candidates(entries, NO_PRICES) == []


def _book(answers, entries):
    groups = [("statement.csv", entries, CHECKING, postfinance.CheckingImporter({}))]
    return transfer_matcher.book(answers, groups, [])[0][1]


def test_a_confirmed_pair_books_both_legs_to_the_clearing_account():
    entries = [_leg("out", CHECKING, "-100"), _leg("in", SAVINGS, "100")]

    booked = _book({frozenset(["out", "in"]): True}, entries)

    for txn in booked:
        assert txn.postings[1].account == IN_TRANSIT
        assert txn.flag == flags.FLAG_OKAY
        assert txn.meta[qif.META_CATEGORY_SOURCE] == transfer_matcher.CATEGORY_SOURCE_PAIR


def test_a_confirmed_pair_in_two_currencies_converts_on_the_receiving_leg():
    entries = [_leg("out", CHECKING, "-100", "EUR"), _leg("in", SAVINGS, "107.50")]

    sent, received = _book({frozenset(["out", "in"]): True}, entries)

    assert sent.postings[1].units is None
    contra = received.postings[1]
    assert contra.units == amount.Amount(data.Decimal("-100"), "EUR")
    assert contra.units.number * contra.price.number == data.Decimal("-107.50")
    assert contra.price.currency == "CHF"


def test_a_rejected_or_unanswered_pair_stays_as_it_was():
    entries = [_leg("out", CHECKING, "-100"), _leg("in", SAVINGS, "100")]

    assert _book({frozenset(["out", "in"]): False}, entries) == entries
    assert _book({}, entries) == entries


def test_a_confirmed_pair_books_even_when_a_third_leg_makes_it_ambiguous():
    entries = [
        _leg("out", CHECKING, "-100"),
        _leg("in", SAVINGS, "100"),
        _leg("also-in", BROKER, "100"),
    ]

    booked = _book({frozenset(["out", "in"]): True}, entries)

    assert [txn.postings[1].account for txn in booked] == [IN_TRANSIT, IN_TRANSIT, UNCATEGORIZED]


def test_a_confirmed_pair_books_the_row_rather_than_its_duplicate():
    duplicate = _leg("in", SAVINGS, "100")
    duplicate.meta[extract.DUPLICATE] = True
    entries = [_leg("out", CHECKING, "-100"), _leg("in", SAVINGS, "100"), duplicate]

    booked = _book({frozenset(["out", "in"]): True}, entries)

    assert [txn.postings[1].account for txn in booked] == [IN_TRANSIT, IN_TRANSIT, UNCATEGORIZED]


def test_a_duplicate_does_not_make_a_pair_ambiguous():
    duplicate = _leg("in", SAVINGS, "100")
    duplicate.meta[extract.DUPLICATE] = True
    entries = [_leg("out", CHECKING, "-100"), _leg("in", SAVINGS, "100"), duplicate]

    assert _ids(transfer_matcher.candidates(entries, NO_PRICES)) == [("out", "in")]


def test_answers_load_from_the_file(tmp_path):
    path = tmp_path / "transfer-pairs.toml"
    path.write_text('[[pair]]\nlegs = ["out", "in"]\nconfirmed = true\n', encoding="utf-8")

    assert transfer_matcher.load_answers(str(path)) == {frozenset(["out", "in"]): True}


def test_no_answers_file_means_no_answers(tmp_path):
    assert transfer_matcher.load_answers(str(tmp_path / "absent.toml")) == {}


def test_an_answer_without_two_legs_is_reported(tmp_path):
    path = tmp_path / "transfer-pairs.toml"
    path.write_text('[[pair]]\nlegs = ["out"]\nconfirmed = true\n', encoding="utf-8")

    with pytest.raises(routing.ConfigError, match="two legs"):
        transfer_matcher.load_answers(str(path))


def test_an_answer_with_a_nested_leg_is_reported(tmp_path):
    path = tmp_path / "transfer-pairs.toml"
    path.write_text('[[pair]]\nlegs = [["out"], "in"]\nconfirmed = true\n', encoding="utf-8")

    with pytest.raises(routing.ConfigError, match="two legs"):
        transfer_matcher.load_answers(str(path))


def _cleared(account, number, days=0, currency="CHF"):
    """A leg as the loaded ledger holds it, with the clearing amount set."""
    units = amount.Amount(data.Decimal(number), currency)
    postings = [
        data.Posting(account, units, None, None, None, None),
        data.Posting(IN_TRANSIT, -units, None, None, None, None),
    ]
    date = DAY + datetime.timedelta(days=days)
    return data.Transaction(
        {}, date, flags.FLAG_OKAY, None, "Transfer", data.EMPTY_SET, data.EMPTY_SET, postings
    )


def _unpaired(entries):
    return [(txn.date, posting.units.number) for txn, posting in transfer_matcher.unpaired(entries)]


def test_opposite_clearing_postings_within_the_window_cancel():
    entries = [_cleared(CHECKING, "-100"), _cleared(SAVINGS, "100", days=7)]

    assert _unpaired(entries) == []


def test_clearing_postings_too_far_apart_stay_unpaired():
    entries = [_cleared(CHECKING, "-100"), _cleared(SAVINGS, "100", days=8)]

    assert len(_unpaired(entries)) == 2


def test_an_arrival_cancels_only_the_oldest_open_departure():
    entries = [
        _cleared(CHECKING, "-100"),
        _cleared(CHECKING, "-100", days=4),
        _cleared(SAVINGS, "100", days=5),
    ]

    assert _unpaired(entries) == [(DAY + datetime.timedelta(days=4), data.Decimal("100"))]


def test_crossing_transfers_all_cancel():
    """Pairing each arrival with its nearest departure would strand two legs."""
    entries = [
        _cleared(CHECKING, "-100", days=-5),
        _cleared(SAVINGS, "100"),
        _cleared(CHECKING, "-100", days=3),
        _cleared(SAVINGS, "100", days=7),
    ]

    assert _unpaired(entries) == []


def test_a_zero_clearing_posting_is_no_leftover():
    assert _unpaired([_cleared(CHECKING, "0")]) == []


def test_clearing_postings_in_two_currencies_do_not_cancel():
    entries = [_cleared(CHECKING, "-100"), _cleared(SAVINGS, "100", currency="EUR")]

    assert len(_unpaired(entries)) == 2
