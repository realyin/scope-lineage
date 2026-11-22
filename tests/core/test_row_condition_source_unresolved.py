"""A predicate column no table can be proven to own is a gap, not ``UNKNOWN`` (WP3q).

``DELETE ... WHERE EXISTS (SELECT 1 FROM a JOIN b ... WHERE status = 1)`` published
``{"table": "UNKNOWN", "column": "status"}`` as a row-membership source beside
``trace_complete: true`` and no gap (C2.4-1). The schema now settles which joined table
owns a bare column when only one can; when it cannot, the row says so: a
``row_condition_source_unresolved`` gap and ``trace_complete: false``.

Every name here is synthetic.
"""

from __future__ import annotations

from scope_lineage.scope.task_lineage import parse_task_lineage

BASE = {"mart.t": ["id", "v"], "ods.a": ["id", "status"]}


def _run(sql: str, schema: dict):
    return parse_task_lineage(sql, "t", schema=schema)


def _rows(result, table: str = "mart.t") -> list[dict]:
    return [row for row in result.end_to_end_lineage if row["table"] == table]


def _gaps(result) -> list[dict]:
    return [
        gap for gap in result.diagnostics["lineage_fact_gaps"]
        if gap["gap_type"] == "row_condition_source_unresolved"
    ]


DELETE_EXISTS = (
    "DELETE FROM mart.t WHERE EXISTS (SELECT 1 FROM ods.a a JOIN ods.b b "
    "ON a.id = b.id WHERE {column} = 1);"
)


def test_the_schema_settles_a_column_only_one_joined_table_has() -> None:
    result = _run(
        DELETE_EXISTS.format(column="status"),
        {**BASE, "ods.b": ["id", "kind"]},
    )

    for row in _rows(result):
        assert {"table": "ods.a", "column": "status"} in row["row_membership_sources"]
        assert row["trace_complete"] is True
    assert _gaps(result) == []


def test_a_column_both_tables_have_is_a_gap_and_an_incomplete_row() -> None:
    result = _run(
        DELETE_EXISTS.format(column="status"),
        {**BASE, "ods.b": ["id", "status"]},
    )

    rows = _rows(result)
    assert rows
    for row in rows:
        assert row["trace_complete"] is False
        assert "row_condition_source_unresolved" in row["missing_reasons"]
    [gap] = _gaps(result)
    assert gap["column"] == "status"
    assert gap["root_impact"] is True


def test_a_table_without_metadata_cannot_settle_it_either() -> None:
    result = _run(DELETE_EXISTS.format(column="status"), BASE)

    assert all(row["trace_complete"] is False for row in _rows(result))
    assert len(_gaps(result)) == 1


def test_an_update_condition_marks_only_the_columns_it_changes() -> None:
    result = _run(
        "UPDATE mart.t SET v = 0 WHERE id IN (SELECT a.id FROM ods.a a JOIN ods.b b "
        "ON a.id = b.id WHERE status = 1);",
        {**BASE, "ods.b": ["id", "status"]},
    )

    by_column = {row["column"]: row for row in _rows(result)}
    assert by_column["v"]["trace_complete"] is False
    assert "row_condition_source_unresolved" in by_column["v"]["missing_reasons"]
    assert by_column["id"]["trace_complete"] is True
    assert len(_gaps(result)) == 1


def test_a_qualified_predicate_is_unchanged() -> None:
    result = _run(
        DELETE_EXISTS.format(column="a.status"),
        {**BASE, "ods.b": ["id", "status"]},
    )

    for row in _rows(result):
        assert {"table": "ods.a", "column": "status"} in row["row_membership_sources"]
        assert row["trace_complete"] is True
    assert _gaps(result) == []


def test_an_append_keeps_the_reason_with_the_membership_it_inherits() -> None:
    result = _run(
        DELETE_EXISTS.format(column="status")
        + " INSERT INTO TABLE mart.t SELECT id, status FROM ods.a;",
        {**BASE, "ods.b": ["id", "status"]},
    )

    rows = _rows(result)
    assert rows and all(row["trace_complete"] is False for row in rows)
    assert all(
        {"table": "UNKNOWN", "column": "status"} in row["row_membership_sources"] for row in rows
    )


def test_an_overwrite_after_it_starts_clean() -> None:
    result = _run(
        DELETE_EXISTS.format(column="status")
        + " INSERT OVERWRITE TABLE mart.t SELECT id, status FROM ods.a;",
        {**BASE, "ods.b": ["id", "status"]},
    )

    assert all(row["trace_complete"] is True for row in _rows(result))


def test_a_merge_condition_subquery_reports_the_gap() -> None:
    result = _run(
        "MERGE INTO mart.t t USING ods.a u ON t.id = u.id "
        "AND EXISTS (SELECT 1 FROM ods.a x JOIN ods.b y ON x.id = y.id WHERE status = 1) "
        "WHEN MATCHED THEN UPDATE SET t.v = u.status;",
        {**BASE, "ods.b": ["id", "status"]},
    )

    assert len(_gaps(result)) == 1
    assert all(row["trace_complete"] is False for row in _rows(result))
