import datetime
import re

import pytest
from beancount import loader
from beancount.core import amount, data, flags
from beangulp import extract

from pybank.importer.beancount import (
    CATEGORY_SOURCE_SUGGESTED,
    UNCATEGORIZED,
    categorize,
    postfinance,
    qif,
    routing,
)

CHECKING = "Assets:Bank:Checking"
GROCERIES = "Expenses:Living:Groceries"
TRANSIT = "Expenses:Mobility:Transit"

OPENS = f"""\
2020-01-01 open {CHECKING}
2020-01-01 open {GROCERIES}
2020-01-01 open {TRANSIT}
2020-01-01 open Income:Other
2020-01-01 open {UNCATEGORIZED}
"""


def _row(import_id, text, contra=UNCATEGORIZED, source=None, day="2020-02-03", number="-20.00"):
    meta = f'\n  category-source: "{source}"' if source else ""
    flag = "*" if contra != UNCATEGORIZED else "!"
    return (
        f'{day} {flag} "{text}"\n  import-id: "{import_id}"{meta}\n'
        f"  {CHECKING}  {number} CHF\n  {contra}\n"
    )


def _ledger(*rows):
    entries, errors, _ = loader.load_string(OPENS + "\n".join(rows))
    assert not errors
    return entries


LABELED = [
    _row("shop-1", "Corner Shop Main Street", GROCERIES, "qif"),
    _row("shop-2", "Corner Shop Station", GROCERIES, "qif"),
    _row("rail-1", "Rail Co Ticket", TRANSIT, "qif"),
]


def _fake(picks):
    """Returns a model that answers by the open row's text, and its prompts."""
    prompts = []

    def ask(prompt, schema):
        prompts.append(prompt)
        numbers = {account: n for n, account in re.findall(r"^(\d+): (\S+)$", prompt, re.MULTILINE)}
        row = prompt.split("Transaction:\n")[1].splitlines()[0]
        choices = next(choices for text, choices in picks.items() if text in row)
        return {"choices": [{"label": numbers.get(a, a), "probability": p} for a, p in choices]}

    return ask, prompts


def _suggest(tmp_path, entries, picks, answers=None, settings=None):
    ask, prompts = _fake(picks)
    cache = str(tmp_path / "suggestions.jsonl")
    settings = settings or categorize.Settings()
    return categorize.suggest(entries, answers or {}, ask, cache, settings), prompts


def test_each_open_row_gets_its_choices_best_first(tmp_path):
    entries = _ledger(*LABELED, _row("open-1", "Corner Shop Market"))
    picks = {"Corner Shop": [(TRANSIT, 0.1), (GROCERIES, 0.9)]}

    (suggestion,), _ = _suggest(tmp_path, entries, picks)

    assert suggestion.import_id == "open-1"
    assert [c.account for c in suggestion.choices] == [GROCERIES, TRANSIT]
    # Normalized over every category. The unnamed one gets the floor.
    assert suggestion.choices[0].probability == pytest.approx(0.9 / (1.0 + 1e-4))


def test_the_prompt_numbers_the_categories_and_shows_the_nearest_example_last(tmp_path):
    entries = _ledger(*LABELED, _row("open-1", "Corner Shop Station"))

    _, (prompt,) = _suggest(tmp_path, entries, {"Corner": [(GROCERIES, 1.0)]})

    assert f"1: {GROCERIES}\n2: {TRANSIT}\n3: Income:Other\n" in prompt
    examples = prompt.split("most similar last:\n")[1].split("\n\n")[0].splitlines()
    assert examples[-1].startswith("Corner Shop Station | account | out 20.00 CHF")
    assert examples[-1].endswith("=> 1")
    assert "a person to a category" in prompt


def test_the_prompt_names_the_configured_country(tmp_path):
    entries = _ledger(*LABELED, _row("open-1", "Corner Shop"))
    settings = categorize.Settings(country="Utopia")

    _, (prompt,) = _suggest(tmp_path, entries, {"Corner": [(GROCERIES, 1.0)]}, settings=settings)

    assert "a person in Utopia" in prompt


def test_rule_output_is_no_example(tmp_path):
    entries = _ledger(
        _row("rule-1", "Corner Shop Rule", GROCERIES, "rule"), _row("open-1", "Corner Shop")
    )

    _, (prompt,) = _suggest(tmp_path, entries, {"Corner": [(GROCERIES, 1.0)]})

    assert "Corner Shop Rule" not in prompt


def test_an_answered_row_is_an_example_and_not_asked(tmp_path):
    entries = _ledger(*[_row(f"open-{i}", f"Corner Shop {i}") for i in range(3)])
    answers = {"open-0": GROCERIES, "open-1": GROCERIES}

    suggestions, (prompt,) = _suggest(tmp_path, entries, {"Corner": [(GROCERIES, 1.0)]}, answers)

    assert [s.import_id for s in suggestions] == ["open-2"]
    assert "Corner Shop 0 | account" in prompt


def test_a_rerun_asks_only_about_new_rows(tmp_path):
    picks = {"Corner": [(GROCERIES, 1.0)], "Rail": [(TRANSIT, 1.0)]}
    _suggest(tmp_path, _ledger(*LABELED, _row("open-1", "Corner Shop")), picks)

    entries = _ledger(*LABELED, _row("open-1", "Corner Shop"), _row("open-2", "Rail Co"))
    suggestions, prompts = _suggest(tmp_path, entries, picks)

    assert [s.choices[0].account for s in suggestions] == [GROCERIES, TRANSIT]
    assert len(prompts) == 1


def test_without_ask_only_cached_rows_get_a_suggestion(tmp_path):
    picks = {"Corner": [(GROCERIES, 1.0)]}
    _suggest(tmp_path, _ledger(*LABELED, _row("open-1", "Corner Shop")), picks)
    entries = _ledger(*LABELED, _row("open-1", "Corner Shop"), _row("open-2", "Rail Co"))
    cache = str(tmp_path / "suggestions.jsonl")

    suggestions = categorize.suggest(entries, {}, None, cache, categorize.Settings())

    assert [s.import_id for s in suggestions] == ["open-1"]


def test_a_year_asks_and_returns_only_its_rows(tmp_path):
    entries = _ledger(
        *LABELED, _row("open-1", "Corner Shop"), _row("open-2", "Rail Co", day="2021-02-03")
    )
    picks = {"Corner": [(GROCERIES, 1.0)], "Rail": [(TRANSIT, 1.0)]}
    ask, prompts = _fake(picks)
    cache = str(tmp_path / "suggestions.jsonl")

    suggestions = categorize.suggest(entries, {}, ask, cache, categorize.Settings(), year=2021)

    assert [s.import_id for s in suggestions] == ["open-2"]
    assert len(prompts) == 1
    assert "Rail Co Ticket" in prompts[0]


def test_a_cache_line_that_is_no_json_is_reported(tmp_path):
    path = tmp_path / "suggestions.jsonl"
    path.write_text('{"import-id": "a", "choi\n', encoding="utf-8")

    with pytest.raises(routing.ConfigError, match="Cannot read"):
        categorize.load_suggested(str(path))


def test_a_suggested_row_is_open_and_no_example(tmp_path):
    entries = _ledger(
        *LABELED,
        _row("open-1", "Corner Shop Booked", GROCERIES, CATEGORY_SOURCE_SUGGESTED),
        _row("open-2", "Corner Shop"),
    )

    suggestions, prompts = _suggest(tmp_path, entries, {"Corner": [(GROCERIES, 1.0)]})

    assert [s.import_id for s in suggestions] == ["open-1", "open-2"]
    assert all("Corner Shop Booked |" not in p.split("Transaction:")[0] for p in prompts)


def test_load_suggested_reads_the_top_choice(tmp_path):
    entries = _ledger(*LABELED, _row("open-1", "Corner Shop"))
    _suggest(tmp_path, entries, {"Corner": [(TRANSIT, 0.2), (GROCERIES, 0.8)]})

    suggested = categorize.load_suggested(str(tmp_path / "suggestions.jsonl"))

    assert suggested == {"open-1": GROCERIES}


def test_an_answer_that_names_no_category_gives_no_suggestion(tmp_path):
    entries = _ledger(*LABELED, _row("open-1", "Corner Shop"))

    suggestions, _ = _suggest(tmp_path, entries, {"Corner": [("Expenses:Unknown", 0.9)]})

    assert suggestions == []


def test_a_row_whose_answer_is_no_json_gets_no_suggestion_and_the_rest_do(tmp_path):
    entries = _ledger(*LABELED, _row("open-1", "Corner Shop"), _row("open-2", "Rail Co"))
    ask, _ = _fake({"Rail": [(TRANSIT, 1.0)]})

    def flaky(prompt, schema):
        if "Transaction:\nCorner" in prompt:
            raise ValueError("no JSON")
        return ask(prompt, schema)

    cache = str(tmp_path / "suggestions.jsonl")
    suggestions = categorize.suggest(entries, {}, flaky, cache, categorize.Settings())

    assert [s.import_id for s in suggestions] == ["open-2"]


def test_a_cached_row_whose_choices_are_all_closed_is_asked_again(tmp_path):
    rows = [*LABELED, _row("open-1", "Corner Shop")]
    _suggest(tmp_path, _ledger(*rows), {"Corner": [("Income:Other", 1.0)]})
    closed = "2020-01-02 close Income:Other\n"

    (suggestion,), prompts = _suggest(
        tmp_path, _ledger(*rows, closed), {"Corner": [(GROCERIES, 1.0)]}
    )

    assert suggestion.choices[0].account == GROCERIES
    assert len(prompts) == 1


def test_clean_cuts_a_lone_masked_number_and_keeps_one_inside_a_word():
    text = categorize._clean(categorize._mask("Shop-123456 Town 123456. Ref 1234"))

    assert text == "Shop-# Town Ref"


def test_the_payee_leaves_out_words_seen_with_many_labels():
    labels = [f"Expenses:Label{i}" for i in range(8)]
    opens = "".join(f"2020-01-01 open {label}\n" for label in labels)
    rows = [
        _row(f"id-{i}", f"Cardpay Merchant{i} Town", label, "qif") for i, label in enumerate(labels)
    ]
    entries, _, _ = loader.load_string(OPENS + opens + "\n".join(rows))

    noise = categorize._noise_words(categorize._rows(entries))

    assert categorize._payee("Cardpay Corner Shop Town", noise) == "corner shop"
    assert categorize._payee("Cardpay Town", noise) == "cardpay town"


def test_sure_suggestions_group_by_payee_and_account():
    def suggestion(import_id, payee, account, probability):
        choices = (categorize.Choice(account, probability),)
        return categorize.Suggestion(choices, import_id, payee, None)

    shop = [suggestion(f"shop-{i}", "corner shop", GROCERIES, 0.97) for i in range(2)]
    rail = suggestion("rail", "rail co", TRANSIT, 0.99)
    unsure = suggestion("other", "corner shop", GROCERIES, 0.5)

    groups, rest = categorize.bands([shop[0], rail, unsure, shop[1]], 0.95)

    assert groups == [shop, [rail]]
    assert rest == [unsure]


def test_group_choices_rank_accounts_by_mean_probability():
    def suggestion(*choices):
        return categorize.Suggestion(tuple(categorize.Choice(*c) for c in choices), "", "", None)

    group = [
        suggestion((GROCERIES, 0.6), (TRANSIT, 0.4)),
        suggestion((GROCERIES, 0.8), ("Income:Other", 0.2)),
    ]

    assert categorize.group_choices(group) == (
        categorize.Choice(GROCERIES, pytest.approx(0.7)),
        categorize.Choice(TRANSIT, pytest.approx(0.2)),
        categorize.Choice("Income:Other", pytest.approx(0.1)),
    )


def test_char_groups_count_a_short_word_once():
    assert categorize._grams("a bc") == [" a", "a ", " a ", " b", "bc", "c ", " bc", "bc ", " bc "]


def test_answers_round_trip_and_a_later_answer_wins(tmp_path):
    path = str(tmp_path / "categories.toml")

    categorize.save_answers(path, {"a": GROCERIES, "b": TRANSIT})
    categorize.save_answers(path, {"a": TRANSIT})

    assert categorize.load_answers(path) == {"a": TRANSIT, "b": TRANSIT}


def test_no_answers_file_means_no_answers(tmp_path):
    assert categorize.load_answers(str(tmp_path / "categories.toml")) == {}


def test_an_answer_without_an_account_is_reported(tmp_path):
    path = tmp_path / "categories.toml"
    path.write_text('[[row]]\nimport-id = "a"\n', encoding="utf-8")

    with pytest.raises(routing.ConfigError, match="#1"):
        categorize.load_answers(str(path))


def _txn(import_id, contra=UNCATEGORIZED, duplicate=False):
    meta = {"import-id": import_id, extract.DUPLICATE: duplicate}
    units = amount.Amount(data.Decimal("-20"), "CHF")
    postings = [
        data.Posting(CHECKING, units, None, None, None, None),
        data.Posting(contra, None, None, None, None, None),
    ]
    day = datetime.date(2024, 3, 4)
    return data.Transaction(
        meta, day, flags.FLAG_WARNING, None, "Shop", data.EMPTY_SET, data.EMPTY_SET, postings
    )


def _book(answers, entries, suggested=None):
    groups = [("statement.csv", entries, CHECKING, postfinance.CheckingImporter({}))]
    return categorize.book(answers, suggested or {}, groups, [])[0][1]


def test_the_hook_books_an_open_row_to_its_answer():
    (booked,) = _book({"a": GROCERIES}, [_txn("a")], {"a": TRANSIT})

    assert booked.postings[1].account == GROCERIES
    assert booked.flag == flags.FLAG_OKAY
    assert booked.meta[qif.META_CATEGORY_SOURCE] == categorize.CATEGORY_SOURCE_MODEL


def test_the_hook_books_a_row_without_an_answer_to_its_suggestion_for_review():
    (booked,) = _book({}, [_txn("a")], {"a": TRANSIT})

    assert booked.postings[1].account == TRANSIT
    assert booked.flag == flags.FLAG_WARNING
    assert booked.meta[qif.META_CATEGORY_SOURCE] == CATEGORY_SOURCE_SUGGESTED


def test_the_hook_leaves_booked_rows_duplicates_and_rows_without_an_answer():
    rows = [_txn("a", contra=TRANSIT), _txn("b", duplicate=True), _txn("c")]

    assert _book({"a": GROCERIES, "b": GROCERIES}, rows, {"b": GROCERIES}) == rows
