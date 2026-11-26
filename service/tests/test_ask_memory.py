"""The ask panel's conversation memory: today's date, the increment block, the state card, the
guard, the budget, the store and ``recall`` -- with scripted models, no SDK, no network."""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timedelta, timezone

import pytest
from service_paths import CUSTOMER, LOAN

from scope_lineage_service.ask import memory
from scope_lineage_service.ask.service import AskError, AskService
from scope_lineage_service.ask.store import MAX_TURNS, SCHEMA, Store
from scope_lineage_service.ask.trace import Tracer
from scope_lineage_service.ask.tools import ToolBox
from scope_lineage_service.state import CatalogState

SQL1 = f"SELECT COUNT(*) AS cnt FROM {CUSTOMER} c WHERE c.dt = '2024-01-31'"
SQL2 = f"SELECT c.gender_cd, COUNT(*) AS cnt FROM {CUSTOMER} c WHERE c.dt = '2024-01-31' GROUP BY c.gender_cd"
SQL_ALT = f"SELECT COUNT(DISTINCT c.customer_id) AS cnt FROM {CUSTOMER} c WHERE c.dt = '2024-01-31'"
LOAN_SQL = f"SELECT COUNT(*) AS cnt FROM {LOAN} l WHERE l.dt = '2024-01-31'"
TZ = timezone(timedelta(hours=8))


def block(topic, *lines, question="q"):
    return "\n".join([f"话题：{topic}", f"问题：{question}", "结论：见 SQL", *lines])


def answer(block_text, *sqls, prose="答案如下。"):
    parts = [prose, ""]
    for sql in sqls:
        parts += ["```sql", sql, "```", ""]
    if block_text is not None:
        parts += ["```text", block_text, "```"]
    return "\n".join(parts)


def no_check(sql):
    return {"tables": [{"table": CUSTOMER}] if CUSTOMER in sql else [{"table": LOAN}],
            "findings": [], "placeholders": []}, None


def apply(state, turn, question, text, messages=None):
    messages = dict(messages or {})
    messages[turn] = question
    return memory.apply_turn(state, turn=turn, question=question, answer=text,
                             segments=memory.sql_segments(text), user_messages=messages,
                             check=no_check, catalog="sha256:abc")


# ---------------------------------------------------------------------- today and the block


def test_today_line_is_the_date_and_the_offset() -> None:
    assert memory.today_line(datetime(2026, 11, 25, 23, 59, tzinfo=TZ)) == "今天：2026-11-25（时区 +08:00）"
    west = timezone(timedelta(hours=-5, minutes=-30))
    assert memory.today_line(datetime(2026, 1, 2, tzinfo=west)) == "今天：2026-01-02（时区 -05:30）"


def test_the_block_parses_roles_statements_gaps_and_the_optional_lines() -> None:
    text = block(
        "#2 区域口径",
        "SQL角色：段1=诊断；段2=当前版（按性别分）；段3=备选（去重口径）",
        "SQL：SELECT 1\n  FROM t",
        f"表：{CUSTOMER} — 一行是一个客户",
        "条件：c.dt = '2024-01-31' — 本体 · 分区",
        "条件：c.status = 'A' — 提问者第 3 轮",
        "说法：第 3 轮「只算有效客户」— 范围：#2；表 demo_dwd.dwd_party_customer_info_df、t2",
        "提议缺口：有效客户的定义 — demo_dwd.x.status；提议：status = 'A'；原话第 3 轮",
        "撤销说法：第 1 轮「别算测试户」",
        "名字映射：客户表 = demo_dwd.dwd_party_customer_info_df",
        "偏好：一周从周一起",
        "未决问题：按签约日期还是放款日期？；不答按：签约日期",
    )
    parsed = memory.parse_block(text)

    assert parsed["topic"] == {"id": 2, "name": "区域口径"}
    assert parsed["roles"] == [{"segment": 1, "role": "诊断", "note": ""},
                               {"segment": 2, "role": "当前版", "note": "按性别分"},
                               {"segment": 3, "role": "备选", "note": "去重口径"}]
    assert parsed["statements"] == [{"raw": parsed["statements"][0]["raw"], "turn": 3, "quote": "只算有效客户",
                                     "topic": 2, "tables": [CUSTOMER, "t2"], "expr": None}]
    assert parsed["gaps"][0] | {"raw": None} == {"raw": None, "missing": "有效客户的定义",
                                                 "column": "demo_dwd.x.status", "proposed": "status = 'A'",
                                                 "turn": 3}
    assert parsed["withdraw"] == [{"turn": 1, "quote": "别算测试户"}]
    assert parsed["mappings"] == ["客户表 = demo_dwd.dwd_party_customer_info_df"]
    assert parsed["preferences"] == ["一周从周一起"]
    assert parsed["open_question"].startswith("按签约日期")
    assert memory.cited_turns(parsed["conditions"]) == {3}
    assert memory.parse_block(memory.block_text(answer(block("新：客户数")))) ["topic"] == {"new": True, "name": "客户数"}


def test_the_current_segment_is_the_one_marked_not_the_first() -> None:
    text = answer(block("新：客户数", "SQL角色：段1=诊断；段2=当前版；段3=备选（去重）"), LOAN_SQL, SQL1, SQL_ALT)
    out = apply(memory.new_state(), 1, "客户数", text)

    assert out["block_status"] == "ok" and out["sql"] == SQL1 and out["version"] == 1
    assert [s["version"] for s in out["segments"]] == [None, 1, None]
    assert [s["role"] for s in out["segments"]] == ["诊断", "当前版", "备选"]
    card = memory.render_card(out["state"], turn=2)
    assert SQL1 in card and LOAN_SQL not in card and SQL_ALT not in card
    assert "当前 SQL（#1 v1，第 1 轮）" in card and "check-sql（服务对 #1 v1 重跑）：错误 0，警告 0，提示 0" in card


def test_versions_are_assigned_by_code_and_unmarked_sql_keeps_the_previous_one() -> None:
    first = apply(memory.new_state(), 1, "客户数", answer(block("新：客户数", "SQL角色：段1=当前版"), SQL1))
    same = apply(first["state"], 2, "再看一次", answer(block("#1", "SQL角色：段1=当前版"), SQL1))
    assert same["version"] == 1 and same["new_version"] is None

    changed = apply(same["state"], 3, "按性别分",
                    answer(block("#1", "SQL角色：段1=当前版（按性别分）"), SQL2))
    assert changed["version"] == 2 and changed["new_version"] == 2

    unmarked = apply(changed["state"], 4, "再改", answer(block("#1"), SQL_ALT))
    topic = unmarked["state"]["topics"][0]
    assert unmarked["sql_missing"] and unmarked["block_status"] == "ok"
    assert topic["sql"]["text"] == SQL2 and topic["sql"]["v"] == 2
    assert unmarked["segments"][0]["version"] is None and unmarked["sql"] == SQL_ALT
    assert "v2（第 3 轮，按性别分）" in memory.render_card(unmarked["state"], turn=5)


def test_a_wrong_segment_count_or_unknown_topic_invalidates_the_block() -> None:
    first = apply(memory.new_state(), 1, "客户数",
                  answer(block("新：客户数", "SQL角色：段1=当前版", "条件：c.dt — 本体"), SQL1))
    for bad in (block("#1", "SQL角色：段2=当前版", "条件：x — 本体"),
                block("#9", "SQL角色：段1=当前版", "条件：x — 本体"),
                block("#1", "SQL角色：段1=当前版", "条件：x — 提问者第 7 轮")):
        out = apply(first["state"], 2, "再算", answer(bad, SQL2))
        topic = out["state"]["topics"][0]
        assert out["block_status"] == "invalid" and out["problems"]
        # model fields keep the previous version; code fields still move
        assert topic["conditions"] == ["c.dt — 本体"] and topic["sql"]["text"] == SQL1
        assert topic["last"] == 2 and out["state"]["turn"] == 2


def test_a_missing_block_keeps_the_model_fields_and_counts_the_streak() -> None:
    first = apply(memory.new_state(), 1, "客户数",
                  answer(block("新：客户数", "SQL角色：段1=当前版", "假设：期间 = 2024-01"), SQL1))
    second = apply(first["state"], 2, "按性别分", answer(None, SQL2))
    third = apply(second["state"], 3, "再按月分", answer(None, SQL2))

    assert second["block_status"] == "missing" and second["sql_missing"]
    assert third["state"]["missing_streak"] == 2
    topic = third["state"]["topics"][0]
    assert topic["params"] == ["期间 = 2024-01"] and topic["sql"]["text"] == SQL1 and topic["last"] == 3
    assert "上一轮的增量块：缺失" in memory.render_card(third["state"], turn=4)


# ---------------------------------------------------------------------- statements and the guard


def test_statements_are_taken_word_for_word_from_the_message() -> None:
    first = apply(memory.new_state(), 1, "客户数", answer(block("新：客户数", "SQL角色：段1=当前版"), SQL1))
    message = "不对，只算有效客户，测试户不要。"
    out = apply(first["state"], 2, message, answer(block(
        "#1", "SQL角色：段1=当前版（只算有效客户）", "条件：c.status = 'A' — 提问者第 2 轮",
        "说法：第 2 轮「只算有效客户」— 范围：#1；表 demo_dwd.dwd_party_customer_info_df"), SQL2),
        messages={1: "客户数"})

    assert out["state"]["statements"] == [{"turn": 2, "text": "只算有效客户", "topic": 1,
                                           "tables": [CUSTOMER], "pending": False, "expr": None}]
    assert "第 2 轮「只算有效客户」— 范围：#1" in memory.render_card(out["state"], turn=3)


def test_a_rewritten_quote_falls_back_to_the_whole_message_as_pending() -> None:
    first = apply(memory.new_state(), 1, "客户数", answer(block("新：客户数", "SQL角色：段1=当前版"), SQL1))
    message = "不对,只算有效客户!"
    out = apply(first["state"], 2, message, answer(block(
        "#1", "SQL角色：段1=当前版", "条件：c.status = 'A' — 提问者第 2 轮",
        "说法：第 2 轮「不对，只算有效客户！」— 范围：#1"), SQL2), messages={1: "客户数"})

    assert out["block_status"] == "ok"
    assert out["state"]["statements"] == [{"turn": 2, "text": message, "topic": 1, "tables": [],
                                           "pending": True}]
    assert any("说法的原话不在第 2 轮" in problem for problem in out["problems"])


def test_a_correction_without_a_marked_statement_is_kept_pending() -> None:
    first = apply(memory.new_state(), 1, "客户数", answer(block("新：客户数", "SQL角色：段1=当前版"), SQL1))
    cited = apply(first["state"], 2, "只算有效客户", answer(block(
        "#1", "SQL角色：段1=当前版", "条件：c.status = 'A' — 提问者第 2 轮"), SQL2))
    worded = apply(first["state"], 2, "只算有效客户", answer(None, SQL2, prose="按你说的改了。"))
    plain = apply(first["state"], 2, "按性别分", answer(block("#1", "SQL角色：段1=当前版"), SQL2))

    assert [s["pending"] for s in cited["state"]["statements"]] == [True]
    assert [s["text"] for s in worded["state"]["statements"]] == ["只算有效客户"]
    assert plain["state"]["statements"] == []


def _with_statement():
    first = apply(memory.new_state(), 1, "客户数", answer(block("新：客户数", "SQL角色：段1=当前版"), SQL1))
    second = apply(first["state"], 2, "只算有效客户", answer(block(
        "#1", "SQL角色：段1=当前版", "条件：c.status = 'A' — 提问者第 2 轮",
        f"说法：第 2 轮「只算有效客户」— 范围：#1；表 {CUSTOMER}"), SQL2), messages={1: "客户数"})
    return second["state"], {1: "客户数", 2: "只算有效客户"}


def test_the_guard_fires_in_topic_when_no_condition_cites_the_statement() -> None:
    state, messages = _with_statement()
    missed = apply(state, 3, "按月分", answer(block("#1", "SQL角色：段1=当前版", "条件：c.dt — 本体"), SQL_ALT),
                   messages)
    kept = apply(state, 3, "按月分", answer(block(
        "#1", "SQL角色：段1=当前版", "条件：c.status = 'A' — 提问者第 2 轮"), SQL_ALT), messages)
    no_sql = apply(state, 3, "这张表一行是什么", answer(block("#1", "SQL角色：无")), messages)

    assert missed["guard"] == ["这次没有沿用你第 2 轮说的「只算有效客户」，要不要加上？"]
    assert kept["guard"] == [] and no_sql["guard"] == []


def test_the_guard_is_quiet_on_a_topic_switch_unless_a_scoped_table_is_used() -> None:
    state, messages = _with_statement()
    switched = apply(state, 3, "看看借据", answer(block("新：借据", "SQL角色：段1=当前版"), LOAN_SQL), messages)
    overlap = apply(state, 3, "另一个客户问题", answer(block("新：客户画像", "SQL角色：段1=当前版"), SQL_ALT),
                    messages)

    assert switched["guard"] == [] and switched["topic"] == 2
    assert len(overlap["guard"]) == 1


def test_a_withdrawn_statement_leaves_the_card_and_the_guard() -> None:
    state, messages = _with_statement()
    messages[3] = "忘掉只算有效客户那条"
    out = apply(state, 3, messages[3], answer(block("#1", "SQL角色：段1=当前版", "撤销说法：第 2 轮"), SQL1),
                messages)

    assert out["state"]["statements"] == [] and out["guard"] == []
    assert out["state"]["withdrawn"] == [{"turn": 2, "text": "只算有效客户", "at": 3}]
    assert "第 2 轮「只算有效客户」（第 3 轮撤销）" in memory.render_card(out["state"], turn=4)


# ---------------------------------------------------------------------- budget


def test_over_budget_old_topics_archive_and_statements_never_do() -> None:
    state, messages = _with_statement()
    turn = 3
    for name, sql in (("借据", LOAN_SQL), ("客户画像", SQL_ALT), ("借据二", LOAN_SQL + " AND 1 = 1")):
        messages[turn] = name
        state = apply(state, turn, name, answer(block(f"新：{name}", "SQL角色：段1=当前版"), sql), messages)["state"]
        turn += 1
    full = memory.render_card(state, turn=turn)
    budget = len(full) - 40

    compacted, archived, card = memory.compact(state, turn=turn, budget=budget)
    assert archived and archived[0] == 1  # least recently used first
    assert len(card) <= budget or compacted["compact"]
    assert "第 2 轮「只算有效客户」" in card  # the statement of the archived topic stays
    assert "已归档，详情用 recall" in card
    assert memory.archive_notice(compacted, archived).startswith("对话状态卡超出预算")
    # a tiny budget archives everything else and then lists versions without turns
    tiny, _, small = memory.compact(state, turn=turn, budget=200)
    assert tiny["compact"] and "第 2 轮「只算有效客户」" in small


def test_statements_over_their_reserve_ask_which_to_drop() -> None:
    state = apply(memory.new_state(), 1, "客户数", answer(block("新：客户数", "SQL角色：段1=当前版"), SQL1))["state"]
    messages = {1: "客户数"}
    long_rule = "口径" * 400
    messages[2] = long_rule + "。" + long_rule + "!"
    out = apply(state, 2, messages[2], answer(block(
        "#1", "SQL角色：段1=当前版", f"说法：第 2 轮「{long_rule}。」— 范围：#1",
        f"说法：第 2 轮「{long_rule}!」— 范围：#1"), SQL1), messages)

    assert memory.statement_chars(out["state"]) > memory.STATEMENT_RESERVE
    assert out["statements_over"].startswith("你给过的说法已经很多") and "要不要撤掉哪些" in out["statements_over"]
    _, _, card = memory.compact(out["state"], turn=3, budget=500)
    assert card.count(long_rule) == 2


# ---------------------------------------------------------------------- recall


def test_recall_by_turn_and_by_topic_and_version() -> None:
    turns = [
        {"turn": 1, "status": "done", "question": "客户数", "answer": "v1 的答案", "topic": 1,
         "segments": [{"index": 1, "sql": SQL1, "role": "当前版", "version": 1, "topic": 1}]},
        {"turn": 2, "status": "done", "question": "按性别分", "answer": "v2 的答案", "topic": 1,
         "segments": [{"index": 1, "sql": SQL2, "role": "当前版", "version": 2, "topic": 1}]},
        {"turn": 3, "status": "interrupted", "question": "再算", "topic": None},
    ]
    ok, text, data = memory.recall(turns, turn=1)
    assert ok and "问题：客户数" in text and SQL1 in text and data["versions"] == [1]
    ok, text, _ = memory.recall(turns, topic=1, version=1)
    assert ok and "第 1 轮" in text and "要取的这一版" in text
    ok, text, data = memory.recall(turns, topic=1)
    assert ok and data["turn"] == 2
    ok, text, _ = memory.recall(turns, turn=3)
    assert ok and "中断" in text
    ok, text, _ = memory.recall(turns, turn=9)
    assert not ok and "没有第 9 轮" in text
    assert not memory.recall(turns, topic=1, version=5)[0]


# ---------------------------------------------------------------------- the service


class Replay:
    """A model that answers each question with the next scripted answer (tool calls first
    when the step is a list), recording every request."""

    name = "replay"

    def __init__(self, *steps):
        self.steps = list(steps)
        self.requests = []
        self.pending = []

    def turn(self, request, should_stop):
        self.requests.append(json.loads(json.dumps(request)))
        if not self.pending:
            step = self.steps.pop(0)
            self.pending = list(step) if isinstance(step, list) else [step]
        item = self.pending.pop(0)
        if isinstance(item, dict):  # a tool call
            return {"content": [{"type": "tool_use", "id": f"t{len(self.requests)}", "name": item["name"],
                                 "input": item["input"]}],
                    "stop_reason": "tool_use", "stop_details": None, "usage": {}, "model": "replay"}
        return {"content": [{"type": "text", "text": item}], "stop_reason": "end_turn",
                "stop_details": None, "usage": {}, "model": "replay"}


class Wall:
    """A wall clock the test sets."""

    def __init__(self, day):
        self.day = day

    def __call__(self):
        return self.day


@pytest.fixture
def toolbox(inputs) -> ToolBox:
    state = CatalogState(str(inputs["ontology"]), semantics=str(inputs["semantics"]),
                         pending=str(inputs["pending"]))
    return ToolBox(state, max_sql=8192)


def ask(service, question, conversation=None):
    conv, run = service.ask(question, conversation)
    done = False
    while not done:
        _, done = run.wait_events(0, 5)
    service_thread_done(service, conv)
    return conv, run


def service_thread_done(service, conv):
    # the record is finished under the service lock right after the run ends
    for _ in range(200):
        with service._lock:
            if all(item["status"] != "running" for item in conv.turns):
                return
        import time
        time.sleep(0.01)


def _first_text(request):
    return request["messages"][0]["content"][0]["text"]


def test_every_question_starts_with_todays_date_and_the_system_prompt_never_changes(toolbox) -> None:
    model = Replay(answer(block("新：客户数", "SQL角色：段1=当前版"), SQL1),
                   answer(block("#1", "SQL角色：段1=当前版（按性别分）"), SQL2))
    wall = Wall(datetime(2026, 11, 25, 23, 59, tzinfo=TZ))
    service = AskService(toolbox, model, now=wall)
    conv, _ = ask(service, "上个月客户数")
    wall.day += timedelta(minutes=2)  # past midnight: the next question is told the new date
    ask(service, "按性别分", conv.id)

    first, second = (_first_text(r) for r in (model.requests[0], model.requests[-1]))
    assert first.startswith("今天：2026-11-25（时区 +08:00）\n【对话状态卡】")
    assert second.startswith("今天：2026-11-26（时区 +08:00）\n【对话状态卡】")
    assert first.endswith("问题：上个月客户数") and second.endswith("问题：按性别分")
    assert "当前 SQL（#1 v1，第 1 轮）" in second and SQL1 in second
    assert "上一题的简报" not in second  # the card replaces the brief
    systems = {json.dumps(r["system"], ensure_ascii=False) for r in model.requests}
    tools = {json.dumps(r["tools"], ensure_ascii=False) for r in model.requests}
    assert len(systems) == 1 and len(tools) == 1
    assert [t["name"] for t in model.requests[0]["tools"]][-1] == "recall"
    assert not any("（时区 +08:00）" in block_["text"] for block_ in model.requests[0]["system"])


def test_the_answer_shows_the_guard_line_and_the_page_gets_topic_and_version(toolbox) -> None:
    model = Replay(
        answer(block("新：客户数", "SQL角色：段1=当前版"), SQL1),
        answer(block("#1", "SQL角色：段1=当前版", "条件：c.status = 'A' — 提问者第 2 轮",
                     f"说法：第 2 轮「只算有效客户」— 范围：#1；表 {CUSTOMER}"), SQL2),
        answer(block("#1", "SQL角色：段1=当前版（按月分）", "条件：c.dt — 本体"), SQL_ALT),
    )
    service = AskService(toolbox, model)
    conv, _ = ask(service, "客户数")
    ask(service, "只算有效客户", conv.id)
    _, run = ask(service, "按月分", conv.id)

    event = next(e for e in run.events if e["type"] == "answer")
    assert event["text"].endswith("这次没有沿用你第 2 轮说的「只算有效客户」，要不要加上？")
    assert event["sql"] == SQL_ALT
    mem = event["memory"]
    assert mem["topic"] == 1 and mem["version"] == 3 and mem["block"] == "ok"
    assert mem["view"]["statements"] == [{"turn": 2, "text": "只算有效客户", "topic": 1, "pending": False}]
    assert mem["view"]["conditions"] == ["c.dt — 本体"]
    assert conv.turns[-1]["answer"] == event["text"]


def test_recall_is_bound_to_its_conversation(toolbox) -> None:
    other = Replay(*[answer(block("新：别的" if i == 0 else "#1", "SQL角色：段1=当前版"), SQL1) for i in range(3)])
    service = AskService(toolbox, other)
    first, _ = ask(service, "别的对话的第一个问题")
    ask(service, "别的对话的第二个问题", first.id)
    ask(service, "别的对话的第三个问题", first.id)

    model = Replay([{"name": "recall", "input": {"turn": 2}},
                    {"name": "recall", "input": {"turn": 1, "conversation": first.id}},
                    answer(block("新：x", "SQL角色：无"))])
    service.models.default.model = model
    _, run = ask(service, "我的第一个问题")

    results = [e for e in run.events if e["type"] == "tool_result"]
    assert [r["ok"] for r in results] == [False, False]
    assert "本对话没有第 2 轮" in results[0]["error"]
    assert "unknown argument(s): conversation" in results[1]["error"]
    sent = json.dumps(model.requests[-1]["messages"], ensure_ascii=False)
    assert "别的对话" not in sent


def test_recall_returns_an_earlier_turn_from_memory(toolbox) -> None:
    model = Replay(answer(block("新：客户数", "SQL角色：段1=当前版"), SQL1),
                   answer(block("#1", "SQL角色：段1=当前版"), SQL2),
                   [{"name": "recall", "input": {"topic": 1, "version": 1}},
                    answer(block("#1", "SQL角色：段1=当前版（回到第一版）"), SQL1)])
    service = AskService(toolbox, model)
    conv, _ = ask(service, "客户数")
    ask(service, "按性别分", conv.id)
    _, run = ask(service, "回到第一版", conv.id)

    result = next(e for e in run.events if e["type"] == "tool_result")
    assert result["ok"] and result["data"]["turn"] == 1
    tool_message = model.requests[-1]["messages"][-1]["content"][0]["content"]
    assert SQL1 in tool_message and "问题：客户数" in tool_message
    # the same text as before is a new version: v3, not v1 again
    assert conv.state["topics"][0]["sql"]["v"] == 3


def test_the_store_round_trips_and_survives_a_restart(toolbox, tmp_path) -> None:
    store_dir = tmp_path / "store"
    model = Replay(
        [{"name": "search_catalog", "input": {"text": "客户"}},
         answer(block("新：客户数", "SQL角色：段1=当前版；段2=备选（去重）",
                      f"说法：第 1 轮「只算有效客户」— 范围：#1；表 {CUSTOMER}"), SQL1, SQL_ALT)],
        answer(block("#1", "SQL角色：段1=当前版"), SQL2),
    )
    service = AskService(toolbox, model, store=Store(store_dir))
    conv, _ = ask(service, "客户数，只算有效客户")
    ask(service, "按性别分", conv.id)

    path = store_dir / f"{conv.id}.json"
    assert stat.S_IMODE(os.stat(store_dir).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert not list(store_dir.glob(".tmp-*"))
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["schema"] == SCHEMA and [t["status"] for t in document["turns"]] == ["done", "done"]
    first = document["turns"][0]
    assert first["question"] == "客户数，只算有效客户" and first["tools"] == [
        {"name": "search_catalog", "input": {"text": "客户"}}]
    assert [(s["role"], s["version"]) for s in first["segments"]] == [("当前版", 1), ("备选", None)]
    assert first["block"]["topic"] == {"new": True, "name": "客户数"} and first["card_after"]
    hits = toolbox.state.search("客户").text()
    assert hits not in path.read_text(encoding="utf-8")  # never a tool result

    restarted = AskService(toolbox, Replay(answer(block("#1", "SQL角色：段1=当前版"), SQL1)),
                           store=Store(store_dir))
    shown = restarted.conversation(conv.id)
    assert [t["turn"] for t in shown["turns"]] == [1, 2] and shown["memory"]["version"] == 2
    assert shown["memory"]["statements"][0]["text"] == "只算有效客户"
    again, run = ask(restarted, "再改回去", conv.id)
    text = _first_text(restarted.models.default.model.requests[0])
    assert "本轮是第 3 轮" in text and SQL2 in text
    assert len(again.turns) == 3 and run.status == "done"


def test_a_run_in_progress_at_restart_is_interrupted_and_leaves_the_card(toolbox, tmp_path) -> None:
    store = Store(tmp_path / "s")
    state = memory.new_state()
    store.save({"conversation": "abc", "created": "x", "state": state,
                "turns": [{"turn": 1, "status": "running", "question": "客户数"}]})
    service = AskService(toolbox, Replay(), store=Store(tmp_path / "s"))

    shown = service.conversation("abc")
    assert shown["turns"][0]["status"] == "interrupted" and shown["memory"]["topic"] is None
    on_disk = json.loads((tmp_path / "s" / "abc.json").read_text(encoding="utf-8"))
    assert on_disk["turns"][0]["status"] == "interrupted"


def test_an_older_record_format_is_read_only(toolbox, tmp_path) -> None:
    (tmp_path / "old.json").write_text(json.dumps({"schema": "ask-store/0", "conversation": "old",
                                                   "turns": [{"turn": 1, "status": "done"}]}))
    service = AskService(toolbox, Replay(), store=Store(tmp_path))

    assert service.conversation("old")["read_only"] is True
    with pytest.raises(AskError) as refused:
        service.ask("再问", "old")
    assert refused.value.status == 409 and refused.value.kind == "read_only"
    assert json.loads((tmp_path / "old.json").read_text())["schema"] == "ask-store/0"


def test_a_conversation_holds_at_most_the_turn_cap(toolbox) -> None:
    service = AskService(toolbox, Replay(answer(block("新：x", "SQL角色：无"))))
    conv, _ = ask(service, "第一个")
    conv.turns.extend({"turn": n, "status": "done", "question": "q"} for n in range(2, MAX_TURNS + 1))
    with pytest.raises(AskError) as refused:
        service.ask("再问", conv.id)
    assert refused.value.kind == "conversation_full"


def test_the_trace_records_the_block_card_size_and_guard(toolbox, tmp_path) -> None:
    model = Replay(answer(block("新：客户数", "SQL角色：段1=当前版"), SQL1), answer(None, SQL2))
    service = AskService(toolbox, model, trace=Tracer(tmp_path / "t"))
    conv, _ = ask(service, "客户数")
    ask(service, "按性别分", conv.id)

    lines = [json.loads(line) for line in (tmp_path / "t" / f"{conv.id}.jsonl").read_text().splitlines()]
    runs = [line for line in lines if line["kind"] == "run"]
    first, second = runs[0]["memory"], runs[1]["memory"]
    assert first["block"] == "ok" and first["turn"] == 1 and first["card_chars"] > 0
    assert first["card_chars_next"] > first["card_chars"] and first["guard"] == []
    assert second["block"] == "missing" and second["sql_missing"] and second["archived"] == []


def test_a_failed_run_does_not_move_the_card(toolbox) -> None:
    from scope_lineage_service.ask.loop import ModelError

    class Failing(Replay):
        def turn(self, request, should_stop):
            raise ModelError("api_error", "down")

    service = AskService(toolbox, Replay(answer(block("新：客户数", "SQL角色：段1=当前版"), SQL1)))
    conv, _ = ask(service, "客户数")
    before = json.dumps(conv.state, ensure_ascii=False)
    service.models.default.model = Failing()
    ask(service, "按性别分", conv.id)

    assert json.dumps(conv.state, ensure_ascii=False) == before
    assert [t["status"] for t in conv.turns] == ["done", "error"]


# ---------------------------------------------------------------------- the options


def test_the_memory_options_need_ask(inputs, tmp_path, capsys) -> None:
    from scope_lineage_service.cli import main

    code = main(["http", str(inputs["ontology"]), "--ask-store", str(tmp_path / "s"),
                 "--ask-today", "2026-01-31"])
    err = capsys.readouterr().err
    assert code == 2 and "--ask-store" in err and "--ask-today" in err
    assert not (tmp_path / "s").exists()


def test_the_memory_options_reach_the_service(inputs, tmp_path) -> None:
    from scope_lineage_service.cli import _ask_service, _parser
    from scope_lineage.cli_catalog_answers import CatalogAnswerError

    state = CatalogState(str(inputs["ontology"]))
    args = _parser().parse_args(["http", str(inputs["ontology"]), "--ask-dev-fake-model",
                                 "--ask-store", str(tmp_path / "s"), "--ask-today", "2026-01-31",
                                 "--ask-card-budget", "3000"])
    service, notice = _ask_service(args, state)
    assert isinstance(service.store, Store) and service.card_budget == 3000
    assert memory.today_line(service.now()).startswith("今天：2026-01-31（时区 ")
    assert "ask store:" in notice and "2026-01-31" in notice

    plain, notice = _ask_service(_parser().parse_args(["http", str(inputs["ontology"]),
                                                       "--ask-dev-fake-model"]), state)
    assert plain.store is None and plain.card_budget == memory.DEFAULT_CARD_BUDGET
    assert "ask store" not in notice
    with pytest.raises(CatalogAnswerError):
        _ask_service(_parser().parse_args(["http", str(inputs["ontology"]), "--ask-dev-fake-model",
                                           "--ask-today", "31/01/2026"]), state)


def test_the_fake_model_walks_the_card_through_two_turns(inputs) -> None:
    from scope_lineage_service.ask.fake_model import FakeModel

    state = CatalogState(str(inputs["ontology"]), semantics=str(inputs["semantics"]))
    service = AskService(ToolBox(state, max_sql=8192), FakeModel(state, delay=0))
    conv, first = ask(service, "客户数")
    _, second = ask(service, "按性别分", conv.id)

    events = [next(e for e in run.events if e["type"] == "answer") for run in (first, second)]
    assert [e["memory"]["block"] for e in events] == ["ok", "ok"]
    assert [e["memory"]["topic"] for e in events] == [1, 1]
    assert conv.state["topics"][0]["versions"][-1]["v"] == 2
