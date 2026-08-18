"""A PIVOT produces columns; without them every reference to it is a gap.

`PIVOT (max(amt) FOR k IN ('A', 'B'))` turns the values of `k` into columns named `A` and
`B`, whose values come from `max(amt)`. Neither was modelled: the pivot's own alias never
became an input edge — the edge pointed at the subquery being pivoted — so a downstream
`p.A` could not even find the alias, let alone the column (PIVOT-001).

The IN list is the column set. When it is not a list of literals the set is unknowable, and
a gap is the honest answer rather than a guessed binding.
"""

from __future__ import annotations

from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {"ods.src": ["k", "v", "amt"]}

PIVOTED = """INSERT INTO mart.t
SELECT p.A AS a_val, p.B AS b_val
FROM (SELECT k, v, amt FROM ods.src) PIVOT (max(amt) FOR k IN ('A', 'B')) p"""


def _root(sql, schema=SCHEMA):
    result = parse_scope_lineage(sql, task_name="t", schema=schema)
    return result, {output.name: output for output in result.scopes["ROOT"].outputs}


def test_the_pivot_alias_is_an_input_edge():
    result, _ = _root(PIVOTED)

    aliases = {ref.get("alias") for ref in result.scopes["ROOT"].input_source_refs}
    assert "p" in aliases


def test_a_reference_to_a_pivoted_column_resolves_to_the_aggregated_column():
    result, outputs = _root(PIVOTED)

    resolution = outputs["a_val"].expression_resolution or {}
    assert resolution.get("status") == "resolved"
    assert resolution.get("physical_source_fields") == [{"table": "ods.src", "field": "amt"}]
    assert result.diagnostics.lineage_fact_gaps == []


def test_every_literal_of_the_in_list_becomes_a_column():
    result, outputs = _root(PIVOTED)

    for name in ("a_val", "b_val"):
        resolution = outputs[name].expression_resolution or {}
        assert resolution.get("status") == "resolved", name


def test_an_aliased_in_item_is_named_by_its_alias():
    sql = """INSERT INTO mart.t
SELECT p.x AS x_val
FROM (SELECT k, v, amt FROM ods.src) PIVOT (max(amt) FOR k IN ('A' AS x)) p"""

    result, outputs = _root(sql)

    resolution = outputs["x_val"].expression_resolution or {}
    assert resolution.get("status") == "resolved"
    assert resolution.get("physical_source_fields") == [{"table": "ods.src", "field": "amt"}]


def test_a_non_literal_in_list_reports_a_gap_rather_than_a_guess():
    sql = """INSERT INTO mart.t
SELECT p.A AS a_val
FROM (SELECT k, v, amt FROM ods.src) PIVOT (max(amt) FOR k IN (SELECT k FROM ods.src)) p"""

    result, outputs = _root(sql)

    resolution = outputs["a_val"].expression_resolution or {}
    assert resolution.get("status") != "resolved"
    assert resolution.get("physical_source_fields") in (None, [])


# The shape seen in practice: the pivot has no alias of its own and sits behind a
# `SELECT *`, whose own subquery carries the alias downstream references.
UNALIASED_BEHIND_STAR = """INSERT INTO mart.t
SELECT t1.A AS a_val, t1.B AS b_val
FROM (SELECT * FROM (SELECT k, amt FROM ods.src) PIVOT (max(amt) FOR k IN ('A', 'B'))) t1"""


def test_a_star_over_a_pivoted_source_sees_the_pivoted_columns():
    result, _ = _root(UNALIASED_BEHIND_STAR)

    # Not k / amt: the PIVOT replaced the relation's columns.
    assert [c.name for c in result.scopes["subq:t1"].columns] == ["a", "b"]


def test_the_unaliased_shape_resolves_to_the_aggregated_column():
    result, outputs = _root(UNALIASED_BEHIND_STAR)

    for name in ("a_val", "b_val"):
        resolution = outputs[name].expression_resolution or {}
        assert resolution.get("status") == "resolved", name
        assert resolution.get("physical_source_fields") == [
            {"table": "ods.src", "field": "amt"}
        ], name
    assert result.diagnostics.lineage_fact_gaps == []


def test_pivoted_names_are_matched_case_insensitively():
    """`IN ('DPMAF034SCORE')` has to meet a reference qualify wrote as lowercase."""
    sql = """INSERT INTO mart.t
SELECT t1.upper_name AS v
FROM (SELECT * FROM (SELECT k, amt FROM ods.src) PIVOT (max(amt) FOR k IN ('UPPER_NAME'))) t1"""

    result, outputs = _root(sql)

    resolution = outputs["v"].expression_resolution or {}
    assert resolution.get("status") == "resolved"
    assert result.diagnostics.lineage_fact_gaps == []


def test_a_star_over_an_unpivoted_source_is_unchanged():
    """The guard: only a pivoted FROM item takes the new path."""
    sql = "INSERT INTO mart.t SELECT t1.k, t1.amt FROM (SELECT * FROM (SELECT k, amt FROM ods.src) x) t1"

    result, _ = _root(sql)

    assert sorted(c.name for c in result.scopes["subq:t1"].columns) == ["amt", "k"]
    assert result.diagnostics.lineage_fact_gaps == []


def test_a_statement_without_a_pivot_is_unaffected():
    sql = "INSERT INTO mart.t SELECT s.amt AS a FROM ods.src s"

    result, outputs = _root(sql)

    resolution = outputs["a"].expression_resolution or {}
    assert resolution.get("status") == "resolved"
    assert result.diagnostics.lineage_fact_gaps == []
