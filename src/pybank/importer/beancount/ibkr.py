"""IBKR Activity Flex Query importer for beangulp.

Input is the XML an Activity Flex Query produces, parsed by `ibflex`, not the
Activity Statement CSVs: Only Flex carries the `Lot` and `TransferLot` elements
that let a sale name the lots it closes.

The saved query must select Trades with Closed Lots, Cash Transactions,
Transfers, Corporate Actions, and Cash Report with a currency breakout, with
dates as `yyyyMMdd`, times as `HHmmss` and `;` between them.

Instruments are identified by `conid` rather than by symbol, and the ledger
holds that map. See `Commodities`.

Open the securities account `"FIFO"`. A closing trade names only the currency
its lot cost, so the ledger's own booking method picks the lot, and the
default booking rejects a reduction that spans two lots.

Reorgs book flagged, and may need their lots corrected by hand.

Sections this does not read are logged with a reason. Statement of Funds is
the one to reconcile against: Its running balance ends at the cash report's
`endingCash` for every currency, so the cash postings this produces have to
sum to the same.
"""

import datetime
import decimal
import logging
import re
from collections.abc import Callable, Iterable, Sequence
from typing import NamedTuple
from xml.etree import ElementTree

import beangulp
import ibflex
from beancount.core import amount, data, flags, interpolate, position
from ibflex import Types, enums

from . import UNCATEGORIZED, identity

# IBKR's own transaction identifier. Unique and stable across re-runs of a
# query, so it carries the import-id on its own.
META_TRANSACTION_ID = "transaction-id"

# On dividends and withholding tax, which name a security the postings do not.
META_CONID = "conid"
META_ISIN = "isin"

# The IBKR symbol, kept whenever it is not the commodity name itself.
META_SYMBOL = "ibkr-symbol"

# On a `commodity` directive in the ledger: The conids that commodity covers,
# comma separated. See `Commodities` for why the ledger holds this mapping.
META_COMMODITY_CONIDS = "ibkr-conid"

# The corporate action a transaction came from. One action reports one row per
# position it touched, and this is what says those rows were the same event.
META_ACTION_ID = "ibkr-action-id"

# For a cash transaction that was booked on another day than it settled.
# See `Importer._cash_transaction`.
META_SETTLE_DATE = "settle-date"

# The fake currency IBKR uses for the base-currency roll-up row in the cash
# report. Not a balance of anything the ledger holds.
_BASE_SUMMARY = "BASE_SUMMARY"

_ROOT_TAG = "FlexQueryResponse"
_SNIFF_BYTES = 4096

_ONE = decimal.Decimal(1)
_ZERO = decimal.Decimal(0)

# How far a cash assertion may miss before it means something.
_BALANCE_TOLERANCE = decimal.Decimal("0.00001")

# The largest imbalance to write off as rounding. IBKR reports rates and
# position values to a fixed number of digits, so the legs of a conversion meet
# a small fraction of a cent apart. Anything larger is a real gap and stays
# one, since a catch-all posting would hide it.
_ROUNDING_TOLERANCE = decimal.Decimal("0.0001")

# Anything a beancount commodity may not contain, and the prefix for a symbol
# that does not start with a letter.
_NOT_COMMODITY = re.compile(r"[^A-Z0-9._-]")
_SYMBOL_PREFIX = "X"

# Sections that restate activity read elsewhere. Importing them would double
# book: Statement of Funds is the cash ledger every trade and cash transaction
# already produces, and the Fx sections are the base-currency view of the same
# currency holdings. Worth keeping in the query as a reconciliation source.
_DERIVED = (
    "StmtFunds",
    "FxTransactions",
    "FxPositions",
    "OpenPositions",
    "ConversionRates",
    "TransactionTaxes",
)

# Sections with no posting shape yet. Securities lending settles inside the
# position rather than in cash, which is why the cash report still ties out
# without it.
_UNREAD = ("SLBActivities", "SLBFees", "StockGrantActivities")

# Asset classes with a verified posting shape. A trade in anything else is
# skipped loudly, because booking one on a guessed shape is worse than a gap.
_TRADEABLE = (
    enums.AssetClass.STOCK,
    enums.AssetClass.MUTUALFUND,
    enums.AssetClass.OPTION,
    enums.AssetClass.CASH,
)

# What each row handler returns: The fields its import-id is taken from, and a
# builder that makes the transaction once that id exists. None when the row
# cannot be booked at all. The id has to be settled for the whole statement
# before any transaction is built, which is why building is deferred.
_Built = tuple[identity.IdFields, Callable[[data.Meta], data.Transaction]] | None

logger = logging.getLogger(__name__)


class Accounts(NamedTuple):
    """An account where transactions book.

    `cash` is a prefix: The currency is appended, since IBKR holds one balance
    per currency and the ledger mirrors that.

    `rounding` takes the sub-cent residual of a conversion, and nothing else.
    """

    cash: str = "Assets:IBKR:Cash"
    securities: str = "Assets:IBKR:Securities"
    dividends: str = "Income:IBKR:Dividends"
    interest: str = "Income:IBKR:Interest"
    pnl: str = "Income:IBKR:PnL"
    commissions: str = "Expenses:IBKR:Commission"
    fees: str = "Expenses:IBKR:Fees"
    interest_paid: str = "Expenses:IBKR:Interest"
    transaction_tax: str = "Expenses:IBKR:TransactionTax"
    sales_tax: str = "Expenses:IBKR:SalesTax"
    withholding_tax: str = "Expenses:Taxes:Withholding"
    rounding: str = "Equity:Rounding"


# Cash transaction types that book to a known account. Deposits and
# withdrawals are deliberately absent: They are the other half of a transfer
# from a bank, which phase 3 matches, so they stay uncategorized.
_CASH_CONTRA = {
    enums.CashAction.DIVIDEND: "dividends",
    enums.CashAction.PAYMENTINLIEU: "dividends",
    enums.CashAction.WHTAX: "withholding_tax",
    enums.CashAction.BROKERINTRCVD: "interest",
    enums.CashAction.BONDINTRCVD: "interest",
    enums.CashAction.BROKERINTPAID: "interest_paid",
    enums.CashAction.BONDINTPAID: "interest_paid",
    enums.CashAction.FEES: "fees",
    enums.CashAction.ADVISORFEES: "fees",
    enums.CashAction.COMMADJ: "commissions",
}

DEFAULT_ACCOUNTS = Accounts()


# `ibflex` 1.1 declares no `cost` and no `openDateTime` on its own TransferLot,
# and its parser drops any attribute the dataclass does not declare, without
# raising. Those two are the incoming cost basis, the whole reason this reads
# Flex, so `_transfer_lots` re-reads them from the XML into this.
class TransferLot(NamedTuple):
    """One lot of a transferred position, at the basis it arrived with."""

    quantity: decimal.Decimal
    cost: decimal.Decimal
    currency: str
    open_date: datetime.date | None


def _posting(
    account: str,
    units: amount.Amount | None,
    cost: position.Cost | position.CostSpec | None = None,
    price: amount.Amount | None = None,
) -> data.Posting:
    return data.Posting(account, units, cost, price, None, None)


def _cash_account(accounts: Accounts, currency: str) -> str:
    return f"{accounts.cash}:{currency}"


def _commodity(symbol: str) -> str:
    """Returns the beancount commodity name for an IBKR symbol."""
    # Option symbols are OCC codes padded with spaces, `ABCD  240119C00150000`,
    # and some listings are all digits, `700` on the SEHK. Neither is a legal
    # commodity name, so the padding goes and a leading digit takes a prefix.
    name = _NOT_COMMODITY.sub("", symbol.upper())
    if not name:
        return _SYMBOL_PREFIX
    return f"{_SYMBOL_PREFIX}{name}" if name[0].isdigit() else name


# A symbol is not an identity. IBKR renames a ticker in place, so one holding
# reads as `FB` in an old export and `META` in a new one, and no row says they
# are the same thing. It also reuses a ticker across contracts, so unrelated
# positions collide under one name. The `conid` is the identity: An integer IBKR
# assigns per contract and never reassigns. The map lives in the ledger rather
# than here because an incremental import sees one file at a time, and that
# file carries only the name that was current when it was generated. Several
# `conids` may share one name: IBKR reissues a contract for the same listing
# after a reorg, and those positions never coexist, so sharing the name is
# safer than splitting them apart under an invented suffix.
class Commodities:
    """The commodity each IBKR `conid` books to, as the ledger declares it.

    Reads the `commodity` directives that carry `ibkr-conid`. A `conid` the
    ledger does not declare is named after its current symbol, which holds
    until the day IBKR renames it. One directive may cover several `conids`,
    for a listing IBKR reissued under a fresh contract after a reorg.
    """

    def __init__(self, existing: Iterable[data.Directive] = ()):
        self._names: dict[str, str] = {}
        for entry in existing:
            if not isinstance(entry, data.Commodity):
                continue
            for conid in str(entry.meta.get(META_COMMODITY_CONIDS) or "").split(","):
                if conid.strip():
                    self._names[conid.strip()] = entry.currency

    def pinned(self, conid: str | None) -> bool:
        return bool(conid) and conid in self._names

    def name(self, symbol: str, conid: str | None) -> str:
        """Returns what to book a symbol as, the ledger's own name winning."""
        derived = _commodity(symbol)
        declared = self._names.get(conid or "")
        if declared is None:
            return derived
        if declared != derived:
            logger.warning(
                "IBKR now calls conid %s %r, which the ledger holds as %s, so it "
                "books as %s. To follow the rename instead, edit that commodity "
                "directive and the postings already using it.",
                conid,
                symbol,
                declared,
                declared,
            )
        return declared


def _unit_cost(price: decimal.Decimal, multiplier: decimal.Decimal | None) -> decimal.Decimal:
    """Returns the cost of one held unit: An option contract, or a share."""
    # An option trades at a price per share but is held per contract, so a
    # multiplier of 100 makes one contract cost a hundred times its quoted
    # price. IBKR reports `proceeds` on the same basis.
    return price * (multiplier if multiplier is not None else _ONE)


def _charge(account: str, number: decimal.Decimal | None, currency: str) -> list[data.Posting]:
    """Returns a list with the fee's expense posting, empty if there is none."""
    # IBKR reports what it took from the account, so a charge arrives negative
    # and the expense is its opposite.
    if not number:
        return []
    return [_posting(account, amount.Amount(-number, currency))]


def _grouped(
    elements: Iterable[Types.FlexElement],
    parent: type,
    child: type,
) -> list[tuple[Types.FlexElement, list[Types.FlexElement]]]:
    """Returns each parent with the children that followed it."""
    # Flex nests closed lots inside the trade that closed them, and transfer
    # lots inside their transfer, but `ibflex` flattens every container and the
    # child carries no id back to the parent. `tradeID` is empty on a `Lot`. So
    # position in the document is the only thing left to group on.
    groups: list[tuple[Types.FlexElement, list[Types.FlexElement]]] = []
    for element in elements:
        if isinstance(element, parent):
            groups.append((element, []))
        elif isinstance(element, child) and groups:
            groups[-1][1].append(element)
    return groups


def _by_action(
    actions: Iterable[Types.FlexElement],
) -> list[list[Types.CorporateAction]]:
    """Returns the rows of each corporate action, grouped by `actionID`."""
    # One action reports one row per position it touched: A split reports the
    # old shares leaving and the new ones arriving, a rights subscription the
    # rights consumed, the cash paid and the shares received. Booked apart,
    # each side needs a gain of its own to balance and a split reads as a sale.
    # Booked together they balance on what the action actually moved.
    groups: dict[str, list[Types.CorporateAction]] = {}
    for index, action in enumerate(actions):
        if not isinstance(action, Types.CorporateAction):
            continue
        key = action.actionID or action.transactionID or str(index)
        groups.setdefault(key, []).append(action)
    return list(groups.values())


def _closes(trade: Types.Trade) -> bool:
    """Returns whether the trade reduces a position rather than opening one."""
    # `openCloseIndicator` decides, not the sign of the quantity. A sale opens
    # a position as readily as it closes one: Selling short carries `O` and
    # names no lots, buying to cover carries `C` and names the lots it covered.
    if trade.openCloseIndicator in (enums.OpenClose.CLOSE, enums.OpenClose.OPENCLOSE):
        return True
    # Except on a fractional share, where the indicator misleads. A fraction
    # arrives from a corporate action and can only ever be sold off, so a
    # negative quantity closes whatever the indicator says. Trusting it would
    # open a position at a cost no held lot carries, which cannot book.
    return trade.transactionType is enums.TradeType.FRACSHARE and (trade.quantity or _ZERO) < 0


def _lot_cost(currency: str) -> position.CostSpec:
    """Returns the spec matching the open lot that a closing trade consumes."""
    # Only the currency, so the ledger's booking method picks the lot. IBKR's
    # `cost` and `tradePrice` on a lot are the basis net of the opening
    # commission, which this importer books to an expense, so neither can equal
    # what the buy booked. The open date it reports is the one from before any
    # reorg, and a reorg here opens a fresh lot on its own date.
    return position.CostSpec(None, None, currency, None, None, False)


def _flex_date(value: str | None) -> datetime.date | None:
    """Returns the date of a Flex timestamp, `yyyyMMdd` with or without time."""
    if not value or len(value) < 8:
        return None
    try:
        return datetime.datetime.strptime(value[:8], "%Y%m%d").date()
    except ValueError:
        return None


def _decimal(value: str | None) -> decimal.Decimal:
    try:
        return decimal.Decimal(value) if value else _ZERO
    except decimal.InvalidOperation:
        return _ZERO


def _transfer_lots(filepath: str) -> dict[str, list[TransferLot]]:
    """Returns the lots of each transfer, keyed by its transaction id."""
    # Reads the XML directly, see `TransferLot` for why `ibflex` cannot. Lots
    # belong to the `<Transfer>` they follow, as everywhere else in Flex.
    try:
        root = ElementTree.parse(filepath).getroot()
    except ElementTree.ParseError:
        return {}

    lots: dict[str, list[TransferLot]] = {}
    current: list[TransferLot] | None = None
    for section in root.iter("Transfers"):
        for element in section:
            if element.tag == "Transfer":
                current = lots.setdefault(element.get("transactionID") or "", [])
            elif element.tag == "TransferLot" and current is not None:
                current.append(
                    TransferLot(
                        _decimal(element.get("quantity")),
                        _decimal(element.get("cost")),
                        element.get("currency") or "",
                        _flex_date(element.get("openDateTime")),
                    )
                )
    return lots


def _id_fields(
    statement_account: str | None,
    kind: str,
    key: str,
    date: datetime.date,
    number: decimal.Decimal,
) -> identity.IdFields:
    return identity.IdFields(
        str(date),
        identity.canonical_amount(number),
        (statement_account or "", kind, key),
    )


def _log_securities(statement: Types.FlexStatement, commodities: Commodities) -> None:
    """Reports each security, and what to declare for a missing one."""
    # Commodity directives are hand-maintained: They live in
    # `accounts.beancount`, which spans years, and an importer that emitted
    # them would re-emit them on every run. Naming a new conid after the
    # symbol it happens to carry today is a guess, so it is reported as one.
    for info in statement.SecuritiesInfo:
        symbol = info.symbol or ""
        commodity = commodities.name(symbol, info.conid)
        logger.info(
            "Security %s%s: isin %s, conid %s, %s",
            commodity,
            "" if commodity == symbol else f" (IBKR {symbol!r})",
            info.isin or "-",
            info.conid or "-",
            info.description or "",
        )
        if info.conid and not commodities.pinned(info.conid):
            logger.info(
                "Conid %s is undeclared, so it books as %s. Give it a "
                "commodity directive with %s: %r, or add the conid to the "
                "directive it belongs on.",
                info.conid,
                commodity,
                META_COMMODITY_CONIDS,
                info.conid,
            )


def _log_unread(statement: Types.FlexStatement) -> None:
    for name in _DERIVED:
        rows = getattr(statement, name, ())
        if rows:
            logger.info(
                "%s has %d rows, read as a cross check rather than imported.", name, len(rows)
            )
    for name in _UNREAD:
        rows = getattr(statement, name, ())
        if rows:
            logger.warning("%s has %d rows, which nothing reads yet.", name, len(rows))


class Importer(beangulp.Importer):
    """Reads one Flex XML file into directives."""

    def __init__(self, accounts: Accounts = DEFAULT_ACCOUNTS):
        self._accounts = accounts

    def identify(self, filepath: str) -> bool:
        if not filepath.lower().endswith(".xml"):
            return False
        try:
            with open(filepath, "rb") as f:
                head = f.read(_SNIFF_BYTES)
        except OSError:
            return False
        return _ROOT_TAG.encode() in head

    def account(self, filepath: str) -> data.Account:
        return self._accounts.cash

    def extract(self, filepath: str, existing: data.Entries) -> data.Entries:
        response = ibflex.parse(filepath)
        transfer_lots = _transfer_lots(filepath)
        commodities = Commodities(existing)
        meta = data.new_metadata(filepath, 0)

        entries: data.Entries = []
        for statement in response.FlexStatements:
            entries.extend(self._statement(statement, transfer_lots, commodities, meta))
        return entries

    def deduplicate(self, entries: data.Entries, existing: data.Entries) -> None:
        identity.mark_duplicates(entries, existing)

    def _statement(
        self,
        statement: Types.FlexStatement,
        transfer_lots: dict[str, list[TransferLot]],
        commodities: Commodities,
        meta: data.Meta,
    ) -> data.Entries:
        _log_securities(statement, commodities)
        _log_unread(statement)

        built = [self._cash_transaction(t, statement.fromDate) for t in statement.CashTransactions]
        # Corporate actions and trades can be be on the same day, but CAs create
        # the position and must be first in the ledger.
        built += [
            self._corporate_action(rows, commodities)
            for rows in _by_action(statement.CorporateActions)
        ]
        built += [
            self._trade(trade, lots, commodities)
            for trade, lots in _grouped(statement.Trades, Types.Trade, Types.Lot)
        ]
        built += [
            self._transfer(
                transfer, transfer_lots.get(transfer.transactionID or "", []), commodities
            )
            for transfer in statement.Transfers
            if isinstance(transfer, Types.Transfer)
        ]
        built += [self._sales_tax(t) for t in statement.SalesTaxes]

        pairs = [pair for pair in built if pair is not None]
        ids = identity.import_ids([fields for fields, _ in pairs])

        entries: data.Entries = []
        for (_, build), import_id in zip(pairs, ids):
            entry_meta = meta.copy()
            entry_meta[identity.META_KEY] = import_id
            entries.append(self._rounded(build(entry_meta)))
        entries.extend(self._balances(statement, meta))
        return data.sorted(entries)

    def _cash_transaction(
        self, txn: Types.CashTransaction, from_date: datetime.date | None
    ) -> _Built:
        # `settleDate` is the day the cash moved, which is what the cash report
        # counts, so it is what an assertion has to agree with. `dateTime` is
        # when IBKR recorded the item, and a withholding tax, a fee or a
        # dividend can settle days later. Dating by `dateTime` puts those in
        # the wrong period, and across a year boundary the assertion misses.
        settled = txn.settleDate or txn.reportDate or (txn.dateTime and txn.dateTime.date())
        if settled is None or txn.amount is None or not txn.currency:
            logger.warning("Skipping a cash transaction without a date, amount or currency.")
            return None

        # A later statement can report a correction (e.g. withholding tax) that
        # settled before it starts. The earlier statement's cash report never
        # counted it, so it books on its report date, no earlier than this
        # statement's first day. The id keeps the settle date, so overlapping
        # statements dedupe.
        date = settled
        if from_date and settled < from_date:
            date = max(txn.reportDate or from_date, from_date)

        key = txn.transactionID or f"{txn.type}:{txn.description}"
        fields = _id_fields(txn.accountId, "cash", key, settled, txn.amount)

        def build(meta: data.Meta) -> data.Transaction:
            if date != settled:
                meta[META_SETTLE_DATE] = settled
            if txn.transactionID:
                meta[META_TRANSACTION_ID] = txn.transactionID
            if txn.conid:
                meta[META_CONID] = txn.conid
            if txn.isin:
                meta[META_ISIN] = txn.isin

            attr = _CASH_CONTRA.get(txn.type)
            contra = getattr(self._accounts, attr) if attr else UNCATEGORIZED
            postings = [
                _posting(
                    _cash_account(self._accounts, txn.currency),
                    amount.Amount(txn.amount, txn.currency),
                ),
                _posting(contra, amount.Amount(-txn.amount, txn.currency) if attr else None),
            ]
            return data.Transaction(
                meta,
                date,
                flags.FLAG_OKAY if attr else flags.FLAG_WARNING,
                None,
                txn.description or "",
                data.EMPTY_SET,
                data.EMPTY_SET,
                postings,
            )

        return fields, build

    def _trade(
        self, trade: Types.Trade, lots: Sequence[Types.Lot], commodities: Commodities
    ) -> _Built:
        date = trade.tradeDate or (trade.dateTime.date() if trade.dateTime else None)
        if date is None or not trade.currency or trade.quantity is None:
            logger.warning("Skipping a trade without a date, currency or quantity.")
            return None
        if trade.netCash is None or trade.tradePrice is None or not trade.symbol:
            logger.warning("Skipping a trade without a price, symbol or net cash.")
            return None
        if trade.assetCategory not in _TRADEABLE:
            logger.warning(
                "Skipping a %s trade in %s, which has no posting shape yet.",
                trade.assetCategory,
                trade.symbol,
            )
            return None

        key = trade.transactionID or trade.tradeID or f"{trade.symbol}:{trade.dateTime}"
        fields = _id_fields(trade.accountId, "trade", key, date, trade.netCash)

        def build(meta: data.Meta) -> data.Transaction:
            if trade.transactionID:
                meta[META_TRANSACTION_ID] = trade.transactionID
            if trade.assetCategory is enums.AssetClass.CASH:
                postings = self._forex_postings(trade)
            else:
                commodity = commodities.name(trade.symbol, trade.conid)
                if commodity != trade.symbol:
                    meta[META_SYMBOL] = trade.symbol
                if trade.conid:
                    meta[META_CONID] = trade.conid
                postings = self._security_postings(trade, lots, commodity, date)
            return data.Transaction(
                meta,
                date,
                flags.FLAG_OKAY,
                None,
                trade.description or trade.symbol,
                data.EMPTY_SET,
                data.EMPTY_SET,
                postings,
            )

        return fields, build

    def _security_postings(
        self,
        trade: Types.Trade,
        lots: Sequence[Types.Lot],
        commodity: str,
        date: datetime.date,
    ) -> list[data.Posting]:
        """Returns the postings for one trade in a security."""
        # The quantity only says which way round the position ends up, so
        # `_closes` decides. An option that expired worthless arrives as a
        # close priced at zero, releasing the basis as the loss it is.
        accounts = self._accounts
        currency = trade.currency
        unit_cost = _unit_cost(trade.tradePrice, trade.multiplier)
        price = amount.Amount(unit_cost, currency)

        if _closes(trade):
            postings = self._closing_postings(trade, lots, commodity, price)
            # A `C;O` trade closes the named lots and opens whatever is left
            # over, which is also where a lot set that does not quite add up
            # to the trade ends up. With no lots at all there is no remainder:
            # The postings above already cover the whole quantity under FIFO.
            closed = sum((lot.quantity for lot in lots if lot.quantity is not None), _ZERO)
            residual = trade.quantity + closed if lots else _ZERO
            if residual:
                logger.warning(
                    "Trade %s closes %s %s but its lots name %s. Letting FIFO take the rest.",
                    trade.tradeID,
                    -trade.quantity,
                    commodity,
                    closed,
                )
                postings.append(
                    _posting(
                        accounts.securities,
                        amount.Amount(residual, commodity),
                        cost=_lot_cost(currency),
                        price=price,
                    )
                )
            postings.append(_posting(accounts.pnl, None))
        else:
            postings = [self._opening_posting(trade.quantity, commodity, unit_cost, currency, date)]

        commission_currency = trade.ibCommissionCurrency or currency
        postings.extend(_charge(accounts.commissions, trade.ibCommission, commission_currency))
        postings.extend(_charge(accounts.transaction_tax, trade.taxes, currency))
        postings.append(
            _posting(_cash_account(accounts, currency), amount.Amount(trade.netCash, currency))
        )
        return postings

    def _opening_posting(
        self,
        quantity: decimal.Decimal,
        commodity: str,
        unit_cost: decimal.Decimal,
        currency: str,
        date: datetime.date,
    ) -> data.Posting:
        return _posting(
            self._accounts.securities,
            amount.Amount(quantity, commodity),
            cost=position.Cost(unit_cost, currency, date, None),
        )

    def _closing_postings(
        self,
        trade: Types.Trade,
        lots: Sequence[Types.Lot],
        commodity: str,
        price: amount.Amount,
    ) -> list[data.Posting]:
        """Returns one posting per closed lot, matched on the date it opened."""
        # A closed lot states a positive quantity against the negative quantity
        # of the sale that consumed it, so the posting is its opposite. Without
        # lots there is nothing to match on and FIFO picks, which is what IBKR
        # did too, but it is worth saying so.
        if not lots:
            logger.warning(
                "Trade %s closes %s %s without naming lots. Letting FIFO choose.",
                trade.tradeID,
                -trade.quantity,
                commodity,
            )
            return [
                _posting(
                    self._accounts.securities,
                    amount.Amount(trade.quantity, commodity),
                    cost=_lot_cost(trade.currency),
                    price=price,
                )
            ]
        return [
            _posting(
                self._accounts.securities,
                amount.Amount(-lot.quantity, commodity),
                cost=_lot_cost(trade.currency),
                price=price,
            )
            for lot in lots
        ]

    def _forex_postings(self, trade: Types.Trade) -> list[data.Posting]:
        """Returns the postings for a conversion, `symbol` is `BOUGHT.SOLD`."""
        # `netCash` is zero on these, unlike on a security trade: The two legs
        # are `quantity` of the bought currency and `proceeds` of the sold one.
        # The commission sits outside both, charged in whichever currency the
        # account settles commissions in, often a third one. So it needs its
        # own cash posting, where a security trade has it inside `netCash`.
        accounts = self._accounts
        bought = trade.symbol.split(".")[0]
        quote = trade.currency
        postings = [
            _posting(
                _cash_account(accounts, bought),
                amount.Amount(trade.quantity, bought),
                price=amount.Amount(trade.tradePrice, quote),
            ),
            _posting(_cash_account(accounts, quote), amount.Amount(trade.proceeds, quote)),
        ]
        if trade.ibCommission:
            currency = trade.ibCommissionCurrency or quote
            postings.extend(_charge(accounts.commissions, trade.ibCommission, currency))
            postings.append(
                _posting(
                    _cash_account(accounts, currency),
                    amount.Amount(trade.ibCommission, currency),
                )
            )
        return postings

    def _transfer(
        self,
        transfer: Types.Transfer,
        lots: Sequence[TransferLot],
        commodities: Commodities,
    ) -> _Built:
        """A position moved in or out of the account, with its lots."""
        # The counterparty is another broker, not an account in this ledger, so
        # the other leg stays uncategorized for phase 3 to match up, the same
        # way a deposit does. Each lot keeps the basis and open date it arrived
        # with, which is what makes a later sale of it report the real gain.
        date = transfer.dateTime.date() if transfer.dateTime else transfer.date
        if date is None or transfer.quantity is None or not transfer.symbol:
            logger.warning("Skipping a transfer without a date, quantity or symbol.")
            return None

        currency = transfer.currency or (lots[0].currency if lots else "")
        key = transfer.transactionID or f"{transfer.symbol}:{date}"
        fields = _id_fields(transfer.accountId, "transfer", key, date, transfer.quantity)

        def build(meta: data.Meta) -> data.Transaction:
            if transfer.transactionID:
                meta[META_TRANSACTION_ID] = transfer.transactionID
            if transfer.isin:
                meta[META_ISIN] = transfer.isin
            commodity = commodities.name(transfer.symbol, transfer.conid)
            if commodity != transfer.symbol:
                meta[META_SYMBOL] = transfer.symbol
            if transfer.conid:
                meta[META_CONID] = transfer.conid

            postings = self._transfer_postings(transfer, lots, commodity, currency)
            if transfer.cashTransfer:
                postings.append(
                    _posting(
                        _cash_account(self._accounts, currency),
                        amount.Amount(transfer.cashTransfer, currency),
                    )
                )
            postings.append(_posting(UNCATEGORIZED, None))
            narration = transfer.description or transfer.symbol
            return data.Transaction(
                meta,
                date,
                flags.FLAG_WARNING,
                None,
                f"{transfer.type or 'Transfer'} {transfer.direction or ''}: {narration}".strip(),
                data.EMPTY_SET,
                data.EMPTY_SET,
                postings,
            )

        return fields, build

    def _transfer_postings(
        self,
        transfer: Types.Transfer,
        lots: Sequence[TransferLot],
        commodity: str,
        currency: str,
    ) -> list[data.Posting]:
        """Returns one posting per transferred lot, at its incoming basis."""
        # `transferPrice` is zero on a real transfer in, so the basis has to
        # come from the lot's own cost. Without lots there is nothing to
        # reconstruct a basis from, so the position moves at the price IBKR
        # reports and the gap, if any, shows up the first time it is sold.
        if not lots:
            logger.warning(
                "Transfer of %s %s has no lots, so it moves at transferPrice.",
                transfer.quantity,
                commodity,
            )
            price = transfer.transferPrice if transfer.transferPrice is not None else _ZERO
            date = transfer.dateTime.date() if transfer.dateTime else transfer.date
            return [
                _posting(
                    self._accounts.securities,
                    amount.Amount(transfer.quantity, commodity),
                    cost=position.Cost(price, currency, date, None),
                )
            ]

        postings = []
        for lot in lots:
            if lot.quantity > 0:
                per_unit = abs(lot.cost / lot.quantity) if lot.cost else _ZERO
                cost = position.Cost(per_unit, lot.currency or currency, lot.open_date, None)
            else:
                cost = _lot_cost(lot.currency or currency)
            postings.append(
                _posting(
                    self._accounts.securities,
                    amount.Amount(lot.quantity, commodity),
                    cost=cost,
                )
            )
        return postings

    def _sales_tax(self, tax: Types.SalesTax) -> _Built:
        """VAT charged on a service, market data most often."""
        # The only cash movement in the export that no other section restates,
        # which is why it books here rather than being read as a cross check
        # the way `TransactionTaxes` is: That one only repeats the `taxes`
        # already carried on the trade it belongs to.
        date = tax.date
        if date is None or tax.salesTax is None or not tax.currency:
            logger.warning("Skipping a sales tax without a date, amount or currency.")
            return None

        key = tax.transactionID or f"{tax.taxType}:{tax.taxableDescription}"
        fields = _id_fields(tax.accountId, "salestax", key, date, tax.salesTax)

        def build(meta: data.Meta) -> data.Transaction:
            if tax.transactionID:
                meta[META_TRANSACTION_ID] = tax.transactionID
            postings = [
                _posting(
                    _cash_account(self._accounts, tax.currency),
                    amount.Amount(tax.salesTax, tax.currency),
                ),
                _posting(
                    self._accounts.sales_tax,
                    amount.Amount(-tax.salesTax, tax.currency),
                ),
            ]
            return data.Transaction(
                meta,
                date,
                flags.FLAG_OKAY,
                None,
                f"{tax.taxType or 'Sales tax'}: {tax.taxableDescription or ''}".strip(),
                data.EMPTY_SET,
                data.EMPTY_SET,
                postings,
            )

        return fields, build

    def _corporate_action(
        self, rows: Sequence[Types.CorporateAction], commodities: Commodities
    ) -> _Built:
        """Books all legs of a reorg as one transaction, flagged for review."""
        # Every type reshapes a position differently: A merger swaps one
        # commodity for another, a spinoff divides basis across two, a rights
        # issue adds a tradeable right that later expires. IBKR reports the
        # resulting quantity, value and cash, which keeps positions and cash
        # right. Whether the basis it assigns is the one you want is a
        # judgment, so these never book clean.
        first = rows[0]
        date = first.dateTime.date() if first.dateTime else first.reportDate
        if date is None or any(row.quantity is None or not row.symbol for row in rows):
            logger.warning("Skipping a corporate action without a date, quantity or symbol.")
            return None

        quantity = sum((row.quantity for row in rows), _ZERO)
        key = first.actionID or first.transactionID or f"{first.symbol}:{date}"
        fields = _id_fields(first.accountId, "reorg", key, date, quantity)
        if len(rows) > 1 and not any(row.value for row in rows):
            logger.warning(
                "Reorg %s on %s values none of its %d legs, so the basis it moves "
                "is released to %s. A split should keep that basis, so set the "
                "cost of the arriving lot by hand.",
                key,
                date,
                len(rows),
                self._accounts.pnl,
            )

        def build(meta: data.Meta) -> data.Transaction:
            if first.actionID:
                meta[META_ACTION_ID] = first.actionID
            # Only when the action moved one position. Two rows carry two of
            # each of these, and a posting already names the commodity.
            if len(rows) == 1:
                if first.transactionID:
                    meta[META_TRANSACTION_ID] = first.transactionID
                if first.isin:
                    meta[META_ISIN] = first.isin

            postings = []
            for row in rows:
                currency = row.currency or ""
                commodity = commodities.name(row.symbol, row.conid)
                if len(rows) == 1 and commodity != row.symbol:
                    meta[META_SYMBOL] = row.symbol
                postings.extend(self._reorg_postings(row, commodity, currency, date))
                if row.proceeds:
                    postings.append(
                        _posting(
                            _cash_account(self._accounts, currency),
                            amount.Amount(row.proceeds, currency),
                        )
                    )
            # The single auto-posting. Basis released by a reorg is a gain or a
            # loss like any other, and it is what makes the entry balance.
            postings.append(_posting(self._accounts.pnl, None))
            return data.Transaction(
                meta,
                date,
                flags.FLAG_WARNING,
                None,
                first.actionDescription or first.description or first.symbol,
                data.EMPTY_SET,
                data.EMPTY_SET,
                postings,
            )

        return fields, build

    def _rounded(self, txn: data.Transaction) -> data.Transaction:
        """Writes a sub-cent residual off to `rounding`, leaving real gaps."""
        # IBKR reports an exchange rate to a fixed number of digits, so the two
        # legs of a conversion do not always meet exactly. Transactions with an
        # auto-posting are skipped: That posting already absorbs the residual,
        # and a lot being closed has no weight to compute until booking runs.
        if any(p.units is None or isinstance(p.cost, position.CostSpec) for p in txn.postings):
            return txn
        postings = []
        for pos in interpolate.compute_residual(txn.postings).get_positions():
            number = pos.units.number
            if number and abs(number) <= _ROUNDING_TOLERANCE:
                postings.append(
                    _posting(self._accounts.rounding, amount.Amount(-number, pos.units.currency))
                )
        return txn._replace(postings=txn.postings + postings) if postings else txn

    def _reorg_postings(
        self,
        action: Types.CorporateAction,
        commodity: str,
        currency: str,
        date: datetime.date,
    ) -> list[data.Posting]:
        """Arriving shares open a lot at IBKR's value, leaving ones close."""
        # `value` is the position value the reorg added or removed, so it is
        # the basis of what arrived. It is zero on a spinoff or a rights issue,
        # where IBKR hands over the shares without assigning basis to them.
        if action.quantity == 0:
            return []
        per_unit = abs(action.value / action.quantity) if action.value else _ZERO
        if action.quantity > 0:
            return [
                _posting(
                    self._accounts.securities,
                    amount.Amount(action.quantity, commodity),
                    cost=position.Cost(per_unit, currency, date, None),
                )
            ]
        return [
            _posting(
                self._accounts.securities,
                amount.Amount(action.quantity, commodity),
                cost=_lot_cost(currency),
                price=amount.Amount(per_unit, currency),
            )
        ]

    def _balances(self, statement: Types.FlexStatement, meta: data.Meta) -> data.Entries:
        """One assertion per currency, dated the day after the statement."""
        # An assertion evaluates at the start of its date, so the day after the
        # last covered day is the first moment the closing cash is true.
        entries: data.Entries = []
        for report in statement.CashReport:
            if not report.currency or report.currency == _BASE_SUMMARY:
                continue
            if report.endingCash is None or report.toDate is None:
                continue
            entries.append(
                data.Balance(
                    meta.copy(),
                    report.toDate + datetime.timedelta(days=1),
                    _cash_account(self._accounts, report.currency),
                    amount.Amount(report.endingCash, report.currency),
                    _BALANCE_TOLERANCE,
                    None,
                )
            )
        return entries
