"""A written query's row-set and row-condition dependencies reach the task level (F4, F5).

The statement document already knew both. ``COUNT(*)`` publishes ``source_kind: rowset``
with the relation it counts, and every WHERE / JOIN condition is a logic block with its
fields. The task-level row for the same target column, though, carried neither: a count
came out with no source at all and ``trace_complete: true``, and a filtered projection
said nothing decided which rows exist -- while ``row_membership_sources`` is documented
as exactly that ("哪些字段决定该目标行是否存在"), filled only for DELETE and MERGE.

What reaches the row: the conditions of the query's own relation path -- ROOT and every
scope it reads as a relation (FROM, JOIN, UNION branch, CTE), traced to physical
columns. A scalar subquery in the SELECT list decides a value, not which rows exist, so
its WHERE stays out.
"""

from __future__ import annotations

from scope_lineage import to_task_lineage_dict, validate_lineage_document
from scope_lineage.scope.task_lineage import parse_task_lineage

SCHEMA = {
    "ods.events": ["id", "v", "keep", "ts"],
    "ods.dim": ["id", "flag"],
    "mart.out": ["id", "n"],
}


def _row(sql: str, column: str, table: str = "mart.out") -> dict:
    result = parse_task_lineage(sql, task_name="deps", schema=SCHEMA)
    return next(
        item
        for item in result.end_to_end_lineage
        if item["table"] == table and item["column"] == column
    )


# ------------------------------------------------------------------ F4: row sets


def test_a_count_depends_on_the_row_set_it_counts() -> None:
    row = _row("CREATE TABLE mart.out AS SELECT COUNT(*) AS n FROM ods.events", "n")

    assert row["value_sources"] == [
        {
            "source_kind": "rowset",
            "table": "ods.events",
            "transform": "AGGREGATE",
            "expression": "COUNT(*)",
        }
    ]
    assert row["trace_complete"] is True


def test_a_count_over_a_cte_names_the_physical_table_behind_it() -> None:
    row = _row(
        "CREATE TABLE mart.out AS WITH c AS (SELECT id FROM ods.events WHERE v > 0) "
        "SELECT COUNT(*) AS n FROM c",
        "n",
    )

    assert [(s["source_kind"], s["table"]) for s in row["value_sources"]] == [
        ("rowset", "ods.events")
    ]


def test_a_count_over_a_join_counts_both_row_sets() -> None:
    row = _row(
        "CREATE TABLE mart.out AS SELECT COUNT(*) AS n "
        "FROM ods.events e JOIN ods.dim d ON e.id = d.id",
        "n",
    )

    assert sorted(s["table"] for s in row["value_sources"]) == ["ods.dim", "ods.events"]


# ------------------------------------------------------------ F5: row conditions


def test_a_where_decides_which_rows_a_projection_writes() -> None:
    row = _row("CREATE TABLE mart.out AS SELECT id FROM ods.events WHERE keep = 1", "id")

    assert row["row_membership_sources"] == [{"table": "ods.events", "column": "keep"}]


def test_a_counts_filter_is_its_row_condition() -> None:
    row = _row(
        "CREATE TABLE mart.out AS SELECT COUNT(*) AS n FROM ods.events WHERE keep = 1", "n"
    )

    assert row["row_membership_sources"] == [{"table": "ods.events", "column": "keep"}]


def test_join_conditions_and_a_ctes_filter_reach_the_row() -> None:
    row = _row(
        "CREATE TABLE mart.out AS WITH c AS (SELECT id, keep FROM ods.events WHERE v > 0) "
        "SELECT c.id FROM c JOIN ods.dim d ON c.id = d.id AND d.flag = 'Y' "
        "WHERE c.keep = 1",
        "id",
    )

    assert sorted(
        (item["table"], item["column"]) for item in row["row_membership_sources"]
    ) == [
        ("ods.dim", "flag"),
        ("ods.dim", "id"),
        ("ods.events", "id"),
        ("ods.events", "keep"),
        ("ods.events", "v"),
    ]


def test_each_union_branchs_filter_reaches_the_row() -> None:
    row = _row(
        "CREATE TABLE mart.out AS SELECT id FROM ods.events WHERE keep = 1 "
        "UNION ALL SELECT id FROM ods.dim WHERE flag = 'Y'",
        "id",
    )

    assert sorted(
        (item["table"], item["column"]) for item in row["row_membership_sources"]
    ) == [("ods.dim", "flag"), ("ods.events", "keep")]


def test_a_scalar_subquerys_filter_decides_a_value_not_a_row() -> None:
    row = _row(
        "CREATE TABLE mart.out AS SELECT e.id, "
        "(SELECT MAX(d.flag) FROM ods.dim d WHERE d.id = 1) AS n FROM ods.events e",
        "id",
    )

    assert row["row_membership_sources"] == []


def test_an_append_adds_its_conditions_to_the_earlier_rows_ones() -> None:
    result = parse_task_lineage(
        "CREATE TABLE mart.out AS SELECT id FROM ods.events WHERE keep = 1;\n"
        "INSERT INTO mart.out SELECT id FROM ods.dim WHERE flag = 'Y'",
        task_name="deps",
        schema=SCHEMA,
    )
    row = next(
        item
        for item in result.end_to_end_lineage
        if item["table"] == "mart.out" and item["column"] == "id"
    )

    assert sorted(
        (item["table"], item["column"]) for item in row["row_membership_sources"]
    ) == [("ods.dim", "flag"), ("ods.events", "keep")]


def test_the_task_document_still_validates() -> None:
    document = to_task_lineage_dict(
        parse_task_lineage(
            "CREATE TABLE mart.out AS SELECT COUNT(*) AS n FROM ods.events WHERE keep = 1",
            task_name="deps",
            schema=SCHEMA,
        )
    )

    validate_lineage_document(document)


def test_a_condition_on_a_column_nobody_resolved_is_a_gap_not_a_name() -> None:
    """The CTE reads a table with no schema, so ``c.b`` has no physical field behind it."""
    result = parse_task_lineage(
        "CREATE TABLE mart.out AS WITH c AS (SELECT * FROM ods.unknown) "
        "SELECT c.a AS id FROM c WHERE c.b = 1",
        task_name="deps",
        schema=SCHEMA,
    )
    row = next(item for item in result.end_to_end_lineage if item["table"] == "mart.out")
    gaps = [
        gap
        for gap in result.diagnostics["lineage_fact_gaps"]
        if gap["gap_type"] == "row_condition_source_unresolved"
    ]

    assert all(item["table"] != "cte:c" for item in row["row_membership_sources"])
    assert [(gap["scope_id"], gap["column"]) for gap in gaps] == [("cte:c", "b")]
