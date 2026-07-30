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

The `download/` package stays, its implementations get replaced one by one.
`__init__.py` holds selenium-free helpers, `bank.py` holds the base-class
concept, both carry over. Delete each legacy scraper module once its
replacement reaches parity, mining it first for login-flow and URL knowledge.
Drop `selenium` when the last one goes.

## Acceptance

- One command fetches new statements for all three institutions and runs the
  importers, end to end, without manual downloads.
