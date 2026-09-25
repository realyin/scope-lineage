"""The ``table-semantics/1`` and ``semantic-confirmations/1`` JSON Schemas.

The schema answers "is the shape legal" and nothing else; whether a legal document
agrees with its packet is ``semantic validate``'s cross checks. Counts a model gets wrong
often (an empty ``sources``, a sixth question) are deliberately left to those checks so
they land in the per-item rewrite list instead of failing the whole document.
"""

from __future__ import annotations

import pytest

from scope_lineage.semantics import (
    CONFIRMATIONS_FORMAT,
    DOC_FORMAT,
    schema_errors,
)

from .table_semantics_demo import CONFIRMATIONS, example, read_json


def _errors(document) -> list[str]:
    return [f"{error['at']}: {error['message']}" for error in schema_errors(document, DOC_FORMAT)]


def test_the_example_document_is_accepted() -> None:
    assert _errors(example()) == []


def test_the_example_confirmations_are_accepted() -> None:
    assert schema_errors(read_json(CONFIRMATIONS), CONFIRMATIONS_FORMAT) == []


def _without(path: str):
    def change(document: dict) -> None:
        *parents, leaf = path.split(".")
        target = document
        for part in parents:
            target = target[int(part)] if part.isdigit() else target[part]
        del target[leaf]
    return change


def _set(path: str, value):
    def change(document: dict) -> None:
        *parents, leaf = path.split(".")
        target = document
        for part in parents:
            target = target[int(part)] if part.isdigit() else target[part]
        target[int(leaf) if leaf.isdigit() else leaf] = value
    return change


REJECTED = {
    "wrong doc_format": (_set("doc_format", "table-semantics/2"), "doc_format"),
    "catalog-qualified table": (_set("table", "spark_catalog.demo_dwd.t"), "table"),
    "summary without row": (_without("summary.row"), "summary"),
    "summary without questions": (_without("summary.questions"), "summary"),
    "unknown column category": (_set("columns.0.category", "key"), "columns[0].category"),
    "unknown source": (_set("columns.0.sources", ["guess"]), "columns[0].sources[0]"),
    "unknown confidence": (_set("columns.0.confidence", "sure"), "columns[0].confidence"),
    "unknown key": (_set("columns.0.meaning_cn", "x"), "columns[0]"),
    "watch without kind": (_without("summary.watch.0.kind"), "summary.watch[0]"),
    "bad grain source": (_set("summary.row.grain_source", "guessed"), "summary.row.grain_source"),
    "bad refresh time": (_set("summary.refresh.time", "daily"), "summary.refresh.time"),
    "bad upstream role": (_set("summary.upstream.0.role", "source"), "summary.upstream[0].role"),
    "bad rule kind": (_set("rules.0.kind", "where"), "rules[0].kind"),
    "bad rule id": (_set("rules.0.id", "rule-1"), "rules[0].id"),
    "bad question status": (_set("summary.questions.0.status", "closed"), "summary.questions[0].status"),
    "no steps": (_set("steps", []), "steps"),
    "eight steps": (_set("steps", ["s"] * 8), "steps"),
    "no task": (_without("task"), None),
}


@pytest.mark.parametrize("name", sorted(REJECTED))
def test_a_broken_document_is_rejected_at_the_broken_place(name: str) -> None:
    change, where = REJECTED[name]
    document = example()
    change(document)
    errors = schema_errors(document, DOC_FORMAT)
    assert errors, name
    if where is not None:
        assert where in [error["at"] for error in errors], errors


def test_a_list_of_tasks_is_accepted_in_place_of_one_task() -> None:
    document = example()
    document["tasks"] = [document.pop("task")]
    assert _errors(document) == []


def test_task_and_tasks_together_are_rejected() -> None:
    document = example()
    document["tasks"] = [document["task"]]
    assert _errors(document)


def test_counts_are_left_to_the_cross_checks() -> None:
    document = example()
    document["columns"][0]["sources"] = []
    document["summary"]["questions"] = [
        {"id": f"q{index}", "text": "?", "status": "open"} for index in range(1, 8)
    ]
    assert _errors(document) == []


CONFIRMATION_REJECTED = {
    "bad target": {"target": "column:x"},
    "no by": {"by": None},
    "bad date": {"date": "26/09/2026"},
}


@pytest.mark.parametrize("name", sorted(CONFIRMATION_REJECTED))
def test_a_broken_confirmation_is_rejected(name: str) -> None:
    document = read_json(CONFIRMATIONS)
    entry = document["confirmations"][0]
    for key, value in CONFIRMATION_REJECTED[name].items():
        if value is None:
            del entry[key]
        else:
            entry[key] = value
    assert schema_errors(document, CONFIRMATIONS_FORMAT)


def test_the_schemas_ship_with_the_package() -> None:
    from importlib import resources

    names = {path.name for path in resources.files("scope_lineage.schemas").iterdir()}
    assert {"table-semantics.schema.json", "semantic-confirmations.schema.json"} <= names
