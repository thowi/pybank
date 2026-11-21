"""All values here are invented. Never derive a fixture from a real export."""

import datetime

import pytest
from beancount.core import amount, data, flags, prices
from beangulp import extract

from pybank.importer.beancount import (
    BANK_FEES,
    IN_TRANSIT,
    META_CONVERSION_ID,
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
PRICE = data.Price({}, DAY, "EUR", amount.Amount(data.Decimal("1.10"), "CHF"))
PRICES = prices.build_price_map([PRICE])
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


def test_twins_pair_oldest_with_oldest():
    # Two top-ups of one amount, each charged on the card a day later.
    entries = [
        _leg("out-2", CHECKING, "-100", contra=IN_TRANSIT, days=2),
        _leg("out-1", CHECKING, "-100", contra=IN_TRANSIT, days=1),
        _leg("in-1", SAVINGS, "100", days=0),
        _leg("in-2", SAVINGS, "100", days=1),
    ]

    pairs = transfer_matcher.candidates(entries, NO_PRICES)

    assert _ids(pairs) == [("out-1", "in-1"), ("out-2", "in-2")]


def test_twins_between_unknown_rows_do_not_pair():
    entries = [
        _leg("out-1", CHECKING, "-100"),
        _leg("out-2", CHECKING, "-100", days=1),
        _leg("in-1", SAVINGS, "100"),
        _leg("in-2", SAVINGS, "100", days=1),
    ]

    assert transfer_matcher.candidates(entries, NO_PRICES) == []


def test_legs_on_two_accounts_are_no_twins():
    entries = [
        _leg("out-1", CHECKING, "-100"),
        _leg("out-2", CHECKING, "-100"),
        _leg("in", SAVINGS, "100"),
        _leg("also-in", BROKER, "100"),
    ]

    assert transfer_matcher.candidates(entries, NO_PRICES) == []


def test_a_transfer_with_two_partners_offers_both_nearest_first():
    out = _leg("out", CHECKING, "-100", contra=IN_TRANSIT)
    cleared = out.postings[1]._replace(units=amount.Amount(data.Decimal("100"), "CHF"))
    entries = [
        out._replace(postings=[out.postings[0], cleared]),
        _leg("later-in", SAVINGS, "100", days=3),
        _leg("in", BROKER, "100", days=1),
    ]

    (choice,) = transfer_matcher.choices(entries, NO_PRICES)

    assert choice.leg.import_id == "out"
    assert [leg.import_id for leg in choice.options] == ["in", "later-in"]


def test_an_uncategorized_row_with_two_partners_offers_nothing():
    entries = [
        _leg("out", CHECKING, "-100"),
        _leg("in", SAVINGS, "100"),
        _leg("also-in", BROKER, "100"),
    ]

    assert transfer_matcher.choices(entries, NO_PRICES) == []


def test_two_legs_that_already_cancel_out_need_no_answer():
    entries = [
        _leg("out", CHECKING, "-100", contra=IN_TRANSIT),
        _leg("in", SAVINGS, "100", contra=IN_TRANSIT),
    ]

    assert transfer_matcher.candidates(entries, NO_PRICES) == []


def test_a_currency_pair_booked_through_a_rate_needs_no_answer():
    received = _leg("in", SAVINGS, "107.50", contra=IN_TRANSIT)
    sent = amount.Amount(data.Decimal("-100"), "EUR")
    rate = amount.Amount(data.Decimal("1.075"), "CHF")
    contra = received.postings[1]._replace(units=sent, price=rate)
    entries = [
        _leg("out", CHECKING, "-100", "EUR", IN_TRANSIT),
        received._replace(postings=[received.postings[0], contra]),
    ]

    assert transfer_matcher.candidates(entries, PRICES) == []


def test_a_categorized_row_is_no_leg():
    entries = [_leg("out", CHECKING, "-100"), _leg("in", SAVINGS, "100", contra="Income:Salary")]

    assert transfer_matcher.candidates(entries, NO_PRICES) == []


def test_currencies_pair_up_at_a_rate_near_the_market():
    entries = [
        _leg("out", CHECKING, "-100", "EUR", contra=IN_TRANSIT),
        _leg("in", SAVINGS, "107.50"),
    ]

    assert _ids(transfer_matcher.candidates(entries, PRICES)) == [("out", "in")]


def test_a_conversion_pairs_its_legs_and_leaves_the_transfer_after_it_alone():
    # Money changed into EUR on one account, then sent on to another.
    changed = _leg("changed", SAVINGS, "-110", contra=IN_TRANSIT)
    bought = _leg("bought", BROKER, "100", "EUR", contra=IN_TRANSIT)
    for txn in (changed, bought):
        txn.meta[META_CONVERSION_ID] = "c1"
    entries = [
        changed,
        bought,
        _leg("sent", BROKER, "-100", "EUR"),
        _leg("arrived", CHECKING, "100", "EUR", contra=IN_TRANSIT, days=1),
    ]

    pairs = transfer_matcher.candidates(entries, PRICES)

    assert sorted(_ids(pairs)) == [("changed", "bought"), ("sent", "arrived")]


def test_an_exact_partner_wins_over_one_a_rate_away():
    entries = [
        _leg("out", CHECKING, "-110", contra=IN_TRANSIT),
        _leg("in", SAVINGS, "110"),
        _leg("in-eur", BROKER, "100", "EUR", contra=IN_TRANSIT),
    ]

    assert _ids(transfer_matcher.candidates(entries, PRICES)) == [("out", "in")]


def test_a_conversion_id_on_one_leg_only_pairs_nothing_by_it():
    changed = _leg("changed", SAVINGS, "-110", contra=IN_TRANSIT)
    changed.meta[META_CONVERSION_ID] = "c1"
    entries = [changed, _leg("bought", BROKER, "100", "EUR", contra=IN_TRANSIT)]

    assert transfer_matcher.candidates(entries, NO_PRICES) == []


def test_currencies_far_off_the_market_rate_do_not_pair():
    entries = [_leg("out", CHECKING, "-100", "EUR", contra=IN_TRANSIT), _leg("in", SAVINGS, "100")]

    assert transfer_matcher.candidates(entries, PRICES) == []


def test_currencies_without_a_market_rate_do_not_pair():
    entries = [
        _leg("out", CHECKING, "-100", "EUR", contra=IN_TRANSIT),
        _leg("in", SAVINGS, "107.50"),
    ]

    assert transfer_matcher.candidates(entries, NO_PRICES) == []


# The fee limit is 0.5% of the amount, or 10 where that is more.
@pytest.mark.parametrize(("sent", "received"), [("-4000", "3980"), ("-100", "90")])
def test_a_leg_that_arrives_short_by_a_fee_pairs(sent, received):
    entries = [
        _leg("out", CHECKING, sent, contra=IN_TRANSIT),
        _leg("in", SAVINGS, received, days=1),
    ]

    assert _ids(transfer_matcher.candidates(entries, NO_PRICES)) == [("out", "in")]


@pytest.mark.parametrize(
    ("sent", "received"), [("-4000", "3979.99"), ("-100", "89.99"), ("-100", "101")]
)
def test_a_gap_no_fee_explains_does_not_pair(sent, received):
    entries = [
        _leg("out", CHECKING, sent, contra=IN_TRANSIT),
        _leg("in", SAVINGS, received, days=1),
    ]

    assert transfer_matcher.candidates(entries, NO_PRICES) == []


@pytest.mark.parametrize(
    ("sent", "currency", "received"), [("-100", "CHF", "98"), ("-100", "EUR", "107.50")]
)
def test_a_loose_fit_between_two_unknown_rows_does_not_pair(sent, currency, received):
    entries = [_leg("out", CHECKING, sent, currency), _leg("in", SAVINGS, received)]

    assert transfer_matcher.candidates(entries, PRICES) == []


def test_a_loose_fit_between_two_unknown_rows_leaves_an_exact_pair_alone():
    entries = [
        _leg("out", CHECKING, "-100"),
        _leg("in", SAVINGS, "100"),
        _leg("in-eur", BROKER, "-91", "EUR"),
    ]

    assert _ids(transfer_matcher.candidates(entries, PRICES)) == [("out", "in")]


def test_an_exact_partner_wins_over_one_a_fee_away():
    entries = [
        _leg("out", CHECKING, "-100", contra=IN_TRANSIT),
        _leg("in", SAVINGS, "100"),
        _leg("short", BROKER, "98"),
    ]

    assert _ids(transfer_matcher.candidates(entries, NO_PRICES)) == [("out", "in")]


def test_two_legs_a_fee_away_pair_with_neither():
    entries = [
        _leg("out", CHECKING, "-100", contra=IN_TRANSIT),
        _leg("in", SAVINGS, "98"),
        _leg("also-in", BROKER, "97"),
    ]

    assert transfer_matcher.candidates(entries, NO_PRICES) == []


def test_clearing_postings_a_fee_apart_need_an_answer():
    entries = [
        _leg("out", CHECKING, "-100", contra=IN_TRANSIT),
        _leg("in", SAVINGS, "98", contra=IN_TRANSIT),
    ]

    assert _ids(transfer_matcher.candidates(entries, NO_PRICES)) == [("out", "in")]


def _book(answers, entries, existing=()):
    groups = [("statement.csv", entries, CHECKING, postfinance.CheckingImporter({}))]
    return transfer_matcher.book(answers, groups, list(existing))[0][1]


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


def test_a_confirmed_pair_books_the_fee_on_the_receiving_leg():
    entries = [_leg("out", CHECKING, "-100"), _leg("in", SAVINGS, "98")]

    _, received = _book({frozenset(["out", "in"]): True}, entries)

    assert [(p.account, p.units) for p in received.postings[1:]] == [
        (IN_TRANSIT, amount.Amount(data.Decimal("-100"), "CHF")),
        (BANK_FEES, amount.Amount(data.Decimal("2"), "CHF")),
    ]


def test_a_rejected_or_unanswered_pair_stays_as_it_was():
    entries = [_leg("out", CHECKING, "-100"), _leg("in", SAVINGS, "100")]

    assert _book({frozenset(["out", "in"]): False}, entries) == entries
    assert _book({}, entries) == entries


def test_an_exact_pair_with_a_known_leg_books_unasked():
    entries = [_leg("out", CHECKING, "-100", contra=IN_TRANSIT), _leg("in", SAVINGS, "100")]

    sent, received = _book({}, entries)

    assert sent == entries[0]
    assert received.postings[1].account == IN_TRANSIT
    assert received.meta[qif.META_CATEGORY_SOURCE] == transfer_matcher.CATEGORY_SOURCE_AUTO


def test_a_fee_pair_with_two_known_legs_books_unasked():
    entries = [
        _leg("out", CHECKING, "-100", contra=IN_TRANSIT),
        _leg("in", SAVINGS, "98", contra=IN_TRANSIT),
    ]

    _, received = _book({}, entries)

    assert received.postings[2].account == BANK_FEES


@pytest.mark.parametrize(
    ("sent", "currency", "received"), [("-100", "CHF", "98"), ("-100", "EUR", "107.50")]
)
def test_a_loose_pair_with_one_known_leg_waits_for_an_answer(sent, currency, received):
    entries = [_leg("out", CHECKING, sent, currency, IN_TRANSIT), _leg("in", SAVINGS, received)]

    assert _book({}, entries, [PRICE]) == entries


def test_a_currency_pair_with_two_known_legs_books_unasked():
    entries = [
        _leg("out", CHECKING, "-100", "EUR", IN_TRANSIT),
        _leg("in", SAVINGS, "107.50", contra=IN_TRANSIT),
    ]

    _, received = _book({}, entries, [PRICE])

    assert received.postings[1].units == amount.Amount(data.Decimal("-100"), "EUR")


def test_a_confirmed_pair_takes_its_legs_from_a_pair_that_books_unasked():
    entries = [
        _leg("out", CHECKING, "-100", contra=IN_TRANSIT),
        _leg("in", SAVINGS, "100"),
        _leg("confirmed-in", BROKER, "80", days=1),
    ]

    booked = _book({frozenset(["out", "confirmed-in"]): True}, entries)

    assert [txn.postings[1].account for txn in booked] == [IN_TRANSIT, UNCATEGORIZED, IN_TRANSIT]


def test_a_rejected_pair_with_a_known_leg_stays_as_it_was():
    entries = [_leg("out", CHECKING, "-100", contra=IN_TRANSIT), _leg("in", SAVINGS, "100")]

    assert _book({frozenset(["out", "in"]): False}, entries) == entries


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


def test_alike_lists_the_postings_unpaired_could_have_listed_instead():
    entries = [
        _cleared(CHECKING, "-100"),
        _cleared(CHECKING, "-100", days=4),
        _cleared(SAVINGS, "100", days=5),
        _cleared(SAVINGS, "100", days=12),
        _cleared(SAVINGS, "90", days=5),
        _cleared(SAVINGS, "100", days=5, currency="EUR"),
    ]
    leg = next(leg for leg in transfer_matcher.unpaired(entries) if leg[0] is entries[1])

    others = transfer_matcher.alike(entries, leg)

    assert [txn for txn, _ in others] == [entries[0], entries[2]]


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


def _pair(sender_id, receiver_id):
    sender = _leg(sender_id, CHECKING, "-100")
    receiver = _leg(receiver_id, SAVINGS, "100")
    return transfer_matcher.Pair(
        transfer_matcher.Leg(sender_id, sender), transfer_matcher.Leg(receiver_id, receiver)
    )


def test_saved_answers_load_back_after_what_the_file_held(tmp_path):
    path = tmp_path / "transfer-pairs.toml"
    path.write_text("# Kept by hand.", encoding="utf-8")

    transfer_matcher.save_answer(str(path), _pair("out", "in"), True)
    transfer_matcher.save_answer(str(path), _pair("out-2", "in-2"), False)

    assert transfer_matcher.load_answers(str(path)) == {
        frozenset(["out", "in"]): True,
        frozenset(["out-2", "in-2"]): False,
    }
    assert path.read_text(encoding="utf-8").startswith("# Kept by hand.\n[[pair]]")
