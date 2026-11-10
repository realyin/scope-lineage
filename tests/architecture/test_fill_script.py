"""``scripts/fill.py`` and ``scripts/runlib.sh``: the run's shell functions as files.

``fill``, ``sl``, ``load_tables`` and ``note`` used to be 108 lines the orchestrator copied
out of the runbook into ``env.sh``, and the tests had to cut ``fill`` out of the Markdown to
run it. They are scripts now. What a subagent is told must not have moved with them: every
template and mode is compared with the prompt 0.11.2 produced.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from .fill_cases import CASES, render_all

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "scope-lineage"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SHELLS = [
    pytest.param(shell, marks=pytest.mark.skipif(shutil.which(shell) is None, reason=f"{shell} is not installed"))
    for shell in ("bash", "zsh")
]


def _env(run: Path, scratch: Path, **extra) -> dict[str, str]:
    return dict(os.environ, TOOL="", SKILL=str(SKILL), SCHEMAS="/SCHEMAS", RUN=str(run), SCRATCH=str(scratch),
                TASKS="/TASKS", PAGES="/RUN/site", SEMPAGES="/RUN/site/semantics", **extra)


def _runner(shell: str, script: Path):
    def fill(run, scratch, *args):
        return subprocess.run([shell, str(script), *args], env=_env(run, scratch), capture_output=True, text=True)
    return fill


@pytest.mark.parametrize("shell", SHELLS)
def test_fill_tells_each_subagent_what_0_11_2_told_it(shell, tmp_path):
    script = tmp_path / "f.sh"
    script.write_text(f'. "{SKILL}/scripts/runlib.sh"\nfill "$@"\n', encoding="utf-8")
    rendered = render_all(_runner(shell, script), tmp_path, SKILL)
    assert sorted(rendered) == sorted(CASES)
    for case, text in rendered.items():
        assert text == (FIXTURES / "fill_golden" / f"{case}.md").read_text(encoding="utf-8"), case


@pytest.mark.parametrize("shell", SHELLS)
def test_an_env_written_from_the_0_11_2_runbook_takes_the_scripts_with_one_line(shell, tmp_path):
    """A run directory started before the split keeps its ``env.sh``: the functions it
    carries are replaced by sourcing ``runlib.sh`` after them."""
    run, scratch = tmp_path / "run", tmp_path / "scratch"
    (run / "reviews").mkdir(parents=True)
    (run / "reviews" / "demo_x.t.md").write_text("review\n", encoding="utf-8")
    old = (FIXTURES / "env_0_11_2.sh").read_text(encoding="utf-8")
    old = old.replace("/abs/path/to/scope-lineage ", f"{ROOT} ").replace("/abs/path/to/runs/run-20260101 ", f"{run} ")
    old = old.replace("/abs/path/to/scratchpad/run-20260101 ", f"{scratch} ")
    assert str(ROOT) in old and str(run) in old and str(scratch) in old
    script = tmp_path / "env.sh"
    script.write_text(old + '. "$SKILL/scripts/runlib.sh"\nfill "$@"\n', encoding="utf-8")
    out = tmp_path / "t4.md"
    done = subprocess.run([shell, str(script), "fix", str(out), "TABLE=demo_x.t", "MODE=首修", "FACTS=无"],
                          env={k: v for k, v in os.environ.items() if k not in ("SKILL", "TOOL", "RUN", "SCHEMAS")},
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert "python3 - " not in subprocess.run([shell, "-c", f'. "{script}" x x >/dev/null 2>&1; type fill'],
                                              capture_output=True, text=True).stdout
    assert f"{SKILL}/references/table-semantics-fix-prompt.md" in out.read_text(encoding="utf-8")


def test_fill_is_not_carried_inside_the_runbook():
    text = (SKILL / "references" / "runbook.md").read_text(encoding="utf-8")
    assert "<<'PY'\nimport os, re, sys" not in text and "fill() {" not in text


@pytest.mark.parametrize("shell", SHELLS)
def test_runlib_gives_note_and_load_tables(shell, tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "tables.txt").write_text("demo_x.a\n\ndemo_x.b\n", encoding="utf-8")
    script = tmp_path / "n.sh"
    script.write_text(f'. "{SKILL}/scripts/runlib.sh"\nload_tables && note "S3 选表 ${{#TABLES[@]}}"\n', encoding="utf-8")
    done = subprocess.run([shell, str(script)], env=_env(run, tmp_path / "s"), capture_output=True, text=True)
    assert done.returncode == 0 and "tables=2" in done.stdout, done.stderr
    assert (run / "ledger.md").read_text(encoding="utf-8").rstrip().endswith("S3 选表 2")
