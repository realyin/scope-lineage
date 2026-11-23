"""The OpenAI-compatible seam, against a stand-in chat-completions server on this machine.

The stand-in (standard library only) answers ``POST /v1/chat/completions`` with a scripted
reply per request: a server-sent-event stream of chunks, an HTTP error, or a slow stream
to cancel. It records every request body and its headers. The real ``openai`` SDK talks
to it, so the plumbing -- the translation both ways, streaming, cancel, error mapping --
is exercised end to end, but no real endpoint or model is. Skipped when the SDK is not
installed.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("openai")

from scope_lineage_service.ask import walk  # noqa: E402
from scope_lineage_service.ask.loop import (  # noqa: E402
    Cancelled, InvalidToolInput, Limits, ModelError, Run, run_question,
)
from scope_lineage_service.ask.models import parse_models  # noqa: E402
from scope_lineage_service.ask.openai_model import (  # noqa: E402
    chat_messages, chat_tools, load_spec,
)
from scope_lineage_service.ask.tools import ToolBox  # noqa: E402
from scope_lineage_service.state import CatalogState  # noqa: E402

REQUEST = {
    "system": [{"type": "text", "text": "walk part 1"},
               {"type": "text", "text": "walk part 2", "cache_control": {"type": "ephemeral"}}],
    "tools": [{"name": "check_sql", "description": "Check a SQL",
               "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}},
                                "required": ["sql"]}}],
    "messages": [{"role": "user", "content": [{"type": "text", "text": "问题：x"}]}],
    "max_tokens": 4000,
}
USAGE = {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150,
         "prompt_tokens_details": {"cached_tokens": 100}}


def chunk(delta=None, finish=None, usage=None, choices=True):
    body = {"id": "c1", "object": "chat.completion.chunk", "created": 0, "model": "example-model",
            "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}] if choices else []}
    if usage is not None:
        body["usage"] = usage
    return body


def call_delta(index, *, id_=None, name=None, arguments=None):
    function = {}
    if name is not None:
        function["name"] = name
    if arguments is not None:
        function["arguments"] = arguments
    item = {"index": index, "function": function}
    if id_ is not None:
        item.update(id=id_, type="function")
    return {"tool_calls": [item]}


def stream(*chunks, delay=0.0):
    return {"kind": "stream", "chunks": list(chunks), "delay": delay}


def status(code, message="refused"):
    return {"kind": "status", "code": code,
            "body": {"error": {"message": message, "type": "invalid_request_error"}}}


class StandIn:
    def __init__(self):
        self.replies, self.requests = [], []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                owner.requests.append({"path": self.path, "body": body,
                                       "headers": {k.lower(): v for k, v in self.headers.items()}})
                reply = owner.replies.pop(0) if owner.replies else status(500, "nothing scripted")
                if callable(reply):
                    reply = reply(body)
                if reply["kind"] == "status":
                    data = json.dumps(reply["body"]).encode()
                    self.send_response(reply["code"])
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                try:
                    for item in reply["chunks"]:
                        self.wfile.write(f"data: {json.dumps(item)}\n\n".encode())
                        self.wfile.flush()
                        if reply["delay"]:
                            time.sleep(reply["delay"])
                    self.wfile.write(b"data: [DONE]\n\n")
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, args=(0.05,), daemon=True).start()

    @property
    def base_url(self):
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}/v1"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    standin = StandIn()
    yield standin
    standin.close()


def spec(base_url, **extra):
    item = {"id": "private", "provider": "openai-compatible", "model": "example-model",
            "base_url": base_url, "api_key_env": "TEST_MODEL_KEY", **extra}
    return parse_models({"models": [item]})[0]


def model(server, **extra):
    found, reason = load_spec(spec(server.base_url, **extra), {"TEST_MODEL_KEY": "test-value"},
                              max_retries=0)
    assert reason is None, reason
    return found


# ------------------------------------------------------------------ the request


def test_a_streamed_text_answer_and_the_request_it_came_from(server) -> None:
    server.replies.append(stream(chunk({"role": "assistant", "content": "答"}), chunk({"content": "案"}),
                                 chunk(finish="stop"), chunk(usage=USAGE, choices=False)))
    result = model(server).turn(REQUEST, lambda: False)

    assert result == {
        "content": [{"type": "text", "text": "答案"}], "stop_reason": "end_turn",
        "stop_details": None, "model": "example-model",
        "usage": {"input_tokens": 20, "output_tokens": 30, "cache_creation_input_tokens": 0,
                  "cache_read_input_tokens": 100},
    }
    sent = server.requests[0]
    assert sent["path"] == "/v1/chat/completions"
    assert sent["headers"]["authorization"] == "Bearer test-value"
    body = sent["body"]
    assert body["model"] == "example-model" and body["stream"] is True
    assert body["stream_options"] == {"include_usage": True} and body["max_tokens"] == 4000
    assert body["messages"] == [{"role": "system", "content": "walk part 1\n\nwalk part 2"},
                                {"role": "user", "content": "问题：x"}]
    assert body["tools"] == [{"type": "function", "function": {
        "name": "check_sql", "description": "Check a SQL",
        "parameters": REQUEST["tools"][0]["input_schema"]}}]
    assert "reasoning_effort" not in body and "tool_choice" not in body


def test_the_output_field_and_effort_follow_the_config(server) -> None:
    server.replies.append(stream(chunk({"content": "x"}, finish="stop")))
    model(server, max_tokens_field="max_completion_tokens", effort="low").turn(REQUEST, lambda: False)

    body = server.requests[0]["body"]
    assert body["max_completion_tokens"] == 4000 and "max_tokens" not in body
    assert body["reasoning_effort"] == "low"


def test_without_api_key_env_no_key_from_the_environment_is_sent(server, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leave")
    item = spec(server.base_url)
    keyless = parse_models({"models": [{k: v for k, v in item.__dict__.items()
                                        if k in ("id", "provider", "model", "base_url")}]})[0]
    found, reason = load_spec(keyless, {}, max_retries=0)
    server.replies.append(stream(chunk({"content": "x"}, finish="stop")))
    found.turn(REQUEST, lambda: False)

    assert reason is None
    assert "must-not-leave" not in server.requests[0]["headers"].get("authorization", "")


# ------------------------------------------------------------------ tool calls


def test_split_argument_deltas_and_two_calls_in_one_turn(server) -> None:
    server.replies.append(stream(
        chunk({"role": "assistant", "content": "查两处。"}),
        chunk(call_delta(0, id_="call_a", name="check_sql", arguments='{"sq')),
        chunk(call_delta(0, arguments='l": "SELECT')),
        chunk(call_delta(1, id_="call_b", name="search_catalog", arguments="")),
        chunk(call_delta(0, arguments=' 1"}')),
        chunk(call_delta(1, arguments='{"text": "客户"}')),
        chunk(finish="tool_calls"), chunk(usage=USAGE, choices=False)))
    result = model(server).turn(REQUEST, lambda: False)

    assert result["stop_reason"] == "tool_use"
    assert result["content"] == [
        {"type": "text", "text": "查两处。"},
        {"type": "tool_use", "id": "call_a", "name": "check_sql", "input": {"sql": "SELECT 1"}},
        {"type": "tool_use", "id": "call_b", "name": "search_catalog", "input": {"text": "客户"}},
    ]


def test_tool_calls_under_a_stop_finish_are_still_calls(server) -> None:
    server.replies.append(stream(chunk(call_delta(0, name="check_sql", arguments="")),
                                 chunk(finish="stop")))
    result = model(server).turn(REQUEST, lambda: False)

    assert result["stop_reason"] == "tool_use"
    assert result["content"] == [{"type": "tool_use", "id": "call_0", "name": "check_sql",
                                  "input": {}}]


@pytest.mark.parametrize("arguments", ['{"sql": "SELECT', "[1, 2]"])
def test_arguments_that_are_not_a_json_object_are_asked_again(server, arguments) -> None:
    server.replies.append(stream(chunk(call_delta(0, id_="c", name="check_sql", arguments=arguments)),
                                 chunk(finish="tool_calls")))
    with pytest.raises(InvalidToolInput):
        model(server).turn(REQUEST, lambda: False)


# ------------------------------------------------------------------ stops and usage


def test_length_is_max_tokens_and_a_cut_call_is_dropped(server) -> None:
    server.replies.append(stream(chunk({"content": "写到一半"}),
                                 chunk(call_delta(0, id_="c", name="check_sql", arguments='{"sq')),
                                 chunk(finish="length")))
    result = model(server).turn(REQUEST, lambda: False)

    assert result["stop_reason"] == "max_tokens"
    assert result["content"] == [{"type": "text", "text": "写到一半"}]


def test_a_content_filter_stop_reads_as_a_refusal(server) -> None:
    server.replies.append(stream(chunk({"content": ""}), chunk(finish="content_filter")))
    result = model(server).turn(REQUEST, lambda: False)

    assert result["stop_reason"] == "refusal"
    assert result["stop_details"]["category"] == "content_filter"
    assert result["stop_details"]["explanation"]


def test_a_refusal_delta_reads_as_a_refusal(server) -> None:
    server.replies.append(stream(chunk({"refusal": "不能回答"}), chunk(finish="stop")))
    result = model(server).turn(REQUEST, lambda: False)

    assert result["stop_reason"] == "refusal"
    assert result["stop_details"]["explanation"] == "不能回答"


def test_missing_usage_is_estimated_and_says_so(server) -> None:
    server.replies.append(stream(chunk({"content": "答案" * 30}), chunk(finish="stop")))
    result = model(server).turn(REQUEST, lambda: False)

    assert result["usage_estimated"] is True
    assert result["usage"]["output_tokens"] > 0 and result["usage"]["input_tokens"] > 0


def test_an_endpoint_that_refuses_stream_options_is_asked_again_without_them(server) -> None:
    def picky(body):
        if "stream_options" in body:
            return status(400, "Unrecognized request argument supplied: stream_options")
        return stream(chunk({"content": "ok"}, finish="stop"))

    server.replies += [picky, picky, picky]
    seam = model(server)
    first = seam.turn(REQUEST, lambda: False)
    seam.turn(REQUEST, lambda: False)

    assert first["content"] == [{"type": "text", "text": "ok"}] and first["usage_estimated"]
    sent = [("stream_options" in item["body"]) for item in server.requests]
    assert sent == [True, False, False]  # remembered for the next turn


def test_a_stream_that_ends_without_a_finish_reason_is_an_error(server) -> None:
    server.replies.append(stream(chunk({"content": "半"})))
    with pytest.raises(ModelError) as caught:
        model(server).turn(REQUEST, lambda: False)
    assert caught.value.kind == "api_error"


# ------------------------------------------------------------------ errors and cancel


@pytest.mark.parametrize(
    ("code", "kind"),
    [(401, "credentials"), (403, "credentials"), (404, "not_found"), (429, "rate_limited"),
     (400, "bad_request"), (500, "api_error")],
)
def test_http_errors_become_model_errors(server, code, kind) -> None:
    server.replies.append(status(code, "the endpoint said no"))
    with pytest.raises(ModelError) as caught:
        model(server).turn(REQUEST, lambda: False)

    assert caught.value.kind == kind and "the endpoint said no" in caught.value.message


def test_a_connection_failure_is_a_connection_error() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    found, _ = load_spec(spec(f"http://127.0.0.1:{port}/v1"), {"TEST_MODEL_KEY": "v"}, max_retries=0)
    with pytest.raises(ModelError) as caught:
        found.turn(REQUEST, lambda: False)

    assert caught.value.kind == "connection"


def test_a_cancel_mid_stream_stops_the_turn(server) -> None:
    server.replies.append(stream(*[chunk({"content": "字"}) for _ in range(50)], chunk(finish="stop"),
                                 delay=0.1))
    seen = []

    def stop():
        seen.append(1)
        return len(seen) > 3

    started = time.monotonic()
    with pytest.raises(Cancelled):
        model(server).turn(REQUEST, stop)
    assert time.monotonic() - started < 3


# ------------------------------------------------------------------ translation


def test_a_conversation_translates_to_chat_messages() -> None:
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "问题：x"}]},
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "", "signature": "s"},
            {"type": "text", "text": "查。"},
            {"type": "tool_use", "id": "t1", "name": "check_sql", "input": {"sql": "SELECT '中'"}},
            {"type": "tool_use", "id": "t2", "name": "search_catalog", "input": {"text": "y"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
            {"type": "tool_result", "tool_use_id": "t2", "content": "no such table", "is_error": True},
            {"type": "text", "text": "补充"}]},
    ]
    chat = chat_messages([{"type": "text", "text": "S"}], messages)

    assert chat == [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "问题：x"},
        {"role": "assistant", "content": "查。", "tool_calls": [
            {"id": "t1", "type": "function",
             "function": {"name": "check_sql", "arguments": '{"sql": "SELECT \'中\'"}'}},
            {"id": "t2", "type": "function",
             "function": {"name": "search_catalog", "arguments": '{"text": "y"}'}}]},
        {"role": "tool", "tool_call_id": "t1", "content": "ok"},
        {"role": "tool", "tool_call_id": "t2", "content": "[error] no such table"},
        {"role": "user", "content": "补充"},
    ]
    assert chat_tools(REQUEST["tools"])[0]["function"]["name"] == "check_sql"


def test_an_assistant_turn_of_only_calls_has_null_content() -> None:
    chat = chat_messages([], [{"role": "assistant", "content": [
        {"type": "tool_use", "id": "t", "name": "n", "input": {}}]}])

    assert chat == [{"role": "assistant", "content": None, "tool_calls": [
        {"id": "t", "type": "function", "function": {"name": "n", "arguments": "{}"}}]}]


# ------------------------------------------------------------------ availability


def test_load_spec_reports_why_a_model_cannot_work(monkeypatch) -> None:
    item = spec("https://models.example.internal/v1")
    _, reason = load_spec(item, {})
    assert reason == "its API key variable (api_key_env) is not set in the server's environment"
    assert "TEST_MODEL_KEY" not in reason

    monkeypatch.setitem(sys.modules, "openai", None)
    _, reason = load_spec(item, {"TEST_MODEL_KEY": "v"})
    assert reason == ("the openai package is not installed "
                      "(pip install 'scope-lineage-service[ask-openai]')")


# ------------------------------------------------------------------ through the loop


def test_the_loop_runs_tools_through_the_adapter_and_respects_the_model_limit(server, inputs) -> None:
    state = CatalogState(str(inputs["ontology"]), semantics=str(inputs["semantics"]))
    tools = ToolBox(state, max_sql=8192)
    server.replies += [
        stream(chunk(call_delta(0, id_="c1", name="search_catalog", arguments='{"text": "客户"}')),
               chunk(finish="tool_calls"), chunk(usage=USAGE, choices=False)),
        stream(chunk({"content": "答：见上。"}), chunk(finish="stop"),
               chunk(usage=USAGE, choices=False)),
    ]
    run = Run("r", "客户数", model_id="private", model_label="Private")
    run_question(run, model(server, max_tokens=2048), tools, walk.system_blocks(False), Limits())

    assert run.status == "done"
    assert [e["name"] for e in run.events if e["type"] == "tool_call"] == ["search_catalog"]
    assert all(item["body"]["max_tokens"] == 2048 for item in server.requests)
    second = server.requests[1]["body"]["messages"]
    assert [m["role"] for m in second[1:]] == ["user", "assistant", "tool"]
    assert run.events[0]["model_id"] == "private" and run.events[-1]["model_id"] == "private"
