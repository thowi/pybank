# pybank

## Review code changes before committing

Overrides the global auto-commit convention for code changes in this repo.

- Leave code changes **unstaged**. Do not run `git add` on code.
- When a unit of work is ready, stop and prompt for review. Summarize what
  changed and list the files.
- Wait. Review happens hunk by hunk, staging selectively.
- Commit only when asked, and commit only what is already staged. Never run
  `git commit -a` or stage extra files at commit time.

Docs-only changes keep the global flow: Propose a commit, get approval, commit.
