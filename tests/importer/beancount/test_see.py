"""All values here are invented. Never derive a fixture from a real database.

Booking is `qif.Importer`'s and tested there. These tests cover reading the
database into the same rows.
"""

import datetime
import decimal
import sqlite3

import pytest
from beancount import loader
from beancount.core import data, flags
from beancount.parser import printer

from pybank.importer.beancount import (
    IN_TRANSIT,
    META_CONVERSION_ID,
    OPENING_BALANCES,
    UNCATEGORIZED,
    qif,
    routing,
    see,
)

CHECKING = "Assets:Bank:Checking"
CARD = "Liabilities:Bank:Card"

TARGETS = {
    "Checking": qif.Target(CHECKING, "CHF"),
    "Card": qif.Target(CARD, "CHF"),
}

# Only the tables and columns the importer reads, as the app names them.
SCHEMA = """
CREATE TABLE Accounts (AccountID_PK TEXT, Name TEXT, CurrencyCode TEXT,
    CategoryID_NN_UK_FK TEXT);
CREATE TABLE Categories (CategoryID_PK TEXT, ParentID_FK TEXT, Name TEXT,
    TypeNumber INTEGER);
CREATE TABLE Payees (PayeeID_PK TEXT, Name TEXT);
CREATE TABLE Transactions (TransactionID_PK TEXT, ParentID_FK TEXT,
    Position INTEGER, AccountID_FK TEXT, PayeeID_FK TEXT, CategoryID_FK TEXT,
    InvestmentTransactionDetailsID_UK_FK TEXT, LinkedTransferID_UK_FK TEXT,
    Date REAL, Memo TEXT, Amount REAL);
"""

ACCOUNTS = [
    ("a-chk", "Checking", "CHF", "c-chk"),
    ("a-card", "Card", "CHF", "c-card"),
    ("a-sav", "Savings", "CHF", "c-sav"),
    ("a-inv", "Brokerage", "CHF", "c-inv"),
]

CATEGORIES = [
    ("c-chk", None, "Checking", 111),
    ("c-card", None, "Card", 111),
    ("c-sav", None, "Savings", 111),
    ("c-inv", None, "Brokerage", 111),
    ("c-split", None, "Split", 101),
    ("c-other", None, "Other Account", 110),
    ("c-vault", "c-other", "Old Vault", 112),
    ("c-food", None, "Groceries", 1),
    ("c-auto", None, "Auto & Transport", 1),
    ("c-fuel", "c-auto", "Fuel", 1),
    ("c-pay", None, "Salary", 2),
]

PAYEES = [("p-shop", "Grocer Ltd"), ("p-work", "Employer"), ("p-open", "Starting Balance")]

LONG_MEMO = "A memo far longer than any QIF export keeps, " * 3


def _day(year, month, day):
    """Returns the app's timestamp for a day: Noon UTC."""
    noon = datetime.datetime(year, month, day, 12, tzinfo=datetime.UTC)
    return noon.timestamp()


# (id, parent, account, payee, category, investment, linked, date, memo, amount)
TRANSACTIONS = [
    ("t-open", None, "a-chk", "p-open", "c-chk", None, None, _day(2026, 1, 1), None, 1000.0),
    ("t-shop", None, "a-chk", "p-shop", "c-food", None, None, _day(2026, 1, 5), "Weekly", -42.5),
    ("t-pay", None, "a-chk", "p-work", "c-pay", None, None, _day(2026, 1, 7), "Pay", 5000.0),
    ("t-out", None, "a-chk", None, "c-card", None, "t-in", _day(2026, 1, 9), "Out", -100.0),
    ("t-in", None, "a-card", None, "c-chk", None, "t-out", _day(2026, 1, 9), "In", 100.0),
    ("t-none", None, "a-chk", None, None, None, None, _day(2026, 1, 11), LONG_MEMO, -7.25),
    ("t-lost", None, "a-chk", None, "c-split", None, None, _day(2026, 1, 12), "Lost", -30.0),
    # Float noise, as a computed amount carries it.
    (
        "t-big",
        None,
        "a-chk",
        None,
        "c-split",
        None,
        None,
        _day(2026, 1, 13),
        "Big",
        0.1 + 0.2 - 60.3,
    ),
    ("t-big-1", "t-big", None, None, "c-food", None, None, _day(2026, 1, 13), "Food part", -45.0),
    ("t-big-2", "t-big", None, None, "c-fuel", None, None, _day(2026, 1, 13), None, -15.0),
    ("t-vault", None, "a-card", None, "c-vault", None, None, _day(2026, 1, 20), "Vault", -18.0),
    ("t-sav", None, "a-sav", None, "c-food", None, None, _day(2026, 1, 14), "Skipped", -11.0),
    ("t-buy", None, "a-card", None, None, "i-buy", None, _day(2026, 1, 22), "Shares", -50.0),
]


def _write(tmp_path, transactions=TRANSACTIONS, accounts=ACCOUNTS):
    folder = tmp_path / "Money.scsf" / "Database"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "Database.sqlite"
    path.unlink(missing_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO Accounts VALUES (?, ?, ?, ?)", accounts)
    con.executemany("INSERT INTO Categories VALUES (?, ?, ?, ?)", CATEGORIES)
    con.executemany("INSERT INTO Payees VALUES (?, ?)", PAYEES)
    con.executemany(
        "INSERT INTO Transactions (TransactionID_PK, ParentID_FK, AccountID_FK, PayeeID_FK,"
        " CategoryID_FK, InvestmentTransactionDetailsID_UK_FK, LinkedTransferID_UK_FK, Date,"
        " Memo, Amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        transactions,
    )
    con.commit()
    con.close()
    return str(path)


@pytest.fixture
def importer():
    return see.Importer(TARGETS, {"*Old Vault": "Assets:Vault"})


@pytest.fixture
def path(tmp_path):
    return _write(tmp_path)


def _by_narration(entries):
    return {e.narration: e for e in entries if isinstance(e, data.Transaction)}


def test_identify_accepts_the_database(importer, path):
    assert importer.identify(path)


def test_identify_rejects_other_files(tmp_path, importer):
    other = tmp_path / "other.sqlite"
    con = sqlite3.connect(other)
    con.execute("CREATE TABLE Transactions (Id TEXT)")
    con.close()
    text = tmp_path / "notes.sqlite"
    text.write_text("not a database")

    assert not importer.identify(str(other))
    assert not importer.identify(str(text))
    assert not importer.identify(str(tmp_path / "missing.sqlite"))


def test_extract_reads_only_mapped_accounts_and_no_investments(importer, path):
    """Savings is unmapped. The share purchase would book as spending."""
    assert set(_by_narration(importer.extract(path, []))) == {
        "",
        "Weekly",
        "Pay",
        "Out",
        "In",
        LONG_MEMO.strip(),
        "Lost",
        "Big",
        "Vault",
    }


def test_dates_amounts_payees_and_memos(importer, path):
    txns = _by_narration(importer.extract(path, []))

    shop = txns["Weekly"]
    assert shop.date == datetime.date(2026, 1, 5)
    assert shop.payee == "Grocer Ltd"
    assert shop.postings[0].units == data.Amount(decimal.Decimal("-42.50"), "CHF")
    assert txns["Big"].postings[0].units.number == decimal.Decimal("-60.00")
    assert LONG_MEMO.strip() in txns, "the memo is kept in full"


def test_categories_book_like_the_qif_export(importer, path):
    txns = _by_narration(importer.extract(path, []))

    assert txns["Weekly"].postings[1].account == "Expenses:Groceries"
    assert txns["Weekly"].postings[1].meta["qif-category"] == "Groceries"
    assert txns["Weekly"].meta["category-source"] == "qif"
    assert txns["Pay"].postings[1].account == "Income:Salary"
    assert txns["Vault"].postings[1].account == "Assets:Vault"
    assert txns["Vault"].postings[1].meta["qif-category"] == "*Old Vault"


def test_a_row_on_its_own_account_with_the_opening_payee_opens_it(importer, path):
    txn = _by_narration(importer.extract(path, []))[""]
    assert txn.postings[1].account == OPENING_BALANCES


def test_linked_transfer_legs_share_a_conversion_id(importer, path):
    txns = _by_narration(importer.extract(path, []))
    out, back = txns["Out"], txns["In"]

    assert out.postings[1].account == back.postings[1].account == IN_TRANSIT
    assert out.postings[1].meta["qif-transfer"] == "Card"
    assert out.meta[META_CONVERSION_ID] == back.meta[META_CONVERSION_ID]
    assert META_CONVERSION_ID not in txns["Weekly"].meta


def test_a_split_books_one_posting_per_child(importer, path):
    txn = _by_narration(importer.extract(path, []))["Big"]

    assert [p.account for p in txn.postings[1:]] == [
        "Expenses:Groceries",
        "Expenses:Auto-Transport:Fuel",
    ]
    assert [p.units.number for p in txn.postings[1:]] == [
        decimal.Decimal("45.00"),
        decimal.Decimal("15.00"),
    ]
    assert txn.postings[1].meta["split-memo"] == "Food part"
    assert "split-memo" not in txn.postings[2].meta


def test_a_split_without_children_stays_uncategorized(importer, path, caplog):
    txn = _by_narration(importer.extract(path, []))["Lost"]

    assert txn.postings[1].account == UNCATEGORIZED
    assert txn.flag == flags.FLAG_WARNING
    assert "The split on 2026-01-12 carries no legs." in caplog.text


def test_a_split_that_does_not_add_up_books_the_rest_uncategorized(tmp_path, importer, caplog):
    short = [(*row[:9], -10.0) if row[0] == "t-big-2" else row for row in TRANSACTIONS]
    txn = _by_narration(importer.extract(_write(tmp_path, short), []))["Big"]

    assert txn.postings[3].account == UNCATEGORIZED
    assert txn.postings[3].units.number == decimal.Decimal("5.00")
    assert "does not add up" in caplog.text


def test_unmapped_and_investment_rows_are_reported(importer, path, caplog):
    caplog.set_level("INFO", logger=see.__name__)
    importer.extract(path, [])

    assert "Skipping 1 transactions of unmapped account Savings." in caplog.text
    assert "Skipping 1 investment transactions of Card." in caplog.text


def test_the_import_id_survives_an_edited_memo(tmp_path, importer, path):
    """It hashes the app's own transaction ID, not the text."""
    before = _by_narration(importer.extract(path, []))["Weekly"].meta["import-id"]
    edited = [(*row[:8], "Edited", *row[9:]) if row[0] == "t-shop" else row for row in TRANSACTIONS]
    after = _by_narration(importer.extract(_write(tmp_path, edited), []))["Edited"]

    assert after.meta["import-id"] == before


def test_reimport_is_idempotent(importer, path):
    existing = importer.extract(path, [])
    again = importer.extract(path, existing)

    importer.deduplicate(again, existing)
    assert all("__duplicate__" in t.meta for t in again)


def test_a_target_in_another_currency_than_the_app_fails(tmp_path, importer):
    accounts = [(*row[:2], "EUR", row[3]) if row[1] == "Card" else row for row in ACCOUNTS]
    with pytest.raises(routing.ConfigError, match="'Card' is in EUR, not CHF"):
        importer.extract(_write(tmp_path, accounts=accounts), [])


def test_extracted_directives_load(tmp_path, importer, path):
    entries = importer.extract(path, [])
    accounts = sorted({p.account for e in entries for p in e.postings})

    ledger = tmp_path / "ledger.beancount"
    with ledger.open("w") as out:
        out.writelines(f"2026-01-01 open {account}\n" for account in accounts)
        printer.print_entries(entries, file=out)

    _loaded, errors, _options = loader.load_file(str(ledger))
    assert errors == []
