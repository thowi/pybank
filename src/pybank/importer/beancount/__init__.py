"""Beancount importers, run through beangulp."""

# Contra account during import time. Categorization replaces it later.
UNCATEGORIZED = "Expenses:Uncategorized"

# Clearing account for transfers.
IN_TRANSIT = "Assets:Transfers:InTransit"
