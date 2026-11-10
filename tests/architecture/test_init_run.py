"""``scripts/init_run.py`` writes ``env.sh``; nobody copies it out of the runbook.

Hand-writing the file went wrong in the trial runs (a heredoc expanded ``$RUN`` on the
spot; the Write tool was blocked). The script takes the paths as arguments and writes
them quoted, so a value with a space or a ``$`` arrives as it was given.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "scope-lineage"
INIT = SKILL / "scripts" / "init_run.py"
SHELLS = [
    pytest.param(shell, marks=pytest.mark.skipif(shutil.which(shell) is None, reason=f"{shell} is not installed"))
    for shell in ("bash", "zsh")
]


def _init(*args):
    return subprocess.run([sys.executable, str(INIT), *args], capture_output=True, text=True)


def _show(shell, env_file: Path, *names: str) -> list[str]:
    script = "; ".join(f'printf "%s\\n" "${name}"' for name in names)
    done = subprocess.run([shell, "-c", f'. {shlex.quote(str(env_file))} && {script}'], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout.splitlines()


@pytest.mark.parametrize("shell", SHELLS)
def test_the_written_env_defines_the_paths_and_the_four_functions(shell, tmp_path):
    run = tmp_path / "run"
    done = _init("--run", str(run), "--scratch", str(tmp_path / "scratch"), "--tasks", "/data/tasks", "--schema", "/data/schema")
    assert done.returncode == 0, done.stderr
    env_file = run / "env.sh"
    assert _show(shell, env_file, "RUN", "TASKS", "SCHEMA", "SKILL", "TOOL", "PAGES", "SEMPAGES", "DDL") == [
        str(run), "/data/tasks", "/data/schema", str(SKILL), str(ROOT), f"{run}/site", f"{run}/site/semantics", ""]
    done = subprocess.run([shell, "-c", f'. {shlex.quote(str(env_file))} && type sl fill note load_tables >/dev/null && echo ok'],
                          capture_output=True, text=True)
    assert done.stdout.strip() == "ok", done.stderr


@pytest.mark.parametrize("shell", SHELLS)
def test_a_space_or_a_dollar_in_a_path_arrives_as_given(shell, tmp_path):
    run = tmp_path / "my run $HOME"
    done = _init("--run", str(run), "--scratch", str(tmp_path / "s p"), "--tasks", "/data/$TASKS dir", "--schema", "/s")
    assert done.returncode == 0, done.stderr
    assert _show(shell, run / "env.sh", "RUN", "TASKS", "SCRATCH") == [str(run), "/data/$TASKS dir", str(tmp_path / "s p")]


def test_the_env_is_short_and_carries_no_code(tmp_path):
    run = tmp_path / "run"
    assert _init("--run", str(run), "--scratch", str(tmp_path / "s"), "--tasks", "/t", "--schema", "/s").returncode == 0
    text = (run / "env.sh").read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 30 and "<<" not in text and "runlib.sh" in text


def test_an_existing_env_is_not_overwritten(tmp_path):
    run = tmp_path / "run"
    args = ("--run", str(run), "--scratch", str(tmp_path / "s"), "--tasks", "/t", "--schema", "/s")
    assert _init(*args).returncode == 0
    (run / "env.sh").write_text("# edited by the owner\n", encoding="utf-8")
    again = _init(*args)
    assert again.returncode == 1 and "env.sh" in again.stderr
    assert (run / "env.sh").read_text(encoding="utf-8") == "# edited by the owner\n"


def test_scratch_inside_the_run_directory_is_refused(tmp_path):
    run = tmp_path / "run"
    done = _init("--run", str(run), "--scratch", str(run / "scratch"), "--tasks", "/t", "--schema", "/s")
    assert done.returncode == 1 and "SCRATCH" in done.stderr and not (run / "env.sh").exists()


def test_a_skill_installed_apart_from_the_tool_leaves_tool_empty(tmp_path):
    skill = tmp_path / "skills" / "scope-lineage"
    shutil.copytree(SKILL, skill)
    run = tmp_path / "run"
    done = subprocess.run([sys.executable, str(skill / "scripts" / "init_run.py"), "--run", str(run), "--scratch",
                           str(tmp_path / "s"), "--tasks", "/t", "--schema", "/s"], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert _show("bash", run / "env.sh", "TOOL", "SKILL") == ["", str(skill)]
