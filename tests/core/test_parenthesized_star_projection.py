"""A parenthesized star is still a projection, never a constant expression."""

from __future__ import annotations

from scope_lineage import parse_scope_lineage
from scope_lineage.scope.task_lineage import parse_task_lineage


SCHEMA = {
    "ods.left_events": ["event_id", "event_code"],
    "ods.right_events": ["event_id", "event_code"],
    "mart.event_rollup": ["event_id", "event_code"],
}


def _root_columns(sql: str):
    result = parse_scope_lineage(sql, "parenthesized_star", schema=SCHEMA)
    return result, result.scopes["ROOT"].columns


def test_distinct_parenthesized_star_expands_from_physical_schema() -> None:
    result, columns = _root_columns(
        "INSERT INTO mart.event_rollup "
        "SELECT DISTINCT(*) FROM ods.left_events"
    )

    assert [(column.name, column.transform) for column in columns] == [
        ("event_id", "DIRECT"),
        ("event_code", "DIRECT"),
    ]
    assert [[(source.scope, source.column) for source in column.sources] for column in columns] == [
        [("ods.left_events", "event_id")],
        [("ods.left_events", "event_code")],
    ]
    assert not result.diagnostics.warnings


def test_distinct_parenthesized_star_survives_union_and_outer_star() -> None:
    sql = (
        "INSERT INTO mart.event_rollup "
        "SELECT * FROM ("
        "SELECT DISTINCT(*) FROM ods.left_events "
        "UNION ALL "
        "SELECT DISTINCT(*) FROM ods.right_events"
        ") combined"
    )

    result = parse_task_lineage(
        sql,
        task_name="parenthesized_star_union",
        schema=SCHEMA,
    )

    assert result.analysis_status == {"status": "complete", "blocking_reasons": []}
    assert result.diagnostics["lineage_fact_gaps"] == []
    assert {
        column["column"]
        for column in result.statement_lineage["stmt:001"]["end_to_end_lineage"]
    } == {
        "event_id",
        "event_code",
    }


def test_parenthesized_named_expression_is_not_treated_as_a_star() -> None:
    _, columns = _root_columns(
        "INSERT INTO mart.event_rollup (event_id) "
        "SELECT DISTINCT(event_id) FROM ods.left_events"
    )

    assert [(column.name, column.transform) for column in columns] == [
        ("event_id", "EXPRESSION")
    ]
    assert [(source.scope, source.column) for source in columns[0].sources] == [
        ("ods.left_events", "event_id")
    ]
