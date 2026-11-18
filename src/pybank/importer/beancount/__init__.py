"""Beancount importers, run through beangulp."""

BANK_FEES = "Expenses:Fees:Bank"

# The spread of a currency conversion.
FX_FEES = "Expenses:Fees:ForeignExchange"

# Clearing account for transfers.
IN_TRANSIT = "Assets:Transfers:InTransit"

OPENING_BALANCES = "Equity:Opening-Balances"

# Contra account during import time. Categorization replaces it later.
UNCATEGORIZED = "Expenses:Uncategorized"

# The statement's own columns decided where a row went, not a person or a hint.
CATEGORY_SOURCE_STATEMENT = "statement"

# The bank's own type of a row, a hint for categorization.
META_BANK_TYPE = "bank-type"
