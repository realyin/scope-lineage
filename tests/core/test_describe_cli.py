"""End-to-end tests for ``scope-lineage describe``.

The library is not done until the CLI that exposes it is wired and tested, so every
option of the subcommand is exercised against real artifacts written by ``parse`` --
single file, corpus tree, ``--out`` mirroring, ``--format``, the unsupported-version
exit code and the missing-diagnostics counter.

``describe`` shares its input walk with ``render`` (``cli._discover_lineage_documents``
and ``cli._load_contract_documents``), so the last test here pins that sharing: the two
commands must agree on what they skip and what they count.
"""

from __future__ import annotations

import json
from pathlib import Path

from scope_lineage.cli import main

from .statement_document import write_statement_documents
from scope_lineage.scope.scope_builder import parse_scope_lineage


SIMPLE_SQL = "INSERT INTO mart.t SELECT id FROM ods.users"
SIMPLE_SCHEMA = {"ods.users": ["id"]}


def _write_artifacts(sql: str, out_dir: Path, schema=None) -> Path:
    result = parse_scope_lineage(sql, out_dir.name, schema=schema)
    write_statement_documents(result, out_dir)
    return out_dir


def test_describe_writes_both_artifacts_next_to_lineage(tmp_path: Path, capsys) -> None:
    task_dir = _write_artifacts(SIMPLE_SQL, tmp_path / "task_a", schema=SIMPLE_SCHEMA)

    assert main(["describe", "--lineage", str(task_dir / "lineage.json")]) == 0

    profile = json.loads((task_dir / "semantic.json").read_text(encoding="utf-8"))
    assert profile["doc_format"] == "semantic-json/1"
    markdown = (task_dir / "semantic.md").read_text(encoding="utf-8")
    assert markdown.startswith("---\n")
    assert 'doc_format: "semantic-md/1"' in markdown
    assert "Described 1 task(s)" in capsys.readouterr().out


def test_describe_json_is_indented_and_newline_terminated(tmp_path: Path) -> None:
    """The file is diffed and read by people, and it is a text fixture like any other."""
    task_dir = _write_artifacts(SIMPLE_SQL, tmp_path / "task_a", schema=SIMPLE_SCHEMA)
    assert main(["describe", "--lineage", str(task_dir / "lineage.json")]) == 0

    raw = (task_dir / "semantic.json").read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert raw.startswith('{\n  "doc_format"')
    assert "\\u" not in raw  # ensure_ascii=False, so Chinese stays readable


def test_describe_directory_recurses_and_skips_unknown_documents(
    tmp_path: Path, capsys
) -> None:
    corpus = tmp_path / "corpus"
    _write_artifacts(SIMPLE_SQL, corpus / "nested" / "task_a", schema=SIMPLE_SCHEMA)
    unknown_dir = corpus / "task_unknown"
    unknown_dir.mkdir(parents=True)
    (unknown_dir / "lineage.json").write_text(
        json.dumps({"schema_version": "2.0"}), encoding="utf-8"
    )

    assert main(["describe", "--lineage", str(corpus)]) == 0

    assert (corpus / "nested" / "task_a" / "semantic.md").exists()
    assert not (unknown_dir / "semantic.md").exists()
    assert not (unknown_dir / "semantic.json").exists()
    out = capsys.readouterr().out
    assert "Described 1 task(s)" in out
    assert "skipped_unknown_version=1" in out


def test_describe_out_mirrors_the_input_tree(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    _write_artifacts(SIMPLE_SQL, corpus / "nested" / "task_a", schema=SIMPLE_SCHEMA)
    out = tmp_path / "docs"

    assert main(["describe", "--lineage", str(corpus), "--out", str(out)]) == 0

    assert (out / "nested" / "task_a" / "semantic.json").exists()
    assert (out / "nested" / "task_a" / "semantic.md").exists()
    assert not (corpus / "nested" / "task_a" / "semantic.md").exists()


def test_describe_format_md_writes_only_markdown(tmp_path: Path) -> None:
    task_dir = _write_artifacts(SIMPLE_SQL, tmp_path / "task_a", schema=SIMPLE_SCHEMA)

    assert (
        main(["describe", "--lineage", str(task_dir / "lineage.json"), "--format", "md"])
        == 0
    )

    assert (task_dir / "semantic.md").exists()
    assert not (task_dir / "semantic.json").exists()


def test_describe_format_json_writes_only_json(tmp_path: Path) -> None:
    task_dir = _write_artifacts(SIMPLE_SQL, tmp_path / "task_a", schema=SIMPLE_SCHEMA)

    assert (
        main(
            ["describe", "--lineage", str(task_dir / "lineage.json"), "--format", "json"]
        )
        == 0
    )

    assert (task_dir / "semantic.json").exists()
    assert not (task_dir / "semantic.md").exists()


def test_describe_rejects_an_unknown_format_name(tmp_path: Path, capsys) -> None:
    task_dir = _write_artifacts(SIMPLE_SQL, tmp_path / "task_a", schema=SIMPLE_SCHEMA)
    try:
        main(
            ["describe", "--lineage", str(task_dir / "lineage.json"), "--format", "yaml"]
        )
    except SystemExit as exit_error:
        assert exit_error.code == 2
    else:  # pragma: no cover - argparse always exits
        raise AssertionError("an unknown --format must not be accepted")
    assert "yaml" in capsys.readouterr().err


def test_describe_sections_filter_reaches_the_renderer(tmp_path: Path) -> None:
    task_dir = _write_artifacts(SIMPLE_SQL, tmp_path / "task_a", schema=SIMPLE_SCHEMA)

    assert (
        main(
            [
                "describe",
                "--lineage",
                str(task_dir / "lineage.json"),
                "--sections",
                "overview,agent",
            ]
        )
        == 0
    )

    markdown = (task_dir / "semantic.md").read_text(encoding="utf-8")
    assert "## 1. 任务概览" in markdown
    assert "## 7. 给 Agent 的说明" in markdown
    assert "## 5. 字段语义" not in markdown


def test_describe_rejects_unknown_schema_versions_for_a_named_file(
    tmp_path: Path, capsys
) -> None:
    unknown = tmp_path / "lineage.json"
    unknown.write_text(json.dumps({"schema_version": "3.0"}), encoding="utf-8")

    assert main(["describe", "--lineage", str(unknown)]) == 1

    error = capsys.readouterr().err
    assert "3.0" in error
    assert "semantic describer" in error
    assert not (tmp_path / "semantic.md").exists()


def test_describe_reports_a_missing_path_and_an_empty_tree(tmp_path: Path, capsys) -> None:
    assert main(["describe", "--lineage", str(tmp_path / "nope")]) == 2
    assert "does not exist" in capsys.readouterr().err

    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["describe", "--lineage", str(empty)]) == 1
    assert "no lineage.json found" in capsys.readouterr().err


def test_describe_counts_missing_diagnostics_and_still_writes(
    tmp_path: Path, capsys
) -> None:
    task_dir = _write_artifacts(SIMPLE_SQL, tmp_path / "task_a", schema=SIMPLE_SCHEMA)
    (task_dir / "diagnostics.json").unlink()

    assert main(["describe", "--lineage", str(task_dir / "lineage.json")]) == 0

    assert "missing_diagnostics=1" in capsys.readouterr().out
    profile = json.loads((task_dir / "semantic.json").read_text(encoding="utf-8"))
    assert profile["confidence"]["diagnostics_available"] is False
    # the honest degradation is stated, not silently reported as "no gaps"
    assert "⚠ 无 diagnostics 文档" in (task_dir / "semantic.md").read_text(encoding="utf-8")


def test_describe_renders_task_documents_written_by_parse(tmp_path: Path) -> None:
    sql_path = tmp_path / "demo.sql"
    sql_path.write_text("INSERT INTO mart.t SELECT id FROM ods.source", encoding="utf-8")
    out = tmp_path / "artifacts"
    assert main(["parse", "--sql-file", str(sql_path), "--out", str(out)]) == 0

    assert main(["describe", "--lineage", str(out)]) == 0

    markdown = (out / "demo" / "semantic.md").read_text(encoding="utf-8")
    assert markdown.startswith("# 任务语义描述：demo")
    assert "## stmt:001" in markdown
    profile = json.loads((out / "demo" / "semantic.json").read_text(encoding="utf-8"))
    assert profile["artifact_kind"] == "task_semantic"


def test_parse_still_writes_only_the_two_contract_files(tmp_path: Path) -> None:
    """``describe`` must not join ``parse``'s output set.

    The invariant itself is owned by
    ``test_public_api_and_cli.test_core_cli_writes_only_lineage_and_diagnostics``; it is
    restated here because this change adds a third and fourth derived artifact, and the
    obvious mistake is to make ``parse`` emit them too.
    """
    sql_path = tmp_path / "demo.sql"
    sql_path.write_text("INSERT INTO mart.t SELECT id FROM ods.source", encoding="utf-8")
    out = tmp_path / "artifacts"

    assert main(["parse", "--sql-file", str(sql_path), "--out", str(out)]) == 0

    assert {path.name for path in (out / "demo").iterdir()} == {
        "lineage.json",
        "diagnostics.json",
    }


def test_describe_and_render_walk_the_same_input(tmp_path: Path, capsys) -> None:
    """Both derived views share one walk, so both must skip and count identically."""
    corpus = tmp_path / "corpus"
    _write_artifacts(SIMPLE_SQL, corpus / "task_a", schema=SIMPLE_SCHEMA)
    _write_artifacts(
        "INSERT INTO mart.u SELECT id FROM ods.users", corpus / "task_b", schema=SIMPLE_SCHEMA
    )
    (corpus / "task_b" / "diagnostics.json").unlink()
    unknown_dir = corpus / "task_unknown"
    unknown_dir.mkdir(parents=True)
    (unknown_dir / "lineage.json").write_text(
        json.dumps({"schema_version": "9.9"}), encoding="utf-8"
    )

    assert main(["render", "--lineage", str(corpus)]) == 0
    render_out = capsys.readouterr().out
    assert main(["describe", "--lineage", str(corpus)]) == 0
    describe_out = capsys.readouterr().out

    counters = "(skipped_unknown_version=1, missing_diagnostics=1, skipped_unreadable=0)"
    assert f"Rendered 2 mapping document(s) {counters}" in render_out
    assert f"Described 2 task(s) {counters}" in describe_out
