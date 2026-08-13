import datetime
import decimal

from beancount.core import amount, data
from beangulp import extract

from pybank.importer.beancount import identity


def _txn(day: int, narration: str, number: str, import_id: str | None = None):
    meta = {}
    if import_id is not None:
        meta[identity.META_KEY] = import_id
    return data.Transaction(
        meta,
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


def test_import_id_shape():
    (import_id,) = identity.import_ids([("acct", "2026-03-01", "Memo", "-9")])
    version, digest, occurrence = import_id.split(":")
    assert version == identity.VERSION
    assert len(digest) == identity.DIGEST_LEN
    assert occurrence == "0"


def test_same_fields_hash_the_same():
    fields = ("acct", "2026-03-01", "Memo", "-9")
    assert identity.import_ids([fields]) == identity.import_ids([fields])


def test_differing_fields_hash_differently():
    (a,) = identity.import_ids([("acct", "2026-03-01", "Memo", "-9")])
    (b,) = identity.import_ids([("acct", "2026-03-01", "Memo", "-8")])
    assert a != b


def test_identical_rows_get_increasing_occurrences():
    fields = ("acct", "2026-03-01", "Coffee", "-4.50")
    first, second, third = identity.import_ids([fields, fields, fields])
    assert [i.rsplit(":", 1)[1] for i in (first, second, third)] == [
        "0",
        "1",
        "2",
    ]
    assert len({first, second, third}) == 3


def test_field_separator_is_unambiguous():
    """Concatenation must not let one field bleed into the next."""
    (a,) = identity.import_ids([("ab", "c")])
    (b,) = identity.import_ids([("a", "bc")])
    assert a != b


def test_mark_duplicates_gates_on_import_id():
    existing = [_txn(1, "Groceries", "-20.00", "v1:deadbeef:0")]
    seen = _txn(1, "Groceries", "-20.00", "v1:deadbeef:0")
    fresh = _txn(2, "Rent", "-2500.00", "v1:cafef00d:0")

    identity.mark_duplicates([seen, fresh], existing)

    assert seen.meta[extract.DUPLICATE] is True
    assert extract.DUPLICATE not in fresh.meta


def test_similar_entries_only_warn(caplog):
    """A re-issued statement hashes differently. That warns, never gates."""
    existing = [_txn(1, "Supermarket", "-20.00", "v1:deadbeef:0")]
    reissued = _txn(1, "Supermarket Zurich", "-20.00", "v1:99999999:0")

    identity.mark_duplicates([reissued], existing)

    assert extract.DUPLICATE not in reissued.meta
    assert "looks like" in caplog.text


def test_empty_ledger_marks_nothing():
    fresh = _txn(1, "Groceries", "-20.00", "v1:deadbeef:0")
    identity.mark_duplicates([fresh], [])
    assert extract.DUPLICATE not in fresh.meta
