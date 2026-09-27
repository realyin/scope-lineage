"""Choosing a sample of a question set: by id, by table (or concept), or both."""

from __future__ import annotations

NO_PLACE = "（无表）"
NO_TYPE = "（未分类）"


class SelectionError(ValueError):
    """An ``--ids`` or ``--only-table`` value that names nothing in the set."""


def place_of(question: dict) -> str:
    """The table a question is about, else its concept, else :data:`NO_PLACE`."""
    return question.get("table") or question.get("concept") or NO_PLACE


def type_of(question: dict) -> str:
    return question.get("type") or NO_TYPE


def select_questions(
    questions: list[dict], *, ids: list[str] | None = None, tables: list[str] | None = None
) -> list[dict]:
    """The questions both filters keep, in set order; every filter value must match.

    ``tables`` compares case-insensitively with a question's ``table`` or ``concept``.
    """
    chosen = list(questions)
    if tables:
        wanted = {table.lower() for table in tables}
        found = set().union(*(_places(q) for q in questions))
        _refuse("table/concept", [t for t in tables if t.lower() not in found])
        chosen = [q for q in chosen if _places(q) & wanted]
    if ids:
        known = {q["id"] for q in questions}
        _refuse("id", [qid for qid in ids if qid not in known])
        wanted_ids = set(ids)
        chosen = [q for q in chosen if q["id"] in wanted_ids]
    if not chosen:
        raise SelectionError("--ids and --only-table together select no question")
    return chosen


def _places(question: dict) -> frozenset:
    return frozenset(
        question[key].lower() for key in ("table", "concept") if question.get(key)
    )


def _refuse(what: str, unknown: list[str]) -> None:
    if unknown:
        raise SelectionError(f"no question in the set has {what} {', '.join(unknown)}")
