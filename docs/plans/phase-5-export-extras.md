# Phase 5: Export and extras

Order-flexible backlog, pick items as needed.

## Export

- OFX 2.x export via `ofxtools` (locked interchange decision).
- Retire `qif.py` and the QIF export for good.

## More institutions

- From the statement archive, roughly by activity: Wise, Revolut, Schwab
  (incl. equity awards), VIAC, crypto exchanges, insurance products.
- Each is just another beangulp importer on the Phase 2 pattern.
- Before starting Revolut or Wise, download fresh exports. The archive holds
  Revolut CSVs only to 2023-10 (PDFs to 2024-10) and Wise CSVs only to
  2021-09. Older data may no longer be available for download.
- Done 2026-11-16: Fresh exports cover both from account opening. Wise
  offers two flavors. Use the one with fees split out: Each fee is its own
  row (ID prefix `FEE-`), and the main row carries the amount the other
  side sees. So a top-up matches the bank leg exactly, and a conversion
  matches its rate. The other flavor folds the fee into the amount in a
  way that differs by transaction type.

### Three of these were already solved once

Wise, Revolut and Schwab had working CSV parsers on the old QIF path, which
phase 2 deleted along with the rest of it. They read the same exports the
new importers will read, so they record which columns each bank ships and
how each one spells amounts, dates and signs. That is the slow part of
writing an importer, and it is worth reading before starting from scratch.

They live in history up to `ae8aa75`, under `src/pybank/importer/`, as
`wise.py`, `revolut.py` and `schwab.py`, alongside `ib.py` for the IBKR
Activity Statement CSVs. Read one with
`git show ae8aa75:src/pybank/importer/wise.py`.

Two warnings. None of them had a single test, so treat the behavior as
undocumented rather than verified. And they emit the old `model.py` objects
and carry no import-id, so the structure ports, not the code.

## Smarter categorization

- Fuzzy merchant matching (rapidfuzz, flofi stage 4).
- AI fallback (flofi stage 5): Batched, cached in a sidecar, NULL-on-failure
  semantics via `Expenses:Uncategorized` + `!`. Adds API dependency and cost,
  hence deferred.
- A model trained on the ledger history moved to phase 3, see
  [Categorization v1](phase-3-backfill-transfers-categorization.md#categorization-v1).

## Maybe, if a need appears

- SQLite read model rebuilt on import, if Fava or bean-query get slow.
- Budgeting via `Custom` directives (Fava's budget convention).
- Downstream push to Firefly III or similar.
- Private git repo for the ledger, if diff-based review becomes wanted.
