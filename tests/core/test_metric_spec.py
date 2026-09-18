"""WI-2.1: ``fields[].metric_spec`` -- the deterministic metric-definition skeleton.

Seven slots, every one of them provable from the contract or published as ``null``:
统计对象 / 时间范围 / 纳入条件 / 聚合 / 单位 / 空值 / 更新频率. The tests below give each
slot one case where the SQL proves it and one where it does not, and then pin the two
failure modes the slot exists to avoid: a filter that sits on a bypass JOIN's right side
being counted into the metric's definition, and any table, column or scope id appearing
in the card that the source document never declared.

Nothing here asserts a business word: a card that said "近 30 天支付金额" because the
column is called ``paid_amount_30d`` would be exactly the fabrication R8 forbids.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.metadata.target_table_metadata import (
    TargetColumnMetadata,
    TargetMetadataMap,
    TargetTableMetadata,
)
from scope_lineage.render.semantic_markdown import render_semantic_markdown
from scope_lineage.render.semantic_profile import (
    METRIC_INCLUSION_WHERE,
    METRIC_PATHS,
    METRIC_SPEC_KEY_ORDER,
    METRIC_TIME_RANGE_KINDS,
    build_semantic_profile,
)
from scope_lineage.scope.scope_builder import parse_scope_lineage


FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN_GROUPS = ("lineage_contract", "task_lineage_contract")
GOLDEN_CASES = tuple(
    sorted(
        (
            path.parent
            for group in GOLDEN_GROUPS
            for path in (FIXTURES / group).glob("*/case.json")
        ),
        key=lambda path: (path.parent.name, path.name),
    )
)


# --------------------------------------------------------------------------- helpers


def _target_metadata(table: str, columns: list[dict], partitions=()) -> TargetMetadataMap:
    item = TargetTableMetadata(
        table_name=table,
        full_table_name=f"spark_catalog.{table}",
        columns=[
            TargetColumnMetadata(
                name=column["name"],
                data_type=column.get("type"),
                ordinal=index,
                is_partition=column["name"] in set(partitions),
                comment=column.get("comment"),
            )
            for index, column in enumerate(columns)
        ],
        partition_columns=list(partitions),
        ddl=None,
        source_file="synthetic-metric-spec.json",
        structure_source="schema",
    )
    return TargetMetadataMap({item.table_name: item})


def _profile(sql: str, *, schema=None, target_metadata=None) -> dict:
    document = to_lineage_dict(
        parse_scope_lineage(
            sql, "wi21", schema=schema, target_metadata=target_metadata
        )
    )
    return build_semantic_profile(document)


def _document(sql: str, *, schema=None, target_metadata=None) -> dict:
    return to_lineage_dict(
        parse_scope_lineage(sql, "wi21", schema=schema, target_metadata=target_metadata)
    )


def _field(profile: dict, column: str) -> dict:
    return next(item for item in profile["fields"] if item["column"] == column)


def _spec(profile: dict, column: str) -> dict:
    spec = _field(profile, column).get("metric_spec")
    assert spec is not None, f"{column} carries no metric_spec"
    return spec


def _card(profile: dict, label: str) -> dict[str, str]:
    """One field's rendered 口径卡 as ``{label: body}``, read out of section 5."""
    rendered = render_semantic_markdown(profile, sections=["fields"])
    section = rendered.split(f"### 字段 {label}")[1].split("### ")[0]
    return {
        line.split("：", 1)[0].strip("- ").strip(): line.split("：", 1)[1]
        for line in section.splitlines()
        if line.startswith("  - ")
    }


# --------------------------------------------------------------------------- fixtures


# One aggregating subquery under a COALESCE, with a date filter, a non-date filter and a
# CASE inside the aggregate call: the shape that fills every slot the contract can fill.
FULL_SQL = """
INSERT OVERWRITE TABLE mart.metric_daily PARTITION (dt='20260814')
SELECT customer_id, COALESCE(paid, 0) AS paid_total
FROM (
  SELECT customer_id,
         SUM(CASE WHEN pay_status = 'PAID' THEN pay_amount END) AS paid
  FROM dwd.order_detail
  WHERE stat_date = '20260814' AND channel = 'APP'
  GROUP BY customer_id
) s
"""

FULL_SCHEMA = {
    "dwd.order_detail": {
        "column_details": [
            {"name": "customer_id", "type": "string", "comment": "Customer key"},
            {"name": "pay_amount", "type": "decimal(18,2)", "comment": "单笔金额"},
            {"name": "pay_status", "type": "string", "comment": "Pay status"},
            {"name": "stat_date", "type": "date", "comment": "Stat date"},
            {"name": "channel", "type": "string", "comment": "Channel"},
        ]
    }
}

FULL_TARGET = _target_metadata(
    "mart.metric_daily",
    [
        {"name": "customer_id", "type": "string", "comment": "Customer key"},
        {"name": "paid_total", "type": "decimal(18,2)", "comment": "已支付金额合计"},
        {"name": "dt", "type": "string", "comment": "Partition date"},
    ],
    partitions=("dt",),
)


# The same statement stripped of everything the card could quote: no metadata, no
# filter, no CASE, no post-aggregation step.
BARE_SQL = """
INSERT INTO mart.bare
SELECT k, SUM(v) AS total FROM ods.src GROUP BY k
"""

BARE_SCHEMA = {"ods.src": ["k", "v"]}


# The shape WI-2.1 got wrong: the metric's argument is read from the *right* side of a
# LEFT JOIN, which the driving path deliberately refuses to cross. The date that bounds
# this number sits there, one day off the main table's own partition, and a group whose
# join matched nothing aggregates over nothing at all.
ARGUMENT_SQL = """
INSERT INTO mart.gap
SELECT a.k,
       MAX(DATEDIFF('20260814', x.oper_dt)) AS gap_days,
       SUM(a.v) AS total
FROM ods.main a
LEFT JOIN (SELECT DISTINCT id, oper_dt FROM ods.oper WHERE dt = '20260813') x
  ON a.k = x.id
WHERE a.dt = '20260814'
GROUP BY a.k
"""

ARGUMENT_SCHEMA = {
    "ods.main": ["k", "v", "dt"],
    "ods.oper": ["id", "oper_dt", "dt"],
}


@pytest.fixture(scope="module")
def argument_side() -> dict:
    return _profile(ARGUMENT_SQL, schema=ARGUMENT_SCHEMA)


@pytest.fixture(scope="module")
def full() -> dict:
    return _profile(FULL_SQL, schema=FULL_SCHEMA, target_metadata=FULL_TARGET)


@pytest.fixture(scope="module")
def bare() -> dict:
    return _profile(BARE_SQL, schema=BARE_SCHEMA)


# ------------------------------------------------------------------ which fields get one


def test_a_measure_and_an_aggregate_chain_get_a_card_and_a_plain_attribute_does_not(
    full: dict,
) -> None:
    assert _field(full, "paid_total")["structural_role"] == "measure"
    assert _field(full, "paid_total")["metric_spec"] is not None
    assert "metric_spec" not in _field(full, "customer_id")


# WI-2.1c item 2 made one slot conditional: ``time_dependent`` is published only when
# it is true, because a card that always carried ``"time_dependent": false`` would say
# "checked and clean" for a statement nobody checked.
CONDITIONAL_CARD_KEYS = ("time_dependent",)


def test_the_card_keys_are_fixed_and_ordered(full: dict) -> None:
    keys = tuple(_spec(full, "paid_total"))
    assert keys == tuple(
        key for key in METRIC_SPEC_KEY_ORDER if key not in CONDITIONAL_CARD_KEYS
    )


def test_every_card_key_is_declared_and_kept_in_the_declared_order(full: dict) -> None:
    """No card may publish a key the order tuple does not name, or name them out of order."""
    for field in full["fields"]:
        keys = list(field.get("metric_spec") or {})
        assert set(keys) <= set(METRIC_SPEC_KEY_ORDER)
        assert keys == [key for key in METRIC_SPEC_KEY_ORDER if key in set(keys)]


# ------------------------------------------------------------------------- 1. 统计对象


def test_the_subject_names_the_aggregate_scope_and_the_tables_it_reads(full: dict) -> None:
    subject = _spec(full, "paid_total")["subject"]
    assert subject["scope_id"] == "subq:s"
    assert subject["tables"] == ["dwd.order_detail"]
    assert "dwd.order_detail" in subject["text"]


def test_the_subject_of_a_root_aggregate_is_root_itself(bare: dict) -> None:
    subject = _spec(bare, "total")["subject"]
    assert subject["scope_id"] == "ROOT"
    assert subject["tables"] == ["ods.src"]


# ------------------------------------------------------------------------- 2. 时间范围


def test_a_date_equality_on_the_aggregation_path_is_the_time_range(full: dict) -> None:
    ranges = _spec(full, "paid_total")["time_range"]
    assert len(ranges) == 1
    assert ranges[0]["column"] == "dwd.order_detail.stat_date"
    assert ranges[0]["expression"] == "stat_date = '20260814'"
    # WI-2.9: a day written out in full is this instance's own date, not a stray literal.
    assert ranges[0]["kind"] == "instance_date"
    assert ranges[0]["scope_id"] == "subq:s"


def test_a_statement_without_a_date_filter_publishes_an_empty_time_range(
    bare: dict,
) -> None:
    assert _spec(bare, "total")["time_range"] == []


def test_a_scheduler_variable_is_a_parameter_not_a_literal() -> None:
    sql = FULL_SQL.replace("'20260814'", "${bizdate}", 1).replace(
        "stat_date = '20260814'", "stat_date = ${bizdate}"
    )
    profile = _profile(sql, schema=FULL_SCHEMA, target_metadata=FULL_TARGET)
    ranges = _spec(profile, "paid_total")["time_range"]

    assert [item["kind"] for item in ranges] == ["parameter"]
    assert ranges[0]["expression"] == "stat_date = ${bizdate}"


def test_a_two_sided_date_window_is_two_range_conjuncts() -> None:
    sql = FULL_SQL.replace(
        "stat_date = '20260814'", "stat_date >= '20260801' AND stat_date < '20260815'"
    )
    ranges = _spec(
        _profile(sql, schema=FULL_SCHEMA, target_metadata=FULL_TARGET), "paid_total"
    )["time_range"]

    assert [item["kind"] for item in ranges] == ["range", "range"]
    assert {item["column"] for item in ranges} == {"dwd.order_detail.stat_date"}


def test_every_published_kind_is_in_the_vocabulary(full: dict) -> None:
    for item in _spec(full, "paid_total")["time_range"]:
        assert item["kind"] in METRIC_TIME_RANGE_KINDS


# ------------------------------------------------------------------------- 3. 纳入条件


def test_a_non_date_filter_before_the_aggregate_is_an_inclusion(full: dict) -> None:
    inclusion = _spec(full, "paid_total")["inclusion"]
    filters = [item for item in inclusion if item["where"] == "filter"]

    assert [item["expression"] for item in filters] == ["channel = 'APP'"]
    assert filters[0]["scope_id"] == "subq:s"
    assert "channel = 'APP'" in filters[0]["text"]


def test_the_condition_inside_the_aggregate_call_is_its_own_inclusion(full: dict) -> None:
    cases = [
        item
        for item in _spec(full, "paid_total")["inclusion"]
        if item["where"] == "aggregate_case"
    ]
    assert len(cases) == 1
    assert cases[0]["expression"] == "pay_status = 'PAID'"
    assert cases[0]["text"] == "仅计 pay_status = 'PAID'"


def test_a_statement_with_neither_publishes_an_empty_inclusion(bare: dict) -> None:
    assert _spec(bare, "total")["inclusion"] == []


def test_every_published_where_is_in_the_vocabulary(full: dict) -> None:
    for item in _spec(full, "paid_total")["inclusion"]:
        assert item["where"] in METRIC_INCLUSION_WHERE


# A lookup joined in on the side: its own WHERE restricts the lookup, never the metric.
BYPASS_SQL = """
INSERT INTO mart.bypass
SELECT a.k, SUM(a.v) AS total
FROM ods.main a
LEFT JOIN (SELECT id, label FROM dim.lookup WHERE region = 'EU') d ON a.k = d.id
GROUP BY a.k
"""

BYPASS_SCHEMA = {
    "ods.main": ["k", "v"],
    "dim.lookup": ["id", "label", "region"],
}


def test_a_filter_on_a_bypass_joins_right_side_is_not_part_of_the_metric() -> None:
    """``region = 'EU'`` narrows the lookup, not the summed rows: counting it would
    state a metric definition the statement never wrote."""
    profile = _profile(BYPASS_SQL, schema=BYPASS_SCHEMA)
    spec = _spec(profile, "total")

    assert [item["expression"] for item in spec["inclusion"]] == []
    assert spec["subject"]["tables"] == ["ods.main"]
    # the filter is still a fact of the statement -- it is in rules[], just not here
    assert any("region" in str(rule["expression"]) for rule in profile["rules"])


def test_an_extra_on_condition_on_the_path_is_an_inclusion() -> None:
    """A condition riding in the ON clause restricts the joined rows the aggregate sees,
    so it belongs to the metric's definition -- labelled by where it sits."""
    sql = BYPASS_SQL.replace(
        "ON a.k = d.id", "ON a.k = d.id AND d.label = 'GOLD'"
    ).replace(" WHERE region = 'EU'", "")
    inclusion = _spec(_profile(sql, schema=BYPASS_SCHEMA), "total")["inclusion"]

    assert [(item["expression"], item["where"]) for item in inclusion] == [
        ("label = 'GOLD'", "join_condition")
    ]
    assert inclusion[0]["text"] == "关联条件 label = 'GOLD'"
    assert inclusion[0]["scope_id"] == "ROOT"


# --------------------------------------------------------------------------- 4. 聚合


def test_the_aggregation_names_the_function_the_argument_and_the_group_keys(
    full: dict,
) -> None:
    aggregation = _spec(full, "paid_total")["aggregation"]

    assert aggregation["function"] == "SUM"
    assert aggregation["argument"] == "pay_amount"
    assert aggregation["argument_comment"] == "单笔金额"
    assert aggregation["group_keys"] == [
        {"name": "customer_id", "target_column": "customer_id"}
    ]
    assert aggregation["text"] == "按 customer_id 汇总 SUM(pay_amount)"


def test_a_group_key_that_never_reaches_the_target_has_a_null_target_column() -> None:
    sql = """
    INSERT INTO mart.unexposed
    SELECT SUM(v) AS total FROM ods.src GROUP BY k
    """
    aggregation = _spec(
        _profile(sql, schema=BARE_SCHEMA), "total"
    )["aggregation"]

    assert aggregation["group_keys"] == [{"name": "k", "target_column": None}]


WRAPPED_AGGREGATE_SQL = """
INSERT INTO mart.observed
SELECT k, DATE_FORMAT(MAX(ts), 'yyyy-MM-dd') AS observed_day
FROM ods.obs GROUP BY k
"""

WRAPPED_AGGREGATE_SCHEMA = {
    "ods.obs": {
        "column_details": [
            {"name": "k", "type": "string", "comment": None},
            {"name": "ts", "type": "timestamp", "comment": None},
        ]
    }
}


def test_an_aggregate_under_a_scalar_call_is_still_the_metrics_aggregation() -> None:
    """WI-2.1d item 4: the step is typed by its outermost node, the metric by its call."""
    profile = _profile(WRAPPED_AGGREGATE_SQL, schema=WRAPPED_AGGREGATE_SCHEMA)
    aggregation = _spec(profile, "observed_day")["aggregation"]

    # MAX of a timestamp: a selective call over a temporal column is an event time.
    assert _field(profile, "observed_day")["structural_role"] == "event_time"
    assert aggregation["function"] == "MAX"
    assert aggregation["argument"] == "ts"
    assert aggregation["group_keys"] == [{"name": "k", "target_column": "k"}]


def test_the_call_wrapping_the_aggregate_is_restated_as_post_aggregation() -> None:
    spec = _spec(
        _profile(WRAPPED_AGGREGATE_SQL, schema=WRAPPED_AGGREGATE_SCHEMA), "observed_day"
    )

    assert spec["post_aggregation"] == ["外层 DATE_FORMAT(…, 'yyyy-MM-dd')"]


def test_a_direct_temporal_read_has_no_aggregation_at_all() -> None:
    sql = """
    INSERT INTO mart.events
    SELECT id, event_ts FROM ods.log WHERE dt = '20260814'
    """
    schema = {
        "ods.log": {
            "column_details": [
                {"name": "id", "type": "string", "comment": None},
                {"name": "event_ts", "type": "timestamp", "comment": None},
                {"name": "dt", "type": "string", "comment": None},
            ]
        }
    }
    profile = _profile(sql, schema=schema)

    assert _field(profile, "event_ts")["structural_role"] == "event_time"
    spec = _spec(profile, "event_ts")
    assert spec["aggregation"] is None
    assert spec["subject"]["tables"] == ["ods.log"]
    assert [item["column"] for item in spec["time_range"]] == ["ods.log.dt"]


# ------------------------------------------------------------------------ 5. 单位/类型


def test_a_unit_hint_is_quoted_from_the_target_comment(full: dict) -> None:
    unit = _spec(full, "paid_total")["unit"]

    assert unit["type"] == "decimal(18,2)"
    assert unit["hint"] == "金额"
    assert unit["hint_source"] == "comment"


def test_a_count_gets_its_hint_from_the_function_when_no_comment_says_so() -> None:
    sql = "INSERT INTO mart.c SELECT k, COUNT(1) AS cnt FROM ods.src GROUP BY k"
    unit = _spec(_profile(sql, schema=BARE_SCHEMA), "cnt")["unit"]

    assert unit["hint"] == "笔数"
    assert unit["hint_source"] == "function"


def test_a_sum_without_a_telling_comment_gets_no_hint(bare: dict) -> None:
    unit = _spec(bare, "total")["unit"]

    assert unit["hint"] is None
    assert unit["hint_source"] is None
    assert unit["type"] is None


# ---------------------------------------------------------------------------- 6. 空值


def test_a_coalesce_after_the_aggregate_is_the_default_value(full: dict) -> None:
    null_handling = _spec(full, "paid_total")["null_handling"]

    assert null_handling["nullable_by_join"] is False
    assert null_handling["default"] == "0"
    assert null_handling["default_source"] == "COALESCE"


def test_a_case_else_is_the_other_provable_default() -> None:
    sql = FULL_SQL.replace(
        "COALESCE(paid, 0) AS paid_total",
        "CASE WHEN paid > 0 THEN paid ELSE 0 END AS paid_total",
    )
    null_handling = _spec(
        _profile(sql, schema=FULL_SCHEMA, target_metadata=FULL_TARGET), "paid_total"
    )["null_handling"]

    assert null_handling["default"] == "0"
    assert null_handling["default_source"] == "CASE_ELSE"


def _full_tail(projection: str) -> dict:
    """``full`` with a different outer projection for ``paid_total``."""
    return _profile(
        FULL_SQL.replace("COALESCE(paid, 0) AS paid_total", f"{projection} AS paid_total"),
        schema=FULL_SCHEMA,
        target_metadata=FULL_TARGET,
    )


@pytest.mark.parametrize(
    "projection",
    [
        # WI-2.1d item 2, reason one: an ELSE that is a column fills nothing in -- it
        # carries another value through, which is still null when that value is.
        "CASE WHEN paid > 0 THEN 0 ELSE paid END",
        # Reason two: a CASE nested inside another call is that call's argument. Reading
        # it as the field's own tail published a grouping key's fallback branch as this
        # metric's default.
        "CAST(CASE WHEN paid > 0 THEN 1 ELSE 0 END AS STRING)",
    ],
)
def test_a_case_that_is_not_the_fields_own_constant_tail_proves_no_default(
    projection: str,
) -> None:
    null_handling = _spec(_full_tail(projection), "paid_total")["null_handling"]

    assert null_handling["default"] is None
    assert null_handling["default_source"] is None


def test_a_fill_step_of_this_fields_own_thread_is_still_the_default() -> None:
    """The COALESCE *is* that step, so it fills the null of the column the step produces."""
    sql = (
        "INSERT INTO mart.filled "
        "WITH agg AS (SELECT k, SUM(v) AS total FROM ods.src GROUP BY k), "
        "filled AS (SELECT k, COALESCE(total, 0) AS total FROM agg) "
        "SELECT k, total FROM filled"
    )
    null_handling = _spec(_profile(sql, schema=BARE_SCHEMA), "total")["null_handling"]

    assert null_handling["default"] == "0"
    assert null_handling["default_source"] == "COALESCE"


def test_a_fill_of_an_operand_is_not_a_default_for_the_value_built_from_it() -> None:
    """``COALESCE(a, 0) - COALESCE(b, 0)`` fills two operands; the difference has no fill."""
    sql = (
        "INSERT INTO mart.delta "
        "WITH agg AS (SELECT k, SUM(v) AS hi, COUNT(v) AS lo FROM ods.src GROUP BY k), "
        "d AS (SELECT k, COALESCE(hi, 0) - COALESCE(lo, 0) AS delta FROM agg) "
        "SELECT k, delta FROM d"
    )
    null_handling = _spec(_profile(sql, schema=BARE_SCHEMA), "delta")["null_handling"]

    assert null_handling["default"] is None
    assert null_handling["default_source"] is None


def test_a_coalesce_belonging_to_a_neighbouring_column_is_not_this_fields_default() -> None:
    """WI-2.1d item 2: one ordered chain interleaves threads, and a default is per field.

    ``rk``'s chain carries the step that computes ``rate`` -- the window reads it -- so
    sweeping the steps after the aggregate for a COALESCE published ``rate``'s fill as
    the rank's own default, a value ``rk`` never takes.
    """
    sql = (
        "INSERT INTO mart.ranked "
        "WITH agg AS (SELECT k, SUM(v) AS total, COUNT(v) AS n FROM ods.src GROUP BY k), "
        "rated AS (SELECT k, COALESCE(total, 0) / n AS rate FROM agg) "
        "SELECT k, RANK() OVER (ORDER BY rate) AS rk FROM rated"
    )
    null_handling = _spec(_profile(sql, schema=BARE_SCHEMA), "rk")["null_handling"]

    assert null_handling["default"] is None
    assert null_handling["default_source"] is None


def test_a_case_inside_the_aggregate_call_is_not_the_metrics_default() -> None:
    """The ELSE runs per row, before the group exists; the metric's null is the group's."""
    sql = "INSERT INTO mart.pre SELECT k, SUM(CASE WHEN v > 0 THEN v ELSE 0 END) AS total "
    sql += "FROM ods.src GROUP BY k"
    null_handling = _spec(_profile(sql, schema=BARE_SCHEMA), "total")["null_handling"]

    assert null_handling["default"] is None
    assert null_handling["default_source"] is None


def test_no_fill_means_no_default(bare: dict) -> None:
    null_handling = _spec(bare, "total")["null_handling"]

    assert null_handling == {
        "nullable_by_join": False,
        "default": None,
        "default_source": None,
    }


# ------------------------------------------------------------------------ 7. 更新频率


def test_the_refresh_slot_is_always_null_this_round(full: dict, bare: dict) -> None:
    """Schedule information is task metadata, which the contract does not carry yet."""
    assert _spec(full, "paid_total")["refresh"] is None
    assert _spec(bare, "total")["refresh"] is None


# ------------------------------------------------------------- post aggregation / 证据


def test_the_steps_after_the_aggregate_are_restated_once_more(full: dict) -> None:
    spec = _spec(full, "paid_total")

    assert spec["post_aggregation"] == ["空值回填为 0"]


def test_nothing_after_the_aggregate_means_no_post_aggregation(bare: dict) -> None:
    assert _spec(bare, "total")["post_aggregation"] == []


def test_the_evidence_points_at_the_blocks_and_the_chain_the_card_was_read_from(
    full: dict,
) -> None:
    spec = _spec(full, "paid_total")
    evidence = spec["evidence"]

    assert _field(full, "paid_total")["mapping_chain_id"] in evidence
    assert any(item.startswith("logic:subq:s:group_by") for item in evidence)
    assert any(item.startswith("logic:subq:s:filter") for item in evidence)
    assert evidence == sorted(set(evidence), key=evidence.index)


# ---------------------------------------------------------------------------- markdown


def test_section_five_renders_the_fixed_seven_line_card(full: dict) -> None:
    lines = render_semantic_markdown(full, sections=["fields"]).splitlines()
    start = lines.index("- 口径：")
    card = lines[start : start + 8]

    assert [line.split("：", 1)[0].strip("- ").strip() for line in card] == [
        "口径",
        "统计对象",
        "时间范围",
        "纳入条件",
        "聚合",
        "单位/类型",
        "空值",
        "更新频率",
    ]
    assert all(line.startswith("  - ") for line in card[1:])
    # the card sits directly under the one-sentence meaning, before the labelled facts
    assert lines[start - 1].startswith("- 语义：")
    assert lines[start + 8].startswith("- 目标注释：")


def test_the_card_says_so_when_a_slot_is_empty(bare: dict) -> None:
    rendered = render_semantic_markdown(bare, sections=["fields"])

    assert "  - 时间范围：未在聚合路径上发现日期过滤" in rendered
    assert "  - 纳入条件：无" in rendered
    assert "  - 更新频率：未知（任务元信息未提供）" in rendered


def test_a_field_without_a_card_gets_no_card_lines(full: dict) -> None:
    rendered = render_semantic_markdown(full, sections=["fields"])
    section = rendered.split("### 字段 mart.metric_daily.customer_id")[1].split("###")[0]

    assert "- 口径：" not in section


def test_the_field_table_carries_a_compressed_definition_column(full: dict) -> None:
    rendered = render_semantic_markdown(full, sections=["fields_table"])
    header = next(line for line in rendered.splitlines() if line.startswith("| # |"))

    assert header == "| # | 字段 | 一句话语义 | 结构角色 | 口径 | 追溯 |"
    row = next(line for line in rendered.splitlines() if "paid_total" in line)
    assert "SUM(pay_amount)" in row
    assert "stat_date = '20260814'" in row


# ------------------------------------------------------------------ determinism (R8)


def test_the_card_is_byte_identical_across_two_builds() -> None:
    document = _document(FULL_SQL, schema=FULL_SCHEMA, target_metadata=FULL_TARGET)
    first = build_semantic_profile(document)
    second = build_semantic_profile(document)

    assert json.dumps(first, ensure_ascii=False) == json.dumps(second, ensure_ascii=False)


# ------------------------------------------------------- anti-fabrication property test


def _known_tables(document: dict) -> set[str]:
    tables = set(document.get("source_tables") or [])
    if document.get("target_table"):
        tables.add(str(document["target_table"]))
    metadata = document.get("related_metadata") or {}
    tables |= set(metadata.get("input_tables") or {})
    tables |= set(metadata.get("output_tables") or {})
    return tables


def _known_columns(document: dict) -> set[str]:
    columns: set[str] = set()
    metadata = document.get("related_metadata") or {}
    for group in ("input_tables", "output_tables"):
        for item in (metadata.get(group) or {}).values():
            for detail in item.get("column_details") or []:
                columns.add(str(detail.get("name")))
    for entry in document.get("end_to_end_lineage") or []:
        columns.add(str(entry.get("column")))
        for source in entry.get("physical_sources") or []:
            columns.add(str(source.get("column")))
    for scope in (document.get("scopes") or {}).values():
        for output in scope.get("outputs") or []:
            columns.add(str(output.get("name")))
    return columns


def _assert_card_invents_nothing(profile: dict, document: dict) -> int:
    tables = _known_tables(document)
    scopes = set(document.get("scopes") or {}) | tables
    columns = _known_columns(document)
    target_columns = {
        str(entry.get("column")) for entry in document.get("end_to_end_lineage") or []
    }
    checked = 0
    for field in profile.get("fields") or []:
        spec = field.get("metric_spec")
        if not spec:
            continue
        checked += 1
        assert spec["subject"]["scope_id"] in scopes
        for table in [
            *spec["subject"]["tables"],
            *(spec["subject"].get("argument_tables") or []),
        ]:
            assert table in tables, f"invented table {table!r}"
        for item in [*spec["time_range"], *spec["inclusion"]]:
            assert item["scope_id"] in scopes, f"invented scope {item['scope_id']!r}"
            assert item["path"] in METRIC_PATHS, f"invented path {item['path']!r}"
        for item in spec["time_range"]:
            owner, _, column = str(item["column"]).rpartition(".")
            assert column in columns, f"invented column {column!r}"
            assert not owner or owner in tables, f"invented owner {owner!r}"
        for key in (spec["aggregation"] or {}).get("group_keys") or []:
            assert key["target_column"] is None or key["target_column"] in target_columns
    return checked


PROPERTY_CASES = (
    (FULL_SQL, FULL_SCHEMA, FULL_TARGET),
    (BARE_SQL, BARE_SCHEMA, None),
    (BYPASS_SQL, BYPASS_SCHEMA, None),
    (ARGUMENT_SQL, ARGUMENT_SCHEMA, None),
)


@pytest.mark.parametrize(
    "sql,schema,target",
    PROPERTY_CASES,
    ids=("full", "bare", "bypass", "argument"),
)
def test_a_synthetic_card_never_invents_an_identifier(sql, schema, target) -> None:
    document = _document(sql, schema=schema, target_metadata=target)
    assert _assert_card_invents_nothing(build_semantic_profile(document), document)


@pytest.mark.parametrize(
    "case_dir",
    [case for case in GOLDEN_CASES if case.parent.name == "lineage_contract"],
    ids=lambda path: path.name,
)
def test_a_golden_card_never_invents_an_identifier(case_dir: Path) -> None:
    lineage = json.loads((case_dir / "lineage.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((case_dir / "diagnostics.json").read_text(encoding="utf-8"))
    _assert_card_invents_nothing(build_semantic_profile(lineage, diagnostics), lineage)


# ------------------------------------------------- argument path (the bypass right side)


def test_the_argument_sides_own_date_filter_is_a_second_time_range(
    argument_side: dict,
) -> None:
    """The metric's parameter comes from the joined scope, so the date that scope pins
    is part of this number's time range -- quoting only the driving side stated a
    window the value was never read over."""
    ranges = _spec(argument_side, "gap_days")["time_range"]

    assert [(item["path"], item["column"], item["expression"]) for item in ranges] == [
        ("grain", "ods.main.dt", "dt = '20260814'"),
        ("argument", "ods.oper.dt", "dt = '20260813'"),
    ]
    assert [item["scope_id"] for item in ranges] == ["ROOT", "subq:x"]


def test_a_metric_read_from_the_driving_table_keeps_the_one_grain_range(
    argument_side: dict,
) -> None:
    """Same statement, same joins: a measure whose argument is a driving-table column
    sees only the driving side's filter, exactly as before."""
    spec = _spec(argument_side, "total")

    assert [(item["path"], item["column"]) for item in spec["time_range"]] == [
        ("grain", "ods.main.dt")
    ]
    assert "argument_tables" not in spec["subject"]
    assert spec["null_handling"]["nullable_by_join"] is False


def test_an_argument_from_a_left_joins_right_side_is_nullable(
    argument_side: dict,
) -> None:
    null_handling = _spec(argument_side, "gap_days")["null_handling"]

    assert null_handling["nullable_by_join"] is True
    assert null_handling["nullable_argument"] == {
        "scope_id": "subq:x",
        "join_type": "LEFT_OUTER",
        "side": "right",
    }
    assert _field(argument_side, "gap_days")["nullable_by_join"] is True


def test_the_subject_keeps_the_driving_table_and_names_the_argument_table(
    argument_side: dict,
) -> None:
    subject = _spec(argument_side, "gap_days")["subject"]

    assert subject["tables"] == ["ods.main"]
    assert subject["argument_tables"] == ["ods.oper"]
    assert subject["text"] == "ods.main 的记录，指标值取自 ods.oper"


def test_an_argument_from_an_inner_joins_right_side_is_not_nullable() -> None:
    """An INNER JOIN drops the unmatched driving row instead of nulling the argument,
    so the range still counts -- the row is gone either way -- but the value cannot be
    null for a row that survived."""
    profile = _profile(
        ARGUMENT_SQL.replace("LEFT JOIN", "INNER JOIN"), schema=ARGUMENT_SCHEMA
    )
    spec = _spec(profile, "gap_days")

    assert [item["path"] for item in spec["time_range"]] == ["grain", "argument"]
    assert spec["null_handling"]["nullable_by_join"] is False
    assert "nullable_argument" not in spec["null_handling"]


def test_a_coalesce_over_the_argument_fills_the_join_null_in() -> None:
    sql = ARGUMENT_SQL.replace(
        "MAX(DATEDIFF('20260814', x.oper_dt))",
        "MAX(DATEDIFF('20260814', COALESCE(x.oper_dt, '19700101')))",
    )
    null_handling = _spec(_profile(sql, schema=ARGUMENT_SCHEMA), "gap_days")[
        "null_handling"
    ]

    assert null_handling["nullable_by_join"] is False
    assert null_handling["default"] == "'19700101'"
    assert null_handling["default_source"] == "COALESCE"


def test_a_count_over_a_nullable_argument_answers_zero_not_null() -> None:
    sql = ARGUMENT_SQL.replace(
        "MAX(DATEDIFF('20260814', x.oper_dt))", "COUNT(x.oper_dt)"
    )
    null_handling = _spec(_profile(sql, schema=ARGUMENT_SCHEMA), "gap_days")[
        "null_handling"
    ]

    assert null_handling["nullable_by_join"] is False


def test_a_bypass_join_the_argument_never_reads_is_still_excluded() -> None:
    """The reason the two paths are separate: a lookup joined in for a column this
    metric does not read is on neither path, and its WHERE stays out of the card."""
    profile = _profile(BYPASS_SQL, schema=BYPASS_SCHEMA)
    spec = _spec(profile, "total")

    assert spec["inclusion"] == []
    assert spec["time_range"] == []
    assert "argument_tables" not in spec["subject"]


def test_every_published_path_is_in_the_vocabulary(argument_side: dict) -> None:
    spec = _spec(argument_side, "gap_days")
    for item in [*spec["time_range"], *spec["inclusion"]]:
        assert item["path"] in METRIC_PATHS


def test_a_non_date_filter_on_the_argument_side_is_an_argument_inclusion() -> None:
    sql = ARGUMENT_SQL.replace("WHERE dt = '20260813'", "WHERE dt = '20260813' AND id <> ''")
    inclusion = _spec(_profile(sql, schema=ARGUMENT_SCHEMA), "gap_days")["inclusion"]

    assert [(item["path"], item["expression"]) for item in inclusion] == [
        ("argument", "id <> ''")
    ]


# ------------------------------------------------------- argument path in the markdown


def test_the_card_marks_the_argument_sides_date_and_the_join_null(
    argument_side: dict,
) -> None:
    card = _card(argument_side, "mart.gap.gap_days")

    assert "（参数来源侧）" in card["时间范围"]
    assert card["时间范围"].count("（参数来源侧）") == 1
    assert "指标值取自" in card["统计对象"]
    assert card["空值"].startswith("参数来自 LEFT JOIN 右侧（subq:x），关联不上时为空")


# ----------------------------------------- WI-2.1c item 1: a date difference's own unit


DIFFERENCE_SQL = """
INSERT INTO mart.gap_metrics
SELECT k,
       MAX(DATEDIFF(end_dt, start_dt)) AS gap_days,
       AVG(MONTHS_BETWEEN(end_dt, start_dt)) AS gap_months,
       SUM(UNIX_TIMESTAMP(end_ts) - UNIX_TIMESTAMP(start_ts)) AS gap_seconds,
       SUM(amount) AS total
FROM ods.spans
WHERE dt = '20260814'
GROUP BY k
"""

DIFFERENCE_SCHEMA = {
    "ods.spans": ["k", "start_dt", "end_dt", "start_ts", "end_ts", "amount", "dt"]
}


@pytest.fixture(scope="module")
def differences() -> dict:
    return _profile(DIFFERENCE_SQL, schema=DIFFERENCE_SCHEMA)


@pytest.mark.parametrize(
    "column,hint",
    [("gap_days", "天"), ("gap_months", "月"), ("gap_seconds", "秒")],
)
def test_a_date_difference_metric_carries_the_calls_own_unit(
    differences: dict, column: str, hint: str
) -> None:
    """The unit is stated by the call, and the aggregate wrapped around it keeps it."""
    unit = _spec(differences, column)["unit"]

    assert (unit["hint"], unit["hint_source"]) == (hint, "function")


def test_a_plain_sum_over_a_column_still_earns_no_unit(differences: dict) -> None:
    unit = _spec(differences, "total")["unit"]

    assert (unit["hint"], unit["hint_source"]) == (None, None)


def test_the_card_prints_the_difference_unit_with_its_source(differences: dict) -> None:
    card = _card(differences, "mart.gap_metrics.gap_days")

    assert card["单位/类型"].endswith("天（来自函数）")


# ------------------------------- WI-2.1c item 2: a value that depends on the run moment


TIME_DEPENDENT_SQL = """
INSERT INTO mart.gap_metrics
SELECT k,
       SUM(DATEDIFF(CURRENT_DATE, start_dt)) AS age_days,
       MAX(DATEDIFF(end_dt, start_dt)) AS gap_days
FROM ods.spans
WHERE dt = '20260814'
GROUP BY k
"""


@pytest.fixture(scope="module")
def time_dependent() -> dict:
    return _profile(TIME_DEPENDENT_SQL, schema=DIFFERENCE_SCHEMA)


def test_a_metric_computed_from_the_run_moment_is_flagged(time_dependent: dict) -> None:
    assert _spec(time_dependent, "age_days")["time_dependent"] is True


def test_a_metric_over_two_data_columns_is_not_flagged(time_dependent: dict) -> None:
    """The key is absent rather than false: nothing was found, nothing is claimed."""
    assert "time_dependent" not in _spec(time_dependent, "gap_days")


def test_the_time_range_line_says_the_number_drifts(time_dependent: dict) -> None:
    card = _card(time_dependent, "mart.gap_metrics.age_days")

    assert card["时间范围"].endswith("（含运行时刻函数，结果随跑批时间漂移）")
    assert "（含运行时刻函数" not in _card(time_dependent, "mart.gap_metrics.gap_days")[
        "时间范围"
    ]


# -------------------------- WI-2.1c item 3: the two paths pinned to different literals


def test_two_paths_pinned_to_different_days_are_both_marked(
    argument_side: dict,
) -> None:
    ranges = _spec(argument_side, "gap_days")["time_range"]

    assert [item["mismatch"] for item in ranges] == [True, True]


def test_two_paths_pinned_to_the_same_day_are_not_marked() -> None:
    sql = ARGUMENT_SQL.replace("dt = '20260813'", "dt = '20260814'")
    ranges = _spec(_profile(sql, schema=ARGUMENT_SCHEMA), "gap_days")["time_range"]

    assert len(ranges) == 2
    assert all("mismatch" not in item for item in ranges)


def test_one_path_alone_cannot_disagree_with_itself(argument_side: dict) -> None:
    """``total`` reads the driving side only, so its single conjunct stays unmarked."""
    assert [item.get("mismatch") for item in _spec(argument_side, "total")["time_range"]] == [
        None
    ]


def test_the_card_states_the_gap_in_days(argument_side: dict) -> None:
    card = _card(argument_side, "mart.gap.gap_days")

    assert "（`dt = '20260813'` 另一侧取前 1 日）" in card["时间范围"]
    assert "（`dt = '20260814'` 另一侧取后 1 日）" in card["时间范围"]


def test_a_gap_between_unmeasurable_literals_is_stated_without_a_number() -> None:
    sql = ARGUMENT_SQL.replace("dt = '20260813'", "dt = 'W202633'")
    profile = _profile(sql, schema=ARGUMENT_SCHEMA)
    ranges = _spec(profile, "gap_days")["time_range"]

    assert [item.get("mismatch") for item in ranges] == [True, True]
    assert "另一侧取另一天）" in _card(profile, "mart.gap.gap_days")["时间范围"]
    assert "日）" not in _card(profile, "mart.gap.gap_days")["时间范围"]


def test_the_mismatch_finding_points_at_the_metrics_it_affects(
    argument_side: dict,
) -> None:
    """WI-2.1c item 3: the governance lead names the mapping chain of the metric whose
    own time range carries the disagreement, so the reader is not left re-deriving it."""
    finding = next(
        item
        for item in argument_side["confidence"]["findings"]
        if item["kind"] == "partition_literal_mismatch"
    )
    chain = _field(argument_side, "gap_days")["mapping_chain_id"]

    assert chain in finding["evidence"]
    assert _field(argument_side, "total")["mapping_chain_id"] not in finding["evidence"]
