"""The fixtures mirror these shapes of the Flex format.

`netCash` is zero on a currency conversion, a closed lot states a positive
quantity against the sale that consumed it and carries no id back to it, a
short sale is a negative quantity marked open, and an option is priced per
share but held per contract.
"""

import decimal

import pytest
from beancount import loader
from beancount.core import data, flags
from beancount.parser import printer
from beangulp import extract

from pybank.importer.beancount import UNCATEGORIZED, ibkr, identity

# A year of activity: Stock bought and partly sold, options opened, closed and
# expired, a short sale, a purchase carrying transaction tax, a currency
# conversion, a position transferred in with its lots, a spinoff, a dividend
# with its withholding tax, a deposit, and VAT on a service.
FLEX_XML = """\
<FlexQueryResponse queryName="pybank" type="AF">
<FlexStatements count="1">
<FlexStatement accountId="U0000000" fromDate="20240101" toDate="20241231"
 period="" whenGenerated="20250102;080000">
<CashReport>
<CashReportCurrency accountId="U0000000" currency="USD"
 fromDate="20240101" toDate="20241231" startingCash="0" endingCash="18355.30" />
<CashReportCurrency accountId="U0000000" currency="EUR"
 fromDate="20240101" toDate="20241231" startingCash="0" endingCash="1000.00" />
<CashReportCurrency accountId="U0000000" currency="CHF"
 fromDate="20240101" toDate="20241231" startingCash="0" endingCash="-2.50" />
<CashReportCurrency accountId="U0000000" currency="BASE_SUMMARY"
 fromDate="20240101" toDate="20241231" startingCash="0" endingCash="20000.00" />
</CashReport>
<SecuritiesInfo>
<SecurityInfo assetCategory="STK" symbol="ABCD" description="Abcd Inc."
 conid="1000001" isin="US0000000001" currency="USD" />
<SecurityInfo assetCategory="STK" symbol="9999" description="Ninetyninetynine Ltd."
 conid="1000005" isin="KY0000000005" currency="USD" />
</SecuritiesInfo>
<Trades>
<Trade accountId="U0000000" currency="USD" assetCategory="STK" symbol="ABCD"
 description="Abcd Inc." conid="1000001" isin="US0000000001" tradeID="T1"
 transactionID="X1" tradeDate="20240103" dateTime="20240103;153000"
 buySell="BUY" openCloseIndicator="O" multiplier="1" quantity="10"
 tradePrice="100.00" proceeds="-1000.00" ibCommission="-1.00"
 ibCommissionCurrency="USD" taxes="0" netCash="-1001.00" />
<Trade accountId="U0000000" currency="USD" assetCategory="STK" symbol="ABCD"
 description="Abcd Inc." conid="1000001" isin="US0000000001" tradeID="T2"
 transactionID="X2" tradeDate="20240210" dateTime="20240210;153000"
 buySell="BUY" openCloseIndicator="O" multiplier="1" quantity="5"
 tradePrice="110.00" proceeds="-550.00" ibCommission="-0.50"
 ibCommissionCurrency="USD" taxes="0" netCash="-550.50" />
<Trade accountId="U0000000" currency="USD" assetCategory="OPT"
 symbol="ABCD  240719C00150000" description="ABCD 19JUL24 150.0 C"
 conid="1000002" tradeID="T3" transactionID="X3" tradeDate="20240301"
 dateTime="20240301;153000" buySell="BUY" openCloseIndicator="O"
 multiplier="100" putCall="C" strike="150" expiry="20240719" quantity="2"
 tradePrice="2.50" proceeds="-500.00" ibCommission="-1.30"
 ibCommissionCurrency="USD" taxes="0" netCash="-501.30" />
<Trade accountId="U0000000" currency="USD" assetCategory="STK" symbol="ABCD"
 description="Abcd Inc." conid="1000001" isin="US0000000001" tradeID="T4"
 transactionID="X4" tradeDate="20240315" dateTime="20240315;153000"
 buySell="SELL" openCloseIndicator="C" multiplier="1" quantity="-12"
 tradePrice="120.00" proceeds="1440.00" ibCommission="-1.20"
 ibCommissionCurrency="USD" taxes="0" netCash="1438.80" />
<Lot accountId="U0000000" currency="USD" assetCategory="STK" symbol="ABCD"
 conid="1000001" tradeDate="20240315" openDateTime="20240103;153000"
 multiplier="1" quantity="10" tradePrice="100.10" cost="1001.00" />
<Lot accountId="U0000000" currency="USD" assetCategory="STK" symbol="ABCD"
 conid="1000001" tradeDate="20240315" openDateTime="20240210;153000"
 multiplier="1" quantity="2" tradePrice="110.10" cost="220.20" />
<Trade accountId="U0000000" currency="USD" assetCategory="CASH"
 symbol="EUR.USD" description="EUR.USD" tradeID="T5" transactionID="X5"
 tradeDate="20240401" dateTime="20240401;100000" buySell="BUY" multiplier="1"
 quantity="1000" tradePrice="1.10" proceeds="-1100.00" ibCommission="-2.00"
 ibCommissionCurrency="CHF" taxes="0" netCash="0" />
<Trade accountId="U0000000" currency="USD" assetCategory="OPT"
 symbol="ABCD  240719C00150000" description="ABCD 19JUL24 150.0 C"
 conid="1000002" tradeID="T6" transactionID="X6" tradeDate="20240415"
 dateTime="20240415;153000" buySell="SELL" openCloseIndicator="C"
 multiplier="100" putCall="C" strike="150" expiry="20240719" quantity="-1"
 tradePrice="4.00" proceeds="400.00" ibCommission="-0.65"
 ibCommissionCurrency="USD" taxes="0" netCash="399.35" />
<Lot accountId="U0000000" currency="USD" assetCategory="OPT"
 symbol="ABCD  240719C00150000" conid="1000002" tradeDate="20240415"
 openDateTime="20240301;153000" multiplier="100" quantity="1"
 tradePrice="2.5065" cost="250.65" />
<Trade accountId="U0000000" currency="USD" assetCategory="STK" symbol="EFGH"
 description="Efgh Corp." conid="1000003" tradeID="T7" transactionID="X7"
 tradeDate="20240510" dateTime="20240510;153000" buySell="SELL"
 openCloseIndicator="O" multiplier="1" quantity="-3" tradePrice="50.00"
 proceeds="150.00" ibCommission="-0.30" ibCommissionCurrency="USD" taxes="0"
 netCash="149.70" />
<Trade accountId="U0000000" currency="USD" assetCategory="STK" symbol="9999"
 description="Ninetyninetynine Ltd." conid="1000005" isin="KY0000000005"
 tradeID="T8" transactionID="X8" tradeDate="20240520"
 dateTime="20240520;153000" buySell="BUY" openCloseIndicator="O"
 multiplier="1" quantity="20" tradePrice="25.00" proceeds="-500.00"
 ibCommission="-0.40" ibCommissionCurrency="USD" taxes="-0.60"
 netCash="-501.00" />
<Trade accountId="U0000000" currency="USD" assetCategory="OPT"
 symbol="ABCD  240719C00150000" description="ABCD 19JUL24 150.0 C"
 conid="1000002" tradeID="T9" transactionID="X9" tradeDate="20240719"
 dateTime="20240719;153000" buySell="SELL" openCloseIndicator="C"
 multiplier="100" putCall="C" strike="150" expiry="20240719" quantity="-1"
 tradePrice="0" proceeds="0" ibCommission="0" ibCommissionCurrency="USD"
 taxes="0" netCash="0" notes="Ep" />
<Lot accountId="U0000000" currency="USD" assetCategory="OPT"
 symbol="ABCD  240719C00150000" conid="1000002" tradeDate="20240719"
 openDateTime="20240301;153000" multiplier="100" quantity="1"
 tradePrice="2.5065" cost="250.65" />
</Trades>
<Transfers>
<Transfer accountId="U0000000" currency="USD" assetCategory="STK" symbol="IJKL"
 description="Ijkl Plc." conid="1000004" isin="GB0000000004"
 transactionID="X20" type="ACATS" direction="IN" date="20240601"
 dateTime="20240601;120000" quantity="30" transferPrice="0"
 positionAmount="900.00" cashTransfer="0" account="00000000" />
<TransferLot accountId="U0000000" currency="USD" assetCategory="STK"
 symbol="IJKL" conid="1000004" date="20240601" openDateTime="20220510;153000"
 quantity="20" transferPrice="0" cost="400.00" />
<TransferLot accountId="U0000000" currency="USD" assetCategory="STK"
 symbol="IJKL" conid="1000004" date="20240601" openDateTime="20230620;153000"
 quantity="10" transferPrice="0" cost="250.00" />
</Transfers>
<CorporateActions>
<CorporateAction accountId="U0000000" currency="USD" assetCategory="STK"
 symbol="MNOP" description="Mnop Inc." conid="1000006" isin="US0000000006"
 transactionID="X30" actionID="A30" type="SO" dateTime="20240615;202500"
 reportDate="20240615" quantity="5" proceeds="0" value="0"
 actionDescription="ABCD(US0000000001) SPINOFF 1 FOR 2 (MNOP, MNOP INC)" />
</CorporateActions>
<SalesTaxes>
<SalesTax accountId="U0000000" currency="CHF" date="20240801"
 country="Switzerland" taxType="VAT" taxableDescription="Market data"
 taxableAmount="-6.50" salesTax="-0.50" transactionID="X40" />
</SalesTaxes>
<CashTransactions>
<CashTransaction accountId="U0000000" currency="USD"
 type="Deposits/Withdrawals" amount="20000.00" dateTime="20240102;000000"
 reportDate="20240102" transactionID="X10" description="Incoming wire" />
<CashTransaction accountId="U0000000" currency="USD" assetCategory="STK"
 type="Dividends" amount="25.00" dateTime="20240401;000000"
 reportDate="20240401" transactionID="X11" symbol="ABCD" conid="1000001"
 isin="US0000000001" description="ABCD CASH DIVIDEND USD 2.50 PER SHARE" />
<CashTransaction accountId="U0000000" currency="USD" assetCategory="STK"
 type="Withholding Tax" amount="-3.75" dateTime="20240401;000000"
 reportDate="20240401" transactionID="X12" symbol="ABCD" conid="1000001"
 isin="US0000000001" description="ABCD CASH DIVIDEND USD 2.50 PER SHARE" />
</CashTransactions>
</FlexStatement>
</FlexStatements>
</FlexQueryResponse>
"""

# A rename and a reorg the first export does not show: IBKR now calls conid
# 1000001 `WXYZ`, a rights subscription reports its three legs as two rows
# sharing an actionID, and a conversion rate carries more digits than the
# proceeds it produced. No cash report, so this one asserts no balances.
REORG_XML = """\
<FlexQueryResponse queryName="pybank" type="AF">
<FlexStatements count="1">
<FlexStatement accountId="U0000000" fromDate="20250101" toDate="20251231"
 period="" whenGenerated="20260102;080000">
<SecuritiesInfo>
<SecurityInfo assetCategory="STK" symbol="WXYZ" description="Wxyz Inc."
 conid="1000001" isin="US0000000001" currency="USD" />
</SecuritiesInfo>
<Trades>
<Trade accountId="U0000000" currency="USD" assetCategory="STK" symbol="WXYZ"
 description="Wxyz Inc." conid="1000001" isin="US0000000001" tradeID="T1"
 transactionID="Y1" tradeDate="20250103" dateTime="20250103;153000"
 buySell="BUY" openCloseIndicator="O" multiplier="1" quantity="10"
 tradePrice="100.00" proceeds="-1000.00" ibCommission="0"
 ibCommissionCurrency="USD" taxes="0" netCash="-1000.00" />
<Trade accountId="U0000000" currency="USD" assetCategory="CASH"
 symbol="EUR.USD" description="EUR.USD" tradeID="T2" transactionID="Y2"
 tradeDate="20250104" dateTime="20250104;100000" buySell="BUY" multiplier="1"
 quantity="1000" tradePrice="1.10000001" proceeds="-1100.00" ibCommission="0"
 ibCommissionCurrency="USD" taxes="0" netCash="0" />
</Trades>
<CorporateActions>
<CorporateAction accountId="U0000000" currency="USD" assetCategory="STK"
 symbol="RGHT" description="Rght Rights" conid="1000007" transactionID="Y50"
 actionID="A50" type="RI" dateTime="20250501;202500" reportDate="20250501"
 quantity="100" proceeds="0" value="100.00" isin="US0000000007"
 actionDescription="WXYZ(US0000000001) SUBSCRIBABLE RIGHTS ISSUE" />
<CorporateAction accountId="U0000000" currency="USD" assetCategory="STK"
 symbol="RGHT" description="Rght Rights" conid="1000007" transactionID="Y51"
 actionID="A51" type="SR" dateTime="20250601;194500" reportDate="20250601"
 quantity="-100" proceeds="-400.00" value="-100.00" isin="US0000000007"
 actionDescription="WXYZ(US0000000001) SUBSCRIBES TO 20 FOR 100" />
<CorporateAction accountId="U0000000" currency="USD" assetCategory="STK"
 symbol="WXYZ" description="Wxyz Inc." conid="1000001" transactionID="Y52"
 actionID="A51" type="SR" dateTime="20250601;194500" reportDate="20250601"
 quantity="20" proceeds="0" value="500.00"
 actionDescription="WXYZ(US0000000001) SUBSCRIBES TO 20 FOR 100" />
</CorporateActions>
</FlexStatement>
</FlexStatements>
</FlexQueryResponse>
"""

# A fraction bought whole, then sold off. IBKR marks the sale `O`, which is
# the quirk: The row is a liquidation, so it can only close.
FRACSHARE_XML = """\
<FlexQueryResponse queryName="pybank" type="AF">
<FlexStatements count="1">
<FlexStatement accountId="U0000000" fromDate="20250101" toDate="20251231"
 period="" whenGenerated="20260102;080000">
<SecuritiesInfo>
<SecurityInfo assetCategory="STK" symbol="ABCD" description="Abcd Inc."
 conid="1000001" isin="US0000000001" currency="USD" />
</SecuritiesInfo>
<Trades>
<Trade accountId="U0000000" currency="USD" assetCategory="STK" symbol="ABCD"
 description="Abcd Inc." conid="1000001" isin="US0000000001" tradeID="T1"
 transactionID="F1" tradeDate="20250103" dateTime="20250103;153000"
 buySell="BUY" openCloseIndicator="O" multiplier="1" quantity="10.5"
 tradePrice="100.00" proceeds="-1050.00" ibCommission="0"
 ibCommissionCurrency="USD" taxes="0" netCash="-1050.00" />
<Trade accountId="U0000000" currency="USD" assetCategory="STK" symbol="ABCD"
 description="Abcd Inc." conid="1000001" isin="US0000000001" tradeID="T2"
 transactionID="F2" tradeDate="20250201" dateTime="20250201;153000"
 buySell="SELL" openCloseIndicator="O" transactionType="FracShare"
 multiplier="1" quantity="-0.5" tradePrice="120.00" proceeds="60.00"
 ibCommission="0" ibCommissionCurrency="USD" taxes="0" netCash="60.00"
 notes="LF" />
</Trades>
</FlexStatement>
</FlexStatements>
</FlexQueryResponse>
"""

# A long position sold through zero: The sale closes the one lot it names and
# opens a short with the rest.
CLOSE_OPEN_XML = """\
<FlexQueryResponse queryName="pybank" type="AF">
<FlexStatements count="1">
<FlexStatement accountId="U0000000" fromDate="20250101" toDate="20251231"
 period="" whenGenerated="20260102;080000">
<Trades>
<Trade accountId="U0000000" currency="USD" assetCategory="STK" symbol="ABCD"
 description="Abcd Inc." conid="1000001" tradeID="T1" transactionID="C1"
 tradeDate="20250103" dateTime="20250103;153000" buySell="BUY"
 openCloseIndicator="O" multiplier="1" quantity="10" tradePrice="100.00"
 proceeds="-1000.00" ibCommission="0" ibCommissionCurrency="USD" taxes="0"
 netCash="-1000.00" />
<Trade accountId="U0000000" currency="USD" assetCategory="STK" symbol="ABCD"
 description="Abcd Inc." conid="1000001" tradeID="T2" transactionID="C2"
 tradeDate="20250201" dateTime="20250201;153000" buySell="SELL"
 openCloseIndicator="C;O" multiplier="1" quantity="-15" tradePrice="120.00"
 proceeds="1800.00" ibCommission="0" ibCommissionCurrency="USD" taxes="0"
 netCash="1800.00" />
<Lot accountId="U0000000" currency="USD" assetCategory="STK" symbol="ABCD"
 conid="1000001" tradeDate="20250201" openDateTime="20250103;153000"
 multiplier="1" quantity="10" tradePrice="100.00" cost="1000.00" />
</Trades>
</FlexStatement>
</FlexStatements>
</FlexQueryResponse>
"""

# A position transferred in without its lots.
TRANSFER_NO_LOTS_XML = """\
<FlexQueryResponse queryName="pybank" type="AF">
<FlexStatements count="1">
<FlexStatement accountId="U0000000" fromDate="20250101" toDate="20251231"
 period="" whenGenerated="20260102;080000">
<Transfers>
<Transfer accountId="U0000000" currency="USD" assetCategory="STK" symbol="IJKL"
 description="Ijkl Plc." conid="1000004" transactionID="N1" type="ACATS"
 direction="IN" date="20250601" dateTime="20250601;120000" quantity="4"
 transferPrice="30.00" positionAmount="120.00" cashTransfer="0"
 account="00000000" />
</Transfers>
</FlexStatement>
</FlexStatements>
</FlexQueryResponse>
"""

# Rights issued and sold on one day. The sale only loads if the action that
# created the rights books first.
SAME_DAY_XML = """\
<FlexQueryResponse queryName="pybank" type="AF">
<FlexStatements count="1">
<FlexStatement accountId="U0000000" fromDate="20250101" toDate="20251231"
 period="" whenGenerated="20260102;080000">
<Trades>
<Trade accountId="U0000000" currency="USD" assetCategory="STK" symbol="RGHT"
 description="Rght Rights" conid="1000007" tradeID="T1" transactionID="S2"
 tradeDate="20250501" dateTime="20250501;100000" buySell="SELL"
 openCloseIndicator="C" multiplier="1" quantity="-100" tradePrice="1.00"
 proceeds="100.00" ibCommission="0" ibCommissionCurrency="USD" taxes="0"
 netCash="100.00" />
</Trades>
<CorporateActions>
<CorporateAction accountId="U0000000" currency="USD" assetCategory="STK"
 symbol="RGHT" description="Rght Rights" conid="1000007" transactionID="S1"
 actionID="A1" type="RI" dateTime="20250501;202500" reportDate="20250501"
 quantity="100" proceeds="0" value="100.00"
 actionDescription="WXYZ(US0000000001) SUBSCRIBABLE RIGHTS ISSUE" />
</CorporateActions>
</FlexStatement>
</FlexStatements>
</FlexQueryResponse>
"""

# What the ledger says about the security IBKR now calls `WXYZ`. The second
# conid is the contract IBKR reissued for the same listing after a reorg.
PINNED_LEDGER = """\
2024-01-01 commodity ABCD
  ibkr-conid: "1000001,1000009"
"""

NOT_FLEX_XML = """\
<?xml version="1.0"?>
<SomethingElse><Row date="20240101" /></SomethingElse>
"""

# Opens the extracted directives need, plus the booking method phase 1 settled
# on. No opening balances: The cash report asserts the activity in the fixture.
LEDGER_PREAMBLE = """\
2023-12-31 commodity ABCD
2023-12-31 commodity EFGH
2023-12-31 commodity IJKL
2023-12-31 commodity MNOP
2023-12-31 commodity X9999
2023-12-31 open Assets:IBKR:Cash:USD        USD
2023-12-31 open Assets:IBKR:Cash:EUR        EUR
2023-12-31 open Assets:IBKR:Cash:CHF        CHF
2023-12-31 open Assets:IBKR:Securities      "FIFO"
2023-12-31 open Income:IBKR:Dividends
2023-12-31 open Income:IBKR:PnL
2023-12-31 open Expenses:IBKR:Commission
2023-12-31 open Expenses:IBKR:TransactionTax
2023-12-31 open Expenses:IBKR:SalesTax
2023-12-31 open Expenses:Taxes:Withholding
2023-12-31 open Expenses:Uncategorized
2023-12-31 open Equity:Rounding
"""

# The same opens for the second fixture, under the names it books.
REORG_PREAMBLE = (
    LEDGER_PREAMBLE
    + """\
2023-12-31 commodity RGHT
2023-12-31 commodity WXYZ
"""
)

# Withholding tax reclassified long after the dividend: Both corrections settle
# before the statement starts. One was reported inside it, the other carries an
# equally old report date. Formatted with the statement's first day.
CORRECTION_XML = """\
<FlexQueryResponse queryName="pybank" type="AF">
<FlexStatements count="1">
<FlexStatement accountId="U0000000" fromDate="{from_date}" toDate="20251231"
 period="" whenGenerated="20260102;080000">
<CashTransactions>
<CashTransaction accountId="U0000000" currency="USD" assetCategory="STK"
 type="Withholding Tax" amount="-1.50" dateTime="20250610;000000"
 settleDate="20250612" reportDate="20250610" transactionID="X60"
 description="ABCD CASH DIVIDEND USD 1.00 PER SHARE" />
<CashTransaction accountId="U0000000" currency="USD" assetCategory="STK"
 type="Withholding Tax" amount="0.75" dateTime="20240401;000000"
 settleDate="20240401" reportDate="20250305" transactionID="X61"
 description="ABCD CASH DIVIDEND - US TAX RECLASSIFIED" />
<CashTransaction accountId="U0000000" currency="USD" assetCategory="STK"
 type="Withholding Tax" amount="0.25" dateTime="20240401;000000"
 settleDate="20240401" reportDate="20240401" transactionID="X62"
 description="ABCD CASH DIVIDEND - US TAX RECLASSIFIED" />
</CashTransactions>
</FlexStatement>
</FlexStatements>
</FlexQueryResponse>
"""

OPTION = "ABCD240719C00150000"
SECURITIES = "Assets:IBKR:Securities"


def _write(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


@pytest.fixture
def importer():
    return ibkr.Importer()


@pytest.fixture
def flex_path(tmp_path):
    return _write(tmp_path, "flex.xml", FLEX_XML)


@pytest.fixture
def entries(importer, flex_path):
    return importer.extract(flex_path, [])


@pytest.fixture
def reorg_path(tmp_path):
    return _write(tmp_path, "reorg.xml", REORG_XML)


@pytest.fixture
def corrections(importer, tmp_path):
    path = _write(tmp_path, "corrections.xml", CORRECTION_XML.format(from_date="20250101"))
    return importer.extract(path, [])


@pytest.fixture
def pinned():
    entries, errors, _options = loader.load_string(PINNED_LEDGER)
    assert errors == []
    return entries


@pytest.fixture
def reorg_entries(importer, reorg_path):
    return importer.extract(reorg_path, [])


def _commodities(txn, account=SECURITIES):
    return sorted({p.units.currency for p in _postings(txn, account) if p.units})


def _txns(entries):
    return [e for e in entries if isinstance(e, data.Transaction)]


def _balances(entries):
    return [e for e in entries if isinstance(e, data.Balance)]


def _by_id(entries, transaction_id):
    (txn,) = [t for t in _txns(entries) if t.meta.get(ibkr.META_TRANSACTION_ID) == transaction_id]
    return txn


def _by_action(entries, action_id):
    (txn,) = [t for t in _txns(entries) if t.meta.get(ibkr.META_ACTION_ID) == action_id]
    return txn


def _postings(txn, account):
    return [p for p in txn.postings if p.account == account]


def _decimal(value):
    return decimal.Decimal(value)


def test_a_flex_export_is_identified(importer, flex_path):
    assert importer.identify(flex_path)


def test_other_xml_is_not_claimed(importer, tmp_path):
    assert not importer.identify(_write(tmp_path, "other.xml", NOT_FLEX_XML))


def test_a_csv_is_not_claimed(importer, tmp_path):
    assert not importer.identify(_write(tmp_path, "flex.csv", FLEX_XML))


def test_no_account_number_has_to_be_configured(importer):
    """The account id is read from the file, as with the other importers."""
    assert importer.account("ignored.xml") == "Assets:IBKR:Cash"


def test_every_row_that_moves_something_is_extracted(entries):
    """Nine trades, three cash transactions, a transfer, a reorg and the VAT."""
    assert len(_txns(entries)) == 15


# Commodity naming.


def test_an_option_symbol_becomes_a_legal_commodity():
    """The OCC symbol is space padded, which a commodity name may not be."""
    assert ibkr._commodity("ABCD  240719C00150000") == OPTION


def test_a_numeric_listing_takes_a_prefix():
    """`9999` on the SEHK is a real ticker and an illegal commodity name."""
    assert ibkr._commodity("9999") == "X9999"


def test_a_plain_ticker_is_left_alone():
    assert ibkr._commodity("ABCD") == "ABCD"


@pytest.mark.parametrize(("symbol", "commodity"), [("ABCD.", "ABCD"), (".ABCD", "X.ABCD")])
def test_punctuation_at_either_end_still_makes_a_legal_commodity(symbol, commodity):
    assert ibkr._commodity(symbol) == commodity
    entries, errors, _ = loader.load_string(f"2020-01-01 commodity {commodity}\n")
    assert entries and not errors


def test_a_conid_list_may_have_spaces_after_its_commas():
    directive = data.Commodity({ibkr.META_COMMODITY_CONIDS: "1000001, 1000009"}, None, "ABCD")
    assert ibkr.Commodities([directive]).name("EFGH", "1000009") == "ABCD"


def test_a_rewritten_symbol_is_kept_in_metadata(entries):
    """Nothing else in the entry records which IBKR symbol it came from."""
    txn = _by_id(entries, "X3")

    assert txn.meta[ibkr.META_SYMBOL] == "ABCD  240719C00150000"
    assert ibkr.META_SYMBOL not in _by_id(entries, "X1").meta


# Stock.


def test_a_buy_opens_a_lot_at_cost(entries):
    (security,) = _postings(_by_id(entries, "X1"), SECURITIES)

    assert security.units == data.Amount(_decimal(10), "ABCD")
    assert security.cost.number == _decimal("100.00")
    assert security.cost.date.isoformat() == "2024-01-03"


def test_a_buy_books_the_commission_as_an_expense(entries):
    (commission,) = _postings(_by_id(entries, "X1"), "Expenses:IBKR:Commission")

    assert commission.units.number == _decimal("1.00"), "IBKR reports it negative"


def test_transaction_tax_is_booked_separately_from_commission(entries):
    """Stamp duty rides on the trade, not on a cash transaction of its own."""
    txn = _by_id(entries, "X8")

    (tax,) = _postings(txn, "Expenses:IBKR:TransactionTax")
    (commission,) = _postings(txn, "Expenses:IBKR:Commission")
    assert tax.units.number == _decimal("0.60")
    assert commission.units.number == _decimal("0.40")


def test_a_sale_closes_the_lots_ibkr_named(entries):
    lots = _postings(_by_id(entries, "X4"), SECURITIES)

    assert [p.units.number for p in lots] == [_decimal(-10), _decimal(-2)]
    assert all(p.price.number == _decimal("120.00") for p in lots)


def test_a_closed_lot_names_only_the_currency_it_cost(entries):
    """Neither the number nor the date IBKR reports can match a held lot.

    Its lot cost is net of the opening commission, which we expensed. Its open
    date is the one from before any reorg, and a reorg opens a fresh lot. So
    the ledger's own booking method picks the lot.
    """
    lots = _postings(_by_id(entries, "X4"), SECURITIES)

    assert all(p.cost.currency == "USD" for p in lots)
    assert all(p.cost.number_per is None and p.cost.date is None for p in lots)


def test_a_sale_leaves_the_gain_to_beancount(entries):
    (pnl,) = _postings(_by_id(entries, "X4"), "Income:IBKR:PnL")

    assert pnl.units is None


def test_a_short_sale_opens_a_position_instead_of_closing_one(entries):
    """Marked open and naming no lots, so the negative quantity is a new lot."""
    (security,) = _postings(_by_id(entries, "X7"), SECURITIES)

    assert security.units == data.Amount(_decimal(-3), "EFGH")
    assert security.cost.number == _decimal("50.00"), "a full cost, not a reduction"
    assert security.price is None


# Options.


def test_an_option_lot_costs_its_price_times_the_multiplier(entries):
    """Quoted per share, held per contract. Missing this is off by a hundred."""
    (security,) = _postings(_by_id(entries, "X3"), SECURITIES)

    assert security.units == data.Amount(_decimal(2), OPTION)
    assert security.cost.number == _decimal("250.000"), "2.50 a share, 100 a contract"


def test_selling_an_option_prices_the_close_per_contract(entries):
    (lot,) = _postings(_by_id(entries, "X6"), SECURITIES)

    assert lot.units == data.Amount(_decimal(-1), OPTION)
    assert lot.price.number == _decimal("400.00")


def test_an_option_expiring_worthless_closes_its_lot_at_zero(entries):
    """It arrives as a sale priced at nothing, releasing the basis as loss."""
    txn = _by_id(entries, "X9")

    (lot,) = _postings(txn, SECURITIES)
    (cash,) = _postings(txn, "Assets:IBKR:Cash:USD")
    assert lot.units == data.Amount(_decimal(-1), OPTION)
    assert lot.price.number == _decimal(0)
    assert cash.units.number == _decimal(0)
    assert _postings(txn, "Income:IBKR:PnL")


# Currency conversion.


def test_a_conversion_takes_its_second_leg_from_proceeds(entries):
    """`netCash` is zero on these, unlike on a security trade."""
    txn = _by_id(entries, "X5")

    (bought,) = _postings(txn, "Assets:IBKR:Cash:EUR")
    (sold,) = _postings(txn, "Assets:IBKR:Cash:USD")
    assert bought.units == data.Amount(_decimal(1000), "EUR")
    assert bought.price == data.Amount(_decimal("1.10"), "USD")
    assert sold.units.number == _decimal("-1100.00")


def test_a_conversion_pays_its_commission_from_a_third_currency(entries):
    """The commission sits outside both legs, so it needs its own posting."""
    txn = _by_id(entries, "X5")

    (commission,) = _postings(txn, "Expenses:IBKR:Commission")
    (cash,) = _postings(txn, "Assets:IBKR:Cash:CHF")
    assert commission.units == data.Amount(_decimal("2.00"), "CHF")
    assert cash.units == data.Amount(_decimal("-2.00"), "CHF")


# Transfers, corporate actions, tax.


def test_a_transfer_keeps_the_basis_and_open_date_of_each_lot(entries):
    """The reason this reads Flex at all. `ibflex` drops both fields."""
    txn = _by_id(entries, "X20")
    lots = _postings(txn, SECURITIES)

    assert [p.units.number for p in lots] == [_decimal(20), _decimal(10)]
    assert [p.cost.number for p in lots] == [_decimal(20), _decimal(25)]
    assert [p.cost.date.isoformat() for p in lots] == ["2022-05-10", "2023-06-20"]


def test_a_transfer_stays_uncategorized(entries):
    """The counterparty is another broker, so phase 3 matches it up."""
    txn = _by_id(entries, "X20")

    assert txn.flag == flags.FLAG_WARNING
    (contra,) = _postings(txn, UNCATEGORIZED)
    assert contra.units is None


def test_a_corporate_action_books_the_shares_it_produced(entries):
    txn = _by_id(entries, "X30")

    (security,) = _postings(txn, SECURITIES)
    assert security.units == data.Amount(_decimal(5), "MNOP")


def test_a_corporate_action_is_flagged_for_review(entries):
    """IBKR reports no basis for spun-off shares, so a human sets it."""
    assert _by_id(entries, "X30").flag == flags.FLAG_WARNING


def test_sales_tax_books_to_its_own_expense(entries):
    """The one cash movement no other section restates."""
    txn = _by_id(entries, "X40")

    (cash,) = _postings(txn, "Assets:IBKR:Cash:CHF")
    (tax,) = _postings(txn, "Expenses:IBKR:SalesTax")
    assert cash.units.number == _decimal("-0.50")
    assert tax.units.number == _decimal("0.50")


# Cash transactions.


def test_a_dividend_books_to_income(entries):
    txn = _by_id(entries, "X11")

    assert txn.flag == flags.FLAG_OKAY
    (cash,) = _postings(txn, "Assets:IBKR:Cash:USD")
    (income,) = _postings(txn, "Income:IBKR:Dividends")
    assert cash.units.number == _decimal("25.00")
    assert income.units.number == _decimal("-25.00")


def test_a_dividend_keeps_the_security_it_names(entries):
    """The postings carry no symbol, so the identifiers ride in metadata."""
    txn = _by_id(entries, "X11")

    assert txn.meta[ibkr.META_CONID] == "1000001"
    assert txn.meta[ibkr.META_ISIN] == "US0000000001"


def test_withholding_tax_books_to_expenses(entries):
    (tax,) = _postings(_by_id(entries, "X12"), "Expenses:Taxes:Withholding")

    assert tax.units.number == _decimal("3.75")


def test_a_deposit_stays_uncategorized(entries):
    """It is half of a transfer from a bank, which phase 3 matches up."""
    txn = _by_id(entries, "X10")

    assert txn.flag == flags.FLAG_WARNING
    (contra,) = _postings(txn, UNCATEGORIZED)
    assert contra.units is None


def test_a_cash_transaction_books_on_its_settle_date(corrections):
    txn = _by_id(corrections, "X60")

    assert txn.date.isoformat() == "2025-06-12"
    assert ibkr.META_SETTLE_DATE not in txn.meta


def test_a_backdated_correction_books_when_it_was_reported(corrections):
    """The earlier cash report never counted it, so neither may the ledger."""
    txn = _by_id(corrections, "X61")

    assert txn.date.isoformat() == "2025-03-05"
    assert txn.meta[ibkr.META_SETTLE_DATE].isoformat() == "2024-04-01"


def test_a_correction_reported_before_the_statement_books_on_its_first_day(corrections):
    txn = _by_id(corrections, "X62")

    assert txn.date.isoformat() == "2025-01-01"
    assert txn.meta[ibkr.META_SETTLE_DATE].isoformat() == "2024-04-01"


def test_a_backdated_correction_keeps_the_id_of_its_settle_date(importer, tmp_path, corrections):
    """A statement reaching back to the settle date books it there, same id."""
    path = _write(tmp_path, "wide.xml", CORRECTION_XML.format(from_date="20240101"))
    wide = importer.extract(path, [])

    for transaction_id in ("X61", "X62"):
        assert _by_id(wide, transaction_id).date.isoformat() == "2024-04-01"
        assert ibkr.META_SETTLE_DATE not in _by_id(wide, transaction_id).meta
        assert (
            _by_id(wide, transaction_id).meta[identity.META_KEY]
            == _by_id(corrections, transaction_id).meta[identity.META_KEY]
        )


# Balances and identity.


def test_one_balance_assertion_per_currency(entries):
    balances = _balances(entries)

    assert len(balances) == 3
    assert {b.account: b.amount.number for b in balances} == {
        "Assets:IBKR:Cash:USD": _decimal("18355.30"),
        "Assets:IBKR:Cash:EUR": _decimal("1000.00"),
        "Assets:IBKR:Cash:CHF": _decimal("-2.50"),
    }
    assert all(b.date.isoformat() == "2025-01-01" for b in balances)


def test_import_ids_are_stable_across_runs(importer, flex_path):
    def ids(entries):
        return [t.meta[identity.META_KEY] for t in _txns(entries)]

    assert ids(importer.extract(flex_path, [])) == ids(importer.extract(flex_path, []))


def test_reimport_is_idempotent(importer, flex_path):
    existing = _txns(importer.extract(flex_path, []))
    again = importer.extract(flex_path, existing)
    importer.deduplicate(again, existing)

    assert all(t.meta.get(extract.DUPLICATE) for t in _txns(again))


def test_extracted_directives_load(tmp_path, entries):
    """The real acceptance test: What comes out has to parse and balance.

    The balance assertions make it stricter than it looks. They come from the
    cash report, so they only hold if every trade, transfer, reorg and cash
    transaction above booked the amount IBKR says it did, in the currency it
    says. A missing option multiplier or a conversion leg taken from `netCash`
    fails here.
    """
    ledger = tmp_path / "ledger.beancount"
    with ledger.open("w") as out:
        out.write(LEDGER_PREAMBLE)
        printer.print_entries(entries, file=out)

    _loaded, errors, _options = loader.load_file(str(ledger))
    assert errors == []


# Instrument identity. A symbol is not one, a conid is.


def test_an_undeclared_conid_is_named_after_its_current_symbol(reorg_entries):
    txn = _by_id(reorg_entries, "Y1")

    assert _commodities(txn) == ["WXYZ"]
    assert ibkr.META_SYMBOL not in txn.meta


def test_the_ledgers_name_for_a_conid_survives_a_rename(importer, reorg_path, pinned):
    txn = _by_id(importer.extract(reorg_path, pinned), "Y1")

    assert _commodities(txn) == ["ABCD"]
    assert txn.meta[ibkr.META_SYMBOL] == "WXYZ"
    assert txn.meta[ibkr.META_CONID] == "1000001"


def test_one_commodity_may_cover_several_conids(pinned):
    commodities = ibkr.Commodities(pinned)

    assert commodities.name("WXYZ", "1000001") == "ABCD"
    assert commodities.name("OTHR", "1000009") == "ABCD"
    assert commodities.pinned("1000001")
    assert not commodities.pinned("1000007")


def test_a_rename_is_reported_once_per_conid(pinned, caplog):
    commodities = ibkr.Commodities(pinned)

    commodities.name("WXYZ", "1000001")
    commodities.name("WXYZ", "1000001")

    assert caplog.text.count("IBKR now calls conid 1000001") == 1


def test_a_conid_the_ledger_never_declared_stays_unpinned():
    commodities = ibkr.Commodities([])

    assert commodities.name("WXYZ", "1000001") == "WXYZ"
    assert not commodities.pinned("1000001")


# Corporate actions. One action, however many rows it reports.


def test_the_legs_of_one_action_book_as_one_transaction(reorg_entries):
    txn = _by_action(reorg_entries, "A51")

    assert _commodities(txn) == ["RGHT", "WXYZ"]
    assert [p.units.number for p in _postings(txn, "Assets:IBKR:Cash:USD")] == [_decimal("-400.00")]


def test_a_paired_action_carries_no_single_transaction_id(reorg_entries):
    txn = _by_action(reorg_entries, "A51")

    assert ibkr.META_TRANSACTION_ID not in txn.meta
    assert ibkr.META_ISIN not in txn.meta


def test_an_action_reporting_one_row_keeps_its_own_identifiers(reorg_entries):
    txn = _by_id(reorg_entries, "Y50")

    assert txn.meta[ibkr.META_ACTION_ID] == "A50"
    assert txn.meta[ibkr.META_ISIN] == "US0000000007"
    assert _commodities(txn) == ["RGHT"]


def test_a_paired_action_that_values_no_leg_is_warned_about(importer, tmp_path, caplog):
    split = REORG_XML.replace(
        'quantity="-100" proceeds="-400.00" value="-100.00"',
        'quantity="-100" proceeds="0" value="0"',
    ).replace('quantity="20" proceeds="0" value="500.00"', 'quantity="20" proceeds="0" value="0"')
    path = _write(tmp_path, "split.xml", split)

    with caplog.at_level("WARNING"):
        importer.extract(path, [])

    assert "Reorg A51" in caplog.text


# Rounding.


def test_a_conversion_rate_with_extra_digits_rounds_to_equity(reorg_entries):
    txn = _by_id(reorg_entries, "Y2")

    (rounding,) = _postings(txn, "Equity:Rounding")
    assert rounding.units == data.Amount(_decimal("-0.00001000"), "USD")


def test_a_transaction_that_balances_gets_no_rounding_posting(entries):
    txn = _by_id(entries, "X1")

    assert _postings(txn, "Equity:Rounding") == []


def test_reorg_directives_load(tmp_path, reorg_entries):
    """The rights subscription is the point: Three legs balance on their own.

    Rights bought for nothing, subscribed by paying cash, produce shares whose
    basis is the rights plus the cash. Booked as separate transactions each
    row needs a gain to close, and the gain would be invented.
    """
    ledger = tmp_path / "reorg.beancount"
    with ledger.open("w") as out:
        out.write(REORG_PREAMBLE)
        printer.print_entries(reorg_entries, file=out)

    loaded, errors, _options = loader.load_file(str(ledger))
    assert errors == []
    # Beancount drops the PnL auto-posting when the legs leave no residual.
    subscription = _by_action(loaded, "A51")
    assert _postings(subscription, "Income:IBKR:PnL") == []


def test_a_fractional_share_sale_reduces_whatever_ibkr_calls_it(importer, tmp_path):
    """As an opening it names a cost no held lot carries, so it cannot load."""
    path = _write(tmp_path, "frac.xml", FRACSHARE_XML)
    entries = importer.extract(path, [])

    ledger = tmp_path / "frac.beancount"
    with ledger.open("w") as out:
        out.write(LEDGER_PREAMBLE)
        printer.print_entries(entries, file=out)

    _loaded, errors, _options = loader.load_file(str(ledger))
    assert errors == []


def test_a_sale_naming_no_lots_reduces_its_quantity_once(importer, tmp_path):
    entries = importer.extract(_write(tmp_path, "frac.xml", FRACSHARE_XML), [])

    (sale,) = _postings(_by_id(entries, "F2"), SECURITIES)
    assert sale.units.number == _decimal("-0.5")


def test_an_action_books_before_a_trade_on_the_same_day(importer, tmp_path):
    entries = importer.extract(_write(tmp_path, "same-day.xml", SAME_DAY_XML), [])

    ledger = tmp_path / "same-day.beancount"
    with ledger.open("w") as out:
        out.write(REORG_PREAMBLE)
        printer.print_entries(entries, file=out)

    _loaded, errors, _options = loader.load_file(str(ledger))
    assert errors == []


def test_a_sale_through_zero_opens_a_short_with_what_its_lots_leave(importer, tmp_path):
    entries = importer.extract(_write(tmp_path, "close-open.xml", CLOSE_OPEN_XML), [])

    closed, opened = _postings(_by_id(entries, "C2"), SECURITIES)
    assert closed.units.number == _decimal(-10)
    assert opened.units.number == _decimal(-5)
    assert opened.cost.number == _decimal(120)

    ledger = tmp_path / "close-open.beancount"
    with ledger.open("w") as out:
        out.write(LEDGER_PREAMBLE)
        printer.print_entries(entries, file=out)

    _loaded, errors, _options = loader.load_file(str(ledger))
    assert errors == []


@pytest.mark.parametrize("lot", ["14.999999", "15.000001"])
def test_lots_that_miss_by_rounding_close_the_whole_trade(importer, tmp_path, caplog, lot):
    rounded = (
        CLOSE_OPEN_XML.replace(
            'quantity="10" tradePrice="100.00"\n proceeds="-1000.00"',
            'quantity="15" tradePrice="100.00"\n proceeds="-1500.00"',
        )
        .replace('netCash="-1000.00"', 'netCash="-1500.00"')
        .replace(
            'quantity="10" tradePrice="100.00" cost="1000.00"',
            f'quantity="{lot}" tradePrice="100.00" cost="1500.00"',
        )
    )
    entries = importer.extract(_write(tmp_path, "rounded.xml", rounded), [])

    (closed,) = _postings(_by_id(entries, "C2"), SECURITIES)
    assert closed.units.number == _decimal(-15)
    assert "FIFO" not in caplog.text

    ledger = tmp_path / "rounded.beancount"
    with ledger.open("w") as out:
        out.write(LEDGER_PREAMBLE)
        printer.print_entries(entries, file=out)

    _loaded, errors, _options = loader.load_file(str(ledger))
    assert errors == []


def test_a_transfer_without_lots_moves_at_its_transfer_price(importer, tmp_path):
    entries = importer.extract(_write(tmp_path, "no-lots.xml", TRANSFER_NO_LOTS_XML), [])

    (posting,) = _postings(_by_id(entries, "N1"), SECURITIES)
    assert posting.units.number == _decimal(4)
    assert posting.cost.number == _decimal(30)
    assert posting.cost.date.isoformat() == "2025-06-01"


def test_a_transferred_lot_without_a_cost_is_reported(tmp_path, caplog):
    no_cost = FLEX_XML.replace(
        'quantity="10" transferPrice="0" cost="250.00"', 'quantity="10" transferPrice="0"'
    )
    path = _write(tmp_path, "no-cost.xml", no_cost)

    lots = ibkr._transfer_lots(path)

    assert [lot.cost for lot in lots["X20"]] == [400, 0]
    assert "Transfer X20 has a lot without a cost" in caplog.text
