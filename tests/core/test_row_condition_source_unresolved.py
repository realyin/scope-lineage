"""A predicate column no table can be proven to own is a gap, not ``UNKNOWN`` (WP3q).

``DELETE ... WHERE EXISTS (SELECT 1 FROM a JOIN b ... WHERE status = 1)`` published
``{"table": "UNKNOWN", "column": "status"}`` as a row-membership source beside
``trace_complete: true`` and no gap (C2.4-1). The schema now settles which joined table
owns a bare column when only one can; when it cannot, the field gets no name and the task
records a ``row_condition_source_unresolved`` gap -- the same as an INSERT condition.
``trace_complete`` keeps answering only whether the values were traced (docs: when a row
may be used as a complete fact); an UPDATE assignment whose value cannot be traced is a
value, so that column is incomplete.

Every name here is synthetic.
"""

from __future__ import annotations

from scope_lineage.contract import to_task_lineage_dict
from scope_lineage.contract.invariants import validate_contract_invariants
from scope_lineage.scope.task_lineage import parse_task_lineage

BASE = {"mart.t": ["id", "v"], "ods.a": ["id", "status"]}


def _run(sql: str, schema: dict):
    return parse_task_lineage(sql, "t", schema=schema)


def _rows(result, table: str = "mart.t") -> list[dict]:
    return [row for row in result.end_to_end_lineage if row["table"] == table]


def _placeholder_tables(row: dict) -> set[str]:
    tables = set()
    for key in ("row_membership_sources", "value_condition_sources"):
        tables |= {source["table"] for source in row.get(key) or []}
    return tables & {"UNKNOWN", "AMBIGUOUS"}


def _invariants(result) -> list[str]:
    return validate_contract_invariants(to_task_lineage_dict(result))


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


def test_a_column_both_tables_have_is_a_gap_not_a_name() -> None:
    result = _run(
        DELETE_EXISTS.format(column="status"),
        {**BASE, "ods.b": ["id", "status"]},
    )

    rows = _rows(result)
    assert rows
    for row in rows:
        assert _placeholder_tables(row) == set()
        assert {"table": "ods.a", "column": "id"} in row["row_membership_sources"]
        assert row["trace_complete"] is True
        assert "row_condition_source_unresolved" not in row["missing_reasons"]
    [gap] = _gaps(result)
    assert gap["column"] == "status"
    assert gap["root_impact"] is True
    assert result.analysis_status["status"] == "partial"
    assert _invariants(result) == []


def test_a_table_without_metadata_cannot_settle_it_either() -> None:
    result = _run(DELETE_EXISTS.format(column="status"), BASE)

    for row in _rows(result):
        assert _placeholder_tables(row) == set()
        assert row["trace_complete"] is True
    assert len(_gaps(result)) == 1


def test_an_update_condition_is_a_gap_and_leaves_the_values_complete() -> None:
    result = _run(
        "UPDATE mart.t SET v = 0 WHERE id IN (SELECT a.id FROM ods.a a JOIN ods.b b "
        "ON a.id = b.id WHERE status = 1);",
        {**BASE, "ods.b": ["id", "status"]},
    )

    by_column = {row["column"]: row for row in _rows(result)}
    assert _placeholder_tables(by_column["v"]) == set()
    assert {"table": "ods.a", "column": "id"} in by_column["v"]["value_condition_sources"]
    assert by_column["v"]["trace_complete"] is True
    assert "row_condition_source_unresolved" not in by_column["v"]["missing_reasons"]
    assert by_column["id"]["trace_complete"] is True
    assert len(_gaps(result)) == 1
    assert _invariants(result) == []


def test_an_update_value_no_table_can_be_proven_to_own_is_incomplete() -> None:
    """The assigned value is a value: an untraceable source leaves that column open."""
    result = _run(
        "UPDATE mart.t SET v = (SELECT MAX(status) FROM ods.a a JOIN ods.b b "
        "ON a.id = b.id) WHERE id = 1;",
        {**BASE, "ods.b": ["id", "status"]},
    )

    by_column = {row["column"]: row for row in _rows(result)}
    assert by_column["v"]["trace_complete"] is False
    assert "row_condition_source_unresolved" in by_column["v"]["missing_reasons"]
    assert by_column["id"]["trace_complete"] is True
    [gap] = _gaps(result)
    assert gap["column"] == "status"
    assert _invariants(result) == []


def test_a_qualified_predicate_is_unchanged() -> None:
    result = _run(
        DELETE_EXISTS.format(column="a.status"),
        {**BASE, "ods.b": ["id", "status"]},
    )

    for row in _rows(result):
        assert {"table": "ods.a", "column": "status"} in row["row_membership_sources"]
        assert row["trace_complete"] is True
    assert _gaps(result) == []


def test_an_append_inherits_no_placeholder_from_the_condition() -> None:
    result = _run(
        DELETE_EXISTS.format(column="status")
        + " INSERT INTO TABLE mart.t SELECT id, status FROM ods.a;",
        {**BASE, "ods.b": ["id", "status"]},
    )

    rows = _rows(result)
    assert rows and all(row["trace_complete"] is True for row in rows)
    assert all(_placeholder_tables(row) == set() for row in rows)
    assert len(_gaps(result)) == 1
    assert _invariants(result) == []


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
    for row in _rows(result):
        assert _placeholder_tables(row) == set()
        assert "row_condition_source_unresolved" not in row["missing_reasons"]
    assert _invariants(result) == []
