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
