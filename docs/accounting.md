# Accounting

The account taxonomy and the booking rules that go with it. A permanent
reference, not a plan. Changes when the rules change, not when a phase ends.

Names are English throughout, matching the Assets and Income side. German
source terms are noted in parentheses where the mapping is not obvious.

This is the shape, not the instance. The supported sources (PostFinance,
DKB, IBKR) are the product and appear by name. Everything else is a
placeholder: `<Bank>`, `<Broker>`, `<Person>` stand for real names, written
without brackets inside code examples. What they resolve to is private and
lives with the ledger, not in this repo.

## Principles

- **Budget at the group, not the leaf.** Mid-level nodes (`Living`,
`Leisure`, `Shopping`, `Mobility`) exist so a budget can be set per group
via `root(account, 2)`, or per leaf where that is more useful.
- **Living has a floor, Leisure goes to zero.** Living spend continues at
some baseline whatever is decided, so it budgets as a monthly rate.
Leisure is attached to an activity and stops with it, so it budgets as an
annual envelope. This is why routine `Living:Meals` and occasional
`Leisure:Dining` are apart: same food, different decision.
- **Group by decision shape, not by theme.** A `Media` or `Entertainment`
group would gather Serafe, streaming and cinema, which are decided in
three different ways and so need three different budgets. Totals that cut
across the tree come from summing, not from restructuring.
- **The tree carries the actionable/fixed split.** No parallel beancount
metadata.
- **Budgets are plans, not facts.** Amounts live in dated
`custom "budget"` directives, not in `open` metadata.
- **Err finer.** Merging two categories later is a find and replace.
Splitting one means re-deciding every historical transaction.
- **A parent can hold postings and have children.** So a category can be
split going forward only, leaving history on the parent. No migration.
- **No cross-cutting tags.** Totals like "kid spend" come from summing
categories. Tagging every transaction is more bookkeeping than the answer
is worth, and it is imprecise on mixed receipts anyway.
- **Every account needs a source.** If no statement, export or certificate
can ever fill an account, it does not exist. This is why there is no
`Insurance:Social`, no payroll tax account, and no `Taxes:Wealth`: those
numbers live on payslips and assessments, not in any importable feed.
- **History can be edited, assertions keep it honest.** Fixing a past
mistake is fine and expected. A `balance` assertion at each period
boundary is what makes it safe: if an edit is wrong, the next assertion
fails. Importers are the exception. They may add transactions, never
rewrite existing ones.

## Expenses, actionable

Short-term controllable. Budgets and warnings live here.

| Account                               | Notes                                                            |
| ------------------------------------- | ---------------------------------------------------------------- |
| `Expenses:Living:Meals`               | Routine refuelling. Work lunches, coffee, takeaway               |
| `Expenses:Living:Groceries`           | With Meals, this is routine food spend                           |
| `Expenses:Living:Education`           | Courses, adult education. Kids' school is `Kids:School`          |
| `Expenses:Living:PersonalCare`        | Styling und Wellness                                             |
| `Expenses:Living:Health`              | Gesundheit. Out of pocket only, see `Insurance:Health`           |
| `Expenses:Living:Health:Acupuncture`  | Akupunktur                                                       |
| `Expenses:Living:Health:Dentist`      |                                                                  |
| `Expenses:Living:Health:Physio`       |                                                                  |
| `Expenses:Leisure:Culture`            | Kultur, Unterhaltung                                             |
| `Expenses:Leisure:Dining`             | The occasion, not the routine. Food or drink, any time of day    |
| `Expenses:Leisure:Travel`             | Everything on a trip, meals included, so trip cost is one number |
| `Expenses:Leisure:Travel:Flights`     | Lumpy enough to watch on its own                                 |
| `Expenses:Leisure:Sport`              |                                                                  |
| `Expenses:Leisure:Sport:Horse`        | Pferd                                                            |
| `Expenses:Leisure:Sport:Ski`          |                                                                  |
| `Expenses:Shopping:Clothing`          |                                                                  |
| `Expenses:Shopping:Clothing:<Person>` | One leaf per wearer. Kid clothes stay here, not under `Kids`     |
| `Expenses:Shopping:Electronics`       |                                                                  |
| `Expenses:Shopping:Home`              | Durable goods. Consumables go to `Living`                        |
| `Expenses:Kids`                       | Anything that is not childcare or school. No `Other` child       |
| `Expenses:Kids:Childcare`             | Kita, babysitters                                                |
| `Expenses:Kids:School`                |                                                                  |
| `Expenses:Gifts`                      |                                                                  |
| `Expenses:Donations`                  |                                                                  |
| `Expenses:Subscriptions`              | Recurring by definition. Streaming, software, gym. See below     |

## Expenses, fixed

Long-term interesting, not actionable this month. Tracked, not budgeted.

| Account                            | Notes                                                                   |
| ---------------------------------- | ----------------------------------------------------------------------- |
| `Expenses:Housing:Rent`            |                                                                         |
| `Expenses:Housing:AdditionalCosts` | Nebenkosten                                                             |
| `Expenses:Housing:Electricity`     | Billed separately, so not AdditionalCosts                               |
| `Expenses:Telecom:Broadcasting`    | Serafe. A household levy, not a service, so not cancellable             |
| `Expenses:Telecom:Internet`        |                                                                         |
| `Expenses:Telecom:Mobile`          | Follows the person, not the flat                                        |
| `Expenses:Mobility:Car`            | Auto. Total cost of ownership                                           |
| `Expenses:Mobility:Car:Fuel`       |                                                                         |
| `Expenses:Mobility:Car:Insurance`  | Here, not `Expenses:Insurance`, else TCO is not a number                |
| `Expenses:Mobility:Car:Service`    | Garage, tyres, repairs                                                  |
| `Expenses:Mobility:Car:Tax`        | Verkehrssteuer. Here, not `Expenses:Taxes`, same reason                 |
| `Expenses:Mobility:Transit`        | ÖV                                                                      |
| `Expenses:Insurance`               |                                                                         |
| `Expenses:Insurance:Health`        | Krankenkasse premium. Out of pocket is `Living:Health`                  |
| `Expenses:Insurance:Household`     | Hausrat, Haftpflicht                                                    |
| `Expenses:Insurance:Life`          |                                                                         |
| `Expenses:Taxes`                   |                                                                         |
| `Expenses:Taxes:Cantonal`          | Staats- und Gemeindesteuern. Wealth tax is assessed inside this         |
| `Expenses:Taxes:Federal`           | Direkte Bundessteuer                                                    |
| `Expenses:Taxes:Withholding`       | Non-recoverable share only. Reclaimable goes to `Assets:Receivable:Tax` |
| `Expenses:Fees:Bank`               |                                                                         |
| `Expenses:Fees:Brokerage`          |                                                                         |
| `Expenses:Fees:ForeignExchange`    |                                                                         |
| `Expenses:Uncategorized`           | Suspense, not a category. Never blocks an import, see Uncategorized     |
| `Expenses:Uncategorized:Cash`      | Wallet true-up, see Cash below                                          |

## Income

| Account                | Notes                                                                                                |
| ---------------------- | ---------------------------------------------------------------------------------------------------- |
| `Income:Salary`        |                                                                                                      |
| `Income:Salary:Stocks` | RSU and ESPP vesting                                                                                 |
| `Income:Dividends`     |                                                                                                      |
| `Income:Interest`      |                                                                                                      |
| `Income:Refunds`       | Cashback and untraceable rebates only. A refund of an expense goes back to that expense, see Refunds |
| `Income:CapitalGains`  | Segregated so taxable income can exclude it                                                          |
| `Income:Other`         |                                                                                                      |

## Assets and Liabilities

Not categories. Several things a budgeting app would file as categories live
here instead: cash, receivables, transfers, pension.

| Account                                        | Notes                                                      |
| ---------------------------------------------- | ---------------------------------------------------------- |
| `Assets:<Bank>:Checking`                       | One per bank account, named after the institution          |
| `Assets:<Bank>:Savings`                        | Closed accounts stay in the tree, history does not move    |
| `Assets:<Broker>:Cash:<CUR>`                   | One leaf per currency held                                 |
| `Assets:<Broker>:Securities`                   | FIFO booking                                               |
| `Assets:<Broker>:EquityComp:{Cash,Securities}` | RSU and ESPP awards, kept apart from ordinary brokerage    |
| `Assets:Cash:<CUR>`                            | Wallet, one per currency, see Cash below                   |
| `Assets:Crypto:<Venue>`                        | One per exchange or wallet, so each reconciles. Phase 5    |
| `Assets:Private:Startups`                      | Illiquid, held at cost. Phase 5                            |
| `Assets:Pension:Pillar2:<Provider>`            | Yearly assertion, see below                                |
| `Assets:Pension:Pillar3a:<Provider>`           | Yearly assertion, see below                                |
| `Assets:Pension:<Foreign>`                     | Foreign pension, non-CHF. Yearly assertion, see below      |
| `Income:Pension:Contributions`                 | Stated on the certificate, so booked                       |
| `Income:Pension:Growth`                        | Pad target. The remainder is investment return             |
| `Assets:Receivable:<Party>`                    | Per counterparty or group, see below                       |
| `Assets:Receivable:Tax`                        | Reclaimable withholding, see Refunds                       |
| `Assets:Transfers:InTransit`                   | Clearing, see below                                        |
| `Liabilities:<Bank>:<Card>`                    | One per card account. Several physical cards can share one |

Receivables are positive when they owe you, negative when you owe them, so
both directions collapse into one running balance. Per-person breakdown
comes from grouping by payee, so no account per person is needed:

```
select payee, sum(position) where account = 'Assets:Receivable:Family'
```

## Cash

ATM withdrawals are transfers between own assets, not spending. Large cash
spends get their own transaction out of the wallet. Small ones are not
itemized: count the wallet, assert the balance, let `pad` absorb the rest.

```
2026-03-02 * "ATM" "Cash withdrawal"
  Assets:PostFinance:Checking      -1000.00 CHF
  Assets:Cash:CHF                1000.00 CHF

2026-03-08 * "Babysitter" "Babysitting Feb-Mar, paid cash"
  Assets:Cash:CHF                -600.00 CHF
  Expenses:Kids:Childcare

2026-03-31 pad Assets:Cash:CHF Expenses:Uncategorized:Cash
2026-04-01 balance Assets:Cash:CHF     350.00 CHF
```

Historical cash is not reconstructed. The wallet opens at the first
withdrawal worth tracking.

## Padding

`pad` fills the gap between the tracked balance and the asserted one, and
books the difference to a named account. It is used in exactly two places:
the cash wallet, and retirement accounts.

**Never pad an account that has an importable transaction stream.** On a
bank or card account a missed import would be silently reclassified as
spending, and the assertion meant to catch it would pass instead of failing.
Pad only where an unexplained difference is expected and has a correct name.

Padding postings carry flag `P`, so they separate from anything hand
entered:

```
select year, account, sum(position) where flag = 'P'
  group by year, account order by year
```

Too much means something different at each site:

- **Cash.** The pad is unrecorded spending, so watch it as a share of cash
  withdrawn. A few percent is coffees. A third means the account has stopped
  meaning "small untracked spending", and the fix is a lower threshold for
  what gets its own transaction, or a more frequent wallet count. Frequent
  assertions also localize a gap to one month instead of a year.
- **Retirement.** The pad is investment return, so its size proves nothing.
  Check plausibility instead: divide by the opening balance and read the
  implied return. Negative growth in a rising year means the contribution
  on the certificate was misread or missed.

## Salary and payroll deductions

A bank statement shows one net credit. Gross pay, AHV, IV, ALV and BVG live
on the payslip, which is not an importable source. So `Income:Salary` means
net received, and there are no `Insurance:Social` or payroll tax accounts:
nothing could be imported into them.

```
2026-01-25 * "Employer" "Salary January"
  Assets:PostFinance:Checking      10000.00 CHF
  Income:Salary                   -10000.00 CHF
```

If gross ever matters, the annual Lohnausweis carries all of it in one
document per year. That is 1 file to handle, not 12 payslips. Not worth
doing until there is a reason.

## Retirement accounts

Brokerage accounts get full transaction detail: IBKR Flex and the equity
comp exports carry every trade, so the balance is derived.

Retirement accounts get their yearly statement value instead. Two different
reasons, one answer.

Pillar 2 contributions never touch a bank account at all. Pillar 3a
contributions do import, as ordinary transfers, but the investment growth on
top of them does not. Either way the balance built from importable
transactions drifts below the truth, silently and forever.

The annual certificate states the year-end balance, so assert it and let
`pad` absorb whatever was not imported:

```
2026-01-10 * "Provider" "Pillar 3a contribution 2026"
  Assets:PostFinance:Checking          -7258.00 CHF
  Assets:Pension:Pillar3a:Provider      7258.00 CHF

; Contribution imported, growth did not. The assertion covers both.
2026-12-30 pad Assets:Pension:Pillar3a:Provider Income:Pension
2026-12-31 balance Assets:Pension:Pillar3a:Provider  50000.00 CHF
```

Contributions and growth split, because they are different things:
contributions are income, growth is a gain. Merged, `Income:Pension` is not
comparable to `Income:Salary`, and any savings-rate query silently counts
market returns as earnings. The certificate states the contribution, so book
it and let `pad` take the remainder.

```
2026-12-29 * "Pension fund" "Pillar 2 contributions 2026, per certificate"
  Assets:Pension:Pillar2:Provider      12000.00 CHF
  Income:Pension:Contributions

; Whatever is left in the year-end balance is investment return.
2026-12-30 pad Assets:Pension:Pillar2:Provider Income:Pension:Growth
2026-12-31 balance Assets:Pension:Pillar2:Provider  150000.00 CHF
```

**Balance assertions are evaluated at the start of their date.** Dating the
contribution 12-31 alongside the assertion puts it after: `pad` then absorbs
the entire balance into growth and the account overshoots by the
contribution. `bean-check` stays green either way, so this fails silently.
Date anything that belongs inside an assertion strictly before it.

One `pad` and one `balance` per account per year, for every pension account
including foreign ones. Pension assets count toward net worth, so query them
separately when asking what is actually spendable.

## Subscriptions

Recurring is what makes them actionable, so they stay in one account rather
than being scattered by theme. Streaming sits here, not in
`Leisure:Culture`, which is one-off by nature. The cancel-candidate list
comes from grouping by payee, no account per service:

```
select payee, count(position) as months, max(date) as last_seen,
       sum(position) as total
  where account = 'Expenses:Subscriptions' group by 1 order by 4 desc
```

A high month count means recurring. A stale `last_seen` means it lapsed or
was cancelled.

## Holdings and pricing

Positions with a cost basis are booked with `{}`, so cost and market value
are both available:

- `sum(cost(position))` is what was paid
- `sum(value(position))` is what it is worth at the latest `price`

**A position with no** `price` **directive silently drops out of any valued
total.** It does not fall back to cost. Net worth comes back as a mixed
bucket (`120000.00 CHF  5000 ACME`) rather than an error. So anything
illiquid gets a `price` at cost on the day it is acquired, and a new
`price` whenever a funding round or valuation gives a better mark. The
cost basis never changes.

```
2025-04-01 * "Broker" "Series C"
  Assets:Private:Startups          5000 ACME {10.00 CHF}
  Assets:Bank                  -50000.00 CHF

; Mark at cost on day one, else the position drops out of net worth.
2025-04-01 price ACME              10.00 CHF

; New round, two years later. Cost basis unchanged, market value moves.
2027-05-01 price ACME              26.00 CHF
```

### Equity compensation

A vest books income at fair market value and holds the shares at that same
cost, so a later sale measures gain from the vest price rather than from
zero. Sell-to-cover is a posting on the vest, not a separate event.

```
2026-02-15 * "Employer" "RSU vest, 20 shares, 6 sold to cover"
  Assets:Broker:EquityComp:Securities    14 EMPL {180.00 USD}
  Expenses:Taxes:Withholding        1080.00 USD
  Income:Salary:Stocks             -3600.00 USD

2027-06-20 * "Broker" "Sell 14 EMPL"
  Assets:Broker:EquityComp:Securities   -14 EMPL {180.00 USD} @ 205.00 USD
  Assets:Broker:Cash:USD             2870.00 USD
  Income:CapitalGains                -350.00 USD
```

### Foreign currency

There is no FX gain or loss account, and there should not be one.

Realized FX needs no posting: a conversion balances at the day's rate by
construction. Only the spread is an expense.

```
2026-02-01 * "Bank" "Convert 5000 EUR to CHF"
  Assets:DKB:Checking            -5000.00 EUR @ 0.92 CHF
  Assets:PostFinance:Checking     4590.00 CHF
  Expenses:Fees:ForeignExchange      10.00 CHF
```

Unrealized FX is not a transaction at all, it is a property of the date the
ledger is valued on. The same holdings come out differently per date:

```
19340.00 CHF   valued at the 0.95 rate
19190.00 CHF   valued at the 0.92 rate
```

Use `convert(position, 'CHF')` for this, not `value(position)`. On plain
cash `value()` silently returns the original currency untouched, which
looks like a working query returning a wrong answer.

### Crypto

Each coin is a commodity with a cost basis, not a CHF balance. A plain
balance can only report what was paid in: no unrealized gain, no year-end
value for the Steuererklärung, and a self-custody withdrawal would look
like a transfer between unrelated pots.

Accounts mirror where the keys actually are, so each one can carry balance
assertions reconciled against that venue's export. A pooled
`Assets:Crypto` could not.

```
2025-03-01 * "Exchange" "Buy 0.5 BTC"
  Assets:Crypto:Exchange             0.5 BTC {40000.00 CHF}
  Assets:Bank                  -20000.00 CHF

; Self-custody move. Cost basis rides along, so no gain is realized.
2025-06-01 * "Exchange" "Withdraw to hardware wallet"
  Assets:Crypto:Exchange            -0.5 BTC {40000.00 CHF}
  Assets:Crypto:HardwareWallet       0.5 BTC {40000.00 CHF}
```

Year-end prices are needed for wealth tax regardless, so maintaining them
costs nothing extra over the plain-balance alternative.

## Transfers

Both legs of a transfer post to `Assets:Transfers:InTransit`, so an
unmatched transfer surfaces as a nonzero balance rather than distorting
income and expenses. Assert it back to zero periodically.

Both legs post there even when the two sides can be matched. Matching is a
detection and reconciliation tool, not a reason to merge the transactions
into one:

- Each importer sees one file. The second leg can arrive weeks later, so an
  importer that needs the other side to decide its output is order
  dependent.
- Merging when the second leg lands means rewriting the first. Importers
  add, never rewrite.
- The dates genuinely differ. Money leaves on the 20th and lands on the
  22nd, so a merged transaction is wrong about one side and breaks that
  account's balance assertion.
- Matching fails sometimes, so `InTransit` is needed as the fallback
  anyway. One shape beats two.

Where matching earns its keep, in Phase 3: a debit near a same-sized credit
on another account is a strong signal the line is a transfer at all, which
is the hard part. Matched pairs can carry a `^link` for audit, and a nonzero
`InTransit` balance then points at a specific transfer instead of just
existing.

A cross-currency transfer needs a rate on the receiving leg, else
`InTransit` holds two currencies and never clears.

```
2026-01-20 * "PostFinance" "Send to broker"
  Assets:PostFinance:Checking     -1000.00 CHF
  Assets:Transfers:InTransit       1000.00 CHF

2026-01-22 * "Broker" "Funds received"
  Assets:Transfers:InTransit      -1000.00 CHF @ 1.05 USD
  Assets:IBKR:Cash:USD             1050.00 USD
```

This is the one case where the second importer needs the first leg's amount.
In practice funding is same currency and the conversion happens inside the
broker afterwards, so it may not come up.

## Splits

One statement line can carry several postings. Gross amounts stay visible
rather than netting out.

```
2026-05-04 * "Supermarket" "Groceries and household"
  Assets:PostFinance:Checking       -120.00 CHF
  Expenses:Living:Groceries           85.00 CHF
  Expenses:Shopping:Home              35.00 CHF
```

A partial return is not a split. See Refunds.

## Refunds

**A refund of your own spending is not income. It posts negative to the
account the original expense went to.**

The reason is budgeting. Budgets are per expense category, so a refund
booked to `Income:Refunds` never gives the budget back: spend 100 of a 500
clothing budget, return 30, and the category has to read 70.

```
2026-05-15 * "Retailer" "Order 4471" ^order-4471
  Liabilities:PostFinance:Visa        -300.00 CHF
  Expenses:Shopping:Clothing:Person    180.00 CHF
  Expenses:Shopping:Electronics        120.00 CHF

; Six weeks later. Negative to the same account, not to income.
2026-06-28 * "Retailer" "Return from order 4471" ^order-4471
  Liabilities:PostFinance:Visa          80.00 CHF
  Expenses:Shopping:Clothing:Person    -80.00 CHF
```

The full amount is booked at purchase, because at purchase that is all that
is known. Nothing is amended when the refund lands, so re-import stays
idempotent. The category is overstated in May, understated in June, and
exactly right over any period holding both. A category can go negative in a
month. That is fine.

`^links` join the two transactions. This is not tagging: a tag marks a
transaction to build a cross-cutting total, a link joins two transactions
that are one event.

Which account to credit is a judgment the bank line cannot make. Default to
the original account, `!` flag when the order spanned several.

Insurer reimbursements are the same shape and matter more: larger amounts,
longer lag, and they recur.

```
2026-03-04 * "Clinic" "Treatment"
  Assets:PostFinance:Checking        -900.00 CHF
  Expenses:Living:Health              900.00 CHF

2026-07-20 * "Insurer" "Reimbursement, Selbstbehalt retained"
  Assets:PostFinance:Checking         640.00 CHF
  Expenses:Living:Health             -640.00 CHF
```

`Income:Refunds` is left for money in that reverses no specific expense:
cashback, referral bonuses, an untraceable rebate. It should stay nearly
empty.

### Reclaimable tax is not a refund

A reclaimable withholding tax was never an expense. It is a claim on the tax
office from the moment it is withheld, so it books as a receivable and no
year is distorted.

```
2026-04-15 * "Broker" "Dividend, 35% withheld"
  Assets:IBKR:Cash:USD                65.00 USD
  Expenses:Taxes:Withholding          15.00 USD   ; not recoverable
  Assets:Receivable:Tax               20.00 USD   ; reclaimable
  Income:Dividends                   -100.00 USD

2027-09-30 * "Tax office" "DA-1 reclaim 2026"
  Assets:IBKR:Cash:USD                20.00 USD
  Assets:Receivable:Tax              -20.00 USD
```

Verrechnungssteuer is the clean case: fully reclaimable if the income is
declared, so it is 100% receivable. Foreign withholding depends on the
treaty and on actually filing DA-1. Where the recoverable share is not
known, book it all to `Expenses:Taxes:Withholding` and reverse on receipt.

## Uncategorized

`Expenses:Uncategorized` is a suspense account, not a category. It never
blocks an import, and it is meant to be emptied rather than to accumulate.
Report it monthly, largest first, and recategorize from there.

```
select date, payee, narration, position
  where account = 'Expenses:Uncategorized' order by abs(number) desc
```

Left alone it grows. In the bank's own categorization roughly a third of
checking rows land in a catch-all or in nothing at all.

`Expenses:Uncategorized:Cash` is different and stays. It is the wallet
true-up and is expected to carry a balance.

The two are opposites despite the shared name. `Expenses:Uncategorized` is a
missing **classification**: the transaction is imported, the amount and
payee are known, and a source exists to resolve it.
`Expenses:Uncategorized:Cash` is a missing **transaction**: nothing beyond
the aggregate was ever knowable, and no source exists to fix it from. So one
is emptied and the other is not, and only the second is ever a `pad` target.
See Padding.

Match the suspense account with `=` and not a prefix, as the query above
does, or the cash balance makes it look permanently dirty.

## History and scope

Full history is the goal, from whatever sources already exist. The
statements and exports on disk are what there is.

Pre-2018 exists only in the SEE Finance QIF export, which has no balances,
no currency and the old taxonomy. It comes in as-is and balances get
adjusted where they are wrong, rather than being reconstructed.

Neobank accounts are deferred. Multi-currency, and the histories have gaps.

Which institutions and people the placeholders resolve to, and where the
coverage is partial, is recorded privately with the ledger.

### Dormant accounts

An account that stopped moving stays open rather than being closed. `close`
guards nothing: beancount accepts a close on a non-zero balance silently.
And a closed account has to be reopened the moment it is used again, which
is likely for anything lending-shaped.

A zero assertion dated where the activity stopped does the real work. A
leftover from the old era surfaces instead of sitting there unnoticed.

```
; Date this at the transition, not today.
2021-01-01 balance Assets:Receivable:Party      0.00 CHF
```
