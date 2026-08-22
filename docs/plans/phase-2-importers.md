# Phase 2: Importers on beangulp

Statement files in, `beancount.core.data` directives out. Reuse the existing
per-bank parsing logic, replace the QIF pipeline. Split by difficulty, each
sub-phase ships independently.

## Libraries

Prefer a real dependency. Write our own only where the format demands it.

- **DKB:** Depend on `beancount-dkb` (`ECImporter` and `CreditImporter`,
  documented for beancount 3.x). Its dependency list turned out to be
  `babel`, `beancount` and `beangulp`, the last two of which we already
  have. See 2b.
- **IBKR:** Depend on `ibflex[web]` from PyPI. A parser library, not an
  importer, so it overlaps nothing we write. The `web` extra is not optional
  for us: The package imports its `client` module unconditionally but
  declares `requests` only under that extra, so a bare install fails on
  `import ibflex`.
- **PostFinance:** Ours. See below.

Two independent reasons rule out `tariochbctools`, which was the candidate
for PostFinance.

The packaging one: It declares `ibflex @ git+...`, a direct URL reference.
That kind of reference wins over any registry constraint for the same
package, so depending on it would drag our IBKR path onto an unpinned git
branch, and a direct URL reference in our own metadata rules out publishing.
It has no extras, so all fifteen dependencies (`camelot-py`,
`opencv-python-headless`, `imap-tools` and the rest) are mandatory to get
one CSV parser. Vendoring the file sidesteps that, but not the second
reason.

The fit one, which is decisive: Its importer reads six fixed columns in
`windows_1252` and matches one shape. The archive holds six header
variants across two encodings, so columns get matched by name and the
encoding gets sniffed. Ours does that in about the same number of lines.

Correcting an earlier claim: `balance` assertions do not come for free. Only
the two `Saldo` variants carry a running balance, 6 files of 63. Everything
since, checking and card alike, ships without one. The monthly PDF
Kontoauszüge have the closing balances and are the eventual source. Until
then PostFinance has assertions for one stretch of 2019 to 2022 and none
after, which is a gap in the chain, not a solved problem.

What stays ours regardless: The `import-id` scheme, year-file routing,
categorization rules, and `Assets:Transfers:InTransit` matching.

## Common pattern (established in 2a)

- `beangulp` importer interface: `identify()`, `account()`, `extract()`.
- Each transaction gets the bank leg plus a contra account
  (`Expenses:Uncategorized` with `!` flag until categorized).
- Dedup key in `meta` (`import-id`), dedup against the existing ledger via
  beangulp. See [importing.md](../importing.md).
  Beangulp's own detection is a heuristic comparator: Same accounts, amounts
  within 5 percent, dates within a window. It marks `__duplicate__`, which
  the writer comments out, so it gates. That is the wrong end for us. The
  `import-id` match is the gate and beangulp's comparator supplies the
  warning, which is why `deduplicate()` is overridden rather than extended.
- Hash a canonical amount, not the source string. Exports disagree about
  trailing zeros, and `42.5` and `42.50` hashing differently would reimport
  the same transaction twice.
- `Balance` assertion from the statement balance.
- Writes to the ledger are plain file writes, no special atomicity needed
  (Drive self-heals once a write completes, version history covers crashes).

## 2a: PostFinance

Done. `pybank/importer/beancount/postfinance.py`, with `identity.py`
alongside it for the `import-id` scheme. Verified against all 63 archive
files: Every file is claimed by exactly one importer, 6620 transactions
extract, and the whole set loads with the only errors being the balance
assertions, which fail because the archive itself has holes. See Backfill
in [phase 3](phase-3-backfill-transfers-categorization.md).

Parsing is checked against the bank, not just against itself. In the six
files carrying a running `Saldo` it appears once per day, on that day's
last row, and all 364 day-over-day deltas match the parsed amounts
exactly. That covers signs, the apostrophe thousands separator and row
order at once.

- Checking and credit card CSV importers. Columns matched by name, encoding
  sniffed, since neither is stable across the archive.
- `Kategorie` and `Label`, which only the recent exports carry, are kept as
  `bank-category` and `bank-label` metadata. They are the bank's guess, so
  they stay out of the `import-id`: The bank may revise a label, and that
  must not reimport the transaction. See categorization in
  [phase 3](phase-3-backfill-transfers-categorization.md).
- The card export's `Einkaufsdatum` trails the booking date on almost every
  row and is kept as `receipt-date`, matching the DKB importer's key for the
  same idea.
- Establishes the common pattern above.

## 2b: DKB

Done. `pybank/importer/beancount/dkb.py`, wrapping `beancount-dkb`. Adds
EUR, and proves the abstraction on a second institution.

The library covers all three formats in the archive: The pre-2023 Girokonto
export, the current one, and the Visa export. It pulls in `babel` and
nothing else, and it holds `beangulp` below 0.3.

Two deliberate differences from how it is normally used. It matches a file
against a configured IBAN or card number, which is exactly the data this
repo must never hold, so the identifier is read from the file and handed
back to it. Identification stays structural and no account number lives in
config. And it emits one posting per transaction for a human to complete,
so we append the contra posting and the `!` flag to match the common
pattern above.

Verified against the archive: All 22 DKB and all 63 PostFinance files route
to exactly one importer, none claimed twice. 1803 transactions extract,
each with two postings and a unique `import-id`, and every file yields a
balance assertion, which PostFinance mostly cannot.

Those assertions reconcile. Seeding one opening balance per account clears
every Visa assertion and 13 of the 14 checking ones, so parsed amounts
agree with the bank's own running balance across both format generations.
The one left over is the newest, whose balance is dated about ten weeks
after the last transaction in that export. That is uncovered activity, and
the assertion is what makes the hole visible. See Backfill in
[phase 3](phase-3-backfill-transfers-categorization.md).

- The giro generations never overlap. Legacy ends 2022-12-30, the current
  format starts 2023-01-02, so their differing columns cannot yield two
  IDs for one transaction.
- The library's own `payee_patterns` categorization is left unused. Rules
  live in phase 3, in one place, not split across importers.

## 2c: IBKR

- The hard one: Multi-currency cash, trades with `{cost}` and `@ price`,
  dividends, withholding tax, fees, FX conversions.
- Source: An Activity Flex Query in XML, not the Activity Statement CSVs the
  archive already holds. Flex is the only export carrying `Lot` and
  `TransferLot`, so it is the only one that can produce explicit cost-basis
  lots instead of inferred ones. `ibflex` declares neither `cost` nor
  `openDateTime` on its `TransferLot`, and drops any attribute it has not
  declared without raising, so the importer reads those two straight from the
  XML.
- Instrument identity is the `conid`, not the symbol. IBKR renames a ticker in
  place and reuses one ticker across contracts, and no row anywhere says which
  happened. The map lives in the ledger, on `commodity` directives carrying an
  `ibkr-conid` list, because an incremental import sees one file at a time and
  that file only knows the name current when it was generated. An undeclared
  conid is named after its symbol and reported, so a new one is declared once
  by hand. One commodity may list several conids: IBKR reissues a contract for
  the same listing after a reorg, and those positions never coexist.
- A corporate action is one transaction, however many rows it reports. The
  rows of one action share an `actionID`. Booked apart, each side needs a gain
  of its own to balance and a split reads as a sale.
- The saved query is configured in the IBKR UI, named `pybank`, and selects
  every section the ledger needs. Account Information is deliberately left
  out: Its fields are the holder's name and mailing address, which the
  importer never needs since the account ID appears in every other section.
  The saved Period maxes at 365 days, but the run dialog offers a custom
  date range, so the whole backfill runs through the same query.
- Retires the investment-event class hierarchy: Events become posting shapes.
- FX rounding follows phase 1: Default tolerance, `Equity:Rounding` only if
  real residuals show up. They did, so a residual under a hundredth of a cent
  books there. Anything larger stays an imbalance, since a catch-all posting
  would hide a real gap.

## End of phase

- Retire `convert.py`, the `pybank-convert` entry point, and the six old
  importers under `pybank/importer/`. See
  [phase 5](phase-5-export-extras.md) for what to salvage from three of
  them.
- `qif.py` and `model.py` stay, correcting an earlier claim that they go
  here. `fetch.py` serializes every download through `qif.serialize_account`
  and `download/bank.py` is built on the `model.py` types, so both are
  load-bearing for the scraper path until [phase 4](phase-4-fetching.md)
  moves it onto directives. `pydantic` stays with `model.py`, and
  `tests/test_qif.py` stays with the code it tests.

## Acceptance

- Each importer: Fixture statement in, expected directives out, `bean-check`
  passes on the result, re-running is idempotent (dedup works).
