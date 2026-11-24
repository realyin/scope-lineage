"""S9b, the optional runbook step that writes platform queries for the open questions.

After S9 one agent (template T-probes) writes ``$RUN/probes/question-probes.json``
(``question-probes/1``); the orchestrator holds it to ``semantic probes check`` and hands it
to the person who runs the queries. The tool never runs one. These tests pin the step's
text, the template's fixed output forms, ``fill``'s premises, and the progress script's
rule: S9b is never the current step, it only asks for the check when the queries are newer
than the report or have none.

Every table here is made up (``demo_dwd.t1``; the template's examples use the demo corpus
names).
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pytest

from .test_next_step import _current, _drive, _through_s9, _write
from .test_runbook_fill import REFS, SHELLS, _fill, _touch

PROBES = "probes/question-probes.json"
REPORT = "probes/check.txt"
PROBES_CHECK = ('sl semantic probes check "$RUN/probes/question-probes.json" --packets "$RUN/packets" '
                '--docs "$RUN/docs"')


@pytest.fixture
def run(tmp_path: Path) -> Path:
    """A run directory finished through S0, as in test_next_step."""
    directory = tmp_path / "run"
    _write(directory / "env.sh", "export Q=\n")
    _write(directory / "TOOL_VERSION", "scope-lineage 0.9.0\n")
    _write(directory / "ledger.md", "# ledger\n")
    return directory


def _later(path: Path, seconds: float) -> Path:
    moment = time.time() + seconds
    os.utime(path, (moment, moment))
    return path


def _prompt(name: str) -> str:
    return (REFS / name).read_text(encoding="utf-8").split("----8<----", 2)[1]


def _probes_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith("S9b（可选") or "semantic probes check" in line]


# ---- next_step.py --------------------------------------------------------------------

def test_without_a_probes_file_s9b_is_skipped_and_nothing_is_said(run):
    _through_s9(run)
    out = _drive(run).stdout
    assert "[-] S9b" in out
    assert _probes_lines(out) == []


@pytest.mark.parametrize("report", [None, "older"])
def test_queries_without_a_fresh_check_report_get_the_check_command(run, report):
    _through_s9(run)
    before = _current(_drive(run).stdout)
    probes = _write(run / PROBES, "{}")
    if report == "older":
        _write(run / REPORT, "RESULT: PASS (0 failure(s), 0 warning(s))\n")
        _later(probes, 3)
    out = _drive(run).stdout
    assert _current(out) == before            # optional: the current step does not move
    assert "[ ] S9b" in out
    assert ("还没有检查报告" if report is None else "比检查报告") in out
    assert PROBES_CHECK + ' > "$RUN/probes/check.txt"' in out


def test_a_check_report_newer_than_the_queries_marks_s9b_done(run):
    _through_s9(run)
    _write(run / PROBES, "{}")
    _later(_write(run / REPORT, "RESULT: PASS (0 failure(s), 0 warning(s))\n"), 3)
    out = _drive(run).stdout
    assert "[x] S9b" in out
    assert _probes_lines(out) == []


def test_queries_do_not_make_the_status_file_stale(run):
    _through_s9(run)                            # status.json written 5 seconds ahead
    _later(_write(run / PROBES, "{}"), 8)
    _later(_write(run / REPORT, "x\n"), 9)
    assert _current(_drive(run).stdout) == "S10a"


# ---- fill and the step text ----------------------------------------------------------

@pytest.mark.parametrize("shell", SHELLS)
def test_the_probes_writer_waits_for_s9_and_rework_needs_the_file(shell, tmp_path):
    directory = tmp_path / "run"
    directory.mkdir()
    out = str(tmp_path / "o.md")
    done = _fill(shell, directory, "probes", out, "MODE=首写", "REWORK=无")
    assert done.returncode == 1 and "validation.json" in done.stderr
    _touch(directory / "validation.json")
    assert _fill(shell, directory, "probes", out, "MODE=首写", "REWORK=无").returncode == 0
    done = _fill(shell, directory, "probes", out, "MODE=返工", "REWORK=一行 FAIL")
    assert done.returncode == 1 and "question-probes.json" in done.stderr


def test_s9b_checks_the_queries_and_never_runs_them():
    s9b = (REFS / "steps" / "S9b.md").read_text(encoding="utf-8")
    assert PROBES_CHECK + ' > "$RUN/probes/check.txt"' in s9b
    assert "从不执行 SQL" in s9b and "可选" in s9b
    assert "sensitive-columns.txt" in s9b and "MODE=返工" in s9b and "最多两轮" in s9b
    assert "sql_id, status, run_on, bizdate, sql_executed, columns, rows, note" in s9b
    assert "S12" in s9b[s9b.index("**下一步**"):]
    assert PROBES_CHECK in _prompt("templates/T-probes.md")


def test_the_probes_writer_is_given_the_fixed_output_columns():
    """Only a uniqueness or value-set query can land as an observation, and only through its
    fixed output columns (``rows, keys, duplicate_keys``; ``value, cnt`` under ``LIMIT 51``):
    the worked examples must be of those forms and fill every field a query item needs."""
    body = _prompt("templates/T-probes.md")
    for rule in ("一字不改", "LIMIT 51", "`rows` 是行数（**一定要输出**", "latest_available", "`full_scan`",
                 "`engine`", "`placeholders`", "`data`", "`human`", "`corpus`", "标识类列不做取值清单"):
        assert rule in body, rule
    example = json.loads(re.search(r"```json\n(.*?)```", body, re.S).group(1))
    assert example["doc_format"] == "question-probes/1"
    items = example["items"]
    lands = {item.get("lands") for item in items}
    assert {"summary.row.observed", "column:gender_cd.observed_values"} <= lands
    assert any(str(target).startswith("input:") for target in lands)
    for item in items:
        if item["class"] != "data":
            assert "note" in item and "sql" not in item and "lands" not in item
            continue
        assert item["engine"] == "spark" and item["partitions"] and item["how_to_read"]
        assert all(name in example["placeholders"] for name in re.findall(r"\$\{\w+\}", item["sql"]))
        sql = item["sql"]
        if item["shape"] == "uniqueness":
            assert re.search(r"SELECT .*\brows\b.*\bkeys\b.*\bduplicate_keys\b FROM", sql), sql
        else:
            assert item["shape"] == "value_set"
            assert " AS value, COUNT(*) AS cnt " in sql and sql.endswith("LIMIT 51")
