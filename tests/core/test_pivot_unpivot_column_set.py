"""PIVOT / UNPIVOT produce Spark's column set (audit 1.7).

A PIVOT keeps every column of the pivoted relation that neither the aggregates nor the
FOR clause read -- they are its implicit grouping columns -- and adds one column per IN
value (per IN value and aggregate, named ``<value>_<alias>``, when there are several
aggregates). Each pivoted column is an aggregate that also depends on the FOR column,
since that column decides which rows feed it. Only the IN-value columns were produced,
marked DIRECT, without the FOR column, and with one column for several aggregates.

An UNPIVOT is the reverse: the relation's columns outside the IN list, then the name
column (whose values are the IN items' names, written by the statement), then the value
column read from the IN columns. It was not recognised at all: ``SELECT *`` over it
silently returned the original table's columns.
"""

from __future__ import annotations

import pytest

from scope_lineage import parse_scope_lineage, to_dict

SCHEMA = {
    "s.sales": ["dept", "quarter", "amt", "cnt"],
    "s.wide": ["id", "q1", "q2"],
}
PIVOTED = (
    "(SELECT dept, quarter, amt FROM s.sales) "
    "PIVOT (SUM(amt) FOR quarter IN ('Q1', 'Q2'))"
)


def _lineage(sql: str) -> dict:
    return to_dict(parse_scope_lineage(sql, "pivot", schema=SCHEMA))


def _columns(lineage: dict, scope_id: str = "ROOT") -> dict[str, dict]:
    return {column["name"]: column for column in lineage["scopes"][scope_id]["columns"]}


def _physical(lineage: dict, column: str) -> set[str]:
    trace = next(item for item in lineage["end_to_end_lineage"] if item["column"] == column)
    return {source["column"] for source in trace["physical_sources"]}


def _warning_types(lineage: dict) -> list[str]:
    return [warning["type"] for warning in lineage["diagnostics"].get("warnings") or []]


def test_a_star_over_a_pivot_keeps_the_implicit_grouping_column():
    lineage = _lineage(f"INSERT INTO m.t SELECT * FROM {PIVOTED}")

    assert list(_columns(lineage)) == ["dept", "q1", "q2"]
    assert _physical(lineage, "dept") == {"dept"}


def test_a_pivoted_column_is_an_aggregate_that_depends_on_the_for_column():
    lineage = _lineage(f"INSERT INTO m.t SELECT * FROM {PIVOTED}")

    q1 = _columns(lineage)["q1"]
    assert q1["transform"] == "AGGREGATE"
    assert _physical(lineage, "q1") == {"amt", "quarter"}


def test_an_outer_reference_to_the_grouping_column_resolves():
    lineage = _lineage(
        f"INSERT INTO m.t SELECT x.dept, x.q1 FROM (SELECT * FROM {PIVOTED}) x"
    )

    assert "dangling_column_ref_dropped" not in _warning_types(lineage)
    assert _physical(lineage, "dept") == {"dept"}
    assert _physical(lineage, "q1") == {"amt", "quarter"}


def test_several_aggregates_name_each_column_value_then_alias():
    lineage = _lineage(
        "INSERT INTO m.t SELECT * FROM (SELECT dept, quarter, amt, cnt FROM s.sales) "
        "PIVOT (SUM(amt) AS s, COUNT(cnt) AS c FOR quarter IN ('Q1' AS q1))"
    )

    assert list(_columns(lineage)) == ["dept", "q1_s", "q1_c"]
    assert _physical(lineage, "q1_s") == {"amt", "quarter"}
    assert _physical(lineage, "q1_c") == {"cnt", "quarter"}


def test_a_pivot_alias_reference_to_the_grouping_column_resolves():
    lineage = _lineage(f"INSERT INTO m.t SELECT p.dept AS dept, p.q1 AS q1 FROM {PIVOTED} p")

    assert "unresolved_alias" not in _warning_types(lineage)
    assert _physical(lineage, "dept") == {"dept"}


def test_a_star_over_an_unpivot_is_the_kept_columns_the_name_and_the_value():
    lineage = _lineage("INSERT INTO m.t SELECT * FROM s.wide UNPIVOT (val FOR q IN (q1, q2))")

    columns = _columns(lineage)
    assert list(columns) == ["id", "q", "val"]
    assert _physical(lineage, "id") == {"id"}
    assert _physical(lineage, "val") == {"q1", "q2"}
    assert _physical(lineage, "q") == set()
    assert columns["q"]["transform"] == "CONSTANT"


def test_unpivot_item_aliases_are_name_values_not_columns():
    lineage = _lineage(
        "INSERT INTO m.t SELECT * FROM s.wide UNPIVOT (val FOR q IN (q1 AS a1, q2 AS a2))"
    )

    assert list(_columns(lineage)) == ["id", "q", "val"]
    assert _physical(lineage, "val") == {"q1", "q2"}
    assert lineage["diagnostics"].get("lineage_fact_gaps") in (None, [])


def test_a_star_over_an_unpivoted_subquery_is_unchanged_without_unpivot():
    """Sentinel: a plain subquery behind `SELECT *` still expands to its own columns."""
    lineage = _lineage("INSERT INTO m.t SELECT * FROM (SELECT id, q1, q2 FROM s.wide) w")

    assert list(_columns(lineage)) == ["id", "q1", "q2"]


def test_a_pivot_is_keyed_by_its_grouping_columns_not_a_single_row():
    """Pivoted aggregates are per grouping key: one row per `dept`, not one row in all."""
    from scope_lineage.contract import to_lineage_dict
    from scope_lineage.render.semantic_profile import build_semantic_profile

    sql = f"INSERT INTO m.t SELECT * FROM {PIVOTED}"
    profile = build_semantic_profile(
        to_lineage_dict(parse_scope_lineage(sql, "pivot", schema=SCHEMA))
    )

    shape = profile["output_shape"]
    assert shape["grain"]["basis"] == "group_by"
    assert shape["candidate_keys"] == ["dept"]


# The PIVOT-alias reference (`p.dept`) used to come out UNKNOWN (audit verify-B side
# note 1). The subquery form is resolved since WP3f; these pin it, with and without a
# schema, so a later change cannot silently bring the UNKNOWN back.


def test_a_pivot_alias_reference_resolves_without_a_schema():
    lineage = to_dict(parse_scope_lineage(
        f"INSERT INTO m.t SELECT p.dept AS dept FROM {PIVOTED} p", "pivot", schema=None,
    ))

    assert "unresolved_alias" not in _warning_types(lineage)
    assert _columns(lineage)["dept"]["transform"] == "DIRECT"
    assert _physical(lineage, "dept") == {"dept"}


def test_a_pivot_alias_reference_to_a_pivoted_column_reads_the_aggregate_argument():
    lineage = _lineage(f"INSERT INTO m.t SELECT p.q1 AS q1 FROM {PIVOTED} p")

    assert "amt" in _physical(lineage, "q1")


@pytest.mark.xfail(
    strict=True,
    reason=(
        "A PIVOT written straight on a table with an alias (`FROM s.sales PIVOT(...) p`) "
        "makes sqlglot's qualify raise 'Unknown column: p' after it has already rewritten "
        "the tree into `sales.p.dept FROM (SELECT * FROM s.sales AS sales PIVOT(...)) AS p`; "
        "_qualify_ast (scope/scope_builder.py) falls back to that mutated tree, so `p.dept` "
        "reads a physical column `p`. Fix: qualify a copy and fall back to the original."
    ),
)
def test_a_pivot_alias_on_a_physical_table_reads_the_grouping_column():
    lineage = _lineage(
        "INSERT INTO m.t SELECT p.dept AS dept FROM s.sales "
        "PIVOT (SUM(amt) FOR quarter IN ('Q1', 'Q2')) p"
    )

    assert _physical(lineage, "dept") == {"dept"}


@pytest.mark.xfail(
    strict=True,
    reason=(
        "An alias reference resolves to one SourceRef (_first_column_ref in "
        "scope/column_ref_resolver.py), so `p.q1` keeps the aggregate argument but drops "
        "the FOR column that `SELECT *` over the same PIVOT carries."
    ),
)
def test_a_pivot_alias_reference_to_a_pivoted_column_also_reads_the_for_column():
    lineage = _lineage(f"INSERT INTO m.t SELECT p.q1 AS q1 FROM {PIVOTED} p")

    assert _physical(lineage, "q1") == {"amt", "quarter"}
