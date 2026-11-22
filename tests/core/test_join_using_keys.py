"""A ``JOIN ... USING`` key is the side Spark outputs, not a COALESCE of both sides.

sqlglot's ``qualify`` expands ``USING (id)`` into ``COALESCE(a.id, b.id)`` wherever the
merged ``id`` is read. Spark outputs the left key for INNER / LEFT (and SEMI / ANTI), the
right key for RIGHT, and a coalesce only for FULL OUTER. The expansion published an INNER
join's key as a ``cleaning`` EXPRESSION over two tables (1.8). The generated COALESCE
differs from a hand-written one only in node metadata, so the join kinds are recorded
before ``qualify`` and the generated nodes told apart from the author's (WP3j).

Every name here is synthetic.
"""

from __future__ import annotations

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {"s.a": ["id", "x"], "s.b": ["id", "y"], "s.c": ["id", "z"]}


def _root(sql: str, schema: dict | None) -> dict:
    return to_lineage_dict(parse_scope_lineage(sql, "t", schema=schema))["scopes"]["ROOT"]


def _column(root: dict, name: str) -> dict:
    return next(column for column in root["columns"] if column["name"] == name)


def _sources(column: dict) -> set[tuple[str, str]]:
    return {(source["scope"], source["column"]) for source in column["sources"]}


@pytest.mark.parametrize("schema", [SCHEMA, None])
@pytest.mark.parametrize("kind", ["", "INNER ", "LEFT ", "LEFT SEMI "])
def test_a_left_keyed_using_join_reads_the_left_key(kind: str, schema) -> None:
    projection = "id, a.x" if "SEMI" in kind else "id, a.x, b.y"
    root = _root(
        f"INSERT OVERWRITE TABLE m.t SELECT {projection} FROM s.a a {kind}JOIN s.b b USING (id)",
        schema,
    )

    key = _column(root, "id")
    assert key["transform"] == "DIRECT"
    assert _sources(key) == {("s.a", "id")}


@pytest.mark.parametrize("schema", [SCHEMA, None])
def test_a_right_using_join_reads_the_right_key(schema) -> None:
    root = _root(
        "INSERT OVERWRITE TABLE m.t SELECT id, b.y FROM s.a a RIGHT JOIN s.b b USING (id)",
        schema,
    )

    key = _column(root, "id")
    assert key["transform"] == "DIRECT"
    assert _sources(key) == {("s.b", "id")}


@pytest.mark.parametrize("schema", [SCHEMA, None])
def test_a_full_using_join_keeps_the_coalesce(schema) -> None:
    root = _root(
        "INSERT OVERWRITE TABLE m.t SELECT id FROM s.a a FULL OUTER JOIN s.b b USING (id)",
        schema,
    )

    key = _column(root, "id")
    assert key["expression"] == "COALESCE(`a`.`id`, `b`.`id`)"
    assert _sources(key) == {("s.a", "id"), ("s.b", "id")}


def test_where_and_group_by_read_the_left_key_too() -> None:
    root = _root(
        "INSERT OVERWRITE TABLE m.t SELECT id, COUNT(*) AS n FROM s.a a JOIN s.b b USING (id) "
        "WHERE id > 1 GROUP BY id",
        SCHEMA,
    )

    [where] = [block for block in root["logic_blocks"] if block["logic_type"] == "filter"]
    assert where["raw_expression"] == "WHERE `a`.`id` > 1"
    assert {(ref["scope"], ref["column"]) for ref in root["group_by"]} == {("s.a", "id")}
    assert "COALESCE" not in (root.get("raw_sql") or "")


def _join_conditions(root: dict) -> list[str]:
    return [join["condition_expression"] for join in root["joins"]]


@pytest.mark.parametrize("schema", [SCHEMA, None])
def test_a_chained_left_using_join_matches_the_accumulated_left_key(schema) -> None:
    root = _root(
        "INSERT OVERWRITE TABLE m.t SELECT id FROM s.a a LEFT JOIN s.b b USING (id) "
        "LEFT JOIN s.c c USING (id)",
        schema,
    )

    assert _join_conditions(root) == ["`a`.`id` = `b`.`id`", "`a`.`id` = `c`.`id`"]
    assert _sources(_column(root, "id")) == {("s.a", "id")}


@pytest.mark.parametrize("schema", [SCHEMA, None])
def test_a_chained_right_using_join_matches_the_right_key_it_carried(schema) -> None:
    root = _root(
        "INSERT OVERWRITE TABLE m.t SELECT id FROM s.a a RIGHT JOIN s.b b USING (id) "
        "JOIN s.c c USING (id)",
        schema,
    )

    assert _join_conditions(root) == ["`a`.`id` = `b`.`id`", "`b`.`id` = `c`.`id`"]
    assert _sources(_column(root, "id")) == {("s.b", "id")}


def test_a_chain_after_a_full_join_matches_the_coalesced_key() -> None:
    root = _root(
        "INSERT OVERWRITE TABLE m.t SELECT id FROM s.a a FULL JOIN s.b b USING (id) "
        "LEFT JOIN s.c c USING (id)",
        SCHEMA,
    )

    assert _join_conditions(root)[1] == "COALESCE(`a`.`id`, `b`.`id`) = `c`.`id`"
    assert _column(root, "id")["expression"] == "COALESCE(`a`.`id`, `b`.`id`)"


def test_a_hand_written_coalesce_is_left_alone() -> None:
    root = _root(
        "INSERT OVERWRITE TABLE m.t SELECT COALESCE(a.id, b.id) AS id, a.x "
        "FROM s.a a JOIN s.b b USING (id)",
        SCHEMA,
    )

    key = _column(root, "id")
    assert key["expression"] == "COALESCE(`a`.`id`, `b`.`id`)"
    assert _sources(key) == {("s.a", "id"), ("s.b", "id")}


def test_a_hand_written_coalesce_over_an_on_join_is_left_alone() -> None:
    root = _root(
        "INSERT OVERWRITE TABLE m.t SELECT COALESCE(a.id, b.id) AS id "
        "FROM s.a a LEFT JOIN s.b b ON a.id = b.id",
        SCHEMA,
    )

    assert _column(root, "id")["expression"] == "COALESCE(`a`.`id`, `b`.`id`)"
