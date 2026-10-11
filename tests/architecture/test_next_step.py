"""The runbook's next-step driver (``skills/scope-lineage/scripts/next_step.py``).

An orchestrator that loses track of where a run stands skips steps, re-runs finished ones,
or stops at the key-fold ``ontology`` and calls it done. The driver reads only the files a
run directory already holds and prints the S0–S13 checklist, the current step, why it is
current, and -- while table semantics is in progress -- each table's next action from the
runbook's appendix A. It never recomputes a table's stage: it reads the ``status.json`` that
``semantic status --json`` wrote, and asks for a fresh one when that file is missing or
older than the documents, reviews and packets it summarises.

The tests run it as the runbook does -- a subprocess over a directory -- and pin the
mistakes a wrong answer would cause: a step reported done before its files exist, a stale
status read as current, a table's next action taken from the wrong row of appendix A, and a
first review with a high finding let through without its one re-review.

Every table here is made up (``demo_dwd.t1``, ``demo_dwd.t2``).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "skills" / "scope-lineage" / "scripts" / "next_step.py"
T1 = "demo_dwd.t1"
T2 = "demo_dwd.t2"


def _drive(run: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(run)], capture_output=True, text=True, encoding="utf-8"
    )


def _write(path: Path, text: str = "x\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _current(output: str) -> str:
    line = next(line for line in output.splitlines() if line.startswith("当前："))
    return line.removeprefix("当前：").split()[0]


def _status(run: Path, rows: list[dict]) -> Path:
    """Write status.json in the shape ``semantic status --json`` writes, newer than every input."""
    tables = []
    for row in rows:
        review = None
        if "high" in row:
            review = {"high": row["high"], "medium": row.get("medium", 0), "low": 0}
        tables.append({"table": row["table"], "stage": row["stage"], "flags": row.get("flags", []), "review": review})
    path = _write(run / "status.json", json.dumps({"doc_format": "table-semantics-status/2", "tables": tables}))
    later = time.time() + 5
    os.utime(path, (later, later))
    return path


@pytest.fixture
def run(tmp_path: Path) -> Path:
    """A run directory finished through S0."""
    directory = tmp_path / "run"
    _write(directory / "env.sh", "export Q=\n")
    _write(directory / "TOOL_VERSION", "scope-lineage 0.9.0\n")
    _write(directory / "ledger.md", "# ledger\n")
    return directory


def _through_s3(run: Path, tables: tuple[str, ...] = (T1, T2)) -> None:
    _write(run / "artifacts" / "task_a" / "lineage.json", "{}")
    _write(run / "corpus" / "tables.json", "{}")
    _write(run / "corpus" / "glossary.json", "{}")
    _write(run / "tables.txt", "".join(t + "\n" for t in tables))
    for table in tables:
        _write(run / "packets" / table / "packet.json", "{}")


def _through_s9(run: Path) -> None:
    _through_s3(run)
    _status(run, [{"table": T1, "stage": "rendered"}, {"table": T2, "stage": "rendered"}])


def test_a_missing_run_directory_exits_2(tmp_path):
    result = _drive(tmp_path / "nowhere")
    assert result.returncode == 2
    assert "nowhere" in result.stderr


def test_an_empty_run_directory_is_at_s0(tmp_path):
    directory = tmp_path / "run"
    directory.mkdir()
    result = _drive(directory)
    assert result.returncode == 0
    assert _current(result.stdout) == "S0"


def test_the_checklist_marks_done_steps_and_the_current_one(run):
    _write(run / "artifacts" / "task_a" / "lineage.json", "{}")
    out = _drive(run).stdout
    assert "[x] S0" in out
    assert "[x] S1" in out
    assert "[ ] S2" in out and "← 当前" in out.split("[ ] S2", 1)[1].splitlines()[0]
    assert "[ ] S3" in out
    assert _current(out) == "S2"


def test_s1_is_not_done_until_a_lineage_json_exists(run):
    (run / "artifacts" / "task_a").mkdir(parents=True)
    assert _current(_drive(run).stdout) == "S1"


def test_s3_is_not_done_while_a_table_in_tables_txt_has_no_packet(run):
    _through_s3(run)
    (run / "packets" / T2 / "packet.json").unlink()
    out = _drive(run).stdout
    assert _current(out) == "S3"
    assert T2 in out


def test_table_semantics_without_a_status_file_asks_for_one(run):
    _through_s3(run)
    out = _drive(run).stdout
    assert _current(out) == "刷新状态"
    assert "semantic status" in out and "--json" in out
    # Without a status nothing between S4 and S9 is known: none is marked done or current.
    assert "[?] S4" in out and "[?] S9" in out
    assert "← 当前" not in out


def test_a_status_file_older_than_a_document_is_not_trusted(run):
    _through_s3(run)
    status = _status(run, [{"table": T1, "stage": "valid"}, {"table": T2, "stage": "valid"}])
    doc = _write(run / "docs" / f"{T1}.json", "{}")
    newer = status.stat().st_mtime + 10
    os.utime(doc, (newer, newer))
    out = _drive(run).stdout
    assert "status.json" in out and "旧" in out
    assert _current(out) == "刷新状态"


def test_a_status_file_written_before_rendering_is_not_trusted(run):
    # S9 runs status for its gate, then renders: the pages move every table to rendered.
    _through_s3(run)
    status = _status(run, [{"table": T1, "stage": "fixed"}, {"table": T2, "stage": "fixed"}])
    page = _write(run / "site" / "semantics" / f"{T1}.md")
    newer = status.stat().st_mtime + 10
    os.utime(page, (newer, newer))
    out = _drive(run).stdout
    assert "status.json" in out and "旧" in out
    assert _current(out) == "刷新状态"


def test_each_table_gets_its_appendix_a_action(run):
    _through_s3(run)
    _status(run, [{"table": T1, "stage": "packet"}, {"table": T2, "stage": "reviewed", "high": 0, "medium": 1}])
    out = _drive(run).stdout
    assert _current(out) == "S4"
    lines = {line.split()[0]: line for line in out.splitlines() if line.startswith("  demo_dwd.")}
    assert "S4" in lines[T1] and "T1" in lines[T1]
    assert "S7" in lines[T2] and "T4" in lines[T2]


def test_a_rewrite_needs_its_preparation_first(run):
    _through_s3(run, (T1,))
    _status(run, [{"table": T1, "stage": "drafted", "flags": ["packet_stale"]}])
    line = next(line for line in _drive(run).stdout.splitlines() if line.startswith(f"  {T1}"))
    assert "重写准备" in line


def test_a_valid_table_with_an_old_review_gets_the_rewrite_first_review(run):
    _through_s3(run, (T1,))
    _write(run / "reviews" / f"{T1}.prior.md")
    _status(run, [{"table": T1, "stage": "valid"}])
    line = next(line for line in _drive(run).stdout.splitlines() if line.startswith(f"  {T1}"))
    assert "S6" in line and "重写后首审" in line


def test_a_fixed_table_whose_first_review_had_a_high_finding_needs_one_re_review(run):
    _through_s3(run, (T1,))
    _status(run, [{"table": T1, "stage": "fixed", "high": 1}])
    out = _drive(run).stdout
    assert _current(out) == "S8"
    line = next(line for line in out.splitlines() if line.startswith(f"  {T1}"))
    assert "T3" in line and "round1" in line


def test_a_re_reviewed_table_is_not_sent_back_to_s8(run):
    _through_s3(run, (T1,))
    _write(run / "reviews_prev" / f"{T1}.round1.md")
    _status(run, [{"table": T1, "stage": "fixed", "high": 0}])
    assert _current(_drive(run).stdout) == "S9"


def test_a_misfiled_document_stops_the_run(run):
    _through_s3(run, (T1,))
    _status(run, [{"table": T1, "stage": "valid", "flags": ["doc_misfiled"]}])
    line = next(line for line in _drive(run).stdout.splitlines() if line.startswith(f"  {T1}"))
    assert "doc_misfiled" in line and "停" in line


def test_blocked_tables_are_left_out(run):
    _through_s3(run, (T1,))
    _write(run / "blocked.txt", f"{T2}\n")
    _status(run, [{"table": T1, "stage": "rendered"}])
    out = _drive(run).stdout
    assert T2 not in [line.split()[0] for line in out.splitlines() if line.startswith("  demo_dwd.")]
    assert _current(out) == "S10a"


def test_all_tables_rendered_moves_to_the_catalog(run):
    _through_s9(run)
    out = _drive(run).stdout
    assert "[x] S9" in out
    assert _current(out) == "S10a"


def test_catalog_steps_follow_their_files(run):
    _through_s9(run)
    _write(run / "catalog" / "catalog.json", "{}")
    assert _current(_drive(run).stdout) == "S10b"
    _write(run / "digest" / "digest.md")
    assert _current(_drive(run).stdout) == "S10c"
    _write(run / "catalog_plan.md", "# 片段分组方案\n\n## 组 main\n\n## 组 party\n\n## 跨组属性\n")
    _write(run / "fragments" / "main.json", "{}")
    out = _drive(run).stdout
    assert _current(out) == "S10d"
    assert "party" in out
    _write(run / "fragments" / "party.json", "{}")
    assert _current(_drive(run).stdout) == "S10e"
    _write(run / "merged" / "catalog.json", "{}")
    _write(run / "merge_report.txt")
    assert _current(_drive(run).stdout) == "S10f"
    _write(run / "catalog_changes.md")
    assert _current(_drive(run).stdout) == "S10g"


def _through_s10(run: Path) -> None:
    _through_s9(run)
    _write(run / "catalog" / "catalog.json", "{}")
    _write(run / "digest" / "digest.md")
    _write(run / "catalog_plan.md", "## 组 main\n")
    _write(run / "fragments" / "main.json", "{}")
    _write(run / "merged" / "catalog.json", "{}")
    _write(run / "merge_report.txt")
    _write(run / "catalog_changes.md")
    _write(run / "onto" / "ontology.json", "{}")
    _write(run / "site" / "concepts" / "c.md")


def test_without_a_question_set_s11_is_skipped(run):
    _through_s10(run)
    out = _drive(run).stdout
    assert "[-] S11" in out
    assert _current(out) == "S13"


def test_with_a_question_set_s11_waits_for_a_score(run):
    _through_s10(run)
    _write(run / "env.sh", "export Q=/abs/questions   # 回归题集\n")
    assert _current(_drive(run).stdout) == "S11"
    _write(run / "round1" / "score" / "score.json", "{}")
    assert _current(_drive(run).stdout) == "S13"


def test_a_delivered_run_is_done(run):
    _through_s10(run)
    _write(run / "RESULT.md")
    out = _drive(run).stdout
    assert "[x] S13" in out
    assert _current(out) == "完成"


def test_the_current_step_names_the_runbook_section_to_read(run):
    out = _drive(run).stdout
    assert "runbook.md" in out
    assert "S1 血缘解析" in out
