# Importing

How source files become ledger directives. A permanent reference, not a
plan. The build order lives in [plans](plans/), the account taxonomy and
booking rules in [accounting.md](accounting.md).

## Import identity

Every imported transaction carries an `import-id`. It answers one question:
has this source line been seen before.

```
2026-05-04 * "Supermarket" "Groceries"
  import-id: "v1:2026-05-04:-85:8f3a2c9d1e2b:0"
  Assets:PostFinance:Checking       -85.00 CHF
  Expenses:Living:Groceries          85.00 CHF
```

Five parts: a version, the date, the amount, a hash of the remaining
normalized source fields, and an occurrence index.

Date and amount are in the clear so a key can be read without re-running
the import, and so a collision needs all three parts to match rather than
the hash alone. Both are already visible in the postings, so nothing new is
exposed. The account or card number is not, and stays hashed. The amount is
canonicalized before use, which is why `-85.00` appears as `-85`.

The key describes the **source row**, never the booked transaction. So
recategorizing, splitting a posting or renaming an account leaves it
untouched. This is what lets history stay editable while importers keep
running against it.

The version marks which normalization wrote the key. It is a label, not a
matching rule. Matching is an exact compare, and changing `normalize_text()`
changes every digest, so keys already written stop matching either way.

The label is what makes that survivable. Old keys stay `v1`, new ones are
`v2`, the generations cannot collide, and either can be selected. Usually
the migration is to leave history alone and not re-import files already
imported under `v1`. To re-import history instead, run both normalizations
over the source archive to build a `v1` to `v2` map, then rewrite the keys.

The source identifier and the memo go into the digest as the export writes
them, after `normalize_text()`. A bank that changes the shape of either
between export formats gives the same row a new import-id. Dedupe then
misses it. An import against an existing ledger warns on the near miss,
and a rebuild from scratch imports both copies without a warning.

The occurrence index exists because two identical rows on one day are
legitimate. Two coffees, same shop, same price. Without it the second is
silently dropped.

Bank identifiers go in the same field, with their own prefix, where a
source provides one that is stable across re-downloads. IBKR Flex does.
Most bank CSVs do not. Upgrading a source changes what is written, not
where, so nothing migrates.

A similarity check runs alongside, on amount and a date window. It only
warns. A re-issued statement with an enriched description hashes
differently and the key cannot see it, but a gate here would need a human
and unattended fetching has to keep working.

Both failure directions are silent. A duplicate inflates every total it
touches. A dropped row leaves a gap. Only the second is caught, by the next
balance assertion, so duplicates are the direction worth the warning.
