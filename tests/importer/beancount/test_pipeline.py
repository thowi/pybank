import datetime

import pytest
from beancount.core import amount, data, flags

from pybank import config
from pybank.importer.beancount import (
    UNCATEGORIZED,
    dkb,
    ibkr,
    pipeline,
    postfinance,
    qif,
    refunds,
    revolut,
    routing,
    see,
    wise,
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

[revolut.accounts]
CHF = "Assets:App:CHF"

[see.targets]
"Old Savings" = { account = "Assets:Bank:Savings", currency = "EUR" }

[wise.accounts]
EUR = "Assets:Transfer:EUR"

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
    # Exact, since `see.Importer` is a `qif.Importer` too.
    return [importer for importer in importers if type(importer) is cls]


def test_a_full_config_builds_every_importer(tmp_path):
    built = pipeline._importers(config.load(_write(tmp_path, FULL_CONFIG)))

    assert len(built) == 9
    for cls in (
        dkb.CheckingImporter,
        dkb.CreditCardImporter,
        ibkr.Importer,
        postfinance.CheckingImporter,
        postfinance.CreditCardImporter,
        qif.Importer,
        revolut.Importer,
        see.Importer,
        wise.Importer,
    ):
        assert len(_of_type(built, cls)) == 1


def test_a_missing_section_turns_that_institution_off(tmp_path):
    loaded = config.load(_write(tmp_path, ONE_SECTION))

    built = pipeline._importers(loaded)

    assert len(built) == 1
    assert _of_type(built, postfinance.CheckingImporter)


def test_the_configured_account_reaches_the_importer(tmp_path):
    loaded = config.load(_write(tmp_path, ONE_SECTION))

    importer = pipeline._importers(loaded)[0]

    assert importer._router.account_for("CH00 0000") == "Assets:A"


def test_the_card_table_reaches_the_card_importer(tmp_path):
    loaded = config.load(_write(tmp_path, FULL_CONFIG))

    importer = _of_type(pipeline._importers(loaded), postfinance.CreditCardImporter)[0]

    assert importer._router.account_for("XXXX 0000 Visa") == "Liabilities:Bank:Card"


@pytest.mark.parametrize("section", ["revolut", "wise"])
def test_a_currency_app_without_accounts_is_reported(tmp_path, section):
    loaded = config.load(_write(tmp_path, f"[{section}]\n"))

    with pytest.raises(routing.ConfigError, match=rf"\[{section}\.accounts\]"):
        pipeline._importers(loaded)


def test_a_bare_account_name_where_a_table_belongs_is_reported(tmp_path):
    loaded = config.load(_write(tmp_path, '[postfinance]\nchecking = "Assets:A"\n'))

    with pytest.raises(routing.ConfigError, match=r"postfinance\.checking"):
        pipeline._importers(loaded)


def test_ibkr_overrides_only_what_the_config_names(tmp_path):
    loaded = config.load(_write(tmp_path, '[ibkr]\ncash = "Assets:Broker:Cash"\n'))

    importer = pipeline._importers(loaded)[0]

    assert importer.account("ignored.xml") == "Assets:Broker:Cash"
    assert importer._accounts.dividends == ibkr.DEFAULT_ACCOUNTS.dividends


def test_qif_targets_become_account_and_currency(tmp_path):
    loaded = config.load(_write(tmp_path, FULL_CONFIG))

    importer = _of_type(pipeline._importers(loaded), qif.Importer)[0]

    assert importer._targets == {"Old Checking": qif.Target("Assets:Bank:Checking", "CHF")}
    assert importer._categories == {"Odd Label": "Expenses:Other"}


# The card's statement and a QIF export both cover one repayment.
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
    loaded = config.load(_write(tmp_path, OVERLAP_CONFIG))
    card, export = pipeline._importers(loaded)
    groups = [
        ("card.csv", [_row(UNCATEGORIZED, flags.FLAG_WARNING)], "Liabilities:Bank:Card", card),
        (
            "old.qif",
            [_row("Assets:Receivable:Friends", flags.FLAG_OKAY)],
            "Liabilities:Bank:Card",
            export,
        ),
    ]

    for hook in pipeline._hooks(config.hints(loaded), {}, [], refunds.Config(), {}, {}):
        groups = hook(groups, [])

    statements, exported = groups[0][1], groups[1][1]
    assert exported == []
    (kept,) = statements
    assert kept.postings[1].account == "Assets:Receivable:Friends"
    assert kept.meta[qif.META_CATEGORY_SOURCE] == qif.CATEGORY_SOURCE_QIF


def test_an_empty_config_is_an_error_rather_than_a_silent_no_op(tmp_path):
    with pytest.raises(routing.ConfigError, match="No importers"):
        pipeline._importers(config.load(_write(tmp_path, "")))


def test_a_misspelled_section_is_reported_rather_than_ignored(tmp_path):
    loaded = config.load(_write(tmp_path, '[postfinanace]\nchecking = "Assets:A"\n'))

    with pytest.raises(routing.ConfigError, match="postfinanace"):
        pipeline._importers(loaded)


def test_see_targets_become_account_and_currency(tmp_path):
    loaded = config.load(_write(tmp_path, FULL_CONFIG))

    (importer,) = _of_type(pipeline._importers(loaded), see.Importer)

    assert importer._targets == {"Old Savings": qif.Target("Assets:Bank:Savings", "EUR")}


def test_a_qif_target_missing_its_currency_names_the_target(tmp_path):
    content = '[qif.targets]\n"Old Checking" = { account = "Assets:A" }\n'
    loaded = config.load(_write(tmp_path, content))

    with pytest.raises(routing.ConfigError, match="Old Checking"):
        pipeline._importers(loaded)


def test_an_unknown_ibkr_key_is_reported(tmp_path):
    loaded = config.load(_write(tmp_path, '[ibkr]\nnonsense = "Assets:A"\n'))

    with pytest.raises(routing.ConfigError, match="ibkr"):
        pipeline._importers(loaded)


def test_ingest_wires_every_importer_and_hook(tmp_path):
    run = pipeline.ingest(_write(tmp_path, FULL_CONFIG))

    assert len(run.importers) == 9
    assert len(run.hooks) == 6
