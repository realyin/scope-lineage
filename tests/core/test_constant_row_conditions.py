"""A row condition on a column computed only from literals is closed, not a gap (F5).

``(SELECT '2026' AS y, o FROM db.src) s JOIN db.dim d ON s.y = d.y`` reads ``s.y`` in its
join, and ``s.y`` is the literal ``'2026'``: no physical field of ``db.src`` decides which
rows match. The trace says exactly that -- no physical source, one CONSTANT source,
nothing incomplete -- but the row-condition walk read "no physical field" as "not traced"
and published ``row_condition_source_unresolved``, which made the whole task ``partial``.

A constant, like a system value, closes the trace the way ``trace_complete`` already
counts it. A column that truly cannot be traced still is a gap, and the gap now says
which condition read it.
"""

from __future__ import annotations

from scope_lineage import to_task_lineage_dict
from scope_lineage.scope.task_lineage import parse_task_lineage

SCHEMA = {
    "db.src": ["o", "t", "y"],
    "db.dim": ["y", "v"],
    "db.tgt": ["o", "v"],
}


def _parse(sql: str):
    result = parse_task_lineage(sql, task_name="t", schema=SCHEMA)
    gaps = [
        gap
        for gap in result.diagnostics["lineage_fact_gaps"]
        if gap["gap_type"] == "row_condition_source_unresolved"
    ]
    return result, gaps


def _row(result, column: str) -> dict:
    return next(
        item
        for item in result.end_to_end_lineage
        if item["table"] == "db.tgt" and item["column"] == column
    )


def test_a_join_on_a_constant_column_is_not_a_gap():
    result, gaps = _parse(
        "INSERT OVERWRITE TABLE db.tgt SELECT s.o, d.v "
        "FROM (SELECT '2026' AS y, o FROM db.src) s JOIN db.dim d ON s.y = d.y"
    )

    assert gaps == []
    assert to_task_lineage_dict(result)["analysis_status"]["status"] == "complete"
    assert _row(result, "o")["row_membership_sources"] == [{"table": "db.dim", "column": "y"}]


def test_a_where_on_a_constant_column_is_not_a_gap():
    _result, gaps = _parse(
        "INSERT OVERWRITE TABLE db.tgt SELECT s.o, 'x' AS v "
        "FROM (SELECT 'ALL' AS biz, o FROM db.src) s WHERE s.biz = 'ALL'"
    )

    assert gaps == []


def test_a_condition_on_a_system_value_is_not_a_gap():
    _result, gaps = _parse(
        "INSERT OVERWRITE TABLE db.tgt SELECT s.o, d.v "
        "FROM (SELECT CURRENT_DATE() AS y, o FROM db.src) s JOIN db.dim d ON s.y = d.y"
    )

    assert gaps == []


def test_a_union_with_a_physical_branch_keeps_its_physical_field():
    result, gaps = _parse(
        "INSERT OVERWRITE TABLE db.tgt SELECT s.o, d.v FROM ("
        "SELECT y, o FROM db.src UNION ALL SELECT '2026' AS y, o FROM db.src"
        ") s JOIN db.dim d ON s.y = d.y"
    )

    assert gaps == []
    assert {"table": "db.src", "column": "y"} in _row(result, "o")["row_membership_sources"]


def test_an_untraceable_condition_is_still_a_gap_and_says_which_condition():
    result, gaps = _parse(
        "INSERT OVERWRITE TABLE db.tgt SELECT s.o, d.v "
        "FROM (SELECT * FROM db.unknown) s JOIN db.dim d ON s.y = d.y"
    )

    [gap] = gaps
    [block] = [
        block for block in result.statement_lineage["stmt:001"]["scopes"]["ROOT"]["logic_blocks"]
        if block["logic_type"] == "join"
    ]
    assert (gap["scope_id"], gap["column"]) == ("subq:s", "y")
    assert gap["condition_scope_id"] == "ROOT"
    assert gap["logic_block_id"] == block["logic_block_id"]
    assert gap["logic_type"] == "join"
    assert gap["expression"] == block["raw_expression"]
