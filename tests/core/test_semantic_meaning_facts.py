"""The packet facts the meaning checks (10-13) read, derived one at a time.

- a JOIN's right side, the names a writer may call it by, and the fan-out verdict the
  semantic profile already reached for it (check 10);
- the literal outputs of a CASE / IF column and which source values each gathers
  (check 11);
- the value-meaning pairs a comment spells out (check 12);
- the lifecycle and data volume a script's header comment states (check 13).
"""

from __future__ import annotations

from scope_lineage.semantics.comment_values import listed_labels, value_labels
from scope_lineage.semantics.packet_meaning import (
    case_outputs,
    code_expression,
    header_facts,
    join_facts,
)

# ------------------------------------------------------------------ joins


def _statement(**risk) -> dict:
    return {
        "inputs": [{"table": "demo_ods.ods_left_df"}, {"table": "demo_ods.ods_right_df"}],
        "stages": [{"scope_id": "subq:r", "upstream_physical_tables": ["demo_ods.ods_pay_di"]}],
        "output_shape": {"fan_out_risks": [{
            "logic_block_id": "logic:ROOT:join:001", "scope_id": "ROOT",
            "join_type": "LEFT_OUTER", "right": "demo_ods.ods_right_df",
            "status": "risk", "reason": "right side not proven unique", "path": "grain", **risk,
        }]},
    }


def _join(right: str, pair: str = "b.id", evidence: str = "logic:ROOT:join:001") -> dict:
    return {"kind": "join_condition", "right_input": right, "evidence": evidence,
            "key_pairs": [{"left": "a.id", "right": pair}]}


def test_a_join_onto_a_physical_table_carries_its_verdict_and_alias() -> None:
    facts = join_facts(_statement(), _join("demo_ods.ods_right_df"))
    assert facts == {
        "right": "demo_ods.ods_right_df",
        "right_aliases": ["b"],
        "right_tables": ["demo_ods.ods_right_df"],
        "fan_out": {"status": "risk", "reason": "right side not proven unique", "path": "grain"},
    }


def test_a_join_onto_a_subquery_names_the_tables_behind_it() -> None:
    facts = join_facts(_statement(), _join("subq:r", "r.id", "logic:ROOT:join:009"))
    assert facts["right_aliases"] == ["r"]
    assert facts["right_tables"] == ["demo_ods.ods_pay_di"]
    assert facts["fan_out"] is None  # on no path the profile walked


# ------------------------------------------------------------------ CASE outputs


def test_a_case_with_literal_outputs_lists_each_value_and_what_feeds_it() -> None:
    outputs = case_outputs("CASE WHEN `t`.`tp` IN (1, 2) THEN 'R' WHEN `t`.`tp` = 3 THEN 'I' ELSE 'I' END")
    assert outputs == [
        {"value": "R", "when": ["`t`.`tp` IN (1, 2)"], "source_values": ["1", "2"], "catch_all": False},
        {"value": "I", "when": ["`t`.`tp` = 3", "ELSE"], "source_values": ["3"], "catch_all": True},
    ]


def test_a_simple_case_and_an_if_are_read_the_same_way() -> None:
    simple = case_outputs("CASE `st` WHEN '0' THEN 0 WHEN '1' THEN 1 END")
    assert [(o["value"], o["source_values"]) for o in simple] == [("0", ["0"]), ("1", ["1"])]
    flag = case_outputs("IF(`amt` > 0, 'Y', 'N')")
    assert [(o["value"], o["source_values"], o["catch_all"]) for o in flag] == [
        ("Y", None, False), ("N", [], True),
    ]


def test_a_case_with_a_computed_output_or_no_case_has_no_literal_outputs() -> None:
    assert case_outputs("CASE WHEN `x` IS NULL THEN 0 ELSE `amt` END") == []
    assert case_outputs("COALESCE(`x`, 0)") == []
    assert case_outputs("CASE WHEN (") == []
    assert case_outputs(None) == []


def test_the_case_is_read_where_it_was_computed_not_where_it_was_projected() -> None:
    field = {"expression": "`latest`.`st`", "derivation": [
        {"step_type": "case_when", "expression": "CASE WHEN `s` = 1 THEN 'A' ELSE 'B' END"},
        {"step_type": "direct_projection", "expression": "`latest`.`st`"},
    ]}
    assert code_expression(field) == "CASE WHEN `s` = 1 THEN 'A' ELSE 'B' END"
    assert code_expression({"expression": "`x`"}) == "`x`"


def test_null_outputs_are_not_code_values() -> None:
    outputs = case_outputs("CASE WHEN `x` = 'A' THEN '1' ELSE NULL END")
    assert [o["value"] for o in outputs] == ["1"]


# ------------------------------------------------------------------ comments


def test_value_meaning_pairs_are_read_in_the_usual_spellings() -> None:
    assert value_labels("状态 0-申请 1-成功 2-失败") == {"0": "申请", "1": "成功", "2": "失败"}
    assert value_labels("推送状态：0未推送，1已推送") == {"0": "未推送", "1": "已推送"}
    assert value_labels("类型:I是分期，R非分期") == {"I": "是分期", "R": "非分期"}
    assert value_labels("1:是,0:否") == {"1": "是", "0": "否"}
    assert value_labels("客户号") == {}


def test_a_comment_listing_labels_yields_its_items() -> None:
    assert listed_labels("账户状态：正常、锁定、删除") == {"正常", "锁定", "删除"}
    assert listed_labels("账户状态") == set()


# ------------------------------------------------------------------ header


def test_the_header_states_a_lifecycle_and_a_volume() -> None:
    sql = "-- 表名\tdemo_dwd.demo_t\n-- 数据规模\t130万\n-- 生命周期\t10天\nSET x=1;\nINSERT INTO t SELECT 1"
    assert header_facts([], sql) == {"lifecycle": "10天", "volume": "130万"}


def test_header_facts_read_the_published_header_and_stop_at_the_first_statement() -> None:
    assert header_facts(["生命周期 永久"], "SELECT 1\n-- 生命周期 10天") == {
        "lifecycle": "永久", "volume": None,
    }
    assert header_facts([], "-- 仅保留新核心\nSELECT 1") == {"lifecycle": None, "volume": None}
    assert header_facts([], None) == {"lifecycle": None, "volume": None}
