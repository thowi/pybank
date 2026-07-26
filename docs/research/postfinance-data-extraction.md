# PostFinance data extraction: research

Research on ways to extract PostFinance (Switzerland) account and credit card
statements, ideally automated. Scope: private/retail customer, recurring pulls,
read-only. Needed: current (checking) account + credit card transactions.
Date: 2026-07-25. Incorporates findings from a second, independent research
report (see "Cross-check with external research").

## TL;DR

- There is **no public REST API for retail customers** to pull their own
  transactions. PostFinance's technical channels (EBICS, SWIFT, MFT) are
  business-only and priced/contracted for companies.
- Switzerland has no PSD2 mandate, so no free legal right to programmatic
  account access. The Swiss open banking platform (SIX **bLink**) is
  provider-to-provider: you would need to be a licensed/registered TPP with a
  contract and fees. Not realistic for an individual.
- **Read-only does not unlock a DIY long-lived token.** e-finance has one login,
  always 2FA-gated, with a short (~1h) server session. Longer-lived read-only
  consent tokens exist only inside bLink, which you cannot access as an
  individual. See "Does read-only change the auth story?".
- **No single method covers both account types.** bLink / camt cover payment and
  savings accounts only. **Credit cards are not payment accounts**, so they never
  appear in camt or open-banking APIs. Card data is always CSV, PDF, or scraping.
- For a private customer, the realistic automated options are:
  1. **Scheduled manual-format export + import** (CSV or camt.053) from
     e-finance. This is what `pybank` already imports.
  2. **Browser automation / scraping** of e-finance. This is what
     `pybank`'s `download/postfinance.py` already does.
- **Recommendation:** hybrid. Current account via **camt.053** (standardized,
  robust, download from Documents), credit card via **CSV** export or scraping.
  Treat the scraper as fragile. One 2FA tap per run is unavoidable.

## Ranked recommendations (ease of use + viability)

For a personal PostFinance current account + credit card, read-only, recurring,
automated. Best to worst:

1. **Hybrid: camt.053 for the account + CSV for the card.** *Recommended.*
   Viability high, ease medium. Best data quality: camt.053 is structured, stable,
   v8-ready. Card has no camt equivalent, so CSV is its ceiling. Cost: one 2FA tap
   per run, plus building a camt.053 importer (not in pybank yet). The durable
   answer.
2. **Manual CSV for both, on a reminder.** Viability high, ease high to set up but
   low to sustain. Zero new code (pybank imports both already). Fully manual each
   time, and the card CSV has the infinite-scroll trap. Good starting point /
   fallback, but not "automated".
3. **Selenium/Playwright scraper (port the existing one).** Viability medium, ease
   low. `download/postfinance.py` already scrapes both, but needs porting to
   Selenium 4, is DOM-fragile, still needs a 2FA tap, and brushes against ToS.
   Best reserved for the card leg of option 1.
4. **Switch/add a fintech account (Wise, or Revolut).** Viability high for the
   fintech's own data, ease high. Wise has a real personal API token, Revolut
   personal gives clean CSV/PDF with account + card together. pybank integrates
   both. Most automatable path, but it is a *different* account, not PostFinance
   data. Only relevant if willing to move money there.

**Not viable here:** bLink / open-banking APIs (partner-gated), ZKB Dataset /
EBICS / MFTPF / SFTP (business only), consumer PFM aggregators (app holds the
token, adds a third party, no card data), PDF-to-CSV SaaS (uploads your ledger
elsewhere), merchant/checkout SDKs (cannot read your ledger).

**Automated delivery by email?** No. Swiss retail banks deliver statements to a
secure e-banking inbox and send only an email *notification*, never the statement
file as an attachment. No bank emails a scheduled CSV/camt for a personal account
(that exists only on the business channels above). Even providers that email a
monthly statement send a PDF, which puts you back on PDF parsing. Email opens no
shortcut.

**Takeaway:** start at #2 today (works now, no code), build toward #1 (camt.053
importer for the account + reuse CSV/scrape for the card). Read-only buys no
easier token or DIY API.

## Context: what pybank already has

- `src/pybank/download/postfinance.py`: Selenium scraper of e-finance. Logs in
  (password + Mobile ID or challenge token), reads accounts, checking/savings
  transactions, and credit card transactions off the DOM.
- `src/pybank/importer/postfinance.py`: CSV importers for checking
  (`Konto:` header) and credit card (`Kartenkonto:` / `Karte:` header).
- So both retail CSV exports (checking and credit card) are already known-good
  inputs. The scraper covers unattended pulls at the cost of DOM fragility.

## The landscape

### 1. Manual-format export from e-finance (recommended base)

Available to every retail customer, no extra contract.

| Format | Where | Content | Notes |
|---|---|---|---|
| CSV | e-finance, per account, transaction list | Date, memo, debit/credit CHF, category | Already imported by pybank. Simple, but proprietary layout, German headers, no stable schema guarantee. **Infinite-scroll trap:** the Export button only writes the transaction rows currently rendered in the DOM. Scroll / "load more" through the full date range before exporting, or rows are silently dropped. |
| camt.053 (ISO 20022 XML) | e-finance → Documents → Kontoauszüge (account statements) | Periodic statement: balances + booked movements, detailed entries as XML | Standardized, richer, more stable than CSV. **Not yet imported by pybank.** |
| camt.052 / camt.054 | Technical channels mainly | Intraday report / debit-credit notification | Business-oriented. Less relevant for retail. |
| PDF | e-finance → Documents | Human-readable statement | Not machine-friendly. Fallback only. |

camt.053 download path in e-finance: sign in, open the Documents tab, find the
"Kontoauszüge" tile, search, select statements, download. This is a manual UI
flow, but the same flow can be scripted with the existing Selenium session.

**Why camt.053 is attractive:** ISO 20022 is a documented, versioned XML schema.
Parsers exist. Far less likely to break than scraping the transaction DOM or
relying on CSV column names. Good Python options: `sepaxml`/`camt` parsers, or
roll a small `xml.etree` reader over the `Ntry` elements. Consider adding a
`camt053` importer to pybank.

**ISO 2019 (v8) migration — hard deadline 2026-11-14.** The Swiss financial
center is migrating all camt/pain messages from the 2013 version (v4,
`camt.053.001.04`) to the 2019 version (v8, `camt.053.001.08`). Any parser must
support v8 before the deadline or the pipeline breaks. v8 adds, among other
things: gross-interest and withholding-tax data under `<Interest>`, mandatory
account type/category on statement level B, and standardized `<AddtlInf>`
values. **Design the importer for v8 (ideally both v4 and v8) from the start.**
PostFinance offers a self-service ISO version switch in e-finance.

### 2. Business technical channels (not applicable to retail, documented for completeness)

PostFinance "technical business channels":

- **EBICS** (2.5 / 3.0): standard automated exchange. Order types for account
  statements deliver camt.053 (e.g. Z53). Requires a business contract, EBICS
  subscriber setup, and bank-side activation.
- **MFTPF** (Managed File Transfer, SFTP-based): file drops for larger firms.
- **SWIFT** (SCORE / FileAct): MT940/MT942 and ISO camt.053/.054 over SWIFT.
  Enterprise-grade, contracted.

All three: business customers only, with onboarding and fees. Not a fit for a
private customer pulling their own data.

### 3. Open banking: SIX bLink

- bLink is the Swiss open banking platform. Its **Account Information API** lets
  an application aggregate a customer's payment account data (balances,
  transactions). PostFinance participates as a data provider.
- **Consumer angle:** PostFinance offers "Multibanking for private customers",
  which uses bLink to pull *other* banks' accounts *into* the PostFinance
  app/e-finance. This is the reverse direction: it aggregates external accounts
  for viewing inside PostFinance, not a way to extract PostFinance data out to
  your own script.
- **Direct API angle:** consuming the bLink Account Information API yourself
  requires being an onboarded third-party provider (fintech/business) with a
  contract and fees, plus typically regulatory standing. Not offered to
  individuals for personal use.
- Verdict: not a practical path for this use case today. Worth re-checking
  yearly as Swiss open banking evolves.

### 4. Consumer PFM aggregator apps (bLink read-only, but you don't own the pipe)

Personal-finance apps that connect to bLink can obtain a read-only consent token
via an e-banking redirect + 2FA, then aggregate transactions without holding
your password. This is the only way an individual touches a longer-lived
read-only token. Trade-offs that make it a poor fit here:

- **You don't own the token or the export.** The app holds the consent, in its
  cloud. No clean local file for pybank unless the app itself exports.
- **Credit cards excluded.** bLink account information is payment/savings
  accounts only. A card ledger will not appear.
- **PostFinance retail coverage is vendor-specific and unverified.** The second
  report named vendors (a "Finch" PFM, BudgetBakers Wallet) whose specifics and
  even domains could not be verified. Treat as leads, not facts.

### 5. Paid API aggregators (Salt Edge, GoCardless/Nordigen, Plaid)

Direct AIS APIs that may cover PostFinance, but: contract + licensing overhead,
pricing aimed at companies (Salt Edge reportedly ended free personal tiers in
late 2025), and still no credit cards. Not worth it for personal use.

### Not this: merchant / checkout SDKs

A common trap. The `postfinancecheckout` / `pfpayments` Python/PHP SDKs
(`checkout.postfinance.ch`), plus `node-postfinance` and `polybanking`, are
**merchant payment-gateway** tools. They process card charges for shops. They
have **no endpoints to read your checking balance, transaction history, or card
statements.** Ignore them for this use case.

## Credit cards specifically

- PostFinance credit card transactions are shown in e-finance under the Credit
  card tile, one billing period at a time. pybank already scrapes this.
- CSV export exists for cards (pybank imports the `Kartenkonto:` / `Karte:`
  format).
- **No camt.053 for cards, and none via bLink.** camt and open-banking account
  information cover payment/savings accounts. A credit card is not a payment
  account, so no API or standardized file will ever emit card transactions. Card
  data therefore stays on CSV or scraping.
- PDF monthly card statements are available under Documents as a fallback. If
  parsing PDFs, do it locally (`pdfplumber` / `tabula`) with a balance
  reconciliation check, not via an online converter.

## Does read-only change the auth story?

Wanting read-only only (no payment initiation) does not unlock an easier or
longer-lived credential for a DIY script:

- **Scraping / e-finance:** one login, always 2FA-gated (Mobile ID push or
  challenge token). There is no separate read-only token. Server session times
  out at ~1h.
- **bLink:** read-only *does* map to a longer-lived consent token (consent-based
  access, periodic re-auth). But minting one requires licensed-partner status.
  As an individual you can only get it indirectly, through a consumer app that
  holds it (see landscape §4).

Net: read-only is the right, safer scope to ask for, but it buys no automation
convenience for a self-built tool. The auth cost stays "one 2FA tap per run".

## Recommendation for recurring automation

Two-tier approach:

1. **Primary: script the export you can get without a contract.**
   - Checking/savings: fetch **camt.053** from the Documents tab on a schedule,
     parse XML. Most robust. Add a camt.053 importer to pybank.
   - Credit cards: **CSV** export (or keep scraping the card tile), since no
     camt exists.
2. **Automation mechanism: reuse the existing Selenium session.** Login needs
   2FA (Mobile ID confirmation or challenge token), so full unattended login is
   inherently limited by design. Options:
   - Semi-automated: script runs, you approve the Mobile ID push once, script
     then downloads camt.053 + card CSV and imports. Practical for a
     weekly/monthly cron with a human tap.
   - Session-cookie reuse (pybank already saves/restores cookies) shortens the
     window but PostFinance session timeout (~1h) still forces periodic 2FA.

### Practical notes / gotchas

- **2FA is unavoidable.** No retail path bypasses Mobile ID / challenge. Plan
  the schedule around one manual confirmation per run.
- **Scraper fragility.** `download/postfinance.py` uses Selenium's old
  `find_element_by_*` API (removed in Selenium 4). It will need porting to
  `find_element(By...)` before it runs on current Selenium. Track separately.
- **Prefer camt.053 to reduce breakage.** Moving checking/savings off DOM
  scraping and onto the camt.053 file download is the single biggest
  robustness win available without a business contract.
- **Session persistence is short-lived.** Saving browser state (Playwright
  `storageState`, or pybank's cookie save/restore) lets a subsequent *headless*
  run skip the login form, but only within the ~1h server session. It does not
  survive to the next day. Do not expect unattended daily runs without 2FA.
- **Don't upload statements to third-party PDF-to-CSV SaaS.** For credit card
  PDFs, several online "converter" services exist, but uploading a full card
  ledger to an unknown processor is a needless data-privacy exposure. Parse
  locally with `pdfplumber` or `tabula` instead. Add a balance-reconciliation
  check (opening balance + sum of rows == closing balance) to catch dropped
  rows.
- **Terms of service.** Automating login/scraping of e-finance may run against
  PostFinance's terms. Personal, low-frequency use of your own data is the
  usual grey area. Worth a glance at the e-finance terms.

## Scraping the card tile: tooling and self-heal (decided direction)

Decided approach for the one surface with no API: the credit-card tile. The
current account avoids scraping entirely via camt.053, so the scraped surface is
small and contained. Existing `download/postfinance.py` (Selenium 3) is retired
in favor of this.

**Runtime: deterministic Playwright (Python), no LLM in the loop.**

- Import Playwright as a library into pybank's fetch pipeline. Matches the
  existing Python codebase.
- Session reuse via `storageState`: log in once with the 2FA tap, save the
  auth-state JSON, reuse within the ~1h PF session. Gitignore it (live session).
- No stealth / anti-detection plugins. You are a legitimate logged-in user on
  your own account. Stealth adds nothing here and leans toward the ToS grey area.
- Keep the LLM out of every run: no per-run token cost, no bank pages sent to a
  model, deterministic behavior.

**Design the scraper to be repairable.** A self-heal skill is only as good as the
seams the scraper exposes:

- **Centralize selectors** in one module/config. Patches touch one file, not
  scattered CSS strings.
- **Fail structured, not generic.** On breakage, raise an exception carrying the
  step, the selector, a screenshot, and a DOM dump.
- **Snapshot the DOM** on success (golden fixture) and on failure (broken
  sample). The old-vs-new diff is the repair skill's key input.
- **Read-only verify command** (`fetch --dry-run --reconcile`) that logs in,
  scrapes, checks balance reconciliation (opening + sum of rows == closing), and
  exits nonzero on mismatch. Idempotent, safe to loop.

**Repair-time skill (e.g. `/fix-pf-scraper`), invoked on break:**

1. Reproduce the failing step, capture the current DOM.
2. Diff against the last golden snapshot.
3. Patch the selector module minimally.
4. Verify by re-running the read-only reconcile command.
5. Hand off a diff for approval + commit. No auto-merge into the scheduled job.

**The repair skill drives Playwright directly, not a separate browser tool.**
Rationale: the fixer should inspect the exact stack the scraper is backed by, so
the DOM it sees is the DOM the scraper sees. One browser stack, no drift between
"what the fixer sees" and "what the runtime uses". An AI-agent browser (Vercel
`agent-browser`, Stagehand) could assist during initial authoring, but is not
needed for repair and is deliberately kept out of the loop.

**Trigger: human-in-the-loop.** Reaching the PF page needs a 2FA tap, so a human
is present at repair time by necessity. Job fails, you get pinged, you run the
skill and tap 2FA, the skill drives from there. Fully autonomous self-heal on a
bank is neither possible (2FA) nor the right risk posture.

**Guardrails.**

- **Local only:** drive local Chrome, never a cloud browser backend. Session and
  balances stay on your machine.
- **Structure, not values:** the fix concerns selectors/flow, not transaction
  amounts. Don't echo balances into a PR.
- **Approval gate:** diff, review, commit. The skill never pushes or edits the
  live scheduled job directly.
- **Scope small:** target only the card tile. No generic scraping framework.

## Suggested next steps for pybank

1. Add a `camt.053` importer (`importer/postfinance_camt.py`) parsing ISO 20022
   `Ntry` entries. Highest robustness payoff. Removes the account from scraping.
2. New `download/postfinance_camt.py`: navigate Documents → Kontoauszüge and
   download camt.053 files. No DOM parsing, just the file download.
3. Rewrite credit-card scraping on **deterministic Playwright** (retire the
   Selenium 3 `download/postfinance.py`), built with the repairability seams
   above: centralized selectors, structured failures, DOM snapshots, a read-only
   reconcile command.
4. Add the `/fix-pf-scraper` repair skill (via `skill-creator`) once those seams
   exist. It drives Playwright directly and gates fixes behind review + commit.

## Other Swiss banks and accounts: is anything more accessible?

The barrier is **structural, not PostFinance-specific**: no PSD2 in Switzerland +
bLink gated to licensed partners. So **no traditional Swiss retail bank offers an
individual a self-service programmatic API.** What differs between banks is only
export ergonomics (manual download vs self-service scheduled file delivery) and
whether a modern/fintech account exposes a real API.

### Traditional Swiss banks

| Bank | Self-service export for individuals | Automation-friendly? | Notes |
|---|---|---|---|
| PostFinance | CSV per account, camt.053 in Documents, PDF | Manual per period; scriptable via scraper | Baseline (this doc). |
| **ZKB** | CSV / camt.053 in e-banking; **"ZKB Dataset"** self-service scheduled CSV/XML delivery with SFTP push *or* pull, retroactive 24 months, **free** | **Yes, best-in-class — but business only** | ZKB Dataset requires being a **legal entity**. For a *private* ZKB customer it reverts to manual CSV/camt, no better than PostFinance. **No credit cards.** If you had a company/sole-proprietorship, ZKB Dataset via SFTP-pull is the cleanest no-scraping option found. |
| Other cantonal / retail banks (UBS, Raiffeisen, Migros Bank, …) | CSV + camt.053 typical | Manual; scriptable via scraping | Same PSD2/bLink barrier. Business channels (EBICS/bLink) contracted. |

**Takeaway for a private customer:** among traditional banks, none is materially
easier than PostFinance. ZKB only pulls ahead with a **business** relationship.

### Neobanks / fintechs (genuinely more accessible for individuals)

Modern app-first providers are the real win if the goal is low-friction personal
data. pybank already integrates several.

| Provider | Personal data access | Notes |
|---|---|---|
| **Wise** | Real **personal API token**; balance-statement endpoint region-limited, but usable | pybank already imports Wise. API beats any Swiss retail bank for automation. |
| **Revolut** | Personal: CSV / PDF export. Real API is **Business-only** | pybank already imports Revolut CSV. Covers card + account in one export. |
| **Neon** (CH, via Hypothekarbank Lenzburg) | In-app **CSV export** (no public API) | Swiss-resident only. Clean CSV. |
| **Yuh** (CH, Swissquote) | In-app export | Swiss-resident only. |
| Swissquote | PSD2 open-banking API exists (EU/LU entity), for **licensed TPPs**, not self-service | Not an individual path. |

**Takeaway:** if you want the least-effort *automated* personal feed, a fintech
account (Wise/Revolut, or Neon/Yuh for a Swiss IBAN) is more accessible than any
traditional Swiss bank. Notably these are where a card ledger and account ledger
come together in one export — traditional banks never expose cards via API/camt.

## Cross-check with external research

A second, independent research report was compared against this doc. Points of
agreement: no retail REST API, business-only technical channels, bLink needs
licensed-partner status, hybrid browser automation is the realistic DIY route,
camt.053 for accounts and PDF/CSV for cards.

Valuable additions taken from it (folded in above):

- **ISO 2019 (v8) camt migration deadline 2026-11-14.** Build the importer for
  `camt.053.001.08`.
- **Merchant-SDK trap.** `postfinancecheckout` / `pfpayments` and friends cannot
  read account ledgers.
- **CSV infinite-scroll trap.** Export only writes DOM-rendered rows.
- **Consumer PFM aggregators** as the only individual-accessible read-only-token
  route (with its limits: no card data, cloud-held token, unverified coverage).

Claims from that report treated with caution:

- Named vendors (a "Finch" PFM, BudgetBakers, and several PDF-to-CSV converter
  sites) are unverified, and some cited domains look auto-generated. Leads only.
- It frames Playwright `storageState` session reuse as near-unattended. In
  practice the ~1h PostFinance session means 2FA recurs; not a daily set-and-
  forget.
- Uploading statements to third-party PDF converters is a privacy exposure we
  recommend against; prefer local parsing.

## Sources

- [Technical business channels | PostFinance](https://www.postfinance.ch/en/business/products/payment-transactions/e-banking-apps-channels/technical-business-channels.html)
- [Multibanking for private customers | PostFinance](https://www.postfinance.ch/en/private/paying-saving/e-banking-apps/multibanking-private-customers.html)
- [PostFinance launches multibanking for private customers | PostFinance](https://www.postfinance.ch/en/about-us/media/newsroom/postfinance-launches-multibanking-for-private-customers.html)
- [Account Information – bLink | SIX](https://blink.six-group.com/en/services/account-information)
- [bLink – The Swiss Open Banking Platform | SIX](https://blink.six-group.com/en)
- [SCORE for business customers | PostFinance](https://www.postfinance.ch/en/business/products/liquidity/manage-liquidity/score.html)
- [PostFinance camt.053 exportieren und importieren](https://invoicedataextraction.com/blog/postfinance-kontoauszug-camt053-importieren)
- [Anleitung zum Download der E-Banking camt.053-Datei | clickbook](https://www.clickbook.ch/blog/download_e_banking_camt053_datei)
- [Postfinance camt.053 import | Banana Accounting](https://www.banana.ch/apps/en/node/9685)
- [finance-dl (scraping tools reference) | GitHub](https://github.com/jbms/finance-dl)
- [EBICS specification | SIX](https://www.six-group.com/dam/download/banking-services/interbank-clearing/en/standardization/ebics/ebics.pdf)
- [ISO 20022: new ISO version for pain/camt messages | PostFinance](https://www.postfinance.ch/en/business/knowledge/news/iso-20022-new-iso-version-pain-camt-messages.html)
- [Self-service ISO version change for camt messages in e-finance | PostFinance](https://www.postfinance.ch/en/business/knowledge/news/iso-version-change.html)
- [ZKB Dataset (Datenbezug via ZKB Dataset) | ZKB](https://www.zkb.ch/de/unternehmen/digitales-banking/software-anbindungen/datenbezug-via-zkb-dataset.html)
- [ZKB API Developer Portal | ZKB](https://www.zkb.ch/de/lps/unternehmen/digitales-banking/api-developer-portal.html)
- [Neobanks in Switzerland: comparison | moneyland.ch](https://www.moneyland.ch/en/neobanks-switzerland-comparison)
- [Revolut Business API | Revolut Developer](https://developer.revolut.com/docs/business/business-api)
- [Wise personal API token | Wise](https://docs.wise.com/guides/developer/auth-and-security/personal-api-token)
