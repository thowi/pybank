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

## Transfer pairs

A transfer between own accounts arrives as two rows, one per statement. Both
book to `Assets:Transfers:InTransit` (see [accounting.md](accounting.md)).
A row reaches it in one of four ways:

- A `[[transfers]]` hint in the config names its account and text.
- The QIF export categorizes it as a transfer.
- The statement marks it as a conversion between two own currency balances,
  as Wise and Revolut do.
- It is one leg of a pair, confirmed or sure enough to book unasked.

A row that reached the clearing account by the first three ways is a *known
transfer*. A *candidate pair* is two rows on different accounts, each
uncategorized or a known transfer, with opposite amounts within a week, where
neither row fits any other row. Two looser fits need one leg to be a known
transfer, because between two purchases they are mostly chance. In two
currencies the implied rate has to lie near the market rate. In one currency,
two rows that match nothing exactly also pair when the receiver got up to
0.5% less, or up to 10 on a small amount. Booking puts that gap on
`Expenses:Fees:Bank`.

Two unrelated rows can have the same amount, so most candidates book only
once they are confirmed. A candidate books unasked when both legs are known
transfers, or when one is and the amounts match exactly. A rate or a fee fit
with one known leg still asks: The known leg can belong to an account with
no importer. Then its real partner is missing, and a purchase near the
amount takes its place. A pair booked unasked carries `category-source:
"pair-auto"` on the leg it categorized, so a query lists them for review. Two
known legs keep the source that made them known.

```
pybank-import --config pybank.toml confirm main.beancount
```

`confirm` shows each candidate that is not booked yet, has no answer, and
that a rebuild does not book unasked. It asks yes, no or skip. Then, for
each clearing posting that nothing cancels and no candidate settles, it
shows the legs it fits and asks which one is its partner.
Answering none rejects every leg shown, so a later run does not ask again.
It appends each answer to `transfer-pairs.toml` next to the config, keyed by
the import-ids of both legs. The legs are already in the ledger, so an
incremental import skips them as duplicates. A rebuild from the sources books
the confirmed pairs. To undo a pair booked unasked, add its two import-ids
to `transfer-pairs.toml` with `confirmed = false` and rebuild.

A pair in two currencies needs the market rate of its day. `extract` reads
the `price` directives from the file passed with `-e`. In a rebuild, pass a
file that holds the prices and no transactions, since `extract` marks a row
already in that file as a duplicate. Without prices, `extract` leaves such
a pair unbooked, and `confirm` asks about it.

```
pybank-import --config pybank.toml unpaired main.beancount
```

`unpaired` lists the clearing postings that no opposite posting in the same
currency cancels within a week. These keep `InTransit` from zero. Typical
causes: The other account has no importer, the transfer changed currency, or
a fee made the two amounts differ and the pair is not confirmed yet.
