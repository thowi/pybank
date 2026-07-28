# Phase 3: Backfill, transfers, categorization v1

Turn the working importers into a complete, categorized history.

## Backfill

- Run importers over the statement archive in Drive: PostFinance to 2018,
  IBKR to 2016, DKB back to 2008 if the old formats still parse.
- Where old formats do not parse: Cutoff date plus opening balances via
  `Equity:Opening-Balances`, do not chase every format variant.
- Balance assertions per statement validate the whole chain.

## Transfers

- Route both legs through an `Assets:Transfers:InTransit` clearing account.
  Simpler for importers than merging legs, and self-reconciling: A nonzero
  clearing balance means an unmatched transfer.
- Detection key for matching: Amount, date window, counter-account hints.

## Categorization v1

- Rules-based only, modeled on the flofi cascade stages 1 to 3: Exclusions
  are structural (both transfer legs under `Assets:*`), then a rules file
  (contains / startswith / exact / regex on a normalized description).
- Provenance in `meta` (`category-source: "rule"`), manual confirmations
  flagged `*`, never overwritten by re-runs. Unmatched stays
  `Expenses:Uncategorized` with `!`.
- No fuzzy matching, no AI fallback yet (Phase 5).

## Acceptance

- Full history loads with `bean-check` green.
- Clearing account balances to zero across the backfilled range.
- Income statement by category renders in Fava and looks plausible.
