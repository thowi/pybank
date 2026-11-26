# Phase 3: Backfill, transfers, categorization v1

Turn the working importers into a complete, categorized history.

## Backfill

- Run importers over the statement archive in Drive: PostFinance to 2018,
  IBKR to 2016, DKB back to 2008 if the old formats still parse.
- Where old formats do not parse: Cutoff date plus opening balances via
  `Equity:Opening-Balances`, do not chase every format variant.
- Balance assertions per statement validate the whole chain.

### Where the backfill stands

The backfill is in the ledger: About 19000 transactions from 2009 to 2026,
with the side-car below folded in. It loads with 3 errors, all balance
assertions: 2 on PostFinance checking, 1 on DKB checking. All 3 are
missing statement rows, checked against the PDFs:

- PostFinance checking, 2021-05-01 to 2021-06-10: The CSV export keeps
  only the newest 100 rows of the range asked for, so the export for that
  window starts on 2021-06-10, partway through the day. The QIF next to it
  has the same cap. The SEE Finance QIF has the same gap, so it was most
  likely fed from that export. The bank no longer exports rows this old.
  Fixed: The rows are reconstructed from the two monthly PDFs into a CSV in
  the export's format, marked as reconstructed in its name. Every balance
  the PDFs print checks out against it. The 2019 and 2020 exports have the
  same cap, but the SEE Finance QIF covers those years.
- DKB checking, from 2026-01-01: The newest export covers the last quarter
  of 2025, but asserts the balance on the day it was exported. Fixed: A
  new export covers 2026 to date.

The 4 errors on the DKB card were import bugs, not missing statements.
The export dated a few card refunds by their purchase date, weeks away from
the booking date the statement uses, so the side-car did not fold them.
It now also matches on the statement's purchase date. Two card bills the
export booked as a transfer to the account itself had the same effect on
DKB checking.

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
  `Equity:Opening-Balances`. Decided: The export is the only source for
  eight such accounts (Revolut and Wise in three currencies each, a rent
  deposit, a pillar 3a account). They are now `[qif.targets]`, and their
  history ends where the export ends. Kraken, Coinbase and EquityZen wait
  for phase 5. Unpaired clearing postings went from 213 to 204. Most of the
  rest are statement legs that have no QIF row.

### Wise and Revolut from their own statements

Wise and Revolut now import from their CSV statements instead of the QIF
targets. The rebuild of 2026-11-18 first left 149 unpaired clearing postings,
up from 125. Every conversion was unpaired: Its leg in the bought currency
fit, through the rate, the transfer that sent that money on, so neither pair
was sure. And Wise converts between EUR and USD, for which the ledger holds
no direct price.

Two matcher changes fixed it. The two legs of a conversion share a
`conversion-id` and pair first. A rate fit applies only to legs that fit
nothing exactly, as the fee fit already did. The second change alone booked
a card purchase against an exchange leg of the same amount, so it waited for
the first. Together they left 91 unpaired postings, none on a Wise or
Revolut account, `bean-check` clean (it had 3 errors before), and 46 pairs
booked unasked, each checked by hand. 14 pairs await an answer in `confirm-transfers`.

What stays open on these accounts: 9 card charges to Revolut that no Revolut
row matches by amount. The cause is not checked yet.

### Same-amount groups in `unpaired`

`unpaired` cancels by amount and date only, so in a group of 3 or more legs
with one amount it can list the wrong one. Over the ledger of 2026-11-21,
4 of 48 unpaired legs sit in such a group. A link between booked pairs would
have fixed none of them: 3 groups hold no linked leg, and the fourth lists
its only unlinked leg already. Decided: No link. The report names the other
legs of the group below the listed one instead.

### The SEE Finance database instead of the QIF

`[see.targets]` and `[see.categories]` take the same values as the `[qif]`
tables. A standalone extract of the database matches the QIF's: 11,542
transactions, 9,290 with a QIF category, plus 542 `conversion-id` links.
Two differences:

- 43 legs booked by a hint, up from 32. Checked by hand: All 11 new ones are
  real transfers (card bill debits, credits from own accounts). The QIF cuts
  the memo at 55 characters, the database holds it in full, so the hint text
  now matches. One of the 11 is the leg the QIF build paired by `pair-auto`.
- The one confirmed pair is missing: `transfer-pairs.toml` names the QIF
  import-ids. `see-db/remap_answers.py` rewrote its 4 QIF ids, all 1:1.

beangulp skips any input above 8 MiB, so `ingest.py` raises that limit.

Done 2026-11-21: `pybank.toml` reads `[see]`, `rebuild.sh` passes the
database to `extract`. The rebuild differs from the QIF build in one booking
only: The 2012 PostFinance to DKB pair now books its CHF leg at a price, as
its answer says. Same counts otherwise: Hint, pair and `pair-auto` bookings,
13 pairs awaiting an answer, 48 unpaired legs, no `bean-check` errors.
`conversion-id` links went from 52 to 504.

### What the `confirm-transfers` answers taught

The answers of 2026-11-22 rejected 9 of 12 pairs. Two kinds of false match:

- **Two cards.** A refund on one card fit a charge on another. Decided: Two
  legs on `Liabilities` accounts never pair. Top-ups from checking to a card
  still pair.
- **A payment from a third party.** A TWINT or bank credit from another
  person fit an unrelated card purchase, 7 pairs. Matching the sender
  against one's own accounts would catch them. Decided: Skip it. It costs a
  sender table and parsing per bank, for about 2 questions a year.

Most rejected pairs are reimbursements, such as postage a buyer pays back.
They go to the same expense account as the cost, so the two cancel. The
payee hints for the rules file are in `Ledger-rebuild/categorize-hints.md`,
outside this repo.

The extract warning counted a pair whose leg a confirmed pair already took,
which `confirm-transfers` skips. It now skips them too. The rebuild after the
answers booked the 3 confirmed pairs, changed nothing else, and leaves no
pair awaiting an answer.

Still open: 3 PostFinance credits of 2024 with an unknown sender, and the 9
Revolut card charges above.

## Categorization v1

- The QIF labels are already carried in, see the mapping above. The rules
  below cover what no label reached: the statement-only years, and the labels
  that were too mixed to name.
- Rules first, modeled on the flofi cascade stages 1 to 3: Exclusions
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
- Rules alone fall short, so a model suggests the rest (below).

### Rules alone leave most rows open

Measured over the ledger, imported rows with two postings, transfers and
splits left out:

- 9721 rows carry a category, nearly all from 2011 to 2020. 7356 do not,
  6085 of them from 2021 to 2025. 38 categories in use.
- 2552 payees (first words of payee and narration). 242 of them have more
  than one category, and they hold 41% of the categorized rows. So a payee
  alone does not decide the category.
- Only 2661 of the 7356 open rows have a payee seen in history.

So rules cover the deterministic cases only. The rest needs a model that
learns from the labeled history and suggests, plus a fast approval step.

### Design

- **Rules first.** `[[rules]]` in the config: `text` (regex on payee and
  narration, case-insensitive), optional `account`, `category`. They run in
  the rebuild after the transfer pairs, share the match code with
  `[[transfers]]`, flag `*` and set `category-source: "rule"`.
- **Then suggestions.** `suggest(ledger)` returns, per open row: `import-id`,
  the top 3 categories with probabilities, and a payee group. A suggestion
  never books by itself. It stays pending until approved.
- **Answers file.** Approve, reject or change, keyed by import-id, next to
  the config like `transfer-pairs.toml`. A rebuild applies the approved
  answers with `category-source: "model"`, so a rebuild keeps them.
- **Review grouped by confidence.** High band first, grouped by payee,
  approved in bulk after a skim. Low band one by one, with a pick from the
  top 3. Retrain after each batch, so each answer improves the next round.
- **UI independent.** `suggest` and the answers file are the interface. A
  `categorize` CLI command comes first, on the `confirm-transfers` pattern. A web UI
  can replace it later, maybe as a Fava extension (unchecked).
- **Train only on real labels:** `"qif"` and approved answers. Rule output
  would only teach the rules back.

### Decided 2026-11-22

- **The SEE Finance database is the source of the hand-assigned labels,**
  not the QIF. Its rows keep `category-source: "qif"`.
- **Backtest again on the SEE data.** The numbers below come from the QIF,
  which cuts memos at 55 characters.
- **The rules hook comes before the model.**
- **A rule books only rows that are still uncategorized.** A label, a
  statement booking or a transfer wins. Letting a rule override a label
  can come later, if a mixed label needs it. Superseded 2026-11-23: A rule
  may override the labels it names, see the rule mechanics below.
- **Rules are written together.** The agent proposes each rule with its
  matching rows as examples. The user approves it.
- **Cashback goes to `Income:Cashback`,** see [accounting.md](../accounting.md).
- **Rule format:** One `text` regex over payee and narration, like
  `[[transfers]]`. An optional `account` filter, more filters only when a
  real rule needs one. Rules live in their own `rules.toml` next to
  `pybank.toml`. The first matching rule wins, and the rebuild reports
  rules that match no row.
- **The expense categories get one review before the first rule,** then
  stay fixed. Rules and model answers name accounts, so a rename later
  touches all of them.
- **Payees seen once or twice get no rule.** The model suggests a category,
  the user approves it, the answer is saved next to the config.
- **The model only suggests.** Every row it touches is approved before it
  is booked.
- **The memo counts as much as the payee.** Generic payees (a payment app,
  a bank transfer) carry their meaning in the memo, so rule proposals group
  rows on payee and memo together.
- **A refund books to the account of its purchase,** so the two cancel.
  It gets the tag `#refund`. When its purchase is clear (same merchant,
  earlier date, larger or equal amount), both get one shared `^link`. With
  no clear purchase, the refund gets only the tag. No split transactions:
  A partial refund nets out in the account total.

The labels end in early 2021, when SEE Finance stopped being used. After the
rebuild of 2026-11-22, about 1700 rows up to 2020 and about 9200 rows from
2021 on are uncategorized.

Where the rows up to 2020 come from, checked against the SEE database:

- About 690 carry an old label that maps to `Expenses:Uncategorized` on
  purpose (`Bills`, `Cash`, `Services`, `Retoure Expense`). The rules split
  them by text. `Cash` stays a true-up.
- About 800 have no category in SEE itself. The database has about 680 such
  bank and card rows up to 2020, most on the cards. About 290 are money in:
  Refunds from online shops, tax-free refunds, rewards, payment-app
  receipts, deposits. The rest are online shops, payment services, foreign
  card purchases and bank transfers. 89 more are the unlabeled part of a
  split purchase in SEE (the part sent back later). Only 17 refunds match
  such a part to the cent, so a refund rule cannot pair them by amount.
- About 115 rows are not gaps. Each is a zero-amount `[Next billing cycle]`
  marker that the legacy card scraper wrote into its CSVs
  (`download/postfinance.py`). They book nothing. The PostFinance importer
  now skips zero-amount rows with this memo. Other zero rows stay, since a
  statement can carry one (the QIF holds a 0.00 account fee).
- About 20 lost a label: The CSV row won the overlap and its QIF twin is
  ambiguous.

So the old labels need no new mapping pass. `[see.categories]` already maps
every label, and rule proposals cite the mapped labels as evidence. Rows
up to 2020 keep their labels, only the open ones get rules.

### Model candidates, to test before building

Backtest: Train on rows before 2019, test on 2019 and 2020 (2552 rows). Later
cutoffs mislead, since the few labeled rows after 2021 are the easy ones.
Goal: The share of rows that can be approved in bulk at 98% right or better,
then top-3 accuracy on the rest.

Baseline, TF-IDF and logistic regression (scikit-learn):

- Inputs: Payee and narration in lower case, digits replaced, as words and
  word pairs plus letter groups of 2 to 5. Own account, currency, sign, and
  a rough size bucket (two per factor of ten). No date, no recurrence.
- Top 1 69%, top 3 81%.

| Confidence | Share of rows | Right |
|---|---|---|
| 0.95 and up | 36% | 99% |
| 0.80 to 0.95 | 15% | 89% |
| 0.50 to 0.80 | 22% | 60% |
| below 0.50 | 28% | 29% |

Below 0.8, 65% of the rows have a payee not seen in training (40% right),
and 29% have a known payee with several categories (44% right). The lever is
a model that already knows merchants, then features beyond the text.

To test, in this order:

1. **Embeddings plus logistic regression,** combined with the TF-IDF
   features. Local, with PyTorch (approved). Candidates:
   multilingual-e5-large-instruct, BGE-M3, Qwen3-Embedding-0.6B.
2. **Gradient-boosted trees** (LightGBM, XGBoost or CatBoost) as a second
   stage. Inputs: The text model's probabilities plus amount, date (day of
   month, weekday) and recurrence. Aimed at known payees with several
   categories. A single decision tree overfits and gives poor
   probabilities.
3. **An LLM for the low band only,** given the 10 most similar labeled
   rows as examples. Claude through the API, or a local model through
   Ollama. Undecided.
4. **A fine-tuned encoder** (XLM-RoBERTa or e5), if embeddings help.
5. **Jev** (TypeSafe AI), a hosted classifier with calibrated
   probabilities, only if the others fall short. Early access, paid.

Ruled out: `smart_importer`. Its linear SVC gives no probabilities and one
account only, and it fills only rows with a single posting, so it never
replaces `Expenses:Uncategorized`.

### The category review, decided 2026-11-23

The review used a local page next to the rebuild tooling
(`category-review/build.py`, outside the repo). Scope: The tree only.
Category gaps show up during the actual categorization, so new categories
come then. Payee answers are in `categorize-hints.md` (outside the repo).

Tree changes, agreed, not yet applied:

- Remove `Insurance:Life` and `Leisure:Travel:Flights`.
- Add `Insurance:Travel`.
- Rename `Telecom:Internet` to `Telecom:Broadband`.
- Map `Retoure Income` and `Bills:Reimbursed` to `Expenses:Uncategorized`,
  so the refund rule books them. Then close `Income:Refunds`.
- Map the SEE labels `Dining` and `Going Out` both to `Leisure:Dining`.
  Payee rules override the few exceptions.
- Keep `Housing:AdditionalCosts`. Each monthly rent payment splits into
  rent and the advance for additional costs, with both amounts from the
  lease per date range in the config. The yearly settlement books there
  too.

Food follows the reason for being away from home:

- `Living:Meals`: Everyday life, so eating at home was not possible. A
  workday lunch, a break on a long drive outside a trip.
- The activity's account: Food on a trip goes to `Leisure:Travel`, like
  half board in a hotel bill. This includes the drive there and back,
  since those days fall in the trip's date range. Food on a ski day
  goes to `Leisure:Sport:Ski`. A day with a row in that account is a ski
  day.
- `Leisure:Dining`: Eating at home was possible. Dinners, weekends,
  delivery to home, also to the home office.
- Meal kits go to `Living:Groceries`.

Trips:

- A trip needs at least one night away.
- A trip list in the config (start, end, name) drives a rule. Food in the
  date range books to `Leisure:Travel`. Every row in the range gets
  `#trip`, so a query can leave trip rows out, plus a tag per trip.
- The list covers 2021 on. Rows up to 2020 keep their SEE labels.
- Finding the trips: A script proposes date ranges from the ledger
  (lodging, airline and rental payees, foreign currency, resort places,
  no local shopping). An LLM then searches calendar and mail near each
  range for bookings to fix the dates, or asks the user. The user
  confirms the list once.
- Each monthly import later: The user may add a trip line when booking.
  The same detection runs on the new rows before the rules, looks a few
  days past the import window, and asks only about trips not yet on the
  list.

### Rule mechanics, decided 2026-11-23

Some SEE labels are wrong for a few payees: A meal kit labeled `Dining`
belongs in `Living:Groceries`. So a rule may override a label, but only a
label it names.

- **Keys:** `text` (regex over payee and narration), `book` (the target
  account), and the optional filters `account` (the bank account, as in
  `[[transfers]]`), `from`, `until` and `labels`.
- **Which rows a rule may book:** A row on `Expenses:Uncategorized` is open
  to every rule. A row with a label (`qif-category`) is open only to rules
  that list that label in `labels`. Every other row is closed.
- **Order:** The rules run top to bottom, and the first match books the
  row. An exception is a narrower rule above the broader one, or a rule
  that names the label it overrides. There is no other exception syntax.
- **Booking:** The posting moves to `book`, with `category-source:
  "rule"`. `qif-category` stays, so the old label remains visible.
- **The trip rule goes first,** with `labels = ["Dining"]`, so trip dates
  win over the payee rules.
- **A rule may book to `Expenses:Uncategorized`.** This sends a labeled
  row back to review, for a payee whose rows need a pick one by one.

### The refund rule, measured 2026-11-23

A prototype (scratchpad, not in the repo) looked for the purchase of each
open money-in row on a card, plus the rows labeled `Retoure Income` and
`Bills:Reimbursed`. Merchant key: The first word of payee and narration,
after prefixes like `Retour.` and `PayPal *` are cut. A purchase is a
money-out row with the same key, up to 120 days earlier, with a larger or
equal amount in the same currency.

- 501 rows. 85 have one purchase with the same amount, 80 have one
  purchase with a larger amount, 84 have none, 235 have several.
- Of the 182 rows with one clear purchase, only 17 purchases carry a
  category. Most purchases are open too, so the refund hook mostly links.
  The booking follows when the purchase gets its category.
- Of the 235 with several purchases, 143 have purchases that all share one
  account.
- The first word is a weak key: It also pairs bank giro rows and fee rows.
- A card refund of a foreign purchase converts at a new rate, so it can be
  a little larger than its purchase in CHF. Unmeasured.

Alternatives to the first word, on all 501 refunds. "Wrong direction" runs
the same search on purchases after the refund, where no link can be right:

| Match                         | Linked | Wrong direction |
| ----------------------------- | ------ | --------------- |
| First word                    | 206    | 62              |
| First word, same amount only  | 86     | 6               |
| First word, then whole text   | 224    | 73              |
| First two words               | 218    | 68              |
| Whole text equal              | 169    | 54              |
| Any shared word               | 161    | 68              |
| Text similarity 0.8           | 211    | 69              |
| No name, same amount only     | 107    | 20              |

- The weak part is the amount, not the word: 56 of the 62 wrong-direction
  links have a different amount. 3 linked pairs differ in the second word.
- Unlinked: 213 have several purchases, 82 have none.
- Of the 15 booked refunds, 12 have a different amount than their purchase.

Scored against the SEE labels `Retoure Expense` (the purchase, or the
returned part of a split one) and `Retoure Income` (the refund). SEE holds no
refund links. 38 pairs are unique by amount and date, 19 of them partial
returns. Scripts: `Ledger-rebuild/refund-match/` (`score2.py`).

| Match                                     | Full, of 19 | Partial, of 19 | Wrong | Links | Wrong direction |
| ----------------------------------------- | ----------- | -------------- | ----- | ----- | --------------- |
| The hook                                  | 14          | 0              | 2     | 206   | 62              |
| Plus split purchases                      | 14          | 6              | 0     | 216   | 71              |
| Plus a split part of the same amount      | 14          | 18             | 0     | 234   | 71              |
| Plus a same amount within 0.50            | 17          | 18             | 0     | 254   | 85              |

- The hook skips split purchases (more than 2 postings). Both wrong links
  come from that.
- The part rule and the pairs both use the amount, so its 18 is optimistic.
- Decided: Add split purchases, the part rule, and a tolerance for "the same
  amount". A same-amount refund claims its purchase first. Book only
  same-amount refunds (or the same amount as one part). A partial refund is
  linked and stays open.
- The tolerance is 1%, not the 3% of the exchange rates: On the 38 pairs 1%
  and 0.50 are equally right (17 and 18). 3% links one pair wrong. In the
  wrong direction, same-amount links are 13 at 1%, 22 at 0.50, 29 at 3%.

### Next steps, in order

1. **Apply the tree changes** above to `accounts.beancount` and
   `[see.categories]` in `pybank.toml`. Done 2026-11-23: Rebuilt, no
   `bean-check` errors, no posting left on a removed account.
2. **The `rules.toml` hook and the first rules,** from
   `categorize-hints.md` and the refund rule above. Status 2026-11-23:
   The hook is built (`rules.py`, wired in `ingest.py`) and went through
   `/ship-change`, reviewed and committed. Fixed from the review: Type
   checks for `from`, `until`, `labels` and `text`, an unknown top-level
   key in `rules.toml` is an error, duplicates are skipped, the shape check
   reuses `hooks.open_slot`. Measured: A rule can book one leg of a pair
   that waits for an answer, so `confirm-transfers` would not ask about it.
   With today's rules no pair is lost (4 pending pairs and 3 choices with
   and without the rule rows), so a comment in `_hooks` notes it. Recheck
   with a broad rule, for example a P2P app's name. The first 8 rules are
   approved and in `rules.toml`. The rebuild books 226 rows by rule, with
   no `bean-check` errors and no rule that matches nothing. Open, each a
   unit of its own: Marketplace sales, TWINT postage (needs a postage
   account), the transfer pair named in `categorize-hints.md`, the refund
   rule, trips, the ski-day rule, the rent split. The first three are rule
   proposals in `rules.toml` only, waiting for the user's approval
   (2026-11-23). Found then: The approved rental-income rule also books 4
   postage receipts whose memo names the rental platform. The postage rule
   must go above it.
   Status later 2026-11-23: The user merged the two postage proposals into
   one rule for payments and refunds (`Expenses:Living:Postage`, above the
   rental rule). The marketplace rule is in. The transfer pair named in
   `categorize-hints.md` gets no rule: It is a one-off loan, booked on
   both rows to `Assets:Receivable:Friends` with the answers file, once that
   exists (decided). The refund hook is built
   (`refunds.py`, `[refunds]` in `rules.toml`) and went through
   `/ship-change` and the user's review. Extended
   after that review (split purchases, part amounts, 1% tolerance, claims,
   no category for other amounts). The extension went through its own
   `/ship-change` and the user's review. All committed (2026-11-23). Fixed
   from the first review:
   - A row an earlier hook dropped no longer counts as a second purchase.
     It stays in beangulp's `existing`.
   - A transfer out is no purchase.
   - A duplicate is no purchase.
   - A row with no merchant word has no purchase.

   The prefixes are config (`[refunds] prefixes`). The rebuild: No
   `bean-check` errors, 501 refunds tagged, 255 linked, 3 booked (before the
   extension: 501, 196, 15, before the fixes: 501, 155, 8). Two refunds
   of the amount of one part both book to that part. Decided: Leave it, no
   row in the ledger has this. Limits, in the docstring:
   - A purchase already in the ledger gets no link.
   - A row a rule booked is no refund.

   Later: Book a linked refund when its purchase gets approved.
3. **The model backtest on the SEE data.** Compare a local model with an
   LLM on the same SEE rows. The user prefers the LLM if it is clearly
   better: The cost is low, and the goal is to save the user's time.
   The user approves suggestions per group, never row by row.

   Setup: Train before 2019, test on 2019 and 2020 (5611 and 2145 rows).
   The confidence cutoff for bulk approval comes from 2018, at 98% right.
   Scripts: `Ledger-rebuild/categorize-backtest/see_*.py`. Run from there:
   `uv run --no-project --python 3.13 --with scikit-learn --with beancount
   python see_baseline.py`.

   Baseline (TF-IDF and logistic regression, light, local): Top 1 69.2%,
   top 3 83.1%. Bulk: 42.9% of rows, 98.4% right, top 3 on the rest 71.2%.
   New payees are 45% of rows: Top 1 53.9%. Known payees: 81.8%. 5.3% of
   the test rows have a category that training never saw. The old labels
   are coarser than today's tree, so this cannot score the finer accounts.

   Local LLMs are ruled out on this machine (M3, 16 GB, 1.5 GB free at
   load, no free swap). `deepseek-r1:8b`: 8 rows, first call 4m54s, then 4
   to 23 s each. Then the machine rebooted. Memory pressure is the likely
   cause, unproven: No panic report. Do not run `see_llm.py` against
   Ollama again, and run no PyTorch embeddings here either.

   Hosted LLM, 2026-11-24 (approved: OpenAI only, cap $5): `gpt-6-luna`, low
   effort, on 300 rows of 2018 and 500 of 2019 and 2020. 12 similar labeled
   rows per prompt, digits masked, no account names, `store=False`. 800
   calls, 5.5 minutes, $0.09 at `whatwasapp`'s price table. Same 500 test
   rows for all three, cutoff from 2018 at 98% right:

   | | Top 1 | Top 3 | Bulk rows | Bulk right | Rest, top 3 | New payee, top 1 |
   |---|---|---|---|---|---|---|
   | TF-IDF | 70.2% | 84.8% | 38.0% | 99.5% | 75.8% | 54.5% |
   | `gpt-6-luna` | 79.2% | 93.2% | 53.2% | 97.0% | 85.9% | 72.3% |
   | Mix, LLM weight 0.40 | 77.8% | 91.6% | 55.6% | 97.1% | 81.5% | 70.6% |

   The LLM is clearly better. Bulk right is 97%, below the 98% target: The
   cutoff comes from only 300 rows. The mix at a stated confidence of 0.95+
   holds 44% of rows at 99% right. This measures the old, coarser labels.
   Script: `see_api.py` (run command in its docstring, `openai` came from
   `whatwasapp`'s venv via `PYTHONPATH`, no download). Answers:
   `out/gpt-6-luna-low.json`.

   Tuning, 2026-11-26 (approved: OpenAI and Google, $10 in all). Script
   `see_tune.py` (variants and run command in its docstring), answers and
   logs in `out/tune/`, spend in `out/tune/spend.json`. Paired counts:
   `see_pair.py`. Error kinds: `see_errors.py`.

   - Errors of the first run (104 of 500): 64 new payee, 35 known payee
     whose label differs from the payee's usual one (18 never used for it),
     5 clear model errors. Label noise caps what a prompt can gain.
   - Prompt, on `gpt-6-luna` low, 600 rows of 2018, one change at a time.
     The same prompt run twice flips 22 rows and moves top 1 by 0.7
     points, so most changes are noise. Every example text is cut to 120
     characters. Kept: `clean` (drop FX boilerplate, card and reference
     numbers, bank tails) and `details` (exact amount, month, weekday, day
     of month). Together: Top 1 81.7%, top 3 94.5%, log loss 0.80 against
     0.88 to 0.93 for base. No gain: Foreign-currency rows nearby,
     category notes, the nearest example of every category, medium effort.
     Worse: 30 varied examples instead of the 12 nearest (78.0%).
   - Models, `clean+details` at low effort, same 500 test rows:

     | | Top 1 | Top 3 | 0.95+ rows | 0.95+ right | New payee, top 1 | Per row |
     |---|---|---|---|---|---|---|
     | TF-IDF, local | 70.2% | 84.8% | 34% | 100% | 54.5% | $0 |
     | `gpt-6-luna` | 80.4% | 93.4% | 52% | 98% | 72.3% | $0.0001 |
     | `gpt-6.2-sol` | 81.2% | 95.4% | 63% | 97% | 74.5% | $0.002 |
     | `gemini-4-argon` | 83.0% | 95.2% | 55% | 99% | 78.4% | $0.005 |
     | Cascade, below | 82.6% | 95.0% | 54% | 98% | 77.5% | $0.002 |

     Paired against Luna on test: Sol +23 -19 (noise), Argon +26 -13 (z
     2.1). Argon is 4 times slower (1300 s for 800 rows, 4 workers). Its
     cost counts the post-promo $4 / $20, the promo until 2026-11-30 is
     half. Prices come from third-party pages, unverified on the vendors'.
   - Cascade, from the cached answers: Luna, and Argon where Luna is below
     0.90 (39% of rows). Top 1 82.6%, 0.95+ on 54% of rows at 98% right.
   - The mix with TF-IDF no longer helps top 1 with these prompts.
   - Spend: $6.79 counted, about $4.8 at the promo price.

   Ideas to try, ranked by likely success (approved 2026-11-26: Try until
   done or the $10 counted spend). Status in brackets.

   1. Agreement of two models as the condition for a sure row (free, from
      the cache). [done: Higher accuracy (99.6%), no more rows. A single
      model at 0.95+ still gives the most rows at 98% right]
   2. Fix the payee key. It is the first 3 words, so every card row of
      one bank reads as the same payee. Drop words common across many
      labels, then take the first words left. (free) [done: 65 noise
      words learned from the data. 2 words change little, 1 word isolates
      a harder new-payee group (21% of rows, top 1 64%)]
   3. Payee history line: The user's past labels for this payee, with
      counts and typical amounts. [done, no gain: By key z -0.3, by text
      similarity 0.6 z +0.8]
   4. Full date on the examples, so the model sees habits change. [kept:
      Z +2.2 on val]
   5. Cutoff per category, or calibrated probabilities (free). [done, no
      gain: 56% of rows at 97.1%. Luna's confidence sits at 0.95 to 0.99]
   6. Cascade with Sol instead of Argon (free, from the cache). [done:
      Worse than with Argon, top 1 81.2%]
   7. Example search on the cleaned text. [kept: Z +2.1 on val]
   8. Several rows per call, sharing the instructions and categories.
      Saves tokens, may cost accuracy. [done: 42% fewer input tokens, 3.6
      times faster, 1 to 2 points less top 1]
   9. `gemini-4-hydrogen`, price to check first. [skipped: $1.50 / $7.50
      per 1M, about $3.5 for 800 rows, over the budget left]
   10. Web search for new payees (paid per search). [later]
   11. Fine-tuning a hosted model on the labels. [later]
   12. Order details from mail for Amazon, PayPal, TWINT. [later, needs
       new data]
   13. Learn from each review, always ask for split payees, test on the
       new tree's labels. [process, at build time]
   14. More nearest examples (25, 50) and no cut of the row text. [kept:
       50 examples z +1.5, full text not worse]

   Result, same 500 test rows. Luna with `clean+details+date+cleansearch
   +nocut+k50`: Top 1 82.4%, top 3 93.8%, 58% of rows at 0.95+ with
   97.9% right, new payee top 1 76.2%, about $0.0003 per row. With Argon
   where it is below 0.90 (36% of rows): 83.2%, 95.2%, 59% at 97.6%,
   78.8%. A rerun of the unchanged prompt moved top 1 by 1 point, so
   single gains under about 2 points are not proven. Spend $7.96 counted.
   Scripts: `see_tune.py` flags, `see_offline.py` for the free analyses,
   `run_round3.sh`, logs in `out/tune/round3.log` to `round6.log`.

   At build time in the repo: The prompt names the user's country. Make
   the country a config value, or drop it. Noise words for the payee key
   are learned from the user's data, never hardcoded.

   Next: The user picks the model for the open rows (10218). Estimates by
   the tokens per row: The tuned Luna about $3, with Argon for unsure
   rows about $10 to 20, Argon alone about $26 to 51. The run needs the
   new tree's categories (more than 26, so the letter labels must change)
   and a review by group.
4. **The user answers the open pairs in `confirm-transfers`.**

## Later, not a priority

- **Embeddings for the refund match.** Expected gain: Small, since most
  unlinked refunds have several purchases from the same shop. Test on the
  38 pairs of `Ledger-rebuild/refund-match/`. Compare with an order number
  that both texts hold.
- **Receivables.** The 3 receivable accounts stop in 2020 with balances
  that are not zero. One holds costs that will not be repaid, so close it
  to zero. Check the other two for gaps, then close them too.
- **VIAC.** The yearly payments since 2021 are transfers, not expenses.
  The transfer hint and the yearly certificates move to phase 4.
- **Odd rows up to 2020.** Costs paid for others, top-ups booked as
  purchases and similar rows stay as they are for now. Once all rows have
  a category, look for odd account totals per year and correct those.
  Older years may stay as they are.
- **Card balances against the bill PDFs.** SEE Finance did this by hand
  with the marker rows. Add a check to the workflow: Each billing period's
  rows sum to the bill's total. Phase 4 plans the same check after each
  fetch, so build it once for both.
- **IBKR capital gains.** The yearly totals look wrong, 2025 most of all.
  Hypothesis: Cash and shares moved into IBKR count as gains. Check
  against the IBKR realized P&L report.
- **Payments in lieu of dividends.** IBKR lends the shares (Stock Yield
  Enhancement Program) and pays a substitute instead of the dividend. Give
  these payments and their withholding their own category, so the tax
  return can tell them from real dividends.

## Acceptance

- Full history loads with `bean-check` green.
- Clearing account balances to zero across the backfilled range.
- Income statement by category looks plausible.
