"""One question's loop, driven by a scripted model behind the model seam (no SDK, no network).

``Scripted`` plays back assistant turns as the Messages API would return them (content
blocks as plain dicts, a stop reason, usage) and records every request the loop sent, so
the tests can check what went back to the model: all tool results of a turn in one user
message, ``is_error`` on a failed tool, a byte-identical cached prefix on every turn.
"""

from __future__ import annotations

import json
import threading

import pytest
from service_paths import CUSTOMER

from scope_lineage_service.ask import walk
from scope_lineage_service.ask.loop import (
    Cancelled, InvalidToolInput, Limits, ModelError, Run, echo_content, question_text,
    run_question,
)
from scope_lineage_service.ask.tools import ToolBox
from scope_lineage_service.state import CatalogState

SQL = (f"SELECT COUNT(*) AS cnt FROM {CUSTOMER} c WHERE c.dt = '2024-01-31' "
       "AND /* 待确认：注销的客户算不算 */ 1 = 1")
BRIEF = f"问题：客户数\n结论：见 SQL\nSQL：{SQL}\n条件：c.dt = '2024-01-31' — 目录 · 分区\n待确认：注销的客户算不算 — 无；无；未记入"
ANSWER = f"客户数这样取：\n\n```sql\n{SQL}\n```\n\n条件和依据……\n\n```text\n{BRIEF}\n```\n"


def text(value):
    return {"type": "text", "text": value}


def call(id_, name, **args):
    return {"type": "tool_use", "id": id_, "name": name, "input": args}


def turn(*content, stop="tool_use", usage=None, details=None):
    return {"content": list(content), "stop_reason": stop, "stop_details": details,
            "usage": usage or {"input_tokens": 100, "output_tokens": 50,
                               "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
            "model": "scripted"}


class Scripted:
    """The model seam, played back; an Exception in the script is raised at that turn."""

    name = "scripted"

    def __init__(self, *turns, on_turn=None):
        self.turns = list(turns)
        self.requests = []
        self.on_turn = on_turn

    def turn(self, request, should_stop):
        self.requests.append(json.loads(json.dumps(request)))
        if self.on_turn:
            self.on_turn(len(self.requests), should_stop)
        if not self.turns:
            raise AssertionError("the loop asked for more turns than scripted")
        step = self.turns.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


@pytest.fixture
def tools(inputs) -> ToolBox:
    state = CatalogState(str(inputs["ontology"]), semantics=str(inputs["semantics"]),
                         pending=str(inputs["pending"]))
    return ToolBox(state, max_sql=8192)


def run(model, tools, question="客户数", brief=None, limits=None, run_obj=None):
    job = run_obj or Run("r1", question, brief)
    run_question(job, model, tools, walk.system_blocks(tools.pending), limits or Limits())
    return job


def events(job, kind):
    return [event for event in job.events if event["type"] == kind]


def finished(job):
    return events(job, "finished")[-1]


# ------------------------------------------------------------------ round trips


def test_a_tool_round_trip_then_an_answer(tools) -> None:
    model = Scripted(
        turn(text("先检索。"), call("t1", "search_catalog", text="客户数")),
        turn(text(ANSWER), stop="end_turn"),
    )
    job = run(model, tools)

    assert finished(job)["status"] == "done"
    result = events(job, "tool_result")[0]
    assert result["ok"] and result["name"] == "search_catalog" and result["data"]["hits"]
    second = model.requests[1]["messages"]
    assert second[0] == {"role": "user", "content": [text("问题：客户数")]}
    assert second[1]["role"] == "assistant" and second[1]["content"][1]["id"] == "t1"
    assert second[2]["content"] == [{
        "type": "tool_result", "tool_use_id": "t1",
        "content": tools.state.search("客户数").text(),
    }]
    answer = events(job, "answer")[0]
    assert answer["sql"] == SQL and answer["brief"] == BRIEF and not answer["brief_missing"]
    assert answer["placeholders"][0]["text"] == "注销的客户算不算"


def test_parallel_tool_calls_go_back_in_one_user_message(tools) -> None:
    model = Scripted(
        turn(call("a", "query_catalog", kind="table", term=CUSTOMER),
             call("b", "search_catalog", text="客户", kinds=["metric"]),
             call("c", "check_sql", sql=SQL)),
        turn(text(ANSWER), stop="end_turn"),
    )
    job = run(model, tools)

    results = model.requests[1]["messages"][2]
    assert results["role"] == "user"
    assert [block["tool_use_id"] for block in results["content"]] == ["a", "b", "c"]
    assert [event["id"] for event in events(job, "tool_call")] == ["a", "b", "c"]
    assert len(model.requests[1]["messages"]) == 3


def test_a_failed_tool_returns_is_error_and_the_loop_goes_on(tools) -> None:
    model = Scripted(
        turn(call("a", "catalog_context", columns_of_table=["x"]),
             call("b", "search_catalog", text="客户")),
        turn(text(ANSWER), stop="end_turn"),
    )
    job = run(model, tools)

    first, second = model.requests[1]["messages"][2]["content"]
    assert first["is_error"] is True and "--table" in first["content"]
    assert "is_error" not in second
    assert [e["ok"] for e in events(job, "tool_result")] == [False, True]
    assert finished(job)["status"] == "done"


def test_a_tool_input_that_does_not_parse_is_asked_again(tools) -> None:
    model = Scripted(InvalidToolInput("bad JSON"), turn(text(ANSWER), stop="end_turn"))
    job = run(model, tools)

    assert finished(job)["status"] == "done"
    assert len(model.requests) == 2 and model.requests[0] == model.requests[1]


def test_the_cached_prefix_is_identical_on_every_turn(tools) -> None:
    model = Scripted(
        turn(call("a", "search_catalog", text="客户")),
        turn(call("b", "query_catalog", kind="table", term=CUSTOMER)),
        turn(text(ANSWER), stop="end_turn"),
    )
    run(model, tools)

    prefixes = {json.dumps([r["tools"], r["system"]], ensure_ascii=False) for r in model.requests}
    assert len(prefixes) == 1
    # each request starts with the previous one's messages, unchanged
    for before, after in zip(model.requests, model.requests[1:]):
        assert after["messages"][: len(before["messages"])] == before["messages"]


def test_usage_is_added_up_per_question(tools) -> None:
    usages = [
        {"input_tokens": 900, "output_tokens": 40, "cache_creation_input_tokens": 5000,
         "cache_read_input_tokens": 0},
        {"input_tokens": 300, "output_tokens": 70, "cache_creation_input_tokens": 200,
         "cache_read_input_tokens": 5000},
    ]
    model = Scripted(turn(call("a", "search_catalog", text="客户"), usage=usages[0]),
                     turn(text(ANSWER), stop="end_turn", usage=usages[1]))
    job = run(model, tools)

    assert finished(job)["usage"] == {
        "input_tokens": 1200, "output_tokens": 110, "cache_creation_input_tokens": 5200,
        "cache_read_input_tokens": 5000, "turns": 2, "tool_calls": 1,
    }
    assert [e["usage"]["cache_read_input_tokens"] for e in events(job, "turn")] == [0, 5000]


# ------------------------------------------------------------------ stop reasons


def test_a_refusal_stops_and_its_tools_are_not_run(tools) -> None:
    details = {"type": "refusal", "category": "cyber", "explanation": "declined"}
    model = Scripted(turn(call("a", "search_catalog", text="x"), stop="refusal", details=details))
    job = run(model, tools)

    assert finished(job)["status"] == "refused"
    assert finished(job)["detail"] == details
    assert not events(job, "tool_call")


def test_max_tokens_stops_without_running_a_cut_tool_call(tools) -> None:
    model = Scripted(turn(text("写到一半"), call("a", "check_sql", sql="SELECT"), stop="max_tokens"))
    job = run(model, tools)

    assert finished(job)["status"] == "max_tokens"
    assert not events(job, "tool_call")
    assert events(job, "turn")[0]["text"] == "写到一半"


def test_pause_turn_sends_the_turn_back_to_continue(tools) -> None:
    paused = turn(text("思考中"), stop="pause_turn")
    model = Scripted(paused, turn(text(ANSWER), stop="end_turn"))
    job = run(model, tools)

    assert finished(job)["status"] == "done"
    assert model.requests[1]["messages"][-1] == {"role": "assistant", "content": paused["content"]}


def test_a_fallback_boundary_is_echoed_by_the_rules(tools) -> None:
    content = [
        {"type": "thinking", "thinking": "", "signature": "s1"},
        text("部分"),
        {"type": "tool_use", "id": "x", "name": "search_catalog", "input": {"text": "a"}},
        {"type": "fallback", "from": {"model": "m1"}, "to": {"model": "m2"}},
        {"type": "thinking", "thinking": "", "signature": "s2"},
        call("b", "search_catalog", text="客户"),
    ]
    assert echo_content(content) == [content[1], content[3], content[4], content[5]]

    model = Scripted(turn(*content), turn(text(ANSWER), stop="end_turn"))
    job = run(model, tools)

    assert [e["id"] for e in events(job, "tool_call")] == ["b"]
    assert events(job, "fallback")[0]["to"] == "m2"
    assert model.requests[1]["messages"][1]["content"] == echo_content(content)


# ------------------------------------------------------------------ caps and cancel


def test_the_turn_cap_stops_the_question(tools) -> None:
    model = Scripted(*[turn(call(f"t{n}", "search_catalog", text="客户")) for n in range(3)])
    job = run(model, tools, limits=Limits(max_turns=2))

    assert finished(job)["status"] == "cap_reached" and finished(job)["reason"] == "turns"
    assert len(model.requests) == 2


def test_the_tool_call_cap_refuses_extra_calls_then_stops(tools) -> None:
    model = Scripted(
        turn(call("a", "search_catalog", text="客户"), call("b", "search_catalog", text="表")),
        turn(call("c", "search_catalog", text="客户")),
    )
    job = run(model, tools, limits=Limits(max_tool_calls=1))

    first = model.requests[1]["messages"][2]["content"]
    assert "is_error" not in first[0] and first[1]["is_error"] is True
    assert "上限" in first[1]["content"]
    assert finished(job)["status"] == "cap_reached" and finished(job)["reason"] == "tool_calls"
    assert finished(job)["usage"]["tool_calls"] == 1


def test_a_refused_extra_call_still_lets_the_model_answer(tools) -> None:
    model = Scripted(
        turn(call("a", "search_catalog", text="客户"), call("b", "search_catalog", text="表")),
        turn(text(ANSWER), stop="end_turn"),
    )
    job = run(model, tools, limits=Limits(max_tool_calls=1))

    assert finished(job)["status"] == "done"


def test_the_output_token_cap_bounds_each_request_and_the_question(tools) -> None:
    big = {"input_tokens": 10, "output_tokens": 1500, "cache_creation_input_tokens": 0,
           "cache_read_input_tokens": 0}
    model = Scripted(turn(call("a", "search_catalog", text="客户"), usage=big),
                     turn(call("b", "search_catalog", text="客户"), usage=big))
    job = run(model, tools, limits=Limits(max_output_tokens=3000, max_tokens_per_turn=64000))

    assert [r["max_tokens"] for r in model.requests] == [3000, 1500]
    assert finished(job)["status"] == "cap_reached"
    assert finished(job)["reason"] == "output_tokens"


def test_wall_time_stops_a_turn_in_flight(tools) -> None:
    now = [0.0]

    def stalled(_, should_stop):
        assert not should_stop()
        now[0] = 5.0
        assert should_stop()
        raise Cancelled()

    job = Run("r1", "客户数", None, clock=lambda: now[0])
    model = Scripted(turn(text("x"), stop="end_turn"), on_turn=stalled)
    run_question(job, model, tools, walk.system_blocks(True), Limits(max_seconds=1))

    assert finished(job)["status"] == "cap_reached" and finished(job)["reason"] == "seconds"


def test_cancel_stops_a_turn_in_flight(tools) -> None:
    started, release = threading.Event(), threading.Event()
    job = Run("r1", "客户数", None)

    def wait_for_cancel(_, should_stop):
        started.set()
        release.wait(5)
        assert should_stop()
        raise Cancelled()

    model = Scripted(turn(text("x"), stop="end_turn"), on_turn=wait_for_cancel)
    worker = threading.Thread(target=run, args=(model, tools), kwargs={"run_obj": job})
    worker.start()
    started.wait(5)
    job.cancel()
    release.set()
    worker.join(5)

    assert finished(job)["status"] == "cancelled"


def test_cancel_between_turns_runs_no_more_tools(tools) -> None:
    job = Run("r1", "客户数", None)
    model = Scripted(turn(call("a", "search_catalog", text="客户")),
                     on_turn=lambda n, _: job.cancel())
    run(model, tools, run_obj=job)

    assert finished(job)["status"] == "cancelled"
    assert not events(job, "tool_call")


def test_a_model_error_ends_the_question_with_its_kind(tools) -> None:
    model = Scripted(ModelError("credentials", "no credential resolved"))
    job = run(model, tools)

    assert finished(job)["status"] == "error" and finished(job)["reason"] == "credentials"
    assert "no credential" in finished(job)["detail"]


# ------------------------------------------------------------------ follow-ups and the answer


def test_a_follow_up_carries_the_brief_not_the_transcript(tools) -> None:
    model = Scripted(turn(text(ANSWER), stop="end_turn"))
    run(model, tools, question="换成上个月", brief=BRIEF)

    assert model.requests[0]["messages"] == [
        {"role": "user", "content": [text(question_text("换成上个月", BRIEF))]}]
    assert BRIEF in question_text("换成上个月", BRIEF)


def test_an_answer_without_a_brief_still_carries_one(tools) -> None:
    model = Scripted(turn(text("目录里没有这个指标。"), stop="end_turn"))
    job = run(model, tools)

    answer = events(job, "answer")[0]
    assert answer["brief_missing"] and answer["brief"].startswith("问题：客户数")
    assert answer["sql"] is None and answer["placeholders"] == []


def test_events_are_numbered_and_waitable(tools) -> None:
    model = Scripted(turn(text(ANSWER), stop="end_turn"))
    job = run(model, tools)

    assert [e["seq"] for e in job.events] == list(range(1, len(job.events) + 1))
    got, done = job.wait_events(after=2, timeout=0)
    assert done and [e["seq"] for e in got] == list(range(3, len(job.events) + 1))
