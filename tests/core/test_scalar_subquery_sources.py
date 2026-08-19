"""A scalar subquery in a projection has physical sources; they were being thrown away.

`_resolve_column_refs_in_expr` skips column references that sit inside a nested query, and it
is right to: those columns resolve against the *subquery's* sources, and resolving them
against the enclosing scope binds them to whatever table happens to share the alias -- the
defect PR #45 fixed.

But nothing picked them up afterwards. A scalar subquery is not a FROM-clause source, so it
never became an input of the outer scope, and the projection fell through to the constant
fallback: the whole `(SELECT COUNT(p.uid) FROM ods.pay p ...)` was recorded as a CONSTANT
value, with `ods.pay.uid` nowhere in the lineage (SUBQ-SRC-001).

In the plain shape this is silent -- no gap, `analysis_status` complete -- so a consumer
reading `lineage_fact_gaps` never learns the source was dropped.

sqlglot already builds the subquery's scope (`Scope.subquery_scopes`), so the fix connects the
projection to a scope that exists rather than inventing one. A correlated subquery still binds
its outer references outward, which is the boundary that keeps PR #45 fixed.
"""

from __future__ import annotations

from scope_lineage.scope.task_lineage import parse_task_lineage

SCHEMA = {
    "ods.acct": ["id", "dt"],
    "ods.pay": ["uid", "aid", "src", "dt"],
    "mart.t": ["id", "n"],
}


def _sources(sql: str, column: str) -> list[tuple]:
    result = parse_task_lineage(sql, task_name="t", schema=SCHEMA)
    row = next(
        (i for i in result.end_to_end_lineage
         if i.get("table") == "mart.t" and i.get("column") == column),
        None,
    )
    assert row is not None, f"no end_to_end row for {column}"
    return [
        (s.get("source_kind"), s.get("table"), s.get("column"))
        for s in row.get("value_sources") or []
        if s.get("source_kind") != "prior_table_state"
    ]


def _gaps(sql: str) -> list[dict]:
    result = parse_task_lineage(sql, task_name="t", schema=SCHEMA)
    return result.diagnostics.get("lineage_fact_gaps") or []


PROJECTION = (
    "INSERT INTO mart.t SELECT a.id AS id,\n"
    "  (SELECT COUNT(p.uid) FROM ods.pay p WHERE p.src = 'x') AS n\n"
    "FROM ods.acct a"
)


def test_a_scalar_subquery_reaches_its_physical_column():
    assert ("physical_field", "ods.pay", "uid") in _sources(PROJECTION, "n")


def test_the_whole_subquery_is_no_longer_recorded_as_a_constant():
    kinds = {kind for kind, _t, _c in _sources(PROJECTION, "n")}

    assert "generated" not in kinds


def test_the_filter_column_inside_the_subquery_is_reached_too():
    """`WHERE p.src = 'x'` decides which rows the count sees, so it is a real input."""
    columns = {column for _k, table, column in _sources(PROJECTION, "n") if table == "ods.pay"}

    assert "src" in columns


def test_a_correlated_subquery_binds_its_outer_reference_outward():
    """The inner column belongs to the subquery, the outer one to the enclosing scope."""
    sql = (
        "INSERT INTO mart.t SELECT a.id AS id,\n"
        "  (SELECT COUNT(p.uid) FROM ods.pay p WHERE p.aid = a.id) AS n\n"
        "FROM ods.acct a"
    )

    sources = _sources(sql, "n")

    assert ("physical_field", "ods.pay", "uid") in sources
    assert ("physical_field", "ods.acct", "id") in sources


def test_a_repeated_alias_does_not_capture_the_inner_column():
    """Same alias inside and out: the inner reference must still name the inner table."""
    sql = (
        "INSERT INTO mart.t SELECT p.id AS id,\n"
        "  (SELECT COUNT(p.uid) FROM ods.pay p WHERE p.src = 'x') AS n\n"
        "FROM ods.acct p"
    )

    assert ("physical_field", "ods.pay", "uid") in _sources(sql, "n")


def test_the_union_branch_shape_no_longer_reports_a_gap():
    """The real task's shape: the subquery sits in a branch of a UNION inside a CTE."""
    sql = (
        "INSERT INTO mart.t\n"
        "WITH src AS (\n"
        "  SELECT a.id AS id, (SELECT COUNT(p.uid) FROM ods.pay p WHERE p.src = 'x') AS n\n"
        "  FROM ods.acct a\n"
        "  UNION ALL\n"
        "  SELECT a.id AS id, (SELECT COUNT(p.uid) FROM ods.pay p WHERE p.src = 'y') AS n\n"
        "  FROM ods.acct a\n"
        ")\n"
        "SELECT src.id, src.n FROM src"
    )

    assert _gaps(sql) == []
    assert ("physical_field", "ods.pay", "uid") in _sources(sql, "n")


def test_a_real_constant_projection_stays_generated():
    """The constant fallback still exists for expressions that reference nothing."""
    sql = "INSERT INTO mart.t SELECT a.id AS id, 'x' AS n FROM ods.acct a"

    assert _sources(sql, "n") == [("generated", None, None)]


def test_a_subquery_in_where_does_not_become_a_value_source():
    """It decides which rows survive, not what the column's value is."""
    sql = (
        "INSERT INTO mart.t SELECT a.id AS id, 1 AS n FROM ods.acct a\n"
        "WHERE a.dt = (SELECT MAX(p.dt) FROM ods.pay p)"
    )

    kinds = {kind for kind, _t, _c in _sources(sql, "n")}

    assert kinds == {"generated"}
