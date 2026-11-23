"""``scope-lineage-service``: refuses to start on inputs the catalog commands refuse."""

from __future__ import annotations

import sys

import pytest

from scope_lineage_service.cli import main


@pytest.mark.parametrize("mode", ["http", "mcp"])
def test_an_unreadable_ontology_stops_the_server_with_the_cli_exit_code(
    mode, tmp_path, capsys
) -> None:
    assert main([mode, str(tmp_path / "none.json")]) == 2
    assert "ontology path does not exist" in capsys.readouterr().err


def test_a_missing_semantics_directory_stops_the_server(inputs, tmp_path, capsys) -> None:
    code = main(["http", str(inputs["ontology"]), "--semantics", str(tmp_path / "none")])
    assert code == 2
    assert "--semantics directory does not exist" in capsys.readouterr().err


# ------------------------------------------------------------------ the ask options


def test_ask_is_refused_on_an_address_other_machines_reach(inputs, capsys) -> None:
    code = main(["http", str(inputs["ontology"]), "--ask", "--host", "0.0.0.0"])

    assert code == 2 and "loopback" in capsys.readouterr().err


def test_ask_caps_must_be_positive(inputs, capsys) -> None:
    code = main(["http", str(inputs["ontology"]), "--ask", "--ask-max-turns", "0"])

    assert code == 2 and "--ask-max-" in capsys.readouterr().err


def _service(inputs, *extra):
    from scope_lineage_service.cli import _ask_service, _parser
    from scope_lineage_service.state import CatalogState

    args = _parser().parse_args(["http", str(inputs["ontology"]), *extra])
    return _ask_service(args, CatalogState(str(inputs["ontology"])))


def test_without_the_sdk_ask_is_unavailable_and_says_how_to_install(inputs, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "anthropic", None)
    service, notice = _service(inputs, "--ask")

    assert not service.status()["available"]
    assert "scope-lineage-service[ask]" in service.status()["reason"]
    assert notice.startswith("ask panel: unavailable")


def test_the_options_reach_the_service(inputs) -> None:
    service, notice = _service(
        inputs, "--ask-dev-fake-model", "--ask-max-turns", "7", "--ask-max-tool-calls", "9",
        "--ask-max-output-tokens", "5000", "--ask-max-seconds", "60",
        "--ask-max-conversations", "3", "--ask-idle-minutes", "2", "--max-body", "2048")
    status = service.status()

    assert status["available"] and status["fake"] and "FAKE MODEL" in notice
    assert status["limits"] == {"max_turns": 7, "max_tool_calls": 9, "max_output_tokens": 5000,
                                "max_seconds": 60.0}
    assert status["conversations"]["max"] == 3 and status["conversations"]["max_idle_seconds"] == 120
    assert service.limits.max_tokens_per_turn == 5000 and service.tools.max_sql == 2048


def test_the_real_mode_names_the_cost_and_what_is_sent(inputs, monkeypatch) -> None:
    from scope_lineage_service.ask import anthropic_model

    class Ready:
        name, effort, fallback, source, fake = "claude-opus-5-5", "high", True, "ANTHROPIC_API_KEY", False

    monkeypatch.setattr(anthropic_model, "load_model", lambda *a, **k: (Ready(), None))
    service, notice = _service(inputs, "--ask")

    assert service.status()["available"] and not service.status()["fake"]
    for words in ("costs money", "sent to the model provider", "No SQL is run", "ANTHROPIC_API_KEY"):
        assert words in notice
