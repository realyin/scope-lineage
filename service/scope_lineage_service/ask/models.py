"""The models the ask panel may use: the ``--ask-models`` file, its checks, and which
models can answer now.

The file is JSON: ``{"models": [ {...}, ... ]}``. Each model has a stable ``id`` (what
the page sends and remembers), a ``label`` (what the page shows), a ``provider``
(``anthropic`` or ``openai-compatible``), the provider's ``model`` id, and optionally a
``base_url``, ``api_key_env`` (the NAME of the environment variable holding the key; the
file itself never holds a secret, and a file that looks like it does is refused),
``effort``, ``max_tokens`` (a per-request output limit), ``default`` and per-provider
switches. Everything is checked when the server starts; a model whose SDK or credential
is missing is kept in the list as unavailable, with the reason, so one missing key does
not stop the others.

Plain ``http://`` to a host other than this machine is refused unless the model sets
``allow_insecure_http``: the question and catalog text travel over that link.

What the page sees of a model (``ModelSet.public``) is its id, label, provider kind,
whether it is available and why not, and whether it is the default -- never a base URL,
an environment variable name or anything read from one.
"""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import parse_qsl, urlsplit

PROVIDERS = ("anthropic", "openai-compatible")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
DEFAULT_ANTHROPIC_EFFORT = "high"
MAX_TOKENS_FIELDS = ("max_tokens", "max_completion_tokens")
SINGLE_ID = "default"

_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
_SECRET_PREFIXES = ("sk-", "sk_", "bearer ", "xoxb-", "xoxp-", "ghp_", "github_pat_", "aiza")
_SECRET_WORDS = ("key", "token", "secret", "password", "passwd", "credential", "auth")
_SECRET_ADVICE = ("the models file never holds a secret: put the key in an environment variable "
                  "on the server and name that variable in api_key_env")

COMMON_FIELDS = {"id", "label", "provider", "model", "base_url", "api_key_env", "effort",
                 "max_tokens", "default", "allow_insecure_http"}
PROVIDER_FIELDS = {
    "anthropic": {"fallback", "prompt_cache", "eager_input_streaming", "adaptive_thinking"},
    "openai-compatible": {"stream_usage", "max_tokens_field"},
}


class ModelsFileError(Exception):
    """The models file is unreadable or wrong; ``message`` is the sentence to print."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    provider: str
    model: str
    base_url: str | None = None
    api_key_env: str | None = None
    effort: str | None = None
    max_tokens: int | None = None
    default: bool = False
    allow_insecure_http: bool = False
    # anthropic: what a gateway may reject, each on by default (today's request)
    fallback: bool = True
    prompt_cache: bool = True
    eager_input_streaming: bool = True
    adaptive_thinking: bool = True
    # openai-compatible
    stream_usage: bool = True
    max_tokens_field: str = "max_tokens"


# ------------------------------------------------------------------ reading the file


def read_models_file(path: str) -> list[ModelSpec]:
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as error:
        raise ModelsFileError(f"--ask-models: cannot read {path}: {error.strerror or error}") from None
    try:
        document = json.loads(text)
    except ValueError as error:
        raise ModelsFileError(f"--ask-models: {path} is not JSON ({error})") from None
    return parse_models(document)


def parse_models(document) -> list[ModelSpec]:
    if not isinstance(document, dict) or not isinstance(document.get("models"), list):
        raise ModelsFileError('--ask-models: the file must be an object with a models list: '
                              '{"models": [...]}')
    _refuse_unknown(document, {"models"}, "the file")
    if not document["models"]:
        raise ModelsFileError("--ask-models: list at least one model")
    specs, seen = [], set()
    for number, item in enumerate(document["models"], 1):
        spec = _spec(item, number)
        if spec.id in seen:
            raise ModelsFileError(f"--ask-models: the id {spec.id!r} is used twice")
        seen.add(spec.id)
        specs.append(spec)
    defaults = [spec for spec in specs if spec.default]
    if len(defaults) > 1:
        raise ModelsFileError("--ask-models: mark at most one default model, not "
                              + ", ".join(spec.id for spec in defaults))
    if not defaults:
        specs[0] = _replace(specs[0], default=True)
    return specs


def _replace(spec: ModelSpec, **changes) -> ModelSpec:
    return ModelSpec(**{**spec.__dict__, **changes})


def _spec(item, number: int) -> ModelSpec:
    where = f"model {number}"
    if not isinstance(item, dict):
        raise ModelsFileError(f"--ask-models: {where} must be an object")
    _refuse_secrets(item, where)
    model_id = item.get("id")
    if not isinstance(model_id, str) or not _ID.match(model_id):
        raise ModelsFileError(f"--ask-models: {where} needs an id of 1-40 lower-case letters, "
                              "digits, '.', '_' or '-' (starting with a letter or digit)")
    where = f"model {model_id!r}"
    provider = item.get("provider")
    if provider not in PROVIDERS:
        raise ModelsFileError(f"--ask-models: {where}: provider must be one of "
                              + ", ".join(PROVIDERS))
    allowed = COMMON_FIELDS | PROVIDER_FIELDS[provider]
    for name in sorted(set(item) - allowed):
        other = next((kind for kind, names in PROVIDER_FIELDS.items() if name in names), None)
        if other:
            raise ModelsFileError(f"--ask-models: {where}: {name} applies to {other} models only")
    _refuse_unknown(item, allowed, where)
    values: dict = {"id": model_id, "provider": provider}
    values["label"] = _text(item, "label", where, default=model_id, limit=60)
    values["model"] = _text(item, "model", where, limit=200)
    base_url = item.get("base_url")
    if base_url is not None:
        if not isinstance(base_url, str):
            raise ModelsFileError(f"--ask-models: {where}: base_url must be a string")
    elif provider == "openai-compatible":
        raise ModelsFileError(f"--ask-models: {where}: an openai-compatible model needs a base_url")
    for name in ("default", "allow_insecure_http", *sorted(PROVIDER_FIELDS[provider] - {"max_tokens_field"})):
        if name in item:
            if not isinstance(item[name], bool):
                raise ModelsFileError(f"--ask-models: {where}: {name} takes true or false")
            values[name] = item[name]
    if base_url is not None:
        check_base_url(base_url, values.get("allow_insecure_http", False), where)
        values["base_url"] = base_url
    env = item.get("api_key_env")
    if env is not None:
        if not isinstance(env, str) or not _ENV_NAME.match(env):
            raise ModelsFileError(f"--ask-models: {where}: api_key_env takes the NAME of an "
                                  "environment variable (upper-case letters, digits and '_')")
        values["api_key_env"] = env
    values["effort"] = _effort(item, provider, where)
    if "max_tokens" in item:
        tokens = item["max_tokens"]
        if not isinstance(tokens, int) or isinstance(tokens, bool) or not 1 <= tokens <= 1_000_000:
            raise ModelsFileError(f"--ask-models: {where}: max_tokens takes an integer from 1 "
                                  "to 1000000 (the model's output limit per request)")
        values["max_tokens"] = tokens
    if "max_tokens_field" in item:
        if item["max_tokens_field"] not in MAX_TOKENS_FIELDS:
            raise ModelsFileError(f"--ask-models: {where}: max_tokens_field takes "
                                  + " or ".join(MAX_TOKENS_FIELDS))
        values["max_tokens_field"] = item["max_tokens_field"]
    return ModelSpec(**values)


def _text(item: dict, name: str, where: str, *, default: str | None = None, limit: int) -> str:
    value = item.get(name, default)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ModelsFileError(f"--ask-models: {where}: {name} takes a non-empty string of at most "
                              f"{limit} characters")
    return value.strip()


def _effort(item: dict, provider: str, where: str) -> str | None:
    if "effort" not in item:
        return DEFAULT_ANTHROPIC_EFFORT if provider == "anthropic" else None
    effort = item["effort"]
    if effort is None:
        return None
    if provider == "anthropic" and effort not in EFFORTS:
        raise ModelsFileError(f"--ask-models: {where}: effort takes null or one of "
                              + ", ".join(EFFORTS))
    if provider != "anthropic" and (not isinstance(effort, str) or not re.match(r"^[a-z]{1,20}$", effort)):
        raise ModelsFileError(f"--ask-models: {where}: effort takes null or a lower-case word "
                              "(sent as reasoning_effort)")
    return effort


def _refuse_unknown(item: dict, allowed: set, where: str) -> None:
    unknown = sorted(set(item) - allowed)
    if unknown:
        raise ModelsFileError(f"--ask-models: {where}: unknown field(s): {', '.join(unknown)}")


def _refuse_secrets(item: dict, where: str) -> None:
    known = COMMON_FIELDS.union(*PROVIDER_FIELDS.values())
    for name, value in item.items():
        if name not in known and any(word in str(name).lower() for word in _SECRET_WORDS):
            raise ModelsFileError(f"--ask-models: {where}: field {name!r} looks like a secret; "
                                  + _SECRET_ADVICE)
        if isinstance(value, str) and name != "base_url" and _looks_like_secret(value):
            raise ModelsFileError(f"--ask-models: {where}: the value of {name!r} looks like a "
                                  "secret; " + _SECRET_ADVICE)
    url = item.get("base_url")
    if isinstance(url, str):
        parts = urlsplit(url)
        if parts.username or parts.password or "@" in parts.netloc:
            raise ModelsFileError(f"--ask-models: {where}: base_url carries credentials; "
                                  + _SECRET_ADVICE)
        for key, _ in parse_qsl(parts.query, keep_blank_values=True):
            if any(word in key.lower() for word in (*_SECRET_WORDS, "sig")):
                raise ModelsFileError(f"--ask-models: {where}: base_url carries a secret in its "
                                      "query; " + _SECRET_ADVICE)


def _looks_like_secret(value: str) -> bool:
    text = value.strip()
    if text.lower().startswith(_SECRET_PREFIXES):
        return True
    # a long random token: one run of letters and digits with all three kinds mixed in
    return (len(text) >= 32 and re.fullmatch(r"[A-Za-z0-9_\-]+", text) is not None
            and re.search(r"[a-z]", text) is not None and re.search(r"[A-Z]", text) is not None
            and len(re.findall(r"\d", text)) >= 4
            and max(len(run) for run in re.split(r"[-_]", text)) >= 24)


def check_base_url(url: str, allow_insecure_http: bool, where: str = "base_url") -> None:
    """Refuse a URL that is not http(s) with a host, and plain http to another machine
    unless ``allow_insecure_http``."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ModelsFileError(f"--ask-models: {where}: base_url must be an http:// or https:// "
                              "URL with a host")
    if parts.scheme == "http" and not allow_insecure_http and not is_loopback(parts.hostname):
        raise ModelsFileError(
            f"--ask-models: {where}: base_url uses plain http:// to another machine, so the "
            "question and the catalog text would cross the network unencrypted; use https://, "
            "or set allow_insecure_http: true for this model if that link is trusted")


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


# ------------------------------------------------------------------ usable models


@dataclass
class ModelEntry:
    id: str
    label: str
    provider: str
    model: object | None
    reason: str | None
    configured_default: bool = False
    spec: ModelSpec | None = None

    @property
    def available(self) -> bool:
        return self.model is not None and self.reason is None

    @property
    def fake(self) -> bool:
        return bool(getattr(self.model, "fake", False))


@dataclass
class ModelSet:
    entries: list = field(default_factory=list)

    @classmethod
    def single(cls, model, reason: str | None) -> "ModelSet":
        """Today's one model (``--ask-model``) as a set of one."""
        name = getattr(model, "name", None) or "model"
        provider = getattr(model, "provider", "anthropic")
        return cls([ModelEntry(SINGLE_ID, name, provider, model, reason, True)])

    @property
    def available(self) -> bool:
        return any(entry.available for entry in self.entries)

    @property
    def default(self) -> ModelEntry:
        usable = [entry for entry in self.entries if entry.available]
        configured = next((entry for entry in usable if entry.configured_default), None)
        return configured or (usable[0] if usable else self.entries[0])

    @property
    def default_id(self) -> str:
        return self.default.id

    @property
    def reason(self) -> str | None:
        if self.available:
            return None
        if len(self.entries) == 1:
            return self.entries[0].reason or "asking is not available"
        return "no model can answer: " + "; ".join(
            f"{entry.id}: {entry.reason}" for entry in self.entries)

    @property
    def fake(self) -> bool:
        return any(entry.fake for entry in self.entries)

    def public(self) -> list[dict]:
        default = self.default_id
        return [{"id": entry.id, "label": entry.label, "provider": entry.provider,
                 "available": entry.available, "reason": entry.reason,
                 "default": entry.id == default, "fake": entry.fake} for entry in self.entries]

    def resolve(self, model_id: str | None) -> ModelEntry:
        """The model a question asks for (None: the default). LookupError: no such id;
        ValueError: it cannot answer now."""
        if model_id is None:
            entry = self.default
        else:
            entry = next((entry for entry in self.entries if entry.id == model_id), None)
            if entry is None:
                raise LookupError(model_id)
        if not entry.available:
            raise ValueError(entry.reason or "unavailable")
        return entry

    def mark_unavailable(self, model_id: str, reason: str) -> None:
        for entry in self.entries:
            if entry.id == model_id:
                entry.reason = reason


Loader = Callable[[ModelSpec, object], tuple]


def default_loaders() -> dict:
    from . import anthropic_model, openai_model

    return {"anthropic": anthropic_model.load_spec, "openai-compatible": openai_model.load_spec}


def load_entries(specs: list[ModelSpec], *, environ=None, loaders: dict | None = None) -> ModelSet:
    """Each spec loaded by its provider's loader: ``(model, None)`` or ``(None, reason)``."""
    loaders = loaders or default_loaders()
    entries = []
    for spec in specs:
        model, reason = loaders[spec.provider](spec, environ)
        entries.append(ModelEntry(spec.id, spec.label, spec.provider, model, reason, spec.default,
                                  spec))
    return ModelSet(entries)
