"""All values here are invented. Never derive a fixture from a real export."""

import datetime
import decimal

import pytest
from beancount import loader
from beancount.core import data
from beancount.parser import printer
from beangulp import extract

from pybank.importer.beancount import postfinance, routing

CHECKING = "Assets:PostFinance:Checking"
CARD = "Liabilities:PostFinance:Visa:Person"
CARD_OTHER = "Liabilities:PostFinance:Visa:Other"

# Checking export: UTF-8 BOM, German dates, no balance column.
CHECKING_CSV = """\
Datum von:;="01.01.2026"
Datum bis:;="31.01.2026"
Konto:;="CH00 0000 0000 0000 0000 0"
Währung:;="CHF"

Datum;Bewegungstyp;Avisierungstext;Gutschrift in CHF;Lastschrift in CHF
05.01.2026;Zahlung;GROCER LTD;;42.50
07.01.2026;Gutschrift;SALARY PAYMENT;5'000.00;
09.01.2026;Zahlung;COFFEE BAR;;4.50
09.01.2026;Zahlung;COFFEE BAR;;4.50

Disclaimer:
Some trailing prose that is not a transaction.
"""

# Checking export: cp1252, ISO dates, running balance.
CHECKING_WITH_BALANCE_CSV = """\
Datum von:;2025-11-01
Datum bis:;2025-11-30
Konto:;CH00 0000 0000 0000 0000 0
Währung:;CHF

Buchungsdatum;Avisierungstext;Gutschrift in CHF;Lastschrift in CHF;Valuta;Saldo in CHF
2025-11-03;GROCER LTD;;20.00;2025-11-03;980.00
2025-11-10;REFUND;30.00;;2025-11-10;1010.00
Total;;;;;
"""

# Card export: no balance anywhere, booking and purchase dates.
CARD_CSV = """\
Kartenkonto:;="0000 0000 0000 0000"
Karte:;="XXXXXXXXXXXX0000"
Karteninhaber:;="A Person"

Rechnungsperiode;Buchungsdatum;Einkaufsdatum;Buchungsdetails;Gutschrift in CHF;Lastschrift in CHF;Label;Kategorie
08.01.2026 - 07.02.2026;12.01.2026;11.01.2026;BOOKSHOP;;18.00;Gift;Shopping
08.01.2026 - 07.02.2026;20.01.2026;19.01.2026;RETURN BOOKSHOP;18.00;;;Shopping
"""

# Checking export that carries Label and Kategorie.
CHECKING_LABELLED_CSV = """\
Datum von:;="01.03.2026"
Datum bis:;="31.03.2026"
Konto:;="CH00 0000 0000 0000 0000 0"
Währung:;="CHF"

Datum;Bewegungstyp;Avisierungstext;Gutschrift in CHF;Lastschrift in CHF;Label;Kategorie
04.03.2026;Zahlung;GROCER LTD;;12.00;Weekly;Groceries
"""

# Card export: cp1252, ISO dates, and a header that declares a Betrag column
# only the Total row fills in.
CARD_TERSE_CSV = """\
Kartenkonto:;0000 0000 0000 0000
Karte:;XXXXXXXXXXXX0000
Karteninhaber:;A Person

Datum;Bezeichnung;Gutschrift in CHF;Lastschrift in CHF;Betrag in CHF
2019-02-14;BÜCHER;;18.00
2019-02-16;RETURN BOOKSHOP;18.00;
2019-02-16;Total;;;-18.00

Disclaimer:
Some trailing prose that is not a transaction.
"""

# A second card on the same card account, with the masked number written
# differently. The fragment has to match either shape.
CARD_SPACED_CSV = """\
Kartenkonto:;="0000 0000 0000 0000"
Karte:;="XXXX XXXX XXXX 1111 PostFinance Visa Gold Card "
Karteninhaber:;="B Person"

Datum;Buchungsdetails;Gutschrift in CHF;Lastschrift in CHF
2023-02-14;BOOKSHOP;;18.00
"""

# Card export without the billing period.
CARD_DETAILS_CSV = """\
Kartenkonto:;="0000 0000 0000 0000"
Karte:;="XXXXXXXXXXXX0000"
Karteninhaber:;="A Person"

Datum;Buchungsdetails;Gutschrift in CHF;Lastschrift in CHF
2023-02-14;BOOKSHOP;;18.00
2023-02-16;RETURN BOOKSHOP;18.00;
"""


def _write(tmp_path, name, content, encoding="utf-8-sig"):
    path = tmp_path / name
    path.write_bytes(content.encode(encoding))
    return str(path)


@pytest.fixture
def checking():
    return postfinance.CheckingImporter({"CH00": CHECKING})


@pytest.fixture
def card():
    return postfinance.CreditCardImporter({"0000": CARD, "1111": CARD_OTHER})


@pytest.fixture
def checking_path(tmp_path):
    return _write(tmp_path, "checking.csv", CHECKING_CSV)


@pytest.fixture
def balance_path(tmp_path):
    return _write(tmp_path, "balance.csv", CHECKING_WITH_BALANCE_CSV, "cp1252")


@pytest.fixture
def card_path(tmp_path):
    return _write(tmp_path, "card.csv", CARD_CSV)


def _txns(entries):
    return [e for e in entries if isinstance(e, data.Transaction)]


def _balances(entries):
    return [e for e in entries if isinstance(e, data.Balance)]


def test_identify_checking(checking, card, checking_path):
    assert checking.identify(checking_path)
    assert not card.identify(checking_path)


def test_identify_card(checking, card, card_path):
    assert card.identify(card_path)
    assert not checking.identify(card_path)


def test_each_card_books_into_its_own_account(tmp_path, card, card_path):
    spaced_path = _write(tmp_path, "spaced.csv", CARD_SPACED_CSV)

    assert card.account(card_path) == CARD
    assert card.account(spaced_path) == CARD_OTHER


def test_a_card_with_no_account_configured_names_the_card(card_path):
    importer = postfinance.CreditCardImporter({"9999": CARD})

    # The file is still ours. Only the config falls short, so say which card.
    assert importer.identify(card_path)
    with pytest.raises(routing.ConfigError, match="0000"):
        importer.account(card_path)


def test_card_fragments_that_disagree_about_the_account_are_reported(card_path):
    importer = postfinance.CreditCardImporter({"000": CARD, "0000": CARD_OTHER})

    with pytest.raises(routing.ConfigError, match=r"postfinance\.card"):
        importer.account(card_path)


def test_identify_rejects_other_files(tmp_path, checking):
    assert not checking.identify(_write(tmp_path, "notes.txt", "hello"))
    assert not checking.identify(_write(tmp_path, "empty.csv", "a;b\n"))


def test_identify_reads_cp1252(checking, balance_path):
    assert checking.identify(balance_path)


def test_extract_signs_and_amounts(checking, checking_path):
    txns = _txns(checking.extract(checking_path, []))

    assert [t.date for t in txns] == [
        datetime.date(2026, 1, 5),
        datetime.date(2026, 1, 7),
        datetime.date(2026, 1, 9),
        datetime.date(2026, 1, 9),
    ]
    numbers = [t.postings[0].units.number for t in txns]
    assert numbers == [
        decimal.Decimal("-42.50"),
        decimal.Decimal("5000.00"),
        decimal.Decimal("-4.50"),
        decimal.Decimal("-4.50"),
    ]
    assert {t.postings[0].units.currency for t in txns} == {"CHF"}


def test_extract_posting_shape(checking, checking_path):
    txn = _txns(checking.extract(checking_path, []))[0]

    assert txn.flag == "!"
    assert txn.postings[0].account == CHECKING
    assert txn.postings[1].account == postfinance.UNCATEGORIZED
    assert txn.postings[1].units is None, "contra leg auto-balances"


def test_extract_normalizes_the_memo(checking, checking_path):
    txn = _txns(checking.extract(checking_path, []))[0]
    assert txn.narration == "Grocer Ltd"
    assert txn.payee is None, "PostFinance gives one free-text field only"


def test_extract_skips_the_total_row(checking, balance_path):
    assert len(_txns(checking.extract(balance_path, []))) == 2


def test_a_newest_first_statement_asserts_its_newest_saldo(tmp_path, checking):
    newest_first = CHECKING_WITH_BALANCE_CSV.replace(
        "2025-11-03;GROCER LTD;;20.00;2025-11-03;980.00\n"
        "2025-11-10;REFUND;30.00;;2025-11-10;1010.00\n",
        "2025-11-10;REFUND;30.00;;2025-11-10;1010.00\n"
        "2025-11-03;GROCER LTD;;20.00;2025-11-03;980.00\n",
    )
    path = _write(tmp_path, "newest_first.csv", newest_first, "cp1252")

    (balance,) = _balances(checking.extract(path, []))

    assert balance.date == datetime.date(2025, 11, 11)
    assert balance.amount.number == decimal.Decimal("1010.00")


def test_balance_assertion_is_dated_the_following_day(checking, balance_path):
    (balance,) = _balances(checking.extract(balance_path, []))

    assert balance.date == datetime.date(2025, 11, 11), (
        "assertions evaluate at the start of their date"
    )
    assert balance.account == CHECKING
    assert balance.amount.number == decimal.Decimal("1010.00")


def test_a_one_day_statement_newest_first_asserts_its_newest_saldo(tmp_path, checking):
    """With one date, the running balance tells the order of the rows."""
    newest_first = CHECKING_WITH_BALANCE_CSV.replace(
        "2025-11-03;GROCER LTD;;20.00;2025-11-03;980.00\n"
        "2025-11-10;REFUND;30.00;;2025-11-10;1010.00\n",
        "2025-11-10;GROCER LTD;;20.00;2025-11-10;960.00\n"
        "2025-11-10;REFUND;30.00;;2025-11-10;980.00\n",
    )
    path = _write(tmp_path, "newest_first.csv", newest_first, "cp1252")

    (balance,) = _balances(checking.extract(path, []))

    assert balance.amount.number == decimal.Decimal("960.00")


def test_no_balance_column_yields_no_assertion(checking, card, checking_path, card_path):
    assert _balances(checking.extract(checking_path, [])) == []
    assert _balances(card.extract(card_path, [])) == []


def test_card_uses_the_booking_date(card, card_path):
    txns = _txns(card.extract(card_path, []))
    assert [t.date for t in txns] == [
        datetime.date(2026, 1, 12),
        datetime.date(2026, 1, 20),
    ]


def test_identical_rows_stay_distinct(checking, checking_path):
    txns = _txns(checking.extract(checking_path, []))
    coffees = [t for t in txns if t.narration == "Coffee Bar"]

    assert len(coffees) == 2, "two coffees on one day are legitimate"
    ids = {t.meta["import-id"] for t in coffees}
    assert len(ids) == 2


def test_import_ids_are_stable_across_runs(checking, checking_path):
    first = _txns(checking.extract(checking_path, []))
    second = _txns(checking.extract(checking_path, []))
    assert [t.meta["import-id"] for t in first] == [t.meta["import-id"] for t in second]


def test_import_ids_survive_a_reformatted_amount(tmp_path, checking, checking_path):
    """`42.5` and `42.50` are the same transaction, so the same id."""
    reformatted = _write(tmp_path, "reformatted.csv", CHECKING_CSV.replace(";42.50", ";42.5"))

    first = _txns(checking.extract(checking_path, []))[0]
    second = _txns(checking.extract(reformatted, []))[0]
    assert first.meta["import-id"] == second.meta["import-id"]


def test_extracted_directives_load(tmp_path, checking, balance_path):
    """The real acceptance test: what comes out has to parse and balance."""
    entries = checking.extract(balance_path, [])

    ledger = tmp_path / "ledger.beancount"
    with ledger.open("w") as out:
        out.write("2025-01-01 open Assets:PostFinance:Checking CHF\n")
        out.write("2025-01-01 open Expenses:Uncategorized\n")
        out.write('2025-11-01 * "Opening"\n')
        out.write("  Assets:PostFinance:Checking   1000.00 CHF\n")
        out.write("  Equity:Opening-Balances\n")
        out.write("2025-01-01 open Equity:Opening-Balances\n")
        printer.print_entries(entries, file=out)

    _loaded, errors, _options = loader.load_file(str(ledger))
    assert errors == []


def test_terse_card_variant(tmp_path, card):
    """ISO dates, cp1252, and a wide Total row."""
    path = _write(tmp_path, "terse.csv", CARD_TERSE_CSV, "cp1252")
    assert card.identify(path)

    txns = _txns(card.extract(path, []))
    assert [t.narration for t in txns] == ["Bücher", "Return Bookshop"]
    assert [t.postings[0].units.number for t in txns] == [
        decimal.Decimal("-18.00"),
        decimal.Decimal("18.00"),
    ]
    assert [t.date for t in txns] == [
        datetime.date(2019, 2, 14),
        datetime.date(2019, 2, 16),
    ]


def test_card_details_variant(tmp_path, card):
    path = _write(tmp_path, "details.csv", CARD_DETAILS_CSV)
    assert card.identify(path)

    txns = _txns(card.extract(path, []))
    assert [t.narration for t in txns] == ["Bookshop", "Return Bookshop"]
    assert [t.postings[0].units.number for t in txns] == [
        decimal.Decimal("-18.00"),
        decimal.Decimal("18.00"),
    ]


def test_labelled_checking_variant(tmp_path, checking):
    path = _write(tmp_path, "labelled.csv", CHECKING_LABELLED_CSV)
    assert checking.identify(path)

    (txn,) = _txns(checking.extract(path, []))
    assert txn.date == datetime.date(2026, 3, 4)
    assert txn.postings[0].units.number == decimal.Decimal("-12.00")


def test_bank_category_and_label_are_kept_as_metadata(tmp_path, card, checking, card_path):
    card_txn = _txns(card.extract(card_path, []))[0]
    assert card_txn.meta["bank-category"] == "Shopping"
    assert card_txn.meta["bank-label"] == "Gift"

    path = _write(tmp_path, "labelled.csv", CHECKING_LABELLED_CSV)
    (checking_txn,) = _txns(checking.extract(path, []))
    assert checking_txn.meta["bank-category"] == "Groceries"
    assert checking_txn.meta["bank-label"] == "Weekly"


def test_the_card_receipt_date_is_kept(card, card_path):
    """`Einkaufsdatum` is the purchase, `Buchungsdatum` dates the entry."""
    txn = _txns(card.extract(card_path, []))[0]

    assert txn.date == datetime.date(2026, 1, 12)
    assert txn.meta["receipt-date"] == "11.01.2026"


def test_the_receipt_date_is_absent_when_the_export_has_none(checking, checking_path):
    """Only the card export splits the two dates. Checking has one column."""
    txn = _txns(checking.extract(checking_path, []))[0]
    assert "receipt-date" not in txn.meta


def test_the_receipt_date_does_not_affect_the_import_id(tmp_path, card):
    """It rides along as metadata, so it stays out of the hash like the rest."""
    moved = _write(tmp_path, "moved.csv", CARD_CSV.replace(";11.01.2026;", ";10.01.2026;"))

    first = _txns(card.extract(_write(tmp_path, "card.csv", CARD_CSV), []))[0]
    second = _txns(card.extract(moved, []))[0]
    assert first.meta["import-id"] == second.meta["import-id"]


def test_bank_category_is_absent_when_the_export_has_none(checking, checking_path):
    txn = _txns(checking.extract(checking_path, []))[0]
    assert "bank-category" not in txn.meta
    assert "bank-label" not in txn.meta


def test_bank_category_does_not_affect_the_import_id(tmp_path, checking):
    """The bank may relabel a transaction. That must not re-import it."""
    path = _write(tmp_path, "labelled.csv", CHECKING_LABELLED_CSV)
    relabelled = _write(
        tmp_path,
        "relabelled.csv",
        CHECKING_LABELLED_CSV.replace(";Weekly;Groceries", ";Other;Shopping"),
    )

    first = _txns(checking.extract(path, []))[0]
    second = _txns(checking.extract(relabelled, []))[0]
    assert first.meta["import-id"] == second.meta["import-id"]


def test_reimport_is_idempotent(checking, balance_path):
    existing = checking.extract(balance_path, [])
    again = checking.extract(balance_path, existing)

    checking.deduplicate(again, existing)
    assert _balances(again)
    assert all(extract.DUPLICATE in e.meta for e in again)
