"""The model seam over the official ``anthropic`` SDK: the only module that imports it.

The import is lazy (inside ``load_model``), so the HTTP server, the MCP server and the
browse page work without the SDK installed; asking then reports why it is unavailable.

Each turn is one streamed Messages API request (``messages.stream`` with
``get_final_message()``): streaming keeps a long turn clear of HTTP timeouts and lets a
cancel or the wall clock close it between events. The request carries:

- the model (default ``claude-opus-5-5``) with adaptive thinking and an explicit
  ``output_config.effort`` (default ``high``: the walk is a long, rule-heavy multi-step
  tool task, the kind that rewards it; that model's own default is ``medium``);
- the tools with ``eager_input_streaming`` (every input is checked against its schema
  before it runs, and an input that is not JSON at all is asked for again), no
  ``tool_choice`` (``auto``; a forced choice is refused by that model);
- a cache breakpoint on the last system block (tools and system prompt, the stable
  prefix) and top-level automatic caching for the growing message tail;
- server-side refusal fallbacks (``fallbacks: "default"`` under the
  ``server-side-fallback-2026-07-01`` beta), unless started with ``--ask-no-fallback``.

Credentials are the SDK's own: it resolves them from the environment on the server (an
API key or auth token variable, an ``ant auth login`` profile, workload identity
federation). No key is taken on the command line, logged, or sent to the page.

A model from the ``--ask-models`` file (``load_spec``) may also name a ``base_url`` (a
private gateway that speaks the Messages API) and ``api_key_env`` (the variable whose
value is passed to the client as its API key; a gateway model without one gets a
placeholder key, so the ambient credential -- ``ANTHROPIC_API_KEY``, an auth token, a
login profile -- is never sent to that host), and may switch off, one by one, what a
gateway may reject: the refusal fallbacks, prompt caching (the top-level mark and the
system block's breakpoint), ``eager_input_streaming``, adaptive thinking and the effort
(``effort: null``). Its defaults are the request above.

These SDK calls are written from the SDK's documentation; the repository's tests drive
them only through a stand-in module of the same shape, never against the real API.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from .loop import Cancelled, InvalidToolInput, ModelError

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "high"
EFFORTS = ("low", "medium", "high", "xhigh", "max")
MIN_SDK = (1, 7, 0)
SDK_RANGE = ">=1.7,<2"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
INSTALL_HINT = "pip install 'scope-lineage-service[ask]'"
NO_KEY = "not-needed"


def credential_source(environ=None, home: Path | None = None) -> str | None:
    """Which credential the SDK will find, in its documented order, or None: an API key or
    auth token variable, a named or ``ant auth login`` profile, workload identity federation.
    Names the kind only, never a value."""
    environ = os.environ if environ is None else environ
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        if environ.get(name):
            return name
    if environ.get("ANTHROPIC_FEDERATION_RULE_ID") and environ.get("ANTHROPIC_ORGANIZATION_ID") and (
        environ.get("ANTHROPIC_IDENTITY_TOKEN_FILE") or environ.get("ANTHROPIC_IDENTITY_TOKEN")
    ):
        return "workload identity federation"
    home = home or Path.home()
    roots = [Path(environ["XDG_CONFIG_HOME"])] if environ.get("XDG_CONFIG_HOME") else []
    for root in [*roots, home / ".config"]:
        profiles = root / "anthropic"
        if profiles.is_dir() and any(profiles.iterdir()):
            return "an ant auth login profile"
    return None


def _version(text: str) -> tuple[int, ...]:
    parts = []
    for piece in text.split(".")[:3]:
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts)


def load_model(model: str = DEFAULT_MODEL, effort: str | None = DEFAULT_EFFORT, *,
               fallback: bool = True, environ=None, base_url: str | None = None,
               api_key_env: str | None = None, prompt_cache: bool = True,
               eager_input_streaming: bool = True, adaptive_thinking: bool = True,
               max_tokens: int | None = None):
    """``(AnthropicModel, None)`` when asking can work, else ``(None, the reason)``."""
    environ = os.environ if environ is None else environ
    try:
        import anthropic
    except ImportError:
        return None, f"the anthropic package is not installed ({INSTALL_HINT})"
    version = getattr(anthropic, "__version__", "0")
    if _version(version) < MIN_SDK:
        return None, (f"anthropic {version} is older than this service needs ({SDK_RANGE}); "
                      f"{INSTALL_HINT}")
    options: dict = {}
    if base_url:
        options["base_url"] = base_url
    if api_key_env:
        key = environ.get(api_key_env) or ""
        if not key:
            return None, "its API key variable (api_key_env) is not set in the server's environment"
        options["api_key"], source = key, api_key_env
    elif base_url:
        # An explicit api_key keeps the SDK from reading any credential of its own (the
        # environment variables, a profile, federation): a private gateway named here
        # must not receive the official key because api_key_env was left out.
        options["api_key"], source = NO_KEY, "no key (placeholder)"
    else:
        source = credential_source(environ)
        if source is None:
            return None, ("no Anthropic credential in the server's environment: set ANTHROPIC_API_KEY "
                          "or ANTHROPIC_AUTH_TOKEN, or run `ant auth login`, then restart")
    try:
        client = anthropic.Anthropic(**options)
    except anthropic.AnthropicError as error:
        return None, f"the anthropic client could not start: {error}"
    return AnthropicModel(anthropic, client, model, effort, fallback=fallback, source=source,
                          prompt_cache=prompt_cache, eager_input_streaming=eager_input_streaming,
                          adaptive_thinking=adaptive_thinking, max_tokens=max_tokens), None


def load_spec(spec, environ=None):
    """A model from the ``--ask-models`` file (``models.ModelSpec``)."""
    return load_model(spec.model, spec.effort, fallback=spec.fallback, environ=environ,
                      base_url=spec.base_url, api_key_env=spec.api_key_env,
                      prompt_cache=spec.prompt_cache,
                      eager_input_streaming=spec.eager_input_streaming,
                      adaptive_thinking=spec.adaptive_thinking, max_tokens=spec.max_tokens)


class AnthropicModel:
    """One streamed Messages API request per turn (see the module docstring)."""

    fake = False
    provider = "anthropic"

    def __init__(self, sdk, client, model: str, effort: str | None, *, fallback: bool, source: str,
                 prompt_cache: bool = True, eager_input_streaming: bool = True,
                 adaptive_thinking: bool = True, max_tokens: int | None = None):
        self._sdk, self._client = sdk, client
        self.name, self.effort, self.fallback, self.source = model, effort, fallback, source
        self.prompt_cache, self.eager_input_streaming = prompt_cache, eager_input_streaming
        self.adaptive_thinking, self.max_tokens = adaptive_thinking, max_tokens

    def params(self, request: dict) -> dict:
        tools, system = request["tools"], request["system"]
        if self.eager_input_streaming:
            tools = [{**tool, "eager_input_streaming": True} for tool in tools]
        if not self.prompt_cache and isinstance(system, list):
            system = [{k: v for k, v in block.items() if k != "cache_control"} for block in system]
        params = {
            "model": self.name,
            "max_tokens": request["max_tokens"],
            "system": system,
            "tools": tools,
            "messages": request["messages"],
        }
        if self.adaptive_thinking:
            params["thinking"] = {"type": "adaptive"}
        if self.effort:
            params["output_config"] = {"effort": self.effort}
        if self.prompt_cache:
            params["cache_control"] = {"type": "ephemeral"}
        if self.fallback:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        return params

    def turn(self, request: dict, should_stop: Callable[[], bool]) -> dict:
        sdk = self._sdk
        api = self._client.beta.messages if self.fallback else self._client.messages
        try:
            with api.stream(**self.params(request)) as stream:
                for _event in stream:
                    if should_stop():
                        raise Cancelled()
                message = stream.get_final_message()
        except Cancelled:
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
        except sdk.AnthropicError as error:
            raise ModelError("sdk_error", _say(error)) from None
        except ValueError as error:
            # a streamed tool input the SDK could not parse at all: no call to answer
            raise InvalidToolInput(str(error)) from None
        data = message.to_dict()
        return {
            "content": data.get("content") or [],
            "stop_reason": data.get("stop_reason"),
            "stop_details": data.get("stop_details"),
            "usage": data.get("usage") or {},
            "model": data.get("model"),
        }


def _say(error) -> str:
    return str(getattr(error, "message", None) or error)
