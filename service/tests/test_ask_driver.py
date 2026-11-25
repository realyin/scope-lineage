"""``service/tools/ask_driver.py``: a two-turn conversation driven over HTTP, as an evaluator would.

The server is the one the CLI options build (``--ask-dev-fake-model --ask-trace DIR``), with
the fake's pause set to zero so the test is quick.
"""

from __future__ import annotations

import importlib.util
import json
import threading

import pytest
from service_paths import REPO

from scope_lineage_service.cli import _ask_service, _parser
from scope_lineage_service.http_server import make_server
from scope_lineage_service.state import CatalogState

DRIVER = REPO / "service" / "tools" / "ask_driver.py"


@pytest.fixture(scope="module")
def driver():
    spec = importlib.util.spec_from_file_location("ask_driver", DRIVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def served(inputs, tmp_path):
    args = _parser().parse_args(["http", str(inputs["ontology"]), "--semantics",
                                 str(inputs["semantics"]), "--ask-dev-fake-model",
                                 "--ask-trace", str(tmp_path / "trace")])
    state = CatalogState(str(inputs["ontology"]), semantics=str(inputs["semantics"]))
    service, _ = _ask_service(args, state)
    service.model.delay = 0
    httpd = make_server(state, host="127.0.0.1", port=0, quiet=True, ask=service)
    threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True).start()
    host, port = httpd.server_address[:2]
    yield f"http://{host}:{port}", tmp_path / "trace"
    httpd.shutdown()
    httpd.server_close()


def _main(driver, capsys, *argv):
    code = driver.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_a_two_turn_conversation_is_driven_and_shown(driver, served, capsys) -> None:
    server, trace = served
    code, out, _ = _main(driver, capsys, "--server", server, "send", "客户数")
    first = json.loads(out)
    assert code == 0 and first["status"] == "done" and first["follow_up"] is False
    assert first["answer"].startswith("【开发用假模型】") and first["sql"] and first["brief"]
    assert first["brief_missing"] is False and isinstance(first["elapsed"], (int, float))

    code, out, _ = _main(driver, capsys, "--server", server, "send", "--conversation",
                         first["conversation"], "再按月分")
    second = json.loads(out)
    assert code == 0 and second["status"] == "done" and second["follow_up"] is True
    assert second["conversation"] == first["conversation"] and second["run"] != first["run"]

    code, out, _ = _main(driver, capsys, "--server", server, "show", first["conversation"])
    shown = json.loads(out)
    assert code == 0 and [run["question"] for run in shown["runs"]] == ["客户数", "再按月分"]
    assert [run["answer"] for run in shown["runs"]] == [first["answer"], second["answer"]]
    assert shown["brief"] == second["brief"]

    lines = [json.loads(line) for line in
             (trace / f"{first['conversation']}.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [line["run"] for line in lines if line["kind"] == "run"] == [first["run"], second["run"]]


def test_a_refused_request_prints_the_server_error(driver, served, capsys) -> None:
    server, _ = served
    code, out, err = _main(driver, capsys, "--server", server, "send", "--conversation", "gone", "x")

    assert code == 2 and out == "" and json.loads(err)["error"]["kind"] == "conversation_gone"


def test_the_question_can_come_from_stdin(driver, served, capsys, monkeypatch) -> None:
    import io

    server, _ = served
    monkeypatch.setattr("sys.stdin", io.StringIO("客户数\n"))
    code, out, _ = _main(driver, capsys, "--server", server, "send", "-")

    assert code == 0 and json.loads(out)["status"] == "done"
