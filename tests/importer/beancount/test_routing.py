"""All values here are invented. Never derive a fixture from a real config."""

import pytest
from beangulp import exceptions

from pybank.importer.beancount import routing

ONE = "Assets:Bank:One"
TWO = "Assets:Bank:Two"


def _router(accounts):
    return routing.AccountRouter(accounts, "bank.checking")


def test_a_fragment_matches_anywhere_in_the_identifier():
    router = _router({"1234": ONE})

    assert router.account_for("CH00 0000 1234 0000") == ONE
    assert router.account_for("CH0000000123400000") == ONE


def test_each_fragment_routes_to_its_own_account():
    router = _router({"1111": ONE, "2222": TWO})

    assert router.account_for("card 1111") == ONE
    assert router.account_for("card 2222") == TWO


def test_fragments_that_agree_on_the_account_are_allowed():
    """A renumbered account can keep its history by naming both identifiers."""
    router = _router({"1111": ONE, "2222": ONE})

    assert router.account_for("1111 and 2222") == ONE


def test_fragments_that_disagree_name_the_table_and_the_identifier():
    router = _router({"111": ONE, "1111": TWO})

    with pytest.raises(routing.ConfigError) as err:
        router.account_for("card 1111")

    assert "bank.checking" in str(err.value)
    assert "card 1111" in str(err.value)


def test_an_unconfigured_identifier_is_quoted_back_for_copying():
    router = _router({"9999": ONE})

    with pytest.raises(routing.ConfigError) as err:
        router.account_for("card 1111")

    assert "card 1111" in str(err.value)
    assert "bank.checking" in str(err.value)


def test_beangulp_reports_a_routing_error_without_a_traceback():
    """The message is the hint to copy into the config, so it stays readable."""
    lines = []
    with exceptions.ExceptionsTrap(lambda text, **_: lines.append(text)):
        _router({"9999": ONE}).account_for("card 1111")

    assert any("card 1111" in line for line in lines)
    assert not any("Traceback" in line for line in lines)
