"""Pairs transfer legs between own accounts.

A leg is a row on an own account whose other posting is still uncategorized
or already in the clearing account.
Two legs are a *candidate pair* when money leaves one account and arrives on
another within `_WINDOW`, and neither leg fits any other leg.
Legs in one currency fit when the amounts match.
The two looser fits below need one leg known to be a transfer, one already in
the clearing account:
Legs in different currencies fit when their implied rate is within `_RATE_BAND`
of the market rate the ledger's prices give for that day.
Two legs in one currency that match nothing exactly also fit when the receiver
got up to `_FEE_SHARE` or `_FEE_FLOOR` less, the fee a bank on the way kept.
Booking puts that fee on `BANK_FEES`.

A candidate can still be wrong: Two unrelated rows can carry the same amount.
So a candidate books on its own only when `books_unasked` says it is sure, and
any other only once a person confirms it. `choices` lists each transfer no
candidate settles, with the legs it fits, so a person can pick its partner.
`load_answers` reads the answers, which are keyed by the import-ids of both
legs, `save_answer` appends one, and `book` is the beangulp hook that books
the pairs. Run it after `transfer_hints.book`, for the same reason that one
runs after `qif_sidecar.donate`.

`unpaired` reads a whole ledger and returns the clearing postings that nothing
cancels, which is what keeps the clearing account from zero.
"""

import bisect
import collections
import datetime
import decimal
import json
import logging
import tomllib
from collections.abc import Callable, Iterable
from typing import NamedTuple

from beancount.core import amount, data, flags, prices
from beangulp import extract

from . import IN_TRANSIT, UNCATEGORIZED, identity, qif, routing
from .hooks import Group, open_slot

CATEGORY_SOURCE_PAIR = "pair"
CATEGORY_SOURCE_AUTO = "pair-auto"

# How far apart the two banks may date one transfer. A cross-border transfer
# takes a few business days, and a weekend can sit in between.
_WINDOW = datetime.timedelta(days=7)

# How far a cross-currency pair's rate may stray from the market rate. Banks
# charge a spread on the rate, and a fixed fee weighs more on a small amount.
_RATE_BAND = decimal.Decimal("0.05")

# The largest fee a bank on the way may keep: A share of the amount, or the
# floor, in the transfer's currency.
_FEE_SHARE = decimal.Decimal("0.005")
_FEE_FLOOR = decimal.Decimal(10)

BANK_FEES = "Expenses:Fees:Bank"

logger = logging.getLogger(__name__)

# One answer per pair, keyed by the import-ids of both legs.
Answers = dict[frozenset[str], bool]


class Leg(NamedTuple):
    import_id: str
    txn: data.Transaction

    @property
    def units(self) -> amount.Amount:
        return self.txn.postings[0].units


class Choice(NamedTuple):
    """A transfer no candidate settles, with the legs it fits, nearest first."""

    leg: Leg
    options: list[Leg]


class Pair(NamedTuple):
    """`sender` is the leg the money leaves, `receiver` the leg it reaches."""

    sender: Leg
    receiver: Leg

    @property
    def key(self) -> frozenset[str]:
        return frozenset((self.sender.import_id, self.receiver.import_id))


def _leg(entry: data.Directive) -> Leg | None:
    """Returns the entry as a leg, if it can be one half of a transfer."""
    if not isinstance(entry, data.Transaction):
        return None
    # beangulp prints a duplicate as a comment, so booking it books nothing.
    if entry.meta.get(extract.DUPLICATE):
        return None
    if open_slot(entry, (IN_TRANSIT, UNCATEGORIZED)) is None:
        return None
    import_id = entry.meta.get(identity.META_KEY)
    if import_id is None:
        return None
    return Leg(import_id, entry)


def _fits(sender: Leg, receiver: Leg, price_map: prices.PriceMap) -> bool:
    sent, received = -sender.units.number, receiver.units.number
    if sender.units.currency == receiver.units.currency:
        return sent == received
    currencies = (sender.units.currency, receiver.units.currency)
    _, market = prices.get_price(price_map, currencies, sender.txn.date)
    if not market:
        return False
    return abs(received / sent / market - 1) <= _RATE_BAND


def _fits_with_fee(sender: Leg, receiver: Leg) -> bool:
    if sender.units.currency != receiver.units.currency:
        return False
    sent = -sender.units.number
    return 0 < sent - receiver.units.number <= max(sent * _FEE_SHARE, _FEE_FLOOR)


def _fit_map(legs: list[Leg], fits: Callable[[Leg, Leg], bool]) -> dict[str, list[Leg]]:
    """Returns the legs each leg fits within `_WINDOW`, keyed by import-id."""
    senders = [leg for leg in legs if leg.units.number < 0]
    receivers = sorted((leg for leg in legs if leg.units.number > 0), key=lambda leg: leg.txn.date)
    dates = [leg.txn.date for leg in receivers]

    result: dict[str, list[Leg]] = {}
    for sender in senders:
        start = bisect.bisect_left(dates, sender.txn.date - _WINDOW)
        end = bisect.bisect_right(dates, sender.txn.date + _WINDOW)
        for receiver in receivers[start:end]:
            if sender.txn.postings[0].account == receiver.txn.postings[0].account:
                continue
            if fits(sender, receiver):
                result.setdefault(sender.import_id, []).append(receiver)
                result.setdefault(receiver.import_id, []).append(sender)
    return result


def _is_transfer(leg: Leg) -> bool:
    return leg.txn.postings[1].account == IN_TRANSIT


def _has_transfer(sender: Leg, receiver: Leg) -> bool:
    return _is_transfer(sender) or _is_transfer(receiver)


def _all_fits(
    entries: Iterable[data.Directive], price_map: prices.PriceMap
) -> tuple[list[Leg], dict[str, list[Leg]]]:
    """Returns every leg, and the legs each one fits, keyed by import-id."""
    legs = [leg for leg in map(_leg, entries) if leg is not None]

    # A rate or a fee explains a gap only when one leg is known to be a
    # transfer. Between two rows nothing marks, such a fit is mostly chance,
    # two purchases that happen to lie close.
    def fits(sender: Leg, receiver: Leg) -> bool:
        if sender.units.currency != receiver.units.currency and not _has_transfer(sender, receiver):
            return False
        return _fits(sender, receiver, price_map)

    def fits_with_fee(sender: Leg, receiver: Leg) -> bool:
        return _has_transfer(sender, receiver) and _fits_with_fee(sender, receiver)

    fit_map = _fit_map(legs, fits)
    # A fee only explains a gap for legs that fit nothing exactly. Otherwise a
    # leg a fee away would make an exact pair ambiguous.
    fit_map |= _fit_map([leg for leg in legs if leg.import_id not in fit_map], fits_with_fee)
    return legs, fit_map


def candidates(entries: Iterable[data.Directive], price_map: prices.PriceMap) -> list[Pair]:
    """Returns every pair of legs that fit each other and nothing else."""
    legs, fits = _all_fits(entries, price_map)
    senders = [leg for leg in legs if leg.units.number < 0]

    result = []
    for sender in senders:
        matched = fits.get(sender.import_id, [])
        if len(matched) != 1 or len(fits[matched[0].import_id]) != 1:
            continue
        pair = Pair(sender, matched[0])
        # A pair already booked only counted above, to spot ambiguity.
        if _needs_booking(pair):
            result.append(pair)
    return result


def choices(entries: Iterable[data.Directive], price_map: prices.PriceMap) -> list[Choice]:
    """Returns the transfers no candidate settles, with the legs they fit.

    A transfer is a clearing posting that nothing cancels. Its options are
    the legs it fits that are uncategorized or uncancelled too, nearest in
    date first. Oldest transfer first.
    """
    # Only a known transfer asks. An uncategorized row fits many others by
    # chance, and most of those are purchases.
    entries = list(entries)
    legs, fits = _all_fits(entries, price_map)
    uncancelled = {id(txn) for txn, _ in unpaired(entries)}

    def is_open(leg: Leg) -> bool:
        return leg.txn.postings[1].account == UNCATEGORIZED or id(leg.txn) in uncancelled

    def in_candidate(leg: Leg) -> bool:
        matched = fits.get(leg.import_id, [])
        return len(matched) == 1 and len(fits[matched[0].import_id]) == 1

    result = []
    for leg in sorted(legs, key=lambda leg: leg.txn.date):
        if id(leg.txn) not in uncancelled or in_candidate(leg):
            continue
        options = [option for option in fits.get(leg.import_id, []) if is_open(option)]
        if options:
            options.sort(key=lambda option: abs(option.txn.date - leg.txn.date))
            result.append(Choice(leg, options))
    return result


def books_unasked(pair: Pair) -> bool:
    """Returns whether the pair is sure enough to book without an answer.

    It is when both legs are known transfers, or when one is and the amounts
    match exactly.
    """
    # A rate or a fee fit with one known leg is not sure enough. The known leg
    # can come from an account with no importer. Then its true partner is
    # missing, and a purchase near the amount takes its place.
    if all(map(_is_transfer, pair)):
        return True
    return _has_transfer(*pair) and -pair.sender.units == pair.receiver.units


def pair_of(leg: Leg, other: Leg) -> Pair:
    """Returns the two legs as a pair, the money leaving first."""
    return Pair(*sorted((leg, other), key=lambda leg: leg.units.number))


def _needs_booking(pair: Pair) -> bool:
    # Two clearing postings that cancel are booked, also through a rate.
    if not all(map(_is_transfer, pair)):
        return True
    return _cleared_units(pair.sender) != -_cleared_units(pair.receiver)


def _cleared_units(leg: Leg) -> amount.Amount:
    # Before the ledger is loaded, the contra posting of a row has no units.
    return leg.txn.postings[1].units or -leg.units


def load_answers(path: str) -> Answers:
    """Reads the answers file, or returns no answers if there is none yet."""
    try:
        with open(path, "rb") as f:
            content = tomllib.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as err:
        raise routing.ConfigError(f"Cannot read {path}: {err}") from err
    answers = {}
    for i, pair in enumerate(content.get("pair", [])):
        legs = pair.get("legs") if isinstance(pair, dict) else None
        confirmed = pair.get("confirmed") if isinstance(pair, dict) else None
        if not (
            isinstance(legs, list)
            and all(isinstance(leg, str) for leg in legs)
            and len(set(legs)) == 2
            and isinstance(confirmed, bool)
        ):
            raise routing.ConfigError(f"{path}: [[pair]] #{i + 1} needs two legs and confirmed")
        answers[frozenset(legs)] = confirmed
    return answers


def save_answer(path: str, pair: Pair, confirmed: bool) -> None:
    """Appends the answer on one pair to the answers file."""
    # Appending keeps what the file already holds, comments and hand edits too.
    # Hand edits must use `[[pair]]` tables, since an inline `pair = [...]`
    # takes no more. A JSON array of strings is valid TOML.
    legs = json.dumps([pair.sender.import_id, pair.receiver.import_id])
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n[[pair]]\nlegs = {legs}\nconfirmed = {str(confirmed).lower()}\n")


def _booked_pair(pair: Pair, source: str) -> tuple[data.Transaction, data.Transaction]:
    """Returns both legs, booked through the clearing account."""
    sender, receiver = (_cleared(leg.txn, source) for leg in pair)
    sent, received = pair.sender.units, pair.receiver.units
    if sent.currency != received.currency:
        # The clearing account holds the sender's currency, and the receiving
        # leg converts it at the rate the banks applied.
        # A quotient rarely terminates. Eight places keep the rounding error far
        # below a cent on any amount a transfer carries.
        rate = (received.number / -sent.number).quantize(decimal.Decimal("1e-8"))
        price = amount.Amount(rate, received.currency)
        contra = receiver.postings[1]._replace(units=sent, price=price)
        receiver = receiver._replace(postings=[receiver.postings[0], contra])
    elif _fits_with_fee(*pair):
        # The clearing account takes back what was sent, and the receiving
        # leg books what did not arrive as the fee. Any other gap stays in
        # the clearing account, where `unpaired` reports it.
        contra = receiver.postings[1]._replace(units=sent)
        fee = amount.Amount(-sent.number - received.number, sent.currency)
        fee_posting = data.Posting(BANK_FEES, fee, None, None, None, None)
        receiver = receiver._replace(postings=[receiver.postings[0], contra, fee_posting])
    return sender, receiver


def _cleared(txn: data.Transaction, source: str) -> data.Transaction:
    contra = txn.postings[1]
    if contra.account == IN_TRANSIT:
        return txn
    meta = {**txn.meta, qif.META_CATEGORY_SOURCE: source}
    postings = [txn.postings[0], contra._replace(account=IN_TRANSIT)]
    return txn._replace(meta=meta, flag=flags.FLAG_OKAY, postings=postings)


def _confirmed(answers: Answers, legs: dict[str, Leg]) -> list[Pair]:
    """Returns the confirmed pairs whose legs are both at hand."""
    # A confirmed pair books even when it is no candidate any more. A row that
    # arrived later can make a pair ambiguous, which the answer has settled.
    result = []
    for key, confirmed in answers.items():
        found = [legs[i] for i in key if i in legs]
        if confirmed and len(found) == 2:
            result.append(pair_of(*found))
    return result


def book(answers: Answers, extracted: list[Group], existing: data.Entries) -> list[Group]:
    """Books every confirmed pair, and every unanswered one `books_unasked`.

    Both go through `IN_TRANSIT`. The `category-source` of a booked leg tells
    the two apart, so the pairs no one confirmed can be listed for review.
    """
    entries = [entry for _, group, _, _ in extracted for entry in group]
    legs = {leg.import_id: leg for leg in map(_leg, entries) if leg is not None}

    found = candidates(entries, prices.build_price_map(existing))
    confirmed = _confirmed(answers, legs)
    # An answer wins: A rejection undoes a wrong match, and a leg of a confirmed
    # pair is taken.
    taken = {import_id for pair in confirmed for import_id in pair.key}
    sure = [
        pair
        for pair in found
        if books_unasked(pair) and pair.key not in answers and pair.key.isdisjoint(taken)
    ]

    replaced: dict[int, data.Transaction] = {}
    for pairs, source in ((sure, CATEGORY_SOURCE_AUTO), (confirmed, CATEGORY_SOURCE_PAIR)):
        for pair in pairs:
            for leg, booked in zip(pair, _booked_pair(pair, source), strict=True):
                replaced[id(leg.txn)] = booked
    logger.info("Booked %d confirmed transfer pairs.", len(confirmed))
    logger.info("Booked %d transfer pairs unasked.", len(sure))

    unanswered = sum(pair.key not in answers and not books_unasked(pair) for pair in found)
    if unanswered:
        logger.warning("%d transfer pairs await an answer.", unanswered)

    return [
        (filepath, [replaced.get(id(entry), entry) for entry in group], account, importer)
        for filepath, group, account, importer in extracted
    ]


def unpaired(entries: Iterable[data.Directive]) -> list[tuple[data.Transaction, data.Posting]]:
    """Returns the clearing postings that no other clearing posting cancels."""
    # Two postings cancel when they carry opposite amounts in one currency
    # within `_WINDOW`. One sweep in date order cancels each posting with the
    # oldest open one of the other sign. A nearest-first choice can strand two
    # legs that this pairs. The open ones never mix signs, since any two in
    # reach of each other would have cancelled.
    legs = sorted(
        (
            (entry, posting)
            for entry in entries
            if isinstance(entry, data.Transaction)
            for posting in entry.postings
            if posting.account == IN_TRANSIT and posting.units and posting.units.number
        ),
        key=lambda leg: leg[0].date,
    )
    open_legs: dict[tuple[str, decimal.Decimal], collections.deque] = collections.defaultdict(
        collections.deque
    )
    result = []
    for entry, posting in legs:
        units = posting.units
        queue = open_legs[(units.currency, abs(units.number))]
        while queue and entry.date - queue[0][0].date > _WINDOW:
            result.append(queue.popleft())
        if queue and (queue[0][1].units.number > 0) != (units.number > 0):
            queue.popleft()
        else:
            queue.append((entry, posting))
    for queue in open_legs.values():
        result.extend(queue)
    return sorted(result, key=lambda leg: leg[0].date)
