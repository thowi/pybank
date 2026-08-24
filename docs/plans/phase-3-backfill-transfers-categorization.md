# Phase 3: Backfill, transfers, categorization v1

Turn the working importers into a complete, categorized history.

## Backfill

- Run importers over the statement archive in Drive: PostFinance to 2018,
  IBKR to 2016, DKB back to 2008 if the old formats still parse.
- Where old formats do not parse: Cutoff date plus opening balances via
  `Equity:Opening-Balances`, do not chase every format variant.
- Balance assertions per statement validate the whole chain.

### The PostFinance archive has holes

Measured, not assumed. All 63 CSVs parse and 6620 transactions come out, but
loading them fails all six balance assertions. The exports are row-capped,
see [phase 4](phase-4-fetching.md), so several cover a range they do not
fill, and there are outright gaps between consecutive files. Card exports
carry no balance at all, so nothing detects a hole there.

The archive alone therefore cannot produce a continuous checking history.
Options in the order worth trying: The QIF export below, which covers the
holes up to 2021 and nothing after, the monthly PDF statements, which carry
balances and run unbroken from 2018-05 to now, and re-fetching the missing
windows from e-finance, which only works as far back as the bank retains.

The PDFs are the answer for everything the QIF does not reach, so parsing
them is its own eventual task. 103 monthly checking statements carry a
`Saldo` column plus an opening and closing `Kontostand`. 78 card statements
carry `Saldo letzte Rechnung`, `Total Zahlungen`, `Total Transaktionen` and
`Saldo neue Rechnung`, so a card statement checks its own arithmetic and not
just its endpoint. Card CSV exports carry no balance at all, which leaves
the PDFs as the only possible source of card assertions.

### The SEE Finance QIF export

A one-shot importer, not part of the recurring set. It is the only source
for the oldest years, and the only source anywhere carrying categories that
were assigned by hand. Those labels seed every later categorization
approach, the rules below and anything smarter in Phase 5, so they are worth
more than the years they cover.

It also covers more than the oldest years, though less than its filename
suggests. Correcting an earlier claim: The name carries the range that was
asked for, not the range that came back. The data runs 2011 to 2021, tapers
through 2022, and stops. Within that window it is a complete second,
independent, already-categorized copy across all accounts, and the natural
first answer to the archive holes above. Import it first there and let the
per-statement imports reconcile against it, rather than the other way round.
After 2021 it contributes nothing and the statement sources stand alone.

- The deliverable is the old-to-new category mapping, not just a parser. The
  export carries the old taxonomy.
- Only this export is ground truth for categories. It holds the labels
  assigned inside SEE Finance. Per-bank files converted straight from bank
  CSV carry at most a bank-assigned category, which is a hint and not a
  decision, so the two must not be treated as one source.
- The labels are reliable but not clean. Validate rather than trust.
- The export has no balances anywhere, so no `balance` assertion is derivable
  from it. Assertions have to come from the statement sources, which is what
  makes the PostFinance balance gap above worth closing rather than
  shrugging at.
- Multi-account and multi-currency. It was written for an app that tracked
  everything, so it also covers accounts with no importer yet. Decide per
  account whether to take it or wait for the real source, and anchor
  whatever is taken with `Equity:Opening-Balances`.

#### What the importer does

`importer/beancount/qif.py`. All 11612 bank and card transactions parse and
the result loads with no errors. What the file turned out to hold, now
measured rather than assumed:

- The export declares every category as income or expense in its own
  `!Type:Cat` section, so account names derive themselves and only the
  awkward ones need an override. There is no mapping file to write by hand.
- Around 15% of transactions carry no category at all. Those become
  `Expenses:Uncategorized` and stay flagged `!`.
- `Split` in the category field is the exporter's marker, not a category.
  Almost every split carries it alongside its legs. Six carry it with no
  legs, having lost their breakdown on the way out, and those stay
  uncategorized.
- A dozen transactions point at accounts the old app no longer holds. They
  read as categories and need an override to book as the transfers they are.
- Category names and account names are private, so neither lives in this
  repo. Accounts arrive through the constructor, which doubles as the
  filter. Categories are read from the file at run time.
- Every counter posting keeps the old app's own words in `qif-category` or
  `qif-transfer`, and the leg's own text in `split-memo`. The mapping will
  change, and this is what a remapping remaps from. None of it feeds the
  import-id.

The app's own SQLite database was checked as a way to skip the export, and
rejected. On bank and card accounts the two agree exactly: Same 11612
transactions, same 63 category definitions, same 336 splits, and the same
607 / 56 / 95 split legs carrying a category, a transfer, or nothing. The
only differences are spelling, the export prefixes a deleted account with
`*` and flattens newlines in a memo. The three tables that would have
justified a rewrite, account balances, transaction rules and statements, are
all empty. The database is richer only for investments, which are skipped.

Investment accounts are skipped. QIF carries neither lots nor prices, and
IBKR holds nearly all of it with a full importer already. The consequence is
that the clearing account cannot balance yet, because many transfers point
at an account that was never imported.

## Transfers

- Route both legs through an `Assets:Transfers:InTransit` clearing account.
  Simpler for importers than merging legs, and self-reconciling: A nonzero
  clearing balance means an unmatched transfer.
- Detection key for matching: Amount, date window, counter-account hints.

## Categorization v1

- Rules-based only, modeled on the flofi cascade stages 1 to 3: Exclusions
  are structural (both transfer legs under `Assets:*`), then a rules file
  (contains / startswith / exact / regex on a normalized description).
- The rules file lives with the ledger, never in this repo. It maps real
  merchants and payees to categories, which [CLAUDE.md](../../CLAUDE.md)
  forbids committing. Doubly so once it is derived from QIF history instead
  of hand-written.
- Provenance in `meta` (`category-source`): `"rule"` for a rules-file match,
  `"qif"` for a hand-curated label carried in from the old export. Manual
  confirmations flagged `*`, never overwritten by re-runs. Unmatched stays
  `Expenses:Uncategorized` with `!`. Keeping `qif` distinct is what lets a
  query separate what was actually labelled from what was guessed.
- No fuzzy matching, no AI fallback yet (Phase 5).

## Acceptance

- Full history loads with `bean-check` green.
- Clearing account balances to zero across the backfilled range.
- Income statement by category looks plausible.
