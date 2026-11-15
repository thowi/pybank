"""All values here are invented. Never derive a fixture from a real export."""

import datetime
import decimal

import pytest
from beancount import loader
from beancount.core import data, flags
from beancount.parser import printer

from pybank.importer.beancount import IN_TRANSIT, OPENING_BALANCES, UNCATEGORIZED, qif

CHECKING = "Assets:Bank:Checking"
CARD = "Liabilities:Bank:Card"

TARGETS = {
    "Checking": qif.Target(CHECKING, "CHF"),
    "Card": qif.Target(CARD, "CHF"),
}

# The whole shape of the export: An AutoSwitch account list, a category list
# declaring income and expense, then one section per account. The investment
# account and the unmapped savings account must both be skipped.
EXPORT_QIF = """\
!Option:AutoSwitch
!Account
NChecking
DEveryday
TBank
B1000.00
^
NCard
DPlastic
TCCard
B-200.00
^
NSavings
DPut away
TBank
B5000.00
^
NBrokerage
DShares
TPort
B0.00
^
!Clear:AutoSwitch
!Type:Cat
NGroceries
DFood
E
^
NAuto & Transport
DGetting about
E
^
NAuto & Transport:Fuel
DPetrol
E
^
NSalary
DPay
I
T
^
!Account
NChecking
TBank
^
!Type:Bank
D05.01.2026
T-42.50
CX
N1
MGrocer Ltd
LGroceries
^
D07.01.2026
T5000.00
CX
MMonthly pay
PEmployer
LSalary
^
D09.01.2026
T-100.00
C*
MMoving money
L[Card]
^
D11.01.2026
T-7.25
CX
MNo label here
^
D12.01.2026
T-30.00
CX
MSplit with no legs
LSplit
^
D13.01.2026
T-60.00
CX
MBig shop
LSplit
SGroceries
EFood part
$-45.00
SAuto & Transport:Fuel
EPetrol part
$-15.00
^
!Account
NSavings
TBank
^
!Type:Bank
D14.01.2026
T-11.00
MShould be skipped
LGroceries
^
!Account
NCard
TCCard
^
!Type:CCard
D20.01.2026
T-18.00
CX
MBOOKSHOP
LUnheard Of
^
D21.01.2026
T100.00
CX
MPaying the card
L[Checking]
^
!Account
NBrokerage
TPort
^
!Type:Invst
D22.01.2026
NBuy
YSome Share
I10.00
Q5
T50.00
^
!Type:Prices
"ABC",10.00,"22.01.2026"
^
"""

# A single-account export, which QIF is also used for. No account list, so it
# is a different importer's file.
SINGLE_ACCOUNT_QIF = """\
!Type:Bank
D05.01.2026
T-42.50
MGrocer Ltd
^
"""


def _write(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


@pytest.fixture
def importer():
    return qif.Importer(TARGETS)


@pytest.fixture
def path(tmp_path):
    return _write(tmp_path, "all-accounts.qif", EXPORT_QIF)


def _txns(entries):
    return [e for e in entries if isinstance(e, data.Transaction)]


def _by_narration(entries):
    return {t.narration: t for t in _txns(entries)}


def test_identify_accepts_the_all_accounts_export(importer, path):
    assert importer.identify(path)


def test_identify_rejects_a_per_account_qif(tmp_path, importer):
    """Without an account list a QIF belongs to whoever exported it."""
    assert not importer.identify(_write(tmp_path, "one.qif", SINGLE_ACCOUNT_QIF))


def test_identify_rejects_other_files(tmp_path, importer):
    assert not importer.identify(_write(tmp_path, "notes.txt", EXPORT_QIF))
    assert not importer.identify(_write(tmp_path, "empty.qif", ""))
    assert not importer.identify(str(tmp_path / "missing.qif"))


def test_account_names_an_archive_directory(importer, path):
    """No single account owns the file. beangulp still wants one name."""
    assert importer.account(path) == CHECKING


def test_extract_reads_only_the_mapped_bank_and_card_accounts(importer, path):
    """Savings is unmapped, Brokerage is an investment account."""
    txns = _txns(importer.extract(path, []))

    assert [t.narration for t in txns] == [
        "Grocer Ltd",
        "Monthly pay",
        "Moving money",
        "No label here",
        "Split with no legs",
        "Big shop",
        "Bookshop",
        "Paying the card",
    ]


def test_extract_dates_amounts_and_currency(importer, path):
    txns = _by_narration(importer.extract(path, []))

    grocer = txns["Grocer Ltd"]
    assert grocer.date == datetime.date(2026, 1, 5)
    assert grocer.postings[0].account == CHECKING
    assert grocer.postings[0].units == data.Amount(decimal.Decimal("-42.50"), "CHF")

    assert txns["Monthly pay"].postings[0].units.number == decimal.Decimal("5000.00")
    assert txns["Bookshop"].postings[0].account == CARD


def test_extract_reads_a_thousands_separator(tmp_path, importer):
    content = EXPORT_QIF.replace("T5000.00", "T5,000.00")
    txns = _by_narration(importer.extract(_write(tmp_path, "grouped.qif", content), []))

    assert txns["Monthly pay"].postings[0].units.number == decimal.Decimal("5000.00")


def test_extract_normalizes_payee_and_memo(importer, path):
    txns = _by_narration(importer.extract(path, []))

    assert txns["Monthly pay"].payee == "Employer"
    assert txns["Grocer Ltd"].payee is None
    assert "Bookshop" in txns, "an ALL CAPS memo is capitalized like elsewhere"


def test_a_category_becomes_an_expense_or_income_account(importer, path):
    """The export declares the direction of each category. Nothing guesses."""
    txns = _by_narration(importer.extract(path, []))

    assert txns["Grocer Ltd"].postings[1].account == "Expenses:Groceries"
    assert txns["Monthly pay"].postings[1].account == "Income:Salary"


def test_a_category_name_is_sanitized_into_components(importer, path):
    """`Auto & Transport:Fuel` is two components, and `&` is not a letter."""
    split = _by_narration(importer.extract(path, []))["Big shop"]
    assert split.postings[2].account == "Expenses:Auto-Transport:Fuel"


@pytest.mark.parametrize(
    ("label", "component"),
    [("Gebühren", "Gebühren"), ("ärzte", "Ärzte"), ("食品", "X食品"), ("m² & ½", "M")],
)
def test_a_category_keeps_letters_of_any_script(label, component):
    assert qif._component(label) == component
    entries, errors, _ = loader.load_string(f"2020-01-01 open Expenses:{component}\n")
    assert entries and not errors


def test_an_undeclared_category_falls_back_to_an_expense(importer, path):
    txn = _by_narration(importer.extract(path, []))["Bookshop"]
    assert txn.postings[1].account == "Expenses:Unheard-Of"


def test_a_category_override_wins(path):
    overrides = {"Unheard Of": "Assets:Elsewhere", "Groceries": "Expenses:Food"}
    txns = _by_narration(qif.Importer(TARGETS, overrides).extract(path, []))

    assert txns["Bookshop"].postings[1].account == "Assets:Elsewhere"
    assert txns["Grocer Ltd"].postings[1].account == "Expenses:Food"


def test_both_legs_of_a_transfer_go_through_the_clearing_account(importer, path):
    """One file holds both legs, so they meet there and cancel out."""
    txns = _by_narration(importer.extract(path, []))

    out = txns["Moving money"]
    back = txns["Paying the card"]
    assert out.postings[1].account == IN_TRANSIT
    assert back.postings[1].account == IN_TRANSIT
    assert out.postings[1].units.number == -back.postings[1].units.number


def test_a_transfer_from_the_account_itself_is_its_opening_balance(tmp_path, importer):
    opening = "!Type:Bank\nD01.01.2026\nT1000.00\nPStarting Balance\nL[Checking]\n^\n"
    content = EXPORT_QIF.replace("!Type:Bank\n", opening, 1)
    txns = _txns(importer.extract(_write(tmp_path, "opening.qif", content), []))

    assert txns[0].payee == "Starting Balance"
    assert txns[0].postings[1].account == OPENING_BALANCES


def test_any_other_transfer_from_the_account_itself_is_a_transfer(tmp_path, importer):
    bill = "!Type:Bank\nD10.01.2026\nT-30.00\nMCard bill\nL[Checking]\n^\n"
    content = EXPORT_QIF.replace("!Type:Bank\n", bill, 1)
    txns = _by_narration(importer.extract(_write(tmp_path, "bill.qif", content), []))

    assert txns["Card bill"].postings[1].account == IN_TRANSIT


def test_the_split_marker_never_becomes_a_category(importer, path):
    """`LSplit` is the exporter saying "see the legs", not a category name."""
    entries = importer.extract(path, [])
    txns = _by_narration(entries)

    assert txns["Big shop"].postings[1].account == "Expenses:Groceries"
    assert all("Split" not in p.account for t in _txns(entries) for p in t.postings)


def test_a_split_that_lost_its_legs_stays_uncategorized(importer, path, caplog):
    """The marker can arrive with no legs, and then the breakdown is gone."""
    txn = _by_narration(importer.extract(path, []))["Split with no legs"]

    assert len(txn.postings) == 2
    assert txn.postings[1].account == UNCATEGORIZED
    assert txn.flag == flags.FLAG_WARNING
    assert txn.postings[1].meta is None, "there is no label worth keeping"
    assert "The split on 12.01.2026 carries no legs." in caplog.text


def test_the_raw_category_rides_along_on_the_posting(importer, path):
    """The mapping will change. This is what a remapping remaps from."""
    txns = _by_narration(importer.extract(path, []))

    assert txns["Grocer Ltd"].postings[1].meta["qif-category"] == "Groceries"
    assert txns["Bookshop"].postings[1].meta["qif-category"] == "Unheard Of"

    split = txns["Big shop"]
    assert split.postings[1].meta["qif-category"] == "Groceries"
    assert split.postings[2].meta["qif-category"] == "Auto & Transport:Fuel"


def test_the_raw_transfer_target_rides_along_on_the_posting(importer, path):
    """Which account the other leg belongs to is what pairs them up later."""
    txn = _by_narration(importer.extract(path, []))["Moving money"]

    assert txn.postings[1].meta["qif-transfer"] == "Card"
    assert "qif-category" not in txn.postings[1].meta, "a transfer is not a category"


def test_a_missing_category_stays_uncategorized_and_flagged(importer, path):
    txn = _by_narration(importer.extract(path, []))["No label here"]

    assert txn.postings[1].account == UNCATEGORIZED
    assert txn.flag == flags.FLAG_WARNING


def test_a_hand_assigned_category_is_marked_as_such(importer, path):
    """`qif` provenance separates a real label from a later rule's guess."""
    txns = _by_narration(importer.extract(path, []))

    assert txns["Grocer Ltd"].meta["category-source"] == "qif"
    assert txns["Grocer Ltd"].flag == flags.FLAG_OKAY
    assert "category-source" not in txns["No label here"].meta


def test_a_transfer_carries_no_category_provenance(importer, path):
    """A transfer is structural. Nobody categorized it."""
    txn = _by_narration(importer.extract(path, []))["Moving money"]

    assert txn.flag == flags.FLAG_OKAY
    assert "category-source" not in txn.meta


def test_a_split_becomes_one_posting_per_leg(importer, path):
    txn = _by_narration(importer.extract(path, []))["Big shop"]

    assert len(txn.postings) == 3
    assert txn.postings[0].units.number == decimal.Decimal("-60.00")
    assert [p.units.number for p in txn.postings[1:]] == [
        decimal.Decimal("45.00"),
        decimal.Decimal("15.00"),
    ]
    assert sum(p.units.number for p in txn.postings) == 0


def test_a_split_keeps_the_memo_of_each_leg(importer, path):
    txn = _by_narration(importer.extract(path, []))["Big shop"]

    assert txn.postings[1].meta["split-memo"] == "Food part"
    assert txn.postings[2].meta["split-memo"] == "Petrol part"
    assert txn.postings[0].meta is None, "the account leg carries none of this"


def test_import_ids_are_unique(importer, path):
    txns = _txns(importer.extract(path, []))
    ids = [t.meta["import-id"] for t in txns]

    assert len(set(ids)) == len(ids)


def test_the_import_id_does_not_depend_on_the_category(tmp_path, importer):
    """Remapping an old label must not re-import the transaction."""
    relabelled = _write(tmp_path, "b.qif", EXPORT_QIF.replace("LGroceries", "LSalary", 1))

    first = _by_narration(importer.extract(_write(tmp_path, "a.qif", EXPORT_QIF), []))
    second = _by_narration(importer.extract(relabelled, []))
    assert first["Grocer Ltd"].meta["import-id"] == second["Grocer Ltd"].meta["import-id"]


def test_reimport_is_idempotent(importer, path):
    existing = _txns(importer.extract(path, []))
    again = importer.extract(path, existing)

    importer.deduplicate(again, existing)
    assert all("__duplicate__" in t.meta for t in _txns(again))


def test_extracted_directives_load(tmp_path, importer, path):
    """The real acceptance test: What comes out has to parse and balance."""
    entries = importer.extract(path, [])

    ledger = tmp_path / "ledger.beancount"
    with ledger.open("w") as out:
        out.write("2026-01-01 open Assets:Bank:Checking CHF\n")
        out.write("2026-01-01 open Liabilities:Bank:Card CHF\n")
        out.write("2026-01-01 open Assets:Transfers:InTransit\n")
        out.write("2026-01-01 open Expenses:Uncategorized\n")
        out.write("2026-01-01 open Expenses:Groceries\n")
        out.write("2026-01-01 open Expenses:Auto-Transport:Fuel\n")
        out.write("2026-01-01 open Expenses:Unheard-Of\n")
        out.write("2026-01-01 open Income:Salary\n")
        printer.print_entries(entries, file=out)

    _loaded, errors, _options = loader.load_file(str(ledger))
    assert errors == []


def test_the_clearing_account_balances_across_the_export(importer, path):
    """A transfer whose two legs met nets to zero. The rest is the report."""
    postings = [p for t in _txns(importer.extract(path, [])) for p in t.postings]
    in_transit = [p for p in postings if p.account == IN_TRANSIT]

    assert len(in_transit) == 2
    assert sum(p.units.number for p in in_transit) == 0


def test_a_split_that_does_not_add_up_books_the_rest_uncategorized(tmp_path, importer, caplog):
    """The transaction still balances, and the gap stays visible."""
    short = EXPORT_QIF.replace("$-15.00", "$-10.00")
    txn = _by_narration(importer.extract(_write(tmp_path, "short.qif", short), []))["Big shop"]

    assert txn.postings[3].account == UNCATEGORIZED
    assert txn.postings[3].units.number == decimal.Decimal("5.00")
    assert sum(p.units.number for p in txn.postings) == 0
    assert txn.flag == flags.FLAG_WARNING
    assert "does not add up" in caplog.text


def test_a_record_without_an_amount_is_skipped(tmp_path, importer):
    content = EXPORT_QIF.replace("T-7.25\n", "", 1)
    txns = _by_narration(importer.extract(_write(tmp_path, "no-amount.qif", content), []))

    assert "No label here" not in txns
    assert "Grocer Ltd" in txns


def test_an_unmapped_account_is_reported(importer, path, caplog):
    caplog.set_level("INFO", logger=qif.__name__)
    importer.extract(path, [])

    assert "Skipping 1 transactions of unmapped account Savings." in caplog.text


def test_an_undeclared_category_is_reported_once(importer, path, caplog):
    importer.extract(path, [])

    assert caplog.text.count("'Unheard Of' is not declared") == 1


def test_an_override_silences_the_undeclared_warning(path, caplog):
    qif.Importer(TARGETS, {"Unheard Of": "Expenses:Books"}).extract(path, [])

    assert "is not declared" not in caplog.text


def test_a_category_override_wins_over_a_transfer(path):
    """A bracketed label can be mapped too, before any transfer rule applies."""
    importer = qif.Importer(TARGETS, {"[Card]": "Assets:Elsewhere"})
    txn = _by_narration(importer.extract(path, []))["Moving money"]

    assert txn.postings[1].account == "Assets:Elsewhere"
