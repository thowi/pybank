"""Tests for the DKB importers.

All values are invented.
"""

import datetime
import decimal

import pytest
from beancount import loader
from beancount.core import data, flags
from beancount.parser import printer
from beangulp import extract

from pybank.importer.beancount import UNCATEGORIZED, dkb, identity

# The three fixtures mirror different historical export formats.
# The balances in particular are not interchangeable.
GIRO_LEGACY_CSV = """\
"Kontonummer:";"DE00000000000000000000 / Girokonto";

"Von:";"01.01.2020";
"Bis:";"31.12.2020";
"Kontostand vom 31.12.2020:";"1.982,00 EUR";

"Buchungstag";"Wertstellung";"Buchungstext";"Auftraggeber / Begünstigter";"Verwendungszweck";"Kontonummer";"BLZ";"Betrag (EUR)";"Gläubiger-ID";"Mandatsreferenz";"Kundenreferenz";
"02.01.2020";"02.01.2020";"Lastschrift";"A BOOKSHOP  GMBH";"Invoice    1";"DE00";"BANKDEFF";"-18,00";"";"";"";
"04.01.2020";"04.01.2020";"Gutschrift";"AN EMPLOYER";"Salary";"DE00";"BANKDEFF";"1.000,00";"";"";"";
"""

# Negative balance and the euro sign, both of which only this format uses.
GIRO_2023_CSV = """\
"Girokonto";"DE00000000000000000000"
"Zeitraum:";"01.01.2023 - 31.12.2023"
"Kontostand vom 31.12.2023:";"-982,00 €"
""
"Buchungsdatum";"Wertstellung";"Status";"Zahlungspflichtige*r";"Zahlungsempfänger*in";"Verwendungszweck";"Umsatztyp";"IBAN";"Betrag (€)";"Gläubiger-ID";"Mandatsreferenz";"Kundenreferenz"
"02.01.23";"02.01.23";"Gebucht";"A Person";"BOOKSHOP";"Invoice 1";"Ausgang";"DE00";"-18,00";"";"";""
"04.01.23";"04.01.23";"Gebucht";"AN EMPLOYER";"A Person";"Salary";"Eingang";"DE00";"1.000,00";"";"";""
"""

# `Belegdatum` trails `Wertstellung` on almost every card row. The third row
# is a foreign-currency purchase: `Ursprünglicher Betrag` is filled on those,
# always negative, and only the settled EUR amount is bookable.
CARD_CSV = """\
"Kreditkarte:";"0000********0000";

"Von:";"01.01.2020";
"Bis:";"31.12.2020";
"Saldo:";"22.50 EUR";
"Datum:";"31.12.2020";

"Umsatz abgerechnet und nicht im Saldo enthalten";"Wertstellung";"Belegdatum";"Beschreibung";"Betrag (EUR)";"Ursprünglicher Betrag";
"Ja";"02.01.2020";"31.12.2019";"A BOOKSHOP";"-18,00";"";
"Ja";"04.01.2020";"02.01.2020";"COFFEE BAR";"-4,50";"";
"Ja";"06.01.2020";"03.01.2020";"FOREIGN SHOP";"-9,20";"-10,00 USD";
"""

# Quarterly interest statement. The real ones run to several hundred
# characters, carry `<br />` markup, and book a zero amount.
GIRO_ABSCHLUSS_CSV = """\
"Kontonummer:";"DE00000000000000000000 / Girokonto";

"Von:";"01.01.2021";
"Bis:";"31.03.2021";
"Kontostand vom 31.03.2021:";"-100,00 EUR";

"Buchungstag";"Wertstellung";"Buchungstext";"Auftraggeber / Begünstigter";"Verwendungszweck";"Kontonummer";"BLZ";"Betrag (EUR)";"Gläubiger-ID";"Mandatsreferenz";"Kundenreferenz";
"31.03.2021";"31.03.2021";"Abschluss";"";"Abrechnung 31.03.2021 siehe Anlage<br />Kontostand am 31.03.2021    100,00 -<br />Rechnungsnummer: 00000000-XX000-00000000000";"0000000000";"00000000";"0,00";"";"";"";
"""

# `Tagessaldo` rows become balance assertions rather than transactions, so a
# reader pairing rows with transactions has to skip them or slip a row.
GIRO_TAGESSALDO_CSV = """\
"Kontonummer:";"DE00000000000000000000 / Girokonto";

"Von:";"01.01.2020";
"Bis:";"31.12.2020";
"Kontostand vom 31.12.2020:";"980,00 EUR";

"Buchungstag";"Wertstellung";"Buchungstext";"Auftraggeber / Begünstigter";"Verwendungszweck";"Kontonummer";"BLZ";"Betrag (EUR)";"Gläubiger-ID";"Mandatsreferenz";"Kundenreferenz";
"02.01.2020";"02.01.2020";"Lastschrift";"SHOP A";"Invoice 1";"DE11";"BANKDEFF";"-18,00";"";"";"";
"02.01.2020";"02.01.2020";"";"";"Tagessaldo";"";"";"982,00";"";"";"";
"04.01.2020";"04.01.2020";"Lastschrift";"SHOP B";"Invoice 2";"DE22";"BANKDEFF";"-2,00";"";"";"";
"""

NOT_DKB_CSV = """\
Konto:;Some Account
Datum;Buchungsdetails;Gutschrift in CHF;Lastschrift in CHF
2026-01-05;Groceries;;85.00
"""


def _write(tmp_path, name, content, encoding="cp1252"):
    path = tmp_path / name
    path.write_bytes(content.encode(encoding))
    return str(path)


@pytest.fixture
def checking():
    return dkb.CheckingImporter("Assets:DKB:Checking")


@pytest.fixture
def card():
    return dkb.CreditCardImporter("Liabilities:DKB:Visa")


@pytest.fixture
def legacy_path(tmp_path):
    return _write(tmp_path, "legacy.csv", GIRO_LEGACY_CSV)


@pytest.fixture
def giro_2023_path(tmp_path):
    return _write(tmp_path, "giro2023.csv", GIRO_2023_CSV, "utf-8-sig")


@pytest.fixture
def card_path(tmp_path):
    return _write(tmp_path, "card.csv", CARD_CSV)


@pytest.fixture
def abschluss_path(tmp_path):
    return _write(tmp_path, "abschluss.csv", GIRO_ABSCHLUSS_CSV)


@pytest.fixture
def tagessaldo_path(tmp_path):
    return _write(tmp_path, "tagessaldo.csv", GIRO_TAGESSALDO_CSV)


def _txns(entries):
    return [e for e in entries if isinstance(e, data.Transaction)]


def _balances(entries):
    return [e for e in entries if isinstance(e, data.Balance)]


def _ids(entries):
    return [t.meta[identity.META_KEY] for t in _txns(entries)]


def test_identifies_both_giro_generations(checking, legacy_path, giro_2023_path):
    assert checking.identify(legacy_path)
    assert checking.identify(giro_2023_path)


def test_identifies_the_card_export(card, card_path):
    assert card.identify(card_path)


def test_importers_do_not_claim_each_others_files(
    checking, card, legacy_path, giro_2023_path, card_path
):
    assert not card.identify(legacy_path)
    assert not card.identify(giro_2023_path)
    assert not checking.identify(card_path)


def test_a_foreign_statement_is_not_claimed(checking, card, tmp_path):
    path = _write(tmp_path, "other.csv", NOT_DKB_CSV, "utf-8")
    assert not checking.identify(path)
    assert not card.identify(path)


def test_no_account_number_has_to_be_configured():
    """The identifier is read from the file, so the constructor takes none."""
    importer = dkb.CheckingImporter("Assets:DKB:Checking")
    assert importer.account("ignored.csv") == "Assets:DKB:Checking"


@pytest.mark.parametrize("fixture", ["legacy_path", "giro_2023_path"])
def test_giro_transactions_are_completed(checking, fixture, request):
    txns = _txns(checking.extract(request.getfixturevalue(fixture), []))

    assert len(txns) == 2
    for txn in txns:
        assert txn.flag == flags.FLAG_WARNING
        assert len(txn.postings) == 2
        assert txn.postings[0].account == "Assets:DKB:Checking"
        assert txn.postings[1].account == UNCATEGORIZED
        assert txn.postings[1].units is None


def test_amounts_keep_their_sign(checking, legacy_path):
    debit, credit = _txns(checking.extract(legacy_path, []))
    assert debit.postings[0].units.number < 0
    assert credit.postings[0].units.number > 0
    assert debit.postings[0].units.currency == "EUR"


def test_a_balance_assertion_is_emitted(checking, legacy_path):
    (balance,) = _balances(checking.extract(legacy_path, []))

    assert balance.account == "Assets:DKB:Checking"
    assert balance.amount.number == decimal.Decimal("1982.00"), "German thousands dot"
    assert balance.date == datetime.date(2021, 1, 1), (
        "assertions evaluate at the start of their date"
    )


def test_the_current_giro_balance_is_signed_and_in_euro_signs(checking, giro_2023_path):
    (balance,) = _balances(checking.extract(giro_2023_path, []))
    assert balance.amount.number == decimal.Decimal("-982.00")
    assert balance.amount.currency == "EUR"


def test_the_card_balance_is_read_as_en_us(card, card_path):
    """`Saldo:` is dot-decimal. Read as German, 22.50 would become 2250."""
    (balance,) = _balances(card.extract(card_path, []))

    assert balance.amount.number == decimal.Decimal("22.50")
    assert balance.date == datetime.date(2021, 1, 1)


def test_a_foreign_currency_purchase_books_the_settled_amount(card, card_path):
    """Only the EUR charge is bookable. The original rides along as metadata."""
    foreign = _txns(card.extract(card_path, []))[2]

    assert foreign.postings[0].units.number == decimal.Decimal("-9.20")
    assert foreign.postings[0].units.currency == "EUR"


def test_an_interest_statement_row_is_imported(checking, abschluss_path):
    """Zero amount, `<br />` markup, and a narration far longer than the rest."""
    (txn,) = _txns(checking.extract(abschluss_path, []))

    assert txn.postings[0].units.number == decimal.Decimal("0.00")
    assert txn.meta[identity.META_KEY]


def test_padding_and_shouting_are_normalized(checking, legacy_path):
    """DKB shouts a third of its payees and pads the rest."""
    debit, _credit = _txns(checking.extract(legacy_path, []))

    assert debit.payee == "A Bookshop Gmbh"
    assert debit.narration == "Lastschrift Invoice 1"


def test_import_ids_survive_repadded_text(checking, legacy_path, tmp_path):
    """The same statement re-exported with tidier spacing is not a new import."""
    repadded = GIRO_LEGACY_CSV.replace("A BOOKSHOP  GMBH", "A Bookshop Gmbh")
    repadded = repadded.replace("Invoice    1", "Invoice 1")

    tidied = _write(tmp_path, "repadded.csv", repadded)

    assert _ids(checking.extract(tidied, [])) == _ids(checking.extract(legacy_path, []))


def test_the_foreign_amount_is_kept(card, card_path):
    """`beancount-dkb` drops `Ursprünglicher Betrag`, so we carry it ourselves."""
    plain, _coffee, foreign = _txns(card.extract(card_path, []))

    assert foreign.meta["original-amount"] == "-10,00 USD"
    assert "original-amount" not in plain.meta, "column is empty on domestic rows"


def test_the_card_receipt_date_is_kept(card, card_path):
    """`Belegdatum` is the purchase. The transaction is dated `Wertstellung`."""
    txn, *_ = _txns(card.extract(card_path, []))

    assert txn.date == datetime.date(2020, 1, 2)
    assert txn.meta["receipt-date"] == "31.12.2019"


@pytest.mark.parametrize("fixture", ["legacy_path", "giro_2023_path"])
def test_the_counterparty_account_is_kept(checking, fixture, request):
    """Both generations name it, under different column names."""
    txns = _txns(checking.extract(request.getfixturevalue(fixture), []))
    assert [t.meta["counterparty-account"] for t in txns] == ["DE00", "DE00"]


def test_the_card_carries_no_counterparty_account(card, card_path):
    """Card exports have no such column, and an absent key beats an empty one."""
    assert all("counterparty-account" not in t.meta for t in _txns(card.extract(card_path, [])))


def test_a_daily_balance_row_does_not_shift_the_metadata(checking, tagessaldo_path):
    """It becomes a balance, so the rows after it still pair with their own."""
    entries = checking.extract(tagessaldo_path, [])

    assert len(_balances(entries)) == 2, "the daily one and the closing one"
    assert [t.meta["counterparty-account"] for t in _txns(entries)] == ["DE11", "DE22"]


def test_every_transaction_gets_an_import_id(checking, legacy_path):
    ids = _ids(checking.extract(legacy_path, []))
    assert len(set(ids)) == len(ids)
    assert all(i.startswith(identity.VERSION + ":") for i in ids)


def test_import_ids_are_stable_across_runs(checking, legacy_path):
    assert _ids(checking.extract(legacy_path, [])) == _ids(checking.extract(legacy_path, []))


def test_the_two_giro_generations_do_not_share_ids(checking, legacy_path, giro_2023_path):
    """Different column semantics, and the archive ranges never overlap."""
    legacy = set(_ids(checking.extract(legacy_path, [])))
    current = set(_ids(checking.extract(giro_2023_path, [])))
    assert not legacy & current


def test_reimport_is_idempotent(checking, legacy_path):
    existing = _txns(checking.extract(legacy_path, []))
    again = checking.extract(legacy_path, existing)
    checking.deduplicate(again, existing)

    assert all(t.meta.get(extract.DUPLICATE) for t in _txns(again))


def test_extracted_directives_load(tmp_path, checking, legacy_path):
    """The real acceptance test: what comes out has to parse and balance."""
    entries = checking.extract(legacy_path, [])

    ledger = tmp_path / "ledger.beancount"
    with ledger.open("w") as out:
        out.write("2019-01-01 open Assets:DKB:Checking EUR\n")
        out.write("2019-01-01 open Expenses:Uncategorized\n")
        out.write("2019-01-01 open Equity:Opening-Balances\n")
        out.write('2020-01-01 * "Opening"\n')
        out.write("  Assets:DKB:Checking   1000.00 EUR\n")
        out.write("  Equity:Opening-Balances\n")
        printer.print_entries(entries, file=out)

    _loaded, errors, _options = loader.load_file(str(ledger))
    assert errors == []


def test_card_transactions_are_completed(card, card_path):
    txns = _txns(card.extract(card_path, []))

    assert len(txns) == 3
    for txn in txns:
        assert txn.flag == flags.FLAG_WARNING
        assert txn.postings[0].account == "Liabilities:DKB:Visa"
        assert txn.postings[1].account == UNCATEGORIZED
