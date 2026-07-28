# Transaction storage format: research + proposal

How to store pybank transactions across multiple accounts in a common,
standardized format. Must cover current accounts, credit cards, savings, and
brokerage, with multi-currency, split transactions, and transfers. Ranked by
fit, popularity, pros/cons. Date: 2026-07-26, updated 2026-07-28.

## Decisions

Status as of 2026-07-28.

| # | Question | Decision | Status |
|---|---|---|---|
| 1 | Domain model | Double-entry ledger, adopting `beancount.core.data` types directly | **Locked** |
| 2 | Interchange export | OFX 2.x via `ofxtools`. Nothing else for now, can add later | **Locked** |
| 3 | Storage | Plaintext `.beancount` in a private Google Drive folder | **Locked** |
| 4 | v1 scope | PostFinance, DKB, Interactive Brokers importers first | **Locked** |

Implementation sequencing: See [../plans/README.md](../plans/README.md).

Only the domain model was expensive to get wrong: Every importer, query, and UI
depends on it. Interchange and storage are adapters hanging off the model, each
replaceable cheaply.

Deliberately deferred on #2: CSV export, `beancount2ledger`, FDX. All are
additive, none block. QIF gets retired.

## Proposal (TL;DR)

- **Adopt Beancount as the canonical format.** Plaintext double-entry
  accounting, written in Python (native library for pybank), files versioned in
  git. The requirements list (splits, transfers, multi-currency, brokerage) is
  precisely what double-entry accounting exists to model. With Beancount the
  "local files vs database" question largely dissolves: The plaintext file *is*
  both the open format and the store, queryable via BQL (beanquery).
- **Use its types as the domain model**, do not mirror them in our own classes.
  See "Domain model: adopt beancount.core.data" below.
- **Keep an interchange export.** Replace the legacy QIF writer with **OFX**
  (via `ofxtools`) for interop with other finance tools that want to import
  pybank data. OFX is the one interchange standard that also covers brokerage.
  Note OFX is single-entry, so the export is lossy. The lossless archive is the
  `.beancount` file itself.
- **Use the ecosystem, don't reinvent:** `beangulp` for the importer layer
  (maps onto pybank's existing importer concept), `fava` for a read-only web UI,
  BQL for queries.
- **Runner-up if you want a GUI + real DB out of the box:** GnuCash via
  `piecash` (SQLite). Weigh only if plaintext/git is not wanted.
- **Not the store:** Firefly III / Actual (apps, not libraries, weak on
  brokerage), raw OFX/QIF/camt (interchange, not storage), a custom DB schema
  (reinvents a non-standard model, loses the open-standard payoff).

## Two layers, don't conflate them

- **Interchange / source formats:** what banks emit and what tools import/export.
  CSV, OFX/QFX, QIF, ISO 20022 camt.053, MT940. Transport, statement-shaped, not
  a place to *keep* a multi-account ledger.
- **Canonical model + store:** one normalized representation of all accounts and
  transactions that pybank owns. This is what the question is really about.
  Candidates: plaintext double-entry (Beancount/Ledger/hledger), GnuCash
  (XML/SQLite), an app DB behind a REST API (Firefly III/Actual), or a bespoke
  schema.

pybank today: heterogeneous CSV in → a Pydantic model (per-account currency,
investment transaction types) → **QIF out**. QIF is the legacy floor: no
multi-currency, no splits, no transfers, weak investment support. Replacing it is
the point of this research.

## Domain model first, serialization second

Correct framing: pick the **domain model** (what accounts, transactions,
postings *are*), then pick serialization/storage. Beancount files, GnuCash
SQLite, or a custom DB are then just encodings of that model.

Is there a standard domain model? Effectively yes, two families:

- **The double-entry ledger model.** Account hierarchy with five root types
  (Assets, Liabilities, Equity, Income, Expenses), Transaction as a balanced set
  of ≥2 Postings, Commodity (currency or security), Price, Lot/Cost. This is the
  centuries-old accounting model, formalized identically across Beancount,
  Ledger, hledger, and GnuCash (their file formats differ, the model is the
  same). Also the model in Fowler's *Analysis Patterns* accounting chapters.
  This models **your books**: one consistent view across all accounts. Splits,
  transfers, multi-currency, and brokerage fall out naturally.
- **Bank message/statement models.** ISO 20022 (a formal business data
  dictionary behind camt/pain/seev), OFX message sets, and FDX (Financial Data
  Exchange, OFX's successor: JSON/REST, the US open-banking schema; OpenWealth
  is the Swiss equivalent for custody/investment data). These model **what one
  institution reports to you**: statement-shaped, single-perspective,
  single-entry. Right for ingestion and interchange, wrong as the canonical
  store: they cannot represent both legs of a transfer across institutions or
  your categorization.

So the layering is: bank message models at the edges (camt, OFX/FDX, CSV in;
OFX out), the **double-entry ledger model as the canonical domain model**, and
only then a serialization choice. pybank's `model.py` should converge toward
the ledger model (Transaction + Postings) regardless of which encoding is
picked. That makes the Beancount-vs-GnuCash-vs-custom-DB question low-stakes
and reversible: all three encode the same model, and Beancount is simply the
encoding with the best Python library, validation, and git ergonomics.

Beyond Fowler, ISO 20022's business logical model, and FDX, **BIAN** (Banking
Industry Architecture Network) is the fourth commonly cited reference, defining
service-domain boundaries for banking capabilities. Enterprise-scale, but
confirms the same separation of domain from persistence.

### Concrete domain decomposition

The DDD shape of the ledger model, as the target for `model.py`:

- **Account** (entity): `id` / hierarchical path (`Assets:PostFinance:Checking`),
  `type` (ASSET, LIABILITY, EQUITY, INCOME, EXPENSE), `base_currency`,
  `parent_account_id`.
- **Transaction** (aggregate root): `id` (UETR or deterministic hash),
  `posted_at`, `value_at`, `status` (PENDING, POSTED, CLEARED, RECONCILED),
  `payee`, `narration`, `postings[]`.
- **Posting** (value object, the split): `account_id`, `amount` (Decimal,
  signed), `commodity` (ISO 4217 code or ticker), optional `cost_spec` (FX/cost
  metadata), optional `lot_spec` (acquisition date, unit price).
- **Holding / tax lot** (brokerage): `symbol` (ISIN/ticker), `quantity`,
  `cost_basis`, `realized_gain`.

**Invariant:** postings within a transaction sum to zero when evaluated at their
stated cost/price. This is the validation Beancount enforces for free, and the
reason import bugs surface immediately.

Instrument mapping: current and savings accounts are ASSET, credit cards are
LIABILITY (purchases increase liability and balance an expense; repayments
reduce it), brokerage is ASSET split across cash and securities sub-accounts.

**One divergence worth noting:** that report models holdings/tax lots as
*stored entities* alongside postings. Prefer **deriving** holdings from postings
with cost annotations (as Beancount does). Storing both creates two sources of
truth that can drift. Treat holdings as a computed projection, not persisted
state.

### Worked examples

Split (ATM withdrawal with fee):

```
Assets:PostFinance:Checking   -152.50 CHF
Assets:Cash:Wallet            +150.00 CHF
Expenses:BankFees               +2.50 CHF
```

Transfer between own accounts (net worth unchanged, one transaction not two):

```
Assets:PostFinance:Checking   -500.00 CHF
Assets:ZKB:Savings            +500.00 CHF
```

Multi-currency purchase (EUR item settled in CHF):

```
Assets:PostFinance:Checking    -96.50 CHF
Expenses:Shopping             +100.00 EUR @ 0.965 CHF
```

Investment buy with commission (cash settlement decoupled from lot):

```
Assets:Brokerage:USD Cash    -1005.00 USD
Assets:Brokerage:Equities:VT      +10 VT {100.00 USD}
Expenses:Brokerage:Commissions  +5.00 USD
```

Each sums to zero. Note all four requirements (splits, transfers,
multi-currency, brokerage lots) are handled by the *same* structure, with no
special-case types. Compare pybank's current model, which needs a separate class
per investment event.

### Domain element to storage mapping

The model is serialization-agnostic. The same elements map cleanly onto every
candidate store, which is what makes the encoding choice reversible:

| Domain element | SQL (SQLite/Postgres) | Beancount / Ledger | JSON / REST | ISO 20022 camt.053 |
|---|---|---|---|---|
| Account | `accounts` row | `open Assets:PF:Checking CHF` | `/accounts/{id}` | `<CashAccount>` |
| Transaction | `transactions` row | dated entry header | parent record | `<Ntry>` |
| Posting / split | `postings` row | indented posting line | `splits[]` | `<TxDtls>` |
| Commodity | FK or ISO code | symbol on the amount | `"currency"` | `<Amt Ccy="CHF">` |
| Lot | `tax_lots` row | `{100.00 USD}` annotation | position object | OpenWealth custody |

### Implementation shape (ports and adapters)

1. **Domain types**: `beancount.core.data`, adopted directly. See next section.
2. **Ingestion adapters** per institution (CSV, camt.053, OFX, IBKR Flex, FinTS)
   converting raw input into Transaction aggregates.
3. **Persistence/export adapters** serializing to `.beancount` or OFX.

pybank's existing `importer/*` layer already matches step 2. The work is
step 1 (retire most of `model.py`) and step 3 (replace the QIF writer).

## Domain model: adopt beancount.core.data

**Decision: Use Beancount's own core types as pybank's domain model.** Do not
write our own classes that mirror them.

The deciding argument: These are not an app schema. They are a direct encoding
of the textbook double-entry model, as immutable NamedTuples, stable for over a
decade. Choosing them *is* choosing the standard model, so the domain-model and
serialization decisions collapse into one. That is the strongest form of
"domain model first": The serialization is the model's canonical text encoding.

### Type inventory

| Type | Fields (essentials) | Role |
|---|---|---|
| `Transaction` | `meta, date, flag, payee, narration, tags, links, postings` | Aggregate root |
| `Posting` | `account, units, cost, price, flag, meta` | One leg |
| `Amount` | `number: Decimal, currency: str` | Money, correctly |
| `Cost` / `CostSpec` | number, currency, date, label | Lot acquisition basis |
| `Open` / `Close` | `account, currencies, booking` | Account lifecycle |
| `Balance` | `account, amount, tolerance` | Bank-reported balance as assertion |
| `Price` | `currency, amount` | FX rates, security quotes |
| `Commodity`, `Pad`, `Note`, `Document`, `Event`, `Custom` | | Supporting directives |
| `Position` / `Inventory` | units + cost, aggregated | **Derived** holdings, never stored |

### Two structural shifts from today's model.py

**Accounts are strings, not a class hierarchy.** `Assets:PostFinance:Checking`
is the whole account object, the root segment carries the typing. The current
`CheckingAccount` / `SavingsAccount` / `InvestmentsAccount` / `CreditCard`
subclasses (empty bodies today) disappear. An `Open` directive declares the
account and its allowed currencies.

`Account.balance` / `balance_date` become `Balance` directives. Instead of
storing a balance as a mutable field, assert what the bank reported and let the
loader verify our transactions sum to it. A free integrity check per import.

**Event types become posting shapes, not classes.** The entire
`InvestmentDividend` / `InvestmentSecurityPurchase` / `InvestmentInterestIncome`
hierarchy collapses. A dividend is not a class:

```python
Transaction(meta, date, flag="*", payee="IBKR", narration="VT dividend",
    tags=set(), links=set(), postings=[
        Posting("Assets:IBKR:USD-Cash", Amount(D("52.30"), "USD"),
                None, None, None, None),
        Posting("Income:Dividends:VT", Amount(D("-52.30"), "USD"),
                None, None, None, None),
    ])
```

New event type from a new bank means new account names, zero new classes. That
is the extensibility win, and it kills the `amount: int | float` float-money bug
in the same stroke.

### Three extension tiers for app-specific data

Put each kind of data in the right tier:

| Need | Mechanism |
|---|---|
| Unmapped CSV column, MCC, auth code, dedup hash, source file | `meta` dict on Transaction or Posting |
| Budgeting, new directive types | `Custom` directives |
| Reconciliation workflow state | Sidecar, outside the ledger |

**`meta` for unmapped fields.** Every Transaction and Posting carries a
key-value dict that round-trips through parse/print and is queryable in BQL:

```
2026-07-15 * "Migros" "Groceries"
  import-hash: "a3f9c1"
  mcc: "5411"
  Assets:PostFinance:Checking  -84.20 CHF
  Expenses:Food:Groceries
```

Limitation: `meta` values are scalars only, no lists or nesting. Needing a list
is the signal that the data belongs in the sidecar. Keep pybank's metadata keys
in a small constants module, since `meta` is stringly-typed.

**`Custom` directives for budgeting.** The designed escape hatch for new
directive types: The loader parses and carries them, apps interpret them. Fava's
budget feature already works this way
(`2026-01-01 custom "budget" Expenses:Food "monthly" 600.00 CHF`), so we inherit
an existing ecosystem convention and Fava's budget UI rather than inventing one.

**Sidecar for workflow state.** Architectural line: The ledger stores settled
facts, in-flight workflow state is app state.

- Auto-inferred category candidates (possibly several), confidence scores,
  review-queue position: Sidecar (JSON or SQLite) keyed by the dedup hash.
  Deliberately disposable. Losing it costs re-triage, never data.
- The pending vs approved distinction *inside* the ledger: Use flags. `!` needs
  review, `*` confirmed. Importer writes `! ... Expenses:Uncategorized`,
  approval flips the flag and sets the final counter-account. `smart_importer`
  already covers the ML-predicted-posting half of this.

Rule of thumb: Temporary or multi-valued means workflow state, not a fact.

### Usable as a library, independently

Yes, and this is one of Beancount's better properties. Since v3 it ships as
separate PyPI packages: `beancount` (core types, loader, printer, no UI, no
server, no daemon), `beanquery`, `beangulp`, `fava`. pybank depends only on what
it uses.

```python
from beancount.core.data import Transaction, Posting
from beancount.core.amount import Amount        # construct, zero I/O
from beancount import loader                    # load_file / load_string
from beancount.parser import printer            # directives -> text
```

The `bean-check` / `bean-format` CLIs are entry points over the same library.
Proof by ecosystem: Fava, beanquery, and smart_importer are all independent
packages consuming the core exactly as pybank would.

### Rejected alternative: a thin layer of our own

Runner-up was our own frozen dataclasses plus converters to Beancount
directives, for insulation against API churn and to get validation at
construction. Rejected:

- A translation layer to write and maintain, for types this simple.
- The core API has been stable across v2 to v3. The churn was in the importer
  framework (`beancount.ingest` to `beangulp`), which we adopt fresh anyway.
- If it ever becomes necessary, wrapping NamedTuples later is cheap. The reverse
  migration (our schema to theirs) is what would be expensive.

### Known costs, accepted

- **License: Beancount is GPL-2.0, pybank is MIT.** Assessed and accepted. Running
  it carries no obligations at all (GPLv2 §0 excludes execution from scope).
  Publishing pybank source on GitHub does not distribute Beancount: `pip` fetches
  it onto each user's machine, so no combined work is ever distributed. Even
  under the maximalist reading that importing a GPL library creates a derivative
  work, MIT is GPL-compatible and our source is already public. Precedent: Fava
  is MIT, imports GPL-2.0 Beancount, and lives in the Beancount GitHub org
  itself. `beangulp` and `beanquery` are GPL-2.0 too, same analysis. Obligations
  would attach only on shipping a bundled artifact (PyInstaller binary, Docker
  image with Beancount baked in), vendoring its source, or licensing pybank
  proprietarily. None are intended. Add a README note recording this.
- **No surgical file edits.** Parse then print normalizes formatting and drops
  comments. There is no API to edit one entry in place. Appending is trivial and
  covers the import path, but "approve this transaction" means rewriting its
  lines. Fava solved this with its own line-based editing code. Options: Append
  only with edits in an editor or Fava, or borrow Fava's approach. This is the
  largest design consequence, and it shapes the reconciliation UI.
- **Bus factor.** Essentially one author (Martin Blais). Development is
  deliberate, not dead. Mitigated by the data outliving the library: The format
  is documented plain text with independent parsers (rustledger and others), so
  the worst case is swapping implementation, not migrating data.
- **Strict loader.** Every account needs an `Open`, every transaction must
  balance within tolerance. FX rounding legs will trip importers early. Solved
  conventionally with tolerance settings or an `Equity:Rounding` posting.
- **Immutability friction.** NamedTuples are frozen. Modifying means
  `._replace()` and rebuilding lists. Fine functionally, alien coming from ORMs.
- **Sidecar drift.** Any sidecar can disagree with the ledger. Mitigated by the
  disposability rule: Keyed by dedup hash, rebuildable, never authoritative.

## UX implications: statement view over a ledger model

Concern: users without an accounting background think in statements. Does
double-entry force them to hunt for matching accounts and keep things balanced?

No. The model is double-entry, the UI is not.

**Categorization is the second leg.** In a statement-model app the
per-transaction job is "assign a category". In a ledger it is "pick the
counter-account". Same action, different vocabulary. The user picks
`Food:Groceries` and never sees the word posting.

**Balancing is the importer's job.** One leg always arrives from the bank with
an authoritative amount. The counter-leg amount is derived by subtraction, which
is why Beancount, Ledger, and hledger all allow eliding the final amount. In a
split the user enters N-1 amounts and the residual auto-fills. The sum-to-zero
invariant exists to catch pybank bugs, not to police the user.

**The income/expense overview is harder in the statement model.** A 2000 CHF
transfer between two own accounts appears as two rows. Categorized naively it
reports 2000 of expense and 2000 of income that never happened. Fixing it needs
a magic "Transfer" category excluded from reports plus row-matching logic, which
is the second leg reimplemented as a special case. In the ledger both postings
sit under `Assets:`, so a report over `Income:*` and `Expenses:*` excludes it
structurally. Same for gross salary minus deductions, and for a EUR purchase
settled in CHF. The overview is the double-entry income statement: A query over
the data, not a layer on top.

Vocabulary mapping for the UI:

| Model concept | What the user sees |
|---|---|
| `Assets:*`, `Liabilities:*` | Accounts: checking, card, savings, brokerage |
| `Income:*`, `Expenses:*` | Categories |
| `Equity:*` | Nothing. Opening balances only |
| Posting sign | Statement sign, relative to the account in view |
| Transaction with 2 postings | A normal row with a category |
| Transaction with 3+ postings | A row with a split expander |
| `Expenses:Food:Groceries` | Breadcrumb picker: Food > Groceries |

GnuCash's UX problem is exposing the mechanics, a UI choice, not a consequence
of the model. Firefly III stores source and destination on every transaction,
which is double-entry, and presents it as withdrawal, deposit, transfer.

Genuine work, none of it extra:

- Uncategorized imports: Default the counter-leg to `Expenses:Uncategorized` so
  nothing ever blocks. Triage later. Rules and learned payee mappings cover most.
- Transfer detection: Matching the two sides is real work, but any model
  ingesting two accounts needs that dedup, and the statement model needs the
  exclusion hack on top.
- Splits and lots: Same effort as a statement-model split UI, except the ledger
  has somewhere to put the result.

## Why double-entry

Map the requirements to features:

| Requirement | Double-entry answer |
|---|---|
| Split transaction | One transaction, multiple postings/splits. Native. |
| Transfer between own accounts | One transaction, two asset-account postings. Native, and dedupable (both statements show the same transfer). |
| Multi-currency | Currencies are commodities. Native. |
| Brokerage | Securities are commodities with quantity + cost basis + lots. Dividends, interest, fees as postings. Native. |
| Current / savings / credit card | Trivial asset/liability accounts. |

Single-entry formats (QIF, and mostly OFX) cannot express splits or link the two
sides of a transfer. That alone rules them out as the store. The four
requirements are the textbook argument for a double-entry model.

## Candidates, ranked by fit

### 1. Beancount (recommended) — 5.8k stars

Plaintext double-entry accounting in Python. Current stable v3 (June 2024).

- **Fit:** excellent. Python-native, so pybank uses it as a library, not a
  subprocess. Commodities + cost basis cover brokerage. Multi-currency,
  splits (postings), transfers all native. Strong validation: the ledger must
  balance, which catches import errors early.
- **Storage mapping:** the `.beancount` file is the open format and the store at
  once. Git-versioned, diffable, greppable. Query with BQL (`beanquery`). No DB
  server. If a SQL DB is ever wanted, export is straightforward.
- **Ecosystem:** `fava` (2.5k) web UI for viewing/reporting, `beangulp` (142)
  importer framework, `smart_importer` for ML-assisted categorization. `beangulp`
  maps directly onto pybank's `importer/*` layer.
- **Cons:** strict and opinionated (a virtue for data integrity, a learning
  curve otherwise). A statement gives one posting leg; you must supply the
  contra account (category → account map, or a `Expenses:Unknown` placeholder).
  Lot/cost-basis booking is powerful but has a learning curve.

### 2. GnuCash + piecash (runner-up) — 4.3k / 347 stars

Desktop double-entry app with XML or SQLite storage. `piecash` reads/writes the
SQLite file from Python.

- **Fit:** very good. Splits are a first-class concept, commodities cover
  brokerage, multi-currency native. This is the option that bundles a real
  **database (SQLite)** + an **open format** + a **GUI** together.
- **Cons:** `piecash` is far less popular (347) and less actively developed than
  Beancount. Schema is app-driven, heavier than plaintext, not git-diffable in a
  meaningful way (binary-ish SQLite). Writing must respect GnuCash's invariants.
- **Choose if:** you want a GUI and a queryable DB without running a server, and
  don't care about plaintext/git.

### 3. Ledger — 6.0k stars / hledger — 4.6k stars

The original (C++) and the Haskell rewrite. Same plaintext double-entry family as
Beancount, fully capable of every requirement.

- **Fit:** good on format, weaker for pybank specifically: **neither is
  Python-native.** pybank would emit text and shell out to the binary for
  reports. Ledger's format is the most lenient (less validation); hledger has the
  best docs/UX.
- **Choose if:** you prefer Ledger/hledger tooling. Note Beancount can convert to
  Ledger syntax (`beancount2ledger`), so picking Beancount does not lock you out.

### 4. OFX via ofxtools (interchange, not store) — 343 stars

OFX is *the* bank/brokerage statement-download standard (v1 SGML, v2 XML).
`ofxtools` has the best OFX **investment** message support in Python (its author,
csingley, also wrote `ibflex`, which the IBKR plan already uses).

- **Fit as store:** poor. Statement-shaped, verbose, no double-entry, weak
  multi-currency. But as an **export/interop target it is the best standard**,
  and as an *import* format it is richer than most bank CSVs.
- **Role:** replace pybank's QIF writer with an OFX writer for interop. Consume
  OFX where a bank offers it (better than scraping CSV).

### 5. Firefly III — 24.1k stars / Actual — 27.7k stars (apps, not stores for us)

The most popular by far, but they are **applications, not libraries**.

- **Firefly III:** self-hosted (PHP + MySQL/Postgres), double-entry-ish, great
  multi-currency, rules engine, REST API. But **weak on investments/brokerage**,
  and integrating means running a server and POSTing via API. It is a possible
  *destination app* to push pybank data into, not pybank's own store.
- **Actual:** envelope budgeting, polished, local SQLite. **No investment
  tracking.** Wrong shape for brokerage.
- **Role:** optional downstream. Could export pybank → Firefly III via its API
  later. Not the canonical format.

### Also-ran: QIF (current), camt.053, MT940

QIF is the legacy output to retire. camt.053 and MT940 are bank *source* formats
(covered in the PostFinance/DKB docs), not multi-account stores.

## Popularity summary

| Project | Stars | Category | Role for pybank |
|---|---|---|---|
| Actual | 27.7k | Budget app | Not a fit (no investments) |
| Firefly III | 24.1k | Finance app | Optional downstream via API |
| Ledger | 6.0k | Plaintext DE (C++) | Alt format, not Python-native |
| **Beancount** | **5.8k** | **Plaintext DE (Python)** | **Proposed canonical store** |
| hledger | 4.6k | Plaintext DE (Haskell) | Alt format, not Python-native |
| GnuCash | 4.3k | Desktop app | Runner-up (DB + GUI) |
| Fava | 2.5k | Beancount web UI | Proposed viewer |
| piecash | 347 | GnuCash SQLite lib | With GnuCash option |
| ofxtools | 343 | OFX lib | Proposed interchange export |
| ofxparse | 218 | OFX lib | Alt OFX reader |
| beangulp | 142 | Beancount importers | Proposed importer layer |

Popularity note: Firefly III / Actual win on stars because they are end-user apps.
Among *libraries you build on*, Beancount is both the most popular and the best
technical fit, and its ecosystem (fava, beangulp) adds thousands more stars.

## Storage strategy: files vs database

- **Plaintext files (Beancount):** the file is the store and the open format.
  Git gives version history, blame, and diffs on every import. No server. Query
  via BQL. Best fit for a personal, code-driven tool. **Recommended.**
- **Single-file DB (GnuCash SQLite via piecash):** portable open schema, SQL
  queries, GUI. No server, but not git-friendly. The runner-up.
- **Custom DB (e.g. SQLModel + SQLite):** pybank already uses Pydantic, so
  SQLModel would be a small step. Full control, but you invent a **non-standard**
  schema and forfeit the open-format payoff. Only worth it if neither Beancount
  nor GnuCash can express something (unlikely here). If chosen, still export to
  OFX/Beancount for interop.
- **App DB behind an API (Firefly III):** heaviest. A server to run and back up.
  Reasonable only if you specifically want Firefly III as the front end.

## Proposal for pybank

1. **Canonical store: Beancount plaintext**, one repo/dir of `.beancount` files
   (e.g. split by account or by year, with an `Accounts` declarations file).
   Version-controlled in git.
2. **Retire most of `model.py`.** Importers emit `beancount.core.data`
   directives directly, with no intermediate pybank model to translate through.
   Each import produces a `Transaction` with the bank leg plus a contra account
   (from `category`, else `Expenses:Uncategorized`), a `Balance` assertion from
   the statement balance, and `Open` directives for new accounts. Investment
   events become postings with commodity, `{cost}`, and `@ price` rather than
   subclasses. Still needed: The **contra-account** decision (today only one leg
   is recorded) and a **transfer dedup key** so a transfer seen on both
   statements collapses to one transaction.
3. **Importer layer via `beangulp`**, reusing existing per-bank parsing logic.
   Its interface is `identify()`, `account()`, `extract()` returning directives,
   which matches pybank's existing importer concept. Dedup against the existing
   ledger is built into the framework.
4. **Interchange export: OFX via `ofxtools`** to replace the QIF writer. Optional
   `beancount2ledger` if Ledger output is ever needed.
5. **Viewing/reporting: `fava`** (read-only) + BQL for ad-hoc queries. No custom
   UI needed.
6. **Defer the DB.** Start with files. Revisit GnuCash/SQLite or a custom DB only
   if a concrete need appears (e.g. heavy programmatic querying that BQL cannot
   serve).

Net: Beancount gives one open, popular, Python-native, git-friendly format that
covers all four account types and all three hard requirements, replaces QIF, and
answers the storage question in the same stroke.

## Model-hardening notes (from external cross-check)

A second, independent report ("Standard Financial Transaction Data Formats and
Schemas", enterprise-architecture angle) was compared against this doc. Same
conclusions on layering (interchange vs canonical) and double-entry. Useful
specifics adopted from it:

- **No floats for money.** Use `Decimal` (or integer minor units) + ISO 4217
  code. `model.py` currently has `amount: int | float`. Fix during the model
  rework. Beancount uses `Decimal` natively, so adopting it forces this anyway.
- **Deterministic transaction identity.** Banks rarely provide UETR/EndToEndId,
  so synthesize a stable ID: hash of account ID + settlement date + settled
  amount + raw remittance text + counterparty. Serves both duplicate-import
  protection and transfer matching.
- **Three-tier FX amounts.** Instructed (original face value) → settlement
  (what hit the account) → base reporting currency. Maps onto Beancount's
  `@ price` / `{cost}` annotations. Keeps currency gains separable from asset
  returns.
- **ISO Bank Transaction Codes** (Domain/Family/SubFamily hierarchy in camt):
  standardized categorization worth using as input to the category →
  contra-account mapping.
- **Credit-card lifecycle:** pending authorization (MCC, auth code, terminal FX
  estimate) vs settled posting. Statements only give the settled stage; model
  posting date vs value date as dual timestamps.
- **OpenWealth API** as a schema reference for brokerage: an open Swiss standard
  for custody data (`/positions`, `/transactions`, corporate actions), filling
  the investment gap PSD2-style AIS leaves. TPP-gated like bLink, so not a data
  source for us, but a good reference for modeling positions/lots/corporate
  actions.

Where that report diverges: it recommends a bespoke canonical JSON schema
(sound for an enterprise aggregation platform, but for pybank it reinvents a
non-standard model, see ranking above), and it ignores plaintext accounting and
library popularity entirely.

A third report ("Canonical Financial Domain Model Architecture") was also
reconciled. It independently arrives at the same domain-model-first layering and
the double-entry ledger model, and supplied the concrete entity decomposition,
worked examples, storage mapping matrix, and ports-and-adapters shape now folded
into the domain-model section above. It is silent on format/library choice, so
it neither supports nor contradicts the Beancount recommendation. Its one
divergence (holdings as stored entities) is noted inline.

## Prior art: the flofi categorization cascade

`flofi categories.txt` (docs/research/) documents a working categorization
pipeline worth reusing rather than reinventing. Five stages, first match wins,
after normalizing the booking text (strip bank boilerplate, lowercase, strip
accents, collapse whitespace):

1. **Exclusions** (`exclusions.yaml`): Transfers between own accounts,
   Finpension deposits, IBKR transfers. Marked `is_excluded`, dropped from
   reporting.
2. **AI cache**: Booking text to category table, so each distinct text hits the
   model once.
3. **Rule engine** (`rules.yaml`): Hand-written patterns. Only two kinds of
   entries, knowledge no model can guess (`Google Switzerland` = salary), and
   high-frequency merchants where errors hurt (coop, migros, lidl, SBB).
4. **Fuzzy merchant matching** (`merchants.yaml`, ~900 entries): `rapidfuzz`
   `token_set_ratio`, threshold 75. Handles word order and trailing noise.
5. **AI fallback**: Batched 20 per request, with Swiss context in the prompt.
   Result written straight to the cache.

Roughly 35 categories, additionally grouped into fixed / variable_essential /
discretionary. Every transaction records its provenance (rule, fuzzy, ai,
manual). Re-applying rules recomputes only the automatic ones, never
hand-corrected values. Failed AI calls leave the category NULL rather than
guessing. Known trap: The cache sits before the rules, so editing `rules.yaml`
does not affect texts already cached.

How this maps onto the Beancount model:

| flofi concept | Beancount equivalent |
|---|---|
| Stage 1 exclusions, `is_excluded` | Not needed. Both legs land under `Assets:`, so `Income:*`/`Expenses:*` reports exclude them structurally |
| Category | Contra-account (`Expenses:Food:Groceries`) |
| fixed / variable_essential / discretionary | Tags, or a level in the account tree. Open question |
| Provenance (rule, fuzzy, ai, manual) | `meta` key, e.g. `category-source: "fuzzy"` |
| Never overwrite manual | Flag `*` (confirmed) vs `!` (needs review) |
| Category NULL on failure | `Expenses:Uncategorized` plus `!` flag |
| AI cache | Sidecar, not ledger state |

Stage 1 disappearing is a concrete instance of the earlier UX argument: The
statement model needs an exclusion flag plus row matching, the ledger gets the
same result from structure.

## Decision backlog

Ordered by how much they constrain everything else. Decided items marked.
Sequencing: See [../plans/README.md](../plans/README.md).

1. **Where the ledger data lives.** Decided: A private Google Drive folder,
   path via local config. Drive version history covers rollback, no atomic
   write ceremony needed (sync self-heals once a write completes). `.gitignore`
   guard in pybank so ledger files cannot land in the public repo. Upgrade
   path: Private git repo later if diff-based review becomes wanted.
2. **Storage shape** (decision #3 above). Decided: Plaintext only. Add a
   derived SQLite read model only when a query is actually too slow.
3. **Chart of accounts.** Partially decided: Per-currency brokerage cash
   (confirmed by IBKR's own per-currency statement exports), credit cards as
   `Liabilities:*`, base currency CHF. Exact naming convention finalized in
   Phase 1.
4. **Category tree.** Map flofi's ~35 categories onto `Expenses:*` / `Income:*`.
   Decide how fixed / variable_essential / discretionary is represented: Tags,
   metadata, or an account-tree level.
5. **Categorization pipeline scope for v1.** Decided: Rules-based only in
   Phase 3 (flofi stages 1 to 3). Fuzzy matching and AI fallback deferred to
   Phase 5 (add an API dependency and cost).
6. **Transfer handling.** Decided: Route through an
   `Assets:Transfers:InTransit` clearing account, simpler for importers and
   self-reconciling. Detection key (date window, amount, counter-account) and
   tolerance settled in Phase 3.
7. **Reconciliation surface.** Fava, a custom UI, or editor-only. Constrained by
   the no-surgical-edits limitation above.
8. **Brokerage booking method.** FIFO, AVERAGE, or STRICT, declared per `Open`.
   Whether to track lots from day one. Note Swiss private capital gains are
   generally tax-free, so lots matter more for performance reporting than tax.
9. **File layout.** Single ledger with includes, per-account, or per-year. Where
   `Open` / `Commodity` declarations live.
10. **v1 scope and backfill.** Decided: PostFinance, DKB, IBKR first. They
    cover every account archetype (checking, savings, credit card, brokerage)
    across CHF and EUR. Backfill depth settled in Phase 3 (DKB archive goes
    back to 2008).
11. **Dependency cleanup.** Decided: Keep `selenium` and the old scrapers
    until the Phase 4 rebuild reaches parity, then delete (learn from the code
    first). Drop `pydantic` at end of Phase 2. Add `beancount` (Phase 1),
    `beangulp` (Phase 2), `playwright` (Phase 4), `ofxtools` (Phase 5).
12. **Downstream push.** Whether to also feed a downstream app (Firefly III) or
    stop at Beancount. Deferrable, purely additive.

## Sources

- [Beancount | GitHub](https://github.com/beancount/beancount) (GPL-2.0)
- [Beancount v3 docs | beancount.github.io](https://beancount.github.io/)
- [beancount/core docs (directives, basic types) | GitHub](https://github.com/beancount/beancount/blob/master/beancount/core/docs.md)
- [Fava (Beancount web UI) | GitHub](https://github.com/beancount/fava) (MIT, imports GPL-2.0 Beancount: The license precedent)
- [beangulp (Beancount importers) | GitHub](https://github.com/beancount/beangulp) (GPL-2.0)
- [beanquery (BQL) | GitHub](https://github.com/beancount/beanquery) (GPL-2.0)
- [smart_importer (ML-assisted categorization) | GitHub](https://github.com/beancount/smart_importer)
- [GNU GPL v2 §0 (running the program is not restricted) | gnu.org](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html)
- [Comparison of Beancount and Ledger/hledger | Beancount docs](https://bradyt.github.io/beancount-docs/15_a_comparison_of_beancount_and_ledger_hledger/)
- [Ledger | GitHub](https://github.com/ledger/ledger)
- [hledger | GitHub](https://github.com/simonmichael/hledger)
- [GnuCash | GitHub](https://github.com/Gnucash/gnucash)
- [piecash (Python GnuCash) | GitHub](https://github.com/sdementen/piecash)
- [ofxtools (Python OFX, investment support) | GitHub](https://github.com/csingley/ofxtools)
- [ofxparse | GitHub](https://github.com/jseutter/ofxparse)
- [Firefly III | GitHub](https://github.com/firefly-iii/firefly-iii)
- [Actual Budget | GitHub](https://github.com/actualbudget/actual)
- [OpenWealth API | openwealth.ch](https://openwealth.ch/)
- [Financial Data Exchange (FDX) | financialdataexchange.org](https://financialdataexchange.org/)
- [ISO 20022 message definitions / business model | iso20022.org](https://www.iso20022.org/iso-20022-message-definitions)
- [Analysis Patterns: Reusable Object Models (accounting patterns) | Martin Fowler](https://martinfowler.com/books/ap.html)
- [BIAN (Banking Industry Architecture Network)](https://bian.org/)
- Cross-checked reports (docs/research/, external agent research):
  "Standard Financial Transaction Data Formats and Schemas",
  "Canonical Financial Domain Model Architecture for Personal Finance and
  Multi-Asset Accounting"
