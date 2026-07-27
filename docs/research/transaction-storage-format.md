# Transaction storage format: research + proposal

How to store pybank transactions across multiple accounts in a common,
standardized format. Must cover current accounts, credit cards, savings, and
brokerage, with multi-currency, split transactions, and transfers. Ranked by
fit, popularity, pros/cons. Date: 2026-07-26.

## Proposal (TL;DR)

- **Adopt Beancount as the canonical format and the store.** Plaintext
  double-entry accounting, written in Python (native library for pybank), files
  versioned in git. The requirements list (splits, transfers, multi-currency,
  brokerage) is precisely what double-entry accounting exists to model. With
  Beancount the "local files vs database" question dissolves: the plaintext file
  *is* both the open format and the store, queryable via BQL (beanquery).
- **Keep an interchange export.** Replace the legacy QIF writer with **OFX**
  (via `ofxtools`) for interop with other finance tools that want to import
  pybank data. OFX is the one interchange standard that also covers brokerage.
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

1. **Domain classes** in Pydantic, enforcing Decimal arithmetic and the
   sum-to-zero invariant.
2. **Ingestion adapters** per institution (CSV, camt.053, OFX, IBKR Flex, FinTS)
   converting raw input into Transaction aggregates.
3. **Persistence/export adapters** serializing to `.beancount`, OFX, or SQL.

pybank's existing `importer/*` layer already matches step 2. The work is
step 1 (rework `model.py`) and step 3 (replace the QIF writer).

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
2. **Map the model → Beancount directives.** `model.Payment` → a `Transaction`
   with two postings (the account leg + a contra account from `category`, else
   `Expenses:Unknown` / `Income:Unknown`). Investment types → postings with
   commodity, `{cost}`, and `@ price`. Currency stays the commodity. This
   requires enriching the model to know the **contra account** (today it records
   only one leg), and a **transfer dedup key** so a transfer seen on both
   statements collapses to one transaction.
3. **Importer layer via `beangulp`**, reusing existing per-bank `can_import` and
   parsing logic. Keeps the current importer design, gains a mature framework.
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

## Open design questions (for iteration)

- Contra-account strategy: category → account mapping table vs placeholder +
  later reclassification (fava, smart_importer).
- Transfer matching: dedup key (date + amount + counter-account) and tolerance.
- Brokerage booking method (FIFO/average) and whether to track lots now or later.
- File layout: per-account vs per-year vs single ledger with includes.
- Whether to also push to a downstream app (Firefly III) or stop at Beancount.

## Sources

- [Beancount | GitHub](https://github.com/beancount/beancount)
- [Beancount v3 docs | beancount.github.io](https://beancount.github.io/)
- [Fava (Beancount web UI) | GitHub](https://github.com/beancount/fava)
- [beangulp (Beancount importers) | GitHub](https://github.com/beancount/beangulp)
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
