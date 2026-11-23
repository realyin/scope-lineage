"""The SDK seam, against a stand-in ``anthropic`` module of the documented shape.

No test here calls the real API or imports the real SDK's network code: ``sdk()`` builds a
module with the classes and methods the seam uses (``Anthropic().messages.stream``,
``.beta.messages.stream``, the typed errors, ``get_final_message().to_dict()``) and records
what the seam passed. This checks the plumbing -- request shape, caching, fallbacks,
cancel, error mapping, credential and version checks -- not the real SDK's behaviour.
"""

from __future__ import annotations

import subprocess
import sys
import types

import pytest
from service_paths import REPO

from scope_lineage_service.ask import anthropic_model
from scope_lineage_service.ask.anthropic_model import (
    AnthropicModel, credential_source, load_model,
)
from scope_lineage_service.ask.loop import Cancelled, InvalidToolInput, ModelError

REQUEST = {
    "system": [{"type": "text", "text": "walk", "cache_control": {"type": "ephemeral"}}],
    "tools": [{"name": "check_sql", "description": "d", "input_schema": {"type": "object"}}],
    "messages": [{"role": "user", "content": [{"type": "text", "text": "问题：x"}]}],
    "max_tokens": 64000,
}
MESSAGE = {
    "content": [{"type": "thinking", "thinking": "", "signature": "sig"},
                {"type": "text", "text": "答"}],
    "stop_reason": "end_turn", "stop_details": None, "model": "claude-opus-5-5",
    "usage": {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 0,
              "cache_read_input_tokens": 900},
}


def sdk(version="1.9.0", events=3, raise_in_stream=None, raise_on_construct=None):
    module = types.ModuleType("anthropic")
    module.__version__ = version
    module.calls = []

    class AnthropicError(Exception):
        pass

    class APIStatusError(AnthropicError):
        def __init__(self, message, status_code=400):
            super().__init__(message)
            self.message, self.status_code = message, status_code

    errors = {"AnthropicError": AnthropicError, "APIStatusError": APIStatusError}
    for name in ("AuthenticationError", "PermissionDeniedError", "NotFoundError",
                 "RateLimitError", "BadRequestError"):
        errors[name] = type(name, (APIStatusError,), {})
    errors["APIConnectionError"] = type("APIConnectionError", (AnthropicError,), {})
    for name, value in errors.items():
        setattr(module, name, value)

    class Final:
        def to_dict(self):
            return MESSAGE

    class Stream:
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            Stream.closed = True
            module.stream = self
            return False

        def __iter__(self):
            for n in range(events):
                if raise_in_stream is not None:
                    raise raise_in_stream
                yield {"type": "event", "n": n}

        def get_final_message(self):
            return Final()

    class Messages:
        def __init__(self, where):
            self.where = where

        def stream(self, **params):
            module.calls.append((self.where, params))
            return Stream()

    class Anthropic:
        def __init__(self, **options):
            if raise_on_construct is not None:
                raise raise_on_construct
            module.client_options = options
            self.messages = Messages("messages")
            self.beta = types.SimpleNamespace(messages=Messages("beta.messages"))

    module.Anthropic = Anthropic
    return module


def model(module, fallback=True, effort="high"):
    return AnthropicModel(module, module.Anthropic(), "claude-opus-5-5", effort,
                          fallback=fallback, source="ANTHROPIC_API_KEY")


def test_the_request_has_the_decided_shape() -> None:
    module = sdk()
    result = model(module).turn(REQUEST, lambda: False)

    where, params = module.calls[0]
    assert where == "beta.messages"
    assert params["model"] == "claude-opus-5-5" and params["max_tokens"] == 64000
    assert params["thinking"] == {"type": "adaptive"}
    assert params["output_config"] == {"effort": "high"}
    assert params["cache_control"] == {"type": "ephemeral"}
    assert params["system"] == REQUEST["system"] and params["messages"] == REQUEST["messages"]
    assert params["betas"] == ["server-side-fallback-2026-07-01"] and params["fallbacks"] == "default"
    assert all(tool["eager_input_streaming"] is True for tool in params["tools"])
    assert "tool_choice" not in params
    assert "eager_input_streaming" not in REQUEST["tools"][0]  # the cached definitions stay put
    assert result == {"content": MESSAGE["content"], "stop_reason": "end_turn",
                      "stop_details": None, "usage": MESSAGE["usage"], "model": "claude-opus-5-5"}


def test_without_fallback_the_plain_messages_api_is_used() -> None:
    module = sdk()
    model(module, fallback=False, effort="medium").turn(REQUEST, lambda: False)

    where, params = module.calls[0]
    assert where == "messages" and "betas" not in params and "fallbacks" not in params
    assert params["output_config"] == {"effort": "medium"}


def test_a_stop_between_events_closes_the_stream() -> None:
    module = sdk(events=5)
    seen = []

    def stop():
        seen.append(1)
        return len(seen) >= 2

    with pytest.raises(Cancelled):
        model(module).turn(REQUEST, stop)
    assert module.stream.closed


@pytest.mark.parametrize(
    ("error", "kind"),
    [("AuthenticationError", "credentials"), ("PermissionDeniedError", "credentials"),
     ("NotFoundError", "not_found"), ("RateLimitError", "rate_limited"),
     ("BadRequestError", "bad_request"), ("APIStatusError", "api_error"),
     ("APIConnectionError", "connection"), ("AnthropicError", "sdk_error")],
)
def test_sdk_errors_become_model_errors(error, kind) -> None:
    template = sdk()
    raised = getattr(template, error)("boom")
    module = sdk(raise_in_stream=raised)
    for name in ("AnthropicError", "APIStatusError", "AuthenticationError", "PermissionDeniedError",
                 "NotFoundError", "RateLimitError", "BadRequestError", "APIConnectionError"):
        setattr(module, name, getattr(template, name))

    with pytest.raises(ModelError) as caught:
        model(module).turn(REQUEST, lambda: False)
    assert caught.value.kind == kind and "boom" in caught.value.message


def test_unparseable_tool_input_is_asked_again() -> None:
    with pytest.raises(InvalidToolInput):
        model(sdk(raise_in_stream=ValueError("bad JSON"))).turn(REQUEST, lambda: False)


# ------------------------------------------------------------------ availability


def test_credentials_are_found_in_the_documented_order_and_never_echoed(tmp_path) -> None:
    assert credential_source({"ANTHROPIC_API_KEY": "secret-value"}, tmp_path) == "ANTHROPIC_API_KEY"
    assert credential_source({"ANTHROPIC_AUTH_TOKEN": "t"}, tmp_path) == "ANTHROPIC_AUTH_TOKEN"
    federation = {"ANTHROPIC_FEDERATION_RULE_ID": "r", "ANTHROPIC_ORGANIZATION_ID": "o",
                  "ANTHROPIC_IDENTITY_TOKEN_FILE": "/token"}
    assert credential_source(federation, tmp_path) == "workload identity federation"
    assert credential_source({}, tmp_path) is None
    (tmp_path / ".config" / "anthropic").mkdir(parents=True)
    (tmp_path / ".config" / "anthropic" / "profile").write_text("x")
    assert credential_source({}, tmp_path) == "an ant auth login profile"


def test_load_model_reports_why_asking_cannot_work(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(anthropic_model.Path, "home", classmethod(lambda cls: tmp_path))

    monkeypatch.setitem(sys.modules, "anthropic", None)
    assert load_model(environ={"ANTHROPIC_API_KEY": "k"}) == (
        None, "the anthropic package is not installed (pip install 'scope-lineage-service[ask]')")

    monkeypatch.setitem(sys.modules, "anthropic", sdk(version="0.49.0"))
    _, reason = load_model(environ={"ANTHROPIC_API_KEY": "k"})
    assert "0.49.0 is older" in reason

    monkeypatch.setitem(sys.modules, "anthropic", sdk())
    _, reason = load_model(environ={})
    assert "no Anthropic credential" in reason

    module = sdk()
    module.Anthropic = sdk(raise_on_construct=module.AnthropicError("no client")).Anthropic
    monkeypatch.setitem(sys.modules, "anthropic", module)
    assert "no client" in load_model(environ={"ANTHROPIC_API_KEY": "k"})[1]

    monkeypatch.setitem(sys.modules, "anthropic", sdk())
    found, reason = load_model("claude-opus-5-5", "xhigh", environ={"ANTHROPIC_API_KEY": "k"})
    assert reason is None and found.effort == "xhigh" and found.source == "ANTHROPIC_API_KEY"


# ------------------------------------------------------------------ one model of several


def spec(**extra):
    from scope_lineage_service.ask.models import parse_models

    item = {"id": "gw", "provider": "anthropic", "model": "claude-opus-5-5", **extra}
    return parse_models({"models": [item]})[0]


def test_a_gateway_model_switches_off_what_the_gateway_rejects(monkeypatch) -> None:
    module = sdk()
    monkeypatch.setitem(sys.modules, "anthropic", module)
    found, reason = anthropic_model.load_spec(
        spec(base_url="https://gateway.example.internal", api_key_env="GATEWAY_KEY", effort=None,
             fallback=False, prompt_cache=False, eager_input_streaming=False,
             adaptive_thinking=False, max_tokens=4096),
        {"GATEWAY_KEY": "gateway-value"})
    assert reason is None and found.max_tokens == 4096
    assert module.client_options == {"base_url": "https://gateway.example.internal",
                                     "api_key": "gateway-value"}
    found.turn(REQUEST, lambda: False)

    where, params = module.calls[0]
    assert where == "messages"
    for name in ("thinking", "output_config", "cache_control", "betas", "fallbacks"):
        assert name not in params, name
    assert all("eager_input_streaming" not in tool for tool in params["tools"])
    assert all("cache_control" not in block for block in params["system"])
    assert REQUEST["system"][0]["cache_control"] == {"type": "ephemeral"}  # the shared prefix stays


def test_a_model_from_the_file_with_defaults_sends_todays_request(monkeypatch) -> None:
    module = sdk()
    monkeypatch.setitem(sys.modules, "anthropic", module)
    found, reason = anthropic_model.load_spec(spec(), {"ANTHROPIC_API_KEY": "k"})
    found.turn(REQUEST, lambda: False)

    assert reason is None and module.client_options == {}
    legacy = model(sdk())
    assert module.calls[0][1] == legacy.params(REQUEST)


def test_a_named_key_variable_must_be_set(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "anthropic", sdk())
    _, reason = anthropic_model.load_spec(spec(api_key_env="GATEWAY_KEY"), {"ANTHROPIC_API_KEY": "k"})

    assert reason == "its API key variable (api_key_env) is not set in the server's environment"


def test_the_service_imports_without_the_sdk() -> None:
    script = (
        "import sys\n"
        "import scope_lineage_service.cli as cli, scope_lineage_service.http_server\n"
        "import scope_lineage_service.ask.service, scope_lineage_service.ask.anthropic_model\n"
        "cli._parser()\n"
        "import scope_lineage_service.ask.models, scope_lineage_service.ask.openai_model\n"
        "assert 'anthropic' not in sys.modules, 'imported the SDK eagerly'\n"
        "assert 'openai' not in sys.modules, 'imported the openai SDK eagerly'\n"
        "sys.modules['anthropic'] = None\n"
        "from scope_lineage_service.ask.anthropic_model import load_model\n"
        "print(load_model()[1])\n"
    )
    path = f"{REPO}:{REPO / 'service'}"
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          env={"PYTHONPATH": path, "PATH": ""}, timeout=60, check=False)

    assert done.returncode == 0, done.stderr
    assert "not installed" in done.stdout
