"""Reads the config file and the files kept next to it.

The config file is TOML. It names the accounts to import into, the
`[categorize]` settings and the `[[transfers]]` hints. The rules file next to
it holds the categorization rules and the `[refunds]` table. Each reader
returns records, or raises `routing.ConfigError` with a message that says what
to fix.

The answers, the rules and the model's suggestions live next to the config
file. The `*_path` functions name them, from the config file's path.
"""

import datetime
import os
import re
import tomllib

from pybank.importer.beancount import categorize, refunds, routing, rules, transfer_hints

# The answers on transfer pairs.
_ANSWERS_FILE = "transfer-pairs.toml"

# The approved categories of open rows.
_CATEGORY_ANSWERS_FILE = "categories.toml"

_CATEGORIZE_KEYS = {"country", "cutoff", "effort", "examples", "model"}

_REFUND_KEYS = {"accounts", "labels", "prefixes"}

# The categorization rules. Optional.
_RULES_FILE = "rules.toml"

_RULE_KEYS = {"account", "book", "from", "labels", "text", "until"}

# The model's suggestions, kept so a rerun does not pay for them again.
_SUGGESTIONS_FILE = "category-suggestions.jsonl"


def answers_path(config_path: str) -> str:
    return os.path.join(os.path.dirname(config_path), _ANSWERS_FILE)


def category_answers_path(config_path: str) -> str:
    return os.path.join(os.path.dirname(config_path), _CATEGORY_ANSWERS_FILE)


def rules_path(config_path: str) -> str:
    return os.path.join(os.path.dirname(config_path), _RULES_FILE)


def suggestions_path(config_path: str) -> str:
    return os.path.join(os.path.dirname(config_path), _SUGGESTIONS_FILE)


def load(path: str) -> dict:
    """Reads a TOML file, or raises `routing.ConfigError`."""
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except OSError as err:
        raise routing.ConfigError(f"Cannot read {path}: {err}") from err
    except tomllib.TOMLDecodeError as err:
        raise routing.ConfigError(f"Cannot parse {path}: {err}") from err


def hints(config: dict) -> list[transfer_hints.Hint]:
    """Returns the `[[transfers]]` hints, or raises `routing.ConfigError`."""
    result = []
    for i, hint in enumerate(config.get("transfers", [])):
        try:
            # Banks change the case of their own text between export formats.
            text = re.compile(hint["text"], re.IGNORECASE)
            result.append(transfer_hints.Hint(hint["account"], text))
        except (KeyError, TypeError) as err:
            raise routing.ConfigError(f"[[transfers]] #{i + 1} needs account and text") from err
        except re.error as err:
            raise routing.ConfigError(f"[[transfers]] #{i + 1}: Bad text pattern: {err}") from err
    return result


def _rule(i: int, entry: dict) -> rules.Rule:
    where = f"{_RULES_FILE} rule #{i + 1}"
    unknown = sorted(set(entry) - _RULE_KEYS)
    if unknown:
        raise routing.ConfigError(f"{where}: Unknown keys: {', '.join(unknown)}")
    if "book" not in entry or "text" not in entry:
        raise routing.ConfigError(f"{where} needs book and text")
    try:
        text = re.compile(entry["text"], re.IGNORECASE)
    except TypeError as err:
        raise routing.ConfigError(f"{where}: text must be a string") from err
    except re.error as err:
        raise routing.ConfigError(f"{where}: Bad text pattern: {err}") from err
    if not isinstance(entry.get("labels", []), list):
        raise routing.ConfigError(f"{where}: labels must be a list")
    # A quoted date loads as a string, and a datetime never compares to a date.
    if any(
        type(entry.get(key, datetime.date.min)) is not datetime.date for key in ("from", "until")
    ):
        raise routing.ConfigError(f"{where}: from and until must be dates")
    return rules.Rule(
        account=entry.get("account"),
        book=entry["book"],
        end=entry.get("until"),
        labels=frozenset(entry.get("labels", [])),
        start=entry.get("from"),
        text=text,
    )


def load_rules(path: str) -> list[rules.Rule]:
    """Returns the rules in `path`, or none if the file is absent.

    Raises `routing.ConfigError` on a bad rule.
    """
    if not os.path.exists(path):
        return []
    loaded = load(path)
    unknown = sorted(set(loaded) - {"refunds", "rules"})
    if unknown:
        raise routing.ConfigError(f"Unknown {_RULES_FILE} sections: {', '.join(unknown)}")
    return [_rule(i, entry) for i, entry in enumerate(loaded.get("rules", []))]


def load_refunds(path: str) -> refunds.Config:
    """Returns the `[refunds]` table in `path`.

    Raises `routing.ConfigError` on a bad table.
    """
    if not os.path.exists(path):
        return refunds.Config()
    table = load(path).get("refunds", {})
    where = f"{_RULES_FILE} [refunds]"
    if not isinstance(table, dict):
        raise routing.ConfigError(f"{where} must be a table")
    unknown = sorted(set(table) - _REFUND_KEYS)
    if unknown:
        raise routing.ConfigError(f"{where}: Unknown keys: {', '.join(unknown)}")
    if not all(isinstance(table.get(key, []), list) for key in _REFUND_KEYS):
        raise routing.ConfigError(f"{where}: accounts, labels and prefixes must be lists")
    try:
        prefixes = tuple(re.compile(p, re.IGNORECASE) for p in table.get("prefixes", []))
    except TypeError as err:
        raise routing.ConfigError(f"{where}: prefixes must be strings") from err
    except re.error as err:
        raise routing.ConfigError(f"{where}: Bad prefix pattern: {err}") from err
    return refunds.Config(
        accounts=tuple(table.get("accounts", [])),
        labels=frozenset(table.get("labels", [])),
        prefixes=prefixes,
    )


def categorize_settings(config: dict) -> categorize.Settings:
    """Returns the `[categorize]` settings, or raises `routing.ConfigError`."""
    table = config.get("categorize", {})
    if not isinstance(table, dict):
        raise routing.ConfigError("[categorize] must be a table")
    unknown = sorted(set(table) - _CATEGORIZE_KEYS)
    if unknown:
        raise routing.ConfigError(f"[categorize]: Unknown keys: {', '.join(unknown)}")
    settings = categorize.Settings(**table)
    if not isinstance(settings.cutoff, int | float) or not isinstance(settings.examples, int):
        raise routing.ConfigError("[categorize]: cutoff must be a number, examples a whole number")
    return settings
