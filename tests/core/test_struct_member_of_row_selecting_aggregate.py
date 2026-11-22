"""A member taken from MAX_BY / MIN_BY / FIRST / LAST of a STRUCT keeps the aggregate.

``MAX_BY(NAMED_STRUCT('val', a.amount), a.ts)`` picks the row with the latest ``ts``; its
``.val`` is that row's ``amount``. Only MAX / MIN were recognised as an aggregate wrapper,
so the member came back as the bare ``amount``: the aggregate disappeared and the ``ts``
that decides which row is chosen was lost (audit 1.12). A member written as a computed
expression was not found at all, so the whole STRUCT was expanded and every one of its
columns became a source. Members are now taken from the AST, by name.
"""

from __future__ import annotations

import pytest

from scope_lineage import parse_scope_lineage, to_dict

SCHEMA = {"s.o": ["id", "amount", "ts", "c1", "c2"]}


def _root_output(sql: str, field_name: str) -> dict:
    lineage = to_dict(parse_scope_lineage(sql, "struct_member", schema=SCHEMA))
    return next(
        item for item in lineage["scopes"]["ROOT"]["outputs"] if item["name"] == field_name
    )


def _fields(output: dict) -> list[str]:
    return [
        item["field"]
        for item in output["expression_resolution"]["physical_source_fields"]
    ]


def _member_of(struct_sql: str, member: str = "val") -> dict:
    sql = f"""INSERT OVERWRITE TABLE m.t
WITH r AS (SELECT a.id, {struct_sql} AS rec FROM s.o a GROUP BY a.id)
SELECT r.id, r.rec.{member} AS v FROM r"""
    return _root_output(sql, "v")


@pytest.mark.parametrize(
    ("struct_sql", "function"),
    [
        ("MAX_BY(NAMED_STRUCT('val', a.amount), a.ts)", "MAX_BY("),
        ("MIN_BY(STRUCT(a.amount AS val), a.ts)", "MIN_BY("),
    ],
)
def test_a_member_of_max_by_keeps_the_aggregate_and_its_ordering_column(struct_sql, function):
    output = _member_of(struct_sql)

    assert function in output["expanded_expression"].upper()
    assert sorted(_fields(output)) == ["amount", "ts"]
    assert output["expression_resolution"]["status"] == "resolved"


def test_a_member_of_first_keeps_the_aggregate():
    output = _member_of("FIRST(NAMED_STRUCT('val', a.amount))")

    assert "FIRST(" in output["expanded_expression"].upper()
    assert _fields(output) == ["amount"]


def test_a_member_of_last_keeps_the_aggregate():
    output = _member_of("LAST(STRUCT(a.amount AS val, a.c1 AS other))")

    assert "LAST(" in output["expanded_expression"].upper()
    assert _fields(output) == ["amount"]


def test_a_computed_member_of_a_plain_struct_reads_only_its_own_columns():
    sql = """INSERT OVERWRITE TABLE m.t
WITH r AS (SELECT NAMED_STRUCT('a', COALESCE(t.c1, 0), 'b', t.c2) AS st FROM s.o t)
SELECT r.st.a AS v FROM r"""

    output = _root_output(sql, "v")

    assert _fields(output) == ["c1"]
    assert "COALESCE(" in output["expanded_expression"].upper()


def test_a_bare_member_of_a_plain_struct_is_unchanged():
    """Sentinel: the bare-column member already resolved to that column alone."""
    sql = """INSERT OVERWRITE TABLE m.t
WITH r AS (SELECT NAMED_STRUCT('a', t.c1, 'b', t.c2) AS st FROM s.o t)
SELECT r.st.a AS v FROM r"""

    output = _root_output(sql, "v")

    assert output["expanded_expression"] == "`s.o`.`c1`"
    assert _fields(output) == ["c1"]


def test_a_member_of_max_struct_keeps_every_member():
    """Sentinel: MAX compares whole structs, so every member decides the chosen row."""
    output = _member_of("MAX(NAMED_STRUCT('t', a.ts, 'val', a.amount))")

    expanded = output["expanded_expression"].upper()
    assert expanded.startswith("(MAX(STRUCT(")
    assert sorted(_fields(output)) == ["amount", "ts"]
