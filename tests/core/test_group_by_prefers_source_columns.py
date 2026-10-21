"""A GROUP BY name binds to a source column first, and to a SELECT alias only failing that.

Spark resolves grouping keys against the input's columns; an alias of the SELECT list is
used only for a name no input column has (``spark.sql.groupByAliases``). sqlglot's
``qualify``, without a schema, expanded every GROUP BY name that matched an alias:
``SELECT UPPER(o.a) AS k ... FROM db.src o GROUP BY k`` grouped by ``UPPER(o.a)`` although
``db.src`` has its own ``k`` -- a different grouping, so a different row set.
"""

from __future__ import annotations

from scope_lineage.scope.scope_builder import parse_scope_lineage

SQL = (
    "INSERT OVERWRITE TABLE db.tgt SELECT UPPER(o.a) AS k, COUNT(*) AS n "
    "FROM {source} o GROUP BY k"
)


def _group_by_fields(sql: str, schema: dict) -> set[tuple[str, str]]:
    result = parse_scope_lineage(sql, "t", schema=schema)
    [block] = [
        block
        for scope in result.scopes.values()
        for block in scope.logic_blocks
        if block.logic_type == "group_by"
    ]
    return {(field.scope, field.column) for field in block.fields}


def test_a_source_column_of_the_alias_name_is_the_grouping_key() -> None:
    fields = _group_by_fields(SQL.format(source="db.src"), {"db.src": ["a", "k"]})

    assert fields == {("db.src", "k")}


def test_a_derived_table_column_of_the_alias_name_is_the_grouping_key() -> None:
    fields = _group_by_fields(
        SQL.format(source="(SELECT a, k FROM db.src)"), {"db.src": ["a", "k"]}
    )

    assert fields == {("subq:o", "k")}


def test_without_such_a_source_column_the_alias_is_the_grouping_key() -> None:
    fields = _group_by_fields(SQL.format(source="db.src"), {"db.src": ["a"]})

    assert fields == {("db.src", "a")}


def test_a_source_the_schema_does_not_list_keeps_the_alias() -> None:
    fields = _group_by_fields(SQL.format(source="db.src"), {})

    assert fields == {("db.src", "a")}
