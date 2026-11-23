import datetime

from beancount.core import amount, data, flags

from pybank.importer.beancount import (
    OPENING_BALANCES,
    UNCATEGORIZED,
    postfinance,
    qif,
    qif_sidecar,
)

CHECKING = "Assets:Bank:Checking"
DINING = "Expenses:Dining"
GROCERIES = "Expenses:Shopping:Groceries"

CHF = "CHF"
DAY = datetime.date(2019, 3, 4)


def _amount(number):
    return amount.Amount(data.Decimal(number), CHF)


def _posting(account, number=None, meta=None):
    units = None if number is None else _amount(number)
    return data.Posting(account, units, None, None, None, meta)


def _txn(date, payee, narration, postings, flag=flags.FLAG_WARNING):
    return data.Transaction(
        {}, date, flag, payee, narration, data.EMPTY_SET, data.EMPTY_SET, postings
    )


def _statement(number="-20", date=DAY, payee="Corner Shop", narration="Card payment"):
    return _txn(date, payee, narration, [_posting(CHECKING, number), _posting(UNCATEGORIZED)])


def _exported(number="-20", date=DAY, narration="Card payment", category=GROCERIES, memo=None):
    counter = _posting(category, str(-data.Decimal(number)), {"split-memo": memo} if memo else None)
    return _txn(date, None, narration, [_posting(CHECKING, number), counter], flags.FLAG_OKAY)


def _donate(statements, exports):
    """Runs the hook over one statement file and one export file."""
    groups = [
        ("statement.csv", statements, CHECKING, postfinance.CheckingImporter({})),
        ("export.qif", exports, CHECKING, qif.Importer({CHECKING: qif.Target(CHECKING, CHF)})),
    ]
    result = qif_sidecar.donate(groups, [])
    return result[0][1], result[1][1]


def test_a_repeated_row_is_dropped_and_hands_over_its_category():
    statements, exports = _donate([_statement()], [_exported()])

    assert exports == []
    (kept,) = statements
    assert [posting.account for posting in kept.postings] == [CHECKING, GROCERIES]
    assert kept.meta[qif.META_CATEGORY_SOURCE] == qif.CATEGORY_SOURCE_QIF
    assert kept.flag == flags.FLAG_OKAY


def test_the_statement_keeps_its_own_payee_and_narration():
    statements, _ = _donate([_statement()], [_exported(narration="Card paymen")])

    assert statements[0].payee == "Corner Shop"
    assert statements[0].narration == "Card payment"


def test_a_truncated_copy_of_the_statement_text_is_not_a_note():
    """The exporter cut the bank's own memo into that field. It adds nothing."""
    statements, _ = _donate([_statement()], [_exported(narration="corner shop, card pay")])

    assert qif_sidecar.META_NOTE not in statements[0].meta


def test_a_reworded_copy_of_the_statement_text_is_not_a_note():
    """The two sources word one description differently, so words decide."""
    reworded = "Card payment, Corner Shop, ref 88"

    statements, _ = _donate([_statement()], [_exported(narration=reworded)])

    assert qif_sidecar.META_NOTE not in statements[0].meta


def test_a_hand_typed_note_is_kept_out_of_the_narration():
    statements, _ = _donate([_statement()], [_exported(narration="Repaid by Sam")])

    assert statements[0].meta[qif_sidecar.META_NOTE] == "Repaid by Sam"
    assert statements[0].narration == "Card payment"


def test_a_row_the_statement_books_days_later_still_pairs():
    late = _statement(date=DAY + datetime.timedelta(days=5))

    statements, exports = _donate([late], [_exported()])

    assert exports == []
    assert statements[0].postings[1].account == GROCERIES


def test_a_row_outside_the_window_stays_a_transaction_of_its_own():
    late = _statement(date=DAY + datetime.timedelta(days=6))

    statements, exports = _donate([late], [_exported()])

    assert len(exports) == 1
    assert statements[0].postings[1].account == UNCATEGORIZED


def test_a_row_dated_by_the_purchase_pairs_with_its_card_booking():
    booked = _statement(number="20", date=DAY - datetime.timedelta(days=20))
    booked.meta[postfinance.META_RECEIPT_DATE] = DAY.strftime("%d.%m.%Y")

    statements, exports = _donate([booked], [_exported(number="20")])

    assert exports == []
    assert statements[0].postings[1].account == GROCERIES


def test_an_unreadable_purchase_date_leaves_the_booking_date():
    booked = _statement()
    booked.meta[postfinance.META_RECEIPT_DATE] = "not a date"

    statements, exports = _donate([booked], [_exported()])

    assert exports == []
    assert statements[0].postings[1].account == GROCERIES


def test_a_different_amount_is_a_different_event():
    statements, exports = _donate([_statement(number="-21")], [_exported(number="-20")])

    assert len(exports) == 1
    assert statements[0].postings[1].account == UNCATEGORIZED


def test_one_statement_transaction_absorbs_one_row():
    """Two coffees on one day are two events in both sources, and stay two."""
    statements, exports = _donate([_statement()], [_exported(), _exported()])

    assert len(statements) == 1
    assert len(exports) == 1


def test_two_alike_rows_pair_with_two_alike_transactions_in_file_order():
    """Nothing tells them apart, so their categories can end up swapped."""
    statements, exports = _donate(
        [_statement(), _statement()],
        [_exported(category=GROCERIES), _exported(category=DINING)],
    )

    assert exports == []
    assert [txn.postings[1].account for txn in statements] == [GROCERIES, DINING]


def test_a_row_the_export_left_uncategorized_still_gives_way():
    statements, exports = _donate([_statement()], [_exported(category=UNCATEGORIZED)])

    assert exports == []
    assert statements[0].postings[1].account == UNCATEGORIZED
    assert qif.META_CATEGORY_SOURCE not in statements[0].meta


def test_a_row_the_export_left_uncategorized_still_hands_over_its_note():
    export = _exported(narration="Repaid by Sam", category=UNCATEGORIZED)

    statements, _ = _donate([_statement()], [export])

    assert statements[0].meta[qif_sidecar.META_NOTE] == "Repaid by Sam"
    assert statements[0].postings[1].account == UNCATEGORIZED


def test_a_split_hands_over_every_leg():
    export = _txn(
        DAY,
        None,
        "Card payment",
        [
            _posting(CHECKING, "-20"),
            _posting(GROCERIES, "12"),
            _posting(DINING, "8"),
        ],
        flags.FLAG_OKAY,
    )

    statements, _ = _donate([_statement()], [export])

    assert [posting.account for posting in statements[0].postings] == [
        CHECKING,
        GROCERIES,
        DINING,
    ]


def test_an_opening_balance_does_not_fold_into_a_deposit_of_the_same_amount():
    deposit = _statement("500")
    opening = _exported("500", category=OPENING_BALANCES)

    statements, exports = _donate([deposit], [opening])

    assert statements == [deposit]
    assert exports == [opening]


def test_an_export_imported_on_its_own_is_left_alone():
    exports = [_exported()]
    groups = [
        ("export.qif", exports, CHECKING, qif.Importer({CHECKING: qif.Target(CHECKING, CHF)}))
    ]

    assert qif_sidecar.donate(groups, []) == groups


def test_a_categorized_statement_transaction_is_not_a_slot():
    """Only the contra posting an importer leaves open can take a category."""
    booked = _txn(
        DAY, "Corner Shop", "Card payment", [_posting(CHECKING, "-20"), _posting(GROCERIES, "20")]
    )

    statements, exports = _donate([booked], [_exported()])

    assert len(exports) == 1
    assert statements[0].postings[1].account == GROCERIES


def test_a_memo_built_from_numbers_is_not_a_note():
    """Card and reference numbers are the bank's own text, not a note."""
    numbers = "4111 1111 1111 1111 Visa refund ref 99"

    statements, _ = _donate([_statement()], [_exported(narration=numbers)])

    assert qif_sidecar.META_NOTE not in statements[0].meta


def test_an_umlaut_does_not_split_a_word_in_two():
    """Splitting `Zürich` invents a `rich`, which is half of this note."""
    statements, _ = _donate([_statement(payee="Zürich Shop")], [_exported(narration="Rich paid")])

    assert statements[0].meta[qif_sidecar.META_NOTE] == "Rich paid"


def test_a_memo_carrying_an_appended_field_label_is_not_a_note():
    """The old scraper wrote those labels. The statement carries the fields."""
    appended = "Shop Original amount: 21"

    statements, _ = _donate([_statement()], [_exported(narration=appended)])

    assert qif_sidecar.META_NOTE not in statements[0].meta
