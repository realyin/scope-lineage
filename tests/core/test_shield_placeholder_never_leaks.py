"""The alias-collision shields never publish their placeholder name as a column.

The WHERE and GROUP BY shields (QUALIFY-002 and its GROUP BY sibling) rename a column for
the duration of ``qualify`` and rename it back afterwards. sqlglot copies an expression
when it expands a lateral, GROUP BY or HAVING alias, so a shielded column can come out of
``qualify`` more than once. Restoring only the node objects saved before ``qualify`` left
every copy carrying ``__lineage_where_column__``; that name then reached raw_sql, the
column list and the physical sources as if it were a real column of the table.
"""

from __future__ import annotations

import json

import pytest
from sqlglot import exp

from scope_lineage import parse_task_lineage, to_task_lineage_dict
from scope_lineage.scope import scope_builder
from scope_lineage.scope.scope_builder import parse_scope_lineage

PREFIX = "__lineage_where_column__"
SCHEMA = {"s.i": ["biz", "v", "k"], "s.o": ["id", "k", "g"]}

COPYING_SHAPES = {
    "lateral alias copies a scalar subquery":
        "INSERT INTO dw.t SELECT (SELECT MAX('ALL') AS biz FROM s.i WHERE biz = 'A') AS x, "
        "x AS y FROM s.o",
    "group by alias copies a scalar subquery":
        "INSERT INTO dw.t SELECT (SELECT MAX('ALL') AS biz FROM s.i WHERE biz = 'A') AS x, "
        "COUNT(*) AS c FROM s.o GROUP BY x",
    "having alias copies a scalar subquery":
        "INSERT INTO dw.t SELECT g, (SELECT MAX('ALL') AS biz FROM s.i WHERE biz = 'A') AS x "
        "FROM s.o GROUP BY g HAVING x = 'ALL'",
    "a lateral alias copies a GROUP BY shield":
        "INSERT INTO dw.t SELECT (SELECT COUNT(*) FROM (SELECT UPPER(v) AS k FROM s.i GROUP BY k) q) "
        "AS x, x + 1 AS y FROM s.o",
}


@pytest.mark.parametrize("schema", [SCHEMA, None], ids=["schema", "no-schema"])
@pytest.mark.parametrize("sql", COPYING_SHAPES.values(), ids=COPYING_SHAPES.keys())
def test_a_copied_shielded_column_is_restored(sql, schema):
    document = to_task_lineage_dict(parse_task_lineage(sql, task_name="t", schema=schema))

    assert PREFIX not in json.dumps(document, ensure_ascii=False)


@pytest.mark.parametrize(
    "sql", list(COPYING_SHAPES.values())[:3], ids=list(COPYING_SHAPES.keys())[:3],
)
def test_every_copy_of_the_where_filter_binds_to_the_inner_source(sql):
    result = parse_scope_lineage(sql, task_name="t", schema=SCHEMA)
    filters = [
        block
        for scope in result.scopes.values()
        for block in scope.logic_blocks
        if block.logic_type == "filter"
    ]

    assert filters
    for block in filters:
        assert block.raw_expression == "WHERE `i`.`biz` = 'A'"
        assert {(field.scope, field.column) for field in block.fields} == {("s.i", "biz")}


def test_a_copied_group_by_shield_groups_by_the_source_column():
    result = parse_scope_lineage(COPYING_SHAPES["a lateral alias copies a GROUP BY shield"],
                                 task_name="t", schema=SCHEMA)
    group_bys = [
        block
        for scope in result.scopes.values()
        for block in scope.logic_blocks
        if block.logic_type == "group_by"
    ]

    assert group_bys
    for block in group_bys:
        assert {(field.scope, field.column) for field in block.fields} == {("s.i", "k")}


def test_a_column_left_with_the_placeholder_is_named_on_exit(monkeypatch):
    """The exit check catches a placeholder any future path forgets to restore."""
    tree = exp.select(exp.column(PREFIX + "a")).from_("s.o")
    monkeypatch.setattr(scope_builder, "_restore_shielded_columns", lambda *a, **k: None)

    with pytest.raises(scope_builder.ShieldPlaceholderLeak, match=PREFIX + "a"):
        scope_builder._qualify_ast(tree)


def _blocks(result, logic_type: str):
    return [
        block
        for scope in result.scopes.values()
        for block in scope.logic_blocks
        if block.logic_type == logic_type
    ]


def test_the_where_shield_compares_alias_names_case_insensitively():
    """Spark identifiers are case-insensitive, and so is sqlglot's alias expansion."""
    result = parse_scope_lineage(
        "INSERT OVERWRITE TABLE d.t SELECT 'ALL' AS BIZ, o.id FROM s.o o "
        "JOIN s.p p ON o.id = p.id WHERE biz IN ('A')",
        task_name="t",
        schema={"s.o": ["biz", "id"], "s.p": ["id"]},
    )
    [block] = _blocks(result, "filter")

    assert "'ALL'" not in block.raw_expression
    assert {(field.scope, field.column) for field in block.fields} == {("s.o", "biz")}


def test_the_group_by_shield_compares_alias_names_case_insensitively():
    result = parse_scope_lineage(
        "INSERT OVERWRITE TABLE d.t SELECT UPPER(o.a) AS K, COUNT(*) AS n FROM s.o o GROUP BY k",
        task_name="t",
        schema={"s.o": ["a", "k"]},
    )
    [block] = _blocks(result, "group_by")

    assert {(field.scope, field.column) for field in block.fields} == {("s.o", "k")}
