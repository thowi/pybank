import datetime

from beancount.core import amount, data, flags, prices

from pybank.importer.beancount import IN_TRANSIT, UNCATEGORIZED, transfer_matcher, transfer_review

DAY = datetime.date(2019, 3, 4)

# 1 EUR buys 1.10 CHF.
PRICE = data.Price({}, DAY, "EUR", amount.Amount(data.Decimal("1.10"), "CHF"))


def _txn(import_id, account, number, currency="CHF", contra=UNCATEGORIZED):
    postings = [
        data.Posting(
            account, amount.Amount(data.Decimal(number), currency), None, None, None, None
        ),
        data.Posting(contra, None, None, None, None, None),
    ]
    meta = {"import-id": import_id}
    return data.Transaction(
        meta, DAY, flags.FLAG_WARNING, None, "Transfer", data.EMPTY_SET, data.EMPTY_SET, postings
    )


def _cleared(import_id, account, number):
    """Returns a transfer leg with its clearing amount set, as once loaded."""
    txn = _txn(import_id, account, number, contra=IN_TRANSIT)
    units = amount.Amount(-data.Decimal(number), "CHF")
    return txn._replace(postings=[txn.postings[0], txn.postings[1]._replace(units=units)])


def _pair(sent, received):
    return transfer_matcher.Pair(
        transfer_matcher.Leg("out", sent), transfer_matcher.Leg("in", received)
    )


def test_rate_check_quotes_the_currency_worth_more():
    pair = _pair(_txn("out", "Assets:A", "-100", "EUR"), _txn("in", "Assets:B", "107.50"))

    check = transfer_review.rate_check(pair, prices.build_price_map([PRICE]))

    assert (check.base, check.quote) == ("EUR", "CHF")
    assert check.implied == data.Decimal("1.075")
    assert (check.market, check.market_date) == (data.Decimal("1.10"), DAY)
    # 107.50 CHF is worth 97.73 EUR at the market, 2.27 EUR short of 100.
    assert check.spread == amount.Amount(data.Decimal("2.27"), "EUR")
    assert round(check.spread_share, 4) == data.Decimal("0.0227")


def test_rate_check_without_a_price_leaves_the_market_open():
    pair = _pair(_txn("out", "Assets:A", "-100", "EUR"), _txn("in", "Assets:B", "107.50"))

    check = transfer_review.rate_check(pair, prices.build_price_map([]))

    assert check.market is check.spread is None


def test_one_currency_needs_no_rate_check():
    pair = _pair(_txn("out", "Assets:A", "-100"), _txn("in", "Assets:B", "100"))

    assert transfer_review.rate_check(pair, prices.build_price_map([])) is None


def test_an_answered_pair_is_no_longer_pending(tmp_path):
    entries = [_txn("out", "Assets:A", "-100"), _txn("in", "Assets:B", "100")]
    session = transfer_review.Session(str(tmp_path / "answers.toml"), entries)
    (pair,) = session.pending_pairs()

    session.answer_pair(pair, False)

    assert session.pending_pairs() == []
    reloaded = transfer_review.Session(str(tmp_path / "answers.toml"), entries)
    assert reloaded.pending_pairs() == []


def test_answering_none_rejects_every_option(tmp_path):
    entries = [
        _cleared("out", "Assets:A", "-100"),
        _txn("in", "Assets:B", "100"),
        _txn("also-in", "Assets:C", "100"),
    ]
    session = transfer_review.Session(str(tmp_path / "answers.toml"), entries)
    (choice,) = session.choices()
    options = session.open_options(choice)

    session.answer_choice(choice.leg, options, None)

    assert len(options) == 2
    assert session.open_options(choice) == []
    assert set(session.answers.values()) == {False}


def test_a_picked_partner_takes_both_legs(tmp_path):
    entries = [
        _cleared("out", "Assets:A", "-100"),
        _txn("in", "Assets:B", "100"),
        _txn("also-in", "Assets:C", "100"),
    ]
    session = transfer_review.Session(str(tmp_path / "answers.toml"), entries)
    (choice,) = session.choices()
    options = session.open_options(choice)

    session.answer_choice(choice.leg, options, options[1])

    assert session.taken == {"out", options[1].import_id}
    assert list(session.answers.values()) == [True]
