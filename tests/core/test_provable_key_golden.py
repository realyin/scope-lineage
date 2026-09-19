"""Semantic locks for the ``grouped_dedup_join`` golden case.

The golden bytes in ``fixtures/lineage_contract/grouped_dedup_join/`` pin the whole
document; this module pins the handful of facts the case exists to prove, by name, so a
regression reads as "the proven-key path broke" instead of "12 000 lines of JSON moved".

The case is the only golden that carries a *provable* output key: a GROUP BY over a
UNION ALL (so each logical key fans out to more than one physical column, and one of
them is an expression key), a dedup-and-filter LEFT JOIN that must be judged ``safe``,
and two row-preserving scopes above the aggregate that ``grain.via_scopes`` has to pierce
(R3 recursion) before it can reach the GROUP BY block.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.render.semantic_markdown import render_semantic_markdown
from scope_lineage.render.semantic_profile import build_semantic_profile


CASE_DIR = (
    Path(__file__).parent / "fixtures" / "lineage_contract" / "grouped_dedup_join"
)


@pytest.fixture(scope="module")
def lineage() -> dict:
    return json.loads((CASE_DIR / "lineage.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def diagnostics() -> dict:
    return json.loads((CASE_DIR / "diagnostics.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def profile(lineage: dict, diagnostics: dict) -> dict:
    return build_semantic_profile(lineage, diagnostics)


def _stage(profile: dict, scope_id: str) -> dict:
    return next(stage for stage in profile["stages"] if stage["scope_id"] == scope_id)


def _field(profile: dict, column: str) -> dict:
    return next(field for field in profile["fields"] if field["column"] == column)


def _sources(key: dict) -> set[tuple[str, str]]:
    return {(item["table"], item["column"]) for item in key["physical_sources"]}


# --------------------------------------------------------------------- shape / grain


def test_the_statement_is_a_filtered_projection_over_the_final_cte(profile: dict) -> None:
    shape = profile["output_shape"]
    assert shape["shape"] == "filtered_projection"
    assert shape["shape_evidence"] == ["ROOT"]


def test_the_grain_is_the_group_by_pierced_through_two_row_preserving_scopes(
    profile: dict,
) -> None:
    """ROOT and ``cte:ranked``/``cte:joined`` neither aggregate nor filter rows, so the
    grain walk has to recurse past them to reach ``cte:agg``'s GROUP BY block."""
    grain = profile["output_shape"]["grain"]
    assert grain["basis"] == "group_by"
    assert grain["via_scopes"] == ["cte:ranked", "cte:joined"]
    assert grain["confidence"] == "structural"
    assert grain["evidence"] == ["logic:cte:agg:group_by:001"]


def test_both_logical_keys_are_attributed_to_the_aggregate_scope(profile: dict) -> None:
    keys = profile["output_shape"]["grain"]["keys"]
    assert [key["name"] for key in keys] == ["segment", "band"]
    assert {key["scope_id"] for key in keys} == {"cte:agg"}


def test_a_union_aligned_key_carries_the_physical_column_of_every_branch(
    profile: dict,
) -> None:
    """``segment`` is projected from ``segment`` on one branch and ``seg_code`` on the
    other; a key that named only one of them would be a false fact."""
    segment = profile["output_shape"]["grain"]["keys"][0]
    assert _sources(segment) == {
        ("ods.events_a", "segment"),
        ("ods.events_b", "seg_code"),
    }


def test_an_expression_key_resolves_through_the_case_to_both_branch_columns(
    profile: dict,
) -> None:
    band = profile["output_shape"]["grain"]["keys"][1]
    assert band["expression"] == (
        "CASE WHEN `events_norm`.`amount` >= 100 THEN 'HIGH' ELSE 'LOW' END"
    )
    assert _sources(band) == {
        ("ods.events_a", "amount"),
        ("ods.events_b", "amount"),
    }


# ----------------------------------------------------------------------- key strength


def test_the_key_set_reaches_the_target_columns_and_is_proven(profile: dict) -> None:
    shape = profile["output_shape"]
    assert shape["candidate_keys"] == ["segment", "band"]
    assert shape["key_confidence"] == "proven"
    assert shape["unexposed_keys"] == []
    assert shape["partition_columns"] == ["dt"]


def test_the_key_columns_are_the_ones_marked_candidate_key_in_the_fields_view(
    profile: dict,
) -> None:
    assert _field(profile, "segment")["structural_role"] == "candidate_key"
    assert _field(profile, "band")["structural_role"] == "candidate_key"
    assert _field(profile, "total")["structural_role"] == "measure"


def test_the_markdown_states_the_key_as_a_fact_and_scopes_it_to_the_partition(
    profile: dict,
) -> None:
    rendered = render_semantic_markdown(profile, sections=["shape"])
    assert (
        "- 键：目标表列 `segment`、`band`——由 GROUP BY 键保证输出内唯一（分区内）"
        "（key_confidence=proven）（结构推断）"
    ) in rendered
    assert "仅为候选" not in rendered
    assert "⚠ 粒度：未能判定" not in rendered


# -------------------------------------------------------------------------- fan-out


def test_the_only_join_is_proven_safe_and_named_by_the_scope_it_sits_in(
    profile: dict,
) -> None:
    """``latest_dim`` is deduped by ``row_number() = 1`` on the join key, so the LEFT
    JOIN cannot multiply rows -- the risk entry has to say ``safe``, not ``unknown``."""
    risks = profile["output_shape"]["fan_out_risks"]
    assert len(risks) == 1
    risk = risks[0]
    assert risk["status"] == "safe"
    assert risk["scope_id"] == "cte:joined"
    assert risk["logic_block_id"] == "logic:cte:joined:join:001"
    assert risk["join_type"] == "LEFT_OUTER"
    assert risk["right"] == "cte:latest_dim"
    # The partition key is quoted as `cte:latest_dim` writes it, not as the physical
    # column it resolves to -- the reader is being told what the SQL says.
    assert risk["reason"] == (
        "右侧 row_number 按 segment 分区并以 = 1 过滤（logic:cte:joined:join:001）"
    )


def test_the_markdown_does_not_warn_about_the_safe_join(profile: dict) -> None:
    rendered = render_semantic_markdown(profile, sections=["shape"])
    assert "安全（safe）" in rendered
    assert "⚠ 有放大风险" not in rendered
    assert "⚠ 未知（unknown）" not in rendered


# ---------------------------------------------------------------- window intents


def test_the_dedup_window_is_read_as_keep_latest_and_points_at_its_consumer(
    profile: dict,
) -> None:
    action = _stage(profile, "cte:latest_dim")["actions"][0]
    assert action["type"] == "window"
    assert action["intent"] == "keep_latest_per_group"
    assert action["consumed_by"] == "logic:cte:joined:join:001"
    assert _stage(profile, "cte:latest_dim")["role"] == "dedup"


def test_a_row_preserving_window_is_not_mistaken_for_a_dedup_filter(
    profile: dict,
) -> None:
    """``cte:ranked`` only adds ``SUM(...) OVER (PARTITION BY band)``; nothing filters on
    it, so its intent is a running aggregate and no consumer claims it.

    C1: the stage ``role`` says ``window`` for exactly that reason. It used to say
    ``dedup`` -- the classifier labelled every window-bearing scope that way -- and a
    reader took the label as the stage's purpose while the grain walk (correctly)
    treated the scope as row-preserving (see ``via_scopes`` above).
    """
    stage = _stage(profile, "cte:ranked")
    action = stage["actions"][0]
    assert action["type"] == "window"
    assert action["intent"] == "running_aggregate"
    assert action["consumed_by"] is None
    assert stage["role"] == "window"
    # `band` is the derived CASE column `cte:agg` publishes; the statement never groups
    # by `amount`, so the restatement must not say it does.
    assert action["text"] == "按 band 分组，计算 SUM（band_total）；组内累计聚合"
    assert {item["column"] for item in action["fields"]} == {"amount"}


# ------------------------------------------------------------------ target binding


def test_the_target_columns_and_comments_come_from_the_ddl_metadata(
    lineage: dict, profile: dict
) -> None:
    output = lineage["related_metadata"]["output_tables"]["mart.metric_by_segment"]
    assert output["metadata_source"] == "target_ddl"
    assert output["metadata_complete"] is True
    assert _field(profile, "segment")["target_comment"] == "Segment code"
    assert _field(profile, "band")["column_label"] == "mart.metric_by_segment.band"


def test_the_filter_inside_the_join_on_clause_is_reported_as_a_warning(
    diagnostics: dict,
) -> None:
    """``d.rn = 1`` is a row filter riding in the ON clause: the join is still safe, and
    the reader is still told the ON clause is not purely a join condition."""
    types = {warning["type"] for warning in diagnostics.get("warnings") or []}
    assert "filter_in_join_on_clause" in types


# ------------------------------------------------------- WI-1g: logical names in text


def test_the_aggregate_line_names_the_two_group_by_items_not_their_four_columns(
    profile: dict,
) -> None:
    """Both GROUP BY items pierce to two branch columns each, and ``band``'s CASE reads
    ``amount``, which is not a grouping key at all. Naming the pierce stated a grain of
    four columns that the statement never wrote."""
    action = next(
        item for item in _stage(profile, "cte:agg")["actions"] if item["type"] == "aggregate"
    )
    assert action["text"] == (
        "按 segment、CASE WHEN amount >= 100 THEN 'HIGH' ELSE 'LOW' END 分组聚合："
        "SUM(amount)、COUNT(1)"
    )
    # the pierce is still published, as the action's fields rather than as its keys
    assert {item["column"] for item in action["fields"]} == {"segment", "seg_code", "amount"}


def test_the_join_states_one_key_and_keeps_the_union_cross_product_beside_it(
    profile: dict,
) -> None:
    """``a.segment = d.segment`` is one key; pierced through the UNION it is two pairs,
    and over a twelve-branch UNION it would be twelve."""
    rule = next(item for item in profile["rules"] if item["kind"] == "join_condition")
    assert rule["key_pairs"] == [{"left": "a.segment", "right": "d.segment"}]
    assert rule["physical_key_pairs"] == [
        {"left": "ods.events_a.segment", "right": "dim.segment_dim.segment"},
        {"left": "ods.events_b.seg_code", "right": "dim.segment_dim.segment"},
    ]
    action = next(
        item for item in _stage(profile, "cte:joined")["actions"] if item["type"] == "join"
    )
    assert "键 segment，" in action["text"]


def test_the_branch_steps_of_a_field_are_marked_as_branches(profile: dict) -> None:
    steps = _field(profile, "segment")["derivation"]
    assert steps[0]["branch"] == {"index": 1, "label": "ods.events_a"}
    assert steps[1]["branch"] == {"index": 2, "label": "ods.events_b"}
    assert "branch" not in steps[2]


def test_the_markdown_folds_the_chain_but_never_arrows_the_branches(profile: dict) -> None:
    rendered = render_semantic_markdown(profile, sections=["fields"])
    assert (
        "- 第 1–2/8 步：各分支直接透传"
        "（经 `union:events_norm:b01`、`union:events_norm:b02`）；粒度=preserved"
    ) in rendered
    assert (
        "- 第 4–8/8 步：直接透传"
        "（经 `cte:events_norm` → `cte:agg` → `cte:joined` → `cte:ranked` → `ROOT`）"
    ) in rendered


def test_the_inference_inventory_is_counted_by_path(profile: dict) -> None:
    assert profile["confidence"]["inferred_items"] == {
        "fields[].structural_role": 6,
        "output_shape.shape": 1,
        "output_shape.grain": 1,
        "output_shape.candidate_keys": 1,
        "output_shape.unexposed_keys": 1,
        "output_shape.key_confidence": 1,
        "output_shape.fan_out_risks[]": 1,
        "stages[].actions[].intent": 2,
    }


# -------------------------------------------------------- WI-2.1: metric definition


def test_the_two_measures_carry_a_card_and_the_keys_do_not(profile: dict) -> None:
    carrying = {
        field["column"] for field in profile["fields"] if field.get("metric_spec")
    }
    assert carrying == {"total", "cnt", "band_total"}


def test_the_card_counts_the_rows_of_both_union_branches(profile: dict) -> None:
    """The aggregate reads one CTE, which reads a UNION: a path that stopped at the
    union would name no table at all, and one that crossed the LEFT JOIN would add the
    dimension the metric never counts."""
    subject = _field(profile, "total")["metric_spec"]["subject"]
    assert subject["scope_id"] == "cte:agg"
    assert subject["tables"] == ["ods.events_a", "ods.events_b"]


def test_the_card_states_the_call_and_the_group_keys_that_reach_the_target(
    profile: dict,
) -> None:
    aggregation = _field(profile, "total")["metric_spec"]["aggregation"]
    assert aggregation["function"] == "SUM"
    assert aggregation["argument"] == "amount"
    assert aggregation["group_keys"] == [
        {"name": "segment", "target_column": "segment"},
        {"name": "band", "target_column": "band"},
    ]
    assert aggregation["text"] == "按 segment、band 汇总 SUM(amount)"


def test_the_statement_has_no_filter_so_the_two_condition_slots_are_empty(
    profile: dict,
) -> None:
    spec = _field(profile, "total")["metric_spec"]
    assert spec["time_range"] == []
    assert spec["inclusion"] == []
    assert spec["refresh"] is None


def test_a_count_reads_as_a_tally_and_a_sum_of_an_uncommented_column_does_not(
    profile: dict,
) -> None:
    assert _field(profile, "cnt")["metric_spec"]["unit"] == {
        "type": "bigint",
        "hint": "笔数",
        "hint_source": "function",
    }
    assert _field(profile, "total")["metric_spec"]["unit"] == {
        "type": "decimal(18,2)",
        "hint": None,
        "hint_source": None,
    }


def test_the_window_above_the_aggregate_is_post_aggregation_not_the_aggregation(
    profile: dict,
) -> None:
    """``band_total`` sums an already-summed column in a window: the card's aggregation
    stays the GROUP BY it came from, and the window is what happened afterwards."""
    spec = _field(profile, "band_total")["metric_spec"]
    assert spec["aggregation"]["function"] == "SUM"
    assert spec["subject"]["scope_id"] == "cte:agg"
    assert spec["post_aggregation"] == ["窗口函数 SUM(total)；按 band 分组"]


def test_the_evidence_names_the_aggregate_block_the_group_by_block_and_the_chain(
    profile: dict,
) -> None:
    assert _field(profile, "total")["metric_spec"]["evidence"] == [
        "logic:cte:agg:aggregate:001",
        "logic:cte:agg:group_by:001",
        "mc:003",
    ]


def test_the_markdown_renders_the_seven_line_card_for_the_measure(profile: dict) -> None:
    rendered = render_semantic_markdown(profile, sections=["fields"])
    assert (
        "- 口径：\n"
        "  - 统计对象：`ods.events_a`、`ods.events_b` 的记录（聚合于 `cte:agg`）\n"
        "  - 时间范围：未在聚合路径上发现日期过滤\n"
        "  - 纳入条件：无\n"
        "  - 聚合：按 segment、band 汇总 SUM(amount)（分组键落目标列 `segment`、`band`）\n"
        "  - 单位/类型：decimal(18,2)；单位未知\n"
        "  - 空值：无可证明的关联致空，未见缺失回填\n"
        "  - 更新频率：未知（任务元信息未提供）\n"
    ) in rendered


def test_the_field_table_compresses_the_card_into_one_column(profile: dict) -> None:
    rendered = render_semantic_markdown(profile, sections=["fields_table"])
    row = next(line for line in rendered.splitlines() if "| 4 |" in line)
    assert "| COUNT(1)；未在聚合路径上发现日期过滤 |" in row
    key_row = next(line for line in rendered.splitlines() if "| 1 |" in line)
    assert key_row.endswith("| candidate_key | — | ✓ |")
