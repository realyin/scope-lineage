"""Check 14 ``placeholder``: a document's prose holding a placeholder nothing filled in.

A writer's own script can leave ``%s`` or ``{name}`` in a sentence. The check only finds
it -- the writer's script is where it comes from. It reads every free-text field a reader
sees (the summary's sentences, ``steps``, the rules' text, the columns' explanations), not
SQL quotes or derivations, and skips what is quoted as code or as a value: backticks and
quotes, ``${param}``, a set written after ``∈`` / ``in`` / ``属于``. A WARN, not a FAIL,
since prose may legitimately hold these characters. A clean document gets one ``pass``.
"""

from __future__ import annotations

import pytest

from scope_lineage.semantics import CHECKS, validate_document
from scope_lineage.semantics.checks_text import check_placeholder

from .table_semantics_demo import demo_packets, example, packet_of


@pytest.fixture(scope="module")
def packets(tmp_path_factory):
    return demo_packets(tmp_path_factory.mktemp("demo"))


@pytest.fixture(scope="module")
def packet(packets) -> dict:
    return packet_of(packets)


@pytest.fixture
def document(packets) -> dict:
    return example(packets)


def _warned(document: dict) -> list[tuple[str, str]]:
    found = check_placeholder(document, {})
    assert all(item["check"] == "placeholder" for item in found)
    return [(item["at"], item["message"]) for item in found if item["status"] == "warn"]


def test_it_is_check_fourteen() -> None:
    assert CHECKS[13] == "placeholder" and len(CHECKS) == 14


def test_a_clean_document_gets_one_pass(document: dict, packet: dict) -> None:
    assert check_placeholder(document, packet) == [
        {"check": "placeholder", "status": "pass", "at": "document", "message": ""}
    ]
    report = validate_document(document, packet)
    assert report["checks"]["placeholder"] == {"pass": 1, "warn": 0, "fail": 0}
    assert report["failures"] == []


@pytest.mark.parametrize("text", ["当天 %s 的数据", "共 %d 行", "截至 %(day)s", "取 {day} 分区",
                                  "空的 {} 没填", "转义写成 {{ 留着"])
def test_a_placeholder_in_a_summary_sentence_is_warned(document: dict, text: str) -> None:
    document["summary"]["row"]["note"] = text
    (warned,) = _warned(document)
    assert warned[0] == "summary.row.note"
    assert "占位符" in warned[1]


def test_each_placeholder_is_one_warning(document: dict) -> None:
    document["summary"]["row"]["note"] = "按 %s 取，再按 %s 汇总"
    document["summary"]["watch"].append({"kind": "risk", "text": "%s 之前 %s 之后", "refs": []})
    watch = f"summary.watch[{len(document['summary']['watch']) - 1}].text"
    assert [where for where, _ in _warned(document)] == [
        "summary.row.note", "summary.row.note", watch, watch,
    ]


def test_a_document_with_a_placeholder_gets_no_pass_line(document: dict, packet: dict) -> None:
    document["summary"]["row"]["note"] = "当天 %s 的数据"
    report = validate_document(document, packet)
    assert report["checks"]["placeholder"] == {"pass": 0, "warn": 1, "fail": 0}
    (problem,) = [f for f in report["failures"] if f["check"] == "placeholder"]
    assert problem["number"] == 14


FIELDS = {
    "summary.what": lambda d, v: d["summary"].__setitem__("what", v),
    "summary.refresh.how_to_read": lambda d, v: d["summary"]["refresh"].__setitem__("how_to_read", v),
    "steps[0]": lambda d, v: d.__setitem__("steps", [v]),
    "rules[0].text": lambda d, v: d["rules"][0].__setitem__("text", v),
    "columns[0].meaning": lambda d, v: d["columns"][0].__setitem__("meaning", v),
    "columns[0].null_meaning": lambda d, v: d["columns"][0].__setitem__("null_meaning", v),
    "columns[0].watch": lambda d, v: d["columns"][0].__setitem__("watch", v),
    "columns[0].unit": lambda d, v: d["columns"][0].__setitem__("unit", v),
}


@pytest.mark.parametrize("at", sorted(FIELDS))
def test_every_listed_field_is_read(document: dict, at: str) -> None:
    FIELDS[at](document, "按 {day} 取")
    (warned,) = _warned(document)
    assert warned[0] == at


def test_branches_scope_and_questions_are_read(document: dict) -> None:
    document["columns"][0]["branches"] = [{"branch": "来源 {src}", "text": "取 %s"}]
    document["summary"]["scope"].append({"text": "只留 %d 行", "rule_refs": [], "sources": ["sql"]})
    document["summary"]["questions"] = [{"id": "q1", "text": "{who} 负责？", "status": "open"}]
    at = {where for where, _ in _warned(document)}
    assert {"columns[0].branches[0].branch", "columns[0].branches[0].text",
            f"summary.scope[{len(document['summary']['scope']) - 1}].text",
            "summary.questions[0].text"} <= at


# --------------------------------------------------------- what is not a placeholder


@pytest.mark.parametrize("text", [
    "状态 ∈ {A, B, C}",          # a set of several members
    "状态 ∈ {A}",                # a set of one member, after ∈
    "状态 in {A}",
    "状态属于 {A}",
    "用 `format_string('%s', x)` 拼出",
    "写成 '%s' 的格式",
    "缺省为 '{}'",
    "分区取 ${dt}",
    "按 `{day}` 引用",
    "增长 50%，按 %比 计",
])
def test_quoted_code_sets_and_parameters_are_not_placeholders(document: dict, text: str) -> None:
    document["summary"]["row"]["note"] = text
    assert _warned(document) == []


def test_sql_quotes_and_derivations_are_not_read(document: dict) -> None:
    document["rules"][0]["sql"] = "x LIKE '%s%' AND y = '{}'"
    document["columns"][0]["derivation"] = "format('%s', {name})"
    assert _warned(document) == []
