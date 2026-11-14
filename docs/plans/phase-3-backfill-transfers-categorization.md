# Phase 3: Backfill, transfers, categorization v1

Turn the working importers into a complete, categorized history.

## Backfill

- Run importers over the statement archive in Drive: PostFinance to 2018,
  IBKR to 2016, DKB back to 2008 if the old formats still parse.
- Where old formats do not parse: Cutoff date plus opening balances via
  `Equity:Opening-Balances`, do not chase every format variant.
- Balance assertions per statement validate the whole chain.

### Where the backfill stands

The backfill is in the ledger: 18889 transactions from 2009 to 2026, with
the side-car below folded in. It loads with 7 errors, all balance
assertions on an account whose archive has no statement for the window
before it: 2 on PostFinance checking, 4 on the DKB card, 1 on DKB
checking. No source in the archive holds a transaction in those windows,
so only a missing statement can close them, not code.

Folding the export into the statements is what took the balance failures
from 59 down, since a doubled transaction breaks every assertion after it.

Category accounts used to be a separate count of roughly 7700 postings the
ledger did not open. The old-to-new mapping below closed that to zero.

### IBKR reports one contract under two symbols

Measured over the archive: 11 `conid`s arrive under two different symbols,
which the importer then books as two commodities. A reorg opening one and
closing the other therefore closes a position nothing holds. The suffixed
form is usually an off-exchange listing (`Z`) or a post-split rename
(`.OLD`), and a plain ticker rename does the same thing.

The importer cannot see this: An incremental import reads one file, and that
file carries only the name that was current when it was generated. So the
`conid` map is the ledger's to declare, which is what the `commodity`
directives with `ibkr-conid` are for, and what `_log_securities` reports a
missing one for. Declaring the 11 took the IBKR errors from 16 to 8.

The other half was lot matching. A closing trade used to name the open date
IBKR reports, but that date predates any reorg, and a reorg here closes the
old lot and opens a new one on its own date. So after a merger or a split no
held lot carries it. The reduction now names only the cost currency and lets
the ledger's booking method pick, which is why the securities account has to
be opened `"FIFO"`. That took 8 to 2.

### IBKR cash assertions

The first import into the ledger loaded with 27 errors, most of them IBKR
cash. Reconciling the archive against Statement of Funds and the cash
report found five importer defects, among them dating cash by `dateTime`
instead of `settleDate`. Fixing them took the ledger to 10 errors and left
no IBKR booking errors.

Three of those 10 are not importer defects. IBKR reports a withholding tax
correction months later, and settles it inside a period that is already
closed. The importer dates it by settlement, so it lands in a period whose
cash report was generated before it existed, and that period's assertion
fails. The archive holds 10 such corrections, in the three newest
statements. Each carries a `reportDate` inside the statement that holds it.

The importer now books such a correction on its `reportDate`, and no
earlier than the first day of the statement that holds it, with the
settle date kept as `settle-date`. The import-id stays on the settle date.
A full rebuild moved the 10 corrections and put the three assertions back
at the cash report values, with no hand edits left in the year files.

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
through 2022, and stops. After 2021 it contributes nothing and the
statement sources stand alone.

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

#### Where it overlaps the statement sources, the CSV wins

The two sources overlap for several years, and nothing deduplicates them
against each other: They hash different source text, so one bank event
yields two `import-id`s and two transactions. Which one to keep was
measured, not assumed. Matching on account, amount, and a five day window,
3039 of the contested rows pair up, 190 are QIF-only and 67 are CSV-only,
so neither source is a superset of the other.

The CSV is the better record wherever it reaches:

- Descriptions are the same text, and the QIF holds less of it. Card rows
  are identical once case and punctuation are normalized. Checking rows are
  worse: The exporter truncates a memo to 54 characters, and on one
  institution the QIF is a literal prefix of the CSV on 378 of 388 pairs.
- What the QIF appears to add is the old scraper's own doing. It appended
  labels like `Account:`, `Original amount:` and `Exchange rate:` into the
  memo, where the truncation then cut them. Every one duplicates a CSV
  field that survives intact, and the FX block in the CSV also carries the
  processing fee, which the QIF drops.
- The QIF drops the bank's booking type (standing order, direct debit, card
  payment, statement close). The CSV keeps it.
- `counterparty-account`, `receipt-date` and `original-amount` exist only on
  the CSV side, and only the statement sources can yield `balance`
  assertions.

So the QIF stops being a transaction source where a statement covers the
same period, and becomes a side-car instead. It matches into the CSV
transaction and donates two things:

- The hand-assigned category, which is the whole reason to keep the export.
- The hand-typed note, which very few matched rows carry, see the count
  below. Rare, but those are the rows whose merchant string says nothing, so
  they are the labeled examples Phase 5 wants. It goes in `meta`, never
  merged into the narration.

Outside that overlap, which is most of the export, the QIF row stays the
transaction. This is also the shape the ledger needs long term: New data
arrives only as CSV, so the export is a one-time seed for categorization,
not a parallel history.

##### What the side-car does

`importer/beancount/qif_sidecar.py`. A beangulp hook, so it needs one extract
pass covering the statements and the export together. Only then are both
sides in memory, and the exported row can be folded into the statement
transaction rather than printed beside it. beangulp extends its `existing`
list after extraction, not during it, so `--existing` cannot serve here.

A row pairs with a statement transaction booking the same amount on the same
account within five days, one row to one transaction. The pairing found 3039
of them over the archive, matching what the measurement above predicted.

Deciding what is a hand-typed note took three rules, and the export holds
far fewer notes than the memo field suggests. Testing a memo for a copy of
the statement text by substring keeps 341 of them, but 28 of the final 31 are
the same description worded differently, which a substring never catches.
Comparing shared words instead does catch them.

Three rules survive measurement, and each rejects memos the others keep:

- A memo carrying one of the old scraper's appended labels. 136 of the 224
  labeled memos would otherwise survive the other two.
- A memo half of whose words are bare numbers, which is a card and reference
  string. 2 of those share no word at all with the statement, because the
  statement holds the same numbers in its own columns.
- A memo whose words the statement already carries, at 40% or more.

An earlier version tested the memo's length instead of its numbers, on the
grounds that the exporter cuts most memos at 54 characters. That threshold
was a property of one exporter, and 492 memos in the archive run past it
anyway. The number rule replaces it, keeps the same 3 notes, and says why a
memo is machine text rather than how long it happens to be.

Words are matched Unicode-aware, so an umlaut does not split a word in two.
That changes the overlap score on 89 of 3027 pairs and the verdict on none of
them, which is the sort of near miss worth removing before it fires.

That leaves 3 hand-typed notes over the whole archive. The rule is worth
keeping because it is cheap and Phase 5 wants the examples, and the yield is
small enough that nothing should depend on it.

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
  filter. Categories are read from the file at run time, and the mapping
  from them to ledger accounts is config, see below.
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

#### The old-to-new category mapping

`[qif.categories]` in the config, so no category name reaches this repo. It
maps every label the export uses, 58 of them, to one ledger account. Nothing
derives its own account any more: the two taxonomies agree on almost no name,
so a derived name was right by accident or not at all.

The mapping is not a bijection and cannot be. Three shapes recur:

- **Several old labels to one account.** A receivable is one running balance
  per party, and the old app kept a give and a receive label per person, so
  both directions and every person in a group meet in one account.
- **One old label to several new accounts.** The old label maps to the
  account its payees mostly say, and the rest is accepted as wrong. Insurance
  premiums and out-of-pocket treatment shared one label, and so did fuel and
  parking, which the new tree splits on purpose.
- **No new account at all.** A label too mixed to name goes to
  `Expenses:Uncategorized`, where the rules below split it by payee. The
  worst case is a label covering telecom, hosting and electricity, three
  budget groups, whose payee strings are strong enough that a rule does
  better than any single account could.

None of this loses information. Every posting still carries the old label in
`qif-category`, so a better mapping applies later without re-reading the
export, and a query can always ask what the old app actually said.

The export also lends in more than one currency, so the receivable accounts
open on the currencies seen rather than on one.

## Transfers

- Route both legs through an `Assets:Transfers:InTransit` clearing account.
  Simpler for importers than merging legs, and self-reconciling: A nonzero
  clearing balance means an unmatched transfer.
- Detection key for matching: Amount, date window, counter-account hints.

Measured over the ledger, the clearing account is far from zero. Only the
QIF importer posts to it, 644 postings, and the side-car carries them over
to a statement row it folds. Every other statement row books its counter
leg to `Expenses:Uncategorized`, transfers included. So the residue splits
four ways, in the order worth working them:

- **IBKR deposits and withdrawals.** Booked to `Expenses:Uncategorized` by
  design, as the other half of a bank transfer. Where the export holds the
  bank leg, that leg sits in the clearing account, unmatched. The largest
  block, and a routing change in the importer.
- **Both accounts imported, legs do not cancel.** Both legs exist and
  should already cancel. They do not, and nothing explains why yet.
- **Statement rows outside the export's years.** Both legs are
  uncategorized, so they need matching on the detection key above.
- **An account with no importer.** Most of the export's clearing postings
  name one. They close only once that account is seeded with
  `Equity:Opening-Balances`. Decide per account.

## Categorization v1

- The QIF labels are already carried in, see the mapping above. The rules
  below cover what no label reached: the statement-only years, and the labels
  that were too mixed to name.
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
