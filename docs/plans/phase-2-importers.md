# Phase 2: Importers on beangulp

Statement files in, `beancount.core.data` directives out. Reuse the existing
per-bank parsing logic, replace the QIF pipeline. Split by difficulty, each
sub-phase ships independently.

## Common pattern (established in 2a)

- `beangulp` importer interface: `identify()`, `account()`, `extract()`.
- Each transaction gets the bank leg plus a contra account
  (`Expenses:Uncategorized` with `!` flag until categorized).
- Dedup key in `meta` (`import-id`), dedup against the existing ledger via
  beangulp. See [importing.md](../importing.md).
- `Balance` assertion from the statement balance.
- Writes to the ledger are plain file writes, no special atomicity needed
  (Drive self-heals once a write completes, version history covers crashes).

## 2a: PostFinance

- Checking and credit card CSV importers, ported from
  `importer/postfinance.py`.
- Establishes the common pattern above.

## 2b: DKB

- Checking and Visa CSV importers, ported from `importer/dkb.py`. Adds EUR.
- Proves the abstraction on a second institution.

## 2c: IBKR

- The hard one: Multi-currency cash, trades with `{cost}` and `@ price`,
  dividends, withholding tax, fees, FX conversions.
- Retires the investment-event class hierarchy: Events become posting shapes.
- Rounding legs from FX may need tolerance or an `Equity:Rounding` account.

## End of phase

- Retire `model.py` and the QIF writer path in `convert.py`, drop `pydantic`.
- `tests/test_qif.py` replaced by importer tests with fixture files
  (sanitized: Fake account numbers, payees, amounts).

## Acceptance

- Each importer: Fixture statement in, expected directives out, `bean-check`
  passes on the result, re-running is idempotent (dedup works).
