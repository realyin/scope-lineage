"""A statement sqlglot can parse but not print back must not take the caller down with it.

`normalized_sql` is generated from the parsed tree. When a statement contains an identifier
sqlglot's tokenizer claims as a keyword, the repaired tree can hold a node the Spark generator
cannot render -- `CAST(out AS DOUBLE)` parses to a Cast whose `to` is None, and
`generators/spark2.py::cast_sql` dereferences it. The AttributeError escapes
`parse_scope_lineage` and `parse_task_lineage` entirely (REGEN-001).

That is the worst failure this parser has: the whole point of keeping a broken statement is
that one bad statement cannot cost a batch its other results, and an exception out of the
public API costs the caller everything.

It also gates the reserved-word rewrite. Any rewriter is incomplete -- `_spark_keywords()` is
a tokenizer word list, not Spark's reserved set -- and an incomplete rewrite turns today's
degraded-but-returning `recovered` into a crash. The guard has to exist first.

Rendering is best-effort here by design: the lineage is built from the AST, not from this
string, so failing to print it costs a convenience field and nothing else.
"""

from __future__ import annotations

import pytest

from scope_lineage import parse_all_scope_lineage, parse_scope_lineage
from scope_lineage.scope.task_lineage import parse_task_lineage

SCHEMA = {"ods.s": ["id", "v"], "mart.t": ["id", "c", "v"]}

# A clause keyword, deliberately: `out` and `not` used to sit here, but Core now quotes
# keyword-colliding identifiers and this statement would be repaired before it could reach
# the generator. Clause keywords are the ones Core will never quote (KEYWORD-IDENT-001), so
# they still produce the Cast-without-a-type that crashes Spark's `cast_sql`.
UNRENDERABLE = "insert overwrite table mart.t select cast(where as double) as c from ods.s"


def test_scope_parse_does_not_raise():
    result = parse_scope_lineage(UNRENDERABLE, "t", schema=SCHEMA)

    assert result is not None


def test_task_parse_does_not_raise():
    result = parse_task_lineage(UNRENDERABLE, task_name="t", schema=SCHEMA)

    assert result is not None


def test_parse_all_does_not_raise():
    assert parse_all_scope_lineage(UNRENDERABLE, "t", schema=SCHEMA) is not None


def test_the_statement_is_still_returned_and_marked_unreliable():
    """Keeping it is the point; the caller must be able to see it is not trustworthy."""
    result = parse_task_lineage(UNRENDERABLE, task_name="t", schema=SCHEMA)

    assert len(result.statements) == 1
    assert result.syntax_status != "strict_ok"


def test_one_unrenderable_statement_does_not_cost_the_others():
    """The reason broken statements are kept at all."""
    sql = f"insert overwrite table mart.t select id, v from ods.s;\n{UNRENDERABLE}"
    result = parse_task_lineage(sql, task_name="t", schema=SCHEMA)

    assert len(result.statements) == 2
    traced = {
        item["column"]
        for item in result.end_to_end_lineage
        if item.get("table") == "mart.t"
        for source in item.get("value_sources") or []
        if source.get("source_kind") == "physical_field"
    }
    assert {"id", "v"} <= traced, "the healthy statement must keep its lineage"


def test_a_renderable_statement_still_gets_its_normalized_sql():
    """Behaviour that must not change: the guard is a fallback, not a replacement."""
    result = parse_task_lineage(
        "insert overwrite table mart.t select id, v from ods.s",
        task_name="t",
        schema=SCHEMA,
    )

    assert result.statements[0]["normalized_sql"].strip() != ""


@pytest.mark.parametrize("sql", [UNRENDERABLE, "insert overwrite table mart.t select cast(select as double) as c from ods.s"])
def test_normalized_sql_is_present_even_when_rendering_failed(sql):
    """A required contract field cannot simply be missing; it falls back to something honest."""
    result = parse_task_lineage(sql, task_name="t", schema=SCHEMA)

    assert "normalized_sql" in result.statements[0]
