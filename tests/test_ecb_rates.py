"""All rates here are invented."""

import datetime
import decimal
import types

import pytest
import requests

from pybank import ecb_rates

HEADER = "KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE\n"

# Friday 2030-04-12 is a holiday: The ECB lists it, with no rate.
RATES = HEADER + (
    "EXR.D.AAA.EUR.SP00.A,D,AAA,EUR,SP00,A,2030-04-10,1.5000\n"
    "EXR.D.AAA.EUR.SP00.A,D,AAA,EUR,SP00,A,2030-04-11,1.6000\n"
    "EXR.D.AAA.EUR.SP00.A,D,AAA,EUR,SP00,A,2030-04-12,\n"
    "EXR.D.BBB.EUR.SP00.A,D,BBB,EUR,SP00,A,2030-04-10,2.0000\n"
    "EXR.D.BBB.EUR.SP00.A,D,BBB,EUR,SP00,A,2030-04-12,\n"
)

FRIDAY = datetime.datetime(2030, 4, 12, 16, tzinfo=datetime.UTC)


class _Response:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code != 200:
            raise requests.HTTPError(self.status_code)


@pytest.fixture
def ecb(monkeypatch):
    """Answers every request with `ecb.text`, and records the requests."""
    ecb = types.SimpleNamespace(text=RATES, status_code=200, requests=[])

    def get(url, params, timeout):
        ecb.requests.append((url, params))
        return _Response(ecb.text, ecb.status_code)

    monkeypatch.setattr(requests, "get", get)
    return ecb


def _price(ticker):
    return ecb_rates.Source().get_historical_price(ticker, FRIDAY)


def test_a_holiday_takes_the_newest_rate_before_it(ecb):
    price = _price("EUR-AAA")

    assert price.price == decimal.Decimal("1.6")
    assert price.time.date() == datetime.date(2030, 4, 11)
    assert price.quote_currency == "AAA"


def test_a_pair_without_the_euro_is_derived_through_it(ecb):
    price = _price("AAA-BBB")

    assert price.price == decimal.Decimal("1.25")
    # The older of the two rates dates the price.
    assert price.time.date() == datetime.date(2030, 4, 10)
    url, params = ecb.requests[-1]
    assert "D.AAA+BBB.EUR" in url
    assert params["endPeriod"] == "2030-04-12"


def test_the_euro_priced_in_a_currency_inverts_its_rate(ecb):
    assert _price("BBB-EUR").price == decimal.Decimal("0.5")


def test_no_rate_in_reach_gives_no_price(ecb):
    ecb.text = ""

    assert _price("EUR-AAA") is None


def test_an_unknown_currency_fails_loudly(ecb):
    ecb.status_code = 404

    with pytest.raises(requests.HTTPError):
        _price("EUR-ZZZ")
