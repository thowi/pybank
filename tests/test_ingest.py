"""All values here are invented. Never derive a fixture from a real config."""

import datetime
import io

import pytest
from beancount.core import amount, data, flags

from pybank import ingest
from pybank.importer.beancount import (
    UNCATEGORIZED,
    dkb,
    ibkr,
    postfinance,
    qif,
    transfer_matcher,
)

FULL_CONFIG = """\
[dkb.card]
"1111" = "Liabilities:Other:Card"

[dkb.checking]
"2222" = "Assets:Other:Checking"

[ibkr]
cash = "Assets:Broker:Cash"

[postfinance.card]
"0000" = "Liabilities:Bank:Card"

[postfinance.checking]
"3333" = "Assets:Bank:Checking"

[qif.targets]
"Old Checking" = { account = "Assets:Bank:Checking", currency = "CHF" }

[qif.categories]
"Odd Label" = "Expenses:Other"

[[transfers]]
account = "Liabilities:Other:Card"
text = "card repayment"
"""


ONE_SECTION = """\
[postfinance.checking]
"0000" = "Assets:A"
"""


def _write(tmp_path, content):
    path = tmp_path / "pybank.toml"
    path.write_text(content, encoding="utf-8")
    return str(path)


def _of_type(importers, cls):
    return [importer for importer in importers if isinstance(importer, cls)]


def test_a_full_config_builds_every_importer(tmp_path):
    built = ingest._importers(ingest._load_config(_write(tmp_path, FULL_CONFIG)))

    assert len(built) == 6
    for cls in (
        dkb.CheckingImporter,
        dkb.CreditCardImporter,
        ibkr.Importer,
        postfinance.CheckingImporter,
        postfinance.CreditCardImporter,
        qif.Importer,
    ):
        assert len(_of_type(built, cls)) == 1


def test_a_missing_section_turns_that_institution_off(tmp_path):
    config = ingest._load_config(_write(tmp_path, ONE_SECTION))

    built = ingest._importers(config)

    assert len(built) == 1
    assert _of_type(built, postfinance.CheckingImporter)


def test_the_configured_account_reaches_the_importer(tmp_path):
    config = ingest._load_config(_write(tmp_path, ONE_SECTION))

    importer = ingest._importers(config)[0]

    assert importer._router.account_for("CH00 0000") == "Assets:A"


def test_the_card_table_reaches_the_card_importer(tmp_path):
    config = ingest._load_config(_write(tmp_path, FULL_CONFIG))

    importer = _of_type(ingest._importers(config), postfinance.CreditCardImporter)[0]

    assert importer._router.account_for("XXXX 0000 Visa") == "Liabilities:Bank:Card"


def test_a_bare_account_name_where_a_table_belongs_is_reported(tmp_path):
    config = ingest._load_config(_write(tmp_path, '[postfinance]\nchecking = "Assets:A"\n'))

    with pytest.raises(ingest._ConfigError, match=r"postfinance\.checking"):
        ingest._importers(config)


def test_ibkr_overrides_only_what_the_config_names(tmp_path):
    config = ingest._load_config(_write(tmp_path, '[ibkr]\ncash = "Assets:Broker:Cash"\n'))

    importer = ingest._importers(config)[0]

    assert importer.account("ignored.xml") == "Assets:Broker:Cash"
    assert importer._accounts.dividends == ibkr.DEFAULT_ACCOUNTS.dividends


def test_qif_targets_become_account_and_currency(tmp_path):
    config = ingest._load_config(_write(tmp_path, FULL_CONFIG))

    importer = _of_type(ingest._importers(config), qif.Importer)[0]

    assert importer._targets == {"Old Checking": qif.Target("Assets:Bank:Checking", "CHF")}
    assert importer._categories == {"Odd Label": "Expenses:Other"}


def test_transfer_hints_ignore_case(tmp_path):
    (hint,) = ingest._hints(ingest._load_config(_write(tmp_path, FULL_CONFIG)))

    assert hint.account == "Liabilities:Other:Card"
    assert hint.text.search("CARD REPAYMENT")


def test_a_transfer_hint_missing_its_text_is_reported(tmp_path):
    config = ingest._load_config(_write(tmp_path, '[[transfers]]\naccount = "Assets:A"\n'))

    with pytest.raises(ingest._ConfigError, match="needs account and text"):
        ingest._hints(config)


def test_a_bad_transfer_pattern_is_reported(tmp_path):
    content = '[[transfers]]\naccount = "Assets:A"\ntext = "("\n'

    with pytest.raises(ingest._ConfigError, match="Bad text pattern"):
        ingest._hints(ingest._load_config(_write(tmp_path, content)))


# The card's statement and an old export both cover one repayment.
# A hint classifies that repayment as a transfer.
OVERLAP_CONFIG = """\
[postfinance.card]
"0000" = "Liabilities:Bank:Card"

[qif.targets]
"Old Card" = { account = "Liabilities:Bank:Card", currency = "CHF" }

[[transfers]]
account = "Liabilities:Bank:Card"
text = "card repayment"
"""


def _row(contra, flag):
    units = amount.Amount(data.Decimal("50"), "CHF")
    postings = [
        data.Posting("Liabilities:Bank:Card", units, None, None, None, None),
        data.Posting(contra, None, None, None, None, None),
    ]
    day = datetime.date(2019, 3, 4)
    return data.Transaction(
        {}, day, flag, None, "Card repayment", data.EMPTY_SET, data.EMPTY_SET, postings
    )


def test_the_hooks_keep_one_copy_of_a_hinted_row_the_export_also_holds(tmp_path):
    config = ingest._load_config(_write(tmp_path, OVERLAP_CONFIG))
    card, export = ingest._importers(config)
    groups = [
        ("card.csv", [_row(UNCATEGORIZED, flags.FLAG_WARNING)], "Liabilities:Bank:Card", card),
        (
            "old.qif",
            [_row("Assets:Receivable:Friends", flags.FLAG_OKAY)],
            "Liabilities:Bank:Card",
            export,
        ),
    ]

    for hook in ingest._hooks(config, {}):
        groups = hook(groups, [])

    statements, exported = groups[0][1], groups[1][1]
    assert exported == []
    (kept,) = statements
    assert kept.postings[1].account == "Assets:Receivable:Friends"
    assert kept.meta[qif.META_CATEGORY_SOURCE] == qif.CATEGORY_SOURCE_QIF


def test_an_empty_config_is_an_error_rather_than_a_silent_no_op(tmp_path):
    with pytest.raises(ingest._ConfigError, match="No importers"):
        ingest._importers(ingest._load_config(_write(tmp_path, "")))


def test_a_misspelled_section_is_reported_rather_than_ignored(tmp_path):
    config = ingest._load_config(_write(tmp_path, '[postfinanace]\nchecking = "Assets:A"\n'))

    with pytest.raises(ingest._ConfigError, match="postfinanace"):
        ingest._importers(config)


def test_a_qif_target_missing_its_currency_names_the_target(tmp_path):
    content = '[qif.targets]\n"Old Checking" = { account = "Assets:A" }\n'
    config = ingest._load_config(_write(tmp_path, content))

    with pytest.raises(ingest._ConfigError, match="Old Checking"):
        ingest._importers(config)


def test_an_unknown_ibkr_key_is_reported(tmp_path):
    config = ingest._load_config(_write(tmp_path, '[ibkr]\nnonsense = "Assets:A"\n'))

    with pytest.raises(ingest._ConfigError, match="ibkr"):
        ingest._importers(config)


def test_a_missing_config_file_says_which_path(tmp_path):
    missing = str(tmp_path / "absent.toml")

    with pytest.raises(ingest._ConfigError, match="absent.toml"):
        ingest._load_config(missing)


def test_unparsable_toml_is_reported_as_config(tmp_path):
    with pytest.raises(ingest._ConfigError, match="Cannot parse"):
        ingest._load_config(_write(tmp_path, "[postfinance\n"))


def test_main_without_a_config_exits_rather_than_guessing(capsys):
    assert ingest.main([]) == 2
    assert "--config" in capsys.readouterr().err


def test_the_config_option_reaches_the_importers(tmp_path):
    assert ingest.main(["--config", _write(tmp_path, FULL_CONFIG), "identify"]) == 0


UNPAIRED_LEDGER = """\
2019-01-01 open Assets:Bank:Checking
2019-01-01 open Assets:Other:Savings
2019-01-01 open Assets:Transfers:InTransit
2019-01-01 open Expenses:Food

2019-03-04 * "Paired out"
  Assets:Bank:Checking  -100.00 CHF
  Assets:Transfers:InTransit

2019-03-06 * "Paired in"
  Assets:Other:Savings  100.00 CHF
  Assets:Transfers:InTransit

2019-03-08 * "Lonely out"
  Assets:Bank:Checking  -40.00 CHF
  Assets:Transfers:InTransit

2019-03-09 * "Split with a transfer"
  Assets:Bank:Checking  -150.00 CHF
  Expenses:Food  100.00 CHF
  Assets:Transfers:InTransit  50.00 CHF
"""


def test_unpaired_lists_the_clearing_postings_nothing_cancels(tmp_path, capsys):
    ledger = tmp_path / "main.beancount"
    ledger.write_text(UNPAIRED_LEDGER, encoding="utf-8")

    assert ingest.main(["--config", _write(tmp_path, ONE_SECTION), "unpaired", str(ledger)]) == 0

    out = capsys.readouterr().out
    assert "2019-03-08  Assets:Bank:Checking  -40.00 CHF  Lonely out" in out
    assert "2019-03-09  Assets:Bank:Checking  -50.00 CHF  Split with a transfer" in out
    assert "Paired" not in out
    assert "Clearing postings without a partner: 2" in out


def test_unpaired_reports_load_errors(tmp_path, capsys):
    ledger = tmp_path / "main.beancount"
    ledger.write_text(UNPAIRED_LEDGER.replace("2019-01-01 open Expenses:Food\n", ""), "utf-8")

    ingest.main(["--config", _write(tmp_path, ONE_SECTION), "unpaired", str(ledger)])

    assert "Expenses:Food" in capsys.readouterr().err


CANDIDATES_LEDGER = """\
2019-01-01 open Assets:Bank:Checking
2019-01-01 open Assets:Other:Savings
2019-01-01 open Expenses:Uncategorized

2019-03-04 ! "First out"
  import-id: "out-1"
  Assets:Bank:Checking  -100.00 CHF
  Expenses:Uncategorized

2019-03-05 ! "First in"
  import-id: "in-1"
  Assets:Other:Savings  100.00 CHF
  Expenses:Uncategorized

2019-05-04 ! "Second out"
  import-id: "out-2"
  Assets:Bank:Checking  -7.00 CHF
  Expenses:Uncategorized

2019-05-05 ! "Second in"
  import-id: "in-2"
  Assets:Other:Savings  7.00 CHF
  Expenses:Uncategorized
"""


def _confirm(tmp_path, monkeypatch, keys, content=CANDIDATES_LEDGER):
    ledger = tmp_path / "main.beancount"
    ledger.write_text(content, encoding="utf-8")
    monkeypatch.setattr("sys.stdin", io.StringIO(keys))
    argv = ["--config", _write(tmp_path, ONE_SECTION), "confirm", str(ledger)]
    assert ingest.main(argv) == 0
    return transfer_matcher.load_answers(str(tmp_path / "transfer-pairs.toml"))


def test_confirm_saves_each_answer(tmp_path, monkeypatch, capsys):
    answers = _confirm(tmp_path, monkeypatch, "Y\nn\n")

    assert answers == {frozenset(["out-1", "in-1"]): True, frozenset(["out-2", "in-2"]): False}
    out = capsys.readouterr().out
    assert "2019-03-04  Assets:Bank:Checking  -100.00 CHF  First out" in out
    assert "Answered 2 of 2 pairs." in out


def test_confirm_asks_only_about_pairs_without_an_answer(tmp_path, monkeypatch, capsys):
    _confirm(tmp_path, monkeypatch, "s\ny\n")

    answers = _confirm(tmp_path, monkeypatch, "n\n")

    assert answers == {frozenset(["out-2", "in-2"]): True, frozenset(["out-1", "in-1"]): False}


def test_confirm_skips_a_leg_of_a_confirmed_pair(tmp_path, monkeypatch):
    path = tmp_path / "transfer-pairs.toml"
    path.write_text('[[pair]]\nlegs = ["out-1", "elsewhere"]\nconfirmed = true\n', encoding="utf-8")

    answers = _confirm(tmp_path, monkeypatch, "n\n")

    assert frozenset(["out-1", "in-1"]) not in answers
    assert answers[frozenset(["out-2", "in-2"])] is False


def test_confirm_does_not_ask_about_a_pair_with_a_known_leg(tmp_path, monkeypatch):
    known = CANDIDATES_LEDGER.replace(
        "2019-01-01 open Expenses:Uncategorized\n",
        "2019-01-01 open Expenses:Uncategorized\n2019-01-01 open Assets:Transfers:InTransit\n",
    ).replace("-100.00 CHF\n  Expenses:Uncategorized", "-100.00 CHF\n  Assets:Transfers:InTransit")

    answers = _confirm(tmp_path, monkeypatch, "n\n", known)

    assert answers == {frozenset(["out-2", "in-2"]): False}


def test_confirm_stops_on_quit(tmp_path, monkeypatch):
    assert _confirm(tmp_path, monkeypatch, "q\n") == {}


# A transfer out and two arrivals of its amount: No candidate forms.
CHOICE_LEDGER = """\
2019-01-01 open Assets:Bank:Checking
2019-01-01 open Assets:Other:Savings
2019-01-01 open Assets:Broker:Cash
2019-01-01 open Assets:Transfers:InTransit
2019-01-01 open Expenses:Uncategorized

2019-03-04 * "Out"
  import-id: "out"
  Assets:Bank:Checking  -100.00 CHF
  Assets:Transfers:InTransit

2019-03-05 ! "In"
  import-id: "in"
  Assets:Other:Savings  100.00 CHF
  Expenses:Uncategorized

2019-03-06 ! "Also in"
  import-id: "also-in"
  Assets:Broker:Cash  100.00 CHF
  Expenses:Uncategorized
"""


def test_confirm_saves_the_partner_picked_among_several(tmp_path, monkeypatch, capsys):
    answers = _confirm(tmp_path, monkeypatch, "2\n", CHOICE_LEDGER)

    assert answers == {frozenset(["out", "also-in"]): True}
    assert "Picked a partner for 1 of 1 transfers." in capsys.readouterr().out


def test_confirm_rejects_every_option_on_none_and_asks_no_more(tmp_path, monkeypatch):
    _confirm(tmp_path, monkeypatch, "n\n", CHOICE_LEDGER)

    # A second question would find no input and abort.
    answers = _confirm(tmp_path, monkeypatch, "", CHOICE_LEDGER)

    assert answers == {frozenset(["out", "in"]): False, frozenset(["out", "also-in"]): False}
