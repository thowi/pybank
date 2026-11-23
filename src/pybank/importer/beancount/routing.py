from collections.abc import Mapping

from beancount.core import data
from beangulp import exceptions


# beangulp prints only the message of its own error type, and a traceback for
# any other. The message quotes what to copy into the config, so it has to stay
# readable.
class ConfigError(exceptions.Error):
    """The configuration is missing, unreadable, or does not say enough."""


class AccountRouter:
    """Maps the account identifier from a statement to a ledger account.

    Every statement names the account or card it came from. The caller
    configures a fragment of that identifier rather than the whole of it, so
    no full account number has to live in config, and an identifier the bank
    reformats between exports still matches.

    A statement naming `XXXX XXXX XXXX 1234 Gold Card` and one naming
    `XXXXXXXXXXXX1234` both route on the fragment `1234`.
    """

    def __init__(self, accounts: Mapping[str, data.Account], table: str):
        self._accounts = dict(accounts)
        # Named in every error, so the reader knows which table to edit.
        self._table = table

    def account_for(self, source_id: str) -> data.Account:
        """Returns the account for this identifier, or raises `ConfigError`."""
        matched = {f: a for f, a in self._accounts.items() if f in source_id}
        # Fragments that overlap onto one account are harmless. Fragments that
        # disagree about the account are a config the file cannot resolve.
        if len(set(matched.values())) > 1:
            raise ConfigError(
                f"Fragments {sorted(matched)} in [{self._table}] all match {source_id!r}, "
                f"and they name different accounts. Make them specific enough to tell "
                f"the accounts apart."
            )
        if not matched:
            raise ConfigError(
                f"No account configured for {source_id!r}. Add a fragment of it to [{self._table}]."
            )
        return next(iter(matched.values()))
