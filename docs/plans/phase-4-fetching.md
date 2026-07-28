# Phase 4: Automated fetching

Rebuild `pybank-fetch` on modern foundations. Details in the extraction
research docs (`../research/`).

## Scope

1. IBKR Flex Web Service: Real API, no browser. Token is a long-lived bearer
   credential: Env var or secret store, never committed, rotatable.
2. PostFinance: Deterministic Playwright scraper. `storageState` auth JSON is
   a live session, gitignored. Repair skill drives local Playwright when the
   scraper breaks, operates on page structure, never echoes balances.
3. DKB: API if viable, else Playwright.
4. Scheduling: launchd or cron, downloads land next to the statement archive.

## Cleanup

- Delete `download/` (selenium scrapers) and drop `selenium` once each bank's
  replacement reaches parity. Review the old code for login-flow and URL
  knowledge before deleting.

## Acceptance

- One command fetches new statements for all three institutions and runs the
  importers, end to end, without manual downloads.
