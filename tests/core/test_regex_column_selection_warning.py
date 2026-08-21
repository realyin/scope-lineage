"""A regex column selection that was expanded must not keep saying it is missing.

``SELECT `(dt)?+.+``` is Spark's quoted-regex column selection -- "every column whose
name matches", the idiom for "all columns except dt". Column-reference resolution runs
before ``_expand_regex_column_selection`` and, seeing a name no table has, warns. The
expansion pass then succeeds and replaces the pattern with the columns it matched, so
the warning is left describing a column that no longer exists in the scope.

The retraction is gated on the expansion having actually happened. A pattern that
matched nothing, a pattern in a WHERE clause that is never expanded, and an ordinary
column whose name merely contains metacharacters (``amount$usd``) must all keep
warning -- suppressing on the "looks like a regex" predicate alone would trade a false
alarm for a false silence.
"""
from __future__ import annotations

from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {"db.src": ["dt", "a", "b", "c"]}


def _parse(sql: str, schema=SCHEMA):
    return parse_scope_lineage(sql, task_name="t", schema=schema)


def _warning_types(result) -> list[str]:
    return [w.type for w in result.diagnostics.warnings]


def _root_outputs(result) -> list[str]:
    return [o.name for o in result.scopes["ROOT"].outputs or []]


def test_expanded_regex_selection_retracts_column_not_found():
    result = _parse("INSERT OVERWRITE TABLE db.tgt SELECT `(dt)?+.+` FROM db.src")
    assert _root_outputs(result) == ["a", "b", "c"]
    assert "column_not_found" not in _warning_types(result)


def test_expanded_qualified_regex_selection_retracts_schema_warning():
    result = _parse("INSERT OVERWRITE TABLE db.tgt SELECT t.`(dt)?+.+` FROM db.src t")
    assert _root_outputs(result) == ["a", "b", "c"]
    assert "column_not_in_table_schema" not in _warning_types(result)


def test_pattern_matching_nothing_still_warns():
    """Nothing was expanded, so nothing proved the warning wrong."""
    result = _parse("INSERT OVERWRITE TABLE db.tgt SELECT `(zzz)?+zzz.+` FROM db.src")
    assert "column_not_found" in _warning_types(result)


def test_metacharacter_column_name_that_is_genuinely_missing_still_warns():
    """The guard that bites: `$` makes this look like a pattern, but it is a name."""
    result = _parse("INSERT OVERWRITE TABLE db.tgt SELECT `amount$usd` FROM db.src")
    assert "column_not_found" in _warning_types(result)


def test_regex_selection_without_schema_still_warns():
    """Covers only the single-source unqualified shape; see the plan for the rest."""
    result = _parse(
        "INSERT OVERWRITE TABLE db.tgt SELECT `(dt)?+.+` FROM db.src", schema=None
    )
    assert _warning_types(result), "expected some diagnostic when nothing can expand"
