"""The ask endpoints: opt-in, same-origin JSON POSTs, polling, conversation bounds, fill-in.

The model behind them is the development fake (``FakeModel`` with no delay), which makes
real catalog tool calls and no network call.
"""

from __future__ import annotations

import http.client
import json
import threading
import time
from urllib.parse import urlencode

import pytest

from scope_lineage_service.ask.fake_model import FakeModel
from scope_lineage_service.ask.loop import Limits
from scope_lineage_service.ask.service import AskError, AskService
from scope_lineage_service.ask.tools import ToolBox
from scope_lineage_service.http_server import make_server
from scope_lineage_service.state import CatalogState


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _serve(state, ask):
    httpd = make_server(state, host="127.0.0.1", port=0, quiet=True, max_body=8192, ask=ask)
    thread = threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    return httpd


def _service(state, **options):
    return AskService(ToolBox(state, max_sql=8192), FakeModel(state, delay=0), **options)


@pytest.fixture
def pending_state(inputs):
    return CatalogState(str(inputs["ontology"]), semantics=str(inputs["semantics"]),
                        pending=str(inputs["pending"]))


@pytest.fixture
def server(pending_state):
    httpd = _serve(pending_state, _service(pending_state))
    yield httpd
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def no_pending_server(inputs):
    state = CatalogState(str(inputs["ontology"]), semantics=str(inputs["semantics"]))
    httpd = _serve(state, _service(state))
    yield httpd
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def off_server(pending_state):
    httpd = _serve(pending_state, None)
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def _request(httpd, method, path, body=None, headers=None):
    host, port = httpd.server_address[:2]
    connection = http.client.HTTPConnection(host, port, timeout=30)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def _origin(httpd):
    host, port = httpd.server_address[:2]
    return f"{host}:{port}"


def _post(httpd, path, payload, **headers):
    sent = {"Content-Type": "application/json", **headers}
    status, _, body = _request(httpd, "POST", path, json.dumps(payload).encode("utf-8"), sent)
    return status, json.loads(body)


def _get(httpd, path, **params):
    status, _, body = _request(httpd, "GET", f"{path}?{urlencode(params)}" if params else path)
    return status, json.loads(body)


def _until_done(httpd, conversation, run):
    events, after = [], 0
    for _ in range(50):
        status, page = _get(httpd, "/api/ask/events", conversation=conversation, run=run,
                            after=after, wait=5)
        assert status == 200
        events += page["events"]
        after = page["next"]
        if page["done"]:
            return events
    raise AssertionError("the run did not finish")


def _ask(httpd, question, conversation=None):
    payload = {"question": question} | ({"conversation": conversation} if conversation else {})
    status, body = _post(httpd, "/api/ask", payload)
    assert status == 202, body
    return body


# ------------------------------------------------------------------ opt-in


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/api/ask/status"), ("POST", "/api/ask"), ("GET", "/api/ask/events"),
     ("POST", "/api/ask/cancel"), ("GET", "/api/ask/conversation")],
)
def test_without_ask_the_endpoints_answer_not_configured(off_server, method, path) -> None:
    body = b"{}" if method == "POST" else None
    headers = {"Content-Type": "application/json"} if method == "POST" else {}
    status, _, answer = _request(off_server, method, path, body, headers)

    error = json.loads(answer)["error"]
    assert status == 404 and error["kind"] == "not_configured"
    assert "--ask" in error["message"] and "costs money" in error["message"]


def test_the_endpoint_list_names_ask_only_when_enabled(server, off_server) -> None:
    def paths(httpd):
        return {item["path"] for item in _get(httpd, "/api")[1]["endpoints"]}

    assert {"/api/ask", "/api/ask/events", "/api/ask/status"} <= paths(server)
    assert not {p for p in paths(off_server) if p.startswith("/api/ask")}
    assert _get(server, "/api")[1]["asks_a_model"] is True


def test_status_says_what_runs_and_its_limits(server) -> None:
    status, body = _get(server, "/api/ask/status")

    assert status == 200 and body["available"] and body["fake"]
    assert body["model"] == "dev-fake-model" and body["pending"] is True
    assert body["executes_sql"] is False and body["limits"]["max_turns"] == Limits().max_turns
    assert body["conversations"]["kept_in_memory"] is True


def test_an_unavailable_model_is_reported_and_asking_refused(pending_state) -> None:
    service = AskService(ToolBox(pending_state, max_sql=8192), None,
                         reason="no Anthropic credential in the server's environment")
    httpd = _serve(pending_state, service)
    try:
        status, body = _get(httpd, "/api/ask/status")
        assert status == 200 and not body["available"] and "credential" in body["reason"]
        status, body = _post(httpd, "/api/ask", {"question": "客户数"})
        assert status == 503 and body["error"]["kind"] == "ask_unavailable"
        assert _get(httpd, "/api/browse")[0] == 200
    finally:
        httpd.shutdown()
        httpd.server_close()


# ------------------------------------------------------------------ asking


def test_a_question_runs_and_its_events_are_polled_to_the_answer(server) -> None:
    started = _ask(server, "客户数")
    events = _until_done(server, started["conversation"], started["run"])

    kinds = [event["type"] for event in events]
    assert kinds[0] == "started" and kinds[-1] == "finished"
    assert events[-1]["status"] == "done"
    names = [event["name"] for event in events if event["type"] == "tool_call"]
    assert names == ["search_catalog", "query_catalog", "search_catalog", "catalog_context",
                     "check_sql"]
    answer = next(event for event in events if event["type"] == "answer")
    assert answer["sql"] and answer["placeholders"]
    assert "开发用假模型" in answer["text"]


def test_a_follow_up_carries_the_brief(server) -> None:
    first = _ask(server, "客户数")
    _until_done(server, first["conversation"], first["run"])
    second = _ask(server, "换成按性别分", first["conversation"])
    events = _until_done(server, second["conversation"], second["run"])

    assert second["follow_up"] is True and events[0]["follow_up"] is True
    status, conversation = _get(server, "/api/ask/conversation", conversation=first["conversation"])
    assert status == 200 and [r["question"] for r in conversation["runs"]] == ["客户数", "换成按性别分"]
    assert conversation["brief"].startswith("问题：换成按性别分")


def test_one_question_at_a_time_and_cancel(pending_state) -> None:
    state = pending_state
    service = AskService(ToolBox(state, max_sql=8192), FakeModel(state, delay=2.0))
    httpd = _serve(state, service)
    try:
        started = _ask(httpd, "客户数")
        status, body = _post(httpd, "/api/ask", {"question": "再问", "conversation": started["conversation"]})
        assert status == 409 and body["error"]["kind"] == "busy"
        status, body = _post(httpd, "/api/ask/cancel", {"conversation": started["conversation"]})
        assert status == 200 and body["cancelled"] == started["run"]
        events = _until_done(httpd, started["conversation"], started["run"])
        assert events[-1]["status"] == "cancelled"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_events_wait_for_the_next_one(server) -> None:
    started = _ask(server, "客户数")
    before = time.monotonic()
    status, page = _get(server, "/api/ask/events", conversation=started["conversation"],
                        run=started["run"], after=0, wait=5)

    assert status == 200 and page["events"] and page["events"][0]["seq"] == 1
    assert time.monotonic() - before < 5
    _until_done(server, started["conversation"], started["run"])


# ------------------------------------------------------------------ refusals


def test_posts_from_another_origin_are_refused(server, inputs) -> None:
    other_port = "127.0.0.1:1"
    for headers in ({"Origin": f"http://{other_port}"}, {"Sec-Fetch-Site": "cross-site"},
                    {"Sec-Fetch-Site": "same-site"}, {"Origin": "null"}):
        status, body = _post(server, "/api/ask", {"question": "客户数"}, **headers)
        assert status == 403 and body["error"]["kind"] == "forbidden_origin", headers
        status, _ = _post(server, "/api/pending", {"question": "q", "missing": "m"}, **headers)
        assert status == 403
    assert not inputs["pending"].exists()
    same = {"Origin": f"http://{_origin(server)}", "Sec-Fetch-Site": "same-origin"}
    status, body = _post(server, "/api/ask", {"question": "客户数"}, **same)
    assert status == 202
    _until_done(server, body["conversation"], body["run"])


@pytest.mark.parametrize(
    ("body", "content_type", "status"),
    [
        (b"question=x", "application/x-www-form-urlencoded", 415),
        (b"question=x", "text/plain", 415),
        (b"[1]", "application/json", 400),
        (b'{"question": "x", "model": "other"}', "application/json", 400),
        (b'{"question": 3}', "application/json", 400),
        (b'{"conversation": "x"}', "application/json", 400),
        (b'{"question": "   "}', "application/json", 400),
        (json.dumps({"question": "x" * 4001}).encode(), "application/json", 400),
    ],
)
def test_ask_takes_only_a_json_question(server, body, content_type, status) -> None:
    got, _, _ = _request(server, "POST", "/api/ask", body, {"Content-Type": content_type})

    assert got == status


@pytest.mark.parametrize(
    "params",
    [{"conversation": "c", "run": "r", "file": "/etc"}, {"conversation": "c"},
     {"conversation": "c", "run": "r", "wait": "99"}, {"conversation": "c", "run": "r", "after": "-1"}],
)
def test_events_refuse_unknown_or_bad_parameters(server, params) -> None:
    assert _get(server, "/api/ask/events", **params)[0] == 400


def test_an_unknown_conversation_says_it_is_gone(server) -> None:
    status, body = _get(server, "/api/ask/events", conversation="nope", run="r")

    assert status == 404 and body["error"]["kind"] == "conversation_gone"
    assert "restarted" in body["error"]["message"]
    status, body = _post(server, "/api/ask", {"question": "客户数", "conversation": "nope"})
    assert status == 404


def test_conversations_are_bounded_by_count_and_age(pending_state) -> None:
    clock = Clock()
    service = _service(pending_state, max_conversations=2, max_idle_seconds=60, clock=clock)
    ids = []
    for question in ("一", "二"):
        conversation, run = service.ask(question)
        _wait(run)
        ids.append(conversation.id)
        clock.now += 1
    third, run = service.ask("三")
    _wait(run)
    assert set(service._conversations) == {ids[1], third.id}  # the least recently used went

    clock.now += 61
    with pytest.raises(AskError) as gone:
        service.conversation(third.id)
    assert gone.value.kind == "conversation_gone" and not service._conversations


def _wait(run):
    for _ in range(200):
        if run.done:
            return
        time.sleep(0.01)
    raise AssertionError("run did not finish")


def test_ids_are_unguessable(pending_state) -> None:
    service = _service(pending_state)
    conversation, run = service.ask("客户数")
    _wait(run)

    assert len(conversation.id) >= 32 and len(run.id) >= 16


# ------------------------------------------------------------------ the placeholder fill-in


def test_a_placeholder_definition_is_appended_through_pending_add(server, inputs) -> None:
    started = _ask(server, "客户数")
    events = _until_done(server, started["conversation"], started["run"])
    placeholder = next(e for e in events if e["type"] == "answer")["placeholders"][0]
    request = {
        "question": "客户数", "missing": placeholder["text"], "proposed": "只算 F 和 M",
        "tables": [placeholder["table"]],
        "columns": [f"{placeholder['table']}.{placeholder['column']}"],
    }
    status, body = _post(server, "/api/pending", request,
                         Origin=f"http://{_origin(server)}", **{"Sec-Fetch-Site": "same-origin"})

    assert status == 201 and body["appended"] == 1
    line = json.loads(inputs["pending"].read_text("utf-8"))
    assert line["missing"] == placeholder["text"] and line["proposed"] == "只算 F 和 M"


def test_without_pending_the_fill_in_is_not_configured(no_pending_server) -> None:
    assert _get(no_pending_server, "/api/ask/status")[1]["pending"] is False
    status, body = _post(no_pending_server, "/api/pending", {"question": "q", "missing": "m"})

    assert status == 404 and body["error"]["kind"] == "not_configured"


def test_the_ask_page_files_are_served(server) -> None:
    for path in ("/ask.js", "/askview.js"):
        status, headers, _ = _request(server, "GET", path)
        assert status == 200 and headers["Content-Type"].startswith("text/javascript")
