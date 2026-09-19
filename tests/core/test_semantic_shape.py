"""Behavioural tests for the semantic profile's ``output_shape`` and ``stages`` (WI-1b).

Three rules live here: R2 (output shape), R3 (grain, candidate keys, per-JOIN fan-out
risk) and R6 (window intent). Each of them is an *inference*, so every rule gets both a
positive case and a "looks like it but is not provable" negative case -- the plan's own
warning is that a wrongly granted ``safe`` is worse than an honest ``unknown``.

One deliberate deviation from the WI-1b brief is asserted here rather than hidden: the
brief specifies ``right-side key set >= join keys -> safe``, which is inverted. Grouping
by ``(a, b)`` and joining on ``a`` alone leaves many right rows per left row, i.e. the
classic fan-out; grouping by ``a`` and joining on ``(a, b)`` cannot fan out. The
implementation therefore proves ``right-side unique key set <= join keys``, and the
tests below pin both directions so the choice cannot drift back silently.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.metadata.schema_metadata import load_schema
from scope_lineage.metadata.target_table_metadata import load_target_table_metadata
from scope_lineage.render.semantic_markdown import render_semantic_markdown
from scope_lineage.render.semantic_profile import FAN_OUT_PATHS, build_semantic_profile
from scope_lineage.scope.scope_builder import parse_scope_lineage

from .statement_document import build_statement_documents


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "examples"
FIXTURES = Path(__file__).parent / "fixtures"

SCHEMA = {
    "ods.base": ["id", "b", "dt"],
    "ods.e": ["id", "v", "ts", "dt"],
    "ods.t": ["a", "b", "x"],
    "ods.orders": ["customer_id", "amount", "dt"],
    "ods.users": ["id", "name", "dt"],
    "ods.a": ["id", "amount"],
    "ods.b": ["id", "amount"],
    "ods.dim": ["id", "name"],
}


def _document(sql: str, task_id: str = "shape_case", schema=None) -> dict:
    return to_lineage_dict(
        parse_scope_lineage(sql, task_id, schema=schema if schema is not None else SCHEMA)
    )


def _shape(sql: str, schema=None) -> dict:
    return build_semantic_profile(_document(sql, schema=schema))["output_shape"]


def _customer_profile_documents() -> tuple[dict, dict]:
    result = parse_scope_lineage(
        (EXAMPLES / "sql" / "customer_profile_daily.sql").read_text(encoding="utf-8"),
        "customer_profile_daily",
        schema=load_schema(str(EXAMPLES / "metadata" / "schema_info.json")),
        target_metadata=load_target_table_metadata(
            str(EXAMPLES / "metadata" / "target_tables")
        ),
    )
    return build_statement_documents(result)


def _stage(profile: dict, scope_id: str) -> dict:
    return next(item for item in profile["stages"] if item["scope_id"] == scope_id)


def _actions(profile: dict, scope_id: str, action_type: str) -> list[dict]:
    return [
        action
        for action in _stage(profile, scope_id)["actions"]
        if action["type"] == action_type
    ]


def _risk(shape: dict, logic_block_id: str) -> dict:
    return next(
        item for item in shape["fan_out_risks"] if item["logic_block_id"] == logic_block_id
    )


# ------------------------------------------------------------------ R2: output shape


def test_a_root_group_by_makes_the_output_aggregated() -> None:
    shape = _shape(
        "INSERT INTO mart.t SELECT customer_id, SUM(amount) AS total "
        "FROM ods.orders GROUP BY customer_id"
    )
    assert shape["shape"] == "aggregated"
    assert shape["shape_evidence"] == ["logic:ROOT:group_by:001"]
    assert shape["grain"] == {
        "keys": [
            {
                "scope_id": "ROOT",
                "name": "customer_id",
                "expression": "`orders`.`customer_id`",
                "physical_sources": [{"table": "ods.orders", "column": "customer_id"}],
            }
        ],
        "basis": "group_by",
        "via_scopes": [],
        "confidence": "structural",
        "evidence": ["logic:ROOT:group_by:001"],
    }
    # WI-1e: the published key is the *target* column the GROUP BY key lands on
    assert shape["candidate_keys"] == ["customer_id"]
    assert shape["unexposed_keys"] == []
    assert shape["key_confidence"] == "proven"
    assert shape["tag"] == "结构推断"


def test_an_aggregate_without_group_by_is_aggregated_with_a_single_row_grain() -> None:
    """B10: an empty grouping set is a proof of uniqueness, not a missing key list.

    The whole rule, with its negatives, lives in
    ``test_grain_pinned_and_single_row.py``; this keeps R2's own answer beside R2's
    other shapes, because the shape stays ``aggregated`` while the grain changes.
    """
    shape = _shape("INSERT INTO mart.t SELECT COUNT(*) AS n FROM ods.orders")
    assert shape["shape"] == "aggregated"
    assert shape["grain"]["keys"] == []
    assert shape["grain"]["basis"] == "single_row"
    assert shape["candidate_keys"] == []
    assert shape["key_confidence"] == "proven"


def test_root_distinct_is_deduplicated() -> None:
    shape = _shape("INSERT INTO mart.t SELECT DISTINCT customer_id FROM ods.orders")
    assert shape["shape"] == "deduplicated"
    assert shape["shape_evidence"] == ["logic:ROOT:distinct:001"]
    # DISTINCT proves uniqueness over the whole projection, so the projection *is* the
    # key set -- pierced to the physical column, because the projection is a plain one.
    assert shape["grain"]["basis"] == "distinct"
    assert [item["name"] for item in shape["grain"]["keys"]] == ["customer_id"]
    assert shape["grain"]["keys"][0]["physical_sources"] == [
        {"table": "ods.orders", "column": "customer_id"}
    ]
    assert shape["candidate_keys"] == ["customer_id"]
    assert shape["key_confidence"] == "proven"


def test_root_filtering_a_rank_to_one_is_deduplicated_on_the_partition_keys() -> None:
    shape = _shape(
        "INSERT INTO mart.t WITH r AS ("
        "  SELECT id, v, RANK() OVER (PARTITION BY id ORDER BY ts) AS rk FROM ods.e"
        ") SELECT id, v FROM r WHERE rk = 1"
    )
    assert shape["shape"] == "deduplicated"
    assert [(item["scope_id"], item["name"]) for item in shape["grain"]["keys"]] == [
        ("cte:r", "id")
    ]
    assert shape["grain"]["basis"] == "window_partition"
    assert shape["candidate_keys"] == ["id"]
    assert "logic:cte:r:window:001" in shape["shape_evidence"]


def test_a_root_reading_only_union_scopes_is_a_union_merge() -> None:
    shape = _shape(
        "INSERT INTO mart.t SELECT id, amount FROM ods.a "
        "UNION ALL SELECT id, amount FROM ods.b"
    )
    assert shape["shape"] == "union_merge"
    assert shape["grain"]["basis"] == "unknown"
    assert shape["grain"]["keys"] == []
    assert shape["candidate_keys"] == []


def test_a_root_with_a_join_is_an_enriched_projection() -> None:
    lineage, _ = _customer_profile_documents()
    shape = build_semantic_profile(lineage)["output_shape"]
    assert shape["shape"] == "enriched_projection"
    assert shape["shape_evidence"] == ["logic:ROOT:join:001", "logic:ROOT:join:002"]
    assert shape["grain"]["basis"] == "driving_table_rows"
    # A physical table declares no primary key, so the grain has a basis but no keys.
    assert shape["grain"]["keys"] == []
    assert shape["partition_columns"] == ["dt"]


def test_a_filter_only_root_is_a_filtered_projection() -> None:
    shape = _shape("INSERT INTO mart.t SELECT id, name FROM ods.users WHERE dt = '20260101'")
    assert shape["shape"] == "filtered_projection"
    assert shape["grain"] == {
        "keys": [],
        "basis": "driving_table_rows",
        "via_scopes": [],
        "confidence": "structural",
        "evidence": ["ods.users"],
    }
    assert shape["fan_out_risks"] == []
    assert shape["key_confidence"] == "none"


def test_a_comma_join_drives_from_its_from_item_not_from_both_tables() -> None:
    """``FROM a, d WHERE a.id = d.id`` names ``d`` as the JOIN's right input, so ``a``
    is the FROM item -- the same answer an explicit ``LEFT JOIN`` gets."""
    shape = _shape(
        "INSERT INTO mart.t SELECT b.id, d.name FROM ods.base b, ods.dim d WHERE b.id = d.id"
    )
    assert shape["grain"]["basis"] == "driving_table_rows"
    assert shape["grain"]["evidence"] == ["ods.base"]
    assert shape["grain"]["keys"] == []
    # the right side is a physical table, so nothing proves it unique by the join key
    assert shape["candidate_keys"] == []


# ----------------------------------------------- R3: the driving input, pierced (WI-1c)


def _pierced(sql: str, schema=None) -> dict:
    return _shape(sql, schema=schema)["grain"]


def test_a_filter_only_subquery_in_from_pierces_to_its_physical_table() -> None:
    """The commonest wide-table shape: ROOT reads no table, but the main one is provable."""
    grain = _pierced(
        "INSERT INTO mart.t SELECT t1.id, d.name "
        "FROM (SELECT * FROM ods.base WHERE dt = '1') t1 "
        "LEFT JOIN ods.dim d ON t1.id = d.id"
    )
    assert grain["basis"] == "driving_table_rows"
    assert grain["via_scopes"] == ["subq:t1"]
    assert grain["evidence"] == ["subq:t1", "ods.base"]


def test_the_pierce_walks_every_row_preserving_layer_and_records_the_path() -> None:
    grain = _pierced(
        "INSERT INTO mart.t SELECT t1.id, d.name FROM ("
        "  SELECT * FROM (SELECT * FROM ods.base WHERE dt = '1') inner1 "
        "  WHERE id IS NOT NULL"
        ") t1 LEFT JOIN ods.dim d ON t1.id = d.id"
    )
    assert grain["basis"] == "driving_table_rows"
    # the outermost scope is the one ROOT reads through; the path keeps both layers
    assert grain["via_scopes"] == ["subq:t1", "subq:inner1"]
    assert grain["evidence"] == ["subq:t1", "subq:inner1", "ods.base"]


def test_a_directly_read_driving_table_reports_an_empty_via_scopes() -> None:
    grain = _pierced(
        "INSERT INTO mart.t SELECT b.id, d.name FROM ods.base b "
        "LEFT JOIN ods.dim d ON b.id = d.id"
    )
    assert grain["basis"] == "driving_table_rows"
    assert grain["via_scopes"] == []
    assert grain["evidence"] == ["ods.base"]


def test_an_aggregating_driving_subquery_reports_its_group_by_keys() -> None:
    """WI-1d: an aggregating FROM item is not an obstacle, it is the answer.

    Before the walk recursed, this stopped at "驱动输入 subq:t1 非保行 scope" -- true,
    and useless: the subquery states the grain outright.
    """
    grain = _pierced(
        "INSERT INTO mart.t SELECT t1.id, d.name "
        "FROM (SELECT id, SUM(b) AS sb FROM ods.base GROUP BY id) t1 "
        "LEFT JOIN ods.dim d ON t1.id = d.id"
    )
    assert grain["basis"] == "group_by"
    assert [(item["scope_id"], item["name"]) for item in grain["keys"]] == [
        ("subq:t1", "id")
    ]
    # ROOT reads the aggregating scope itself, so nothing was pierced *through*
    assert grain["via_scopes"] == []
    assert grain["evidence"] == ["logic:subq:t1:group_by:001"]


def test_a_driving_subquery_that_joins_walks_on_to_its_own_from_item() -> None:
    """WI-1d: a JOIN inside the FROM item hands the question to *its* FROM item.

    The join itself is not lost -- it joins the risk list, tagged with the scope it sits
    in, so the reader sees that the driving rows passed through an unproven join.
    """
    shape = _shape(
        "INSERT INTO mart.t SELECT t1.id, e.v FROM ("
        "  SELECT a.id FROM ods.base a JOIN ods.dim d ON a.id = d.id"
        ") t1 LEFT JOIN ods.e e ON t1.id = e.id"
    )
    assert shape["grain"]["basis"] == "driving_table_rows"
    assert shape["grain"]["via_scopes"] == ["subq:t1"]
    assert shape["grain"]["evidence"] == ["subq:t1", "ods.base"]
    assert [risk["scope_id"] for risk in shape["fan_out_risks"]] == ["ROOT", "subq:t1"]
    assert shape["key_confidence"] == "none"


def test_an_ambiguous_from_item_stays_unknown() -> None:
    """A semi-join subquery in WHERE is a ROOT input and is not a JOIN right side, so
    two candidates remain and nothing proves which one the FROM item is."""
    grain = _pierced(
        "INSERT INTO mart.t SELECT id FROM ods.base WHERE id IN (SELECT id FROM ods.dim)"
    )
    assert grain["basis"] == "unknown"
    assert grain["evidence"] == ["ROOT 的 FROM 项无法唯一确定（候选：ods.base、ods.dim）"]


def test_candidate_keys_come_from_the_pierced_table_when_every_join_is_safe() -> None:
    shape = _shape(
        "INSERT INTO mart.t WITH agg AS (SELECT a, SUM(x) AS s FROM ods.t GROUP BY a) "
        "SELECT t1.id, agg.s FROM (SELECT * FROM ods.base WHERE dt = '1') t1 "
        "LEFT JOIN agg ON t1.id = agg.a"
    )
    assert [item["status"] for item in shape["fan_out_risks"]] == ["safe"]
    # WI-1e: the join key pierces to `ods.base.id`, and what is published is the target
    # column that physical key is written to
    assert shape["candidate_keys"] == ["id"]


def test_the_pierced_table_takes_the_driving_role_and_keeps_its_other_roles() -> None:
    profile = build_semantic_profile(
        _document(
            "INSERT INTO mart.t SELECT t1.id, d.name "
            "FROM (SELECT * FROM ods.base WHERE dt = '1') t1 "
            "LEFT JOIN ods.dim d ON t1.id = d.id"
        )
    )
    roles = {item["table"]: item["roles"] for item in profile["inputs"]}
    assert roles["ods.base"] == ["driving", "enrich"]
    assert roles["ods.dim"] == ["enrich"]
    # B2: the sentence opens with the row source and demotes what ROOT only reads.
    assert profile["task"]["structural_summary"].startswith(
        "行来源 ods.base（经 subq:t1）；补充 ods.dim；"
    )


def test_a_merge_statement_reports_an_unknown_shape_rather_than_guessing() -> None:
    lineage = json.loads(
        (FIXTURES / "lineage_contract" / "merge" / "lineage.json").read_text(
            encoding="utf-8"
        )
    )
    shape = build_semantic_profile(lineage)["output_shape"]
    assert shape["shape"] == "unknown"
    assert shape["grain"]["basis"] == "unknown"
    assert shape["grain"]["keys"] == []
    assert shape["candidate_keys"] == []


# ------------------------------------------------------- R3: fan-out risk, three ways


def test_a_right_side_grouped_by_the_join_key_is_safe() -> None:
    lineage, _ = _customer_profile_documents()
    shape = build_semantic_profile(lineage)["output_shape"]
    risk = _risk(shape, "logic:ROOT:join:002")

    assert risk["status"] == "safe"
    assert risk["right"] == "cte:order_summary"
    assert risk["join_type"] == "LEFT_OUTER"
    assert "GROUP BY" in risk["reason"]


def test_a_right_side_grouped_more_finely_than_the_join_key_is_a_risk() -> None:
    """GROUP BY (a, b) joined on `a` alone leaves many right rows per left row."""
    shape = _shape(
        "INSERT INTO mart.t WITH agg AS ("
        "  SELECT a, b, SUM(x) AS s FROM ods.t GROUP BY a, b"
        ") SELECT base.id, agg.s FROM ods.base base LEFT JOIN agg ON base.id = agg.a"
    )
    risk = _risk(shape, "logic:ROOT:join:001")
    assert risk["status"] == "risk"
    assert shape["candidate_keys"] == []


def test_a_right_side_grouped_more_coarsely_than_the_join_key_is_safe() -> None:
    """GROUP BY (a) joined on (a, b) cannot fan out -- the extra key only filters.

    This is the case the WI-1b brief asked to report as ``risk``; see the module
    docstring for why the implementation proves the opposite direction.
    """
    shape = _shape(
        "INSERT INTO mart.t WITH agg AS ("
        "  SELECT a, MAX(b) AS b, SUM(x) AS s FROM ods.t GROUP BY a"
        ") SELECT base.id, agg.s FROM ods.base base "
        "LEFT JOIN agg ON base.id = agg.a AND base.b = agg.b"
    )
    assert _risk(shape, "logic:ROOT:join:001")["status"] == "safe"


GROUPED_THREE_WAYS = (
    "INSERT INTO mart.t WITH agg AS ("
    "  SELECT CASE WHEN x > 0 THEN a ELSE b END AS k1, b AS k2,"
    "         SUBSTRING(a, 1, 3) AS k3, SUM(x) AS s"
    "  FROM ods.t"
    "  GROUP BY CASE WHEN x > 0 THEN a ELSE b END, b, SUBSTRING(a, 1, 3)"
    ") SELECT base.id, agg.s FROM ods.base base "
    "LEFT JOIN agg ON base.id = agg.k1 AND base.b = agg.k2"
)


def test_a_third_group_by_key_is_a_risk_even_when_it_pierces_to_covered_columns() -> None:
    """WI-2.1d item 1: the subset test is asked of the logical keys, not the physical ones.

    ``k3`` reads only columns ``k1`` already reads, so on the pierced sets the right
    side's key set looks covered by the two join keys -- and the join was called safe
    while the right side held one row per ``(k1, k2, k3)``, i.e. many per ``(k1, k2)``.
    """
    shape = _shape(GROUPED_THREE_WAYS)
    risk = _risk(shape, "logic:ROOT:join:001")

    assert risk["status"] == "risk"
    assert "k1、k2、k3" in risk["reason"]
    assert shape["key_confidence"] == "none"
    assert shape["candidate_keys"] == []


def test_the_pierced_columns_stay_in_the_fan_out_sentence_as_a_note() -> None:
    reason = _risk(_shape(GROUPED_THREE_WAYS), "logic:ROOT:join:001")["reason"]

    assert "ods.t.a" in reason and "键的物理来源" in reason


def test_a_group_by_expression_joined_by_the_name_it_is_projected_as_is_safe() -> None:
    """One GROUP BY item is one key, and the ON clause names it by its output column."""
    shape = _shape(
        "INSERT INTO mart.t WITH agg AS ("
        "  SELECT CASE WHEN x > 0 THEN 'P' ELSE 'N' END AS band, SUM(x) AS s"
        "  FROM ods.t GROUP BY CASE WHEN x > 0 THEN 'P' ELSE 'N' END"
        ") SELECT base.id, agg.s FROM ods.base base LEFT JOIN agg ON base.b = agg.band"
    )
    risk = _risk(shape, "logic:ROOT:join:001")

    assert risk["status"] == "safe"
    assert "右侧按 band GROUP BY" in risk["reason"]


def test_a_row_number_equals_one_right_side_is_safe() -> None:
    lineage, _ = _customer_profile_documents()
    shape = build_semantic_profile(lineage)["output_shape"]
    risk = _risk(shape, "logic:ROOT:join:001")

    assert risk["status"] == "safe"
    assert risk["right"] == "cte:latest_status"
    assert "row_number" in risk["reason"]


def test_a_window_partition_without_an_equals_one_filter_is_a_risk() -> None:
    shape = _shape(
        "INSERT INTO mart.t WITH r AS ("
        "  SELECT id, ROW_NUMBER() OVER (PARTITION BY id ORDER BY ts) AS rn FROM ods.e"
        ") SELECT b.id, r.rn FROM ods.base b LEFT JOIN r ON b.id = r.id"
    )
    assert _risk(shape, "logic:ROOT:join:001")["status"] == "risk"


def test_a_physical_right_side_is_unknown_not_safe() -> None:
    shape = _shape(
        "INSERT INTO mart.t SELECT b.id, d.name FROM ods.base b "
        "LEFT JOIN ods.dim d ON b.id = d.id"
    )
    risk = _risk(shape, "logic:ROOT:join:001")
    assert risk["status"] == "unknown"
    assert risk["reason"] == "物理表无主键事实"
    assert shape["candidate_keys"] == []


def test_candidate_keys_are_the_driving_table_join_keys_when_every_join_is_safe() -> None:
    lineage, _ = _customer_profile_documents()
    shape = build_semantic_profile(lineage)["output_shape"]
    assert shape["candidate_keys"] == ["customer_id"]


def test_candidate_keys_are_empty_when_the_joins_use_different_driving_keys() -> None:
    shape = _shape(
        "INSERT INTO mart.t WITH x AS (SELECT a, SUM(v) AS sv FROM ods.e2 GROUP BY a), "
        "y AS (SELECT b, SUM(v) AS sv FROM ods.e2 GROUP BY b) "
        "SELECT base.id, x.sv, y.sv AS sv2 FROM ods.base base "
        "LEFT JOIN x ON base.id = x.a LEFT JOIN y ON base.b = y.b",
        schema={**SCHEMA, "ods.e2": ["a", "b", "v"]},
    )
    assert [item["status"] for item in shape["fan_out_risks"]] == ["safe", "safe"]
    assert shape["candidate_keys"] == []


# ------------------------------------------------------------------- stages topology


def test_stages_follow_the_scope_graph_with_root_last() -> None:
    lineage, _ = _customer_profile_documents()
    stages = build_semantic_profile(lineage)["stages"]
    assert [item["scope_id"] for item in stages] == [
        "cte:latest_status",
        "cte:order_summary",
        "ROOT",
    ]


def test_a_stage_reports_its_inputs_outputs_and_source_boundary() -> None:
    lineage, _ = _customer_profile_documents()
    stage = _stage(build_semantic_profile(lineage), "cte:latest_status")

    assert stage["name"] == "latest_status"
    assert stage["kind"] == "cte"
    assert stage["role"] == "dedup"
    assert stage["direct_inputs"] == ["ods.customer_status_event"]
    assert stage["direct_source_tables"] == ["ods.customer_status_event"]
    assert stage["upstream_physical_tables"] == ["ods.customer_status_event"]
    assert stage["outputs"] == ["customer_id", "customer_status", "row_num"]
    assert stage["output_count"] == 3


def test_pattern_signature_folds_same_shaped_stages_and_names_no_identifier() -> None:
    sql = (
        "INSERT INTO mart.t WITH x AS (SELECT a, SUM(v) AS s FROM ods.e2 GROUP BY a), "
        "y AS (SELECT b, SUM(v) AS s FROM ods.e2 GROUP BY b) "
        "SELECT base.id, x.s, y.s AS s2 FROM ods.base base "
        "LEFT JOIN x ON base.id = x.a LEFT JOIN y ON base.b = y.b"
    )
    profile = build_semantic_profile(
        _document(sql, schema={**SCHEMA, "ods.e2": ["a", "b", "v"]})
    )
    signatures = {item["scope_id"]: item["pattern_signature"] for item in profile["stages"]}
    assert signatures["cte:x"] == signatures["cte:y"]
    assert signatures["cte:x"] != signatures["ROOT"]
    for signature in signatures.values():
        assert "ods." not in signature and "base" not in signature


def test_stage_actions_restate_filters_joins_and_aggregates() -> None:
    lineage, _ = _customer_profile_documents()
    profile = build_semantic_profile(lineage)

    partition_filter = _actions(profile, "cte:latest_status", "filter")[0]
    assert partition_filter["text"].endswith("（分区过滤）")
    assert "dt = '${bizdate}'" in partition_filter["text"]
    assert partition_filter["evidence"] == "logic:cte:latest_status:filter:001"
    assert partition_filter["tag"] == "SQL事实"
    assert partition_filter["fields"] == [
        {
            "table": "ods.customer_status_event",
            "column": "dt",
            "comment": "Partition date",
        }
    ]

    aggregate = _actions(profile, "cte:order_summary", "aggregate")[0]
    # WI-1f: each call keeps its SQL and gains the structural reading in parentheses.
    # `paid_at` is declared `timestamp`, so MAX over it reads as a time, not a maximum.
    assert aggregate["text"] == (
        "按 customer_id 分组聚合：COUNT(DISTINCT order_id)（去重计数 order_id）、"
        "SUM(CASE WHEN pay_status = 'PAID' THEN pay_amount ELSE 0 END)、"
        "MAX(paid_at)（最晚时间）"
    )
    assert aggregate["evidence"] == "logic:cte:order_summary:group_by:001"

    join = _actions(profile, "ROOT", "join")[0]
    assert join["text"] == (
        # WI-1g item A2: the scope-level key, short because both sides spell it the same
        # way. The pierced columns stay in `fields`.
        "LEFT_OUTER 关联 cte:latest_status，键 customer_id，"
        "附加条件 `status`.`row_num` = 1，"
        # WI-1f: what this join does to the rows it cannot match, one fixed sentence
        # per join type.
        "右侧无匹配时保留左行，右侧字段为空"
    )


def test_a_case_when_action_reuses_the_branch_restatement() -> None:
    lineage, _ = _customer_profile_documents()
    action = _actions(build_semantic_profile(lineage), "ROOT", "case_when")[0]
    assert "'HIGH'" in action["text"]
    assert action["evidence"] == "logic:ROOT:case_when:001"


def test_a_union_scope_reports_one_union_action_not_one_per_column() -> None:
    sql = (
        "INSERT INTO mart.t SELECT id, amount FROM ods.a "
        "UNION ALL SELECT id, amount FROM ods.b"
    )
    profile = build_semantic_profile(_document(sql))
    actions = _actions(profile, "union:main", "union")
    assert len(actions) == 1
    assert actions[0]["text"] == "合并 2 个分支（来自 ods.a、ods.b）"


def test_a_distinct_scope_reports_a_distinct_action() -> None:
    profile = build_semantic_profile(
        _document("INSERT INTO mart.t SELECT DISTINCT customer_id FROM ods.orders")
    )
    assert _actions(profile, "ROOT", "distinct")[0]["evidence"] == (
        "logic:ROOT:distinct:001"
    )


def test_a_having_predicate_becomes_its_own_action() -> None:
    profile = build_semantic_profile(
        _document(
            "INSERT INTO mart.t SELECT customer_id, SUM(amount) AS total FROM ods.orders "
            "GROUP BY customer_id HAVING SUM(amount) > 100"
        )
    )
    assert _actions(profile, "ROOT", "having")


def test_a_lateral_view_action_quotes_the_contract_not_a_guess() -> None:
    profile = build_semantic_profile(
        _document(
            "INSERT INTO mart.t SELECT u.id, t.tag FROM ods.users u "
            "LATERAL VIEW EXPLODE(u.tags) t AS tag",
            schema={"ods.users": ["id", "tags"]},
        )
    )
    action = next(
        item
        for stage in profile["stages"]
        for item in stage["actions"]
        if item["type"] == "lateral_view"
    )
    assert "EXPLODE(u.tags)" in action["text"]
    assert "tag" in action["text"]


# ----------------------------------------------------------------- R6: window intent


WINDOW_INTENT_CASES = (
    (
        "keep_first_per_group",
        "INSERT INTO mart.t WITH r AS ("
        "  SELECT id, v, RANK() OVER (PARTITION BY id ORDER BY ts) AS rk FROM ods.e"
        ") SELECT id, v FROM r WHERE rk = 1",
    ),
    (
        "rank_within_group",
        "INSERT INTO mart.t SELECT id, "
        "DENSE_RANK() OVER (PARTITION BY id ORDER BY ts) AS rk FROM ods.e",
    ),
    (
        "pick_first_in_group",
        "INSERT INTO mart.t SELECT id, "
        "FIRST_VALUE(v) OVER (PARTITION BY id ORDER BY ts) AS fv FROM ods.e",
    ),
    (
        "pick_last_in_group",
        "INSERT INTO mart.t SELECT id, "
        "LAST_VALUE(v) OVER (PARTITION BY id ORDER BY ts) AS lv FROM ods.e",
    ),
    (
        "adjacent_row_offset",
        "INSERT INTO mart.t SELECT id, "
        "LAG(v, 1) OVER (PARTITION BY id ORDER BY ts) AS pv FROM ods.e",
    ),
    (
        "running_aggregate",
        "INSERT INTO mart.t SELECT id, "
        "SUM(v) OVER (PARTITION BY id ORDER BY ts) AS rs FROM ods.e",
    ),
    (
        "other",
        "INSERT INTO mart.t SELECT id, "
        "NTILE(4) OVER (PARTITION BY id ORDER BY ts) AS nt FROM ods.e",
    ),
)


@pytest.mark.parametrize("intent,sql", WINDOW_INTENT_CASES, ids=lambda item: str(item)[:30])
def test_window_intents_follow_r6(intent: str, sql: str) -> None:
    profile = build_semantic_profile(_document(sql))
    windows = [
        action
        for stage in profile["stages"]
        for action in stage["actions"]
        if action["type"] == "window"
    ]
    assert [action["intent"] for action in windows] == [intent]


def test_a_descending_row_number_consumed_by_a_join_keeps_the_latest_row() -> None:
    lineage, _ = _customer_profile_documents()
    profile = build_semantic_profile(lineage)
    window = _actions(profile, "cte:latest_status", "window")[0]

    assert window["intent"] == "keep_latest_per_group"
    assert window["consumed_by"] == "logic:ROOT:join:001"
    assert window["tag"] == "结构推断"
    assert window["text"] == (
        "按 customer_id 分组，按 event_time 降序编号（row_num）；"
        "ROOT 以 row_num = 1 消费，即每组保留最新一条"
    )
    assert {item["column"] for item in window["fields"]} == {"customer_id", "event_time"}


def test_an_unconsumed_ranking_window_says_so_instead_of_claiming_dedup() -> None:
    profile = build_semantic_profile(
        _document(
            "INSERT INTO mart.t WITH r AS ("
            "  SELECT id, ROW_NUMBER() OVER (PARTITION BY id ORDER BY ts) AS rn FROM ods.e"
            ") SELECT b.id, r.rn FROM ods.base b LEFT JOIN r ON b.id = r.id"
        )
    )
    window = _actions(profile, "cte:r", "window")[0]
    assert window["intent"] == "rank_within_group"
    assert window["consumed_by"] is None


# ------------------------------------ partition / order keys are named logically (R6)
#
# A window's restatement says what the SQL was written against. `PARTITION BY band`
# groups by `band` however that column was derived; piercing to the physical columns the
# derived column reads would state a grouping the statement never wrote. The physical
# fact stays in the action's `fields[]`.


def test_a_partition_by_a_derived_column_is_restated_by_that_column() -> None:
    profile = build_semantic_profile(
        _document(
            "INSERT INTO mart.t WITH b AS ("
            "  SELECT customer_id, amount,"
            "         CASE WHEN amount >= 100 THEN 'HIGH' ELSE 'LOW' END AS band"
            "  FROM ods.orders"
            ") SELECT customer_id, SUM(amount) OVER (PARTITION BY band) AS band_total "
            "FROM b"
        )
    )
    window = _actions(profile, "ROOT", "window")[0]

    assert window["text"] == "按 band 分组，计算 SUM（band_total）；组内累计聚合"
    assert "amount" not in window["text"]
    # The physical pass-through is still published, just not as the grouping key.
    assert {item["column"] for item in window["fields"]} == {"amount"}


def test_a_partition_by_an_expression_restates_the_expression() -> None:
    """``PARTITION BY DATE(ts)`` groups by the day, not by ``ts``.

    The expression is re-rendered through sqlglot like every other restatement in this
    view, so Spark's ``DATE(x)`` prints in its canonical ``CAST(x AS DATE)`` form.
    """
    profile = build_semantic_profile(
        _document(
            "INSERT INTO mart.t SELECT id,"
            " SUM(v) OVER (PARTITION BY DATE(ts)) AS s FROM ods.e"
        )
    )
    window = _actions(profile, "ROOT", "window")[0]

    assert window["text"].startswith("按 CAST(ts AS DATE) 分组")
    assert {item["column"] for item in window["fields"]} == {"ts"}


def test_an_order_by_an_expression_restates_the_expression() -> None:
    profile = build_semantic_profile(
        _document(
            "INSERT INTO mart.t WITH r AS ("
            "  SELECT id, v,"
            "         ROW_NUMBER() OVER (PARTITION BY id ORDER BY DATE(ts) DESC) AS rn"
            "  FROM ods.e"
            ") SELECT id, v FROM r WHERE rn = 1"
        )
    )
    window = _actions(profile, "cte:r", "window")[0]

    assert window["text"] == (
        "按 id 分组，按 CAST(ts AS DATE) 降序编号（rn）；"
        "ROOT 以 rn = 1 消费，即每组保留最新一条"
    )


def test_a_partition_by_a_plain_column_is_unchanged() -> None:
    profile = build_semantic_profile(
        _document(
            "INSERT INTO mart.t SELECT id, SUM(v) OVER (PARTITION BY id) AS s FROM ods.e"
        )
    )
    window = _actions(profile, "ROOT", "window")[0]

    assert window["text"] == "按 id 分组，计算 SUM（s）；组内累计聚合"


def test_a_dedup_key_on_a_derived_partition_column_keeps_the_logical_name() -> None:
    """R3's key object: the logical name deduplicates, the physical columns are sources."""
    shape = _shape(
        "INSERT INTO mart.t WITH b AS ("
        "  SELECT amount, v, ts,"
        "         CASE WHEN amount >= 100 THEN 'HIGH' ELSE 'LOW' END AS band"
        "  FROM ods.o2"
        "), r AS ("
        "  SELECT band, v,"
        "         ROW_NUMBER() OVER (PARTITION BY band ORDER BY ts DESC) AS rn"
        "  FROM b"
        ") SELECT band, v FROM r WHERE rn = 1",
        schema={**SCHEMA, "ods.o2": ["amount", "v", "ts"]},
    )

    assert shape["grain"]["basis"] == "window_partition"
    assert shape["grain"]["keys"] == [
        {
            "scope_id": "cte:r",
            "name": "band",
            "expression": "band",
            "physical_sources": [{"table": "ods.o2", "column": "amount"}],
        }
    ]


def test_a_proven_dedup_join_names_the_partition_key_the_right_side_writes() -> None:
    shape = _shape(
        "INSERT INTO mart.t WITH d AS ("
        "  SELECT CASE WHEN id > 0 THEN 'P' ELSE 'N' END AS sign, v, ts,"
        "         ROW_NUMBER() OVER ("
        "           PARTITION BY CASE WHEN id > 0 THEN 'P' ELSE 'N' END ORDER BY ts DESC"
        "         ) AS rn"
        "  FROM ods.e"
        ") SELECT b.id, d.v FROM ods.base b "
        "LEFT JOIN d ON b.b = d.sign AND d.rn = 1"
    )
    risk = _risk(shape, "logic:ROOT:join:001")

    assert risk["status"] == "safe"
    assert "按 CASE WHEN id > 0 THEN 'P' ELSE 'N' END 分区" in risk["reason"]
    assert "ods.e.id" not in risk["reason"]


# ------------------------------------------------------------------ field key roles


def test_a_grain_key_field_is_a_candidate_key() -> None:
    profile = build_semantic_profile(
        _document(
            "INSERT INTO mart.t SELECT customer_id, SUM(amount) AS total "
            "FROM ods.orders GROUP BY customer_id"
        )
    )
    roles = {item["column"]: item["structural_role"] for item in profile["fields"]}
    assert roles["customer_id"] == "candidate_key"
    assert roles["total"] == "measure"


def test_a_target_partition_column_takes_the_partition_role() -> None:
    profile = build_semantic_profile(
        _document(
            "INSERT OVERWRITE TABLE mart.t PARTITION (dt) "
            "SELECT id, dt FROM ods.users",
            schema={"ods.users": ["id", "dt"]},
        )
    )
    roles = {item["column"]: item["structural_role"] for item in profile["fields"]}
    assert roles["dt"] == "partition"


def test_inferred_items_name_every_wi_1b_inference() -> None:
    lineage, _ = _customer_profile_documents()
    items = build_semantic_profile(lineage)["confidence"]["inferred_items"]

    assert items["output_shape.shape"] == 1
    assert items["output_shape.grain"] == 1
    assert items["output_shape.candidate_keys"] == 1
    # WI-1g item E7: the two ROOT joins are counted under one path, not indexed apart.
    assert items["output_shape.fan_out_risks[]"] == 2
    assert any(path.endswith("].intent") for path in items)


# ----------------------------------------------------------- awkward shapes still run


AWKWARD_CASES = ("merge", "directory_target", "star_without_schema", "complex_scope")


@pytest.mark.parametrize("case", AWKWARD_CASES)
def test_awkward_documents_build_a_shape_and_stages_without_raising(case: str) -> None:
    case_dir = FIXTURES / "lineage_contract" / case
    lineage = json.loads((case_dir / "lineage.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((case_dir / "diagnostics.json").read_text(encoding="utf-8"))

    profile = build_semantic_profile(lineage, diagnostics)
    assert profile["output_shape"]["shape"] in {
        "aggregated",
        "deduplicated",
        "union_merge",
        "enriched_projection",
        "filtered_projection",
        "unknown",
    }
    assert [item["scope_id"] for item in profile["stages"]] == sorted(
        {item["scope_id"] for item in profile["stages"]},
        key=[item["scope_id"] for item in profile["stages"]].index,
    )


def test_a_union_merge_document_builds() -> None:
    shape = _shape(
        "INSERT INTO mart.t SELECT id, amount FROM ods.a "
        "UNION ALL SELECT id, amount FROM ods.b"
    )
    assert shape["shape"] == "union_merge"


def test_stage_actions_follow_sql_evaluation_order_not_logic_block_id_order() -> None:
    """Block ids sort alphabetically, which listed ROOT's ``case_when`` before the
    ``filter``/``join`` whose rows it is computed over. The order is the engine's."""
    lineage, _ = _customer_profile_documents()
    profile = build_semantic_profile(lineage)

    types = [action["type"] for action in _stage(profile, "ROOT")["actions"]]
    # WI-1g item B: the four COALESCE projections are `derive` actions, ranked between
    # the rows they read and the CASE computed over them.
    assert types == ["join", "join", "filter", *["derive"] * 4, "case_when"]
    # premise: id order really would have put the CASE first
    assert sorted(
        block["logic_block_id"]
        for block in lineage["scopes"]["ROOT"]["logic_blocks"]
        if block["logic_type"] in {"case_when", "filter", "join"}
    )[0].startswith("logic:ROOT:case_when")


def test_same_typed_actions_keep_their_logic_block_id_order() -> None:
    sql = (
        "INSERT INTO mart.wide SELECT a.id, b.amount, c.name FROM ods.base a "
        "JOIN ods.a b ON a.id = b.id JOIN ods.dim c ON a.id = c.id"
    )
    profile = build_semantic_profile(_document(sql))
    joins = [action["evidence"] for action in _actions(profile, "ROOT", "join")]
    assert joins == sorted(joins)


def test_every_action_type_the_builder_emits_has_a_declared_rank() -> None:
    """A type missing from the order would silently sink to the end of every stage."""
    from scope_lineage.render.semantic_profile import ACTION_TYPE_ORDER

    emitted = set()
    for sql, schema in (
        (
            "INSERT INTO mart.t SELECT customer_id, SUM(amount) AS total FROM ods.orders "
            "WHERE dt = '1' GROUP BY customer_id HAVING SUM(amount) > 100",
            None,
        ),
        (
            "INSERT INTO mart.t SELECT id, amount FROM ods.a "
            "UNION ALL SELECT id, amount FROM ods.b",
            None,
        ),
        ("INSERT INTO mart.t SELECT DISTINCT customer_id FROM ods.orders", None),
        (
            "INSERT INTO mart.t SELECT u.id, t.tag FROM ods.users u "
            "LATERAL VIEW EXPLODE(u.tags) t AS tag",
            {"ods.users": ["id", "tags"]},
        ),
        (
            "INSERT INTO mart.t SELECT id, CASE WHEN v > 1 THEN 'A' ELSE 'B' END AS f, "
            "ROW_NUMBER() OVER (PARTITION BY id ORDER BY ts) AS rn FROM ods.e "
            "JOIN ods.dim d ON d.id = ods.e.id",
            None,
        ),
    ):
        profile = build_semantic_profile(_document(sql, schema=schema))
        emitted |= {
            action["type"]
            for stage in profile["stages"]
            for action in stage["actions"]
        }
    # equality, not containment: the corpus is chosen to emit every declared type,
    # so a builder that stops emitting one fails here too.
    assert emitted == set(ACTION_TYPE_ORDER), sorted(emitted ^ set(ACTION_TYPE_ORDER))


# ------------------------------------------- R3 recursion and key confidence (WI-1d)


# The chain WI-1d was written for, in synthetic form: a projecting ROOT over a window
# CTE over a projection CTE over a JOIN CTE whose FROM item aggregates. Every layer but
# the last keeps the row count, so the grain is the last one's GROUP BY key set.
_RECURSIVE_CHAIN = """
INSERT INTO mart.t
WITH gsum AS (SELECT a, SUM(x) AS s FROM ods.t GROUP BY a),
     joined AS (
       SELECT g.k AS k, g.n AS n, gsum.s AS s
       FROM (SELECT customer_id AS k, COUNT(*) AS n FROM ods.orders GROUP BY customer_id) g
       LEFT JOIN gsum ON g.k = gsum.a
     ),
     rated AS (SELECT k, n, s, n * 2 AS n2 FROM joined),
     ranked AS (
       SELECT k, n, s, n2, ROW_NUMBER() OVER (PARTITION BY k ORDER BY n) AS rn FROM rated
     )
SELECT k, n, s FROM ranked
"""

# The same chain with the JOIN's right side reduced to a plain projection: nothing then
# proves one right row per left row, so the rows may be duplicated.
_UNPROVEN_RIGHT_CHAIN = _RECURSIVE_CHAIN.replace(
    "WITH gsum AS (SELECT a, SUM(x) AS s FROM ods.t GROUP BY a)",
    "WITH gsum AS (SELECT a, x AS s FROM ods.t)",
)


def test_the_walk_pierces_window_projection_and_join_layers_to_a_group_by() -> None:
    shape = _shape(_RECURSIVE_CHAIN)

    assert shape["grain"]["basis"] == "group_by"
    assert [(item["scope_id"], item["name"]) for item in shape["grain"]["keys"]] == [
        ("subq:g", "k")
    ]
    assert shape["grain"]["via_scopes"] == ["cte:ranked", "cte:rated", "cte:joined"]
    assert shape["grain"]["evidence"] == ["logic:subq:g:group_by:001"]


def test_a_join_crossed_by_the_walk_becomes_a_fan_out_risk_of_its_own_scope() -> None:
    shape = _shape(_RECURSIVE_CHAIN)

    assert [(item["scope_id"], item["status"]) for item in shape["fan_out_risks"]] == [
        ("cte:joined", "safe")
    ]
    assert shape["fan_out_risks"][0]["logic_block_id"] == "logic:cte:joined:join:001"


def test_a_group_by_grain_with_only_safe_joins_is_a_proven_key_set() -> None:
    shape = _shape(_RECURSIVE_CHAIN)

    assert shape["key_confidence"] == "proven"
    assert shape["candidate_keys"] == ["k"]


def test_an_unproven_join_on_the_path_drops_the_keys_but_keeps_the_basis() -> None:
    """A fan-out duplicates whole rows, so the GROUP BY key is no longer unique in the
    output -- but the grain the rows were built at is still the GROUP BY's."""
    shape = _shape(_UNPROVEN_RIGHT_CHAIN)

    assert shape["grain"]["basis"] == "group_by"
    assert [item["name"] for item in shape["grain"]["keys"]] == ["k"]
    assert [item["status"] for item in shape["fan_out_risks"]] == ["risk"]
    assert shape["key_confidence"] == "none"
    assert shape["candidate_keys"] == []


def test_a_lateral_view_on_the_path_is_an_unknown_grain_that_says_so() -> None:
    shape = _shape(
        "INSERT INTO mart.t WITH exploded AS ("
        "  SELECT a, item FROM ods.t LATERAL VIEW EXPLODE(SPLIT(b, ',')) tt AS item"
        ") SELECT a, item FROM exploded"
    )
    assert shape["grain"]["basis"] == "unknown"
    assert shape["grain"]["keys"] == []
    assert "LATERAL VIEW" in shape["grain"]["evidence"][0]
    assert "cte:exploded" in shape["grain"]["evidence"][0]


def test_a_union_on_the_path_is_an_unknown_grain_that_says_so() -> None:
    shape = _shape(
        "INSERT INTO mart.t WITH u AS ("
        "  SELECT id, amount FROM ods.a UNION ALL SELECT id, amount FROM ods.b"
        ") SELECT id, amount FROM u WHERE amount > 0"
    )
    assert shape["grain"]["basis"] == "unknown"
    assert "UNION" in shape["grain"]["evidence"][0]


def test_an_ambiguous_input_on_the_path_is_named_as_the_reason() -> None:
    """A bare column several inputs could own leaves the scope's FROM item unprovable;
    the sentinel is reported as itself rather than as a missing scope."""
    document = {
        "schema_version": "1.0",
        "target_table": "mart.t",
        "source_tables": ["ods.base"],
        "scopes": {
            "ROOT": {"kind": "root", "depends_on": ["subq:a"], "logic_blocks": []},
            "subq:a": {
                "kind": "subquery",
                "depends_on": ["AMBIGUOUS", "ods.base"],
                "logic_blocks": [],
            },
        },
    }
    grain = build_semantic_profile(document)["output_shape"]["grain"]
    assert grain["basis"] == "unknown"
    assert "AMBIGUOUS" in grain["evidence"][0]


def test_a_self_referencing_scope_stops_instead_of_walking_forever() -> None:
    document = {
        "schema_version": "1.0",
        "target_table": "mart.t",
        "source_tables": ["ods.base"],
        "scopes": {
            "ROOT": {"kind": "root", "depends_on": ["cte:loop"], "logic_blocks": []},
            "cte:loop": {"kind": "cte", "depends_on": ["cte:loop"], "logic_blocks": []},
        },
    }
    grain = build_semantic_profile(document)["output_shape"]["grain"]
    assert grain["basis"] == "unknown"
    assert grain["evidence"] == ["驱动输入 cte:loop 自引用成环"]


def test_a_self_referencing_merge_document_still_builds() -> None:
    """The contract's own self-join MERGE: the walk must terminate on it, not recurse."""
    case_dir = FIXTURES / "task_lineage_contract" / "merge_cte_source"
    lineage = json.loads((case_dir / "lineage.json").read_text(encoding="utf-8"))
    profile = build_semantic_profile(lineage)
    for statement in profile["statements"]:
        assert statement["output_shape"]["grain"]["basis"] in {
            "group_by",
            "distinct",
            "window_partition",
            "driving_table_rows",
            "unknown",
        }
        assert statement["output_shape"]["key_confidence"] in {
            "proven",
            "candidate",
            "none",
        }


def test_the_walk_stops_at_the_depth_limit_rather_than_running_away() -> None:
    from scope_lineage.render.semantic_profile import GRAIN_DEPTH_LIMIT

    depth = GRAIN_DEPTH_LIMIT + 4
    scopes = {"ROOT": {"kind": "root", "depends_on": ["s0"], "logic_blocks": []}}
    for index in range(depth):
        following = f"s{index + 1}" if index + 1 < depth else "ods.base"
        scopes[f"s{index}"] = {
            "kind": "subquery",
            "depends_on": [following],
            "logic_blocks": [],
        }
    document = {
        "schema_version": "1.0",
        "target_table": "mart.t",
        "source_tables": ["ods.base"],
        "scopes": scopes,
    }
    grain = build_semantic_profile(document)["output_shape"]["grain"]
    assert grain["basis"] == "unknown"
    assert grain["evidence"] == [f"穿透层数超过上限 {GRAIN_DEPTH_LIMIT}"]


def test_every_basis_the_builder_emits_is_a_declared_one() -> None:
    from scope_lineage.render.semantic_profile import GRAIN_BASES

    emitted = {
        _shape(sql)["grain"]["basis"]
        for sql in (
            "INSERT INTO mart.t SELECT customer_id, SUM(amount) AS t "
            "FROM ods.orders GROUP BY customer_id",
            "INSERT INTO mart.t SELECT DISTINCT customer_id FROM ods.orders",
            "INSERT INTO mart.t SELECT id, name FROM ods.users WHERE dt = '1'",
            "INSERT INTO mart.t WITH r AS ("
            "  SELECT id, v, RANK() OVER (PARTITION BY id ORDER BY ts) AS rk FROM ods.e"
            ") SELECT id, v FROM r WHERE rk = 1",
            "INSERT INTO mart.t SELECT id, amount FROM ods.a "
            "UNION ALL SELECT id, amount FROM ods.b",
            "INSERT INTO mart.t SELECT COUNT(*) AS n FROM ods.orders",
        )
    }
    assert emitted == set(GRAIN_BASES)


# ------------------------------------------------- R3: logical keys on the target (WI-1e)
#
# A GROUP BY item is one *logical* key however many physical columns it pierces to, and
# the answer a reader wants is "which target columns identify a row", not "which columns
# the expression happens to read". These tests pin both halves.

_LOGICAL_SCHEMA = {
    "ods.orders": [
        "customer_id",
        "amount",
        "dt",
        "region",
        "city",
        "kind",
        "product_type",
    ],
    "ods.left_a": ["k1", "v"],
    "ods.left_b": ["k2", "v"],
    "ods.main": ["id", "name", "v"],
    "ods.side": ["id", "v"],
}

_THREE_ITEM_GROUP_BY = (
    "INSERT INTO mart.t SELECT "
    "  CASE WHEN kind = 'a' THEN CONCAT(region, city) ELSE dt END AS bucket, "
    "  customer_id, product_type, SUM(amount) AS total "
    "FROM ods.orders GROUP BY "
    "  CASE WHEN kind = 'a' THEN CONCAT(region, city) ELSE dt END, "
    "  customer_id, product_type"
)


def _logical_shape(sql: str) -> dict:
    return _shape(sql, schema=_LOGICAL_SCHEMA)


def test_a_group_by_item_is_one_logical_key_however_many_columns_it_pierces_to() -> None:
    shape = _logical_shape(_THREE_ITEM_GROUP_BY)
    keys = shape["grain"]["keys"]

    assert [item["name"] for item in keys] == ["bucket", "customer_id", "product_type"]
    assert all(item["scope_id"] == "ROOT" for item in keys)
    # the CASE item reads four physical columns and is still exactly one key
    assert len(keys[0]["physical_sources"]) == 4
    assert keys[0]["expression"].startswith("CASE WHEN")
    assert keys[1]["physical_sources"] == [
        {"table": "ods.orders", "column": "customer_id"}
    ]


def test_the_candidate_keys_of_a_group_by_are_the_target_columns_the_keys_reach() -> None:
    shape = _logical_shape(_THREE_ITEM_GROUP_BY)

    assert shape["candidate_keys"] == ["bucket", "customer_id", "product_type"]
    assert shape["unexposed_keys"] == []
    assert shape["key_confidence"] == "proven"


def test_a_key_pierced_through_a_union_stays_one_key_with_both_branch_columns() -> None:
    shape = _logical_shape(
        "INSERT INTO mart.t WITH u AS ("
        "  SELECT k1 AS k, v FROM ods.left_a UNION ALL SELECT k2 AS k, v FROM ods.left_b"
        ") SELECT k, SUM(v) AS s FROM u GROUP BY k"
    )
    keys = shape["grain"]["keys"]

    assert len(keys) == 1
    assert keys[0]["name"] == "k"
    assert keys[0]["physical_sources"] == [
        {"table": "ods.left_a", "column": "k1"},
        {"table": "ods.left_b", "column": "k2"},
    ]
    assert shape["candidate_keys"] == ["k"]
    assert shape["key_confidence"] == "proven"


def test_a_group_by_key_the_target_never_receives_is_a_governance_finding() -> None:
    """The keys are proven unique, and the *target* columns are not: say exactly that."""
    shape = _logical_shape(
        "INSERT INTO mart.t WITH agg AS ("
        "  SELECT customer_id, region, SUM(amount) AS total "
        "  FROM ods.orders GROUP BY customer_id, region"
        ") SELECT customer_id, total FROM agg"
    )

    assert [item["name"] for item in shape["grain"]["keys"]] == ["customer_id", "region"]
    assert shape["candidate_keys"] == ["customer_id"]
    assert [item["name"] for item in shape["unexposed_keys"]] == ["region"]
    assert shape["key_confidence"] == "proven_unexposed"


def test_a_key_renamed_on_the_way_out_is_published_under_the_target_column_name() -> None:
    shape = _logical_shape(
        "INSERT INTO mart.t WITH agg AS ("
        "  SELECT customer_id, SUM(amount) AS total FROM ods.orders GROUP BY customer_id"
        ") SELECT customer_id AS cust, total FROM agg"
    )

    assert [item["name"] for item in shape["grain"]["keys"]] == ["customer_id"]
    assert shape["grain"]["keys"][0]["scope_id"] == "cte:agg"
    assert shape["candidate_keys"] == ["cust"]
    assert shape["key_confidence"] == "proven"


def test_a_key_wrapped_in_coalesce_before_the_target_is_not_exposed() -> None:
    """``COALESCE(key, 'NA')`` maps two distinct keys onto one value: not a direct path."""
    shape = _logical_shape(
        "INSERT INTO mart.t WITH agg AS ("
        "  SELECT customer_id, SUM(amount) AS total FROM ods.orders GROUP BY customer_id"
        ") SELECT COALESCE(customer_id, 'NA') AS cust, total FROM agg"
    )

    assert shape["candidate_keys"] == []
    assert [item["name"] for item in shape["unexposed_keys"]] == ["customer_id"]
    assert shape["key_confidence"] == "proven_unexposed"


def test_a_dedup_partition_key_also_lands_on_the_target_column() -> None:
    shape = _shape(
        "INSERT INTO mart.t WITH r AS ("
        "  SELECT id, v, ROW_NUMBER() OVER (PARTITION BY id ORDER BY ts) AS rk FROM ods.e"
        ") SELECT id, v FROM r WHERE rk = 1"
    )

    assert shape["grain"]["basis"] == "window_partition"
    assert [(item["scope_id"], item["name"]) for item in shape["grain"]["keys"]] == [
        ("cte:r", "id")
    ]
    assert shape["grain"]["keys"][0]["physical_sources"] == [
        {"table": "ods.e", "column": "id"}
    ]
    assert shape["candidate_keys"] == ["id"]
    assert shape["key_confidence"] == "proven"


def test_a_driving_table_candidate_is_the_target_column_its_join_key_reaches() -> None:
    shape = _logical_shape(
        "INSERT INTO mart.t WITH agg AS ("
        "  SELECT id, SUM(v) AS s FROM ods.side GROUP BY id"
        ") SELECT m.id AS main_id, agg.s FROM ods.main m LEFT JOIN agg ON m.id = agg.id"
    )

    assert shape["grain"]["basis"] == "driving_table_rows"
    assert shape["grain"]["keys"] == []
    assert shape["candidate_keys"] == ["main_id"]
    assert shape["key_confidence"] == "candidate"


def test_a_driving_join_key_the_target_never_receives_proves_no_candidate() -> None:
    shape = _logical_shape(
        "INSERT INTO mart.t WITH agg AS ("
        "  SELECT id, SUM(v) AS s FROM ods.side GROUP BY id"
        ") SELECT m.name, agg.s FROM ods.main m LEFT JOIN agg ON m.id = agg.id"
    )

    assert shape["grain"]["basis"] == "driving_table_rows"
    assert shape["candidate_keys"] == []
    assert shape["key_confidence"] == "none"
    assert any("未输出到目标表" in note for note in shape["key_evidence"])


def test_a_target_partition_column_is_dropped_from_the_candidate_keys() -> None:
    shape = _logical_shape(
        "INSERT OVERWRITE TABLE mart.t PARTITION (dt) "
        "SELECT customer_id, dt, SUM(amount) AS s FROM ods.orders GROUP BY customer_id, dt"
    )

    assert [item["name"] for item in shape["grain"]["keys"]] == ["customer_id", "dt"]
    assert shape["candidate_keys"] == ["customer_id"]
    assert shape["unexposed_keys"] == []
    assert shape["key_evidence"] == ["目标列 dt 是分区列，不计入候选键"]
    assert shape["key_confidence"] == "proven"


def test_a_candidate_key_field_role_follows_the_target_column_name() -> None:
    profile = build_semantic_profile(
        _document(
            "INSERT INTO mart.t WITH agg AS ("
            "  SELECT customer_id, SUM(amount) AS total FROM ods.orders GROUP BY customer_id"
            ") SELECT customer_id AS cust, total FROM agg",
            schema=_LOGICAL_SCHEMA,
        )
    )
    roles = {item["column"]: item["structural_role"] for item in profile["fields"]}

    assert roles["cust"] == "candidate_key"
    assert roles["total"] == "measure"


def test_every_key_confidence_the_builder_emits_is_a_declared_one() -> None:
    from scope_lineage.render.semantic_profile import KEY_CONFIDENCES

    emitted = {
        _logical_shape(sql)["key_confidence"]
        for sql in (
            _THREE_ITEM_GROUP_BY,
            "INSERT INTO mart.t WITH agg AS ("
            "  SELECT customer_id, region, SUM(amount) AS total "
            "  FROM ods.orders GROUP BY customer_id, region"
            ") SELECT customer_id, total FROM agg",
            "INSERT INTO mart.t WITH agg AS ("
            "  SELECT id, SUM(v) AS s FROM ods.side GROUP BY id"
            ") SELECT m.id AS main_id, agg.s FROM ods.main m LEFT JOIN agg ON m.id = agg.id",
            "INSERT INTO mart.t SELECT id, v FROM ods.main",
        )
    }
    assert emitted == set(KEY_CONFIDENCES)


# ------------------------------------------- WI-1g A: stage text uses logical names

_UNION_GROUP_BY_SCHEMA = {"ods.a": ["seg", "amt"], "ods.b": ["seg_code", "amt"]}

_UNION_GROUP_BY = (
    "INSERT INTO mart.t WITH u AS ("
    "SELECT seg AS segment, amt AS amount FROM ods.a "
    "UNION ALL SELECT seg_code AS segment, amt AS amount FROM ods.b) "
    "SELECT segment, CASE WHEN amount >= 100 THEN 'H' ELSE 'L' END AS band, "
    "SUM(amount) AS total FROM u "
    "GROUP BY segment, CASE WHEN amount >= 100 THEN 'H' ELSE 'L' END"
)


def test_an_aggregate_action_names_the_group_by_items_not_their_physical_roots() -> None:
    """Two GROUP BY items over a two-branch UNION pierce to four physical columns.

    Naming those four made the line read as a four-column grain the statement never
    wrote (and `amount` is not a grouping key at all -- it is the CASE's input).
    """
    profile = build_semantic_profile(_document(_UNION_GROUP_BY, schema=_UNION_GROUP_BY_SCHEMA))
    action = _actions(profile, "ROOT", "aggregate")[0]

    assert action["text"] == (
        "按 segment、CASE WHEN amount >= 100 THEN 'H' ELSE 'L' END 分组聚合：SUM(amount)"
    )


def test_the_physical_columns_behind_a_group_by_item_stay_in_the_action_fields() -> None:
    """The logical name is the sentence; the pierce is still published, just not as a key."""
    profile = build_semantic_profile(_document(_UNION_GROUP_BY, schema=_UNION_GROUP_BY_SCHEMA))
    action = _actions(profile, "ROOT", "aggregate")[0]

    assert {(item["table"], item["column"]) for item in action["fields"]} == {
        ("ods.a", "seg"),
        ("ods.b", "seg_code"),
        ("ods.a", "amt"),
        ("ods.b", "amt"),
    }


def _ten_branch_join() -> tuple[str, dict]:
    """Two join keys over a ten-branch UNION: 2 logical pairs, 20 pierced ones."""
    branches = " UNION ALL ".join(
        f"SELECT k1_{index} AS k1, k2_{index} AS k2, v AS v FROM ods.s{index}"
        for index in range(1, 11)
    )
    schema = {f"ods.s{index}": [f"k1_{index}", f"k2_{index}", "v"] for index in range(1, 11)}
    schema["dim.d"] = ["k1", "k2", "label"]
    sql = (
        f"INSERT INTO mart.t WITH u AS ({branches}) "
        "SELECT u.k1, u.k2, d.label FROM u LEFT JOIN dim.d d ON u.k1 = d.k1 AND u.k2 = d.k2"
    )
    return sql, schema


def test_a_join_over_a_union_publishes_two_logical_keys_not_twenty_pierced_ones() -> None:
    sql, schema = _ten_branch_join()
    rule = next(
        item
        for item in build_semantic_profile(_document(sql, schema=schema))["rules"]
        if item["kind"] == "join_condition"
    )

    assert rule["key_pairs"] == [
        {"left": "u.k1", "right": "d.k1"},
        {"left": "u.k2", "right": "d.k2"},
    ]
    # the cross product is a fact too -- it is published, just not as the join's keys
    assert len(rule["physical_key_pairs"]) == 20


def test_the_join_action_states_the_key_once_when_both_sides_spell_it_the_same() -> None:
    sql, schema = _ten_branch_join()
    profile = build_semantic_profile(_document(sql, schema=schema))

    assert _actions(profile, "ROOT", "join")[0]["text"] == (
        "LEFT_OUTER 关联 dim.d，键 k1、k2，右侧无匹配时保留左行，右侧字段为空"
    )


def test_a_renamed_join_key_keeps_both_sides() -> None:
    sql = (
        "INSERT INTO mart.t SELECT o.customer_id, u.name FROM ods.orders o "
        "LEFT JOIN ods.users u ON o.customer_id = u.id"
    )
    profile = build_semantic_profile(_document(sql))
    rule = next(
        item for item in profile["rules"] if item["kind"] == "join_condition"
    )
    assert rule["key_pairs"] == [{"left": "o.customer_id", "right": "u.id"}]
    assert "键 o.customer_id = u.id" in _actions(profile, "ROOT", "join")[0]["text"]


def test_the_fan_out_verdict_compares_the_logical_key_sets_and_notes_the_physical_one() -> None:
    """WI-2.1d item 1 moved the *proof* to scope level too; the pierce is now a note.

    WI-1g had moved only the wording there and this test pinned the physical comparison
    as the proof. It is the same sentence either way while one GROUP BY item reads one
    column, which is exactly why the wrong comparison survived so long.
    """
    sql = (
        "INSERT INTO mart.t WITH s AS (SELECT id, SUM(amount) AS total FROM ods.a GROUP BY id) "
        "SELECT base.id, s.total FROM ods.base base LEFT JOIN s ON base.id = s.id"
    )
    risk = _shape(sql)["fan_out_risks"][0]
    assert risk["status"] == "safe"
    assert risk["reason"] == "右侧按 id GROUP BY，键集被连接键覆盖（键的物理来源 ods.a.id）"


# ------------------------------------------------- WI-1g B: plain expression derivations

_DERIVE_SCHEMA = {"ods.m": ["id", "a", "b", "ts"]}


def test_a_plain_expression_output_becomes_its_own_derive_action() -> None:
    """Arithmetic and function derivations are not logic blocks, so nothing in `stages`
    mentioned them: a task whose 24 core metrics are all `a - b` showed none of them."""
    profile = build_semantic_profile(
        _document(
            "INSERT INTO mart.t SELECT id, a - b AS delta FROM ods.m", schema=_DERIVE_SCHEMA
        )
    )
    action = _actions(profile, "ROOT", "derive")[0]

    assert action["column"] == "delta"
    assert action["text"] == "算术运算：a - b"
    assert action["expression"] == "`m`.`a` - `m`.`b`"
    assert {item["column"] for item in action["fields"]} == {"a", "b"}
    assert action["evidence"] == "ROOT"


def test_a_derive_outside_the_vocabulary_keeps_a_null_text_and_its_expression() -> None:
    profile = build_semantic_profile(
        _document(
            "INSERT INTO mart.t SELECT id, my_udf(a) AS scored FROM ods.m",
            schema=_DERIVE_SCHEMA,
        )
    )
    action = _actions(profile, "ROOT", "derive")[0]
    assert action["column"] == "scored"
    assert action["text"] == "UDF 黑盒"
    assert action["expression"] == "MY_UDF(`m`.`a`)"


def test_direct_constant_case_aggregate_and_window_outputs_are_not_derive_actions() -> None:
    """Each of them already has an action of its own; `derive` is the one that had none."""
    profile = build_semantic_profile(
        _document(
            "INSERT INTO mart.t SELECT id, 'X' AS flag, "
            "CASE WHEN a > 1 THEN 'y' ELSE 'n' END AS label, "
            "SUM(a) OVER (PARTITION BY id) AS running FROM ods.m",
            schema=_DERIVE_SCHEMA,
        )
    )
    assert _actions(profile, "ROOT", "derive") == []


def test_derive_is_ranked_before_the_case_computed_over_it() -> None:
    profile = build_semantic_profile(
        _document(
            "INSERT INTO mart.t SELECT id, a - b AS delta, "
            "CASE WHEN a - b > 0 THEN 'up' ELSE 'down' END AS trend FROM ods.m",
            schema=_DERIVE_SCHEMA,
        )
    )
    types = [action["type"] for action in _stage(profile, "ROOT")["actions"]]
    assert types.index("derive") < types.index("case_when")


def test_a_builtin_the_core_catalog_does_not_know_is_not_marked_a_udf() -> None:
    """`function_catalog` stops at 40-odd names, so HOUR / RANK / LAG were all "UDF 黑盒".

    sqlglot parses every one of them into its own node class, and that is the whitelist.
    """
    profile = build_semantic_profile(
        _document(
            "INSERT INTO mart.t SELECT id, HOUR(ts) AS hh FROM ods.m", schema=_DERIVE_SCHEMA
        )
    )
    action = _actions(profile, "ROOT", "derive")[0]
    assert "UDF 黑盒" not in str(action["text"])


# ----------------------------------------------- WI-1g E1: pattern signature vocabulary


def test_the_pattern_signature_separates_stages_by_the_kind_of_their_inputs() -> None:
    """`physical_input=yes/no` folded "reads one table" together with "reads three"."""
    sql = (
        "INSERT INTO mart.t WITH one AS (SELECT id, v FROM ods.e), "
        "two AS (SELECT o.id, o.v FROM ods.e o JOIN ods.e2 e2 ON o.id = e2.a) "
        "SELECT one.id, two.v FROM one JOIN two ON one.id = two.id"
    )
    profile = build_semantic_profile(
        _document(sql, schema={**SCHEMA, "ods.e2": ["a", "b", "v"]})
    )
    signatures = {item["scope_id"]: item["pattern_signature"] for item in profile["stages"]}
    assert "inputs=tables:1,scopes:0,union:no" in signatures["cte:one"]
    assert "inputs=tables:2,scopes:0,union:no" in signatures["cte:two"]
    assert signatures["cte:one"] != signatures["cte:two"]
    for signature in signatures.values():
        assert "ods." not in signature


def test_the_pattern_signature_counts_derive_actions() -> None:
    profile = build_semantic_profile(
        _document(
            "INSERT INTO mart.t SELECT id, a - b AS delta FROM ods.m", schema=_DERIVE_SCHEMA
        )
    )
    assert "derive=1" in _stage(profile, "ROOT")["pattern_signature"]


# --------------------- WI-2.1c item 5: fan-out on a metric's argument path


# The driving side joins one scope that is never on the grain walk (it is a LEFT JOIN's
# right input), and that scope itself joins a second relation without deduplicating it.
# Nothing about the output's row count changes; the number `MAX` reads does.
ARGUMENT_FAN_OUT_SQL = """
INSERT INTO mart.t
SELECT d.k AS k, MAX(v.amt) AS mx
FROM ods.drive d
LEFT JOIN (
  SELECT x.k AS k, x.amt AS amt
  FROM ods.val x
  JOIN (SELECT k FROM ods.tag) g ON x.k = g.k
) v ON d.k = v.k
GROUP BY d.k
"""

ARGUMENT_FAN_OUT_SCHEMA = {
    "ods.drive": ["k"],
    "ods.val": ["k", "amt"],
    "ods.tag": ["k"],
}


def test_a_join_on_the_argument_path_is_judged_and_labelled_argument() -> None:
    risks = _shape(ARGUMENT_FAN_OUT_SQL, schema=ARGUMENT_FAN_OUT_SCHEMA)["fan_out_risks"]
    argument = [item for item in risks if item["path"] == "argument"]

    assert [(item["scope_id"], item["right"], item["status"]) for item in argument] == [
        ("subq:v", "subq:g", "risk")
    ]
    assert argument[0]["reason"] == "右侧未被证明按连接键唯一"
    # The grain-path join is still listed, and still says which path it is on.
    assert [item["path"] for item in risks if item["scope_id"] == "ROOT"] == ["grain"]


def test_a_join_on_neither_path_is_still_not_listed() -> None:
    """The bypass case the grain walk exists to exclude: a lookup nothing reads from."""
    sql = ARGUMENT_FAN_OUT_SQL.replace(
        "GROUP BY d.k",
        "GROUP BY d.k",
    ).replace(
        "FROM ods.drive d",
        "FROM ods.drive d LEFT JOIN (SELECT k FROM ods.tag) bypass ON d.k = bypass.k",
    )
    risks = _shape(sql, schema=ARGUMENT_FAN_OUT_SCHEMA)["fan_out_risks"]

    # ROOT's two joins are on the grain path; nothing names a scope the metric's
    # argument never reads beyond them.
    assert {item["scope_id"] for item in risks} == {"ROOT", "subq:v"}


def test_every_fan_out_entry_declares_a_path_from_the_vocabulary() -> None:
    risks = _shape(ARGUMENT_FAN_OUT_SQL, schema=ARGUMENT_FAN_OUT_SCHEMA)["fan_out_risks"]

    assert risks
    for risk in risks:
        assert risk["path"] in FAN_OUT_PATHS


def test_section_two_lists_the_argument_path_joins_under_their_own_heading() -> None:
    profile = build_semantic_profile(
        _document(ARGUMENT_FAN_OUT_SQL, schema=ARGUMENT_FAN_OUT_SCHEMA)
    )
    rendered = render_semantic_markdown(profile, sections=["shape"])
    heading = "- 影响指标取值的关联："

    assert heading in rendered
    tail = rendered.split(heading)[1]
    assert "`subq:g`" in tail
    # The grain-path join stays above the heading, where the row-count claim belongs.
    assert "`subq:v`" in rendered.split(heading)[0]


def test_a_statement_without_an_argument_path_join_keeps_one_list() -> None:
    profile = build_semantic_profile(
        _document(
            "INSERT INTO mart.t SELECT a.id, a.b FROM ods.base a "
            "LEFT JOIN ods.dim d ON a.id = d.id"
        )
    )
    rendered = render_semantic_markdown(profile, sections=["shape"])

    assert "影响指标取值的关联" not in rendered
    assert all(
        item["path"] == "grain" for item in profile["output_shape"]["fan_out_risks"]
    )


# ------------------------- an argument-path risk is about the VALUE, not the row count


_ARGUMENT_RISK_SCHEMA = {
    "ods.main": ["k", "v", "dt"],
    "ods.oper": ["id", "dt"],
    "ods.extra": ["id", "tag"],
}

_ARGUMENT_RISK_SQL = (
    "INSERT INTO mart.gap SELECT a.k, MAX(x.id) AS last_id, SUM(a.v) AS total "
    "FROM ods.main a "
    "LEFT JOIN (SELECT o.id FROM ods.oper o LEFT JOIN ods.extra e ON o.id = e.id "
    "GROUP BY o.id) x ON a.k = x.id "
    "WHERE a.dt = '20260814' GROUP BY a.k"
)


def test_an_argument_path_fan_out_does_not_cost_the_statement_its_keys() -> None:
    """A JOIN that only feeds a metric's argument inflates a number, not the row count.

    ``GROUP BY a.k`` proves one row per ``k`` whatever happens inside the subquery a
    ``MAX`` reads from: the subquery is aggregated before ROOT joins it, so no row of
    the output is duplicated. Counting the argument path's risk against the key set
    published ``key_confidence: none`` for statements whose grain is proven --
    the strongest claim the profile can make, withdrawn by a risk about a different
    question. The risk itself stays: it is still true that ``MAX(x.id)`` may be read
    over duplicated rows.
    """
    shape = _shape(_ARGUMENT_RISK_SQL, schema=_ARGUMENT_RISK_SCHEMA)

    assert shape["key_confidence"] == "proven"
    assert shape["candidate_keys"] == ["k"]
    assert [(item["scope_id"], item["status"], item["path"]) for item in shape["fan_out_risks"]] == [
        ("ROOT", "safe", "grain"),
        ("subq:x", "unknown", "argument"),
    ]


def test_a_grain_path_fan_out_still_costs_the_statement_its_keys() -> None:
    """The other direction, so the filter cannot quietly become "ignore every risk".

    B12 narrowed which grain-path risk counts -- only one *downstream* of the grouping
    can duplicate what the grouping made unique -- so the JOIN that proves the filter
    still bites is the one ROOT runs over the already-grouped CTE.
    """
    shape = _shape(
        "INSERT INTO mart.gap WITH g AS (SELECT a.k, SUM(a.v) AS total FROM ods.main a "
        "GROUP BY a.k) SELECT g.k, g.total FROM g LEFT JOIN ods.extra e ON g.k = e.id",
        schema=_ARGUMENT_RISK_SCHEMA,
    )

    assert [item["path"] for item in shape["fan_out_risks"]] == ["grain"]
    assert shape["key_confidence"] == "none"
    assert shape["candidate_keys"] == []


# --------------------------------- the metric anchor's own input subtree (WI-9 legacy a)


ANCHOR_FAN_OUT_SCHEMA = {
    "ods.drive": ["k", "amt"],
    "ods.val": ["k"],
    "ods.tag": ["k"],
    "ods.lbl": ["k", "label"],
    "ods.lx": ["k"],
}

# `total` aggregates inside `subq:a`. The JOIN in `subq:s` sits under that aggregation
# without being on its driving path (s is a right input) or on the metric's argument
# path (the argument is `d.amt`, read off the driving side), and duplicating s's rows
# still inflates the SUM.
ANCHOR_FAN_OUT_SQL = """
INSERT INTO mart.t
SELECT a.k AS k, a.total AS total
FROM (
  SELECT d.k AS k, SUM(d.amt) AS total
  FROM ods.drive d
  LEFT JOIN (
    SELECT v.k AS k FROM ods.val v JOIN ods.tag g ON v.k = g.k
  ) s ON d.k = s.k
  GROUP BY d.k
) a
"""

# The same statement with a lookup ROOT joins in for a non-metric column. The JOIN
# inside that lookup is under neither the grain walk, the argument path, nor the
# anchor's subtree, so it stays unlisted exactly as it always did.
ANCHOR_BYPASS_SQL = """
INSERT INTO mart.t
SELECT a.k AS k, a.total AS total, o.label AS label
FROM (
  SELECT d.k AS k, SUM(d.amt) AS total
  FROM ods.drive d
  GROUP BY d.k
) a
LEFT JOIN (
  SELECT l.k AS k, l.label AS label FROM ods.lbl l JOIN ods.lx x ON l.k = x.k
) o ON a.k = o.k
"""


def test_a_join_below_the_metric_anchor_is_judged_and_labelled_anchor() -> None:
    risks = _shape(ANCHOR_FAN_OUT_SQL, schema=ANCHOR_FAN_OUT_SCHEMA)["fan_out_risks"]
    anchor = [item for item in risks if item["path"] == "anchor"]

    assert [(item["scope_id"], item["right"], item["status"]) for item in anchor] == [
        ("subq:s", "ods.tag", "unknown")
    ]
    # The join the grain walk itself crossed keeps its own path.
    assert [item["path"] for item in risks if item["scope_id"] == "subq:a"] == ["grain"]


def test_an_anchor_path_fan_out_does_not_cost_the_statement_its_keys() -> None:
    """``GROUP BY d.k`` still proves one row per k: the anchor path inflates a number."""
    shape = _shape(ANCHOR_FAN_OUT_SQL, schema=ANCHOR_FAN_OUT_SCHEMA)

    assert any(item["path"] == "anchor" for item in shape["fan_out_risks"])
    assert shape["grain"]["basis"] == "group_by"


def test_a_join_outside_the_anchor_subtree_is_still_not_listed() -> None:
    risks = _shape(ANCHOR_BYPASS_SQL, schema=ANCHOR_FAN_OUT_SCHEMA)["fan_out_risks"]

    # ROOT's join onto the lookup is on the grain walk; the join *inside* the lookup is
    # on no path at all, and the anchor's subtree is `ods.drive` alone.
    assert {item["scope_id"] for item in risks} == {"ROOT"}


def test_section_two_lists_the_anchor_path_joins_with_the_value_risks() -> None:
    profile = build_semantic_profile(
        _document(ANCHOR_FAN_OUT_SQL, schema=ANCHOR_FAN_OUT_SCHEMA)
    )
    rendered = render_semantic_markdown(profile, sections=["shape"])
    heading = "- 影响指标取值的关联："

    assert heading in rendered
    assert "`subq:s`" in rendered.split(heading)[1]


@pytest.mark.parametrize(
    "sql",
    [ANCHOR_FAN_OUT_SQL, ANCHOR_BYPASS_SQL, ARGUMENT_FAN_OUT_SQL],
    ids=["anchor", "bypass", "argument"],
)
def test_every_fan_out_risk_names_a_scope_the_document_declares(sql: str) -> None:
    """Anti-fabrication: a path may widen what is judged, never what is named."""
    document = _document(sql, schema=ANCHOR_FAN_OUT_SCHEMA | ARGUMENT_FAN_OUT_SCHEMA)
    risks = build_semantic_profile(document)["output_shape"]["fan_out_risks"]

    for risk in risks:
        assert risk["path"] in FAN_OUT_PATHS
        assert risk["scope_id"] in document["scopes"]
        assert risk["logic_block_id"] in {
            str(block.get("logic_block_id"))
            for scope in document["scopes"].values()
            for block in scope.get("logic_blocks") or []
        }
