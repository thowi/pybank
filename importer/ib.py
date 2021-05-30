import collections
import csv
import datetime
import logging
import re

import importer
import model

DATE_TIME_FORMAT = '%Y-%m-%d, %H:%M:%S'
DATE_FORMAT = '%Y-%m-%d'

logger = logging.getLogger(__name__)


class InteractiveBrokersImporter(importer.Importer):
    """Importer for Interactive Brokers (https://www.interactivebrokers.com/).
    """

    def import_transactions(self, file=None, filename=None, currency=None):
        with importer.open_input_file(file, filename) as file:
            csv_dict = self._parse_csv_into_dict(file)

        transfers = self._get_transfers(csv_dict)
        trades = self._get_trades(csv_dict)
        withholding_tax = self._get_withholding_tax(csv_dict)
        dividends = self._get_dividends(csv_dict)
        interest = self._get_interest(csv_dict)
        other_fees = self._get_other_fees(csv_dict)

        # Collect transactions for all currencies. Later filter by currency.
        transactions_by_currency = collections.defaultdict(list)
        for category in (
                transfers, trades, withholding_tax, dividends, interest,
                other_fees):
            for category_currency, transactions in list(category.items()):
                transactions_by_currency[category_currency] += transactions

        transactions = []
        if currency in transactions_by_currency:
            transactions = transactions_by_currency[currency]
        logger.info('Found %i transactions for currency %s.' % (
                len(transactions), currency))
        return transactions

    def _parse_csv_into_dict(self, csvfile):
        reader = csv.reader(csvfile, delimiter=',', quotechar='"')
        nested_default_dict = lambda: collections.defaultdict(nested_default_dict)
        csv_dict = nested_default_dict()
        for row in reader:
            cur = csv_dict
            for i, cell in enumerate(row):
                cur = cur[cell]
                if '__rows' not in cur:
                    cur['__rows'] = []
                cur['__rows'].append(row[i+1:])
        return csv_dict

    def _get_transfers(self, csv_dict):
        logger.debug('Extracting transfers…')

        transactions_by_currency = collections.defaultdict(list)
        for row in csv_dict['Deposits & Withdrawals']['Data']['__rows']:
            currency = row[0]
            if currency.startswith('Total'):
                continue
            date = datetime.datetime.strptime(row[1], DATE_FORMAT)
            kind = row[2]
            amount = _parse_float(row[3])
            transaction = model.Payment(date, amount)
            transactions_by_currency[currency].append(transaction)

        return transactions_by_currency

    def _get_trades(self, csv_dict):
        logger.debug('Extracting trades…')

        transactions_by_currency = collections.defaultdict(list)

        # Stock and options transactions:
        st = csv_dict['Trades']['Data']['Order']['Stocks'].get('__rows', [])
        ot = csv_dict['Trades']['Data']['Order']['Equity and Index Options'] \
                .get('__rows', [])
        for row in st + ot:
            currency = row[0]
            symbol = row[1]
            date = datetime.datetime.strptime(row[2], DATE_TIME_FORMAT)
            quantity = _parse_float(row[3])
            price = _parse_float(row[4])
            proceeds = _parse_float(row[6])
            # Commissions are reported as a negative number.
            commissions =  - _parse_float(row[7])
            amount = proceeds - commissions
            if quantity >= 0:
                transaction = model.InvestmentSecurityPurchase(
                        date, symbol, quantity, price, commissions, amount)
            else:
                transaction = model.InvestmentSecuritySale(
                        date, symbol, -quantity, price, commissions, amount)
            transactions_by_currency[currency].append(transaction)

        # Forex transactions. Treated slightly differently from stocks.
        ft = csv_dict['Trades']['Data']['Order']['Forex'].get('__rows', [])
        for row in ft:
            currency = row[0]
            symbol = row[1]
            to_currency, from_currency = symbol.split('.')
            assert currency == from_currency
            date = datetime.datetime.strptime(row[2], DATE_TIME_FORMAT)
            quantity = _parse_float(row[3])
            price = _parse_float(row[4])
            proceeds = _parse_float(row[6])
            # Commissions are reported as a negative number.
            commissions =  - _parse_float(row[7])

            if quantity >= 0:
                buy_currency, sell_currency = to_currency, from_currency
                buy_amount, sell_amount = quantity, -proceeds
            else:
                buy_currency, sell_currency = from_currency, to_currency
                buy_amount, sell_amount = proceeds, -quantity
            memo = 'Buy %.2f %s, sell %.2f %s' % (
                    buy_amount, buy_currency, sell_amount, sell_currency)
            quantity = abs(quantity)
            transactions_by_currency[buy_currency].append(
                    model.InvestmentSecuritySale(
                            date, symbol, quantity, price, commissions,
                            buy_amount, memo))
            transactions_by_currency[sell_currency].append(
                    model.InvestmentSecurityPurchase(
                            date, symbol, quantity, price, 0, sell_amount,
                            memo))

            # Forex commissions are all billed to the main (CHF) account.
            # TODO: Find out the main currency/account. Don't just hardcode
            # CHF.
            transactions_by_currency['CHF'].append(model.InvestmentMiscExpense(
                    date, commissions, symbol=symbol, memo='Forex commissions'))

        return transactions_by_currency

    def _get_withholding_tax(self, csv_dict):
        logger.debug('Extracting withholding tax…')

        transactions_by_currency = collections.defaultdict(list)
        for row in csv_dict['Withholding Tax']['Data']['__rows']:
            currency = row[0]
            if currency.startswith('Total'):
                continue
            date = datetime.datetime.strptime(row[1], DATE_FORMAT)
            description = row[2]
            amount = _parse_float(row[3])
            symbol = re.split('[ (]', description)[0]
            memo = description
            if amount < 0:
                transaction = model.InvestmentMiscExpense(
                       date, amount, symbol=symbol, memo=memo)
            else:
                # Possibly a correction for previous withholding tax.
                transaction = model.InvestmentMiscIncome(
                       date, amount, symbol=symbol, memo=memo)
            transactions_by_currency[currency].append(transaction)

        return transactions_by_currency

    def _get_dividends(self, csv_dict):
        logger.debug('Extracting dividends…')

        transactions_by_currency = collections.defaultdict(list)
        for row in csv_dict['Dividends']['Data']['__rows']:
            currency = row[0]
            if currency.startswith('Total'):
                continue
            date = datetime.datetime.strptime(row[1], DATE_FORMAT)
            description = row[2]
            amount = _parse_float(row[3])
            symbol = re.split('[ (]', description)[0]
            memo = description
            transaction = model.InvestmentDividend(date, symbol, amount, memo)
            transactions_by_currency[currency].append(transaction)

        return transactions_by_currency

    def _get_interest(self, csv_dict):
        logger.debug('Extracting interest…')

        transactions_by_currency = collections.defaultdict(list)
        for row in csv_dict['Interest']['Data']['__rows']:
            currency = row[0]
            if currency.startswith('Total'):
                continue
            date = datetime.datetime.strptime(row[1], DATE_FORMAT)
            description = row[2]
            amount = _parse_float(row[3])
            memo = description
            if amount < 0:
                transaction = model.InvestmentInterestExpense(
                        date, amount, memo)
            else:
                transaction = model.InvestmentInterestIncome(date, amount, memo)
            transactions_by_currency[currency].append(transaction)

        return transactions_by_currency

    def _get_other_fees(self, csv_dict):
        logger.debug('Extracting other fees…')

        transactions_by_currency = collections.defaultdict(list)
        for row in csv_dict['Fees']['Data']['Other Fees']['__rows']:
            currency = row[0]
            date = datetime.datetime.strptime(row[1], DATE_FORMAT)
            description = row[2]
            amount = _parse_float(row[3])
            memo = description
            symbol = ''
            transaction = model.InvestmentMiscExpense(
                    date, amount, symbol=symbol, memo=memo)
            transactions_by_currency[currency].append(transaction)

        return transactions_by_currency


def _parse_float(string):
    return float(string.replace(',', ''))
