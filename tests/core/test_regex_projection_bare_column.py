"""A regex column selection hides its column set from the resolver, not forever.

Spark's quoted regex column selection names the columns a source exposes by pattern, so the
set is not knowable until the pattern is matched against the upstream columns — which
happens after column resolution. Until then a source projecting `` `(rk)?+.+` `` was read as
projecting one column literally called ``(rk)?+.+``, so any other name was judged absent
from it, and a bare reference with two inputs lost the one source that could supply it
(PROJECTION-001).

A pattern means "not yet knowable", which the resolver already models as ``unknown`` and
already treats as still possible.
"""

from __future__ import annotations

from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {"ods.src": ["a", "b", "rk"], "ods.other": ["id", "c"]}

REGEX_SOURCE = """INSERT INTO mart.t
SELECT t1.a, b, t2.c
FROM (SELECT `(rk)?+.+` FROM ods.src) t1
JOIN (SELECT id, c FROM ods.other) t2 ON t1.a = t2.id"""

PLAIN_SOURCE = """INSERT INTO mart.t
SELECT t1.a, b, t2.c
FROM (SELECT a, b FROM ods.src) t1
JOIN (SELECT id, c FROM ods.other) t2 ON t1.a = t2.id"""


def _outputs(sql, schema=SCHEMA):
    result = parse_scope_lineage(sql, task_name="t", schema=schema)
    return result, {output.name: output for output in result.scopes["ROOT"].outputs}


def test_bare_column_binds_through_a_regex_projection():
    result, outputs = _outputs(REGEX_SOURCE)

    resolution = outputs["b"].expression_resolution or {}
    assert resolution.get("status") == "resolved"
    assert resolution.get("physical_source_fields") == [{"table": "ods.src", "field": "b"}]
    assert result.diagnostics.lineage_fact_gaps == []


def test_the_regex_source_still_expands_to_its_real_columns():
    result, _ = _outputs(REGEX_SOURCE)

    assert [c.name for c in result.scopes["subq:t1"].columns] == ["a", "b"]


def test_a_plain_projection_is_unaffected():
    """The comparison that isolates the cause: same statement, no pattern, already fine."""
    result, outputs = _outputs(PLAIN_SOURCE)

    resolution = outputs["b"].expression_resolution or {}
    assert resolution.get("status") == "resolved"
    assert result.diagnostics.lineage_fact_gaps == []


def test_a_name_the_pattern_excludes_is_not_invented():
    """`(rk)?+.+` selects everything except rk, so rk must not resolve through it."""
    sql = """INSERT INTO mart.t
SELECT t1.a, rk, t2.c
FROM (SELECT `(rk)?+.+` FROM ods.src) t1
JOIN (SELECT id, c FROM ods.other) t2 ON t1.a = t2.id"""

    result, outputs = _outputs(sql)

    resolution = outputs["rk"].expression_resolution or {}
    assert resolution.get("status") != "resolved"
    assert resolution.get("physical_source_fields") in (None, [])


def test_a_name_two_regex_sources_could_both_supply_stays_ambiguous():
    """Ambiguity is a fact about the SQL; narrowing to one source would be a guess."""
    sql = """INSERT INTO mart.t
SELECT b
FROM (SELECT `(rk)?+.+` FROM ods.src) t1
JOIN (SELECT `(id)?+.+` FROM ods.dup) t2 ON t1.a = t2.b"""

    result, outputs = _outputs(
        sql, {"ods.src": ["a", "b", "rk"], "ods.dup": ["b", "id"]}
    )

    resolution = outputs["b"].expression_resolution or {}
    assert resolution.get("status") != "resolved"
