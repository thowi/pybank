"""A local web page to review the cached category suggestions.

`app` serves one ledger's review: The page in `static/`, the open rows
with their cached suggestions as cards, and a POST that saves answers. It
never asks the model, so a review costs nothing. A card is a group of sure
suggestions that one answer books, or one unsure row.
"""

import datetime
import pathlib

from beancount.core import data
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pybank.importer.beancount import categorize, ledger

# The page as `npm run build` in web/ at the repo root leaves it.
_PAGE = pathlib.Path(__file__).parent / "static"


class Choice(BaseModel):
    account: str
    probability: float


class Row(BaseModel):
    # The row's own account, not its category.
    account: str
    amount: str
    # The row's own choices, which a card of several rows merges.
    choices: list[Choice]
    currency: str
    date: datetime.date
    import_id: str
    narration: str
    payee: str


class Card(BaseModel):
    # The most likely comes first.
    choices: list[Choice]
    payee: str
    rows: list[Row]
    # Whether the top choice reaches the cutoff for every row.
    sure: bool


class Review(BaseModel):
    cards: list[Card]
    # The accounts an answer can name.
    categories: list[str]
    year: int | None


class Answers(BaseModel):
    # Account by import-id.
    answers: dict[str, str]


class NewCategory(BaseModel):
    account: str


def _choices(choices: tuple[categorize.Choice, ...]) -> list[Choice]:
    return [Choice(account=c.account, probability=c.probability) for c in choices]


def _row(suggestion: categorize.Suggestion) -> Row:
    txn = suggestion.txn
    units = txn.postings[0].units
    return Row(
        account=txn.postings[0].account,
        amount=str(units.number),
        choices=_choices(suggestion.choices),
        currency=units.currency,
        date=txn.date,
        import_id=suggestion.import_id,
        narration=txn.narration or "",
        payee=txn.payee or "",
    )


def _card(group: list[categorize.Suggestion], sure: bool) -> Card:
    return Card(
        choices=_choices(categorize.group_choices(group)),
        payee=group[0].payee,
        rows=[_row(s) for s in group],
        sure=sure,
    )


def app(
    entries: data.Entries,
    answers_path: str,
    cache_path: str,
    cutoff: float,
    year: int | None = None,
) -> FastAPI:
    """Returns the review app for the open rows in `entries`.

    Only rows dated in `year`, if given. Reads the answers at `answers_path`
    on each request, so a row answered elsewhere drops out on reload. A new
    category writes its `open` line into the ledger files of `entries`.
    """
    # The categories opened here join the ledger for the rest of the run.
    opened: data.Entries = []
    api = FastAPI(title="pybank review")

    def categories() -> list[data.Account]:
        return categorize.categories(entries + opened)

    def suggestions() -> list[categorize.Suggestion]:
        answers = categorize.load_answers(answers_path)
        settings = categorize.Settings(cutoff=cutoff)
        return categorize.suggest(entries, answers, None, cache_path, settings, year=year)

    @api.get("/api/review")
    def review() -> Review:
        sure, unsure = categorize.bands(suggestions(), cutoff)
        cards = [_card(g, True) for g in sure] + [_card([s], False) for s in unsure]
        return Review(cards=cards, categories=categories(), year=year)

    @api.post("/api/categories", status_code=204)
    def add_category(body: NewCategory) -> None:
        try:
            opened.append(ledger.open_account(entries + opened, body.account))
        except ValueError as err:
            raise HTTPException(422, str(err)) from err

    @api.post("/api/answers", status_code=204)
    def save(body: Answers) -> None:
        unknown = set(body.answers.values()) - set(categories())
        if unknown:
            raise HTTPException(422, f"Not a category: {', '.join(sorted(unknown))}")
        open_ids = {s.import_id for s in suggestions()}
        # An answered row may be answered again, a later answer wins.
        open_ids |= categorize.load_answers(answers_path).keys()
        missing = body.answers.keys() - open_ids
        if missing:
            raise HTTPException(422, f"Not an open row: {', '.join(sorted(missing))}")
        categorize.save_answers(answers_path, body.answers)

    if _PAGE.is_dir():
        api.mount("/", StaticFiles(directory=_PAGE, html=True), name="page")
    return api
