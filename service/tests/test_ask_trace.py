"""``--ask-trace DIR``: a read-only record of each question run; off, nothing changes.

The runs are the development fake's (real catalog tool calls, no model) and a scripted
model's for the error line; the clock is fixed so two runs' events can be compared exactly.
"""

from __future__ import annotations

import json
import logging
import stat
import threading

from scope_lineage_service.ask import walk
from scope_lineage_service.ask.fake_model import FakeModel
from scope_lineage_service.ask.loop import Limits, ModelError, Run, run_question
from scope_lineage_service.ask.service import AskService
from scope_lineage_service.ask.tools import ToolBox
from scope_lineage_service.ask.trace import SCHEMA, Tracer
from scope_lineage_service.cli import main
from scope_lineage_service.http_server import make_server
from scope_lineage_service.state import CatalogState

QUESTION = "客户数"
TURN_KEYS = {"schema", "kind", "at", "conversation", "run", "turn", "model_id", "model", "elapsed",
             "stop_reason", "usage", "usage_estimated", "request_chars",
             "largest_tool_result_chars", "tool_results"}
TOOL_KEYS = {"schema", "kind", "at", "conversation", "run", "turn", "id", "name", "input", "ok",
             "result_chars"}
RUN_KEYS = {"schema", "kind", "at", "conversation", "run", "model_id", "question", "follow_up",
            "status", "reason", "error_kind", "error_message", "answer", "has_sql", "has_brief",
            "brief_missing", "elapsed", "turns", "tool_calls", "usage", "usage_estimated"}


def _state(inputs):
    return CatalogState(str(inputs["ontology"]), semantics=str(inputs["semantics"]),
                        pending=str(inputs["pending"]))


def _lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _run(state, model, tracer=None):
    tools = ToolBox(state, max_sql=8192)
    job = Run("r1", QUESTION, None, model_id="default", clock=lambda: 1000.0)
    if tracer is not None:
        job.observer = tracer.observer("c", job)
    run_question(job, model, tools, walk.system_blocks(tools.pending), Limits())
    return job


def test_a_run_is_recorded_turn_by_turn_without_the_catalog_text(inputs, tmp_path) -> None:
    state = _state(inputs)
    tracer = Tracer(tmp_path / "trace")
    job = Run("r1", QUESTION, None, model_id="default")
    _run_with(state, job, tracer.observer("conv1", job))

    path = tmp_path / "trace" / "conv1.jsonl"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    lines = _lines(path)
    assert all(line["schema"] == SCHEMA and line["conversation"] == "conv1" and line["run"] == "r1"
               for line in lines)
    turns = [line for line in lines if line["kind"] == "turn"]
    tools = [line for line in lines if line["kind"] == "tool"]
    assert [line["kind"] for line in lines][-1] == "run"
    assert all(set(line) == TURN_KEYS for line in turns)
    assert all(set(line) == TOOL_KEYS for line in tools)
    assert [line["turn"] for line in turns] == list(range(1, len(turns) + 1))
    assert turns[0]["tool_results"] == 0 and turns[0]["largest_tool_result_chars"] == 0
    assert turns[1]["tool_results"] == 1 and turns[2]["tool_results"] == 3
    assert all(line["request_chars"] > 0 and line["elapsed"] >= 0 for line in turns)
    assert turns[0]["model_id"] == "default" and turns[0]["model"] == "dev-fake-model"
    assert [line["name"] for line in tools][:3] == ["search_catalog", "query_catalog", "search_catalog"]
    assert tools[0]["input"] == {"text": QUESTION} and tools[0]["turn"] == 1
    # the tool result's size, never its text: the biggest one sent equals one recorded
    assert max(t["largest_tool_result_chars"] for t in turns) == max(t["result_chars"] for t in tools)
    search_text = state.search(QUESTION).text()
    assert tools[0]["result_chars"] == len(search_text)
    assert search_text not in path.read_text(encoding="utf-8")

    end = lines[-1]
    assert set(end) == RUN_KEYS
    assert end["status"] == "done" and end["question"] == QUESTION and end["follow_up"] is False
    assert end["answer"] == job.answer["text"] and end["has_sql"] and end["has_brief"]
    assert end["brief_missing"] is False and end["error_kind"] is None and end["error_message"] is None
    assert end["turns"] == len(turns) and end["tool_calls"] == len(tools)
    assert end["usage"]["output_tokens"] == sum(t["usage"]["output_tokens"] for t in turns)


def _run_with(state, job, observer):
    tools = ToolBox(state, max_sql=8192)
    job.observer = observer
    run_question(job, FakeModel(state, delay=0), tools, walk.system_blocks(tools.pending), Limits())


def test_recording_leaves_the_events_exactly_as_they_were(inputs, tmp_path) -> None:
    state = _state(inputs)
    plain = _run(state, FakeModel(state, delay=0))
    traced = _run(state, FakeModel(state, delay=0), Tracer(tmp_path))

    assert json.dumps(plain.events, ensure_ascii=False) == json.dumps(traced.events, ensure_ascii=False)
    assert plain.answer == traced.answer and plain.status == traced.status == "done"
    assert (tmp_path / "c.jsonl").exists()


def test_a_provider_error_keeps_its_kind_and_the_start_of_its_message(inputs, tmp_path) -> None:
    class Failing:
        name = "failing"

        def turn(self, request, should_stop):
            raise ModelError("bad_request", "prompt is too long: " + "x" * 1000)

    tracer = Tracer(tmp_path)
    job = Run("r1", QUESTION, "问题：上一题", model_id="m")
    job.observer = tracer.observer("c", job)
    tools = ToolBox(_state(inputs), max_sql=8192)
    run_question(job, Failing(), tools, walk.system_blocks(tools.pending), Limits())

    (end,) = _lines(tmp_path / "c.jsonl")
    assert end["kind"] == "run" and end["status"] == "error" and end["error_kind"] == "bad_request"
    assert end["error_message"].startswith("prompt is too long") and len(end["error_message"]) == 300
    assert end["answer"] is None and not end["has_sql"] and not end["has_brief"]
    assert end["follow_up"] is True and end["turns"] == 0


def test_a_write_that_fails_is_logged_and_the_run_goes_on(inputs, tmp_path, caplog) -> None:
    state = _state(inputs)
    tracer = Tracer(tmp_path / "trace")
    (tmp_path / "trace").rmdir()
    (tmp_path / "trace").write_text("not a directory")
    job = Run("r1", QUESTION, None)
    with caplog.at_level(logging.WARNING):
        _run_with(state, job, tracer.observer("c", job))

    assert job.status == "done" and job.answer is not None
    assert "ask trace: could not write" in caplog.text


def test_an_observer_that_raises_never_stops_the_run(inputs, caplog) -> None:
    def broken(item):
        raise RuntimeError("boom")

    job = Run("r1", QUESTION, None)
    with caplog.at_level(logging.WARNING):
        _run_with(_state(inputs), job, broken)

    assert job.status == "done" and "observer failed" in caplog.text


# ------------------------------------------------------------------ through the service and HTTP


class Clock:
    def __call__(self):
        return 1000.0


def _http(httpd, method, path, payload=None):
    import http.client

    host, port = httpd.server_address[:2]
    connection = http.client.HTTPConnection(host, port, timeout=30)
    try:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {} if payload is None else {"Content-Type": "application/json"}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def _conversation_bytes(state, trace):
    """Every response of a two-question conversation, with its ids replaced by placeholders."""
    service = AskService(ToolBox(state, max_sql=8192), FakeModel(state, delay=0), clock=Clock(),
                         trace=trace)
    httpd = make_server(state, host="127.0.0.1", port=0, quiet=True, max_body=8192, ask=service)
    threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True).start()
    try:
        seen, ids = [], []
        conversation = None
        for question in (QUESTION, "再按月分"):
            payload = {"question": question} | ({"conversation": conversation} if conversation else {})
            status, body = _http(httpd, "POST", "/api/ask", payload)
            started = json.loads(body)
            conversation, run = started["conversation"], started["run"]
            ids += [conversation, run]
            seen.append(body)
            done = False
            while not done:
                status, body = _http(httpd, "GET", f"/api/ask/events?conversation={conversation}"
                                                   f"&run={run}&after=0&wait=5")
                done = json.loads(body)["done"]
            seen.append(body)
        seen.append(_http(httpd, "GET", f"/api/ask/conversation?conversation={conversation}")[1])
        seen.append(_http(httpd, "GET", "/api/ask/status")[1])
        seen.append(_http(httpd, "GET", "/api")[1])
    finally:
        httpd.shutdown()
        httpd.server_close()
    text = b"\n".join(seen).decode("utf-8")
    for number, value in enumerate(ids):
        text = text.replace(value, f"<id{number}>")
    return text, conversation


def test_without_a_trace_every_response_is_byte_for_byte_the_same(inputs, tmp_path) -> None:
    state = _state(inputs)
    untraced, _ = _conversation_bytes(state, None)
    assert not list(tmp_path.glob("**/*.jsonl"))
    traced, conversation = _conversation_bytes(state, Tracer(tmp_path / "trace"))

    assert untraced == traced
    lines = _lines(tmp_path / "trace" / f"{conversation}.jsonl")
    ends = [line for line in lines if line["kind"] == "run"]
    assert [end["follow_up"] for end in ends] == [False, True]
    assert [end["question"] for end in ends] == [QUESTION, "再按月分"]


# ------------------------------------------------------------------ the option


def test_the_trace_option_needs_ask(inputs, tmp_path, capsys) -> None:
    code = main(["http", str(inputs["ontology"]), "--ask-trace", str(tmp_path / "t")])

    assert code == 2 and "--ask-trace" in capsys.readouterr().err
    assert not (tmp_path / "t").exists()


def test_the_trace_option_reaches_the_service_and_says_what_it_keeps(inputs, tmp_path) -> None:
    from scope_lineage_service.cli import _ask_service, _parser

    args = _parser().parse_args(["http", str(inputs["ontology"]), "--ask-dev-fake-model",
                                 "--ask-trace", str(tmp_path / "t")])
    service, notice = _ask_service(args, CatalogState(str(inputs["ontology"])))

    assert isinstance(service.trace, Tracer) and (tmp_path / "t").is_dir()
    assert "FAKE MODEL" in notice and "ask trace:" in notice and "answer text" in notice

    args = _parser().parse_args(["http", str(inputs["ontology"]), "--ask-dev-fake-model"])
    service, notice = _ask_service(args, CatalogState(str(inputs["ontology"])))
    assert service.trace is None and "ask trace" not in notice
