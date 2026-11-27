import io

from pybank.cli import ingest
from pybank.importer.beancount import categorize, transfer_matcher

ONE_SECTION = """\
[postfinance.checking]
"0000" = "Assets:A"
"""


def _write(tmp_path, content):
    path = tmp_path / "pybank.toml"
    path.write_text(content, encoding="utf-8")
    return str(path)


def test_main_without_a_config_exits_rather_than_guessing(capsys):
    assert ingest.main([]) == 2
    assert "--config" in capsys.readouterr().err


def test_the_config_option_reaches_the_importers(tmp_path):
    assert ingest.main(["--config", _write(tmp_path, ONE_SECTION), "identify"]) == 0


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


def test_unpaired_names_the_postings_with_the_same_amount(tmp_path, capsys):
    ledger = tmp_path / "main.beancount"
    second = '2019-03-05 * "Second out"\n  Assets:Bank:Checking  -100.00 CHF\n'
    ledger.write_text(f"{UNPAIRED_LEDGER}\n{second}  Assets:Transfers:InTransit\n", "utf-8")

    ingest.main(["--config", _write(tmp_path, ONE_SECTION), "unpaired", str(ledger)])

    out = capsys.readouterr().out
    assert (
        "2019-03-05  Assets:Bank:Checking  -100.00 CHF  Second out\n"
        "  1 of 3 with this amount. Any may be the one:\n"
        "    2019-03-04  Assets:Bank:Checking  -100.00 CHF  Paired out\n"
        "    2019-03-06  Assets:Other:Savings  100.00 CHF  Paired in\n"
    ) in out
    assert "Clearing postings without a partner: 3" in out


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
    monkeypatch.setenv("COLUMNS", "100")
    argv = ["--config", _write(tmp_path, ONE_SECTION), "confirm-transfers", str(ledger)]
    assert ingest.main(argv) == 0
    return transfer_matcher.load_answers(str(tmp_path / "transfer-pairs.toml"))


def _rows(out):
    """Returns each printed row with its column gaps collapsed to one space."""
    return [" ".join(line.split()) for line in out.splitlines()]


def test_confirm_saves_each_answer(tmp_path, monkeypatch, capsys):
    answers = _confirm(tmp_path, monkeypatch, "Y\nn\n")

    assert answers == {frozenset(["out-1", "in-1"]): True, frozenset(["out-2", "in-2"]): False}
    out = capsys.readouterr().out
    rows = _rows(out)
    assert "Sent Received" in rows
    assert "Date 2019-03-04 2019-03-05" in rows
    assert "Account Assets:Bank:Checking Assets:Other:Savings" in rows
    assert "Amount -100.00 CHF 100.00 CHF" in rows
    assert "Text First out First in" in rows
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


def test_confirm_does_not_ask_about_an_exact_pair_with_a_known_leg(tmp_path, monkeypatch):
    known = CANDIDATES_LEDGER.replace(
        "2019-01-01 open Expenses:Uncategorized\n",
        "2019-01-01 open Expenses:Uncategorized\n2019-01-01 open Assets:Transfers:InTransit\n",
    ).replace("-100.00 CHF\n  Expenses:Uncategorized", "-100.00 CHF\n  Assets:Transfers:InTransit")

    answers = _confirm(tmp_path, monkeypatch, "n\n", known)

    assert answers == {frozenset(["out-2", "in-2"]): False}


# Two known legs in two currencies, at a rate near the market.
CURRENCY_LEDGER = """\
2019-01-01 open Assets:Bank:Checking
2019-01-01 open Assets:Other:Savings
2019-01-01 open Assets:Transfers:InTransit

2019-03-04 price EUR 1.10 CHF

2019-03-04 * "Out"
  import-id: "out"
  Assets:Bank:Checking  -100.00 EUR
  Assets:Transfers:InTransit

2019-03-05 * "In"
  import-id: "in"
  Assets:Other:Savings  107.50 CHF
  Assets:Transfers:InTransit
"""


def test_confirm_asks_about_a_sure_pair_left_unbooked(tmp_path, monkeypatch):
    assert _confirm(tmp_path, monkeypatch, "y\n", CURRENCY_LEDGER) == {
        frozenset(["out", "in"]): True
    }


def test_confirm_shows_the_rate_a_currency_pair_implies(tmp_path, monkeypatch, capsys):
    _confirm(tmp_path, monkeypatch, "y\n", CURRENCY_LEDGER)

    rows = _rows(capsys.readouterr().out)
    assert "Rate 1 EUR = 1.0750 CHF" in rows
    assert "Market 1 EUR = 1.1000 CHF on 2019-03-04" in rows
    # 107.50 CHF is worth 97.73 EUR at the market, 2.27 EUR short of what left.
    assert "Spread 2.27 EUR (2.3%)" in rows


def test_confirm_shows_payee_and_counterparty_account(tmp_path, monkeypatch, capsys):
    detailed = CANDIDATES_LEDGER.replace(
        '2019-03-05 ! "First in"\n  import-id: "in-1"',
        '2019-03-05 ! "A Sender" "First in"\n  import-id: "in-1"\n  counterparty-account: "XX00"',
    )

    _confirm(tmp_path, monkeypatch, "y\nn\n", detailed)

    rows = _rows(capsys.readouterr().out)
    assert "Payee A Sender" in rows
    assert "Their acct XX00" in rows


def test_confirm_does_not_ask_about_a_booked_pair(tmp_path, monkeypatch):
    booked = CURRENCY_LEDGER.replace(
        "107.50 CHF\n  Assets:Transfers:InTransit",
        "107.50 CHF\n  Assets:Transfers:InTransit  -100.00 EUR @ 1.075 CHF",
    )

    # A question would find no input and abort.
    assert _confirm(tmp_path, monkeypatch, "", booked) == {}


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


CATEGORIZE_LEDGER = """\
2019-01-01 open Assets:Bank:Checking
2019-01-01 open Expenses:Living:Groceries
2019-01-01 open Expenses:Mobility:Transit
2019-01-01 open Expenses:Uncategorized

2019-03-01 * "Corner Shop"
  import-id: "shop-1"
  category-source: "qif"
  Assets:Bank:Checking  -20.00 CHF
  Expenses:Living:Groceries

2019-03-02 * "Corner Shop"
  import-id: "shop-2"
  category-source: "qif"
  Assets:Bank:Checking  -20.00 CHF
  Expenses:Living:Groceries

2019-03-03 ! "Corner Shop"
  import-id: "open-1"
  Assets:Bank:Checking  -20.00 CHF
  Expenses:Uncategorized

2019-03-04 ! "Corner Shop"
  import-id: "open-2"
  Assets:Bank:Checking  -20.00 CHF
  Expenses:Uncategorized

2019-03-05 ! "Rail Co"
  import-id: "open-3"
  Assets:Bank:Checking  -20.00 CHF
  Expenses:Uncategorized
"""


def _fake_ask(model, effort):
    def ask(prompt, schema):
        row = prompt.split("Transaction:\n")[1]
        if row.startswith("Corner"):
            return {"choices": [{"label": "1", "probability": 0.99}]}
        return {"choices": [{"label": "2", "probability": 0.6}, {"label": "1", "probability": 0.3}]}

    return ask


def _categorize(tmp_path, monkeypatch, keys, config=ONE_SECTION + '[categorize]\nmodel = "m"\n'):
    ledger = tmp_path / "main.beancount"
    ledger.write_text(CATEGORIZE_LEDGER, encoding="utf-8")
    monkeypatch.setattr(categorize, "openai_ask", _fake_ask)
    monkeypatch.setattr("sys.stdin", io.StringIO(keys))
    monkeypatch.setenv("COLUMNS", "100")
    return ingest.main(["--config", _write(tmp_path, config), "categorize", str(ledger)])


def test_categorize_approves_a_sure_group_then_asks_one_by_one(tmp_path, monkeypatch, capsys):
    assert _categorize(tmp_path, monkeypatch, "y\n2\n") == 0

    answers = categorize.load_answers(str(tmp_path / "categories.toml"))
    assert answers == {
        "open-1": "Expenses:Living:Groceries",
        "open-2": "Expenses:Living:Groceries",
        "open-3": "Expenses:Living:Groceries",
    }
    out = capsys.readouterr().out
    assert "Group 1 of 1: 2 rows of 'corner shop'" in out
    assert "  1) Expenses:Mobility:Transit  67%" in out
    assert "Approved 3 of 3 rows." in out


def test_categorize_asks_one_by_one_about_a_declined_group(tmp_path, monkeypatch, capsys):
    assert _categorize(tmp_path, monkeypatch, "n\ns\n1\nq\n") == 0

    answers = categorize.load_answers(str(tmp_path / "categories.toml"))
    assert answers == {"open-1": "Expenses:Living:Groceries"}
    assert "Approved 1 of 3 rows." in capsys.readouterr().out


def test_categorize_needs_a_model(tmp_path, monkeypatch, capsys):
    assert _categorize(tmp_path, monkeypatch, "", config=ONE_SECTION) == 1

    assert "[categorize] needs a model" in capsys.readouterr().err
