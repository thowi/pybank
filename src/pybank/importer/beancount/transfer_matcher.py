"""Pairs transfer legs between own accounts.

A leg is a row on an own account whose other posting is still uncategorized
or already in the clearing account.
Two legs are a *candidate pair* when money leaves one account and arrives on
another within `_WINDOW`, and neither leg fits any other leg.
Legs in different currencies fit when their implied rate is within `_RATE_BAND`
of the market rate the ledger's prices give for that day.

A candidate can still be wrong: Two unrelated rows can carry the same amount.
So only confirmed pairs are booked. `load_answers` reads the answers, which are
keyed by the import-ids of both legs, and `book` is the beangulp hook that books
the confirmed pairs. Run it after `transfer_hints.book`, for the same reason
that one runs after `qif_sidecar.donate`.
"""

import bisect
import datetime
import decimal
import logging
import tomllib
from collections.abc import Iterable
from typing import NamedTuple

import beangulp
from beancount.core import amount, data, flags, prices
from beangulp import extract

from . import IN_TRANSIT, UNCATEGORIZED, identity, qif, routing
from .qif_sidecar import open_slot

CATEGORY_SOURCE_PAIR = "pair"

# How far apart the two banks may date one transfer. A cross-border transfer
# takes a few business days, and a weekend can sit in between.
_WINDOW = datetime.timedelta(days=7)

# How far a cross-currency pair's rate may stray from the market rate. Banks
# charge a spread on the rate, and a fixed fee weighs more on a small amount.
_RATE_BAND = decimal.Decimal("0.05")

logger = logging.getLogger(__name__)

# What beangulp hands to a hook, one per imported file.
_Group = tuple[str, data.Entries, data.Account, beangulp.Importer]

# One answer per pair, keyed by the import-ids of both legs.
Answers = dict[frozenset[str], bool]


class Leg(NamedTuple):
    import_id: str
    txn: data.Transaction

    @property
    def units(self) -> amount.Amount:
        return self.txn.postings[0].units


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
    if sender.txn.postings[0].account == receiver.txn.postings[0].account:
        return False
    sent, received = -sender.units.number, receiver.units.number
    if sender.units.currency == receiver.units.currency:
        return sent == received
    currencies = (sender.units.currency, receiver.units.currency)
    _, market = prices.get_price(price_map, currencies, sender.txn.date)
    if not market:
        return False
    return abs(received / sent / market - 1) <= _RATE_BAND


def candidates(entries: Iterable[data.Directive], price_map: prices.PriceMap) -> list[Pair]:
    """Returns every pair of legs that fit each other and nothing else."""
    legs = [leg for leg in map(_leg, entries) if leg is not None]
    senders = [leg for leg in legs if leg.units.number < 0]
    receivers = sorted((leg for leg in legs if leg.units.number > 0), key=lambda leg: leg.txn.date)
    dates = [leg.txn.date for leg in receivers]

    fits: dict[str, list[Leg]] = {}
    for sender in senders:
        start = bisect.bisect_left(dates, sender.txn.date - _WINDOW)
        end = bisect.bisect_right(dates, sender.txn.date + _WINDOW)
        for receiver in receivers[start:end]:
            if _fits(sender, receiver, price_map):
                fits.setdefault(sender.import_id, []).append(receiver)
                fits.setdefault(receiver.import_id, []).append(sender)

    result = []
    for sender in senders:
        matched = fits.get(sender.import_id, [])
        if len(matched) != 1 or len(fits[matched[0].import_id]) != 1:
            continue
        pair = Pair(sender, matched[0])
        # Two legs already in the clearing account in one currency cancel out
        # without anyone's say. They only counted above, to spot ambiguity.
        if _needs_booking(pair):
            result.append(pair)
    return result


def _needs_booking(pair: Pair) -> bool:
    if pair.sender.units.currency != pair.receiver.units.currency:
        return True
    return any(leg.txn.postings[1].account == UNCATEGORIZED for leg in pair)


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


def _booked_pair(pair: Pair) -> tuple[data.Transaction, data.Transaction]:
    """Returns both legs, booked through the clearing account."""
    sender, receiver = (_cleared(leg.txn) for leg in pair)
    if pair.sender.units.currency != pair.receiver.units.currency:
        # The clearing account holds the sender's currency, and the receiving
        # leg converts it at the rate the banks applied.
        sent, received = pair.sender.units, pair.receiver.units
        # A quotient rarely terminates. Eight places keep the rounding error far
        # below a cent on any amount a transfer carries.
        rate = (received.number / -sent.number).quantize(decimal.Decimal("1e-8"))
        price = amount.Amount(rate, received.currency)
        contra = receiver.postings[1]._replace(units=sent, price=price)
        receiver = receiver._replace(postings=[receiver.postings[0], contra])
    return sender, receiver


def _cleared(txn: data.Transaction) -> data.Transaction:
    contra = txn.postings[1]
    if contra.account == IN_TRANSIT:
        return txn
    meta = {**txn.meta, qif.META_CATEGORY_SOURCE: CATEGORY_SOURCE_PAIR}
    postings = [txn.postings[0], contra._replace(account=IN_TRANSIT)]
    return txn._replace(meta=meta, flag=flags.FLAG_OKAY, postings=postings)


def _confirmed(answers: Answers, legs: dict[str, Leg]) -> list[Pair]:
    """Returns the confirmed pairs whose legs are both at hand."""
    # A confirmed pair books even when it is no candidate any more. A row that
    # arrived later can make a pair ambiguous, which the answer has settled.
    result = []
    for key, confirmed in answers.items():
        found = sorted((legs[i] for i in key if i in legs), key=lambda leg: leg.units.number)
        if confirmed and len(found) == 2:
            result.append(Pair(*found))
    return result


def book(answers: Answers, extracted: list[_Group], existing: data.Entries) -> list[_Group]:
    """Books every confirmed pair through `IN_TRANSIT`."""
    entries = [entry for _, group, _, _ in extracted for entry in group]
    legs = {leg.import_id: leg for leg in map(_leg, entries) if leg is not None}

    replaced: dict[int, data.Transaction] = {}
    pairs = _confirmed(answers, legs)
    for pair in pairs:
        for leg, booked in zip(pair, _booked_pair(pair), strict=True):
            replaced[id(leg.txn)] = booked
    logger.info("Booked %d confirmed transfer pairs.", len(pairs))

    found = candidates(entries, prices.build_price_map(existing))
    unanswered = sum(pair.key not in answers for pair in found)
    if unanswered:
        logger.warning("%d transfer pairs await an answer.", unanswered)

    return [
        (filepath, [replaced.get(id(entry), entry) for entry in group], account, importer)
        for filepath, group, account, importer in extracted
    ]
