# Phase 4: Automated fetching

Rebuild `pybank-fetch` on modern foundations. Details in the extraction
research docs (`../research/`).

## Scope

1. IBKR Flex Web Service: Real API, no browser. Token is a long-lived bearer
   credential: Env var or secret store, never committed, rotatable.
2. PostFinance: Deterministic Playwright scraper. `storageState` auth JSON is
   a live session, gitignored. Repair skill drives local Playwright when the
   scraper breaks, operates on page structure, never echoes balances.
   The CSV export is row-capped, not date-capped. Files in the archive stop
   at exactly 100 rows and a fresh export stops at exactly 200, whatever
   range was asked for, and nothing in the file says it was truncated. So
   fetch in windows small enough to stay under the cap, and treat a
   row count that lands exactly on it as a truncated file, not a full one.
3. DKB: API if viable, else Playwright.
4. Scheduling: launchd or cron, downloads land next to the statement archive.

## Overlap and late bookings

A row can reach the bank after the period it belongs to: A card refund is
booked weeks after the purchase, a booking is backdated. Two exports that
meet edge to edge can miss it. Seen 2026-11: The old card export stopped at
booking date 2025-02-28, the new one started at purchase date 2025-03-01
(hypothesis from the rows, the file names no range). 9 rows bought in
February or earlier and booked in March were in neither file. Only the card
bill PDFs showed them, because card CSVs carry no balance.

- Each fetch downloads a trailing window that overlaps the previous one,
  for example the last 90 days. The importers' dedupe drops the rows already
  in the ledger. Checked 2026-11: Re-downloading a quarter that overlaps two
  card files added exactly the 9 missing rows and doubled none.
- A card check runs after each fetch: The sum of a billing period's CSV rows
  against the bill PDF's total. A mismatch names the period to fetch again.
  Today it is a one-off script outside the repo.

The row cap above needs checking again. A 2026-11 checking export returned
well over 200 rows, and its balances check out.

## Consolidation

Once a year is closed (all its bills issued, past the late-booking window),
replace its small exports with one export for the whole year, so the
archive holds fewer files. Before deleting the small files, check that the
yearly export holds the same row identities. Keep the PDFs, which are the
only source of card balances.

## Cleanup

The `download/` package stays, its implementations get replaced one by one.
`__init__.py` holds parsing and formatting helpers, which carry over, and
selenium element helpers, which go with selenium. `bank.py` holds the
base-class concept, which carries over. Delete each legacy scraper module once its
replacement reaches parity, mining it first for login-flow and URL knowledge.
Drop `selenium` when the last one goes.

## Acceptance

- One command fetches new statements for all three institutions and runs the
  importers, end to end, without manual downloads.
