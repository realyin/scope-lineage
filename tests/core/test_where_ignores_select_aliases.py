"""A WHERE clause binds to source columns, never to the SELECT list's aliases.

Spark evaluates WHERE before the projection, so in
``SELECT 'ALL' AS biz ... FROM s.o WHERE biz IN ('A')`` the ``biz`` is ``s.o.biz``. sqlglot's
``qualify`` expands alias references early when it has no schema, and that expansion reaches
WHERE too: the filter became ``'ALL' IN ('A')`` -- a constant predicate that silently dropped
the real one (QUALIFY-002). Passing a schema does not cure it: a join or a source the metadata
does not list still lets the early or late expansion rewrite the column.

GROUP BY, HAVING and later projections may legitimately reference aliases in Spark; those
expansions must survive the guard.
"""

from __future__ import annotations

from scope_lineage.scope.scope_builder import parse_scope_lineage


def _blocks(sql: str, schema: dict, logic_type: str = "filter"):
    result = parse_scope_lineage(sql, task_name="t", schema=schema)
    return [
        block
        for scope in result.scopes.values()
        for block in scope.logic_blocks
        if block.logic_type == logic_type
    ]


def _fields(block) -> set[tuple[str, str]]:
    return {(field.scope, field.column) for field in block.fields}


def test_a_constant_alias_does_not_replace_the_source_column_in_where():
    [block] = _blocks(
        "INSERT OVERWRITE TABLE d.t SELECT 'ALL' AS biz, id FROM s.o "
        "WHERE dt = '1' AND biz IN ('A', 'B')",
        {"s.o": ["biz", "id", "dt"]},
    )

    assert block.raw_expression == "WHERE `o`.`dt` = '1' AND `o`.`biz` IN ('A', 'B')"
    assert _fields(block) == {("s.o", "dt"), ("s.o", "biz")}


def test_an_alias_of_another_column_does_not_redirect_the_where_filter():
    [block] = _blocks(
        "INSERT OVERWRITE TABLE d.t SELECT crm_biz AS biz, id FROM s.o WHERE biz = 'X'",
        {"s.o": ["biz", "crm_biz", "id"]},
    )

    assert block.raw_expression == "WHERE `o`.`biz` = 'X'"
    assert _fields(block) == {("s.o", "biz")}


def test_a_joined_statement_keeps_the_where_column_on_its_source():
    [block] = _blocks(
        "INSERT OVERWRITE TABLE d.t SELECT 'ALL' AS biz, o.id FROM s.o o "
        "JOIN s.p p ON o.id = p.id WHERE biz IN ('A')",
        {"s.o": ["biz", "id"], "s.p": ["id"]},
    )

    assert "'ALL'" not in block.raw_expression
    assert _fields(block) == {("s.o", "biz")}


def test_a_derived_table_column_is_qualified_to_its_sole_source():
    [outer] = [
        block
        for block in _blocks(
            "INSERT OVERWRITE TABLE d.t "
            "SELECT a.x, ROW_NUMBER() OVER (PARTITION BY a.y ORDER BY a.z) AS rk "
            "FROM (SELECT x, y, z, rk FROM s.o) a WHERE rk = 1",
            {"s.o": ["x", "y", "z", "rk"]},
        )
        if "rk" in block.raw_expression
    ]

    assert outer.raw_expression == "WHERE `a`.`rk` = 1"


def test_a_lateral_alias_in_a_later_projection_is_still_expanded():
    result = parse_scope_lineage(
        "INSERT OVERWRITE TABLE d.t SELECT o.a AS b, b + 1 AS c FROM s.o o WHERE b > 0",
        task_name="t",
        schema={"s.o": ["a", "b"]},
    )
    root = result.scopes["ROOT"]
    [where] = [block for block in root.logic_blocks if block.logic_type == "filter"]
    [c] = [output for output in root.outputs if output.name == "c"]

    assert c.expression == "`o`.`a` + 1"
    assert where.raw_expression == "WHERE `o`.`b` > 0"


def test_group_by_and_having_aliases_are_still_expanded():
    sql = (
        "INSERT OVERWRITE TABLE d.t SELECT UPPER(o.a) AS k, 'ALL' AS biz, COUNT(*) AS n "
        "FROM s.o o WHERE biz = 'X' GROUP BY k, biz HAVING n > 1"
    )
    schema = {"s.o": ["a", "biz"]}

    [where] = _blocks(sql, schema)
    [group_by] = _blocks(sql, schema, "group_by")
    [having] = _blocks(sql, schema, "having")

    assert where.raw_expression == "WHERE `o`.`biz` = 'X'"
    # ``k`` is only an alias, so it expands; ``biz`` is also a column of ``s.o``, which a
    # Spark grouping key prefers (test_group_by_prefers_source_columns).
    assert _fields(group_by) == {("s.o", "a"), ("s.o", "biz")}
    assert having.raw_expression == "HAVING COUNT(*) > 1"
