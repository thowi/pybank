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

## The code is generic. One archive is not the spec

pybank is for anyone banking with these institutions, not for one ledger.
Code, docstrings, comments and the README describe the file format and what
the importer does with it. They never describe one person's export.

The test for a sentence: Would it still hold for a different user, with a
different file, next year? "QIF carries no balance rows" holds, it is a fact
about the format. "The export covers every account from 2008 on" does not, it
is a fact about one file that happens to be on this machine.

- Counts, date ranges, and "a few of these are broken" are observations of
  one archive. They belong in `docs/plans/`, which is the record of this
  migration, or in a commit message, which records why a change was made.
  Keep them out of code.
- Handle a quirk generically. Branch on what the format permits, and let the
  comment say what the branch is for, never how often it fired here.
- Configuration carries the personal part. An importer takes its accounts,
  categories and currencies from the caller, so the ledger holds them and the
  repo holds none of them. Never hardcode a default that fits one user only.
- Naming an institution is fine, it is what the importer supports. Naming
  one user's account, category, or archive layout is not.

## Separate business logic from presentation

Another front end, such as a web page, must reuse every rule, not copy it.

- Logic decides and computes. It returns records, numbers and dates, never
  formatted text.
- Presentation, such as the CLI, only reads input, formats, and asks.
- Example: `transfer_review` picks the pairs to ask about and saves the
  answers. `ingest.py` draws them and asks.

## Review code changes before committing

Overrides the global auto-commit convention for code changes in this repo.

- Leave code changes **unstaged**. Do not run `git add` on code.
- A unit of work larger than about 50 lines of code (tests included) goes
  through `/ship-change` before it is ready. Run it before the review prompt,
  and put its report in that prompt.
- When a unit of work is ready, stop and prompt for review. Summarize what
  changed and list the files.
- Wait. Review happens hunk by hunk, staging selectively.
- Wait means stop building, not just stop committing. Do not start work that
  touches a file with unreviewed changes.
- When told to work ahead unattended, keep each task's changes in a disjoint
  file set, and report the batches and a review order at the end. A pile of
  unreviewed work spanning shared files cannot be reviewed hunk by hunk,
  which defeats the point.
- Commit only when asked, and commit only what is already staged. Never run
  `git commit -a` or stage extra files at commit time.

Docs-only changes keep the global flow: Propose a commit, get approval, commit.
