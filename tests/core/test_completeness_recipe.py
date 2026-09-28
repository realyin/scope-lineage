"""The published recipe for "may this row be used as a complete fact" runs, and is right (WP7).

A task document has five separate ways to say something is missing -- ``trace_complete``,
an unresolved row condition, a hop the fold could not resolve, a hop nobody folded, and
the task's own ``analysis_status`` -- and no field combines them (owner decision E: a
documented recipe, not a new field). The recipe is the code block in
``docs/*/task-lineage-v2.md``; this test executes that very block, so the documentation
cannot drift from what the documents mean. Both languages must carry the same code.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scope_lineage import fold_session_scoped
from scope_lineage.contract.task_lineage import to_task_lineage_dict
from scope_lineage.scope.task_lineage import parse_task_lineage

REPO = Path(__file__).resolve().parents[2]
MARKER = "<!-- recipe: usable-as-complete -->"
SCHEMA = {"ods.e": ["id", "v", "keep"], "ods.a": ["id", "flag"]}


def _recipe(language: str) -> str:
    text = (REPO / "docs" / language / "task-lineage-v2.md").read_text(encoding="utf-8")
    match = re.search(re.escape(MARKER) + r"\s*```python\n(.*?)```", text, re.S)
    assert match, f"{language} task-lineage-v2.md has no recipe block"
    return match.group(1)


def _usable():
    namespace: dict = {}
    exec(_recipe("en"), namespace)  # noqa: S102 - the documented code is the thing under test
    return namespace["usable_as_complete"]


def _rows(sql: str, fold: bool = False) -> tuple[dict, dict]:
    document = to_task_lineage_dict(parse_task_lineage(sql, task_name="recipe", schema=SCHEMA))
    if fold:
        document = fold_session_scoped(document)
    row = next(item for item in document["end_to_end_lineage"] if item["table"] == "mart.out")
    return document, row


def test_both_languages_publish_the_same_code() -> None:
    assert _recipe("zh-CN") == _recipe("en")


@pytest.mark.parametrize(
    ("sql", "fold", "usable"),
    [
        ("CREATE TABLE mart.out AS SELECT id FROM ods.e WHERE keep = 1", False, True),
        # the row's own sources are fine, but a condition names no physical field
        (
            "CREATE TABLE mart.out AS WITH c AS (SELECT * FROM ods.unknown) "
            "SELECT c.a AS id FROM c WHERE c.b = 1",
            False,
            False,
        ),
        # a hop through a temp view that nobody folded
        (
            "CREATE OR REPLACE TEMP VIEW tv AS SELECT * FROM ods.e;\n"
            "CREATE TABLE mart.out AS SELECT id FROM tv",
            False,
            False,
        ),
        # the same, folded
        (
            "CREATE OR REPLACE TEMP VIEW tv AS SELECT * FROM ods.e;\n"
            "CREATE TABLE mart.out AS SELECT id FROM tv",
            True,
            True,
        ),
        # a column two tables could own
        (
            "CREATE TABLE mart.out AS SELECT id FROM ods.e JOIN ods.a ON ods.e.id = ods.a.id",
            False,
            False,
        ),
    ],
    ids=["complete", "unresolved condition", "unfolded hop", "folded hop", "ambiguous column"],
)
def test_the_recipe_answers_each_way_a_fact_can_be_incomplete(
    sql: str, fold: bool, usable: bool
) -> None:
    document, row = _rows(sql, fold)

    assert _usable()(document, row) is usable


def test_each_criterion_decides_on_its_own() -> None:
    """Real inputs trip several criteria at once; a hand-built document trips one each."""
    usable = _usable()
    row = {
        "table": "mart.out",
        "target_state": "state:mart.out:001",
        "trace_complete": True,
        "value_sources": [{"source_kind": "physical_field", "table": "ods.e", "column": "id"}],
        "row_membership_sources": [],
    }
    document = {
        "analysis_status": {"status": "complete", "blocking_reasons": []},
        "statement_sequence": [
            {"statement_id": "stmt:001", "target_table": "mart.out", "output_state": "state:mart.out:001"}
        ],
        "diagnostics": {"lineage_fact_gaps": []},
    }
    gap = {"gap_type": "row_condition_source_unresolved", "statement_id": "stmt:001"}
    elsewhere = {"gap_type": "row_condition_source_unresolved", "statement_id": "stmt:009"}

    assert usable(document, row) is True
    assert usable({**document, "analysis_status": {"status": "partial"}}, row) is False
    assert usable(document, {**row, "trace_complete": False}) is False
    assert usable(document, {**row, "value_sources_folded": False}) is False
    assert usable(
        document,
        {**row, "row_membership_sources": [{"table": "tv", "column": "k", "session_scoped": True}]},
    ) is False
    assert usable({**document, "diagnostics": {"lineage_fact_gaps": [gap]}}, row) is False
    assert usable({**document, "diagnostics": {"lineage_fact_gaps": [elsewhere]}}, row) is True
