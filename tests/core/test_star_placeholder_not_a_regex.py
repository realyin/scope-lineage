"""`a.*` waiting for its upstream is a star, not a pattern.

A qualified star cannot always be expanded when the projection is first read: a CTE backed
by a UNION only gets its columns in a later pass, so `a.*` is parked as an EXPAND_ALL
placeholder for the fixpoint expansion to finish. Spark's regex column selection then read
that placeholder as a pattern — and `a.*` is a valid one, matching whatever happens to start
with "a". A 63-column star collapsed into the single column named `app_code`, and the
placeholder was gone before the pass that would have expanded it properly ever ran
(REGEX-COLUMN-002).

This needs the two conditions together: an upstream whose columns are not yet known when the
star is read, and an upstream column name the alias-prefixed pattern happens to match. Which
is why it takes a deep script to hit and no small one reproduces it.
"""

from __future__ import annotations

from scope_lineage.scope.scope_builder import parse_scope_lineage

# `amount` and `app_code` both match the pattern `a.*`; `id` and `dt` do not.
SCHEMA = {"ods.src": ["id", "dt", "amount", "app_code"], "ods.lab": ["cust", "label"]}

# `base` is a UNION, so its columns arrive in a later pass than `det`'s projection is read.
STAR_OVER_UNION_CTE = """INSERT INTO mart.t
WITH base AS (
  SELECT a.*, 'x' AS kind FROM ods.src a JOIN ods.lab b ON a.id = b.cust
  UNION ALL
  SELECT a.*, 'y' AS kind FROM ods.src a
),
det AS (SELECT a.* FROM base a)
SELECT d.id, d.dt, d.amount, d.app_code, d.kind FROM det d"""


def _parse(sql, schema=SCHEMA):
    return parse_scope_lineage(sql, task_name="t", schema=schema)


def test_the_star_expands_to_every_upstream_column():
    result = _parse(STAR_OVER_UNION_CTE)

    names = [column.name for column in result.scopes["cte:det"].columns]
    assert sorted(names) == ["amount", "app_code", "dt", "id", "kind"]


def test_no_column_is_lost_to_the_pattern_that_matches_the_alias():
    """The regression kept only names matching `a.*`, dropping id, dt and kind."""
    result = _parse(STAR_OVER_UNION_CTE)

    names = {column.name for column in result.scopes["cte:det"].columns}
    assert {"id", "dt", "kind"} <= names


def test_downstream_references_resolve_to_physical_columns():
    result = _parse(STAR_OVER_UNION_CTE)
    outputs = {output.name: output for output in result.scopes["ROOT"].outputs}

    for name, field in (("id", "id"), ("dt", "dt"), ("amount", "amount")):
        resolution = outputs[name].expression_resolution or {}
        assert resolution.get("status") == "resolved", name
        assert {"table": "ods.src", "field": field} in (
            resolution.get("physical_source_fields") or []
        ), name
    assert result.diagnostics.lineage_fact_gaps == []


def test_a_real_regex_column_selection_still_expands():
    """The guard must not disarm the feature it sits inside."""
    sql = """INSERT INTO mart.t
SELECT t1.id, t1.dt FROM (SELECT `(app_code)?+.+` FROM ods.src) t1"""

    result = _parse(sql)

    names = {column.name for column in result.scopes["subq:t1"].columns}
    assert "app_code" not in names, "the pattern excludes app_code"
    assert {"id", "dt", "amount"} <= names
