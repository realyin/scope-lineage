"""HAVING and QUALIFY read a source column before a SELECT alias of the same name.

"HAVING prefers the table column over the SELECT list alias", and QUALIFY does the same
(https://docs.databricks.com/en/sql/language-manual/sql-ref-name-resolution.html). ``qualify``
expanded the alias in both clauses, so ``HAVING amt > 0`` over a source with its own ``amt``
became ``HAVING MAX(x.fee) > 0``. A name no source has is still the alias. ORDER BY, which
prefers the alias, is not shielded.
"""

from __future__ import annotations

from scope_lineage.scope.scope_builder import parse_scope_lineage


def _block(sql: str, schema: dict | None, prefix: str):
    result = parse_scope_lineage(sql, task_name="t", schema=schema)
    [block] = [
        block
        for scope in result.scopes.values()
        for block in scope.logic_blocks
        if (block.raw_expression or "").upper().startswith(prefix)
    ]
    return block


def _fields(block) -> set[tuple[str, str]]:
    return {(field.scope, field.column) for field in block.fields}


_HAVING = "INSERT OVERWRITE TABLE d.t SELECT g, MAX(fee) AS amt FROM ods.x GROUP BY g HAVING amt > 0"


def test_having_reads_the_source_column_over_the_alias():
    block = _block(_HAVING, {"ods.x": ["g", "fee", "amt"]}, "HAVING")

    assert block.raw_expression == "HAVING `x`.`amt` > 0"
    assert _fields(block) == {("ods.x", "amt")}


def test_having_reads_the_source_column_under_a_join():
    block = _block(
        "INSERT OVERWRITE TABLE d.t SELECT x.g, MAX(y.fee) AS amt FROM ods.x x "
        "JOIN ods.y y ON x.id = y.id GROUP BY x.g HAVING MAX(amt) > 0",
        {"ods.x": ["g", "id", "amt"], "ods.y": ["id", "fee"]},
        "HAVING",
    )

    assert "fee" not in block.raw_expression
    assert _fields(block) == {("ods.x", "amt")}


# sqlglot 30.0 leaves the column inside an expanded alias unqualified; 30.16+ qualifies it.
# Both readings resolve the alias to the same source field, which is what these tests pin.
_EXPANDED_ALIAS = {"HAVING MAX(`x`.`fee`) > 0", "HAVING MAX(`fee`) > 0"}


def test_having_still_expands_an_alias_no_source_has():
    block = _block(_HAVING, {"ods.x": ["g", "fee"]}, "HAVING")

    assert block.raw_expression in _EXPANDED_ALIAS
    assert [(field.scope, field.column) for field in block.fields] == [("ods.x", "fee")]


def test_having_without_a_schema_keeps_the_alias_reading():
    """Unknown source columns leave the name to the alias, as GROUP BY and the SELECT list do."""
    block = _block(_HAVING, None, "HAVING")

    assert block.raw_expression in _EXPANDED_ALIAS
    assert [(field.scope, field.column) for field in block.fields] == [("ods.x", "fee")]


_QUALIFY = (
    "INSERT OVERWRITE TABLE d.t SELECT g, fee AS amt FROM ods.x "
    "QUALIFY ROW_NUMBER() OVER (PARTITION BY g ORDER BY amt) = 1"
)


def test_qualify_reads_the_source_column_over_the_alias():
    block = _block(_QUALIFY, {"ods.x": ["g", "fee", "amt"]}, "QUALIFY")

    assert block.raw_expression == "QUALIFY ROW_NUMBER() OVER (PARTITION BY `x`.`g` ORDER BY `x`.`amt`) = 1"
    assert _fields(block) == {("ods.x", "g"), ("ods.x", "amt")}


def test_qualify_still_expands_an_alias_no_source_has():
    block = _block(_QUALIFY, {"ods.x": ["g", "fee"]}, "QUALIFY")

    assert block.raw_expression == "QUALIFY ROW_NUMBER() OVER (PARTITION BY `x`.`g` ORDER BY `x`.`fee`) = 1"


def test_the_documented_having_example():
    """``SELECT sum(b) AS a FROM t GROUP BY a HAVING a > 1``: 'a' refers to column 'a'."""
    block = _block(
        "INSERT OVERWRITE TABLE d.t SELECT SUM(b) AS a FROM s.t GROUP BY a HAVING a > 1",
        {"s.t": ["a", "b"]},
        "HAVING",
    )

    assert block.raw_expression == "HAVING `t`.`a` > 1"


def test_the_documented_qualify_example():
    """``SELECT -row_number() OVER (ORDER BY b) AS a FROM t QUALIFY a > 1``: column 'a'."""
    block = _block(
        "INSERT OVERWRITE TABLE d.t SELECT -ROW_NUMBER() OVER (ORDER BY b) AS a FROM s.t QUALIFY a > 1",
        {"s.t": ["a", "b"]},
        "QUALIFY",
    )

    assert block.raw_expression == "QUALIFY `t`.`a` > 1"
    assert {(f.scope, f.column) for f in block.fields} == {("s.t", "a")}
