"""Suggests categories for open rows, learned from labeled rows.

A row is a transaction with an import-id and two postings: Its own posting
first, then its counter posting. It is open while the counter posting is on
`UNCATEGORIZED`, or on a suggestion that no person approved yet
(`category-source` "suggested"). It is labeled when a person chose its
category: A label from an export (`category-source` "qif"), or an approved
answer. Rule output is no label, it would only teach the rules back.

An answer is a person's approved category for one open row, keyed by its
import-id. Alike rows share the payee, the own account, the sign and the
text after masking numbers and email addresses. `suggest` asks a model for
the likely categories of each open row without an answer, once per group
of alike rows, and `bands` splits the suggestions for review.
`group_alike` groups the rows that differ in numbers and email addresses
only.
`group_choices` merges the choices of a group. `categories` lists the
accounts an answer can name.
`load_answers` reads the answers, and `save_answers` appends some.
`save_note` appends a note on rows to discuss, which books nothing.
`load_suggested` reads the top suggestion of each row. `book` is the beangulp
hook that books both. `openai_ask` makes the model call.
"""

import collections
import concurrent.futures
import functools
import json
import logging
import math
import re
import tomllib
from collections.abc import Callable, Iterable
from typing import NamedTuple

from beancount.core import amount, data, flags
from beangulp import extract

from . import CATEGORY_SOURCE_SUGGESTED, UNCATEGORIZED, identity, qif, routing
from .hooks import Group, open_slot

CATEGORY_SOURCE_MODEL = "model"

# Takes a prompt and a JSON schema, returns the model's answer in that schema.
Ask = Callable[[str, dict], dict]

logger = logging.getLogger(__name__)

# The sources of a category that a person chose.
_LABEL_SOURCES = frozenset({CATEGORY_SOURCE_MODEL, qif.CATEGORY_SOURCE_QIF})

# How many categories a suggestion offers.
_TOP = 3

# Every category starts at this probability before the stated ones are
# normalized, as in the tuning that set the cutoff. So stated probabilities
# that sum to less than 1 read as more certain.
_FLOOR = 1e-4

# A word seen with this many labels, in this share of the labeled rows, names
# no payee: A card network, a payment app, a booking text.
_NOISE_LABELS = 8
_NOISE_SHARE = 0.01

# How many words of a row's text name its payee. Noise words do not count.
_PAYEE_WORDS = 2

# Calls to the model at a time.
_WORKERS = 4

_ANSWER_SCHEMA = {
    "additionalProperties": False,
    "properties": {
        "choices": {
            "items": {
                "additionalProperties": False,
                "properties": {"label": {"type": "string"}, "probability": {"type": "number"}},
                "required": ["label", "probability"],
                "type": "object",
            },
            "type": "array",
        }
    },
    "required": ["choices"],
    "type": "object",
}

# A masked number that stands alone, maybe with a dot or comma after it.
_LONE_MARK = re.compile(r"(?<!\S)#[.,]?(?!\S)")

# A run of digits, maybe grouped: "0000 0000", "01.02.2019".
_DIGITS = re.compile(r"\d(?:[ ./:'-]?\d)*")
_EMAIL = re.compile(r"\S+@\S+")
_WORD = re.compile(r"[^\W\d_]+")


class Choice(NamedTuple):
    account: data.Account
    probability: float


class Suggestion(NamedTuple):
    """The likely categories of one open row."""

    # The most likely comes first.
    choices: tuple[Choice, ...]
    import_id: str
    # The row's first words, which group one payee's rows for review.
    payee: str
    txn: data.Transaction


class Settings(NamedTuple):
    """How to ask the model, and how sure a suggestion must be to go in bulk."""

    # Where the person lives. The prompt names it if set.
    country: str | None = None
    # The probability from which a suggestion is sure.
    cutoff: float = 0.95
    # The reasoning effort of the OpenAI model.
    effort: str | None = "low"
    # How many similar labeled rows a prompt shows.
    examples: int = 50
    # The OpenAI model.
    model: str | None = None


class _Row(NamedTuple):
    account: data.Account
    import_id: str
    # None while the row is open.
    label: data.Account | None
    txn: data.Transaction
    units: amount.Amount

    @property
    def text(self) -> str:
        return _text(self.txn)


def _text(txn: data.Transaction) -> str:
    return " ".join(filter(None, [txn.payee, txn.narration]))


class _Labels:
    """The labels that a prompt gives the categories: Numbers from 1.

    The one place to change if names suit a model better than numbers.
    """

    noun = "numbers"

    def __init__(self, categories: list[data.Account]):
        self.account = {str(i): category for i, category in enumerate(categories, start=1)}
        self.label = {category: label for label, category in self.account.items()}


def _mask(text: str) -> str:
    """Replaces e-mail addresses, and digit runs of 4 or more, by a mark."""
    text = _EMAIL.sub("EMAIL", text)
    return _DIGITS.sub(lambda m: "#" if sum(c.isdigit() for c in m[0]) >= 4 else m[0], text)


def _clean(text: str) -> str:
    """Cuts lone masked numbers and stray dots from a masked text."""
    text = _LONE_MARK.sub(" ", text)
    text = re.sub(r"(\s*\.)+\s*\.", ".", text)
    return " ".join(text.split())


def _search_text(text: str) -> str:
    return re.sub(r"\d+", "0", _clean(_mask(text)).lower())


def _words(text: str) -> list[str]:
    return _WORD.findall(_clean(_mask(text)).lower())


def _noise_words(rows: list[_Row]) -> frozenset[str]:
    """Returns the words that come with too many labels to name a payee."""
    count: collections.Counter[str] = collections.Counter()
    labels: dict[str, set[str]] = collections.defaultdict(set)
    for row in rows:
        for word in set(_words(row.text)):
            count[word] += 1
            labels[word].add(row.label)
    return frozenset(
        word
        for word, n in count.items()
        if len(labels[word]) >= _NOISE_LABELS and n >= _NOISE_SHARE * len(rows)
    )


def _payee(text: str, noise: frozenset[str]) -> str:
    words = _words(text)
    # A text of noise words only is still its own payee.
    return " ".join(([w for w in words if w not in noise] or words)[:_PAYEE_WORDS])


def _alike_key(payee: str, txn: data.Transaction) -> tuple:
    own = txn.postings[0]
    # The masked text tells a payment service's merchants apart, which the
    # payee's first words may not.
    return (payee, own.account, own.units.number > 0, _search_text(_text(txn)))


def _grams(text: str) -> list[str]:
    """Returns the letter groups of 2 to 5 inside each word, space-padded."""
    # Counted like scikit-learn's `char_wb` analyzer, which the tuning used.
    grams = []
    for word in text.split():
        padded = f" {word} "
        for n in range(2, 6):
            if len(padded) <= n:
                grams.append(padded)
                break
            grams.extend(padded[i : i + n] for i in range(len(padded) - n + 1))
    return grams


class _Index:
    """Finds the texts most like a given one, by TF-IDF cosine similarity.

    Over `_grams`, with sublinear term frequency and smoothed IDF, and only the
    groups that two texts or more share.
    """

    def __init__(self, texts: list[str]):
        # Recurring payments repeat a text, so each distinct one is scored once.
        self.rows: dict[str, list[int]] = collections.defaultdict(list)
        for i, text in enumerate(texts):
            self.rows[text].append(i)
        self.texts = list(self.rows)
        counts = [collections.Counter(_grams(text)) for text in self.texts]
        df: collections.Counter[str] = collections.Counter()
        for text, count in zip(self.texts, counts, strict=True):
            for gram in count:
                df[gram] += len(self.rows[text])
        n = len(texts)
        self.idf = {g: math.log((1 + n) / (1 + d)) + 1 for g, d in df.items() if d >= 2}
        self.postings: dict[str, list[tuple[int, float]]] = collections.defaultdict(list)
        for t, count in enumerate(counts):
            for gram, weight in self._vector(count).items():
                self.postings[gram].append((t, weight))

    def _vector(self, count: collections.Counter[str]) -> dict[str, float]:
        weights = {g: (1 + math.log(c)) * self.idf[g] for g, c in count.items() if g in self.idf}
        norm = math.sqrt(sum(w * w for w in weights.values())) or 1.0
        return {g: w / norm for g, w in weights.items()}

    def nearest(self, text: str, k: int) -> list[int]:
        """Returns up to `k` indices of texts sharing a group, best first."""
        scores: dict[int, float] = collections.defaultdict(float)
        for gram, weight in self._vector(collections.Counter(_grams(text))).items():
            for t, other in self.postings[gram]:
                scores[t] += weight * other
        result: list[int] = []
        for t in sorted(scores, key=scores.__getitem__, reverse=True):
            result.extend(self.rows[self.texts[t]][: k - len(result)])
            if len(result) == k:
                break
        return result


def _rows(entries: Iterable[data.Directive]) -> list[_Row]:
    """Returns the open rows and the labeled rows, in ledger order."""
    result = []
    for entry in entries:
        if not isinstance(entry, data.Transaction) or identity.META_KEY not in entry.meta:
            continue
        booked = open_slot(entry, None)
        if booked is None:
            continue
        if open_slot(entry) is not None:
            label = None
        elif entry.meta.get(qif.META_CATEGORY_SOURCE) in _LABEL_SOURCES:
            label = entry.postings[1].account
        else:
            continue
        result.append(
            _Row(booked.account, entry.meta[identity.META_KEY], label, entry, booked.units)
        )
    return result


def categories(entries: Iterable[data.Directive]) -> list[data.Account]:
    """Returns the open expense and income accounts, except `UNCATEGORIZED`."""
    opened = {e.account for e in entries if isinstance(e, data.Open)}
    closed = {e.account for e in entries if isinstance(e, data.Close)}
    return sorted(
        account
        for account in opened - closed - {UNCATEGORIZED}
        if account.startswith(("Expenses:", "Income:"))
    )


def _line(row: _Row) -> str:
    """Returns the row as the prompt shows it: Text, kind, amount and date."""
    side = "in" if row.units.number > 0 else "out"
    kind = "card" if row.account.startswith("Liabilities:") else "account"
    day = row.txn.date
    return " | ".join(
        [
            _clean(_mask(row.text)),
            kind,
            f"{side} {abs(row.units.number):.2f} {row.units.currency}",
            f"{day:%b %a}, day {day.day}",
            f"{day:%Y-%m-%d}",
        ]
    )


def _prompt(settings: Settings, labels: _Labels, examples: list[_Row], row: _Row) -> str:
    person = f"a person in {settings.country}" if settings.country else "a person"
    options = "\n".join(f"{label}: {account}" for label, account in labels.account.items())
    shown = "\n".join(f"{_line(e)} => {labels.label[e.label]}" for e in examples)
    return (
        f"Assign a bank transaction of {person} to a category.\n"
        f"Categories:\n{options}\n\n"
        f"Similar past transactions, labeled by the person, most similar last:\n{shown}\n\n"
        f"Transaction:\n{_line(row)}\n\n"
        f"Give the {_TOP} most likely category {labels.noun}, best first, each with the "
        "probability that it is the person's label. Follow the person's habits over "
        "general sense."
    )


def _choices(answer: dict, labels: _Labels) -> tuple[Choice, ...]:
    """Returns the top choices of an answer, normalized over all categories."""
    stated: dict[data.Account, float] = {}
    for choice in answer["choices"]:
        account = labels.account.get(str(choice["label"]).strip())
        if account:
            probability = min(max(float(choice["probability"]), _FLOOR), 1.0)
            stated[account] = max(stated.get(account, 0.0), probability)
    total = sum(stated.values()) + _FLOOR * (len(labels.account) - len(stated))
    ranked = sorted(stated.items(), key=lambda item: item[1], reverse=True)[:_TOP]
    return tuple(Choice(account, p / total) for account, p in ranked)


def _load_cache(path: str, categories: list[data.Account] | None) -> dict[str, tuple[Choice, ...]]:
    """Reads the cached choices, without the accounts no longer open.

    `None` for `categories` keeps every account.
    """
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return {}
    known = None if categories is None else set(categories)
    cache = {}
    for line in lines:
        try:
            cached = json.loads(line)
            choices = tuple(
                Choice(a, p) for a, p in cached["choices"] if known is None or a in known
            )
            import_id = cached["import-id"]
        except (KeyError, TypeError, ValueError) as err:
            raise routing.ConfigError(f"Cannot read {path}: {err}") from err
        # A row whose choices are all closed now is asked again.
        if choices:
            cache[import_id] = choices
    return cache


def suggest(
    entries: data.Entries,
    answers: dict[str, data.Account],
    ask: Ask | None,
    cache_path: str,
    settings: Settings,
    progress: Callable[[int, int], None] | None = None,
    year: int | None = None,
) -> list[Suggestion]:
    """Returns a suggestion per open row without an answer, in ledger order.

    Only rows dated in `year`, if given. The model learns from the labeled rows
    of every year and from the answers. Each prompt shows it the
    `settings.examples` labeled rows with the most similar text. The categories
    are the expense and income accounts that the ledger keeps open.

    Asks `ask` only about rows that the cache file at `cache_path` lacks, once
    per group of alike rows, and appends each answer there for each row, so a
    rerun pays for new rows only. With `ask` None, a row that the cache lacks
    gets no suggestion. Calls `progress` with the rows asked so far and the
    rows to ask, after each call.
    A row whose answer names no category gets no suggestion. An error in a
    call stops the run, and a rerun asks the rest.
    """
    labels = _Labels(categories(entries))
    labeled, pending = [], []
    for row in _rows(entries):
        label = row.label or answers.get(row.import_id)
        if label is None:
            if year is None or row.txn.date.year == year:
                pending.append(row)
        # An example whose account is closed cannot be shown by its label.
        elif label in labels.label:
            labeled.append(row._replace(label=label))
    cache = _load_cache(cache_path, list(labels.label))
    noise = _noise_words(labeled)
    todo: dict[tuple, list[_Row]] = collections.defaultdict(list)
    for row in pending:
        if row.import_id not in cache:
            todo[_alike_key(_payee(row.text, noise), row.txn)].append(row)
    if todo and ask:
        _ask_all(list(todo.values()), labeled, labels, ask, settings, cache_path, cache, progress)
    return [
        Suggestion(cache[row.import_id], row.import_id, _payee(row.text, noise), row.txn)
        for row in pending
        if cache.get(row.import_id)
    ]


def _ask_all(
    todo: list[list[_Row]],
    labeled: list[_Row],
    labels: _Labels,
    ask: Ask,
    settings: Settings,
    cache_path: str,
    cache: dict[str, tuple[Choice, ...]],
    progress: Callable[[int, int], None] | None,
) -> None:
    """Asks once per group of alike rows in `todo`, and caches each row."""
    index = _Index([_search_text(row.text) for row in labeled])
    total = sum(map(len, todo))

    def ask_one(group: list[_Row]) -> dict:
        # The newest row stands for its group.
        row = group[-1]
        near = index.nearest(_search_text(row.text), settings.examples)
        examples = [labeled[i] for i in reversed(near)]
        return ask(_prompt(settings, labels, examples, row), _ANSWER_SCHEMA)

    with (
        open(cache_path, "a", encoding="utf-8") as f,
        concurrent.futures.ThreadPoolExecutor(_WORKERS) as pool,
    ):
        futures = {pool.submit(ask_one, group): group for group in todo}
        done = 0
        try:
            for future in concurrent.futures.as_completed(futures):
                group = futures[future]
                try:
                    choices = _choices(future.result(), labels)
                # An answer can be cut off or no JSON. Any other error stops
                # the run.
                except (KeyError, TypeError, ValueError):
                    logger.warning("Malformed answer for %s.", group[-1].import_id)
                    choices = ()
                if choices:
                    for row in group:
                        cache[row.import_id] = choices
                        line = {"choices": choices, "import-id": row.import_id}
                        f.write(json.dumps(line) + "\n")
                    f.flush()
                done += len(group)
                if progress:
                    progress(done, total)
        finally:
            # A failed call fails the rest alike, a wrong key for example.
            pool.shutdown(cancel_futures=True)


def bands(
    suggestions: list[Suggestion], cutoff: float
) -> tuple[list[list[Suggestion]], list[Suggestion]]:
    """Splits suggestions into groups of sure ones and the unsure rest.

    A suggestion is sure when its top choice reaches `cutoff`. Sure ones group
    by payee and top account. The largest group comes first. The rest keep
    their order.
    """
    groups: dict[tuple[str, str], list[Suggestion]] = collections.defaultdict(list)
    unsure = []
    for suggestion in suggestions:
        top = suggestion.choices[0]
        if top.probability >= cutoff:
            groups[suggestion.payee, top.account].append(suggestion)
        else:
            unsure.append(suggestion)
    return sorted(groups.values(), key=len, reverse=True), unsure


def group_alike(suggestions: list[Suggestion]) -> list[list[Suggestion]]:
    """Groups the suggestions of alike rows, in order of their first rows."""
    groups: dict[tuple, list[Suggestion]] = collections.defaultdict(list)
    for suggestion in suggestions:
        groups[_alike_key(suggestion.payee, suggestion.txn)].append(suggestion)
    return list(groups.values())


def group_choices(group: list[Suggestion]) -> tuple[Choice, ...]:
    """Returns the top choices of a group by mean probability, best first.

    An account that a row does not list counts as 0 for that row.
    """
    total: dict[data.Account, float] = collections.defaultdict(float)
    for suggestion in group:
        for choice in suggestion.choices:
            total[choice.account] += choice.probability
    ranked = sorted(total.items(), key=lambda item: item[1], reverse=True)[:_TOP]
    return tuple(Choice(account, p / len(group)) for account, p in ranked)


def load_answers(path: str) -> dict[str, data.Account]:
    """Reads the answers file, or returns no answers if there is none yet.

    A later answer for a row replaces an earlier one.
    """
    try:
        with open(path, "rb") as f:
            content = tomllib.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as err:
        raise routing.ConfigError(f"Cannot read {path}: {err}") from err
    answers = {}
    for i, row in enumerate(content.get("row", [])):
        import_id = row.get("import-id") if isinstance(row, dict) else None
        account = row.get("account") if isinstance(row, dict) else None
        if not (isinstance(import_id, str) and isinstance(account, str)):
            raise routing.ConfigError(f"{path}: [[row]] #{i + 1} needs import-id and account")
        answers[import_id] = account
    return answers


def save_answers(path: str, answers: dict[str, data.Account]) -> None:
    """Appends answers to the answers file."""
    # Appending keeps comments and hand edits.
    with open(path, "a", encoding="utf-8") as f:
        f.writelines(
            f"\n[[row]]\nimport-id = {_toml(i)}\naccount = {_toml(a)}\n" for i, a in answers.items()
        )


def save_note(path: str, import_ids: list[str], note: str) -> None:
    """Appends a note on some rows to the answers file. It leaves them open."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n[[note]]\nimport-ids = {_toml(import_ids)}\nnote = {_toml(note)}\n")


def _toml(value: str | list[str]) -> str:
    # JSON escapes the control characters as TOML does. An ASCII-only dump
    # would write an emoji as a surrogate pair, which TOML rejects, and TOML
    # also rejects a raw DEL.
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def load_suggested(cache_path: str) -> dict[str, data.Account]:
    """Returns the top cached suggestion of each row, keyed by import-id."""
    return {i: choices[0].account for i, choices in _load_cache(cache_path, None).items()}


def _booked(txn: data.Transaction, account: data.Account, approved: bool) -> data.Transaction:
    booked, counter = txn.postings
    source = CATEGORY_SOURCE_MODEL if approved else CATEGORY_SOURCE_SUGGESTED
    meta = {**txn.meta, qif.META_CATEGORY_SOURCE: source}
    flag = flags.FLAG_OKAY if approved else flags.FLAG_WARNING
    postings = [booked, counter._replace(account=account)]
    return txn._replace(meta=meta, flag=flag, postings=postings)


def book(
    answers: dict[str, data.Account],
    suggested: dict[str, data.Account],
    extracted: list[Group],
    existing: data.Entries,
) -> list[Group]:
    """Books each open row to its answer, else to its top suggestion.

    `suggested` maps an import-id to its top suggestion, as `load_suggested`
    reads it. A suggestion keeps the row flagged `!` for review.
    Run it last, so a transfer, a rule or a refund wins over both.
    """
    if not (answers or suggested):
        return extracted
    approved = unapproved = 0
    result = []
    for filepath, entries, account, importer in extracted:
        kept = []
        for entry in entries:
            # beangulp prints a duplicate as a comment, which books nothing.
            if (
                isinstance(entry, data.Transaction)
                and not entry.meta.get(extract.DUPLICATE)
                and open_slot(entry) is not None
            ):
                import_id = entry.meta.get(identity.META_KEY)
                if import_id in answers:
                    entry = _booked(entry, answers[import_id], approved=True)
                    approved += 1
                elif import_id in suggested:
                    entry = _booked(entry, suggested[import_id], approved=False)
                    unapproved += 1
            kept.append(entry)
        result.append((filepath, kept, account, importer))
    logger.info("Booked %d rows by approved category, %d by suggestion.", approved, unapproved)
    return result


def openai_ask(model: str, effort: str | None) -> Ask:
    """Returns a call to an OpenAI model, keyed by `OPENAI_API_KEY`.

    Needs the `categorize` extra. On the first call, raises `ImportError`
    without it, and `ConfigError` without a key. Asks OpenAI not to store the
    responses (`store=False`).
    """

    # Made on the first call, so a run that asks nothing needs no key.
    @functools.cache
    def client():
        import openai

        try:
            return openai.OpenAI()
        except openai.OpenAIError as err:
            raise routing.ConfigError(str(err)) from err

    def ask(prompt: str, schema: dict) -> dict:
        reasoning = {"reasoning": {"effort": effort}} if effort else {}
        response = client().responses.create(
            input=prompt,
            max_output_tokens=4000,
            model=model,
            store=False,
            text={
                "format": {
                    "name": "answer",
                    "schema": schema,
                    "strict": True,
                    "type": "json_schema",
                }
            },
            **reasoning,
        )
        return json.loads(response.output_text)

    return ask
