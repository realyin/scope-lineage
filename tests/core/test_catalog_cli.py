"""``scope-lineage catalog validate|build``: exit codes, the two report forms, the file."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.cli import main

from .catalog_demo import DEMO, copy_demo, mutate


def _broken(tmp_path: Path) -> Path:
    root = copy_demo(tmp_path)
    mutate(root, "terms.yaml", lambda d: d["terms"][0].update(refers_to="concept:ghost"))
    return root


def test_validate_a_valid_catalog_exits_zero(capsys) -> None:
    assert main(["catalog", "validate", str(DEMO)]) == 0

    out = capsys.readouterr().out
    assert "demo-lending" in out
    assert "0 error(s)" in out
    assert "unmapped_binding" in out


def test_validate_json_prints_the_report(capsys) -> None:
    assert main(["catalog", "validate", str(DEMO), "--json"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["errors"] == []
    assert report["counts"]["concepts"] == 10


def test_validate_exits_one_on_errors(tmp_path: Path, capsys) -> None:
    assert main(["catalog", "validate", str(_broken(tmp_path))]) == 1

    out = capsys.readouterr().out
    assert "term_refers_to" in out
    assert "terms.yaml" in out


def test_validate_json_exits_one_on_errors(tmp_path: Path, capsys) -> None:
    assert main(["catalog", "validate", str(_broken(tmp_path)), "--json"]) == 1

    report = json.loads(capsys.readouterr().out)
    assert [error["rule"] for error in report["errors"]] == ["term_refers_to"]


def test_a_catalog_that_cannot_be_read_exits_two(tmp_path: Path, capsys) -> None:
    assert main(["catalog", "validate", str(tmp_path / "nowhere")]) == 2
    assert "not a directory" in capsys.readouterr().err


def test_build_writes_ontology_json(tmp_path: Path, capsys) -> None:
    out = tmp_path / "out"

    assert main(["catalog", "build", str(DEMO), "--out", str(out)]) == 0

    document = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    assert document["doc_format"] == "ontology-json/3"
    assert "ontology.json" in capsys.readouterr().out


def test_build_refuses_an_invalid_catalog(tmp_path: Path, capsys) -> None:
    out = tmp_path / "out"

    assert main(["catalog", "build", str(_broken(tmp_path)), "--out", str(out)]) == 1

    assert not (out / "ontology.json").exists()
    assert "term_refers_to" in capsys.readouterr().err


def test_catalog_requires_an_action() -> None:
    with pytest.raises(SystemExit):
        main(["catalog"])
