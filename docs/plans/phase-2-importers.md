# Phase 2: Importers on beangulp

Statement files in, `beancount.core.data` directives out. Reuse the existing
per-bank parsing logic, replace the QIF pipeline. Split by difficulty, each
sub-phase ships independently.

## Libraries

All three sources already have a maintained, MIT-licensed, beangulp-native
importer. Prefer a real dependency. Vendor only where one is not viable.

- **DKB:** Depend on `beancount-dkb` (`ECImporter` and `CreditImporter`,
  documented for beancount 3.x). Read its dependency list when adding it.
- **IBKR:** Depend on `ibflex` from PyPI. A parser library, not an importer,
  so it overlaps nothing we write.
- **PostFinance:** Vendor the importer from `tariochbctools` (~100 lines,
  MIT, keep the license header). It handles the semicolon CSV,
  `windows_1252`, and reads the balance column, so `balance` assertions come
  for free.

PostFinance is the exception for one reason: `tariochbctools` declares
`ibflex @ git+...`, a direct URL reference. That kind of reference wins over
any registry constraint for the same package, so depending on it would drag
our IBKR path onto an unpinned git branch, and a direct URL reference in our
own metadata rules out publishing. It also has no extras, so all fifteen
dependencies (`camelot-py`, `opencv-python-headless`, `imap-tools` and the
rest) are mandatory to get one CSV parser.

Vendoring buys a starting point and the freedom to patch a format variant.
It does not buy maintenance: Nothing flows back in after the copy.

What stays ours regardless: The `import-id` scheme, year-file routing,
categorization rules, and `Assets:Transfers:InTransit` matching.

## Common pattern (established in 2a)

- `beangulp` importer interface: `identify()`, `account()`, `extract()`.
- Each transaction gets the bank leg plus a contra account
  (`Expenses:Uncategorized` with `!` flag until categorized).
- Dedup key in `meta` (`import-id`), dedup against the existing ledger via
  beangulp. See [importing.md](../importing.md). Read beangulp's own
  duplicate detection first: If its comparator covers the similarity
  warning, ours is a hashing function, not a subsystem.
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
