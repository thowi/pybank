import datetime
import logging

import importer
import model

DATE_FORMAT_LONG = '%d.%m.%Y'
DATE_FORMAT_SHORT = '%d.%m.%y'

logger = logging.getLogger(__name__)


def _parse_date(date_str):
    try:
        return datetime.datetime.strptime(date_str, DATE_FORMAT_LONG)
    except ValueError:
        return datetime.datetime.strptime(date_str, DATE_FORMAT_SHORT)


class _DkbImporter(importer.Importer):
    # This base method is generic enough for both checking and credit card.
    def import_transactions(self, file=None, filename=None, currency=None):
        metadata, rows = importer.read_csv_with_header(file, filename)
        # TODO: Support different currencies.
        date_cols = 'Buchungstag', 'Buchungsdatum', 'Belegdatum'
        payee_payer_col = 'Auftraggeber / Begünstigter'
        payer_col = 'Zahlungspflichtige*r'
        payee_col = 'Zahlungsempfänger*in'
        acc_col = 'Kontonummer'
        routing_col = 'BLZ'
        amount_cols = 'Betrag (EUR)', 'Betrag (€)'
        orig_amount_col = 'Ursprünglicher Betrag'
        memo_cols = (
                'Verwendungszweck', 'Bezeichnung', 'Avisierungstext',
                'Beschreibung')

        # Get transactions.
        transactions = []
        for row in rows:
            date_str = importer.get_value(row, date_cols)
            date = _parse_date(date_str)

            amount_str = importer.get_value(row, amount_cols)
            amount = importer.parse_decimal_number(amount_str, 'de_DE')

            # Older DKB CSVs have a single column for payee and payer.
            payer_payee_str = row.get(payee_payer_col)
            if payer_payee_str:
                payer_payee = importer.normalize_text(payer_payee_str)
                if amount < 0:
                    payee = payer_payee
                else:
                    payer = payer_payee
            else:
                payer = importer.normalize_text(row.get(payer_col))
                payee = importer.normalize_text(row.get(payee_col))

            memo_str = importer.get_value(row, memo_cols)
            memo = importer.normalize_text(memo_str)

            acc = 'Account: ' + row[acc_col] if row.get(acc_col) else None
            routing = 'Routing: ' + row[routing_col] if row.get(routing_col) \
                    else None
            orig_amount = 'Original amount: ' + row[orig_amount_col] \
                    if row.get(orig_amount_col) else None
            
            memo_parts = memo, orig_amount, acc, routing
            memo = '. '.join(filter(bool, memo_parts))

            transactions.append(
                model.Payment(date, amount, payer, payee, memo=memo))
        logger.info("Imported %d transactions." % len(transactions))
        return transactions


class DkbCheckingImporter(_DkbImporter):
    """Importer for DKB checking accounts (http://www.dkb.de/).
    """

class DkbCreditCardImporter(_DkbImporter):
    """Importer for DKB credit cards (http://www.dkb.de/).
    """
