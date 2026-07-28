# Phase 1: Ledger foundation

Hand-written skeleton ledger before any importer exists. Forces the naming and
layout decisions on a tiny surface.

## Scope

1. Add `beancount` dependency.
2. Ledger home: A private Google Drive folder. Path is local config (env var or
   config file), never hardcoded or committed. Add .gitignore guards
   (`*.beancount`, `ledger/`) so ledger files cannot land in this public repo.
3. File layout: Propose `main.beancount` including `accounts.beancount`
   (Open/Commodity directives) and per-year transaction files. Finalize here.
4. Chart of accounts for the v1 institutions:
   - PostFinance: Checking and savings under `Assets:PostFinance:*`, credit
     card under `Liabilities:PostFinance:*`. CHF.
   - DKB: Checking under `Assets:DKB:*`, Visa under `Liabilities:DKB:*`. EUR.
   - IBKR: Per-currency cash (`Assets:IBKR:Cash:USD` etc, confirmed by the
     per-currency statement exports), holdings as commodity positions.
5. Base reporting currency: CHF (`operating_currency` option).
6. Initial category tree: Coarse `Expenses:*` / `Income:*`, informed by the
   flofi categories. Refined in Phase 3.
7. Seed with a handful of hand-written transactions and Balance assertions to
   validate the shapes (incl. one FX transaction and one IBKR trade with
   `{cost}` and `@ price`).

## Acceptance

- `bean-check` passes on the skeleton ledger.
- Fava browses it: Balance sheet and income statement render sensibly in CHF.

## Open within this phase

- Booking method per brokerage `Open` (FIFO vs AVERAGE vs STRICT). Default
  FIFO unless a reason emerges. Swiss private capital gains are generally
  tax-free, so lots matter for performance reporting, not tax.
