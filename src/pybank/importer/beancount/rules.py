"""Books rows to the account a categorization rule names.

A `Rule` names a target account and the tests a row must pass. `pybank-import`
reads rules from `rules.toml` next to its `--config`. `book` is the beangulp
hook that applies them.

Which rules may book a row depends on its counter posting:

- On `UNCATEGORIZED`: Every rule.
- With a label from the old export: Only the rules that name this label.
- Any other, a transfer for example: No rule.
"""

import datetime
import logging
import re
from typing import NamedTuple

from beancount.core import data, flags
from beangulp import extract

from . import UNCATEGORIZED, qif
from .hooks import Group, open_slot

CATEGORY_SOURCE_RULE = "rule"

logger = logging.getLogger(__name__)


class Rule(NamedTuple):
    """A categorization rule: A text pattern, filters, and a target account.

    A row that matches the rule books to `book`. `text` searches the payee and
    the narration, joined by a space. The optional filters narrow the match:
    `account` is the statement's own account or one above it, `start` and
    `end` bound the date (both inclusive), and `labels` names the old
    export's labels this rule may override.
    """

    book: data.Account
    text: re.Pattern
    account: data.Account | None = None
    end: datetime.date | None = None
    labels: frozenset[str] = frozenset()
    start: datetime.date | None = None


def _is_open(rule: Rule, counter: data.Posting) -> bool:
    if counter.account == UNCATEGORIZED:
        return True
    return (counter.meta or {}).get(qif.META_QIF_CATEGORY) in rule.labels


def _matches(rule: Rule, txn: data.Transaction) -> bool:
    booked, counter = txn.postings
    if rule.account and not (
        booked.account == rule.account or booked.account.startswith(f"{rule.account}:")
    ):
        return False
    if (rule.start and txn.date < rule.start) or (rule.end and txn.date > rule.end):
        return False
    if not _is_open(rule, counter):
        return False
    return bool(rule.text.search(" ".join(filter(None, [txn.payee, txn.narration]))))


def _booked(rule: Rule, txn: data.Transaction) -> data.Transaction:
    booked, counter = txn.postings
    meta = {**txn.meta, qif.META_CATEGORY_SOURCE: CATEGORY_SOURCE_RULE}
    # A rule that books to UNCATEGORIZED sends a labeled row back to review.
    flag = flags.FLAG_WARNING if rule.book == UNCATEGORIZED else flags.FLAG_OKAY
    counter = counter._replace(account=rule.book)
    return txn._replace(meta=meta, flag=flag, postings=[booked, counter])


def _first_match(rules: list[Rule], entry: data.Directive) -> int | None:
    """Returns the index of the first rule that matches, if any."""
    if not isinstance(entry, data.Transaction):
        return None
    # beangulp prints a duplicate as a comment, so booking it books nothing.
    if entry.meta.get(extract.DUPLICATE) or open_slot(entry, None) is None:
        return None
    return next((i for i, rule in enumerate(rules) if _matches(rule, entry)), None)


def book(rules: list[Rule], extracted: list[Group], existing: data.Entries) -> list[Group]:
    """Books every open row to the account of the first rule it matches.

    Run it after the transfer hooks, so a transfer is booked before any rule
    sees it. Logs a warning for each rule that matched no row.
    """
    if not rules:
        return extracted
    counts = [0] * len(rules)
    result = []
    for filepath, entries, account, importer in extracted:
        kept = []
        for entry in entries:
            index = _first_match(rules, entry)
            if index is not None:
                counts[index] += 1
                entry = _booked(rules[index], entry)
            kept.append(entry)
        result.append((filepath, kept, account, importer))
    logger.info("Booked %d rows by rule.", sum(counts))
    for i, (rule, count) in enumerate(zip(rules, counts, strict=True)):
        if not count:
            logger.warning("Rule #%d (%s) matched no row.", i + 1, rule.text.pattern)
    return result
