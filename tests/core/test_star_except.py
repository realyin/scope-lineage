"""`SELECT * EXCEPT (...)` must not publish the columns it excludes.

Spark's grammar allows exactly one star modifier -- `exceptClause` (SqlBaseParser.g4:
`ASTERISK exceptClause?` and `qualifiedName DOT ASTERISK exceptClause?`). REPLACE,
RENAME and ILIKE are other engines' constructs that sqlglot's base parser accepts
anyway, so they are diagnosed rather than modelled. MERGE's `INSERT *` / `UPDATE SET *`
take no except clause at all.

Expected values come from that grammar, not from what sqlglot happens to accept.
"""
from __future__ import annotations

from scope_lineage import parse_scope_lineage

SCHEMA = {
    "db.src": [{"name": "a"}, {"name": "b"}, {"name": "c"}],
    "db.tgt": [{"name": "a"}, {"name": "b"}],
}


def _run(sql: str, schema=SCHEMA):
    return parse_scope_lineage(sql, "star_except", schema)


def _names(result, scope="ROOT"):
    return [column.name for column in result.scopes[scope].columns]


def _warns(result):
    return [w.type for w in result.diagnostics.warnings]


def test_an_excluded_column_is_not_published():
    result = _run("INSERT INTO db.tgt SELECT * EXCEPT (c) FROM db.src")
    assert _names(result) == ["a", "b"]


def test_a_qualified_star_honours_its_own_except_list():
    # The Star hangs off inner.this here, not off inner -- reading the wrong one is the
    # obvious way to implement this and silently do nothing.
    result = _run("INSERT INTO db.tgt SELECT s.* EXCEPT (c) FROM db.src s")
    assert _names(result) == ["a", "b"]


def test_a_star_over_a_union_honours_it_too():
    # This shape never reaches the projection-time expander: it is materialized by the
    # deferred path. Fixing only the projection site would answer the same construct two
    # different ways depending on how it was written.
    result = _run(
        "INSERT INTO db.tgt SELECT * EXCEPT (c) FROM "
        "(SELECT a, b, c FROM db.src UNION ALL SELECT a, b, c FROM db.src) u"
    )
    assert _names(result) == ["a", "b"]


def test_excluding_a_column_the_star_does_not_produce_is_reported():
    result = _run("INSERT INTO db.tgt SELECT * EXCEPT (nosuch) FROM db.src")
    assert "star_except_column_not_found" in _warns(result)


def test_a_modifier_spark_has_no_grammar_for_is_reported_not_applied():
    result = _run("INSERT INTO db.tgt SELECT * REPLACE (a + 1 AS a) FROM db.src")
    assert "star_modifier_not_supported" in _warns(result)
    # Not applied: inventing a transform for syntax the engine would reject is worse
    # than leaving the expansion alone and saying so.
    assert _names(result) == ["a", "b", "c"]


def test_an_unexpandable_star_says_its_except_list_went_unapplied():
    result = _run("INSERT INTO db.tgt SELECT * EXCEPT (c) FROM db.src", schema=None)
    assert "star_not_expanded" in _warns(result)
    assert "star_modifier_not_applied" in _warns(result)


# --- guards --------------------------------------------------------------------------

def test_a_star_with_no_modifier_expands_exactly_as_before():
    result = _run("INSERT INTO db.tgt SELECT * FROM db.src")
    assert _names(result) == ["a", "b", "c"]
    assert not [w for w in _warns(result) if w.startswith("star_")]


def test_a_column_the_metastore_omits_but_the_sql_filters_on_survives():
    # `_with_referenced_columns_missing_from_schema` deliberately re-adds a column the SQL
    # references but the schema export lacks (partition columns). Excluding a different
    # column must not disturb that, and must not leave the filter referencing a column
    # the projection dropped.
    schema = {"db.src": [{"name": "a"}, {"name": "b"}, {"name": "c"}], "db.tgt": [{"name": "a"}]}
    result = _run(
        "INSERT INTO db.tgt SELECT * EXCEPT (c) FROM db.src WHERE dt = '2026-01-01'",
        schema=schema,
    )
    assert "c" not in _names(result)
    # `dt` is not in the schema export but the SQL filters on it, so the helper re-adds it.
    # Excluding a different column must not take it away with it.
    assert "dt" in _names(result)
