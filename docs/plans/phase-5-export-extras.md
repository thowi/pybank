# Phase 5: Export and extras

Order-flexible backlog, pick items as needed.

## Export

- OFX 2.x export via `ofxtools` (locked interchange decision).
- Retire `qif.py` and the QIF export for good.

## More institutions

- From the statement archive, roughly by activity: Wise, Revolut, Schwab
  (incl. equity awards), VIAC, crypto exchanges, insurance products.
- Each is just another beangulp importer on the Phase 2 pattern.

## Smarter categorization

- Fuzzy merchant matching (rapidfuzz, flofi stage 4).
- AI fallback (flofi stage 5): Batched, cached in a sidecar, NULL-on-failure
  semantics via `Expenses:Uncategorized` + `!`. Adds API dependency and cost,
  hence deferred.
- Or evaluate `smart_importer` (ML on ledger history) as an alternative.

## Maybe, if a need appears

- SQLite read model rebuilt on import, if Fava or bean-query get slow.
- Budgeting via `Custom` directives (Fava's budget convention).
- Downstream push to Firefly III or similar.
- Private git repo for the ledger, if diff-based review becomes wanted.
