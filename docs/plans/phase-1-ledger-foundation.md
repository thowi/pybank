# Phase 1: Ledger foundation

Hand-written skeleton ledger before any importer exists. Forces the naming and
layout decisions on a tiny surface.

Done. The skeleton passes `bean-check`.

## Scope

1. Add `beancount` dependency.
2. Ledger home: A private Google Drive folder, `Ledger/` next to the existing
   `Statements/`. The path stays local config, never hardcoded or committed.
   It becomes a `--ledger` flag with an environment variable fallback when
   the ingest CLI lands in phase 2. .gitignore guards (`*.beancount`,
   `/ledger/`) keep ledger files out of this public repo.
3. File layout, decided: `main.beancount` includes `accounts.beancount`
   (`open`, `close`, `commodity`), `prices.beancount`, `budgets.beancount`,
   and one file per year. Directives that span years stay out of the year
   files, so a rename or a new budget touches one place.
   Year-boundary `balance` assertions go at the top of the new year's file,
   dated 1 January. Assertions evaluate at the start of their date, so that
   single directive is both the close of the old year and the open of the
   new. Keeping it in the new file preserves one file, one year, which is
   what keeps importer year-routing free of special cases.
4. Chart of accounts for the v1 institutions:
   - PostFinance: Checking and savings under `Assets:PostFinance:*`, credit
     card under `Liabilities:PostFinance:*`. CHF.
   - DKB: Checking under `Assets:DKB:*`, Visa under `Liabilities:DKB:*`. EUR.
   - IBKR: Per-currency cash (`Assets:IBKR:Cash:USD` etc, confirmed by the
     per-currency statement exports), holdings as commodity positions.
5. Base reporting currency: CHF (`operating_currency` option).
6. Category tree as settled in [accounting.md](../accounting.md). Phase 3
   adds the rules that assign transactions to it, not new categories.
7. Seed with a handful of hand-written transactions and Balance assertions to
   validate the shapes (incl. one FX transaction and one IBKR trade with
   `{cost}` and `@ price`).

## Acceptance

- `bean-check` passes on the skeleton ledger.
- Balance sheet and income statement render sensibly in CHF.

## Decided

- Booking method: FIFO everywhere, written on each brokerage `Open` rather
  than left to a file-level default, so the choice is visible where the
  account is. Swiss private capital gains are generally tax-free, so lots
  serve performance reporting, not tax. Equity compensation books the same
  way, which keeps vested and open-market lots of one ticker comparable.
- Prices: `beanprice`, monthly. Year-end prices are needed for wealth tax
  regardless. Monthly is enough to make a performance chart readable without
  turning `prices.beancount` into a data feed.
- Commodities: The ticker is the commodity name. ISIN and the IBKR `conid`
  ride along as `commodity` metadata, so a ticker rename or a dual listing
  stays resolvable.
- FX rounding: Beancount's default tolerance first. Add `Equity:Rounding`
  only if real imports show residuals it does not absorb.
