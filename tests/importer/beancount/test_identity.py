import datetime
import decimal

import pytest
from beancount.core import amount, data
from beangulp import extract

from pybank.importer.beancount import identity


def _txn(day: int, narration: str, number: str, import_id: str):
    return data.Transaction(
        {identity.META_KEY: import_id},
        datetime.date(2026, 3, day),
        "*",
        None,
        narration,
        data.EMPTY_SET,
        data.EMPTY_SET,
        [
            data.Posting(
                "Assets:Bank",
                amount.Amount(decimal.Decimal(number), "CHF"),
                None,
                None,
                None,
                None,
            ),
            data.Posting("Expenses:Uncategorized", None, None, None, None, None),
        ],
    )


def _fields(date="2026-03-01", amount="-9", hashed=("acct", "Memo")):
    return identity.IdFields(date, amount, hashed)


def test_import_id_shape():
    (import_id,) = identity.import_ids([_fields()])
    version, date, amount, digest, occurrence = import_id.split(":")
    assert version == identity.VERSION
    assert date == "2026-03-01"
    assert amount == "-9"
    assert len(digest) == identity._DIGEST_LEN
    assert occurrence == "0"


def test_same_fields_yield_the_same_id():
    assert identity.import_ids([_fields()]) == identity.import_ids([_fields()])


def test_differing_hashed_fields_yield_different_ids():
    a = identity.import_ids([_fields(hashed=("acct", "Memo"))])
    b = identity.import_ids([_fields(hashed=("acct", "Other"))])
    assert a != b


def test_differing_amounts_yield_different_ids():
    a = identity.import_ids([_fields(amount="-9")])
    b = identity.import_ids([_fields(amount="-8")])
    assert a != b


def test_differing_dates_yield_different_ids():
    a = identity.import_ids([_fields(date="2026-03-01")])
    b = identity.import_ids([_fields(date="2026-03-02")])
    assert a != b


@pytest.mark.parametrize(
    "number, expected",
    [("24", "24"), ("24.00", "24"), ("1000.00", "1000"), ("-85.50", "-85.5")],
)
def test_canonical_amount_drops_trailing_zeros_without_an_exponent(number, expected):
    assert identity.canonical_amount(decimal.Decimal(number)) == expected


def test_identical_rows_get_increasing_occurrences():
    fields = _fields(amount="-4.5", hashed=("acct", "Coffee"))
    ids = identity.import_ids([fields, fields, fields])
    assert [i.rsplit(":", 1)[1] for i in ids] == ["0", "1", "2"]
    assert len(set(ids)) == 3


def test_a_colliding_digest_does_not_merge_rows_of_other_dates():
    """Date and amount are part of the key, not just the digest."""
    same_digest = ("acct", "Memo")
    a, b = identity.import_ids(
        [
            _fields(date="2026-03-01", hashed=same_digest),
            _fields(date="2026-09-09", hashed=same_digest),
        ]
    )
    assert a.rsplit(":", 1)[0] != b.rsplit(":", 1)[0]
    assert [i.rsplit(":", 1)[1] for i in (a, b)] == ["0", "0"]


def test_field_separator_is_unambiguous():
    """Concatenation must not let one field bleed into the next."""
    (a,) = identity.import_ids([_fields(hashed=("ab", "c"))])
    (b,) = identity.import_ids([_fields(hashed=("a", "bc"))])
    assert a != b


def test_mark_duplicates_gates_on_import_id():
    existing = [_txn(1, "Groceries", "-20.00", "v1:2026-03-01:-20:deadbeefcafe:0")]
    seen = _txn(1, "Groceries", "-20.00", "v1:2026-03-01:-20:deadbeefcafe:0")
    fresh = _txn(2, "Rent", "-2500.00", "v1:2026-03-02:-2500:cafef00dfeed:0")

    identity.mark_duplicates([seen, fresh], existing)

    assert seen.meta[extract.DUPLICATE] is True
    assert extract.DUPLICATE not in fresh.meta


def test_similar_entries_only_warn(caplog):
    """A re-issued statement hashes differently. That warns, never gates."""
    existing = [_txn(1, "Supermarket", "-20.00", "v1:2026-03-01:-20:deadbeefcafe:0")]
    reissued = _txn(1, "Supermarket Zurich", "-20.00", "v1:2026-03-01:-20:99999999aaaa:0")

    identity.mark_duplicates([reissued], existing)

    assert extract.DUPLICATE not in reissued.meta
    assert "looks like" in caplog.text


def test_empty_ledger_marks_nothing():
    fresh = _txn(1, "Groceries", "-20.00", "v1:2026-03-01:-20:deadbeefcafe:0")
    identity.mark_duplicates([fresh], [])
    assert extract.DUPLICATE not in fresh.meta


def test_a_categorized_twin_still_warns(caplog):
    """The fresh entry's open contra leg must not hide a categorized match."""
    categorized = _txn(1, "Supermarket", "-20.00", "v1:2026-03-01:-20:deadbeefcafe:0")
    categorized.postings[1] = data.Posting(
        "Expenses:Food",
        amount.Amount(decimal.Decimal("20.00"), "CHF"),
        None,
        None,
        None,
        None,
    )
    reissued = _txn(1, "Supermarket Zurich", "-20.00", "v1:2026-03-01:-20:99999999aaaa:0")

    identity.mark_duplicates([reissued], [categorized])

    assert "looks like" in caplog.text


def _balance(number: str):
    return data.Balance(
        {},
        datetime.date(2026, 3, 2),
        "Assets:Bank",
        amount.Amount(decimal.Decimal(number), "CHF"),
        None,
        None,
    )


def test_a_balance_the_ledger_already_asserts_is_a_duplicate():
    asserted = _balance("100.00")
    again = _balance("100")
    other = _balance("90.00")

    identity.mark_duplicates([again, other], [asserted])

    assert again.meta[extract.DUPLICATE] is True
    assert extract.DUPLICATE not in other.meta
