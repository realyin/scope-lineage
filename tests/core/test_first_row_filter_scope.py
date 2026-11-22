"""Which ``rn = 1`` filter proves which rows unique (audit 2026-11-21, WP2a / WP2b / WP2h).

A ``row_number() ... = 1`` filter proves *one* relation unique by the window's
partition: the rows the filter actually reads. Three places borrowed it for rows it
never touched:

1. **WP2a -- the fan-out rule.** A JOIN's right side was proven unique by any ``= 1``
   filter on the window, wherever it sat: a sibling CTE that filters ``ranked`` proved a
   bare ``LEFT JOIN ranked r`` unique, and ``WHERE r.rn = 1`` proved a second alias
   ``r2`` of the same CTE unique too. Only a filter whose ``rn`` column is read through
   *this* join's right input (its ``input_ref_id``) counts now, in the WHERE as in the
   ON clause. The three other readers of the same helper (the window-intent rule among
   them) ask whether anybody keeps the first row, and are unchanged.
2. **WP2b -- the predicate test.** ``rn = 1`` nested under OR, NOT or CASE keeps more
   than one row per partition; only a top-level AND conjunct counts.
3. **WP2h -- ROOT's own grain.** ``FROM orders o JOIN ranked r ... WHERE r.rn = 1``
   writes one row per order, not one per user: the window deduplicates the joined side.
   ROOT's output is deduplicated by a window only when the window sits on ROOT's driving
   FROM-item path.

Every fixture is synthetic.
"""

from __future__ import annotations

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {
    "ods.users": ["user_id", "user_name", "ts", "is_vip"],
    "ods.orders": ["order_id", "user_id", "buyer_id"],
    "ods.dept": ["user_id", "dept"],
}

RANKED = (
    "WITH ranked AS (SELECT user_id, user_name, "
    "row_number() over (partition by user_id order by ts desc) rn FROM ods.users)"
)


def _profile(sql: str) -> dict:
    return build_semantic_profile(to_lineage_dict(parse_scope_lineage(sql, "t", schema=SCHEMA)))


def _risks(profile: dict) -> dict[str, dict]:
    return {
        f"{item['right']}@{item['logic_block_id']}": item
        for item in profile["output_shape"]["fan_out_risks"]
    }


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


# ------------------------------------------------------------------------- WP2a


def test_a_sibling_ctes_filter_does_not_prove_the_unfiltered_join_unique() -> None:
    risks = _risks(
        _profile(
            f"INSERT OVERWRITE TABLE dw.t_out {RANKED}, "
            "latest AS (SELECT user_id, user_name FROM ranked WHERE rn = 1) "
            "SELECT o.order_id, r.user_name, l.user_name AS latest_name FROM ods.orders o "
            "LEFT JOIN ranked r ON o.user_id = r.user_id "
            "LEFT JOIN latest l ON o.user_id = l.user_id"
        )
    )
    assert risks["cte:ranked@logic:ROOT:join:001"]["status"] != "safe"
    # The CTE that does filter is still unique: a different path proves it.
    assert risks["cte:latest@logic:ROOT:join:002"]["status"] == "safe"


def test_a_where_on_one_alias_does_not_prove_another_alias_unique() -> None:
    risks = _risks(
        _profile(
            f"INSERT OVERWRITE TABLE dw.t_out {RANKED} "
            "SELECT o.order_id, r.user_name, r2.user_name AS n2 FROM ods.orders o "
            "LEFT JOIN ranked r ON o.user_id = r.user_id "
            "LEFT JOIN ranked r2 ON o.buyer_id = r2.user_id WHERE r.rn = 1"
        )
    )
    assert risks["cte:ranked@logic:ROOT:join:001"]["status"] == "safe"
    assert risks["cte:ranked@logic:ROOT:join:002"]["status"] != "safe"


def test_an_on_clause_naming_another_alias_does_not_prove_this_join_unique() -> None:
    risks = _risks(
        _profile(
            f"INSERT OVERWRITE TABLE dw.t_out {RANKED} "
            "SELECT o.order_id, r.user_name, r2.user_name AS n2 FROM ods.orders o "
            "LEFT JOIN ranked r ON o.user_id = r.user_id AND r.rn = 1 "
            "LEFT JOIN ranked r2 ON o.buyer_id = r2.user_id AND r.rn = 1"
        )
    )
    assert risks["cte:ranked@logic:ROOT:join:001"]["status"] == "safe"
    assert risks["cte:ranked@logic:ROOT:join:002"]["status"] != "safe"


def test_sentinel_a_where_on_the_joined_alias_still_proves_it_unique() -> None:
    risks = _risks(
        _profile(
            f"INSERT OVERWRITE TABLE dw.t_out {RANKED} "
            "SELECT o.order_id, r.user_name FROM ods.orders o "
            "LEFT JOIN ranked r ON o.user_id = r.user_id WHERE r.rn = 1"
        )
    )
    assert risks["cte:ranked@logic:ROOT:join:001"]["status"] == "safe"


def test_sentinel_an_on_clause_on_the_joined_alias_still_proves_it_unique() -> None:
    risks = _risks(
        _profile(
            f"INSERT OVERWRITE TABLE dw.t_out {RANKED} "
            "SELECT o.order_id, r.user_name FROM ods.orders o "
            "LEFT JOIN ranked r ON o.user_id = r.user_id AND r.rn = 1"
        )
    )
    assert risks["cte:ranked@logic:ROOT:join:001"]["status"] == "safe"


def test_sentinel_a_plain_dedup_keeps_its_window_intent() -> None:
    profile = _profile(
        f"INSERT OVERWRITE TABLE dw.t_out {RANKED} SELECT user_id, user_name FROM ranked WHERE rn = 1"
    )
    assert _intents(profile) == {"keep_latest_per_group"}
    assert profile["output_shape"]["candidate_keys"] == ["user_id"]
    assert profile["output_shape"]["key_confidence"] == "proven"


def test_sentinel_the_window_intent_ignores_which_join_reads_the_filter() -> None:
    profile = _profile(
        f"INSERT OVERWRITE TABLE dw.t_out {RANKED} "
        "SELECT o.order_id, r.user_name, r2.user_name AS n2 FROM ods.orders o "
        "LEFT JOIN ranked r ON o.user_id = r.user_id "
        "LEFT JOIN ranked r2 ON o.buyer_id = r2.user_id WHERE r.rn = 1"
    )
    assert _intents(profile) == {"keep_latest_per_group"}


# ------------------------------------------------------------------------- WP2b

NESTED = (
    "INSERT OVERWRITE TABLE dw.t_out SELECT o.order_id, u.user_name FROM ods.orders o "
    "LEFT JOIN (SELECT user_id, user_name, rn FROM (SELECT user_id, user_name, is_vip, "
    "row_number() over (partition by user_id order by ts desc) rn FROM ods.users) x "
    "WHERE {predicate}) u ON o.user_id = u.user_id"
)


def _nested_status(predicate: str) -> str:
    risks = _profile(NESTED.format(predicate=predicate))["output_shape"]["fan_out_risks"]
    assert len(risks) == 1, risks
    return risks[0]["status"]


def test_rn_equals_one_under_an_or_does_not_keep_one_row() -> None:
    assert _nested_status("rn = 1 OR is_vip = 'Y'") != "safe"


def test_rn_equals_one_inside_a_case_does_not_keep_one_row() -> None:
    assert _nested_status("CASE WHEN rn = 1 THEN 1 ELSE 1 END = 1") != "safe"


def test_rn_equals_one_under_a_not_does_not_keep_one_row() -> None:
    assert _nested_status("NOT (rn = 1 AND is_vip = 'Y')") != "safe"


def test_sentinel_rn_equals_one_as_an_and_conjunct_still_keeps_one_row() -> None:
    assert _nested_status("rn = 1 AND is_vip = 'Y'") == "safe"
    assert _nested_status("(rn = 1) AND is_vip = 'Y'") == "safe"


# ------------------------------------------------------------------------- WP2h


def _shape(sql: str) -> dict:
    return _profile(sql)["output_shape"]


def test_a_window_on_the_inner_joined_side_does_not_dedup_root() -> None:
    shape = _shape(
        f"INSERT OVERWRITE TABLE dw.t_out {RANKED} "
        "SELECT o.order_id, r.user_id, r.user_name FROM ods.orders o "
        "JOIN ranked r ON o.user_id = r.user_id WHERE r.rn = 1"
    )
    assert not (shape["candidate_keys"] == ["user_id"] and shape["key_confidence"] == "proven")
    assert shape["grain"]["basis"] != "window_partition"


def test_a_window_on_the_left_joined_side_does_not_dedup_root() -> None:
    shape = _shape(
        f"INSERT OVERWRITE TABLE dw.t_out {RANKED} "
        "SELECT o.order_id, r.user_id, r.user_name FROM ods.orders o "
        "LEFT JOIN ranked r ON o.user_id = r.user_id WHERE r.rn = 1"
    )
    assert not (shape["candidate_keys"] == ["user_id"] and shape["key_confidence"] == "proven")
    assert shape["grain"]["basis"] != "window_partition"
    # The filter still proves the join's right side unique (WP2a sentinel).
    assert [risk["status"] for risk in shape["fan_out_risks"]] == ["safe"]


def test_sentinel_a_window_on_the_driving_table_still_dedups_root() -> None:
    shape = _shape(
        f"INSERT OVERWRITE TABLE dw.t_out {RANKED} SELECT user_id, user_name FROM ranked WHERE rn = 1"
    )
    assert shape["grain"]["basis"] == "window_partition"
    assert (shape["candidate_keys"], shape["key_confidence"]) == (["user_id"], "proven")


def test_sentinel_a_semi_join_subquery_does_not_hide_the_driving_window() -> None:
    # The IN subquery is one of ROOT's inputs too; the FROM item is still ``ranked``.
    shape = _shape(
        f"INSERT OVERWRITE TABLE dw.t_out {RANKED} SELECT user_id, user_name FROM ranked "
        "WHERE rn = 1 AND user_id IN (SELECT user_id FROM ods.dept)"
    )
    assert shape["grain"]["basis"] == "window_partition"
    assert (shape["candidate_keys"], shape["key_confidence"]) == (["user_id"], "proven")


def test_sentinel_a_driving_window_with_a_safe_join_on_root_still_dedups_root() -> None:
    shape = _shape(
        f"INSERT OVERWRITE TABLE dw.t_out {RANKED} "
        "SELECT r.user_id, r.user_name, d.dept FROM ranked r "
        "LEFT JOIN (SELECT user_id, max(dept) dept FROM ods.dept GROUP BY user_id) d "
        "ON r.user_id = d.user_id WHERE r.rn = 1"
    )
    assert shape["grain"]["basis"] == "window_partition"
    assert (shape["candidate_keys"], shape["key_confidence"]) == (["user_id"], "proven")
    assert [risk["status"] for risk in shape["fan_out_risks"]] == ["safe"]
