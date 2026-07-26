# Interactive Brokers + DKB data extraction: research

Research on ways to extract Interactive Brokers (IBKR) and Deutsche Kreditbank
(DKB) account and transaction data, ideally automated. Scope: private/retail
customer, recurring pulls, read-only. Companion to
[postfinance-data-extraction.md](postfinance-data-extraction.md).
Date: 2026-07-26.

## TL;DR

- **Both are far better than the Swiss situation.** Unlike PostFinance, neither
  forces you onto scraping. Each has a genuine programmatic path for an
  individual.
- **IBKR: use the Flex Web Service.** A token-based reporting API. Generate a
  read-only token (lifetime up to 1 year) plus a saved Flex Query, then pull an
  XML/CSV Activity statement over HTTPS. **No interactive login, no per-run 2FA.**
  This is the single best data source across all banks researched. It replaces
  pybank's dead IBKR Selenium scraper outright.
- **DKB: use FinTS/HBCI or the maintained `dkb-robo` library.** Germany has PSD2,
  and DKB still runs a consumer **FinTS** server (`fints.dkb.de/fints`). FinTS is
  a real, documented protocol reachable with `python-fints`. Catch: since
  2024-11-25 DKB requires a **TAN approval on every login** (pushTAN via DKB app,
  or chipTAN). So DKB is "one tap per run", like PostFinance, but over a clean
  protocol instead of DOM scraping.
- **pybank's existing scrapers for both are dead.** Both use Selenium 3's removed
  `find_element_by_*` API. The DKB one additionally targets the old
  `dkb.de/banking` UI that DKB retired in July 2023. Replace, do not port.
- **Read-only:** IBKR Flex is inherently read-only (reporting only, no trading).
  DKB FinTS with a read scope still needs the per-login TAN. Neither PSD2/XS2A
  raw API is open to individuals (same licensed-TPP gate as Swiss bLink).

## Context: what pybank already has

- IBKR: `download/ib.py` (Selenium scraper of the client portal, downloads the
  Activity Statement CSV) + `importer/ib.py` (parses that CSV into trades,
  dividends, interest, withholding tax, fees, transfers, forex). The importer
  logic is good and reusable. The scraper is obsolete.
- DKB: `download/dkb.py` (Selenium scraper of `dkb.de/banking`) + `importer/dkb.py`
  (CSV importer for checking `Girokonto` and credit card `Kreditkarte:`).
- Both scrapers use `find_element_by_*` (removed in Selenium 4). The DKB scraper
  also drives a UI that no longer exists. Both need replacing, not porting.

---

# Interactive Brokers

IBKR is the best case in this whole research effort: a broker that actually
publishes APIs for clients to read their own data, no business contract, no TPP
license.

## 1. Flex Web Service (recommended)

A token-based reporting API. You predefine a "Flex Query" (which sections and
fields you want) in the web portal, then fetch it programmatically.

**Setup (one-time, in Client Portal):**
1. Reports / Tax Docs → Flex Queries. Create an **Activity Flex Query**, select
   sections (trades, cash transactions, dividends, interest, deposits &
   withdrawals, withholding tax, fees, open positions, etc.). Note its Query ID.
2. Settings → enable the **Flex Web Service** and generate a **token**. Token
   lifetime is configurable, up to **1 year**.

**Request flow (two HTTPS GETs, version `v=3`):**
1. `SendRequest` with the token + Query ID. Returns a numeric **reference code**.
2. `GetStatement` with the token + reference code. Returns the statement as
   **XML** (or CSV).

**Properties that make it ideal:**
- **No interactive login and no per-run 2FA.** The token is the credential. This
  is the only source researched that is truly unattended.
- **Read-only by nature.** Flex is reporting only. No trading capability. Matches
  the read-only requirement perfectly.
- **Structured, stable schema.** XML with documented fields. Far more robust than
  scraping the portal DOM or relying on CSV column order.
- Activity statements update **once daily at close of business**, so a daily
  cron is the natural cadence. Intraday polling adds nothing.

**Python:** `ibflex` (`csingley/ibflex` on GitHub, on PyPI) parses Flex XML into
typed objects and can also drive the download. Recommended over hand-rolling.

**Content vs pybank's current importer:** the Activity Flex covers exactly the
categories `importer/ib.py` already models (trades, forex, dividends, interest,
withholding tax, fees, deposits & withdrawals). Migrating from CSV-scrape to Flex
XML is a data-source swap, not a model change.

**Downside:** the token is a long-lived bearer secret. Store it like a password
(env var / secret manager), scope the Flex Query to what you need, rotate it.

## 2. Client Portal Web API (a.k.a. IBKR Web API)

REST API for real-time portfolio, positions, and account data.

- **Auth:** OAuth 2.0, `private_key_jwt` client authentication (RFC 7521/7523).
  Has a two-tier session: a read-only **Portal session** (non-trading resources)
  and a brokerage session.
- **Consolidation:** IBKR is merging the Client Portal API, Digital Account
  Management, and the Flex Web Service into one unified **IBKR Web API** behind
  OAuth 2.0. Worth tracking, since Flex may eventually live under it.
- **Fit:** more setup than Flex (key pair, OAuth dance, and historically a
  running gateway process for the session-cookie variant). Overkill if the goal
  is periodic statement extraction. Choose this only if you need near-real-time
  balances/positions rather than end-of-day statements.

## 3. TWS API (not for this use case)

The classic socket API (Python `ib_insync` / `ib_async`, or the native TWS API)
requires **Trader Workstation or IB Gateway running and logged in**. Great for
live trading and market data, wrong tool for unattended reporting. Skip.

## IBKR ranking

1. **Flex Web Service** — token, XML/CSV, unattended, read-only. Use this.
2. **Client Portal / Web API** — only if you need real-time data. More auth setup.
3. **TWS API** — needs a running desktop session. Not for reporting.
4. Selenium scraping — obsolete once Flex is in. Delete.

---

# Deutsche Kreditbank (DKB)

DKB sits under EU PSD2 and the German **FinTS** standard, so an individual has
real protocol options. The tradeoff is a mandatory TAN per login since late 2024.

## 1. FinTS / HBCI (recommended protocol route)

FinTS (formerly HBCI) is the German home-banking standard that desktop finance
apps (StarMoney, MoneyMoney, Hibiscus) use. It is a documented protocol, not a
scrape, and it is open to consumers.

- **Server:** `https://fints.dkb.de/fints` (new since **2024-11-25**).
- **Auth / 2FA:** since 2024-11-25 DKB requires a **TAN on every login**.
  Supported methods: **pushTAN via the DKB app**, **chipTAN QR / manual**,
  **AppTAN**. The old **TAN2go was discontinued 2024-11-24**.
- **Data:** account balances and transactions (Umsätze), including camt-style
  booked entries. Read scope covers what you need.
- **Python:** `python-fints` (`raphaelm/python-fints`). Works with DKB, but the
  2024 auth change means you must handle the app/chipTAN flow. Community reports
  confirm it works with pushTAN/AppTAN as the selected medium, with a manual
  approval step. Fully unattended runs are not possible: DKB forces a TAN each
  login by design.
- **Verdict:** cleanest DKB route. Structured protocol, official-ish, no DOM
  fragility. Cost: one TAN tap per run, same human-in-the-loop as PostFinance.

## 2. dkb-robo (maintained community library)

`grindsa/dkb-robo` (PyPI: `dkb-robo`) accesses DKB's online-banking area and
returns accounts + transactions.

- DKB launched a new web frontend in **July 2023** backed by a **REST API**.
  dkb-robo migrated to those REST endpoints (started v0.22, completed v0.27) and
  is **actively maintained (through late 2025)**.
- Handles the PSD2 second factor (app approval). Same per-login TAN constraint.
- **This is the drop-in replacement for pybank's dead `download/dkb.py`.** It
  already tracks DKB's current REST backend, so it absorbs the maintenance that
  the retired-UI Selenium scraper cannot.
- Note: it drives the private web/REST interface, not the official PSD2 API (see
  below). Lives in the same personal-use grey area as any scraper.

## 3. PSD2 / XS2A API (not individually accessible)

DKB exposes a PSD2 XS2A interface, but **only to licensed/registered third-party
providers (fintechs)**, not to individuals. Same structural gate as Swiss bLink:
the regulation exists, but consuming the API yourself requires TPP standing. Not
a DIY path.

## 4. CSV / camt export from the web UI (manual baseline)

DKB's web banking exports transactions as **CSV** (and camt for accounts). pybank
already imports the DKB CSV (checking `Girokonto` and credit card `Kreditkarte:`,
including older single payee/payer-column layouts). Zero new code, fully manual
each time. Good fallback / starting point.

## DKB ranking

1. **FinTS via `python-fints`** — real protocol, structured, one TAN per run.
2. **`dkb-robo`** — maintained, tracks the current REST backend, one TAN per run.
   Easiest to adopt if FinTS auth handling proves fiddly.
3. **Manual CSV export + existing importer** — works today, no code, but manual.
4. **PSD2/XS2A** — not open to individuals.
5. Selenium scraping of the old UI — dead (retired UI + Selenium 3 API). Delete.

---

# Overall ranked recommendations

Across both institutions, best to worst by ease + viability:

1. **IBKR Flex Web Service.** *Recommended, highest payoff.* Unattended,
   read-only, structured XML, token up to 1 year. Genuinely set-and-forget. Use
   `ibflex`. Nothing else researched (IBKR, DKB, or PostFinance) matches this.
2. **DKB FinTS via `python-fints`** (or **`dkb-robo`** as the pragmatic
   alternative). Structured/maintained, but one TAN approval per run. Pick
   `dkb-robo` if the FinTS TAN flow is painful, `python-fints` for a cleaner
   protocol dependency.
3. **Manual CSV for DKB** on a reminder. Works now, no code, but manual.
4. **IBKR Client Portal Web API.** Only if you need real-time balances/positions.
   OAuth key-pair setup, more moving parts than Flex.

**Not viable / avoid:** DKB PSD2/XS2A direct (TPP-gated), IBKR TWS API for
reporting (needs a running desktop session), and both existing Selenium scrapers
(obsolete).

---

# Suggested next steps for pybank

1. **IBKR: replace the scraper with a Flex Web Service downloader.** New
   `download/ib_flex.py` (or fold into `download/ib.py`): `SendRequest` +
   `GetStatement` with a stored token + Query ID, via `ibflex`. Then either feed
   the XML to a new parser or keep exporting CSV to reuse `importer/ib.py` first.
   Delete the Selenium scraper once Flex works.
2. **IBKR: prefer an XML importer.** The Flex XML is richer and more stable than
   the CSV. A small `importer/ib_flex.py` over the typed `ibflex` objects would
   be more robust than the current nested-CSV-dict approach. Optional follow-up.
3. **DKB: replace the scraper with `dkb-robo` or `python-fints`.** New
   `download/dkb_fints.py`. Accept the per-login TAN as a manual step in the run.
   Retire `download/dkb.py` (dead UI + Selenium 3).
4. **DKB: keep the CSV importer.** `importer/dkb.py` stays as-is for manual
   exports and as a fallback.
5. **Secrets:** the IBKR Flex token is a long-lived bearer credential. Load from
   env/secret store, never commit, support rotation.

**No scraping or self-heal skill needed for either.** Both have real APIs (IBKR
Flex, DKB FinTS), so the deterministic-Playwright + `/fix-pf-scraper` repair
approach from [postfinance-data-extraction.md](postfinance-data-extraction.md) is
PostFinance-only. IBKR is fully unattended (token). DKB needs one TAN tap per run
but over a stable protocol, not a DOM that drifts.

---

# Sources

## Interactive Brokers
- [Flex Web Service | IBKR API | IBKR Campus](https://www.interactivebrokers.com/campus/ibkr-api-page/flex-web-service/)
- [Configure Flex Web Service | IBKR Guides](https://www.ibkrguides.com/brokerportal/performanceandstatements/flex3.htm)
- [Web API v1.0 Documentation | IBKR Campus](https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/)
- [Web API Documentation (unified) | IBKR Campus](https://www.interactivebrokers.com/campus/ibkr-api-page/webapi-doc/)
- [IBKR API Home | Getting Started](https://www.interactivebrokers.com/campus/ibkr-api-page/getting-started/)
- [ibflex: Python parser for IBKR Flex XML | GitHub](https://github.com/csingley/ibflex)
- [ibflex | PyPI](https://pypi.org/project/ibflex/)

## DKB
- [DKB: new FinTS address, TAN2go shutdown, DKB-App | Buhl FAQ](https://www.buhl.de/shop/faqs?article=2826)
- [DKB: neue Freigabemethoden und Serverwechsel für Finanzsoftware | ifun.de](https://www.ifun.de/dkb-neue-freigabemethoden-und-serverwechsel-fuer-finanzsoftware-243660/)
- [DKB New Authentication Methods (issue #183) | python-fints | GitHub](https://github.com/raphaelm/python-fints/issues/183)
- [python-fints | GitHub](https://github.com/raphaelm/python-fints)
- [dkb-robo | GitHub](https://github.com/grindsa/dkb-robo)
- [dkb-robo | PyPI](https://pypi.org/project/dkb-robo/)
- [FinTS | Wikipedia](https://en.wikipedia.org/wiki/FinTS)
