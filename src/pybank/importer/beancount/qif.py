"""QIF importer for beangulp.

Reads a Quicken Interchange Format export covering many accounts at once,
categories included. Those categories were assigned inside the exporting app
rather than guessed from a bank's own labels, which is what makes such an
export worth reading.

Written against SEE Finance, which is the only export it has been tested on.
QIF fixes neither the date format nor the decimal separator, so `_DATE_FORMAT`
and `_number` encode one app's choices and another app needs its own. So does
`_SPLIT_MARKER`, the word the exporter puts in the category field of a split.

Only bank and credit card accounts are read. QIF carries no lots and no
prices, so a broker's own export books an investment account better than this
one can.

The format carries no currency and no running balance, so it yields no
`balance` assertion. Currency comes from the account mapping, which also
filters: An account absent from it is skipped.

Category accounts derive themselves, since the export declares each category
as income or expense. Only the awkward labels need a mapping.
"""

import datetime
import decimal
import logging
import re
from collections.abc import Iterator, Mapping, Sequence
from typing import NamedTuple

import beangulp
from beancount.core import amount, data, flags

from ... import csvfile, text
from . import IN_TRANSIT, OPENING_BALANCES, UNCATEGORIZED, identity

# Records under `!Account` declare accounts while AutoSwitch is on. Once it is
# cleared, a one-record `!Account` section selects the account that the
# transaction sections after it belong to.
_SET_AUTOSWITCH = "!Option:AutoSwitch"
_CLEAR_AUTOSWITCH = "!Clear:AutoSwitch"
_ACCOUNTS = "!Account"
_CATEGORIES = "!Type:Cat"
_TRANSACTIONS = ("!Type:Bank", "!Type:CCard")

_NAME = "N"
_INCOME = "I"

_DATE = "D"
_AMOUNT = "T"
_REFERENCE = "N"
_PAYEE = "P"
_MEMO = "M"
_CATEGORY = "L"
_SPLIT_CATEGORY = "S"
_SPLIT_MEMO = "E"
_SPLIT_AMOUNT = "$"

_DATE_FORMAT = "%d.%m.%Y"

# What the exporter writes in the category field of a split, in place of a
# category. It can arrive without any leg, and then the breakdown is gone.
_SPLIT_MARKER = "Split"

_INCOME_ROOT = "Income"
_EXPENSES_ROOT = "Expenses"
_SEP = ":"
_NON_COMPONENT = re.compile(r"[^0-9A-Za-z]+")

# What the file starts with. Per-account QIF exports carry no account list.
_SNIFF_BYTES = 1024

# The old app's own words, kept verbatim so a later remapping has something to
# remap from. All three sit on the counter posting rather than the
# transaction, because a split labels each leg separately.
META_QIF_CATEGORY = "qif-category"
META_QIF_TRANSFER = "qif-transfer"
META_SPLIT_MEMO = "split-memo"

# Marks a category the old app's user assigned by hand, as opposed to one a
# rule guessed later. See the phase 3 plan.
META_CATEGORY_SOURCE = "category-source"
CATEGORY_SOURCE_QIF = "qif"

logger = logging.getLogger(__name__)

# One `(code, value)` pair per QIF line, in file order. Split legs repeat their
# codes, so the order is what pairs them up.
_Record = tuple[tuple[str, str], ...]
_Section = tuple[str, list[_Record]]


class Target(NamedTuple):
    """Where one account named in the export lands in the ledger."""

    account: data.Account
    currency: str


class _Leg(NamedTuple):
    """One counter-posting: A category, a `[transfer]`, or an empty label."""

    label: str
    memo: str | None
    number: decimal.Decimal


class _Transaction(NamedTuple):
    date: datetime.date
    legs: tuple[_Leg, ...]
    narration: str | None
    number: decimal.Decimal
    payee: str | None
    reference: str | None
    source: str


def _read_sections(content: str) -> list[_Section]:
    """Splits a QIF file into `!header` sections of `^`-terminated records."""
    sections: list[_Section] = []
    header, records, fields = "", [], []
    for line in content.splitlines():
        if line.startswith("!"):
            if fields:
                records.append(tuple(fields))
            if header or records:
                sections.append((header, records))
            header, records, fields = line, [], []
        elif line == "^":
            if fields:
                records.append(tuple(fields))
            fields = []
        elif line:
            fields.append((line[0], line[1:]))
    if fields:
        records.append(tuple(fields))
    if header or records:
        sections.append((header, records))
    return sections


def _first(record: _Record, code: str) -> str | None:
    """Returns the first value under `code`, or None if absent or empty."""
    for field_code, value in record:
        if field_code == code:
            return value or None
    return None


def _number(number_str: str) -> decimal.Decimal:
    """Comma thousands separator, dot decimal point."""
    return decimal.Decimal(number_str.replace(",", ""))


def _component(name: str) -> str:
    """Returns one QIF category name part as a Beancount account component."""
    # A component holds letters, digits and dashes, and starts with a capital
    # letter or a digit, so anything else collapses into a dash.
    cleaned = _NON_COMPONENT.sub("-", name).strip("-")
    if not cleaned:
        return "Unknown"
    return cleaned[0].upper() + cleaned[1:]


def _leg_meta(leg: _Leg) -> data.Meta | None:
    """Returns what the export said about this leg, in its own words."""
    meta = {}
    if _is_transfer(leg.label):
        meta[META_QIF_TRANSFER] = leg.label[1:-1]
    elif leg.label:
        meta[META_QIF_CATEGORY] = leg.label
    if leg.memo:
        meta[META_SPLIT_MEMO] = leg.memo
    return meta or None


def _is_transfer(label: str) -> bool:
    return label.startswith("[") and label.endswith("]")


def _category_account(label: str, income: Mapping[str, bool]) -> data.Account:
    """Returns the Beancount account for one QIF category label."""
    root = _INCOME_ROOT if income.get(label) else _EXPENSES_ROOT
    return _SEP.join([root, *(_component(part) for part in label.split(_SEP))])


def _declared_categories(sections: Sequence[_Section]) -> dict[str, bool]:
    """Returns each declared category, mapped to whether it is income."""
    declared = {}
    for header, records in sections:
        if header != _CATEGORIES:
            continue
        for record in records:
            name = _first(record, _NAME)
            if name:
                declared[name] = any(code == _INCOME for code, _ in record)
    return declared


def _legs(record: _Record) -> tuple[_Leg, ...]:
    """Returns the split legs, or one leg carrying the whole amount."""
    legs: list[_Leg] = []
    for code, value in record:
        if code == _SPLIT_CATEGORY:
            legs.append(_Leg(value, None, decimal.Decimal(0)))
        elif not legs:
            continue
        elif code == _SPLIT_MEMO:
            legs[-1] = legs[-1]._replace(memo=text.normalize_text(value) or None)
        elif code == _SPLIT_AMOUNT:
            legs[-1] = legs[-1]._replace(number=_number(value))
    if legs:
        return tuple(legs)
    label = _first(record, _CATEGORY) or ""
    if label == _SPLIT_MARKER:
        logger.warning(
            "The split on %s carries no legs. Leaving it uncategorized.",
            _first(record, _DATE),
        )
        label = ""
    return (_Leg(label, None, _number(_first(record, _AMOUNT) or "0")),)


def _transaction(record: _Record, source: str) -> _Transaction | None:
    """Returns the parsed record, or None if it carries no date or amount."""
    date_str = _first(record, _DATE)
    number_str = _first(record, _AMOUNT)
    if not date_str or number_str is None:
        logger.warning("Skipping a record without a date or an amount.")
        return None
    return _Transaction(
        date=datetime.datetime.strptime(date_str, _DATE_FORMAT).date(),
        legs=_legs(record),
        narration=text.normalize_text(_first(record, _MEMO)),
        number=_number(number_str),
        payee=text.normalize_text(_first(record, _PAYEE)),
        reference=_first(record, _REFERENCE),
        source=source,
    )


def _walk(sections: Sequence[_Section]) -> Iterator[tuple[str, _Record]]:
    """Yields every bank and card record, paired with its account name."""
    autoswitch = False
    source = ""
    for header, records in sections:
        if header == _SET_AUTOSWITCH:
            autoswitch = True
        elif header == _CLEAR_AUTOSWITCH:
            autoswitch = False
        elif header == _ACCOUNTS and not autoswitch and records:
            source = _first(records[0], _NAME) or ""
        elif header in _TRANSACTIONS:
            for record in records:
                yield source, record


class Importer(beangulp.Importer):
    """A QIF export covering every account the app tracked."""

    def __init__(
        self,
        targets: Mapping[str, Target],
        categories: Mapping[str, data.Account] = {},
    ):
        """
        :param targets: Ledger account and currency per account name in the
            export. Accounts left out are skipped.
        :param categories: Ledger account per QIF category label, for the ones
            whose derived name is wrong. Every other label is derived.
        """
        self._targets = targets
        self._categories = categories

    def identify(self, filepath: str) -> bool:
        if not filepath.lower().endswith(".qif"):
            return False
        try:
            with open(filepath, "rb") as f:
                head = f.read(_SNIFF_BYTES)
        except OSError:
            return False
        return _SET_AUTOSWITCH.encode() in head

    def account(self, filepath: str) -> data.Account:
        # The export covers every account at once, so none of them owns the
        # file. beangulp only uses this to name an archive directory.
        return next(iter(self._targets.values())).account

    def extract(self, filepath: str, existing: data.Entries) -> data.Entries:
        sections = _read_sections(csvfile.read_text(filepath))
        income = _declared_categories(sections)

        parsed = []
        skipped: dict[str, int] = {}
        for source, record in _walk(sections):
            if source not in self._targets:
                skipped[source] = skipped.get(source, 0) + 1
                continue
            transaction = _transaction(record, source)
            if transaction is not None:
                parsed.append(transaction)
        for source, count in sorted(skipped.items()):
            logger.info("Skipping %d transactions of unmapped account %s.", count, source)

        ids = identity.import_ids(
            [
                identity.IdFields(
                    str(row.date),
                    identity.canonical_amount(row.number),
                    (row.source, row.narration or "", row.payee or "", row.reference or ""),
                )
                for row in parsed
            ]
        )

        meta = data.new_metadata(filepath, 0)
        entries: data.Entries = []
        for row, import_id in zip(parsed, ids):
            entry_meta = meta.copy()
            entry_meta[identity.META_KEY] = import_id
            entries.append(self._entry(row, entry_meta, income))
        self._warn_undeclared(parsed, income)
        return entries

    def deduplicate(self, entries: data.Entries, existing: data.Entries) -> None:
        identity.mark_duplicates(entries, existing)

    def _entry(
        self, row: _Transaction, meta: data.Meta, income: Mapping[str, bool]
    ) -> data.Transaction:
        target = self._targets[row.source]
        postings = [
            data.Posting(
                target.account,
                amount.Amount(row.number, target.currency),
                None,
                None,
                None,
                None,
            )
        ]
        for leg in row.legs:
            postings.append(
                data.Posting(
                    self._counter_account(leg, income, row.source),
                    amount.Amount(-leg.number, target.currency),
                    None,
                    None,
                    None,
                    _leg_meta(leg),
                )
            )

        if any(leg.label and not _is_transfer(leg.label) for leg in row.legs):
            meta[META_CATEGORY_SOURCE] = CATEGORY_SOURCE_QIF
        flag = flags.FLAG_OKAY if all(leg.label for leg in row.legs) else flags.FLAG_WARNING
        return data.Transaction(
            meta,
            row.date,
            flag,
            row.payee,
            row.narration or "",
            data.EMPTY_SET,
            data.EMPTY_SET,
            postings,
        )

    def _counter_account(self, leg: _Leg, income: Mapping[str, bool], source: str) -> data.Account:
        if not leg.label:
            return UNCATEGORIZED
        if leg.label in self._categories:
            return self._categories[leg.label]
        # QIF records an opening balance as a transfer from the account itself.
        if leg.label == f"[{source}]":
            return OPENING_BALANCES
        # Both legs of a transfer land here and cancel out, so a nonzero
        # clearing balance is the report of what failed to pair up.
        if _is_transfer(leg.label):
            return IN_TRANSIT
        return _category_account(leg.label, income)

    def _warn_undeclared(self, parsed: Sequence[_Transaction], income: Mapping[str, bool]) -> None:
        """Reports labels the export used without declaring them."""
        # An undeclared label has no income flag, so it books as an expense,
        # which is wrong for anything that was really income.
        undeclared = {
            leg.label
            for row in parsed
            for leg in row.legs
            if leg.label
            and not _is_transfer(leg.label)
            and leg.label not in income
            and leg.label not in self._categories
        }
        for label in sorted(undeclared):
            logger.warning(
                "Category %r is not declared in the export, so it books under "
                "%s. Map it in `categories` if that is wrong.",
                label,
                _EXPENSES_ROOT,
            )
