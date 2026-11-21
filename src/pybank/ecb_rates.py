"""A bean-price source for the ECB euro reference rates.

A ticker is `BASE-QUOTE`, such as `USD-CHF`: The price of one BASE in QUOTE.

Declare it on a commodity as `price: "CHF:pybank.ecb_rates/USD-CHF"`.
"""

import csv
import datetime
import decimal
import io

import requests
from beanprice import source
from requests import adapters
from urllib3.util import retry

_URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.{}.EUR.SP00.A"

# bean-price asks once per date, and one failed request ends its whole run.
# The ECB API may fail with a timeout or a 5xx.
_SESSION = requests.Session()
_SESSION.mount(
    "https://",
    adapters.HTTPAdapter(
        max_retries=retry.Retry(
            backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504), total=6
        )
    ),
)

# Reaches past the longest run of days without a rate, the turn of the year.
_LOOKBACK = datetime.timedelta(days=14)

# The ECB publishes five significant digits, and a cross rate adds no more.
_PLACES = decimal.Decimal("1e-6")

_TIMEOUT_SECONDS = 30

Rate = tuple[datetime.date, decimal.Decimal]


class Source(source.Source):
    """Quotes a ticker from the ECB reference rates.

    The ECB quotes every currency against the euro, so a pair without the euro
    is derived through it. A day without a rate, such as a weekend or an ECB
    holiday, takes the newest rate before it.
    """

    def get_latest_price(self, ticker: str) -> source.SourcePrice | None:
        return _quote(ticker, datetime.datetime.now(datetime.UTC).date())

    def get_historical_price(
        self, ticker: str, time: datetime.datetime
    ) -> source.SourcePrice | None:
        return _quote(ticker, time.date())


def _quote(ticker: str, day: datetime.date) -> source.SourcePrice | None:
    base, quote = ticker.split("-")
    rates = {"EUR": (day, decimal.Decimal(1)), **_euro_rates({base, quote} - {"EUR"}, day)}
    if base not in rates or quote not in rates:
        return None
    (base_day, base_rate), (quote_day, quote_rate) = rates[base], rates[quote]
    price = (quote_rate / base_rate).quantize(_PLACES)
    # Noon UTC is the same calendar day in nearly every timezone, and
    # bean-price dates the price in the local one.
    time = datetime.datetime.combine(min(base_day, quote_day), datetime.time(12), datetime.UTC)
    return source.SourcePrice(price, time, quote)


def _euro_rates(currencies: set[str], day: datetime.date) -> dict[str, Rate]:
    """Returns the newest rate of one euro in each currency, up to `day`."""
    if not currencies:
        return {}
    params = {
        "detail": "dataonly",
        "endPeriod": day.isoformat(),
        "format": "csvdata",
        "startPeriod": (day - _LOOKBACK).isoformat(),
    }
    url = _URL.format("+".join(sorted(currencies)))
    response = _SESSION.get(url, params=params, timeout=_TIMEOUT_SECONDS)
    response.raise_for_status()
    rates: dict[str, Rate] = {}
    for row in csv.DictReader(io.StringIO(response.text)):
        # The ECB lists its holidays with an empty rate.
        if not row["OBS_VALUE"]:
            continue
        rate = (datetime.date.fromisoformat(row["TIME_PERIOD"]), decimal.Decimal(row["OBS_VALUE"]))
        currency = row["CURRENCY"]
        if currency not in rates or rate[0] > rates[currency][0]:
            rates[currency] = rate
    return rates
