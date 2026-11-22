"""An equality pin fixes one input's column, not every column of that name (audit WP2c).

``WHERE a.status = 'ACTIVE' ... GROUP BY a.user_id, b.status`` pins ``a.status``; the
grouping key ``b.status`` still varies, so the output is one row per ``(user_id,
status)``. The pin used to be recorded by bare column name and matched against keys by
bare name, so ``b.status`` left the key set and the target was proven unique by
``user_id`` alone. Pins and keys are now compared by the input they read
(``input_ref_id``, falling back to the field's ``scope``):

- a column the engine resolved as ``AMBIGUOUS`` / ``UNKNOWN`` pins nothing;
- in a self join the two aliases share a ``scope`` and only ``input_ref_id`` tells them
  apart;
- a pin carried up from a lower CTE on the driving path only applies to keys read from
  that driving FROM item, and only when every scope on the way passes the column through
  from that very input;
- the window-intent rule's "ORDER BY a pinned column" test reads the same identity.

Every fixture is synthetic.
"""

from __future__ import annotations

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {
    "ods.users": ["user_id", "status", "dt", "flag"],
    "ods.orders": ["order_id", "user_id", "parent_id", "status", "dt"],
}


def _profile(sql: str, schema: dict | None = SCHEMA) -> dict:
    return build_semantic_profile(to_lineage_dict(parse_scope_lineage(sql, "t", schema=schema)))


def _keys(sql: str, schema: dict | None = SCHEMA) -> tuple[list[str], str]:
    shape = _profile(sql, schema)["output_shape"]
    return shape["candidate_keys"], shape["key_confidence"]


def _intents(node: object, found: set[str] | None = None) -> set[str]:
    found = set() if found is None else found
    if isinstance(node, dict):
        if "intent" in node and "consumed_by" in node:
            found.add(str(node["intent"]))
        for value in node.values():
            _intents(value, found)
    elif isinstance(node, list):
        for value in node:
            _intents(value, found)
    return found


JOINED = (
    "INSERT OVERWRITE TABLE dw.t_out SELECT a.user_id, b.status, COUNT(*) AS cnt "
    "FROM ods.users a LEFT JOIN ods.orders b ON a.user_id = b.user_id "
    "WHERE {predicate} GROUP BY a.user_id, b.status"
)


@pytest.mark.parametrize("schema", [SCHEMA, None], ids=["schema", "no_schema"])
def test_a_pin_on_one_table_does_not_drop_the_other_tables_key(schema) -> None:
    keys, _ = _keys(JOINED.format(predicate="a.status = 'ACTIVE'"), schema)
    assert keys == ["user_id", "status"]


@pytest.mark.parametrize("schema", [SCHEMA, None], ids=["schema", "no_schema"])
def test_an_ambiguous_column_pins_nothing(schema) -> None:
    keys, _ = _keys(JOINED.format(predicate="status = 'PAID'"), schema)
    assert keys != ["user_id"]


def test_a_self_join_pin_stays_on_its_own_alias() -> None:
    keys, _ = _keys(
        "INSERT OVERWRITE TABLE dw.t_out SELECT a.user_id, b.status, COUNT(*) AS cnt "
        "FROM ods.orders a JOIN ods.orders b ON a.parent_id = b.order_id "
        "WHERE a.status = 'PAID' GROUP BY a.user_id, b.status"
    )
    assert keys != ["user_id"]


def test_a_driving_ctes_pin_does_not_drop_a_joined_tables_key() -> None:
    keys, _ = _keys(
        "INSERT OVERWRITE TABLE dw.t_out "
        "WITH p AS (SELECT user_id, status FROM ods.orders WHERE status = 'PAID') "
        "SELECT x.user_id, a.status, COUNT(*) AS cnt FROM p x "
        "JOIN ods.users a ON a.user_id = x.user_id GROUP BY x.user_id, a.status"
    )
    assert keys != ["user_id"]


def test_ordering_by_another_tables_column_is_not_ordering_by_a_pinned_one() -> None:
    profile = _profile(
        "INSERT OVERWRITE TABLE dw.t SELECT user_id, dt FROM (SELECT a.user_id, b.dt, "
        "row_number() over (partition by a.user_id order by b.dt desc) rn "
        "FROM ods.users a JOIN ods.orders b ON a.user_id = b.user_id "
        "WHERE a.dt = '20260101') x WHERE rn = 1"
    )
    assert "keep_arbitrary_per_group" not in _intents(profile)


# ------------------------------------------------------------------- sentinels


def test_sentinel_a_pin_on_the_keys_own_table_still_drops_it() -> None:
    keys, confidence = _keys(JOINED.format(predicate="b.status = 'PAID'"))
    assert (keys, confidence) == (["user_id"], "proven")


def test_sentinel_a_pinned_grouping_column_of_the_same_alias_is_still_dropped() -> None:
    keys, confidence = _keys(
        "INSERT OVERWRITE TABLE dw.t_out SELECT a.dt, a.user_id, COUNT(*) AS cnt "
        "FROM ods.users a JOIN ods.orders b ON a.user_id = b.user_id "
        "WHERE a.dt = '20260101' GROUP BY a.dt, a.user_id"
    )
    assert (keys, confidence) == (["user_id"], "proven")


def test_sentinel_a_driving_ctes_pin_still_drops_the_key_read_from_it() -> None:
    keys, confidence = _keys(
        "INSERT OVERWRITE TABLE dw.t_out "
        "WITH p AS (SELECT user_id, status FROM ods.orders WHERE status = 'PAID') "
        "SELECT x.user_id, x.status, COUNT(*) AS cnt FROM p x "
        "JOIN ods.users a ON a.user_id = x.user_id GROUP BY x.user_id, x.status"
    )
    assert (keys, confidence) == (["user_id"], "proven")


def test_sentinel_a_driving_subquery_pinning_dt_still_drops_dt() -> None:
    keys, confidence = _keys(
        "INSERT OVERWRITE TABLE dw.t_out SELECT x.dt, x.user_id, COUNT(*) AS cnt FROM "
        "(SELECT dt, user_id FROM ods.orders WHERE dt = '20260101') x GROUP BY x.dt, x.user_id"
    )
    assert (keys, confidence) == (["user_id"], "proven")


def test_sentinel_ordering_by_the_pinned_column_itself_orders_nothing() -> None:
    profile = _profile(
        "INSERT OVERWRITE TABLE dw.t SELECT user_id, dt FROM (SELECT a.user_id, b.dt, "
        "row_number() over (partition by a.user_id order by b.dt desc) rn "
        "FROM ods.users a JOIN ods.orders b ON a.user_id = b.user_id "
        "WHERE b.dt = '20260101') x WHERE rn = 1"
    )
    assert _intents(profile) == {"keep_arbitrary_per_group"}
