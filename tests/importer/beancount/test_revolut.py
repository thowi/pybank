import datetime
import decimal

import pytest
from beancount import loader
from beancount.core import amount, data, prices
from beancount.parser import printer
from beangulp import exceptions, extract

from pybank.importer.beancount import (
    BANK_FEES,
    FX_FEES,
    IN_TRANSIT,
    UNCATEGORIZED,
    revolut,
    routing,
    transfer_matcher,
)

CHF = "Assets:Revolut:CHF"
EUR = "Assets:Revolut:EUR"

HEADER = "Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance\n"

# The reverted row never completed and moves no money. The card payment carries
# a fee, so its balance moves by the amount minus the fee.
CHF_CSV = HEADER + (
    "Topup,Current,2026-01-02 09:00:00,2026-01-02 09:00:05,Top-up by *0000,1.00,0.00,CHF,"
    "REVERTED,\n"
    "Topup,Current,2026-01-02 09:01:00,2026-01-02 09:01:05,Top-up by *0000,500.00,1.50,CHF,"
    "COMPLETED,498.50\n"
    'Card Payment,Current,2026-01-03 18:00:00,2026-01-05 03:00:00,"Grocer, Ltd",-40.00,0.00,CHF,'
    "COMPLETED,458.50\n"
    "Exchange,Current,2026-01-06 10:00:00,2026-01-06 10:00:00,Exchanged to EUR,-100.00,0.50,"
    "CHF,COMPLETED,358.00\n"
    "Card Payment,Current,2026-01-07 12:00:00,2026-01-07 12:00:01,COFFEE BAR,-4.50,0.00,CHF,"
    "COMPLETED,353.50\n"
    "Card Payment,Current,2026-01-07 12:05:00,2026-01-07 12:05:01,COFFEE BAR,-4.50,0.00,CHF,"
    "COMPLETED,349.00\n"
)

# The older export spells types in capitals and joins words with underscores.
EUR_CSV = HEADER + (
    "EXCHANGE,Current,2026-01-06 10:00:00,2026-01-06 10:00:00,Exchanged to EUR,104.00,0.00,EUR,"
    "COMPLETED,104.00\n"
)


def _write(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


@pytest.fixture
def importer():
    return revolut.Importer({"CHF": CHF, "EUR": EUR})


@pytest.fixture
def chf_path(tmp_path):
    return _write(tmp_path, "chf.csv", CHF_CSV)


def _txns(entries):
    return [e for e in entries if isinstance(e, data.Transaction)]


def _balances(entries):
    return [e for e in entries if isinstance(e, data.Balance)]


def _main(entries):
    return [t for t in _txns(entries) if not t.narration.startswith("Fee: ")]


def test_identify(tmp_path, importer, chf_path):
    assert importer.identify(chf_path)
    assert not importer.identify(_write(tmp_path, "notes.txt", "hello"))
    assert not importer.identify(_write(tmp_path, "other.csv", "a,b\n1,2\n"))


def test_a_file_with_no_rows_names_no_currency(tmp_path, importer):
    assert not importer.identify(_write(tmp_path, "empty.csv", HEADER))


def test_each_currency_books_into_its_own_account(tmp_path, importer, chf_path):
    assert importer.account(chf_path) == CHF
    assert importer.account(_write(tmp_path, "eur.csv", EUR_CSV)) == EUR


def test_a_column_added_to_the_export_keeps_the_file_ours(tmp_path, importer):
    wider = CHF_CSV.replace("Balance\n", "Balance,Extra\n", 1)

    assert importer.identify(_write(tmp_path, "wider.csv", wider))


def test_a_mixed_currency_file_is_refused(tmp_path, importer):
    path = _write(tmp_path, "mixed.csv", CHF_CSV + EUR_CSV.removeprefix(HEADER))

    assert importer.identify(path)
    with pytest.raises(exceptions.Error, match="one currency"):
        importer.extract(path, [])


def test_a_savings_row_is_refused(tmp_path, importer):
    path = _write(tmp_path, "savings.csv", CHF_CSV.replace("Current", "Savings", 1))

    with pytest.raises(exceptions.Error, match="Savings"):
        importer.extract(path, [])


def test_a_currency_with_no_account_configured_names_the_currency(tmp_path):
    importer = revolut.Importer({"CHF": CHF})
    path = _write(tmp_path, "eur.csv", EUR_CSV)

    # The file is still ours. Only the config falls short, so name the currency.
    assert importer.identify(path)
    with pytest.raises(routing.ConfigError, match="EUR"):
        importer.account(path)


def test_only_completed_rows_are_booked(importer, chf_path):
    numbers = [t.postings[0].units.number for t in _main(importer.extract(chf_path, []))]
    assert numbers == [
        decimal.Decimal("500.00"),
        decimal.Decimal("-40.00"),
        decimal.Decimal("-100.00"),
        decimal.Decimal("-4.50"),
        decimal.Decimal("-4.50"),
    ]


def test_the_booking_date_is_the_completed_date(importer, chf_path):
    card = _main(importer.extract(chf_path, []))[1]

    assert card.date == datetime.date(2026, 1, 5)
    assert card.meta["started-date"] == "2026-01-03"


def test_the_started_date_is_absent_when_it_is_the_same_day(importer, chf_path):
    topup = _main(importer.extract(chf_path, []))[0]
    assert "started-date" not in topup.meta


def test_a_quoted_description_keeps_its_comma(importer, chf_path):
    card = _main(importer.extract(chf_path, []))[1]
    assert card.narration == "Grocer, Ltd"
    assert card.payee is None


def test_an_ordinary_row_waits_for_categorization(importer, chf_path):
    card = _main(importer.extract(chf_path, []))[1]

    assert card.flag == "!"
    assert card.postings[0].account == CHF
    assert card.postings[1].account == UNCATEGORIZED
    assert card.postings[1].units is None, "contra leg auto-balances"
    assert card.meta["bank-type"] == "CARD_PAYMENT"


def test_a_fee_books_as_its_own_transaction(importer, chf_path):
    """The row keeps its gross amount, so a transfer leg still matches it."""
    txns = _txns(importer.extract(chf_path, []))
    topup, fee = txns[0], txns[1]

    assert topup.postings[0].units.number == decimal.Decimal("500.00")
    assert fee.date == topup.date
    assert fee.flag == "*"
    assert fee.meta["category-source"] == "statement"
    assert [(p.account, p.units.number) for p in fee.postings] == [
        (CHF, decimal.Decimal("-1.50")),
        (BANK_FEES, decimal.Decimal("1.50")),
    ]
    assert fee.meta["import-id"] != topup.meta["import-id"]


def test_an_exchange_fee_is_a_foreign_exchange_fee(importer, chf_path):
    fees = [t for t in _txns(importer.extract(chf_path, [])) if t.narration.startswith("Fee: ")]
    assert [t.postings[1].account for t in fees] == [BANK_FEES, FX_FEES]


def test_a_refunded_fee_books_back(tmp_path, importer):
    path = _write(
        tmp_path,
        "refund.csv",
        HEADER + "Card Refund,Current,2026-02-01 08:00:00,2026-02-01 08:00:00,Shop,20.00,-0.30,"
        "CHF,COMPLETED,20.30\n",
    )
    _refund, fee = _txns(importer.extract(path, []))

    assert fee.postings[0].units.number == decimal.Decimal("0.30")
    assert fee.postings[1].units.number == decimal.Decimal("-0.30")


def test_an_exchange_is_a_known_transfer(tmp_path, importer, chf_path):
    sent = _main(importer.extract(chf_path, []))[2]
    (received,) = _txns(importer.extract(_write(tmp_path, "eur.csv", EUR_CSV), []))

    for txn in (sent, received):
        assert txn.postings[1].account == IN_TRANSIT
        assert txn.flag == "*"
        assert txn.meta["category-source"] == "statement"
    assert received.meta["bank-type"] == "EXCHANGE", "older spelling, same type"


def test_both_exchange_legs_pair_without_a_market_rate(tmp_path, importer, chf_path):
    entries = [
        *importer.extract(chf_path, []),
        *importer.extract(_write(tmp_path, "eur.csv", EUR_CSV), []),
    ]

    (pair,) = transfer_matcher.candidates(entries, prices.build_price_map([]))

    assert pair.sender.units.currency == "CHF"
    assert pair.receiver.units.currency == "EUR"
    assert transfer_matcher.books_unasked(pair)


def test_balance_assertion_is_the_newest_completed_row(importer, chf_path):
    (balance,) = _balances(importer.extract(chf_path, []))

    assert balance.date == datetime.date(2026, 1, 8), (
        "assertions evaluate at the start of their date"
    )
    assert balance.account == CHF
    assert balance.amount == amount.Amount(decimal.Decimal("349.00"), "CHF")


def test_rows_sharing_a_timestamp_close_on_the_running_balance(tmp_path, importer):
    """With one timestamp, the running balance tells which row came last."""
    path = _write(
        tmp_path,
        "tied.csv",
        HEADER + "Card Payment,Current,2026-03-01 10:00:00,2026-03-01 10:00:00,Shop,-5.00,0.00,CHF,"
        "COMPLETED,85.00\n"
        "Card Refund,Current,2026-03-01 10:00:00,2026-03-01 10:00:00,Shop,10.00,0.00,CHF,"
        "COMPLETED,90.00\n",
    )
    (balance,) = _balances(importer.extract(path, []))
    assert balance.amount.number == decimal.Decimal("85.00")


def test_identical_rows_stay_distinct(importer, chf_path):
    coffees = [t for t in _txns(importer.extract(chf_path, [])) if t.narration == "Coffee Bar"]

    assert len(coffees) == 2, "two coffees on one day are legitimate"
    assert len({t.meta["import-id"] for t in coffees}) == 2


def test_import_ids_are_stable_across_runs(importer, chf_path):
    first = _txns(importer.extract(chf_path, []))
    second = _txns(importer.extract(chf_path, []))
    assert [t.meta["import-id"] for t in first] == [t.meta["import-id"] for t in second]


def test_import_ids_survive_a_reformatted_amount(tmp_path, importer, chf_path):
    """`-40.00` and `-40` are the same transaction, so the same id."""
    reformatted = _write(tmp_path, "reformatted.csv", CHF_CSV.replace(",-40.00,", ",-40,"))

    first = _main(importer.extract(chf_path, []))[1]
    second = _main(importer.extract(reformatted, []))[1]
    assert first.meta["import-id"] == second.meta["import-id"]


def test_reimport_marks_duplicates(importer, chf_path):
    existing = importer.extract(chf_path, [])
    entries = importer.extract(chf_path, [])

    importer.deduplicate(entries, existing)

    assert all(e.meta.get(extract.DUPLICATE) for e in entries)


def test_extracted_directives_load(tmp_path, importer, chf_path):
    """The real acceptance test: What comes out has to parse and balance."""
    entries = importer.extract(chf_path, [])

    ledger = tmp_path / "ledger.beancount"
    with ledger.open("w") as out:
        for account in (CHF, IN_TRANSIT, UNCATEGORIZED, BANK_FEES, FX_FEES):
            out.write(f"2026-01-01 open {account}\n")
        printer.print_entries(entries, file=out)

    _loaded, errors, _options = loader.load_file(str(ledger))
    assert errors == []
