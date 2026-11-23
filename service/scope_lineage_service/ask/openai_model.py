"""The model seam over any endpoint that speaks the OpenAI Chat Completions API with tool
calls: the only module that imports the official ``openai`` SDK (lazily, in ``load_spec``).

The loop keeps its Anthropic-shaped request and turn; this module translates at the seam.

Request: the system blocks become one ``system`` message (their ``cache_control`` marks
are dropped: there is no prompt caching on this path); a user turn's ``tool_result``
blocks become ``tool`` messages (a failed one prefixed ``[error]``) followed by its text
as a ``user`` message; an assistant turn's text and ``tool_use`` blocks become one
``assistant`` message with ``tool_calls`` (thinking and fallback blocks are dropped); the
tool definitions become ``function`` tools. ``max_tokens`` (or ``max_completion_tokens``)
is the loop's per-turn limit, already held under the model's configured ``max_tokens``;
``effort``, when configured, is sent as ``reasoning_effort``. No ``tool_choice``.

Reply: one streamed request per turn, so a cancel or the wall clock closes it between
chunks. Text deltas, refusal deltas and tool-call deltas (arguments arrive in pieces,
keyed by index; two calls may interleave) are put back together. ``finish_reason``
``tool_calls`` (or any finish with calls) is ``tool_use``, ``stop`` is ``end_turn``,
``length`` is ``max_tokens`` (a cut call is dropped), ``content_filter`` or a refusal
delta is ``refusal``. Arguments that are not a JSON object raise ``InvalidToolInput`` (the
loop asks again). Usage comes from the final chunk (``stream_options.include_usage``);
an endpoint that rejects ``stream_options`` is asked again without it, once, and that is
remembered; when no usage arrives, the counts are estimated from text lengths and the
turn says so (``usage_estimated``), so the output-token cap still bounds the question.

The key is read from the environment variable the models file names (``api_key_env``)
and given to the client explicitly; without one, a placeholder is sent, never a key the
SDK would otherwise pick up from ``OPENAI_API_KEY``.
"""

from __future__ import annotations

import json
import math
import os
from typing import Callable

from .loop import Cancelled, InvalidToolInput, ModelError

MIN_SDK = (1, 40, 0)
SDK_RANGE = ">=1.40,<3"
INSTALL_HINT = "pip install 'scope-lineage-service[ask-openai]'"
NO_KEY = "not-needed"
DEFAULT_MAX_TOKENS = 8192


def load_spec(spec, environ=None, *, max_retries: int = 2):
    """``(OpenAICompatibleModel, None)`` when the model can work, else ``(None, reason)``.
    The reason never names the variable or the URL (it is shown on the page)."""
    environ = os.environ if environ is None else environ
    try:
        import openai
    except ImportError:
        return None, f"the openai package is not installed ({INSTALL_HINT})"
    version = getattr(openai, "__version__", "0")
    if _version(version) < MIN_SDK:
        return None, f"openai {version} is older than this service needs ({SDK_RANGE}); {INSTALL_HINT}"
    key = NO_KEY
    if spec.api_key_env:
        key = environ.get(spec.api_key_env) or ""
        if not key:
            return None, "its API key variable (api_key_env) is not set in the server's environment"
    try:
        client = openai.OpenAI(base_url=spec.base_url, api_key=key, max_retries=max_retries)
    except openai.OpenAIError as error:
        return None, f"the openai client could not start: {error}"
    return OpenAICompatibleModel(openai, client, spec), None


def _version(text: str) -> tuple[int, ...]:
    parts = []
    for piece in text.split(".")[:3]:
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts)


# ------------------------------------------------------------------ translation


def chat_messages(system, messages: list) -> list:
    out = []
    if isinstance(system, str):
        system_text = system
    else:
        system_text = "\n\n".join(b.get("text", "") for b in system or [] if b.get("type") == "text")
    if system_text:
        out.append({"role": "system", "content": system_text})
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            out.append({"role": message["role"], "content": content})
        elif message["role"] == "assistant":
            text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
            calls = [{"id": b["id"], "type": "function",
                      "function": {"name": b["name"],
                                   "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False)}}
                     for b in content if b.get("type") == "tool_use"]
            if not text and not calls:
                continue
            item = {"role": "assistant", "content": text or None}
            if calls:
                item["tool_calls"] = calls
            out.append(item)
        else:
            for block in content:
                if block.get("type") == "tool_result":
                    out.append({"role": "tool", "tool_call_id": block["tool_use_id"],
                                "content": _result_text(block)})
            texts = [b.get("text", "") for b in content if b.get("type") == "text"]
            if texts:
                out.append({"role": "user", "content": "\n\n".join(texts)})
    return out


def _result_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if part.get("type") == "text")
    text = str(content or "")
    return f"[error] {text}" if block.get("is_error") else text


def chat_tools(tools: list) -> list:
    return [{"type": "function", "function": {
        "name": tool["name"], "description": tool.get("description", ""),
        "parameters": tool.get("input_schema") or {"type": "object"}}} for tool in tools]


# ------------------------------------------------------------------ the seam


class OpenAICompatibleModel:
    """One streamed chat-completions request per turn (see the module docstring)."""

    fake = False
    provider = "openai-compatible"
    fallback = False

    def __init__(self, sdk, client, spec) -> None:
        self._sdk, self._client = sdk, client
        self.name = spec.model
        self.effort = spec.effort
        self.max_tokens = spec.max_tokens or DEFAULT_MAX_TOKENS
        self.max_tokens_field = spec.max_tokens_field
        self.stream_usage = spec.stream_usage
        self.source = spec.api_key_env or "no key"

    def params(self, request: dict) -> dict:
        params = {
            "model": self.name,
            "messages": chat_messages(request["system"], request["messages"]),
            "tools": chat_tools(request["tools"]),
            "stream": True,
            self.max_tokens_field: min(request["max_tokens"], self.max_tokens),
        }
        if self.stream_usage:
            params["stream_options"] = {"include_usage": True}
        if self.effort:
            params["reasoning_effort"] = self.effort
        return params

    def turn(self, request: dict, should_stop: Callable[[], bool]) -> dict:
        sdk = self._sdk
        try:
            try:
                return self._turn(request, should_stop)
            except sdk.BadRequestError as error:
                if not self.stream_usage or "stream_options" not in _say(error):
                    raise
                self.stream_usage = False  # this endpoint does not take it: ask again without
                return self._turn(request, should_stop)
        except (Cancelled, InvalidToolInput, ModelError):
            raise
        except (sdk.AuthenticationError, sdk.PermissionDeniedError) as error:
            raise ModelError("credentials", _say(error)) from None
        except sdk.NotFoundError as error:
            raise ModelError("not_found", _say(error)) from None
        except sdk.RateLimitError as error:
            raise ModelError("rate_limited", _say(error)) from None
        except sdk.BadRequestError as error:
            raise ModelError("bad_request", _say(error)) from None
        except sdk.APIStatusError as error:
            raise ModelError("api_error", f"HTTP {error.status_code}: {_say(error)}") from None
        except sdk.APIConnectionError as error:
            raise ModelError("connection", _say(error)) from None
        except sdk.OpenAIError as error:
            raise ModelError("sdk_error", _say(error)) from None

    def _turn(self, request: dict, should_stop: Callable[[], bool]) -> dict:
        if should_stop():
            raise Cancelled()
        params = self.params(request)
        text, refusal, calls = [], [], {}
        finish = usage = model = None
        with self._client.chat.completions.create(**params) as stream:
            for chunk in stream:
                if should_stop():
                    raise Cancelled()
                model = getattr(chunk, "model", None) or model
                if getattr(chunk, "usage", None) is not None:
                    usage = chunk.usage
                for choice in getattr(chunk, "choices", None) or []:
                    if getattr(choice, "index", 0) != 0:
                        continue
                    delta = choice.delta
                    if delta is not None:
                        if delta.content:
                            text.append(delta.content)
                        if getattr(delta, "refusal", None):
                            refusal.append(delta.refusal)
                        for piece in delta.tool_calls or []:
                            call = calls.setdefault(piece.index, {"id": None, "name": "", "args": []})
                            if piece.id:
                                call["id"] = piece.id
                            if piece.function is not None:
                                if piece.function.name:
                                    call["name"] += piece.function.name
                                if piece.function.arguments:
                                    call["args"].append(piece.function.arguments)
                    if choice.finish_reason:
                        finish = choice.finish_reason
        if finish is None:
            raise ModelError("api_error", "the endpoint's stream ended without a finish reason")
        return self._result(request, "".join(text), "".join(refusal), calls, finish, usage, model)

    def _result(self, request, text, refusal, calls, finish, usage, model) -> dict:
        content = [{"type": "text", "text": text}] if text else []
        details = None
        if finish == "length":
            stop = "max_tokens"  # a cut call may not parse: it is not run anyway
        elif finish == "content_filter" or refusal:
            stop = "refusal"
            details = {"type": "refusal", "category": "content_filter" if finish == "content_filter"
                       else None,
                       "explanation": refusal or "the endpoint's content filter stopped the reply"}
        else:
            content += [self._tool_use(index, calls[index]) for index in sorted(calls)]
            stop = "tool_use" if calls else "end_turn"
        result = {"content": content, "stop_reason": stop, "stop_details": details,
                  "usage": _usage(usage), "model": model or self.name}
        if usage is None:
            result["usage"] = self._estimate(request, text, calls)
            result["usage_estimated"] = True
        return result

    @staticmethod
    def _tool_use(index: int, call: dict) -> dict:
        if not call["name"]:
            raise InvalidToolInput(f"tool call {index} has no name")
        raw = "".join(call["args"]).strip()
        try:
            value = json.loads(raw) if raw else {}
        except ValueError as error:
            raise InvalidToolInput(f"the arguments of {call['name']} are not JSON: {error}") from None
        if not isinstance(value, dict):
            raise InvalidToolInput(f"the arguments of {call['name']} are not a JSON object")
        return {"type": "tool_use", "id": call["id"] or f"call_{index}", "name": call["name"],
                "input": value}

    def _estimate(self, request: dict, text: str, calls: dict) -> dict:
        sent = json.dumps([request["system"], request["tools"], request["messages"]], ensure_ascii=False)
        said = text + "".join("".join(call["args"]) + call["name"] for call in calls.values())
        return {"input_tokens": math.ceil(len(sent) / 3), "output_tokens": max(1, math.ceil(len(said) / 3)),
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}


def _usage(usage) -> dict:
    if usage is None:
        return {}
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    details = getattr(usage, "prompt_tokens_details", None)
    cached = int(getattr(details, "cached_tokens", 0) or 0) if details is not None else 0
    return {"input_tokens": max(0, prompt - cached),
            "output_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": cached}


def _say(error) -> str:
    return str(getattr(error, "message", None) or error)
