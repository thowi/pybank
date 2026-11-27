import json

import pytest
from beancount import loader
from fastapi.testclient import TestClient

from pybank.importer.beancount import UNCATEGORIZED, categorize
from pybank.web import review

CHECKING = "Assets:Bank:Checking"
GROCERIES = "Expenses:Living:Groceries"
TRANSIT = "Expenses:Mobility:Transit"

LEDGER = f"""\
2019-01-01 open {CHECKING}
2019-01-01 open {GROCERIES}
2019-01-01 open {TRANSIT}
2019-01-01 open {UNCATEGORIZED}
"""


def _row(import_id, text, day="2020-02-03"):
    return (
        f'{day} ! "{text}"\n  import-id: "{import_id}"\n'
        f"  {CHECKING}  -20.00 CHF\n  {UNCATEGORIZED}\n"
    )


@pytest.fixture
def files(tmp_path):
    cache = tmp_path / "suggestions.jsonl"
    lines = [
        {"choices": [[GROCERIES, 0.98], [TRANSIT, 0.02]], "import-id": "shop-1"},
        {"choices": [[GROCERIES, 0.96], [TRANSIT, 0.04]], "import-id": "shop-2"},
        {"choices": [[TRANSIT, 0.6], [GROCERIES, 0.4]], "import-id": "rail-1"},
    ]
    cache.write_text("".join(json.dumps(line) + "\n" for line in lines))
    return str(tmp_path / "answers.toml"), str(cache)


def _client(files, year=None):
    rows = [
        _row("shop-1", "Corner Shop"),
        _row("shop-2", "Corner Shop"),
        _row("rail-1", "Rail Co"),
        _row("uncached", "Unknown Co"),
        _row("old", "Corner Shop", day="2019-12-31"),
    ]
    entries, errors, _ = loader.load_string(LEDGER + "\n".join(rows))
    assert not errors
    return TestClient(review.app(entries, *files, cutoff=0.95, year=year))


def test_sure_rows_form_one_card_and_unsure_rows_their_own(files):
    body = _client(files).get("/api/review").json()

    cards = body["cards"]
    assert [[r["import_id"] for r in c["rows"]] for c in cards] == [
        ["shop-1", "shop-2"],
        ["rail-1"],
    ]
    assert [c["sure"] for c in cards] == [True, False]
    assert cards[0]["choices"][0] == {"account": GROCERIES, "probability": pytest.approx(0.97)}
    assert cards[0]["rows"][0]["amount"] == "-20.00"
    assert body["categories"] == [GROCERIES, TRANSIT]


def test_unsure_rows_that_differ_in_numbers_only_share_a_card(tmp_path):
    cache = tmp_path / "suggestions.jsonl"
    lines = [
        {"choices": [[TRANSIT, 0.7], [GROCERIES, 0.3]], "import-id": "rail-1"},
        {"choices": [[GROCERIES, 0.6], [TRANSIT, 0.4]], "import-id": "rail-2"},
    ]
    cache.write_text("".join(json.dumps(line) + "\n" for line in lines))
    rows = [_row("rail-1", "Rail Co ticket 40001"), _row("rail-2", "Rail Co ticket 40002")]
    entries, _, _ = loader.load_string(LEDGER + "\n".join(rows))
    client = TestClient(review.app(entries, str(tmp_path / "a.toml"), str(cache), cutoff=0.95))

    cards = client.get("/api/review").json()["cards"]

    assert [[r["import_id"] for r in c["rows"]] for c in cards] == [["rail-1", "rail-2"]]
    assert not cards[0]["sure"]
    assert [r["choices"][0]["account"] for r in cards[0]["rows"]] == [TRANSIT, GROCERIES]


def test_a_saved_answer_is_booked_and_drops_the_row(files):
    client = _client(files)

    response = client.post("/api/answers", json={"answers": {"rail-1": TRANSIT}})

    assert response.status_code == 204
    assert categorize.load_answers(files[0]) == {"rail-1": TRANSIT}
    cards = client.get("/api/review").json()["cards"]
    assert [r["import_id"] for c in cards for r in c["rows"]] == ["shop-1", "shop-2"]


def test_an_answered_row_can_be_answered_again(files):
    client = _client(files)
    client.post("/api/answers", json={"answers": {"rail-1": TRANSIT}})

    client.post("/api/answers", json={"answers": {"rail-1": GROCERIES}})

    assert categorize.load_answers(files[0]) == {"rail-1": GROCERIES}


@pytest.mark.parametrize(
    "answers",
    [{"rail-1": "Expenses:Unknown"}, {"uncached": GROCERIES}, {"no-such-row": GROCERIES}],
)
def test_an_unknown_category_or_row_is_refused(files, answers):
    response = _client(files).post("/api/answers", json={"answers": answers})

    assert response.status_code == 422
    assert categorize.load_answers(files[0]) == {}


def test_a_year_shows_only_its_rows(files):
    cards = _client(files, year=2019).get("/api/review").json()["cards"]

    assert cards == []


def test_a_new_category_is_opened_and_can_be_answered(files, tmp_path):
    path = tmp_path / "main.beancount"
    path.write_text(LEDGER + _row("rail-1", "Rail Co"))
    entries, _, _ = loader.load_file(str(path))
    client = TestClient(review.app(entries, *files, cutoff=0.95))
    new = "Expenses:Mobility:Bike"

    assert client.post("/api/categories", json={"account": new}).status_code == 204

    assert f"2019-01-01 open {new}\n" in path.read_text()
    assert new in client.get("/api/review").json()["categories"]
    assert client.post("/api/answers", json={"answers": {"rail-1": new}}).status_code == 204


def test_a_category_that_is_open_already_is_refused(files):
    response = _client(files).post("/api/categories", json={"account": GROCERIES})

    assert response.status_code == 422
    assert "Already in the ledger" in response.text
