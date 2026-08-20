"""A column named after a SQL keyword costs the whole statement its lineage.

`not`, `out`, `like` and `using` are legal column names in Spark when quoted, and a
machine-generated projection list will not have been audited for keyword collisions. sqlglot's
parser stops at the first one, the statement falls to the lenient parse, its projection list is
discarded, and nearly every output column comes back with no source at all — one or two
identifiers can cost an entire statement (KEYWORD-IDENT-001).

The repair asks the parser rather than a keyword list. `_spark_keywords()` is 305 tokenizer
words, not Spark's reserved set, so any list is either too wide or too narrow; instead the parse
error names the token it stopped on, that token is quoted, and the statement is parsed again. A
rewrite is kept only if it makes the statement parse — otherwise the original text stands and the
statement stays `recovered`, which is the honest answer for SQL that is simply malformed.

Clause keywords are never quoted, and that guard is not theoretical: malformed SQL with an empty
WHERE body parses *successfully* once its `WHERE` is quoted, producing an AST in which WHERE is a
column name. A confidently wrong answer is worse than a degraded one.
"""

from __future__ import annotations

import pytest

from scope_lineage import parse_scope_lineage
from scope_lineage.scope.task_lineage import parse_task_lineage

SCHEMA = {"ods.s": ["id", "v", "not", "out", "like", "using"], "mart.t": ["id", "c", "d"]}


def _traced_columns(sql: str) -> set[str]:
    result = parse_task_lineage(sql, task_name="t", schema=SCHEMA)
    return {
        item["column"]
        for item in result.end_to_end_lineage
        if item.get("table") == "mart.t"
        for source in item.get("value_sources") or []
        if source.get("source_kind") == "physical_field"
    }


@pytest.mark.parametrize("word", ["not", "out", "like", "using"])
def test_a_column_named_after_a_keyword_keeps_its_lineage(word):
    sql = f"insert overwrite table mart.t select cast({word} as double) as c from ods.s"

    assert parse_task_lineage(sql, task_name="t", schema=SCHEMA).syntax_status == "strict_ok"
    assert "c" in _traced_columns(sql)


def test_several_keyword_columns_in_one_statement():
    """The real statement had two; repairing one and stopping left the other to fail."""
    sql = (
        "insert overwrite table mart.t\n"
        "select cast(not as double) as c, cast(out as double) as d from ods.s"
    )
    result = parse_task_lineage(sql, task_name="t", schema=SCHEMA)

    assert result.syntax_status == "strict_ok"
    assert {"c", "d"} <= _traced_columns(sql)


def test_malformed_sql_is_not_repaired_into_something_that_parses():
    """The guard that matters: quoting a clause keyword can make nonsense parse."""
    sql = "insert overwrite table mart.t select id from ods.s where group by id"
    result = parse_task_lineage(sql, task_name="t", schema=SCHEMA)

    assert result.syntax_status == "recovered", "malformed SQL must stay malformed"


@pytest.mark.parametrize("sql", [
    "insert overwrite table mart.t select coalesce(not v, false) as c from ods.s",
    "insert overwrite table mart.t select cast(v as double) as c from ods.s",
    "insert overwrite table mart.t select id as c from ods.s where v not in (1, 2)",
    "insert overwrite table mart.t select case when v then 1 else 2 end as c from ods.s",
])
def test_valid_sql_is_left_exactly_alone(sql):
    """Behaviour that must not change: no rewrite unless the parser actually stopped."""
    result = parse_task_lineage(sql, task_name="t", schema=SCHEMA)

    assert result.syntax_status == "strict_ok"
    assert "c" in _traced_columns(sql)


def test_the_rewrite_is_declared_not_silent():
    """A statement Core rewrote must say so; an undeclared fact in the artifact is how
    cross_task_trace_required became impossible to remove safely."""
    sql = "insert overwrite table mart.t select cast(not as double) as c from ods.s"
    result = parse_task_lineage(sql, task_name="t", schema=SCHEMA)

    warnings = [w for w in result.diagnostics.get("warnings") or []
                if w.get("type") == "identifiers_quoted_for_parse"]
    assert warnings, "the rewrite must be visible in diagnostics"
    assert "not" in warnings[0].get("msg", "").lower()


def test_the_scope_entry_point_repairs_too():
    sql = "insert overwrite table mart.t select cast(out as double) as c from ods.s"

    assert parse_scope_lineage(sql, "t", schema=SCHEMA).syntax_status == "strict_ok"
