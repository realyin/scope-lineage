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


def load_model(model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT, *, fallback: bool = True,
               environ=None):
    """``(AnthropicModel, None)`` when asking can work, else ``(None, the reason)``."""
    try:
        import anthropic
    except ImportError:
        return None, f"the anthropic package is not installed ({INSTALL_HINT})"
    version = getattr(anthropic, "__version__", "0")
    if _version(version) < MIN_SDK:
        return None, (f"anthropic {version} is older than this service needs ({SDK_RANGE}); "
                      f"{INSTALL_HINT}")
    source = credential_source(environ)
    if source is None:
        return None, ("no Anthropic credential in the server's environment: set ANTHROPIC_API_KEY "
                      "or ANTHROPIC_AUTH_TOKEN, or run `ant auth login`, then restart")
    try:
        client = anthropic.Anthropic()
    except anthropic.AnthropicError as error:
        return None, f"the anthropic client could not start: {error}"
    return AnthropicModel(anthropic, client, model, effort, fallback=fallback, source=source), None


class AnthropicModel:
    """One streamed Messages API request per turn (see the module docstring)."""

    fake = False

    def __init__(self, sdk, client, model: str, effort: str, *, fallback: bool, source: str):
        self._sdk, self._client = sdk, client
        self.name, self.effort, self.fallback, self.source = model, effort, fallback, source

    def params(self, request: dict) -> dict:
        params = {
            "model": self.name,
            "max_tokens": request["max_tokens"],
            "system": request["system"],
            "tools": [{**tool, "eager_input_streaming": True} for tool in request["tools"]],
            "messages": request["messages"],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.effort},
            "cache_control": {"type": "ephemeral"},
        }
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
