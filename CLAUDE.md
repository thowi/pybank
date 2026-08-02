# pybank

## This repo is public. Never commit personal or financial data

`github.com/thowi/pybank` is a public repo. Anything committed is
world-readable, and git history keeps it after deletion. Treat a leak as
unfixable without a history rewrite.

Never commit, in code, tests, fixtures, docs, comments, or commit messages:

- Names of people: Account holders, family, payees, contacts.
- Account identifiers: IBANs, account and card numbers, card suffixes,
  customer and login IDs, Flex query IDs.
- Credentials: Passwords, API tokens, cookies, Playwright `storageState`.
- Amounts and balances: Real transaction values, real net worth.
- Real payees, merchants, employers, schools, insurers, landlords.
- Addresses, phone numbers, email addresses, birthdates.
- Statement and export files: PDF, CSV, QIF, OFX, the ledger itself.

Fine to commit: Institution names as supported-source identifiers
(PostFinance, DKB, IBKR are the product), file format structure, field names,
category and account names in the taxonomy.

### Working rules

- Real statements and exports are read-only inputs. Read them in place, never
  copy them into the repo or the working tree.
- Test fixtures are synthetic: Invent every value. Do not redact a real file,
  redaction misses things.
- Docs describe shapes and rules, not values. Category labels and counts are
  fine, sample rows from real data are not.
- Untracked files holding real data stay untracked. Never `git add -A`,
  `git add .`, or `git commit -a`.
- Read the full diff before every commit and check it against this list.
- Chat and scratchpad may hold real data. Neither is a staging area for the
  repo, do not carry values across.

## Review code changes before committing

Overrides the global auto-commit convention for code changes in this repo.

- Leave code changes **unstaged**. Do not run `git add` on code.
- When a unit of work is ready, stop and prompt for review. Summarize what
  changed and list the files.
- Wait. Review happens hunk by hunk, staging selectively.
- Commit only when asked, and commit only what is already staged. Never run
  `git commit -a` or stage extra files at commit time.

Docs-only changes keep the global flow: Propose a commit, get approval, commit.
