"""The Anthropic seam with the real ``anthropic`` SDK, against a stand-in Messages API
gateway on this machine (a model's ``base_url``). Skipped when the SDK is not installed.

The stand-in answers ``POST /v1/messages`` with one streamed text turn (server-sent
events in the Messages API's shape) and records the request, so the test sees what a
gateway would receive with the default features and with each one switched off. No real
endpoint is called.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("anthropic")

from scope_lineage_service.ask import anthropic_model  # noqa: E402
from scope_lineage_service.ask.models import parse_models  # noqa: E402

EVENTS = [
    ("message_start", {"type": "message_start", "message": {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": [], "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 1}}}),
    ("content_block_start", {"type": "content_block_start", "index": 0,
                             "content_block": {"type": "text", "text": ""}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0,
                             "delta": {"type": "text_delta", "text": "答案"}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn",
                                                          "stop_sequence": None},
                       "usage": {"output_tokens": 5}}),
    ("message_stop", {"type": "message_stop"}),
]
REQUEST = {
    "system": [{"type": "text", "text": "walk", "cache_control": {"type": "ephemeral"}}],
    "tools": [{"name": "check_sql", "description": "d",
               "input_schema": {"type": "object", "properties": {}}}],
    "messages": [{"role": "user", "content": [{"type": "text", "text": "问题：x"}]}],
    "max_tokens": 4000,
}


@pytest.fixture
def gateway():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append({"path": self.path, "body": body,
                         "headers": {k.lower(): v for k, v in self.headers.items()}})
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for name, data in EVENTS:
                self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True).start()
    host, port = httpd.server_address[:2]
    yield f"http://{host}:{port}", seen
    httpd.shutdown()
    httpd.server_close()


def load(base_url, **extra):
    spec = parse_models({"models": [{"id": "gw", "provider": "anthropic", "model": "claude-opus-5-5",
                                     "base_url": base_url, "api_key_env": "GATEWAY_KEY", **extra}]})[0]
    model, reason = anthropic_model.load_spec(spec, {"GATEWAY_KEY": "gateway-value"})
    assert reason is None, reason
    return model


def test_the_default_request_reaches_the_gateway_with_todays_features(gateway) -> None:
    url, seen = gateway
    result = load(url).turn(REQUEST, lambda: False)

    assert result["content"] == [{"type": "text", "text": "答案"}]
    assert result["stop_reason"] == "end_turn" and result["usage"]["output_tokens"] == 5
    sent = seen[0]
    assert sent["path"].startswith("/v1/messages") and sent["headers"]["x-api-key"] == "gateway-value"
    assert "server-side-fallback-2026-07-01" in sent["headers"].get("anthropic-beta", "")
    body = sent["body"]
    assert body["thinking"] == {"type": "adaptive"} and body["output_config"] == {"effort": "high"}
    assert body["cache_control"] == {"type": "ephemeral"} and body["fallbacks"] == "default"
    assert body["tools"][0]["eager_input_streaming"] is True and body["stream"] is True


def test_every_gateway_feature_can_be_switched_off(gateway) -> None:
    url, seen = gateway
    load(url, effort=None, fallback=False, prompt_cache=False, eager_input_streaming=False,
         adaptive_thinking=False).turn(REQUEST, lambda: False)

    sent = seen[0]
    assert "anthropic-beta" not in sent["headers"] or "fallback" not in sent["headers"]["anthropic-beta"]
    body = sent["body"]
    for name in ("thinking", "output_config", "cache_control", "fallbacks"):
        assert name not in body, name
    assert "eager_input_streaming" not in body["tools"][0]
    assert "cache_control" not in body["system"][0]


def test_a_gateway_without_api_key_env_never_gets_the_ambient_credential(gateway, monkeypatch,
                                                                          tmp_path) -> None:
    url, seen = gateway
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ambient-api-key-value")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "ambient-auth-token-value")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "anthropic").mkdir()
    (tmp_path / "anthropic" / "profile").write_text("x")
    spec = parse_models({"models": [{"id": "gw", "provider": "anthropic", "model": "claude-opus-5-5",
                                     "base_url": url}]})[0]
    model, reason = anthropic_model.load_spec(spec)  # the process environment, as the server sees it
    assert reason is None
    model.turn(REQUEST, lambda: False)

    headers = seen[0]["headers"]
    sent = json.dumps(headers)
    assert "ambient-api-key-value" not in sent and "ambient-auth-token-value" not in sent
    assert "authorization" not in headers
    assert headers["x-api-key"] == anthropic_model.NO_KEY


def test_without_any_credential_a_gateway_model_is_still_available(monkeypatch) -> None:
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    spec = parse_models({"models": [{"id": "gw", "provider": "anthropic", "model": "claude-opus-5-5",
                                     "base_url": "https://gateway.example.internal"}]})[0]

    model, reason = anthropic_model.load_spec(spec, {})
    assert reason is None and model.source == "no key (placeholder)"
