"""What a dedup window really keeps, and a string column compared with a number.

1. **M5: an ORDER BY column the window's input pins to one value orders nothing.**
   ``row_number() OVER (PARTITION BY k ORDER BY dt DESC)`` over ``WHERE dt = '…'`` keeps
   an arbitrary row of each group, not the latest one: the intent is
   ``keep_arbitrary_per_group``. A range on the column, or a second ORDER BY item, still
   orders the rows.
2. **G1c: descending on a string column is lexicographic.** The rule text keeps
   「每组保留最新一条」 and says the order column is a string sorted as text.
3. **G1a: a string column compared with a numeric literal is a finding**
   (``numeric_compare_on_string``). What the comparison does depends on the engine's
   implicit cast, so the text says the types disagree and asks for a check. A partition
   filter is left out: it decides which partitions are read, not what a value means.

Every fixture is synthetic.
"""

from __future__ import annotations

import json

from scope_lineage import build_semantic_profile
from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.metadata.schema_metadata import load_schema
from scope_lineage.scope.scope_builder import parse_scope_lineage

TYPED_SCHEMA = {
    "tables": [
        {
            "table_name": "ods.ev",
            "schema": [
                {"columnName": "k", "columnType": "string", "columnIndex": 0},
                {"columnName": "ts_ms", "columnType": "string", "columnIndex": 1},
                {"columnName": "n", "columnType": "bigint", "columnIndex": 2},
                {"columnName": "upd", "columnType": "string", "columnIndex": 3},
                {"columnName": "ut", "columnType": "timestamp", "columnIndex": 4},
                {"columnName": "dt", "columnType": "string", "columnIndex": 5, "isPartition": True},
            ],
        },
        {
            "table_name": "dw.out",
            "schema": [
                {"columnName": "k", "columnType": "string", "columnIndex": 0},
                {"columnName": "v", "columnType": "string", "columnIndex": 1},
            ],
        },
    ]
}


def _profile(sql: str, tmp_path) -> dict:
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(TYPED_SCHEMA), encoding="utf-8")
    document = to_lineage_dict(
        parse_scope_lineage(sql, "t", schema=load_schema(str(path)))
    )
    return build_semantic_profile(document)


def _window_actions(profile: dict) -> list[dict]:
    return [
        action
        for stage in profile["stages"]
        for action in stage.get("actions") or []
        if action.get("type") == "window"
    ]


def _dedup(where: str, order: str) -> str:
    return (
        "INSERT OVERWRITE TABLE dw.out SELECT k, upd AS v FROM (SELECT k, upd, row_number() OVER"
        f" (PARTITION BY k ORDER BY {order}) rn FROM ods.ev WHERE {where}) a WHERE a.rn = 1"
    )


# --- M5 -------------------------------------------------------------------------------


def test_ordering_by_a_column_pinned_to_one_value_keeps_an_arbitrary_row(tmp_path):
    (action,) = _window_actions(_profile(_dedup("dt = '20260101'", "dt DESC"), tmp_path))
    assert action["intent"] == "keep_arbitrary_per_group"
    assert "每组保留任意一条" in action["text"]
    assert "最新" not in action["text"]


def test_a_range_on_the_order_column_still_orders(tmp_path):
    (action,) = _window_actions(_profile(_dedup("dt >= '20260101'", "dt DESC"), tmp_path))
    assert action["intent"] == "keep_latest_per_group"


def test_a_second_order_column_still_orders(tmp_path):
    (action,) = _window_actions(
        _profile(_dedup("dt = '20260101'", "dt DESC, ut DESC"), tmp_path)
    )
    assert action["intent"] == "keep_latest_per_group"


# --- G1c ------------------------------------------------------------------------------


def test_descending_on_a_string_column_says_it_sorts_as_text(tmp_path):
    (action,) = _window_actions(_profile(_dedup("n > 0", "upd DESC"), tmp_path))
    assert action["intent"] == "keep_latest_per_group"
    assert "每组保留最新一条" in action["text"]
    assert "upd 为 string，按字典序" in action["text"]


def test_descending_on_a_timestamp_column_does_not(tmp_path):
    (action,) = _window_actions(_profile(_dedup("n > 0", "ut DESC"), tmp_path))
    assert action["intent"] == "keep_latest_per_group"
    assert "字典序" not in action["text"]


# --- G1a ------------------------------------------------------------------------------


def _numeric_findings(profile: dict) -> list[dict]:
    return [
        item
        for item in profile["confidence"]["findings"]
        if item["kind"] == "numeric_compare_on_string"
    ]


def test_a_string_column_compared_with_a_number_is_a_finding(tmp_path):
    profile = _profile(
        "INSERT OVERWRITE TABLE dw.out SELECT e.k, if(e.ts_ms > 0, e.ts_ms, NULL) AS v"
        " FROM ods.ev e",
        tmp_path,
    )
    (finding,) = _numeric_findings(profile)
    assert finding["severity"] == "warn"
    assert "ods.ev" in finding["text"] and "ts_ms" in finding["text"]
    assert "string" in finding["text"] and "取决于引擎" in finding["text"]
    assert finding["evidence"]


def test_a_bigint_column_compared_with_a_number_is_not(tmp_path):
    profile = _profile(
        "INSERT OVERWRITE TABLE dw.out SELECT e.k, if(e.n > 0, e.upd, NULL) AS v FROM ods.ev e",
        tmp_path,
    )
    assert _numeric_findings(profile) == []


def test_a_partition_filter_with_an_unquoted_date_is_not(tmp_path):
    profile = _profile(
        "INSERT OVERWRITE TABLE dw.out SELECT e.k, e.upd AS v FROM ods.ev e WHERE e.dt = 20260101",
        tmp_path,
    )
    assert _numeric_findings(profile) == []


def test_a_string_column_compared_with_a_string_literal_is_not(tmp_path):
    profile = _profile(
        "INSERT OVERWRITE TABLE dw.out SELECT e.k, e.upd AS v FROM ods.ev e WHERE e.ts_ms > '0'",
        tmp_path,
    )
    assert _numeric_findings(profile) == []


def test_columns_of_one_table_compared_with_numbers_are_one_finding(tmp_path):
    profile = _profile(
        "INSERT OVERWRITE TABLE dw.out SELECT e.k,"
        " CASE WHEN e.ts_ms > 0 THEN 'a' WHEN e.upd > -1 THEN 'b' END AS v"
        " FROM ods.ev e WHERE e.k <> 0",
        tmp_path,
    )
    (finding,) = _numeric_findings(profile)
    for column in ("ts_ms", "upd", "k"):
        assert column in finding["text"]
