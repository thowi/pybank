"""A person's review of transfer pairs, apart from how they are asked.

A command line or a web page renders these and asks. A `Session` holds the
answers given so far. `pending_pairs` lists the candidates that need a yes or
no, `choices` the transfers that need a partner picked, and `open_options` the
options of one that are still open. `answer_pair` and `answer_choice` save an
answer. `rate_check` compares a pair in two currencies to the market.
"""

import datetime
import decimal
from typing import NamedTuple

from beancount.core import amount, data, prices

from . import transfer_matcher
from .transfer_matcher import Choice, Leg, Pair

_CENT = decimal.Decimal("0.01")


class RateCheck(NamedTuple):
    """The rate a pair in two currencies implies, and the market's that day.

    Rates are in `quote` per one `base`. The market fields are None when the
    ledger holds no price. A spread is negative when the rate beat the market.
    """

    # The currency worth more.
    base: str
    implied: decimal.Decimal
    market: decimal.Decimal | None
    market_date: datetime.date | None
    quote: str
    # What the receiver lost against the market rate, in the sent currency.
    spread: amount.Amount | None
    # `spread` as a share of what was sent.
    spread_share: decimal.Decimal | None


def rate_check(pair: Pair, price_map: prices.PriceMap) -> RateCheck | None:
    """Returns the rate check of a pair in two currencies, else None."""
    sent, received = -pair.sender.units, pair.receiver.units
    if sent.currency == received.currency:
        return None
    # One unit of the currency with fewer units buys more than one of the other.
    base, quote = (sent, received) if sent.number <= received.number else (received, sent)
    implied = quote.number / base.number
    day = pair.sender.txn.date
    market_date, market = prices.get_price(price_map, (base.currency, quote.currency), day)
    check = RateCheck(
        base=base.currency,
        implied=implied,
        market=None,
        market_date=None,
        quote=quote.currency,
        spread=None,
        spread_share=None,
    )
    if not market:
        return check
    _, back = prices.get_price(price_map, (received.currency, sent.currency), day)
    # Cents, even where the statement writes a round sum without decimals.
    spread = (sent.number - received.number * back).quantize(_CENT)
    return check._replace(
        market=market,
        market_date=market_date,
        spread=amount.Amount(spread, sent.currency),
        spread_share=spread / sent.number,
    )


class Session:
    """One review of the ledger's transfer pairs, answers saved to `path`."""

    def __init__(self, path: str, entries: data.Entries):
        self.path = path
        self.entries = entries
        self.price_map = prices.build_price_map(entries)
        self.answers = transfer_matcher.load_answers(path)
        # A leg of a confirmed pair is taken. A fee pair books its receiver
        # beyond what a leg can be, so its sender would otherwise seek a new
        # partner.
        self.taken = {
            import_id for key, confirmed in self.answers.items() if confirmed for import_id in key
        }

    def pending_pairs(self) -> list[Pair]:
        """Returns the unanswered candidates that a rebuild would not book."""
        # A rebuild books a sure pair in one currency. One in two currencies
        # needs prices, which `extract` may lack.
        return [
            pair
            for pair in transfer_matcher.candidates(self.entries, self.price_map)
            if pair.key not in self.answers
            and pair.key.isdisjoint(self.taken)
            and not (
                transfer_matcher.books_unasked(pair)
                and pair.sender.units.currency == pair.receiver.units.currency
            )
        ]

    def answer_pair(self, pair: Pair, confirmed: bool) -> None:
        """Saves the answer to the answers file and the session."""
        transfer_matcher.save_answer(self.path, pair, confirmed)
        self.answers[pair.key] = confirmed
        if confirmed:
            self.taken.update(pair.key)

    def choices(self) -> list[Choice]:
        return transfer_matcher.choices(self.entries, self.price_map)

    def open_options(self, choice: Choice) -> list[Leg]:
        """Returns the options still open, none if the transfer is taken."""
        # An answer earlier in this session can take a leg, or settle an option.
        if choice.leg.import_id in self.taken:
            return []
        return [
            option
            for option in choice.options
            if option.import_id not in self.taken
            and transfer_matcher.pair_of(choice.leg, option).key not in self.answers
        ]

    def answer_choice(self, leg: Leg, options: list[Leg], picked: Leg | None) -> None:
        """Confirms the picked option. None rejects every option shown."""
        # Rejecting the rest is what keeps a rerun from asking again.
        for option in options:
            if picked is None or option is picked:
                self.answer_pair(transfer_matcher.pair_of(leg, option), option is picked)
