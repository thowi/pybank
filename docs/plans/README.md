# Implementation plan

Staged plan for rebuilding pybank on the Beancount data model.
Decisions and rationale: [transaction-storage-format.md](../research/transaction-storage-format.md).

| Phase | Theme | Outcome |
|---|---|---|
| [0](phase-0-modernization.md) | Repo modernization | Clean pyproject, ruff, pending docs committed |
| [1](phase-1-ledger-foundation.md) | Ledger foundation | Browsable skeleton ledger, account taxonomy settled in [accounting.md](../accounting.md) |
| [2](phase-2-importers.md) | Importers on beangulp | PostFinance, DKB, IBKR statements flow into the ledger |
| [3](phase-3-backfill-transfers-categorization.md) | Backfill, transfers, categorization v1 | Complete history, rules-based categories |
| [4](phase-4-fetching.md) | Automated fetching | Playwright PF scraper, IBKR Flex, DKB |
| [5](phase-5-export-extras.md) | Export and extras | OFX export, more institutions, smarter categorization |

## Principles

- Each phase ends in a usable state.
- Risky unknowns (IBKR complexity, old-DKB parseability, PF scraping) sit in
  their own phase and can slip without blocking the rest.
- Sequencing can change between phases. Phase 5 items are order-flexible.
- The ledger holds real financial data and lives outside this public repo,
  alongside the chart of accounts naming its real institutions and people.
  [accounting.md](../accounting.md) carries the rules and uses placeholders.
  See [CLAUDE.md](../../CLAUDE.md) for what must never be committed.
