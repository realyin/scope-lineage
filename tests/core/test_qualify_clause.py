"""QUALIFY is a row filter evaluated after the window functions (audit 1.4, D5).

It was ignored: no logic block, role ``pass_through``, and the columns it reads (the
window's ``updated_at``) appeared nowhere but the raw SQL. Supported natively -- the AST
keeps its shape, and the clause becomes a filter block with ``predicate_type="qualify"``
plus a window block for each window it computes -- because rewriting it into a subquery
(``sqlglot.transforms.eliminate_qualify``) changes the output on six common shapes
(review-1 R3): a ``SELECT *`` gains the synthetic window column, an unaliased expression is
renamed, a GROUP BY statement grows a bare column, DISTINCT / ORDER BY / LIMIT move inside.

The test on every shape is that the statement's output columns and scopes are exactly
those of the same statement without its QUALIFY.
"""

from __future__ import annotations

import pytest

from scope_lineage import parse_scope_lineage, to_dict
from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.semantic_profile import build_semantic_profile

SCHEMA = {
    "ods.users": ["user_id", "name", "updated_at"],
    "ods.orders": ["user_id", "amt", "order_id"],
}
PIN = " QUALIFY ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY updated_at DESC) = 1"

# (statement without QUALIFY, the QUALIFY clause, the clauses written after it)
SHAPES = {
    "star": ("INSERT INTO dw.t SELECT * FROM ods.users", PIN, ""),
    "qualified_star_and_join": (
        "INSERT INTO dw.t SELECT u.*, o.amt FROM ods.users u "
        "JOIN ods.orders o ON u.user_id = o.user_id",
        " QUALIFY ROW_NUMBER() OVER (PARTITION BY u.user_id ORDER BY u.updated_at DESC) = 1",
        "",
    ),
    "unaliased_expression": (
        "INSERT INTO dw.t SELECT user_id, UPPER(name) FROM ods.users", PIN, ""
    ),
    "group_by": (
        "INSERT INTO dw.t SELECT user_id, SUM(amt) AS s FROM ods.orders GROUP BY user_id",
        " QUALIFY RANK() OVER (ORDER BY SUM(amt) DESC) <= 10",
        "",
    ),
    "distinct": ("INSERT INTO dw.t SELECT DISTINCT user_id FROM ods.users", PIN, ""),
    "order_by_limit": (
        "INSERT INTO dw.t SELECT user_id, name FROM ods.users", PIN, " ORDER BY name LIMIT 5"
    ),
}

DEDUP = (
    "INSERT INTO dw.dedup_users SELECT user_id, name FROM ods.users"
    " QUALIFY ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY updated_at DESC) = 1"
)


def _lineage(sql: str) -> dict:
    return to_dict(parse_scope_lineage(sql, "qualify", schema=SCHEMA))


def _shape(lineage: dict) -> tuple[list[str], list[str], list]:
    root = lineage["scopes"]["ROOT"]
    outputs = [
        (output["name"], sorted(
            (item["table"], item["field"])
            for item in (output.get("expression_resolution") or {}).get("physical_source_fields") or []
        ))
        for output in root["outputs"]
    ]
    return [name for name, _ in outputs], sorted(lineage["scopes"]), outputs


def _qualify_blocks(lineage: dict, scope_id: str = "ROOT") -> list[dict]:
    return [
        block for block in lineage["scopes"][scope_id].get("logic_blocks") or []
        if (block.get("filter_predicate_detail") or {}).get("predicate_type") == "qualify"
    ]


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_qualify_leaves_the_output_columns_of_the_statement_unchanged(shape):
    base, clause, tail = SHAPES[shape]

    without, with_qualify = _lineage(base + tail), _lineage(base + clause + tail)

    assert _shape(with_qualify) == _shape(without)
    assert len(_qualify_blocks(with_qualify)) == 1


def test_the_qualify_block_is_a_filter_reading_the_window_columns():
    lineage = _lineage(DEDUP)

    (block,) = _qualify_blocks(lineage)
    assert block["logic_type"] == "filter"
    assert {(field["scope"], field["column"]) for field in block["fields"]} == {
        ("ods.users", "user_id"),
        ("ods.users", "updated_at"),
    }


def test_the_window_in_qualify_is_a_window_block_with_its_partition_and_order():
    lineage = _lineage(DEDUP)

    windows = [
        block for block in lineage["scopes"]["ROOT"]["logic_blocks"]
        if block["logic_type"] == "window"
    ]
    assert len(windows) == 1
    spec = windows[0]["window_specification"]
    assert spec["window_function"] == "row_number"
    assert [item["expression_sql"] for item in spec["partition_by"]] == ["`users`.`user_id`"]
    assert [item["expression_sql"] for item in spec["order_by"]] == ["`users`.`updated_at`"]
    assert {field["column"] for field in windows[0]["fields"]} == {"user_id", "updated_at"}
    (link,) = spec["filter_after_window"]
    assert link["logic_block_id"] == _qualify_blocks(lineage)[0]["logic_block_id"]


def test_a_row_number_pinned_to_one_by_qualify_is_a_dedup():
    lineage = _lineage(DEDUP)

    assert lineage["scopes"]["ROOT"]["role"] == "dedup"


def test_a_row_number_pinned_to_one_by_qualify_proves_its_partition_unique():
    profile = build_semantic_profile(
        to_lineage_dict(parse_scope_lineage(DEDUP, "qualify", schema=SCHEMA))
    )

    shape = profile["output_shape"]
    assert shape["shape"] == "deduplicated"
    assert shape["candidate_keys"] == ["user_id"]
    assert shape["grain"]["basis"] == "window_partition"


def test_a_qualify_on_a_window_alias_is_the_same_dedup():
    sql = (
        "INSERT INTO dw.dedup_users SELECT user_id, name, "
        "ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY updated_at DESC) AS rn "
        "FROM ods.users QUALIFY rn = 1"
    )
    lineage = _lineage(sql)

    assert lineage["scopes"]["ROOT"]["role"] == "dedup"
    assert len(_qualify_blocks(lineage)) == 1


def test_a_qualify_that_is_not_a_rank_pin_is_a_filter_not_a_dedup():
    sql = (
        "INSERT INTO dw.t SELECT user_id, amt FROM ods.orders "
        "QUALIFY SUM(amt) OVER (PARTITION BY user_id) > 100"
    )
    lineage = _lineage(sql)

    assert lineage["scopes"]["ROOT"]["role"] == "filter"
    profile = build_semantic_profile(
        to_lineage_dict(parse_scope_lineage(sql, "qualify", schema=SCHEMA))
    )
    assert profile["output_shape"]["key_confidence"] != "proven"


def test_rank_pinned_to_one_dedups_but_proves_no_key():
    """``rank() = 1`` keeps every tie, so it is a dedup without a unique key."""
    sql = (
        "INSERT INTO dw.t SELECT user_id, name FROM ods.users "
        "QUALIFY RANK() OVER (PARTITION BY user_id ORDER BY updated_at DESC) = 1"
    )
    profile = build_semantic_profile(
        to_lineage_dict(parse_scope_lineage(sql, "qualify", schema=SCHEMA))
    )

    assert profile["output_shape"]["shape"] == "deduplicated"
    assert profile["output_shape"]["candidate_keys"] == []


def test_the_subquery_form_of_the_dedup_is_unchanged():
    """Sentinel: the hand-written equivalent keeps its dedup reading."""
    sql = (
        "INSERT INTO dw.dedup_users SELECT user_id, name FROM ("
        "SELECT user_id, name, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY updated_at DESC)"
        " AS _w FROM ods.users) _t WHERE _w = 1"
    )
    lineage = _lineage(sql)
    profile = build_semantic_profile(
        to_lineage_dict(parse_scope_lineage(sql, "qualify", schema=SCHEMA))
    )

    assert lineage["scopes"]["subq:_t"]["role"] == "dedup"
    assert profile["output_shape"]["candidate_keys"] == ["user_id"]
    assert profile["output_shape"]["key_confidence"] == "proven"
