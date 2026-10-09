"""``semantic validate`` checks 10-13: what the document means, held to the packet's facts.

Checks 1-9 hold the document's *form* to the packet -- every column covered, every source
cited, every quote found. A page can pass all of them and still tell a reader the wrong
thing; these four catch the misreadings that happen most:

10. ``fan_out`` -- a JOIN that may multiply rows goes unmentioned;
11. ``derived_codes`` -- a CASE / IF output is missing from ``code_values``, or a
    success-like value gathers several source values without a warning;
12. ``documented_meaning`` -- a value the comments already explain is left 待确认, or a
    qualifier of the upstream (增值税, 测试 ...) is dropped;
13. ``header_facts`` -- the lifecycle or volume the script header states is not passed on.

Each fixture is the example document (or the demo packet) with one thing changed.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.semantics import CHECKS, validate_document
from scope_lineage.semantics.checks_meaning import check_fan_out
from scope_lineage.semantics.packet import build_packets

from .table_semantics_demo import demo_packets, example, packet_of


@pytest.fixture(scope="module")
def packets(tmp_path_factory) -> Path:
    return demo_packets(tmp_path_factory.mktemp("demo"))


@pytest.fixture
def packet(packets: Path) -> dict:
    return copy.deepcopy(packet_of(packets))


@pytest.fixture
def document(packets: Path) -> dict:
    return example(packets)


def _problems(report: dict, check: str, status: str = "fail") -> list[dict]:
    return [f for f in report["failures"] if f["check"] == check and f["status"] == status]


def _passes(report: dict, check: str) -> int:
    return report["checks"].get(check, {}).get("pass", 0)


def _column(document: dict, name: str) -> dict:
    return next(column for column in document["columns"] if column["column"] == name)


def test_the_meaning_checks_follow_the_first_nine() -> None:
    assert CHECKS[9:] == ("fan_out", "derived_codes", "documented_meaning", "header_facts")


def test_the_example_raises_nothing_under_the_meaning_checks(document: dict, packet: dict) -> None:
    report = validate_document(document, packet)
    assert report["failures"] == []


# 10 ------------------------------------------------------------------ fan out


@pytest.fixture
def borrower(packets: Path) -> dict:
    """Two joins, neither proven unique: a loan table on customer_id, a LEFT JOIN ``cr``."""
    return packet_of(packets, "demo_dwd.dwd_lending_borrower_df")


def test_a_join_that_may_multiply_rows_and_goes_unmentioned_fails(
    document: dict, borrower: dict
) -> None:
    problems = _problems(validate_document(document, borrower), "fan_out")
    assert {p["at"] for p in problems} == {"summary.row.note"}
    messages = "\n".join(p["message"] for p in problems)
    assert "demo_ods.ods_credit_limit_df" in messages
    assert "demo_dwd.dwd_lending_loan_df" in messages
    assert "kind 为 risk" in messages


def test_naming_each_join_by_table_or_alias_in_the_note_or_a_risk_passes(
    document: dict, borrower: dict
) -> None:
    document["summary"]["row"]["note"] = "每个客户可能有多笔贷款（dwd_lending_loan_df），关联后行数放大，再按客户号汇总。"
    document["summary"]["watch"].append(
        {"text": "额度表 cr 没有证明按客户号唯一，一个客户多条额度时 MAX 取最大值。", "kind": "risk"}
    )
    report = validate_document(document, borrower)
    assert _problems(report, "fan_out") == []
    assert _passes(report, "fan_out") == 2


def test_a_mention_in_a_watch_that_is_not_a_risk_does_not_count(
    document: dict, borrower: dict
) -> None:
    document["summary"]["row"]["note"] = "关联 dwd_lending_loan_df 会放大行数。"
    document["summary"]["watch"].append({"text": "额度来自 cr。", "kind": "other"})
    (problem,) = _problems(validate_document(document, borrower), "fan_out")
    assert "demo_ods.ods_credit_limit_df" in problem["message"]


def test_a_left_join_called_harmless_to_the_row_count_warns(
    document: dict, borrower: dict
) -> None:
    document["summary"]["row"]["note"] = "关联 dwd_lending_loan_df 会放大行数，再按客户号汇总。"
    document["summary"]["watch"].append(
        {"text": "左关联额度表 ods_credit_limit_df，不影响行数。", "kind": "risk"}
    )
    report = validate_document(document, borrower)
    assert _problems(report, "fan_out") == []
    (warning,) = _problems(report, "fan_out", "warn")
    assert warning["at"] == "summary.watch[1]"
    assert "LEFT JOIN" in warning["message"]


def _harmless_warnings(document: dict, packet: dict, sentence: str) -> list[dict]:
    document["summary"]["row"]["note"] = "关联 dwd_lending_loan_df 会放大行数，再按客户号汇总。"
    document["summary"]["watch"].append({"text": sentence, "kind": "risk"})
    return _problems(validate_document(document, packet), "fan_out", "warn")


@pytest.mark.parametrize("sentence", [
    "左关联额度表 cr 不保证不放大，cr 同客户多条时会重复",
    "左关联额度表 cr 并不保证不会放大行数",
    "左关联额度表 cr 不一定不放大",
    "左关联额度表 cr 未必不影响行数",
])
def test_a_negated_no_effect_phrase_is_not_a_claim_of_no_effect(
    document: dict, borrower: dict, sentence: str
) -> None:
    assert _harmless_warnings(document, borrower, sentence) == []


@pytest.mark.parametrize("sentence", [
    "左关联额度表 cr 保证不放大",
    "额度表 cr 左关联不影响行数",
    "左关联额度表 cr 不保证不放大，但行数不变",
])
def test_a_no_effect_phrase_without_a_negation_before_it_still_warns(
    document: dict, borrower: dict, sentence: str
) -> None:
    (warning,) = _harmless_warnings(document, borrower, sentence)
    assert warning["at"] == "summary.watch[1]"


def _with_safe_joins(borrower: dict, *aliases: str) -> dict:
    """The borrower packet plus a LEFT JOIN per alias, each proven unique (safe)."""
    packet = copy.deepcopy(borrower)
    limit = next(r for r in packet["lineage"]["rules"] if r.get("right_aliases") == ["cr"])
    for index, alias in enumerate(aliases):
        table = f"demo_ods.ods_branch_{index}_df"
        packet["lineage"]["rules"].append(
            {**limit, "id": f"p9{index}", "right": table, "right_tables": [table],
             "right_aliases": [alias], "fan_out": {"status": "safe", "reason": "去重后唯一"}}
        )
    return packet


@pytest.mark.parametrize("sentence", [
    "左关联网点表 br 已去重，不放大",
    "LEFT JOIN 网点表 ods_branch_0_df 不会导致行数放大",
    "左关联的网点表 br 与机构表 og 两路都已去重，不放大",
])
def test_a_sentence_naming_only_safe_joins_does_not_warn(
    document: dict, borrower: dict, sentence: str
) -> None:
    packet = _with_safe_joins(borrower, "br", "og")
    assert _harmless_warnings(document, packet, sentence) == []


@pytest.mark.parametrize("sentence", [
    "左关联网点表 br 与额度表 cr 不放大",
    "网点表 br 已去重，左关联都不放大",
    "网点表 br 已去重，所有左关联均不放大",
])
def test_a_safe_join_named_beside_an_unproven_one_or_a_universal_claim_still_warns(
    document: dict, borrower: dict, sentence: str
) -> None:
    packet = _with_safe_joins(borrower, "br")
    (warning,) = _harmless_warnings(document, packet, sentence)
    assert "ods_credit_limit_df" in warning["message"]


def test_a_safe_alias_shared_with_an_unproven_join_still_warns(
    document: dict, borrower: dict
) -> None:
    packet = _with_safe_joins(borrower, "l")
    (warning,) = _harmless_warnings(document, packet, "左关联网点表 l 已去重，不放大")
    assert "ods_credit_limit_df" in warning["message"]


def _mapping_and_catalog(borrower: dict) -> dict:
    """The unproven LEFT JOIN called 映射表 m, and a join proven unique called 目录表 n."""
    packet = _with_safe_joins(borrower, "n")
    limit = next(r for r in packet["lineage"]["rules"] if r.get("right_aliases") == ["cr"])
    limit["right_aliases"] = ["m"]
    return packet


@pytest.mark.parametrize("sentence", [
    "若映射表 m 按键唯一，左关联 m 不放大；否则同一订单会关联出多行",
    "只有映射表 m 按键唯一时，左关联 m 才不放大，不成立时会放大行数",
    "若映射表 m 按键唯一，左关联 m 不放大。若这个前提不成立，左关联会放大行数",
    "映射表 m 左关联不放大（注释推出，SQL 未证明）。若注释不成立，左关联会放大行数",
    "映射表 m 按键唯一成立时，左关联 m 不放大；不成立时右侧同一键可能有多条，会放大行数",
    "若映射表 m 按键唯一成立时不放大；不成立时会放大行数",
    "映射表 m 按键唯一成立时不放大，不成立时会放大行数",
    "映射表 m 按键唯一时，左关联 m 不放大；不唯一时会放大行数",
    "映射表 m 按键不重复时，左关联 m 不放大；重复时会放大行数",
    "映射表 m 按键不重复时不放大，重复时会放大行数",
])
def test_a_no_effect_claim_under_a_condition_with_its_opposite_case_does_not_warn(
    document: dict, borrower: dict, sentence: str
) -> None:
    """The warning asks when the right side has several rows; these sentences say it."""
    packet = _mapping_and_catalog(borrower)
    assert _harmless_warnings(document, packet, sentence) == []


@pytest.mark.parametrize("sentence", [
    "若映射表 m 按键唯一，左关联 m 不放大。",
    "映射表 m 左关联不放大。",
    "映射表 m 左关联不放大；否则会放大。",
    "映射表 m 左关联不放大；目录表 n 重复时会放大",
    "若映射表 m 按键唯一，左关联 m 不放大，目录表 n 重复时会放大",
    "目录表 n 已去重，左关联都不放大",
    "映射表 m 左关联保证不放大",
    "映射表 m 左关联不放大（注释推出，SQL 未证明）。",
    "映射表 m 按键唯一成立时，左关联 m 不放大；不成立时写入方的合并多行匹配，结果取决于引擎",
    "映射表 m 按键唯一成立时，左关联 m 不放大；不成立时也不会放大",
    "映射表 m 按键唯一成立时，左关联 m 不放大",
    "映射表 m 左关联不放大；不成立时目录表 n 会放大行数",
    "映射表 m 左关联不放大；不成立时不放大",
    "映射表 m 按键不重复时，左关联 m 不放大；重复时也不会放大",
    "映射表 m 按键唯一时，左关联 m 不放大",
    "映射表 m 左关联不放大；重复时目录表 n 会放大行数",
    "映射表 m 按键不唯一时左关联 m 不放大；唯一时会放大行数",
])
def test_a_condition_or_an_opposite_case_alone_or_about_another_join_still_warns(
    document: dict, borrower: dict, sentence: str
) -> None:
    packet = _mapping_and_catalog(borrower)
    (warning,) = _harmless_warnings(document, packet, sentence)
    assert "ods_credit_limit_df" in warning["message"]


def test_joins_onto_one_table_are_asked_about_once(document: dict, borrower: dict) -> None:
    again = copy.deepcopy(borrower)
    limit = next(r for r in again["lineage"]["rules"] if r.get("right_aliases") == ["cr"])
    again["lineage"]["rules"].append({**limit, "id": "p99", "right_aliases": ["cr2"]})
    problems = _problems(validate_document(document, again), "fan_out")
    assert len(problems) == 2
    (twice,) = [p for p in problems if "ods_credit_limit_df" in p["message"]]
    assert "p99" in twice["message"] and "cr2" in twice["message"]


def test_one_sentence_calling_every_left_join_harmless_warns_once(
    document: dict, borrower: dict
) -> None:
    document["summary"]["row"]["note"] = (
        "关联 dwd_lending_loan_df 与 cr 会放大行数；其余左关联不会增加行数。"
    )
    again = copy.deepcopy(borrower)
    limit = next(r for r in again["lineage"]["rules"] if r.get("right_aliases") == ["cr"])
    again["lineage"]["rules"].append(
        {**limit, "id": "p99", "right": "demo_ods.ods_other_df", "right_aliases": ["o"],
         "right_tables": ["demo_ods.ods_other_df"]}
    )
    report = validate_document(document, again)
    (warning,) = _problems(report, "fan_out", "warn")
    assert warning["at"] == "summary.row.note"


def test_a_join_proven_unique_asks_for_nothing(document: dict, packets: Path) -> None:
    loan = packet_of(packets, "demo_dwd.dwd_lending_loan_df")
    report = validate_document(document, loan)
    assert _problems(report, "fan_out") == [] and _problems(report, "fan_out", "warn") == []


def test_a_packet_without_fan_out_facts_is_not_held_to_them(
    document: dict, borrower: dict
) -> None:
    older = copy.deepcopy(borrower)
    for rule in older["lineage"]["rules"]:
        rule.pop("fan_out", None)
    assert "fan_out" not in validate_document(document, older)["checks"]


# A JOIN inside a SUM's argument, below the outer aggregate (``fan_out.path`` argument):
# it can count an amount twice but copies no output row. The second statement adds the
# same right table on the grain path.
UNDER_AGGREGATE = """INSERT OVERWRITE TABLE dw.t_g PARTITION (dt = '20260101')
SELECT o.id, coalesce(s.amt, 0) AS amt
FROM (SELECT id FROM ods.orders WHERE dt = '20260101') o
LEFT JOIN (
  SELECT a.id, sum(amt) AS amt
  FROM (SELECT id FROM ods.orders WHERE dt = '20260101') a
  LEFT JOIN (
    SELECT p.id, sum(CASE WHEN e.kind = 'X' THEN p.amt ELSE 0 END) AS amt
    FROM ods.pay p LEFT JOIN ods.pay_ext e ON p.id = e.id AND p.seq = e.seq
    GROUP BY p.id
  ) b ON a.id = b.id
  GROUP BY a.id
) s ON o.id = s.id"""
ON_THE_GRAIN = UNDER_AGGREGATE.replace(
    ") s ON o.id = s.id", ") s ON o.id = s.id LEFT JOIN ods.pay_ext g ON o.id = g.id")
# A LEFT JOIN on the grain path whose right side is not proven unique.
GRAIN_RISK = """INSERT OVERWRITE TABLE dw.t_m PARTITION (dt = '20260101')
SELECT o.id, 0 AS amt, r.v
FROM (SELECT id FROM ods.orders WHERE dt = '20260101') o
LEFT JOIN ods.ref r ON o.id = r.k"""
PATH_SCHEMA = {
    "ods.orders": ["id", "b_val", "dt"],
    "ods.pay": ["id", "seq", "amt"],
    "ods.pay_ext": ["id", "seq", "kind"],
    "ods.ref": ["k", "v", "t"],
    "dw.t_m": ["id", "amt", "v", "dt"],
    "dw.t_g": ["id", "amt", "dt"],
}


def _path_packet(sql: str) -> dict:
    lineage = to_lineage_dict(parse_scope_lineage(sql, "t0", schema=PATH_SCHEMA))
    (built,) = build_packets([(lineage, None)])
    return built


def _fan_out(packet: dict, note: str = "每个 id 一行。", *risks: str) -> list[tuple[str, str]]:
    document = {"summary": {"row": {"note": note},
                            "watch": [{"kind": "risk", "text": text} for text in risks]}}
    return [(item["status"], item["at"]) for item in check_fan_out(document, packet)
            if item["status"] != "pass"]


def _paths(packet: dict) -> list:
    return [(rule.get("right_tables"), rule["fan_out"].get("path")) for rule in packet["lineage"]["rules"]
            if rule["kind"] == "join" and rule.get("fan_out")
            and rule["fan_out"].get("status") != "safe"]


def test_a_join_under_an_aggregate_need_not_be_named() -> None:
    packet = _path_packet(UNDER_AGGREGATE)
    assert _paths(packet) == [(["ods.pay_ext"], "argument")]
    assert _fan_out(packet) == []


def test_a_join_under_an_aggregate_may_be_called_harmless_to_the_row_count() -> None:
    assert _fan_out(_path_packet(UNDER_AGGREGATE), "每个 id 一行。", "左关联 pay_ext 不放大。") == []


def test_a_grain_path_join_must_still_be_named_and_not_called_harmless() -> None:
    packet = _path_packet(GRAIN_RISK)
    assert _paths(packet) == [(["ods.ref"], "grain")]
    assert _fan_out(packet) == [("fail", "summary.row.note")]
    assert _fan_out(packet, "每个 id 一行。", "左关联 ref 不放大。") == [("warn", "summary.watch[0]")]


def test_a_packet_without_paths_holds_every_join_as_before() -> None:
    packet = _path_packet(UNDER_AGGREGATE)
    for rule in packet["lineage"]["rules"]:
        (rule.get("fan_out") or {}).pop("path", None)
    assert _fan_out(packet) == [("fail", "summary.row.note")]
    assert _fan_out(packet, "每个 id 一行。", "左关联 pay_ext 不放大。") == [("warn", "summary.watch[0]")]


def test_a_table_joined_on_both_paths_is_still_held_on_the_grain_path() -> None:
    packet = _path_packet(ON_THE_GRAIN)
    assert sorted(path for _, path in _paths(packet)) == ["argument", "grain"]
    assert _fan_out(packet) == [("fail", "summary.row.note")]
    assert _fan_out(packet, "每个 id 一行。", "左关联 pay_ext 不放大。") == [("warn", "summary.watch[0]")]


# An alias is unique within one SELECT, not within a packet: every UNION branch and
# subquery may call its right side ``c``. A sentence naming ``c`` may be about any join
# that alias stands for, so only a table name, an alias no other right side uses, or the
# join's rule number (pN) names a join for sure; a shared alias alone warns.


def _join(rule_id: str, table: str, alias: str, status: str = "risk") -> dict:
    return {"id": rule_id, "kind": "join", "join_type": "LEFT_OUTER",
            "expression": f"a.k = {alias}.k", "task": "t0", "right": f"subq:{alias}",
            "right_tables": [table], "right_aliases": [alias],
            "fan_out": {"status": status, "reason": "未证明唯一", "path": "grain"}}


def _joins(*rules: dict) -> dict:
    return {"lineage": {"rules": list(rules)}}


AGENT, GROUP, NOTE = "demo_ods.ods_probe_agent_df", "demo_dim.dim_probe_group_dc", "demo_ods.ods_probe_note_df"
SHARED_C = _joins(_join("p1", AGENT, "c"), _join("p2", GROUP, "c"), _join("p3", NOTE, "d"))


def _verdicts(packet: dict, note: str, *risks: str) -> list[dict]:
    document = {"summary": {"row": {"note": note},
                            "watch": [{"kind": "risk", "text": text} for text in risks]}}
    return [item for item in check_fan_out(document, packet) if item["status"] != "pass"]


def test_a_join_named_only_by_an_alias_another_join_shares_warns() -> None:
    (warning,) = _verdicts(SHARED_C, "每个 id 一行。", "坐席分支 c（坐席子查询，p1）与 d 都未证明唯一，会放大行数。")
    assert (warning["status"], warning["at"]) == ("warn", "summary.watch[0]")
    assert warning["message"].startswith(
        f"关联 {GROUP}（p2）只被别名 c 点到，而 c 也是 p1 的右侧；这句可能在说 p1，"
        f"{GROUP} 可能没写——用表名或 pN 点名 {GROUP}")


@pytest.mark.parametrize("name", ["dim_probe_group_dc", GROUP, "p2"])
def test_a_table_name_or_the_rule_number_names_a_join_for_sure(name: str) -> None:
    assert _verdicts(SHARED_C, f"c（p1）、{name} 与 d 都未证明唯一，会放大行数。") == []


def test_a_rule_number_names_no_join_whose_number_it_merely_starts() -> None:
    packet = _joins(_join("p2", GROUP, "c"), _join("p23", AGENT, "c"))
    (warning,) = _verdicts(packet, "c（p23）未证明唯一，会放大行数。")
    assert warning["status"] == "warn" and f"{GROUP}（p2）" in warning["message"]


def test_one_table_joined_twice_under_one_alias_shares_it_with_no_other_join() -> None:
    packet = _joins(_join("p1", AGENT, "c"), _join("p4", AGENT, "c"), _join("p3", NOTE, "d"))
    assert _verdicts(packet, "c 与 d 都未证明唯一，会放大行数。") == []


def test_a_join_named_nowhere_still_fails_with_the_same_message() -> None:
    (problem,) = _verdicts(_joins(_join("p3", NOTE, "d")), "每个 id 一行。")
    assert problem == {
        "check": "fan_out", "status": "fail", "at": "summary.row.note",
        "message": f"关联 {NOTE}（LEFT_OUTER，ON a.k = d.k，t0，材料包 p3）的右侧没有被证明按关联键唯一"
                   "（未证明唯一），一条记录可能匹配多条、让行数放大；在 summary.row.note 或一条 kind 为 "
                   f"risk 的 summary.watch 里点名它（{NOTE}、ods_probe_note_df、d 任一），写明会不会放大行数、为什么",
    }


def test_a_harmless_claim_about_one_join_does_not_label_the_join_sharing_its_alias() -> None:
    named = f"c（p1）、{GROUP}、d 都未证明唯一，会放大行数。"
    (warning,) = _verdicts(SHARED_C, named, "c（p1）不放大。")
    assert warning["at"] == "summary.watch[0]"
    assert AGENT in warning["message"] and GROUP not in warning["message"]
    (warning,) = _verdicts(SHARED_C, named, "c 不放大。")
    assert AGENT in warning["message"] and GROUP in warning["message"]


# 11 ------------------------------------------------------------------ derived codes


def _verify_status_case(packet: dict, *outputs: dict) -> dict:
    column = next(c for c in packet["lineage"]["columns"] if c["column"] == "verify_status")
    column["producers"][0]["case_outputs"] = list(outputs) or [
        {"value": "1", "when": ["`verify_flag` IN (1, 2)"], "source_values": ["1", "2"],
         "catch_all": False},
        {"value": "0", "when": ["ELSE"], "source_values": [], "catch_all": True},
    ]
    return packet


def test_every_literal_a_case_returns_is_listed_as_a_code_value(
    document: dict, packet: dict
) -> None:
    report = validate_document(document, _verify_status_case(packet))
    assert _problems(report, "derived_codes") == []
    assert _passes(report, "derived_codes") == 2


def test_a_case_output_missing_from_code_values_fails(document: dict, packet: dict) -> None:
    _verify_status_case(packet)
    _column(document, "verify_status")["code_values"].pop()
    (problem,) = _problems(validate_document(document, packet), "derived_codes")
    assert problem["at"] == "columns[4].code_values"
    assert "'0'" in problem["message"] and "其余值" in problem["message"]


def test_a_case_column_with_no_code_values_fails_once_per_value(
    document: dict, packet: dict
) -> None:
    _verify_status_case(packet)
    del _column(document, "verify_status")["code_values"]
    problems = _problems(validate_document(document, packet), "derived_codes")
    assert len(problems) == 2


def test_a_success_like_value_gathering_several_source_values_asks_for_a_watch(
    document: dict, packet: dict
) -> None:
    _verify_status_case(packet)
    _column(document, "verify_status")["code_values"][0]["meaning"] = "实名有效"
    report = validate_document(document, packet)
    (warning,) = _problems(report, "derived_codes", "warn")
    assert warning["at"] == "columns[4].watch"
    assert "实名有效" in warning["message"]


def test_the_watch_on_the_column_or_in_the_summary_satisfies_it(
    document: dict, packet: dict
) -> None:
    _verify_status_case(packet)
    column = _column(document, "verify_status")
    column["code_values"][0]["meaning"] = "实名有效"
    column["watch"] = "来源值 1、2 都算作实名有效。"
    assert _problems(validate_document(document, packet), "derived_codes", "warn") == []
    del column["watch"]
    document["summary"]["watch"].append(
        {"text": "来源值 1、2 都算作实名有效。", "kind": "risk", "refs": ["column:verify_status"]}
    )
    assert _problems(validate_document(document, packet), "derived_codes", "warn") == []


def test_a_meaning_that_negates_success_or_mentions_it_aside_is_not_success_like(
    document: dict, packet: dict
) -> None:
    _verify_status_case(packet)
    codes = _column(document, "verify_status")["code_values"]
    codes[0]["meaning"] = "没有成功实名"
    codes[1]["meaning"] = "未实名（有效期外）"
    assert _problems(validate_document(document, packet), "derived_codes", "warn") == []


def test_a_value_two_producers_return_is_one_item_with_each_branch_once(
    document: dict, packet: dict
) -> None:
    _verify_status_case(packet)
    column = next(c for c in packet["lineage"]["columns"] if c["column"] == "verify_status")
    column["producers"].append(copy.deepcopy(column["producers"][0]))
    _column(document, "verify_status")["code_values"].pop()
    (problem,) = _problems(validate_document(document, packet), "derived_codes")
    assert problem["message"].count("其余值") == 1


def test_a_literal_beside_a_computed_else_is_not_asked_for(document: dict, packet: dict) -> None:
    # A stamp the CASE writes when a row is new, beside an ELSE that keeps another
    # column's value: published as information, but not a code of the column.
    _verify_status_case(packet, {
        "value": "20000101", "when": ["`a`.`k` IS NULL"], "source_values": None,
        "catch_all": False, "else": "computed",
    })
    report = validate_document(document, packet)
    assert _problems(report, "derived_codes") == []
    assert _passes(report, "derived_codes") == 0


def test_a_literal_beside_an_else_passing_the_source_on_is_still_asked_for(
    document: dict, packet: dict
) -> None:
    _verify_status_case(packet, {
        "value": "U", "when": ["`verify_flag` = 9"], "source_values": ["9"],
        "catch_all": False, "else": "source",
    })
    (problem,) = _problems(validate_document(document, packet), "derived_codes")
    assert problem["at"] == "columns[4].code_values" and "'U'" in problem["message"]


def test_a_success_like_value_from_one_source_value_needs_no_watch(
    document: dict, packet: dict
) -> None:
    _verify_status_case(packet, {"value": "1", "when": ["`verify_flag` = 1"],
                                 "source_values": ["1"], "catch_all": False})
    _column(document, "verify_status")["code_values"][0]["meaning"] = "实名有效"
    assert _problems(validate_document(document, packet), "derived_codes", "warn") == []


# 12 ------------------------------------------------------------------ documented meaning


def _source_column(packet: dict, name: str) -> dict:
    return next(c for c in packet["inputs"][0]["columns"] if c["name"] == name)


def test_a_value_the_comment_explains_cannot_be_left_unconfirmed(
    document: dict, packet: dict
) -> None:
    _source_column(packet, "verify_flag")["comment"] = "实名标志 0-未实名 1-已实名"
    code = _column(document, "verify_status")["code_values"][1]
    code.update(meaning="待确认", unconfirmed=True)
    (problem,) = _problems(validate_document(document, packet), "documented_meaning")
    assert problem["at"] == "columns[4].code_values[1]"
    assert "「实名标志 0-未实名 1-已实名」" in problem["message"]
    assert "未实名" in problem["message"]


def test_an_unconfirmed_value_no_comment_explains_passes(document: dict, packet: dict) -> None:
    code = _column(document, "verify_status")["code_values"][1]
    code.update(meaning="待确认", unconfirmed=True)
    report = validate_document(document, packet)
    assert _problems(report, "documented_meaning") == []
    assert _passes(report, "documented_meaning") == 1


def test_a_value_whose_documented_meaning_is_pending_may_say_so(
    document: dict, packet: dict
) -> None:
    _source_column(packet, "verify_flag")["comment"] = "处理状态 0:待确认 1:已确认"
    _column(document, "verify_status")["code_values"][1]["meaning"] = "待确认"
    assert _problems(validate_document(document, packet), "documented_meaning") == []


@pytest.mark.parametrize("meaning", [
    "已实名（是否含历史补录待确认）",
    "已实名，历史补录是否计入待确认",
])
def test_a_meaning_that_only_mentions_something_else_pending_is_not_pending(
    document: dict, packet: dict, meaning: str
) -> None:
    _source_column(packet, "verify_flag")["comment"] = "实名标志 0-未实名 1-已实名"
    _column(document, "verify_status")["code_values"][0]["meaning"] = meaning
    assert _problems(validate_document(document, packet), "documented_meaning") == []


@pytest.mark.parametrize("meaning", ["待确认", "待确认（猜测：已实名）", "「待确认」"])
def test_a_meaning_that_starts_pending_is_pending_without_the_flag(
    document: dict, packet: dict, meaning: str
) -> None:
    _source_column(packet, "verify_flag")["comment"] = "实名标志 0-未实名 1-已实名"
    _column(document, "verify_status")["code_values"][0]["meaning"] = meaning
    (problem,) = _problems(validate_document(document, packet), "documented_meaning")
    assert problem["at"] == "columns[4].code_values[0]"
    assert "（1 = 已实名）" in problem["message"]


def test_a_listed_label_the_sql_compares_with_is_its_own_meaning(
    document: dict, packet: dict
) -> None:
    _source_column(packet, "gender")["comment"] = "性别：男、女、未知"
    packet["tasks"][0]["sql"] += "\n-- gender IN ('男', '女')"
    _column(document, "gender_cd")["code_values"].append(
        {"value": "男", "meaning": "含义待确认", "sources": ["sql"], "unconfirmed": True}
    )
    (problem,) = _problems(validate_document(document, packet), "documented_meaning")
    assert "「性别：男、女、未知」" in problem["message"]


def test_a_qualifier_of_the_main_upstream_must_reach_the_summary(
    document: dict, packet: dict
) -> None:
    packet["inputs"][0]["comment"] = "核心系统客户注册表（含测试客户）"
    (warning,) = _problems(validate_document(document, packet), "documented_meaning", "warn")
    assert warning["at"] == "summary.what"
    assert "「测试」" in warning["message"]
    document["summary"]["what"] += "含测试客户。"
    assert _problems(validate_document(document, packet), "documented_meaning", "warn") == []


def test_a_qualifier_of_a_source_column_must_reach_that_column(
    document: dict, packet: dict
) -> None:
    _source_column(packet, "register_ts")["comment"] = "冲正后的注册时间戳"
    (warning,) = _problems(validate_document(document, packet), "documented_meaning", "warn")
    assert warning["at"] == "columns[3]"
    _column(document, "register_time")["derivation"] += "取冲正后的时间。"
    assert _problems(validate_document(document, packet), "documented_meaning", "warn") == []


def _shout_inputs(packet: dict) -> None:
    """Spell the input metadata the way an upper-case schema export has it."""
    for item in packet["inputs"]:
        item["table"] = item["table"].upper()
        for column in item["columns"]:
            column["name"] = column["name"].upper()


def test_an_upper_case_source_comment_still_explains_a_value(
    document: dict, packet: dict
) -> None:
    _source_column(packet, "verify_flag")["comment"] = "实名标志 0-未实名 1-已实名"
    _shout_inputs(packet)
    code = _column(document, "verify_status")["code_values"][1]
    code.update(meaning="待确认", unconfirmed=True)
    (problem,) = _problems(validate_document(document, packet), "documented_meaning")
    assert problem["at"] == "columns[4].code_values[1]"


def test_a_qualifier_of_an_upper_case_source_column_must_reach_that_column(
    document: dict, packet: dict
) -> None:
    _source_column(packet, "register_ts")["comment"] = "冲正后的注册时间戳"
    _shout_inputs(packet)
    (warning,) = _problems(validate_document(document, packet), "documented_meaning", "warn")
    assert warning["at"] == "columns[3]"


def test_a_value_confirmed_on_an_upper_case_source_column_needs_no_text(
    document: dict, packet: dict
) -> None:
    _source_column(packet, "gender")["confirmed_values"] = [{"value": "X", "meaning": "Other"}]
    _shout_inputs(packet)
    _column(document, "gender_cd")["code_values"].append(
        {"value": "X", "meaning": "Other", "sources": ["confirmed"]})
    assert _problems(validate_document(document, packet), "code_values") == []


def test_one_qualifier_over_several_columns_is_one_warning_naming_them(
    document: dict, packet: dict
) -> None:
    _source_column(packet, "cust_no")["comment"] = "冲正后的客户号"
    _source_column(packet, "verified_no")["comment"] = "冲正后的实名客户号"
    (warning,) = _problems(validate_document(document, packet), "documented_meaning", "warn")
    assert warning["at"] == "columns[0]"
    assert "customer_id" in warning["message"] and "verified_customer_no" in warning["message"]
    _column(document, "verified_customer_no")["meaning"] += "（冲正后）"
    report = validate_document(document, packet)
    assert _problems(report, "documented_meaning", "warn") == []


def test_a_qualifier_the_target_already_states_and_a_shorter_term_inside_a_longer_one_are_quiet(
    document: dict, packet: dict
) -> None:
    packet["inputs"][0]["comment"] = "客户注册表（增值税发票客户）"
    report = validate_document(document, packet)
    (warning,) = _problems(report, "documented_meaning", "warn")
    assert "「增值税」" in warning["message"]
    packet["target"]["comment"] += "（增值税发票客户）"
    assert _problems(validate_document(document, packet), "documented_meaning", "warn") == []


# 13 ------------------------------------------------------------------ header facts


def _header(packet: dict, lifecycle=None, volume=None) -> dict:
    packet["tasks"][0]["header_facts"] = {"lifecycle": lifecycle, "volume": volume}
    return packet


def test_a_lifecycle_the_header_states_must_reach_how_to_read(
    document: dict, packet: dict
) -> None:
    (warning,) = _problems(
        validate_document(document, _header(packet, "10天")), "header_facts", "warn"
    )
    assert warning["at"] == "summary.refresh.how_to_read"
    assert "10天" in warning["message"]


def test_how_to_read_or_a_watch_naming_the_lifecycle_passes(document: dict, packet: dict) -> None:
    _header(packet, "10天", "130万")
    document["summary"]["refresh"]["how_to_read"] += "分区只保留最近 10 天。"
    document["summary"]["watch"].append({"text": "每天约 130万 行。", "kind": "other"})
    report = validate_document(document, packet)
    assert _problems(report, "header_facts", "warn") == []
    assert _passes(report, "header_facts") == 2


def test_a_permanent_lifecycle_and_a_volume_are_asked_for_too(document: dict, packet: dict) -> None:
    warnings = _problems(
        validate_document(document, _header(packet, "永久", "130万")), "header_facts", "warn"
    )
    assert [("永久" in w["message"], "130万" in w["message"]) for w in warnings] == [
        (True, False), (False, True),
    ]


# ------------------------------------------------------------------ the report


def test_the_text_report_numbers_the_meaning_checks_for_the_rewrite_prompt(
    document: dict, borrower: dict
) -> None:
    from scope_lineage.semantics import render_validation_text, validation_report
    from scope_lineage.semantics.validate import check_file

    report = validation_report([check_file(document, borrower, "doc.json")])
    assert "  FAIL [10 fan_out] summary.row.note: 关联 demo_ods.ods_credit_limit_df" in (
        render_validation_text(report)
    )
