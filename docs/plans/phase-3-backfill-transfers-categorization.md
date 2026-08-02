# Phase 3: Backfill, transfers, categorization v1

Turn the working importers into a complete, categorized history.

## Backfill

- Run importers over the statement archive in Drive: PostFinance to 2018,
  IBKR to 2016, DKB back to 2008 if the old formats still parse.
- Where old formats do not parse: Cutoff date plus opening balances via
  `Equity:Opening-Balances`, do not chase every format variant.
- Balance assertions per statement validate the whole chain.

### Pre-2018, from the SEE Finance QIF export

A one-shot importer, not part of the recurring set. It is the only source
for the oldest years, and the only source anywhere carrying hand-curated
categories. Those labels seed every later categorization approach, the rules
below and anything smarter in Phase 5, so they are worth more than the years
they cover.

- The deliverable is the old-to-new category mapping, not just a parser. The
  export carries the old taxonomy.
- The export has no balances and no currency, so no `balance` assertion is
  derivable for this range and CHF is assumed. The first trustworthy
  assertion sits at the handover date, anchored by `Equity:Opening-Balances`.
  Whatever the old era gets wrong stops there.

## Transfers

- Route both legs through an `Assets:Transfers:InTransit` clearing account.
  Simpler for importers than merging legs, and self-reconciling: A nonzero
  clearing balance means an unmatched transfer.
- Detection key for matching: Amount, date window, counter-account hints.

## Categorization v1

- Rules-based only, modeled on the flofi cascade stages 1 to 3: Exclusions
  are structural (both transfer legs under `Assets:*`), then a rules file
  (contains / startswith / exact / regex on a normalized description).
- The rules file lives with the ledger, never in this repo. It maps real
  merchants and payees to categories, which [CLAUDE.md](../../CLAUDE.md)
  forbids committing. Doubly so once it is derived from QIF history instead
  of hand-written.
- Provenance in `meta` (`category-source`): `"rule"` for a rules-file match,
  `"qif"` for a hand-curated label carried in from the old export. Manual
  confirmations flagged `*`, never overwritten by re-runs. Unmatched stays
  `Expenses:Uncategorized` with `!`. Keeping `qif` distinct is what lets a
  query separate what was actually labelled from what was guessed.
- No fuzzy matching, no AI fallback yet (Phase 5).

## Acceptance

- Full history loads with `bean-check` green.
- Clearing account balances to zero across the backfilled range.
- Income statement by category renders in Fava and looks plausible.
