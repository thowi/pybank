import datetime
import re

import pytest

from pybank import config
from pybank.importer.beancount import refunds, routing

HINT = """\
[[transfers]]
account = "Liabilities:Other:Card"
text = "card repayment"
"""


def _write(tmp_path, content):
    path = tmp_path / "pybank.toml"
    path.write_text(content, encoding="utf-8")
    return str(path)


def test_transfer_hints_ignore_case(tmp_path):
    (hint,) = config.hints(config.load(_write(tmp_path, HINT)))

    assert hint.account == "Liabilities:Other:Card"
    assert hint.text.search("CARD REPAYMENT")


def test_a_transfer_hint_missing_its_text_is_reported(tmp_path):
    loaded = config.load(_write(tmp_path, '[[transfers]]\naccount = "Assets:A"\n'))

    with pytest.raises(routing.ConfigError, match="needs account and text"):
        config.hints(loaded)


def test_a_bad_transfer_pattern_is_reported(tmp_path):
    content = '[[transfers]]\naccount = "Assets:A"\ntext = "("\n'

    with pytest.raises(routing.ConfigError, match="Bad text pattern"):
        config.hints(config.load(_write(tmp_path, content)))


def test_a_missing_config_file_says_which_path(tmp_path):
    missing = str(tmp_path / "absent.toml")

    with pytest.raises(routing.ConfigError, match="absent.toml"):
        config.load(missing)


def test_unparsable_toml_is_reported_as_config(tmp_path):
    with pytest.raises(routing.ConfigError, match="Cannot parse"):
        config.load(_write(tmp_path, "[postfinance\n"))


def test_rules_load_with_their_filters(tmp_path):
    content = """\
[[rules]]
account = "Assets:Bank"
book = "Expenses:Living:Groceries"
from = 2025-01-01
labels = ["Dining"]
text = "meal box"
until = 2025-12-31
"""
    (rule,) = config.load_rules(_write(tmp_path, content))

    assert rule.account == "Assets:Bank"
    assert rule.book == "Expenses:Living:Groceries"
    assert rule.end == datetime.date(2025, 12, 31)
    assert rule.labels == frozenset({"Dining"})
    assert rule.start == datetime.date(2025, 1, 1)
    assert rule.text.search("MEAL BOX")


def test_no_rules_file_means_no_rules(tmp_path):
    assert config.load_rules(str(tmp_path / "rules.toml")) == []


def test_a_misspelled_rule_key_is_reported(tmp_path):
    content = '[[rules]]\nbook = "Expenses:A"\ntext = "a"\nlabel = ["Dining"]\n'

    with pytest.raises(routing.ConfigError, match="Unknown keys: label"):
        config.load_rules(_write(tmp_path, content))


def test_a_rule_missing_its_target_is_reported(tmp_path):
    with pytest.raises(routing.ConfigError, match="needs book and text"):
        config.load_rules(_write(tmp_path, '[[rules]]\ntext = "a"\n'))


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ('text = "a("', "Bad text pattern"),
        ("text = 5", "text must be a string"),
        ('labels = "Dining"', "labels must be a list"),
        ('from = "2025-01-01"', "from and until must be dates"),
        ("until = 2025-01-01T00:00:00", "from and until must be dates"),
    ],
)
def test_a_rule_value_of_the_wrong_type_is_reported(tmp_path, line, error):
    defaults = {"book": 'book = "Expenses:A"', "text": 'text = "a"'}
    defaults[line.split(" ")[0]] = line
    content = "[[rules]]\n" + "\n".join(defaults.values()) + "\n"

    with pytest.raises(routing.ConfigError, match=error):
        config.load_rules(_write(tmp_path, content))


def test_a_misspelled_rules_section_is_reported(tmp_path):
    with pytest.raises(routing.ConfigError, match="Unknown rules.toml sections: rule"):
        config.load_rules(_write(tmp_path, '[[rule]]\nbook = "Expenses:A"\ntext = "a"\n'))


def test_the_refunds_table_is_read(tmp_path):
    content = (
        '[refunds]\naccounts = ["Liabilities:Card"]\nlabels = ["Returns"]\n'
        "prefixes = ['return\\b']\n"
    )

    table = config.load_refunds(_write(tmp_path, content))

    assert table == refunds.Config(
        accounts=("Liabilities:Card",),
        labels=frozenset({"Returns"}),
        prefixes=(re.compile(r"return\b", re.IGNORECASE),),
    )


def test_no_rules_file_means_no_refunds(tmp_path):
    assert config.load_refunds(str(tmp_path / "rules.toml")) == refunds.Config()


def test_a_misspelled_refunds_key_is_reported(tmp_path):
    with pytest.raises(routing.ConfigError, match="Unknown keys: account"):
        config.load_refunds(_write(tmp_path, '[refunds]\naccount = ["Liabilities:Card"]\n'))


def test_a_refunds_value_that_is_no_list_is_reported(tmp_path):
    with pytest.raises(routing.ConfigError, match="must be lists"):
        config.load_refunds(_write(tmp_path, '[refunds]\nlabels = "Returns"\n'))


def test_a_refunds_value_that_is_no_table_is_reported(tmp_path):
    with pytest.raises(routing.ConfigError, match="must be a table"):
        config.load_refunds(_write(tmp_path, "refunds = 1\n"))


def test_a_bad_refunds_prefix_is_reported(tmp_path):
    with pytest.raises(routing.ConfigError, match="Bad prefix pattern"):
        config.load_refunds(_write(tmp_path, '[refunds]\nprefixes = ["("]\n'))


def test_a_refunds_prefix_that_is_no_string_is_reported(tmp_path):
    with pytest.raises(routing.ConfigError, match="must be strings"):
        config.load_refunds(_write(tmp_path, "[refunds]\nprefixes = [1]\n"))


def test_a_misspelled_categorize_key_is_reported(tmp_path):
    with pytest.raises(routing.ConfigError, match="Unknown keys: modle"):
        config.categorize_settings({"categorize": {"modle": "m"}})
