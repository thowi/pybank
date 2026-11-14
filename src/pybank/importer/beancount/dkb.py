"""DKB CSV importers for beangulp.

Covers the pre-2023 Girokonto export, the current one, and the pre-2023 Visa
export.

The account or card number is read from the file itself and routed to a ledger
account by `routing.AccountRouter`.

Parsing is delegated to the `beancount-dkb` package, which builds transactions
from date, amount, payee and purpose alone. The columns it drops ride along as
metadata, and payee and narration are normalized before the import-id is taken
off them.
"""

import logging
import os
import re
from collections.abc import Mapping

import beangulp
from beancount.core import data, flags
from beancount_dkb import CreditImporter, ECImporter

from ... import csvfile, text
from . import UNCATEGORIZED, identity, routing

# Source columns `beancount-dkb` drops, and the metadata key each lands under.
# Values keep the export's own notation, German decimals included.
_META_COLS = {
    # On foreign-currency purchases. The transaction itself books EUR amount.
    "original-amount": ["Ursprünglicher Betrag"],
    # More stable than a payee name, which the bank rewrites.
    "counterparty-account": ["IBAN", "Kontonummer"],
    # The purchase date, which trails `Wertstellung` by a few days.
    "receipt-date": ["Belegdatum"],
}

_PURPOSE_COL = "Verwendungszweck"
_DAILY_BALANCE = "Tagessaldo"

# The delegate wants an account name even when it is constructed only to
# identify a file, where it never reads the name. Use a dummy for that case.
_DUMMY_ACCOUNT = "Assets:Dummy"

logger = logging.getLogger(__name__)


def _source_id(filepath: str, patterns: tuple[str, ...]) -> str | None:
    """Returns the account or card identifier named on the file's first line."""
    try:
        lines = csvfile.read_text(filepath).splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    if not lines:
        return None
    for pattern in patterns:
        match = re.match(pattern, lines[0])
        if match:
            return match.group(1).strip()
    return None


def _aligned_rows(filepath: str, count: int) -> list[dict[str, str]]:
    """Returns one source row per transaction, empty ones if they disagree."""
    # Both readers walk the same rows in the same order, so they line up. A
    # disagreement means an export shape neither of us has seen, where no
    # metadata beats metadata taken from the wrong row.
    _metadata, rows = csvfile.read_path_with_header(filepath)
    # `beancount-dkb` turns `Tagessaldo` rows into `Balance` directives.
    rows = [row for row in rows if row.get(_PURPOSE_COL) != _DAILY_BALANCE]
    if len(rows) == count:
        return rows
    logger.warning(
        "%s: %d rows for %d transactions, dropping the extra metadata.",
        os.path.basename(filepath),
        len(rows),
        count,
    )
    return [{}] * count


def _normalize(txn: data.Transaction) -> data.Transaction:
    """Collapses the padding and shouting DKB puts in payees and purposes."""
    return txn._replace(
        payee=text.normalize_text(txn.payee),
        narration=text.normalize_text(txn.narration),
    )


class _DkbImporter(beangulp.Importer):
    """Shared logic. Checking and card differ only in how they identify."""

    # Matched against the first line. Group 1 is the identifier, which is
    # also what `beancount-dkb` needs back to accept the file.
    _source_patterns: tuple[str, ...] = ()
    _delegate_class: type[beangulp.Importer]
    # Config table this importer takes its accounts from, named in errors.
    _config_table: str = ""

    def __init__(self, accounts: Mapping[str, data.Account], currency: str = "EUR"):
        self._router = routing.AccountRouter(accounts, self._config_table)
        self._currency = currency

    def identify(self, filepath: str) -> bool:
        if not filepath.lower().endswith(".csv"):
            return False
        source_id = _source_id(filepath, self._source_patterns)
        if source_id is None:
            return False
        return bool(self._delegate(source_id, _DUMMY_ACCOUNT).identify(filepath))

    def account(self, filepath: str) -> data.Account:
        return self._router.account_for(self._require_source_id(filepath))

    def extract(self, filepath: str, existing: data.Entries) -> data.Entries:
        source_id = self._require_source_id(filepath)
        account = self._router.account_for(source_id)

        entries = self._delegate(source_id, account).extract(filepath, existing)
        transactions = [_normalize(e) for e in entries if isinstance(e, data.Transaction)]
        rows = _aligned_rows(filepath, len(transactions))
        ids = identity.import_ids(
            [
                identity.IdFields(
                    str(txn.date),
                    identity.canonical_amount(txn.postings[0].units.number),
                    (source_id, txn.payee or "", txn.narration or ""),
                )
                for txn in transactions
            ]
        )
        completed = map(self._complete, transactions, rows, ids)
        return [
            next(completed) if isinstance(entry, data.Transaction) else entry for entry in entries
        ]

    def deduplicate(self, entries: data.Entries, existing: data.Entries) -> None:
        identity.mark_duplicates(entries, existing)

    def _require_source_id(self, filepath: str) -> str:
        source_id = _source_id(filepath, self._source_patterns)
        if source_id is None:
            raise ValueError(f"Not a DKB statement: {filepath}")
        return source_id

    def _delegate(self, source_id: str, account: data.Account) -> beangulp.Importer:
        return self._delegate_class(source_id, account, self._currency)

    def _complete(
        self, txn: data.Transaction, row: dict[str, str], import_id: str
    ) -> data.Transaction:
        """Adds the import-id, dropped columns, contra posting and flag."""
        meta = dict(txn.meta)
        meta[identity.META_KEY] = import_id
        for key, columns in _META_COLS.items():
            value = (csvfile.get_value(row, columns) or "").strip()
            if value:
                meta[key] = value
        contra = data.Posting(UNCATEGORIZED, None, None, None, None, None)
        return txn._replace(
            meta=meta,
            flag=flags.FLAG_WARNING,
            postings=[*txn.postings, contra],
        )


class CheckingImporter(_DkbImporter):
    """DKB checking statement importer."""

    _config_table = "dkb.checking"
    _source_patterns = (
        r'"?Kontonummer:"?;"?(\S+)\s',
        r'"?Girokonto"?[;,]"?([^";,]+)"?',
    )
    _delegate_class = ECImporter


class CreditCardImporter(_DkbImporter):
    """DKB credit card statement importer."""

    _config_table = "dkb.card"
    _source_patterns = (r'"?Kreditkarte:"?;"?([^"]+?)(?: Kreditkarte)?"?;',)
    _delegate_class = CreditImporter
