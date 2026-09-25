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

from scope_lineage.semantics import CHECKS, validate_document

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
