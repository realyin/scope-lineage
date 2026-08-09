"""Public import surface and minimal Core CLI behavior."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

import lineage_parser
from lineage_parser.cli import main


def test_public_exports_match_the_declared_core_api() -> None:
    assert set(lineage_parser.__all__) == lineage_parser.PUBLIC_CORE_API


def test_importing_core_does_not_load_upper_layers() -> None:
    script = (
        "import sys, lineage_parser; "
        "forbidden=('pipeline','pipeline.understanding.insight','pipeline.refactor',"
        "'pipeline.understanding.presets'); "
        "assert not any(n == p or n.startswith(p + '.') for n in sys.modules for p in forbidden)"
    )
    subprocess.run([sys.executable, "-c", script], check=True)


def test_core_cli_writes_only_lineage_and_diagnostics(tmp_path) -> None:
    sql_path = tmp_path / "demo.sql"
    sql_path.write_text(
        "INSERT INTO mart.t SELECT id FROM ods.source",
        encoding="utf-8",
    )
    output = tmp_path / "output"

    assert main([
        "parse",
        "--sql-file",
        str(sql_path),
        "--out",
        str(output),
    ]) == 0

    task_dir = output / "demo"
    assert {path.name for path in task_dir.iterdir()} == {
        "lineage.json",
        "diagnostics.json",
    }
    assert json.loads((task_dir / "lineage.json").read_text())["schema_version"] == "1.0"


def test_core_cli_help_exposes_only_parse(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "parse" in help_text
    for upper_command in ("insight", "governance", "refactor-candidates"):
        assert upper_command not in help_text


def test_public_qualified_field_extractor() -> None:
    assert lineage_parser.extract_qualified_field_refs(
        "a.id + `b`.`amount` + named_struct('x', c.value).x"
    ) == [("b", "amount"), ("a", "id"), ("c", "value")]
