# Importing

How source files become ledger directives. A permanent reference, not a
plan. The build order lives in [plans](plans/), the account taxonomy and
booking rules in [accounting.md](accounting.md).

## Import identity

Every imported transaction carries an `import-id`. It answers one question:
has this source line been seen before.

```
2026-05-04 * "Supermarket" "Groceries"
  import-id: "v1:8f3a2c9d:0"
  Assets:PostFinance:Checking       -85.00 CHF
  Expenses:Living:Groceries          85.00 CHF
```

Three parts: a version, a hash of a fixed set of normalized source fields,
and an occurrence index.

The key describes the **source row**, never the booked transaction. So
recategorizing, splitting a posting or renaming an account leaves it
untouched. This is what lets history stay editable while importers keep
running against it.

The version exists because the normalization will improve. New imports
write the current version, matching checks every version. Without it, one
change to `normalize_text()` strands every key already written.

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
