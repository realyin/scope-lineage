"""WP4 1.11: each GROUP BY / PARTITION BY / ORDER BY item carries its own source fields.

The per-item `source_fields` of `aggregation_detail.group_by_items` and
`window_specification.partition_by` / `order_by` were cut from one flat list of the
clause's references by counting each item's `Column` nodes. The list does not have that
shape: GROUP BY references are de-duplicated across items, an item's repeated column is
listed once, and a constant item has none. So `GROUP BY 'c', a.y` gave the constant the
`y` and left `a.y` with nothing -- a constant with a physical source, a key with none.
"""

from __future__ import annotations

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {"s.a": ["x", "y", "z", "v"]}


def _blocks(select: str) -> list[dict]:
    document = to_lineage_dict(
        parse_scope_lineage(f"INSERT OVERWRITE TABLE m.t {select}", "keys", schema=SCHEMA)
    )
    return document["scopes"]["ROOT"]["logic_blocks"]


def _group_by_items(select: str) -> list[tuple[str, list[str]]]:
    for block in _blocks(select):
        detail = block.get("aggregation_detail") or {}
        if detail.get("group_by_items"):
            return [
                (item["expression_sql"], [field["column"] for field in item["source_fields"]])
                for item in detail["group_by_items"]
            ]
    raise AssertionError("no group_by_items")


def _window_items(select: str, key: str) -> list[tuple[str, list[str]]]:
    for block in _blocks(select):
        spec = block.get("window_specification") or {}
        if spec.get(key):
            return [
                (item["expression_sql"], [field["column"] for field in item["source_fields"]])
                for item in spec[key]
            ]
    raise AssertionError(f"no window {key}")


@pytest.mark.parametrize(
    ("select", "expected"),
    [
        (
            "SELECT 'c' AS c, a.y, COUNT(1) AS n FROM s.a a GROUP BY 'c', a.y",
            [("'c'", []), ("`a`.`y`", ["y"])],
        ),
        (
            "SELECT COALESCE(a.x, a.x) AS c, a.y, COUNT(1) AS n FROM s.a a "
            "GROUP BY COALESCE(a.x, a.x), a.y",
            [("COALESCE(`a`.`x`, `a`.`x`)", ["x"]), ("`a`.`y`", ["y"])],
        ),
        (
            "SELECT a.x, COALESCE(a.x, a.y) AS c, a.z, COUNT(1) AS n FROM s.a a "
            "GROUP BY a.x, COALESCE(a.x, a.y), a.z",
            [("`a`.`x`", ["x"]), ("COALESCE(`a`.`x`, `a`.`y`)", ["x", "y"]), ("`a`.`z`", ["z"])],
        ),
        # sentinel: plain keys, and an ordinal expanded before this path, were already right
        (
            "SELECT a.x, a.y, COUNT(1) AS n FROM s.a a GROUP BY a.x, a.y",
            [("`a`.`x`", ["x"]), ("`a`.`y`", ["y"])],
        ),
        (
            "SELECT a.x, a.y, COUNT(1) AS n FROM s.a a GROUP BY 1, a.y",
            [("`a`.`x`", ["x"]), ("`a`.`y`", ["y"])],
        ),
    ],
)
def test_each_group_by_item_has_only_its_own_fields(select: str, expected) -> None:
    assert _group_by_items(select) == expected


@pytest.mark.parametrize(
    ("select", "key", "expected"),
    [
        (
            "SELECT ROW_NUMBER() OVER (PARTITION BY 'k', a.x ORDER BY a.v) AS rn FROM s.a a",
            "partition_by",
            [("'k'", []), ("`a`.`x`", ["x"])],
        ),
        (
            "SELECT ROW_NUMBER() OVER (PARTITION BY COALESCE(a.x, a.x), a.z ORDER BY a.v) AS rn "
            "FROM s.a a",
            "partition_by",
            [("COALESCE(`a`.`x`, `a`.`x`)", ["x"]), ("`a`.`z`", ["z"])],
        ),
        (
            "SELECT ROW_NUMBER() OVER (PARTITION BY a.x ORDER BY 'q', a.v DESC) AS rn FROM s.a a",
            "order_by",
            [("'q'", []), ("`a`.`v`", ["v"])],
        ),
        # sentinel
        (
            "SELECT ROW_NUMBER() OVER (PARTITION BY a.x, a.z ORDER BY a.v) AS rn FROM s.a a",
            "partition_by",
            [("`a`.`x`", ["x"]), ("`a`.`z`", ["z"])],
        ),
    ],
)
def test_each_window_key_has_only_its_own_fields(select: str, key: str, expected) -> None:
    assert _window_items(select, key) == expected


def test_sentinel_order_by_keeps_its_direction() -> None:
    document_blocks = _blocks(
        "SELECT ROW_NUMBER() OVER (PARTITION BY a.x ORDER BY 'q', a.v DESC) AS rn FROM s.a a"
    )
    spec = next(b["window_specification"] for b in document_blocks if b.get("window_specification"))

    assert [item["direction"] for item in spec["order_by"]] == ["ASC", "DESC"]
