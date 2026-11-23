"""The models file (``--ask-models``): validation, secrets refused, the loopback rule for
plain HTTP, and which models are usable -- without importing any SDK or opening a socket."""

from __future__ import annotations

import json

import pytest

from scope_lineage_service.ask.models import (
    ModelEntry, ModelSet, ModelsFileError, check_base_url, load_entries, parse_models,
    read_models_file,
)

OFFICIAL = {"id": "opus", "label": "Claude Opus", "provider": "anthropic",
            "model": "claude-opus-5-5", "default": True}
PRIVATE = {"id": "private", "label": "Private model", "provider": "openai-compatible",
           "model": "example-model", "base_url": "https://models.example.internal/v1",
           "api_key_env": "PRIVATE_MODELS_KEY", "max_tokens": 8192}


def parse(*models):
    return parse_models({"models": list(models)})


def test_a_valid_file_reads_into_specs_with_todays_defaults(tmp_path) -> None:
    path = tmp_path / "models.json"
    path.write_text(json.dumps({"models": [OFFICIAL, PRIVATE]}), "utf-8")
    opus, private = read_models_file(str(path))

    assert (opus.id, opus.label, opus.provider, opus.model) == ("opus", "Claude Opus", "anthropic",
                                                                 "claude-opus-5-5")
    assert opus.default and not private.default
    # the official endpoint keeps what the single-model server sends today
    assert opus.effort == "high" and opus.fallback and opus.prompt_cache
    assert opus.eager_input_streaming and opus.adaptive_thinking and opus.base_url is None
    assert private.base_url == "https://models.example.internal/v1"
    assert private.api_key_env == "PRIVATE_MODELS_KEY" and private.max_tokens == 8192
    assert private.effort is None and private.stream_usage and private.max_tokens_field == "max_tokens"


def test_anthropic_features_switch_off_one_by_one() -> None:
    spec, = parse({**OFFICIAL, "base_url": "https://gateway.example.internal", "effort": None,
                   "fallback": False, "prompt_cache": False, "eager_input_streaming": False,
                   "adaptive_thinking": False})

    assert spec.effort is None and not spec.fallback and not spec.prompt_cache
    assert not spec.eager_input_streaming and not spec.adaptive_thinking


def test_without_a_default_the_first_model_is_it() -> None:
    first, second = parse({**OFFICIAL, "default": False}, PRIVATE)

    assert first.default and not second.default


def test_the_label_defaults_to_the_id() -> None:
    spec, = parse({k: v for k, v in OFFICIAL.items() if k != "label"})

    assert spec.label == "opus"


@pytest.mark.parametrize(
    ("document", "words"),
    [
        ([], "an object with a models list"),
        ({"models": []}, "at least one model"),
        ({"models": [OFFICIAL], "other": 1}, "unknown field"),
        ({"models": [{**OFFICIAL, "colour": "red"}]}, "unknown field"),
        ({"models": [{**OFFICIAL, "id": "Bad Id"}]}, "id"),
        ({"models": [OFFICIAL, {**PRIVATE, "id": "opus"}]}, "twice"),
        ({"models": [{**OFFICIAL, "provider": "other"}]}, "provider"),
        ({"models": [{**OFFICIAL, "model": ""}]}, "model"),
        ({"models": [{k: v for k, v in PRIVATE.items() if k != "base_url"}]}, "base_url"),
        ({"models": [OFFICIAL, {**PRIVATE, "default": True}]}, "one default"),
        ({"models": [{**OFFICIAL, "effort": "extreme"}]}, "effort"),
        ({"models": [{**PRIVATE, "max_tokens": 0}]}, "max_tokens"),
        ({"models": [{**PRIVATE, "api_key_env": "lower-case"}]}, "api_key_env"),
        ({"models": [{**PRIVATE, "max_tokens_field": "tokens"}]}, "max_tokens_field"),
        ({"models": [{**OFFICIAL, "stream_usage": False}]}, "openai-compatible"),
        ({"models": [{**PRIVATE, "fallback": False}]}, "anthropic"),
        ({"models": [{**OFFICIAL, "fallback": "no"}]}, "true or false"),
        ({"models": [{**OFFICIAL, "label": ""}]}, "label"),
    ],
)
def test_a_bad_file_is_refused_with_a_sentence_that_names_the_problem(document, words) -> None:
    with pytest.raises(ModelsFileError) as refused:
        parse_models(document)

    assert words in refused.value.message


def test_an_unreadable_file_is_refused(tmp_path) -> None:
    with pytest.raises(ModelsFileError) as missing:
        read_models_file(str(tmp_path / "none.json"))
    assert "--ask-models" in missing.value.message
    (tmp_path / "bad.json").write_text("{", "utf-8")
    with pytest.raises(ModelsFileError) as bad:
        read_models_file(str(tmp_path / "bad.json"))
    assert "JSON" in bad.value.message


@pytest.mark.parametrize(
    "model",
    [
        {**PRIVATE, "api_key": "abc"},
        {**PRIVATE, "token": "abc"},
        {**PRIVATE, "label": "sk-ant-api03-abcdef"},
        {**PRIVATE, "model": "Zx81ab9Qw2Lm7Pq0Rt5Yu3Io6As4Df8Gh1"},
        {**PRIVATE, "base_url": "https://user:pass@models.example.internal/v1"},
        {**PRIVATE, "base_url": "https://models.example.internal/v1?api_key=abc"},
    ],
)
def test_a_file_holding_what_looks_like_a_secret_is_refused(model) -> None:
    with pytest.raises(ModelsFileError) as refused:
        parse(model)

    assert "secret" in refused.value.message and "api_key_env" in refused.value.message
    assert "abc" not in refused.value.message and "pass" not in refused.value.message


def test_ordinary_long_model_names_are_not_mistaken_for_keys() -> None:
    spec, = parse({**PRIVATE, "model": "org/Example-Model-70B-Instruct-Quantized-v2"})

    assert spec.model.startswith("org/")


# ------------------------------------------------------------------ the loopback rule


@pytest.mark.parametrize(
    "url",
    ["https://models.example.internal/v1", "http://127.0.0.1:8000/v1", "http://localhost:11434/v1",
     "http://[::1]:8000/v1"],
)
def test_https_anywhere_and_plain_http_on_this_machine_are_accepted(url) -> None:
    check_base_url(url, allow_insecure_http=False)


def test_plain_http_to_another_host_needs_an_explicit_switch() -> None:
    with pytest.raises(ModelsFileError) as refused:
        check_base_url("http://models.example.internal/v1", allow_insecure_http=False)

    assert "allow_insecure_http" in refused.value.message
    check_base_url("http://models.example.internal/v1", allow_insecure_http=True)
    with pytest.raises(ModelsFileError):
        parse({**PRIVATE, "base_url": "http://10.0.0.5/v1"})
    spec, = parse({**PRIVATE, "base_url": "http://10.0.0.5/v1", "allow_insecure_http": True})
    assert spec.allow_insecure_http


@pytest.mark.parametrize("url", ["ftp://models.example.internal", "models.example.internal/v1",
                                 "https://"])
def test_a_base_url_must_be_an_http_url_with_a_host(url) -> None:
    with pytest.raises(ModelsFileError):
        check_base_url(url, allow_insecure_http=True)


# ------------------------------------------------------------------ availability


class Ready:
    fake = False

    def __init__(self, name):
        self.name = name


def loaders(**reasons):
    def load(spec, environ):
        reason = reasons.get(spec.id)
        return (None, reason) if reason else (Ready(spec.model), None)
    return {"anthropic": load, "openai-compatible": load}


def test_a_model_that_cannot_load_is_listed_unavailable_with_its_reason() -> None:
    specs = parse(OFFICIAL, PRIVATE)
    models = load_entries(specs, environ={}, loaders=loaders(private="its API key variable is not set"))

    assert models.available and models.default_id == "opus"
    listed = {item["id"]: item for item in models.public()}
    assert listed["private"] == {"id": "private", "label": "Private model",
                                 "provider": "openai-compatible", "available": False,
                                 "reason": "its API key variable is not set", "default": False,
                                 "fake": False}
    assert listed["opus"]["available"] and listed["opus"]["default"]


def test_the_public_list_never_carries_urls_or_variable_names() -> None:
    models = load_entries(parse(OFFICIAL, PRIVATE), environ={}, loaders=loaders())
    text = json.dumps(models.public())

    assert "example.internal" not in text and "PRIVATE_MODELS_KEY" not in text


def test_an_unavailable_default_gives_way_to_the_first_usable_model() -> None:
    models = load_entries(parse(OFFICIAL, PRIVATE), environ={}, loaders=loaders(opus="no credential"))

    assert models.default_id == "private"
    assert [item["default"] for item in models.public()] == [False, True]


def test_with_no_usable_model_the_set_says_why() -> None:
    models = load_entries(parse(OFFICIAL, PRIVATE), environ={},
                          loaders=loaders(opus="no credential", private="no package"))

    assert not models.available
    assert "opus: no credential" in models.reason and "private: no package" in models.reason


def test_resolving_a_model_for_a_question() -> None:
    models = load_entries(parse(OFFICIAL, PRIVATE), environ={}, loaders=loaders(private="down"))

    assert models.resolve(None).id == "opus" and models.resolve("opus").id == "opus"
    with pytest.raises(LookupError):
        models.resolve("nope")
    with pytest.raises(ValueError):
        models.resolve("private")


def test_a_model_can_be_marked_unavailable_later() -> None:
    models = load_entries(parse(OFFICIAL, PRIVATE), environ={}, loaders=loaders())
    models.mark_unavailable("opus", "the provider refused the credentials")

    assert models.default_id == "private"
    assert not models.public()[0]["available"]


def test_the_single_model_set_keeps_todays_shape() -> None:
    models = ModelSet.single(Ready("claude-opus-5-5"), None)

    assert models.default_id == "default" and models.available
    assert models.public() == [{"id": "default", "label": "claude-opus-5-5", "provider": "anthropic",
                                "available": True, "reason": None, "default": True,
                                "fake": False}]
    missing = ModelSet.single(None, "the anthropic package is not installed")
    assert not missing.available and missing.reason == "the anthropic package is not installed"
    assert isinstance(missing.entries[0], ModelEntry)
