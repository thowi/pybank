import datetime
import re

from beancount.core import amount, data, flags
from beangulp import extract

from pybank.importer.beancount import (
    CATEGORY_SOURCE_SUGGESTED,
    IN_TRANSIT,
    UNCATEGORIZED,
    identity,
    postfinance,
    qif,
    refunds,
)

CARD = "Liabilities:Bank:Card"
CHECKING = "Assets:Bank:Checking"
GIFTS = "Expenses:Shopping:Gifts"
SPORT = "Expenses:Leisure:Sport"

DAY = datetime.date(2024, 3, 4)
LEDGER = "main.beancount"
STATEMENT = "statement.csv"
CONFIG = refunds.Config(
    accounts=("Liabilities:Bank",),
    labels=frozenset({"Returns"}),
    prefixes=tuple(re.compile(p, re.IGNORECASE) for p in (r"retoure\b\.?", r"paypal\s*\*")),
)


def _txn(number, narration, days=0, account=CARD, contra=UNCATEGORIZED, label=None, file=STATEMENT):
    units = amount.Amount(data.Decimal(number), "CHF")
    counter_meta = {qif.META_QIF_CATEGORY: label} if label else None
    counter_units = None if contra == UNCATEGORIZED else -units
    postings = [
        data.Posting(account, units, None, None, None, None),
        data.Posting(contra, counter_units, None, None, None, counter_meta),
    ]
    meta = {"filename": file, identity.META_KEY: f"v1:{number}:{narration}:{days}"}
    flag = flags.FLAG_WARNING if contra == UNCATEGORIZED else flags.FLAG_OKAY
    day = DAY + datetime.timedelta(days=days)
    return data.Transaction(
        meta, day, flag, None, narration, data.EMPTY_SET, data.EMPTY_SET, postings
    )


def _split(number, parts):
    row = _txn(number, "Bike Shop", contra=SPORT)
    counters = [
        data.Posting(a, amount.Amount(data.Decimal(n), "CHF"), None, None, None, None)
        for a, n in parts.items()
    ]
    return row._replace(postings=[row.postings[0], *counters])


def _book(entries, existing=(), config=CONFIG):
    groups = [(STATEMENT, entries, CARD, postfinance.CheckingImporter({}))]
    return refunds.book(config, groups, list(existing))[0][1]


def test_a_refund_books_to_the_account_of_its_purchase():
    buy = _txn("-80", "Bike Shop Berlin", contra=SPORT)
    back = _txn("80", "Retoure. Bike Shop Berlin", days=10)

    linked_buy, refund = _book([buy, back])

    assert refund.postings[1].account == SPORT
    assert refund.flag == flags.FLAG_OKAY
    assert refund.tags == {refunds.TAG_REFUND}
    assert refund.meta[qif.META_CATEGORY_SOURCE] == refunds.CATEGORY_SOURCE_REFUND
    assert refund.links == linked_buy.links and len(refund.links) == 1


def test_an_open_purchase_stays_open_and_linked():
    buy, back = _book([_txn("-80", "PayPal *bikeshop"), _txn("80", "bikeshop", days=3)])

    assert back.postings[1].account == UNCATEGORIZED
    assert back.flag == flags.FLAG_WARNING
    assert back.links == buy.links and back.links


def test_the_refund_of_a_purchase_on_a_suggestion_stays_open():
    buy = _txn("-80", "Bike Shop", contra=SPORT, file=LEDGER)
    buy = buy._replace(meta={**buy.meta, qif.META_CATEGORY_SOURCE: CATEGORY_SOURCE_SUGGESTED})

    (back,) = _book([_txn("80", "Bike Shop", days=3)], existing=[buy])

    assert back.postings[1].account == UNCATEGORIZED
    assert back.links


def test_a_refund_with_no_purchase_only_gets_the_tag():
    (back,) = _book([_txn("40", "Bike Shop")])

    assert back.tags == {refunds.TAG_REFUND}
    assert not back.links
    assert back.postings[1].account == UNCATEGORIZED


def test_the_purchase_with_the_same_amount_wins_over_larger_ones():
    small, large, back = _book(
        [
            _txn("-30", "Bike Shop", contra=SPORT),
            _txn("-30.20", "Bike Shop"),
            _txn("30", "Bike Shop", days=5),
        ]
    )

    assert back.links == small.links and back.links
    assert not large.links


def test_several_larger_purchases_leave_the_refund_unlinked():
    entries = [_txn("-50", "Bike Shop"), _txn("-90", "Bike Shop"), _txn("30", "Bike Shop", days=5)]

    *_, back = _book(entries)

    assert not back.links
    assert back.tags == {refunds.TAG_REFUND}


def test_a_purchase_must_be_earlier_recent_and_on_the_same_account():
    entries = [
        _txn("-30", "Bike Shop", days=1),
        _txn("-30", "Bike Shop", days=-121),
        _txn("-30", "Bike Shop", account=CHECKING),
        _txn("30", "Bike Shop"),
    ]

    *_, back = _book(entries)

    assert not back.links


def test_a_foreign_refund_may_exceed_its_purchase_a_little():
    buy = _txn("-100", "Bike Shop", contra=SPORT)

    _, back = _book([buy, _txn("102.50", "Bike Shop", days=5)])

    assert back.links
    assert back.postings[1].account == UNCATEGORIZED


def test_a_labeled_row_on_another_account_counts_as_a_refund():
    (back,) = _book([_txn("20", "Shop", account=CHECKING, label="Returns")])

    assert back.tags == {refunds.TAG_REFUND}


def test_money_in_elsewhere_is_no_refund():
    (row,) = _book([_txn("20", "Salary", account=CHECKING)])

    assert not row.tags


def test_a_purchase_in_the_existing_ledger_counts():
    buy = _txn("-80", "Bike Shop", contra=SPORT, file=LEDGER)

    (back,) = _book([_txn("80", "Bike Shop", days=2)], existing=[buy])

    assert back.postings[1].account == SPORT


def test_a_duplicate_is_left_alone():
    row = _txn("20", "Bike Shop")
    row.meta[extract.DUPLICATE] = True

    (kept,) = _book([row])

    assert kept is row


def test_no_config_changes_nothing():
    row = _txn("20", "Bike Shop")

    (kept,) = _book([row], config=refunds.Config())

    assert kept is row


def test_an_existing_copy_of_an_imported_purchase_is_ignored():
    buy = _txn("-80", "Bike Shop")

    linked_buy, back = _book([buy, _txn("80", "Bike Shop", days=2)], existing=[buy._replace()])

    assert back.links == linked_buy.links and back.links


def test_a_row_an_earlier_hook_dropped_is_no_second_purchase():
    buy = _txn("-80", "Bike Shop")
    dropped = buy._replace(meta={**buy.meta, identity.META_KEY: "v1:other"})

    linked_buy, back = _book([buy, _txn("80", "Bike Shop", days=2)], existing=[buy, dropped])

    assert back.links == linked_buy.links and back.links


def test_a_duplicate_purchase_gets_no_link():
    buy = _txn("-80", "Bike Shop", contra=SPORT, file=LEDGER)
    again = _txn("-80", "Bike Shop", contra=SPORT)
    again.meta[extract.DUPLICATE] = True

    kept, back = _book([again, _txn("80", "Bike Shop", days=2)], existing=[buy])

    assert not kept.links
    assert back.postings[1].account == SPORT


def test_a_transfer_out_is_no_purchase():
    _, back = _book([_txn("-80", "Bike Shop", contra=IN_TRANSIT), _txn("80", "Bike Shop", days=2)])

    assert not back.links
    assert back.postings[1].account == UNCATEGORIZED


def test_a_row_with_no_merchant_word_has_no_purchase():
    _, back = _book([_txn("-80", "12 34"), _txn("80", "56", days=2)])

    assert not back.links


def test_several_prefixes_are_cut_in_any_order():
    buy, back = _book([_txn("-80", "Bike Shop"), _txn("80", "Retoure. PayPal *Bike Shop", days=2)])

    assert back.links == buy.links and back.links


def test_a_prefix_that_is_not_configured_stays():
    config = CONFIG._replace(prefixes=())

    _, back = _book(
        [_txn("-80", "Bike Shop"), _txn("80", "Retoure. Bike Shop", days=2)], config=config
    )

    assert not back.links


def test_refunds_that_exceed_their_purchase_together_get_no_link():
    buy, *backs = _book(
        [
            _txn("-80", "Bike Shop", contra=SPORT),
            _txn("60", "Bike Shop", days=2),
            _txn("30", "Bike Shop", days=5),
        ]
    )

    assert not buy.links
    for back in backs:
        assert back.tags == {refunds.TAG_REFUND}
        assert not back.links
        assert back.postings[1].account == UNCATEGORIZED


def test_a_refund_of_the_same_amount_claims_its_purchase():
    buy, partial, full = _book(
        [
            _txn("-80", "Bike Shop"),
            _txn("20", "Bike Shop", days=2),
            _txn("80", "Bike Shop", days=5),
        ]
    )

    assert full.links == buy.links and full.links
    assert not partial.links


def test_a_refund_of_nearly_the_same_amount_claims_its_purchase():
    buy, partial, full = _book(
        [
            _txn("-80.30", "Bike Shop"),
            _txn("20", "Bike Shop", days=2),
            _txn("80", "Bike Shop", days=5),
        ]
    )

    assert full.links == buy.links and full.links
    assert not partial.links


def test_a_refund_that_becomes_clear_late_claims_its_purchase():
    # The last refund is too late for the first purchase, so it takes the other.
    buy, _, full, partial, _ = _book(
        [
            _txn("-80", "Bike Shop", days=-115),
            _txn("-80.30", "Bike Shop"),
            _txn("80.10", "Bike Shop", days=2),
            _txn("20", "Bike Shop", days=3),
            _txn("80.20", "Bike Shop", days=10),
        ]
    )

    assert full.links == buy.links and full.links
    assert not partial.links


def test_the_earlier_refund_claims_its_purchase():
    _, later, earlier = _book(
        [
            _txn("-80", "Bike Shop"),
            _txn("80", "Bike Shop", days=5),
            _txn("80", "Bike Shop", days=2),
        ]
    )

    assert earlier.links
    assert not later.links


def test_a_purchase_of_nearly_the_same_amount_wins_over_a_larger_one():
    near, large, back = _book(
        [
            _txn("-80.30", "Bike Shop", contra=SPORT),
            _txn("-200", "Bike Shop"),
            _txn("80", "Bike Shop", days=5),
        ]
    )

    assert back.links == near.links and back.links
    assert back.postings[1].account == SPORT
    assert not large.links


def test_a_partial_refund_is_linked_and_stays_open():
    buy, back = _book([_txn("-80", "Bike Shop", contra=SPORT), _txn("30", "Bike Shop", days=3)])

    assert back.links == buy.links and back.links
    assert back.postings[1].account == UNCATEGORIZED
    assert back.flag == flags.FLAG_WARNING


def test_a_refund_of_one_part_of_a_split_purchase_books_to_its_account():
    split = _split("-80", {GIFTS: "50", SPORT: "30"})

    buy, other, back = _book([split, _txn("-90", "Bike Shop"), _txn("30", "Bike Shop", days=3)])

    assert back.links == buy.links and back.links
    assert back.postings[1].account == SPORT
    assert not other.links


def test_a_full_refund_of_a_split_purchase_is_linked_and_stays_open():
    buy, back = _book([_split("-80", {GIFTS: "50", SPORT: "30"}), _txn("80", "Bike Shop", days=3)])

    assert back.links == buy.links and back.links
    assert back.postings[1].account == UNCATEGORIZED


def test_a_refund_that_fits_two_parts_is_linked_and_stays_open():
    buy, back = _book([_split("-60", {GIFTS: "30", SPORT: "30"}), _txn("30", "Bike Shop", days=3)])

    assert back.links == buy.links and back.links
    assert back.postings[1].account == UNCATEGORIZED


def test_a_split_with_a_transfer_is_no_purchase():
    _, back = _book([_split("-80", {IN_TRANSIT: "50", SPORT: "30"}), _txn("30", "Bike Shop")])

    assert not back.links


def test_refunds_that_fit_their_purchase_together_share_its_link():
    buy, *backs = _book(
        [
            _txn("-80", "Bike Shop"),
            _txn("62", "Bike Shop", days=2),
            _txn("20", "Bike Shop", days=5),
        ]
    )

    assert buy.links
    assert all(back.links == buy.links for back in backs)
