"""``parse`` says not just how many tasks came back partial, but why.

``partial_tasks=7`` at the end of a corpus run is a number an operator cannot act on: it
could be seven unsupported SELECTs to ignore or seven lineage gaps to investigate, and
finding out meant opening seven ``diagnostics.json`` files. The breakdown is the same
fact the artifacts already carry -- each task's ``analysis_status.blocking_reasons`` --
counted once per task and printed beside the total.
"""

from __future__ import annotations

import json
from pathlib import Path

from scope_lineage.cli import main


def _write_task(path: Path, task_name: str, sql: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"meta": {"task_name": task_name, "sql": sql}}), encoding="utf-8"
    )


def _parse(tmp_path: Path, out: str) -> str:
    assert (
        main(
            [
                "parse",
                "--input-dir",
                str(tmp_path / "tasks"),
                "--out",
                str(tmp_path / out),
                "--allow-partial",
            ]
        )
        in (0, 1)
    )
    return ""


def test_two_partial_tasks_are_broken_down_by_reason(tmp_path: Path, capsys) -> None:
    _write_task(tmp_path / "tasks" / "a.json", "read_only", "SELECT id FROM ods.source")
    _write_task(tmp_path / "tasks" / "b.json", "dropper", "DROP DATABASE mart")

    _parse(tmp_path, "out")

    report = capsys.readouterr().out
    assert "partial_tasks=2" in report
    assert (
        "partial_reasons=unsupported_data_change:1,unsupported_statement:1" in report
    )


def test_the_same_reason_twice_is_counted_twice(tmp_path: Path, capsys) -> None:
    """One count per task, so the breakdown adds up to `partial_tasks`."""
    _write_task(tmp_path / "tasks" / "a.json", "read_a", "SELECT id FROM ods.source")
    _write_task(tmp_path / "tasks" / "b.json", "read_b", "SELECT id FROM ods.other")

    _parse(tmp_path, "out")

    report = capsys.readouterr().out
    assert "partial_tasks=2" in report
    assert "partial_reasons=unsupported_statement:2" in report


def test_one_task_with_two_reasons_is_counted_under_both(
    tmp_path: Path, capsys
) -> None:
    _write_task(
        tmp_path / "tasks" / "a.json",
        "mixed",
        "DROP DATABASE mart; SELECT id FROM ods.source",
    )

    _parse(tmp_path, "out")

    report = capsys.readouterr().out
    assert "partial_tasks=1" in report
    assert (
        "partial_reasons=unsupported_data_change:1,unsupported_statement:1" in report
    )


def test_a_corpus_with_nothing_partial_says_nothing(tmp_path: Path, capsys) -> None:
    """A breakdown that is always printed is a breakdown nobody reads."""
    _write_task(
        tmp_path / "tasks" / "a.json",
        "clean",
        "INSERT INTO mart.t SELECT id FROM ods.source",
    )

    _parse(tmp_path, "out")

    report = capsys.readouterr().out
    assert "partial_tasks=0" in report
    assert "partial_reasons" not in report
