"""A bare column a correlated subquery's own tables do not have resolves to the outer query.

``... FROM s.o o WHERE EXISTS (SELECT 1 FROM s.i i WHERE i.k = o.id AND flag = 1)`` with
metadata saying ``s.i`` has no ``flag`` and ``s.o`` does: Spark looks for ``flag`` in the
subquery's sources, finds none, and resolves it in the enclosing query -- ``s.o.flag``. The
resolver searched only the subquery's own sources, so with a schema the column was
``UNKNOWN`` (``column_not_found``) and the condition a ``row_condition_source_unresolved``
gap. Without a schema it stays bound to the subquery's one table, as before.

Every name here is synthetic.
"""

from __future__ import annotations

import pytest

from scope_lineage.scope.task_lineage import parse_task_lineage

SCHEMA = {"s.o": ["id", "flag"], "s.i": ["k"], "m.t": ["id"]}
EXISTS = (
    "INSERT OVERWRITE TABLE m.t SELECT o.id FROM s.o o "
    "WHERE EXISTS (SELECT {projection} FROM s.i i WHERE i.k = o.id AND {column} = 1)"
)


def _row(result) -> dict:
    [row] = [row for row in result.end_to_end_lineage if row["table"] == "m.t"]
    return row


def _gaps(result) -> list[dict]:
    return [
        gap for gap in result.diagnostics["lineage_fact_gaps"]
        if gap["gap_type"] == "row_condition_source_unresolved"
    ]


def _warning_types(result) -> set[str]:
    return {
        warning["type"]
        for statement in result.statement_lineage.values()
        for warning in statement["diagnostics"].get("warnings") or []
    }


# ``1 AS flag`` also names the inner projection like the column, which routes the WHERE
# through the alias shield (WP3a0); the answer must be the same.
@pytest.mark.parametrize("projection", ["1", "1 AS flag"])
def test_a_column_only_the_outer_table_has_resolves_there(projection: str) -> None:
    result = parse_task_lineage(
        EXISTS.format(projection=projection, column="flag"), "t", schema=SCHEMA,
    )

    row = _row(result)
    assert {"table": "s.o", "column": "flag"} in row["row_membership_sources"]
    assert all(source["table"] != "s.i" or source["column"] != "flag"
               for source in row["row_membership_sources"])
    assert _gaps(result) == []
    assert "column_not_found" not in _warning_types(result)


def test_a_column_the_inner_table_has_stays_there() -> None:
    result = parse_task_lineage(
        EXISTS.format(projection="1", column="flag"),
        "t",
        schema={**SCHEMA, "s.i": ["k", "flag"]},
    )

    row = _row(result)
    assert {"table": "s.i", "column": "flag"} in row["row_membership_sources"]
    assert {"table": "s.o", "column": "flag"} not in row["row_membership_sources"]


def test_a_column_no_table_has_is_still_not_found() -> None:
    result = parse_task_lineage(
        EXISTS.format(projection="1", column="nope"), "t", schema=SCHEMA,
    )

    assert [gap["column"] for gap in _gaps(result)] == ["nope"]


def test_without_metadata_it_stays_on_the_subquery_table() -> None:
    result = parse_task_lineage(EXISTS.format(projection="1", column="flag"), "t")

    assert {"table": "s.i", "column": "flag"} in _row(result)["row_membership_sources"]


def test_a_derived_table_does_not_reach_the_outer_query() -> None:
    """Only a subquery in an expression is correlated; a FROM-clause query is not."""
    result = parse_task_lineage(
        "INSERT OVERWRITE TABLE m.t SELECT d.k AS id FROM s.o o "
        "JOIN (SELECT k FROM s.i WHERE flag = 1) d ON d.k = o.id",
        "t",
        schema=SCHEMA,
    )

    assert {"table": "s.o", "column": "flag"} not in _row(result)["row_membership_sources"]


def test_a_bare_column_of_a_correlated_scalar_subquery_is_its_own_tables() -> None:
    """sqlglot 30.0 read ``MAX(k)`` here as ``MAX(o.i.k)``, a struct field of the outer table.

    Later versions leave ``i.k``; the CI matrix runs both, so this pins the shape.
    """
    result = parse_task_lineage(
        "INSERT OVERWRITE TABLE m.t "
        "SELECT (SELECT MAX(k) FROM s.i i WHERE i.k = o.id) AS id FROM s.o o",
        "t",
        schema=SCHEMA,
    )

    fields = {(source["table"], source["column"]) for source in _row(result)["value_sources"]}
    assert ("s.i", "k") in fields
    assert ("s.o", "i") not in fields


# The DELETE / UPDATE / MERGE predicate path resolves columns from the AST on its own
# (``_expression_field_sources``) and had the same blind spot in a sharper form: a bare
# column in a one-table subquery was given to that table without asking the schema, so
# ``flag`` was published as ``s.i.flag`` -- a field metadata says does not exist -- beside
# ``trace_complete: true``.
DELETE_SCHEMA = {"s.i": ["k"], "s.j": ["k", "kind"], "m.t": ["id", "flag"]}
DELETE_EXISTS = (
    "DELETE FROM m.t WHERE EXISTS (SELECT 1 FROM {tables} WHERE i.k = t.id AND {column} = 1)"
)


def _membership(result) -> list[dict]:
    rows = [row for row in result.end_to_end_lineage if row["table"] == "m.t"]
    assert rows
    return rows[0]["row_membership_sources"]


def test_a_delete_condition_column_only_the_target_has_is_the_target() -> None:
    result = parse_task_lineage(
        DELETE_EXISTS.format(tables="s.i i", column="flag"), "t", schema=DELETE_SCHEMA,
    )

    sources = _membership(result)
    assert {"table": "m.t", "column": "flag"} in sources
    assert {"table": "s.i", "column": "flag"} not in sources
    assert _gaps(result) == []


def test_a_delete_condition_reaches_through_a_join_whose_tables_both_lack_it() -> None:
    result = parse_task_lineage(
        DELETE_EXISTS.format(tables="s.i i JOIN s.j j ON i.k = j.k", column="flag"),
        "t",
        schema=DELETE_SCHEMA,
    )

    assert {"table": "m.t", "column": "flag"} in _membership(result)
    assert _gaps(result) == []


def test_a_delete_condition_column_the_subquery_table_has_stays_there() -> None:
    result = parse_task_lineage(
        DELETE_EXISTS.format(tables="s.i i", column="flag"),
        "t",
        schema={**DELETE_SCHEMA, "s.i": ["k", "flag"]},
    )

    sources = _membership(result)
    assert {"table": "s.i", "column": "flag"} in sources
    assert {"table": "m.t", "column": "flag"} not in sources


def test_a_delete_condition_column_no_table_has_is_a_gap() -> None:
    result = parse_task_lineage(
        DELETE_EXISTS.format(tables="s.i i", column="nope"), "t", schema=DELETE_SCHEMA,
    )

    assert all(source["column"] != "nope" for source in _membership(result))
    assert [gap["column"] for gap in _gaps(result)] == ["nope"]


def test_a_delete_condition_without_metadata_stays_on_the_subquery_table() -> None:
    """``s.i`` has no metadata: the subquery's one table may have it, and Spark looks there first."""
    result = parse_task_lineage(
        DELETE_EXISTS.format(tables="s.i i", column="flag"),
        "t",
        schema={"m.t": DELETE_SCHEMA["m.t"]},
    )

    assert {"table": "s.i", "column": "flag"} in _membership(result)
