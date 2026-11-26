"""The guard, statements and SQL roles after the real-model rerun: shapes the model actually
wrote (roles with ；in their notes, quotes and scopes with 「」, replies to a guard question)."""

from __future__ import annotations

import pytest
from service_paths import CUSTOMER
from test_ask_memory import SQL1, SQL2, SQL_ALT, _with_statement, answer, apply, block

from scope_lineage_service.ask import memory


@pytest.mark.parametrize("line, expected", [
    ("段1=当前版（改了 A；加了 B）；段2=备选（x；y）",
     [(1, "当前版", "改了 A；加了 B"), (2, "备选", "x；y")]),
    ("段1=当前版（相比 v4：is_deleted 的占位换成确定条件 is_deleted = 'N'（提问者第 5 轮），其余不变）",
     [(1, "当前版", "相比 v4：is_deleted 的占位换成确定条件 is_deleted = 'N'（提问者第 5 轮），其余不变")]),
    ("段1=当前版（新建；分区示例值 20261119 → 20261125）",
     [(1, "当前版", "新建；分区示例值 20261119 → 20261125")]),
    ("段1=原文（#1 v1，第 1 轮首版原样复现，未改；非本话题当前口径）",
     [(1, "原文", "#1 v1，第 1 轮首版原样复现，未改；非本话题当前口径")]),
    ("段1:当前版(按月); 段2 = 诊断", [(1, "当前版", "按月"), (2, "诊断", "")]),
    ("段1=当前版（首版", [(1, "当前版", "首版")]),
])
def test_sql_roles_split_at_each_segment_not_at_every_semicolon(line, expected) -> None:
    problems: list = []
    roles = memory.parse_roles(line, problems)
    assert problems == [] and [(r["segment"], r["role"], r["note"]) for r in roles] == expected


def test_a_semicolon_in_the_role_note_no_longer_loses_the_version() -> None:
    first = apply(memory.new_state(), 1, "客户数", answer(block("新：客户数", "SQL角色：段1=当前版"), SQL1))
    out = apply(first["state"], 2, "按性别分", answer(block(
        "#1", "SQL角色：段1=当前版（改了分组；加了排序）；段2=诊断（看重复；只读）"), SQL2, SQL_ALT))
    assert out["block_status"] == "ok" and out["version"] == 2 and out["sql"] == SQL2


def test_topic_line_variants_and_soft_problems() -> None:
    first = apply(memory.new_state(), 1, "客户数", answer(block("新：客户数", "SQL角色：段1=当前版"), SQL1))
    new = apply(first["state"], 2, "x", answer(block("新 #3 账期内金额", "SQL角色：无")))
    assert new["block_status"] == "ok" and new["topic"] == 2 and new["topic_name"] == "账期内金额"
    no_topic = apply(first["state"], 2, "x", answer("问题：x\n结论：y\nSQL角色：段1=当前版", SQL2))
    assert no_topic["block_status"] == "ok" and no_topic["topic"] == 1 and no_topic["version"] == 2
    shown_old = apply(first["state"], 2, "把第一版给我看", answer(block("#1", "SQL角色：无"), SQL1))
    assert shown_old["block_status"] == "ok" and not shown_old["sql_missing"]
    assert shown_old["new_version"] is None


def test_a_statement_quote_and_scope_may_hold_corner_brackets_and_an_expression() -> None:
    parsed = memory._statement("第 8 轮「那就先假设只看「甲」那一类预算」— 范围：后续问「甲」的题（含 #1）；"
                               f"表 {CUSTOMER}；SQL：budget_type = 'A'")
    assert parsed["quote"] == "那就先假设只看「甲」那一类预算" and parsed["topic"] == 1
    assert parsed["tables"] == [CUSTOMER] and parsed["expr"] == "budget_type = 'A'"


def test_a_question_is_not_a_statement() -> None:
    out = apply(memory.new_state(), 1, "今年各部门收入多少？", answer(block(
        "新：收入", "SQL角色：段1=当前版", "说法：第 1 轮「今年各部门收入多少？」— 范围：#1"), SQL1))
    assert out["state"]["statements"] == [] and any("是一个问题" in p for p in out["problems"])


def _missed(state, turn, messages, *extra):
    """A turn in topic #1 with a new current SQL whose 条件 cite no asker turn."""
    return apply(state, turn, messages[turn], answer(
        block("#1", "SQL角色：段1=当前版", "条件：c.dt — 本体", *extra), SQL_ALT + f" -- {turn}"), messages)


def test_the_guard_asks_once_and_the_card_says_it_asked() -> None:
    state, messages = _with_statement()
    messages.update({3: "按月分", 4: "再按部门分", 5: "再按年分"})
    third = _missed(state, 3, messages)
    assert len(third["guard"]) == 1
    assert "上一轮提醒过：第 2 轮「只算有效客户」是否加上" in memory.render_card(third["state"], turn=4)
    fourth = _missed(third["state"], 4, messages)
    fifth = _missed(fourth["state"], 5, messages)
    assert fourth["guard"] == [] and fifth["guard"] == []
    assert "上一轮提醒过" not in memory.render_card(fourth["state"], turn=5)


def test_a_reply_to_the_guard_is_not_a_statement() -> None:
    state, messages = _with_statement()
    messages.update({3: "按月分", 4: "要，按你说的加上"})
    third = _missed(state, 3, messages)
    reply = apply(third["state"], 4, messages[4], answer(block(
        "#1", "SQL角色：段1=当前版", "条件：c.status = 'A' — 提问者第 2 轮",
        "说法：第 4 轮「要，按你说的加上」— 范围：#1", "提醒答复：第 2 轮 加上"), SQL2, prose="按你说的加上了。"),
        messages)
    assert [s["turn"] for s in reply["state"]["statements"]] == [2] and reply["guard"] == []


def test_no_marks_the_statement_not_applicable_in_that_topic() -> None:
    state, messages = _with_statement()
    messages.update({3: "按月分", 4: "不用加", 5: "再按年分"})
    third = _missed(state, 3, messages)
    fourth = _missed(third["state"], 4, messages, "提醒答复：第 2 轮 不加")
    assert fourth["state"]["statements"][0]["not_applicable"] == [1]
    assert "不适用于 #1" in memory.render_card(fourth["state"], turn=5)
    assert _missed(fourth["state"], 5, messages)["guard"] == []


def test_yes_without_the_rule_in_the_sql_reminds_once_more() -> None:
    state, messages = _with_statement()
    messages.update({3: "按月分", 4: "加上", 5: "再按年分"})
    third = _missed(state, 3, messages)
    fourth = _missed(third["state"], 4, messages, "提醒答复：第 2 轮 加上")
    assert fourth["guard"] == ["你要加上第 2 轮说的「只算有效客户」，但这一版还没有沿用它。"]
    assert _missed(fourth["state"], 5, messages)["guard"] == []


def test_a_statement_is_kept_by_a_join_or_table_citation_or_its_expression() -> None:
    state, messages = _with_statement()
    messages[3] = "按月分"
    by_table = _missed(state, 3, messages, f"表：{CUSTOMER} — 一行是一个客户；只取有效（提问者第 2 轮）")
    by_join = _missed(state, 3, messages, "关联：a.id = b.id — 提问者第 2 轮；放大：无")
    assert by_table["guard"] == [] and by_join["guard"] == []
    state["statements"][0]["expr"] = "C.DT = '2024-01-31'"
    assert _missed(state, 3, messages)["guard"] == []  # the SQL holds c.dt = '2024-01-31'


def test_pending_statements_never_guard_and_never_hit_the_budget() -> None:
    first = apply(memory.new_state(), 1, "客户数", answer(block("新：客户数", "SQL角色：段1=当前版"), SQL1))
    long_message = "纠正一下" + "口径" * 900
    pending = apply(first["state"], 2, long_message, answer(block("#1", "SQL角色：段1=当前版"), SQL2,
                                                            prose="按你说的改了。"), {1: "客户数"})
    assert pending["state"]["statements"][0]["pending"] and pending["statements_over"] is None
    third = apply(pending["state"], 3, "按月分", answer(block("#1", "SQL角色：段1=当前版"), SQL_ALT),
                  {1: "客户数", 2: long_message})
    assert third["guard"] == []
