"""Tests for the Wise importer.

All values here are invented. Never derive a fixture from a real export.
"""

import datetime
import decimal

import pytest
from beancount import loader
from beancount.core import amount, data, flags, prices
from beancount.parser import printer
from beangulp import exceptions, extract

from pybank.importer.beancount import (
    BANK_FEES,
    CATEGORY_SOURCE_STATEMENT,
    FX_FEES,
    IN_TRANSIT,
    UNCATEGORIZED,
    identity,
    qif,
    routing,
    transfer_matcher,
    wise,
)

ACCOUNTS = {"EUR": "Assets:Wise:EUR", "USD": "Assets:Wise:USD"}

_HEADER = (
    '"TransferWise ID",Date,"Date Time",Amount,Currency,Description,"Payment Reference",'
    '"Running Balance","Exchange From","Exchange To","Exchange Rate","Payer Name","Payee Name",'
    '"Payee Account Number",Merchant,"Card Last Four Digits","Card Holder Full Name",Attachment,'
    'Note,"Total fees","Exchange To Amount","Transaction Type","Transaction Details Type"\n'
)

# Newest first. Each fee row is a moment older than its main row, and carries
# the balance before the main row. The transfer is sent and refunded under one
# ID.
EUR_CSV = _HEADER + (
    "TRANSFER-300,12-02-2024,12-02-2024 10:00:00.002,100.00,EUR,"
    '"Sent money to A Shop",REF1,40.00,,,,,"A Shop",XX00,,,,,,1.00,,CREDIT,TRANSFER\n'
    "TRANSFER-300,10-02-2024,10-02-2024 10:00:00.002,-100.00,EUR,"
    '"Sent money to A Shop (fee: 1.00 EUR)",REF1,-60.00,,,,,"A Shop",XX00,,,,,,1.00,,DEBIT,TRANSFER\n'
    "FEE-TRANSFER-300,10-02-2024,10-02-2024 10:00:00.001,-1.00,EUR,"
    '"Wise Charges for: TRANSFER-300",REF1,40.00,,,,,Wise,,,,,,,0,,DEBIT,TRANSFER\n'
    "CARD-200,05-02-2024,05-02-2024 09:00:00.000,-9.00,EUR,"
    '"Card transaction of 9.00 EUR issued by A Cafe",,41.00,,,,,,,"A CAFE",0000,A Person,,,0.00,,DEBIT,CARD\n'
    "BALANCE-100,03-02-2024,03-02-2024 12:00:00.002,-49.50,EUR,"
    '"Converted 50.00 EUR to 54.00 USD (fee: 0.50 EUR)",,50.00,EUR,USD,1.09,,,,,,,,,0.50,54.00,DEBIT,CONVERSION\n'
    "FEE-BALANCE-100,03-02-2024,03-02-2024 12:00:00.001,-0.50,EUR,"
    '"Wise Charges for: BALANCE-100",,99.50,,,,,,,,,,,,0,,DEBIT,CONVERSION\n'
    "TRANSFER-050,01-02-2024,01-02-2024 08:00:00.000,100.00,EUR,"
    '"Topped up account",,100.00,,,,,,,,,,,,0.00,,CREDIT,MONEY_ADDED\n'
)

USD_CSV = _HEADER + (
    "BALANCE-100,03-02-2024,03-02-2024 12:00:00.002,54.00,USD,"
    '"Converted 50.00 EUR to 54.00 USD",,54.00,EUR,USD,1.09,,,,,,,,,0.00,54.00,CREDIT,CONVERSION\n'
)

# The older, shorter header. A fee row reuses the main row's ID.
EUR_LEGACY_CSV = (
    '"TransferWise ID",Date,Amount,Currency,Description,"Payment Reference","Running Balance",'
    '"Exchange From","Exchange To","Exchange Rate","Payer Name","Payee Name",'
    '"Payee Account Number",Merchant,"Total fees"\n'
    "BALANCE-100,03-02-2024,-49.50,EUR,"
    '"Converted EUR to USD",,50.00,EUR,USD,1.09,,,,,0.50\n'
    "BALANCE-100,03-02-2024,-0.50,EUR,"
    '"TransferWise Charges for: BALANCE-100",,99.50,,,,,,,,0\n'
    "TRANSFER-050,01-02-2024,100.00,EUR,"
    '"Topped up balance",,100.00,,,,,,,,0.00\n'
)

HEADER_ONLY_CSV = _HEADER


def _write(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


@pytest.fixture
def importer():
    return wise.Importer(ACCOUNTS)


@pytest.fixture
def eur_path(tmp_path):
    return _write(tmp_path, "eur.csv", EUR_CSV)


@pytest.fixture
def usd_path(tmp_path):
    return _write(tmp_path, "usd.csv", USD_CSV)


@pytest.fixture
def legacy_path(tmp_path):
    return _write(tmp_path, "legacy.csv", EUR_LEGACY_CSV)


def _txns(entries):
    return [e for e in entries if isinstance(e, data.Transaction)]


def _balances(entries):
    return [e for e in entries if isinstance(e, data.Balance)]


def _by_id(entries):
    return {t.meta[wise.META_WISE_ID]: t for t in reversed(_txns(entries))}


def test_identifies_both_header_generations(importer, eur_path, legacy_path):
    assert importer.identify(eur_path)
    assert importer.identify(legacy_path)


def test_rejects_other_files(importer, tmp_path):
    assert not importer.identify(_write(tmp_path, "notes.txt", "hello"))
    assert not importer.identify(_write(tmp_path, "other.csv", "Datum;Betrag\n01.01.2024;1\n"))
    assert not importer.identify(_write(tmp_path, "empty.csv", HEADER_ONLY_CSV))


def test_the_account_follows_the_currency(importer, eur_path, usd_path):
    assert importer.account(eur_path) == "Assets:Wise:EUR"
    assert importer.account(usd_path) == "Assets:Wise:USD"


def test_an_unconfigured_currency_names_it(eur_path):
    importer = wise.Importer({"USD": "Assets:Wise:USD"})

    # The file is still ours. Only the config falls short.
    assert importer.identify(eur_path)
    with pytest.raises(routing.ConfigError, match=r"EUR.*\[wise\.accounts\]"):
        importer.account(eur_path)


def test_contra_accounts_follow_the_row_type(importer, eur_path):
    txns = _by_id(importer.extract(eur_path, []))

    assert txns["FEE-TRANSFER-300"].postings[1].account == BANK_FEES
    assert txns["FEE-BALANCE-100"].postings[1].account == FX_FEES
    assert txns["BALANCE-100"].postings[1].account == IN_TRANSIT
    assert txns["CARD-200"].postings[1].account == UNCATEGORIZED
    assert txns["TRANSFER-050"].postings[1].account == UNCATEGORIZED


def test_only_rows_booked_by_type_are_flagged_okay(importer, eur_path):
    for txn in _txns(importer.extract(eur_path, [])):
        known = txn.postings[1].account != UNCATEGORIZED
        assert txn.flag == (flags.FLAG_OKAY if known else flags.FLAG_WARNING)
        source = txn.meta.get(qif.META_CATEGORY_SOURCE)
        assert source == (CATEGORY_SOURCE_STATEMENT if known else None)


def test_amounts_dates_and_text(importer, eur_path):
    card = _by_id(importer.extract(eur_path, []))["CARD-200"]

    assert card.date == datetime.date(2024, 2, 5)
    assert card.postings[0].units == amount.Amount(decimal.Decimal("-9.00"), "EUR")
    assert card.payee == "A Cafe", "the merchant, unshouted"
    assert card.narration == "Card transaction of 9.00 EUR issued by A Cafe"


def test_useful_columns_are_kept(importer, eur_path):
    txns = _by_id(importer.extract(eur_path, []))
    sent = txns["TRANSFER-300"]

    assert sent.meta["counterparty-account"] == "XX00"
    assert sent.meta["payment-reference"] == "REF1"
    assert txns["BALANCE-100"].meta["exchange-rate"] == "1.09"
    assert "exchange-rate" not in txns["CARD-200"].meta, "an absent key beats an empty one"


def test_the_newest_row_closes_the_statement(importer, eur_path):
    entries = importer.extract(eur_path, [])
    (balance,) = _balances(entries)

    assert balance.account == "Assets:Wise:EUR"
    assert balance.amount == amount.Amount(decimal.Decimal("40.00"), "EUR")
    assert balance.date == datetime.date(2024, 2, 13), "assertions evaluate at start of day"
    total = sum(t.postings[0].units.number for t in _txns(entries))
    assert total == balance.amount.number, "the statement opens at zero"


def test_a_reused_id_yields_distinct_import_ids(importer, eur_path):
    ids = [t.meta[identity.META_KEY] for t in _txns(importer.extract(eur_path, []))]
    assert len(set(ids)) == len(ids)


def test_the_legacy_export_yields_the_same_import_ids(importer, eur_path, legacy_path):
    """A re-download in the current flavor must not import old rows twice."""
    current = {
        t.meta[identity.META_KEY]: t.meta[wise.META_WISE_ID]
        for t in _txns(importer.extract(eur_path, []))
    }
    legacy = _by_id(importer.extract(legacy_path, []))

    assert set(legacy) == {"BALANCE-100", "FEE-BALANCE-100", "TRANSFER-050"}
    assert legacy["FEE-BALANCE-100"].postings[1].account == FX_FEES
    for wise_id, txn in legacy.items():
        assert current[txn.meta[identity.META_KEY]] == wise_id


def test_reimport_is_idempotent(importer, eur_path):
    existing = importer.extract(eur_path, [])
    again = importer.extract(eur_path, existing)
    importer.deduplicate(again, existing)

    assert all(e.meta.get(extract.DUPLICATE) for e in again)


def test_both_conversion_legs_pair_unasked(importer, eur_path, usd_path):
    entries = importer.extract(eur_path, []) + importer.extract(usd_path, [])
    price = data.Price(
        {}, datetime.date(2024, 2, 3), "EUR", amount.Amount(decimal.Decimal("1.08"), "USD")
    )

    (pair,) = transfer_matcher.candidates(entries, prices.build_price_map([price]))

    assert {leg.txn.meta[wise.META_WISE_ID] for leg in pair} == {"BALANCE-100"}
    assert transfer_matcher.books_unasked(pair)


def test_a_mixed_currency_file_is_refused(importer, tmp_path):
    mixed = _write(tmp_path, "mixed.csv", EUR_CSV + USD_CSV.removeprefix(_HEADER))
    with pytest.raises(exceptions.Error, match="one currency"):
        importer.extract(mixed, [])


def test_the_export_that_folds_fees_into_the_amount_is_refused(importer, tmp_path):
    folded = EUR_CSV.replace("(fee: 1.00 EUR)", "").replace("FEE-TRANSFER-300,", "IGNORED,", 1)
    folded = "".join(line for line in folded.splitlines(True) if not line.startswith("IGNORED,"))
    path = _write(tmp_path, "folded.csv", folded)

    with pytest.raises(exceptions.Error, match="TRANSFER-300.*fees split out"):
        importer.extract(path, [])


def test_extracted_directives_load(tmp_path, importer, eur_path, usd_path):
    """The real acceptance test: What comes out has to parse and balance."""
    entries = importer.extract(eur_path, []) + importer.extract(usd_path, [])

    ledger = tmp_path / "ledger.beancount"
    with ledger.open("w") as out:
        for account in sorted([*ACCOUNTS.values(), IN_TRANSIT, UNCATEGORIZED, BANK_FEES, FX_FEES]):
            out.write(f"2024-01-01 open {account}\n")
        printer.print_entries(data.sorted(entries), file=out)

    _loaded, errors, _options = loader.load_file(str(ledger))
    assert errors == []
