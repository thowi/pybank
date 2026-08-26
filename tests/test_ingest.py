"""All values here are invented. Never derive a fixture from a real config."""

import pytest

from pybank import ingest
from pybank.importer.beancount import dkb, ibkr, postfinance, qif

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
