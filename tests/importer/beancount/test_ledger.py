import pytest
from beancount import loader

from pybank.importer.beancount import ledger

ACCOUNTS = """\
2010-01-01 open Assets:Bank:Checking
2012-01-01 open Expenses:Food:Groceries
2011-01-01 open Expenses:Phone:Fixed
  note: "a metadata line"
2013-01-01 open Expenses:Phone:Mobile

2010-01-01 open Income:Salary
"""


def _load(tmp_path, extra="", includes=""):
    main = tmp_path / "main.beancount"
    accounts = tmp_path / "accounts.beancount"
    accounts.write_text(ACCOUNTS + extra)
    main.write_text('include "accounts.beancount"\n' + includes)
    entries, errors, _ = loader.load_file(str(main))
    assert not errors
    return entries, accounts


def test_a_new_category_goes_below_its_siblings_with_their_earliest_date(tmp_path):
    entries, accounts = _load(tmp_path)

    opened = ledger.open_account(entries, "Expenses:Phone:Internet")

    assert accounts.read_text().splitlines()[2:6] == [
        "2011-01-01 open Expenses:Phone:Fixed",
        '  note: "a metadata line"',
        "2013-01-01 open Expenses:Phone:Mobile",
        "2011-01-01 open Expenses:Phone:Internet",
    ]
    assert (opened.account, opened.meta["lineno"]) == ("Expenses:Phone:Internet", 6)


def test_a_parent_goes_above_its_first_child(tmp_path):
    entries, accounts = _load(tmp_path)

    ledger.open_account(entries, "Expenses:Phone")

    assert accounts.read_text().splitlines()[2] == "2011-01-01 open Expenses:Phone"


def test_metadata_lines_stay_with_their_open_line(tmp_path):
    entries, accounts = _load(tmp_path)

    ledger.open_account(entries, "Expenses:Phone:Fixed:Sip")
    _, errors, _ = loader.load_file(str(tmp_path / "main.beancount"))

    assert not errors
    assert accounts.read_text().splitlines()[4] == "2011-01-01 open Expenses:Phone:Fixed:Sip"


@pytest.mark.parametrize(
    ("account", "error"),
    [
        ("Expenses:Phone:Mobile", "Already in the ledger"),
        ("Assets:Bank:Savings", "Not a category"),
        ("Expenses:lower", "Not a category"),
    ],
)
def test_a_bad_name_is_reported_and_changes_nothing(tmp_path, account, error):
    entries, accounts = _load(tmp_path)

    with pytest.raises(ValueError, match=error):
        ledger.open_account(entries, account)

    assert accounts.read_text() == ACCOUNTS


def test_the_date_is_early_enough_for_every_open_row(tmp_path):
    entries, _ = _load(tmp_path, "2008-01-01 open Expenses:Uncategorized\n")

    opened = ledger.open_account(entries, "Expenses:Phone:Internet")

    assert str(opened.date) == "2008-01-01"


def test_a_last_line_without_a_newline_keeps_its_own_line(tmp_path):
    entries, accounts = _load(tmp_path, "2010-01-01 open Expenses:Travel")

    ledger.open_account(entries, "Expenses:Travel:Train")

    assert accounts.read_text().splitlines()[-2:] == [
        "2010-01-01 open Expenses:Travel",
        "2010-01-01 open Expenses:Travel:Train",
    ]


def test_the_file_with_most_relatives_gets_the_line(tmp_path):
    other = tmp_path / "other.beancount"
    other.write_text("2010-01-01 open Expenses:Phone:Old\n")
    entries, accounts = _load(tmp_path, "", 'include "other.beancount"\n')

    ledger.open_account(entries, "Expenses:Phone:Internet")

    assert "Expenses:Phone:Internet" in accounts.read_text()
    assert "Expenses:Phone:Internet" not in other.read_text()


def test_a_new_child_of_a_root_goes_below_the_last_account_of_that_root(tmp_path):
    entries, accounts = _load(tmp_path)

    ledger.open_account(entries, "Income:Gifts")

    assert accounts.read_text().splitlines()[-1] == "2010-01-01 open Income:Gifts"


def test_a_root_with_no_open_account_is_reported(tmp_path):
    accounts = tmp_path / "main.beancount"
    accounts.write_text("2010-01-01 open Expenses:Travel\n")
    entries, _, _ = loader.load_file(str(accounts))

    with pytest.raises(ValueError, match="No open account under Income"):
        ledger.open_account(entries, "Income:Salary")
