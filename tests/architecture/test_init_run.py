"""``scripts/init_run.py`` writes ``env.sh``; nobody copies it out of the runbook.

Hand-writing the file went wrong in the trial runs (a heredoc expanded ``$RUN`` on the
spot; the Write tool was blocked). The script takes the paths as arguments and writes
them quoted, so a value with a space or a ``$`` arrives as it was given.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "scope-lineage-ontology"
LINEAGE = ROOT / "skills" / "scope-lineage"
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
    assert _show(shell, env_file, "RUN", "TASKS", "SCHEMA", "SKILL", "LINEAGE_SKILL", "TOOL", "PAGES", "SEMPAGES", "DDL") == [
        str(run), "/data/tasks", "/data/schema", str(SKILL), str(LINEAGE), str(ROOT), f"{run}/site", f"{run}/site/semantics", ""]
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
    skill = tmp_path / "skills" / "scope-lineage-ontology"
    shutil.copytree(SKILL, skill)
    shutil.copytree(LINEAGE, tmp_path / "skills" / "scope-lineage")
    run = tmp_path / "run"
    done = subprocess.run([sys.executable, str(skill / "scripts" / "init_run.py"), "--run", str(run), "--scratch",
                           str(tmp_path / "s"), "--tasks", "/t", "--schema", "/s"], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert _show("bash", run / "env.sh", "TOOL", "SKILL", "LINEAGE_SKILL") == ["", str(skill), str(tmp_path / "skills" / "scope-lineage")]


def test_without_the_lineage_skill_beside_it_the_run_is_refused(tmp_path):
    skill = tmp_path / "skills" / "scope-lineage-ontology"
    shutil.copytree(SKILL, skill)
    run = tmp_path / "run"
    done = subprocess.run([sys.executable, str(skill / "scripts" / "init_run.py"), "--run", str(run), "--scratch",
                           str(tmp_path / "s"), "--tasks", "/t", "--schema", "/s"], capture_output=True, text=True)
    assert done.returncode == 1 and "--lineage-skill" in done.stderr and not (run / "env.sh").exists()


def test_the_lineage_skill_can_be_given(tmp_path):
    skill = tmp_path / "a" / "scope-lineage-ontology"
    shutil.copytree(SKILL, skill)
    lineage = tmp_path / "b" / "lineage"
    shutil.copytree(LINEAGE, lineage)
    run = tmp_path / "run"
    done = subprocess.run([sys.executable, str(skill / "scripts" / "init_run.py"), "--run", str(run), "--scratch",
                           str(tmp_path / "s"), "--tasks", "/t", "--schema", "/s", "--lineage-skill", str(lineage)],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert _show("bash", run / "env.sh", "LINEAGE_SKILL") == [str(lineage)]


def _args(tmp_path, run):
    return ("--run", str(run), "--scratch", str(tmp_path / "s"), "--tasks", "/t", "--schema", "/s")


def test_the_ledger_is_written_with_the_run_and_ends_with_the_running_log(tmp_path):
    run = tmp_path / "run-20260101"
    assert _init(*_args(tmp_path, run)).returncode == 0
    ledger = (run / "ledger.md").read_text(encoding="utf-8")
    assert ledger.startswith("# 运行账本：run-20260101\n")
    assert "```" not in ledger and "demo_dwd" not in ledger            # the template's fence and its example row stay out
    assert ledger.rstrip().splitlines()[-1].startswith("## 流水")
    for section in ("## 表进度", "## 派发记录", "## blocked", "## 给 owner 的待确认", "## 问题清单"):
        assert section in ledger
    done = subprocess.run(["bash", "-c", f'. {shlex.quote(str(run / "env.sh"))} && note "S0 建好运行目录"'], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert (run / "ledger.md").read_text(encoding="utf-8").rstrip().endswith("S0 建好运行目录")


def test_an_existing_ledger_is_kept(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "ledger.md").write_text("# 已有的账本\n", encoding="utf-8")
    assert _init(*_args(tmp_path, run)).returncode == 0
    assert (run / "ledger.md").read_text(encoding="utf-8") == "# 已有的账本\n"


def test_a_refused_run_writes_no_ledger(tmp_path):
    run = tmp_path / "run"
    done = _init("--run", str(run), "--scratch", str(run / "scratch"), "--tasks", "/t", "--schema", "/s")
    assert done.returncode == 1 and not (run / "ledger.md").exists()


@pytest.mark.parametrize("shell", SHELLS)
def test_the_number_of_review_passes_is_one_unless_asked(shell, tmp_path):
    base = ("--scratch", str(tmp_path / "s"), "--tasks", "/t", "--schema", "/s")
    assert _init("--run", str(tmp_path / "a"), *base).returncode == 0
    assert _init("--run", str(tmp_path / "b"), *base, "--review-passes", "2").returncode == 0
    assert _show(shell, tmp_path / "a" / "env.sh", "REVIEW_PASSES") == ["1"]
    assert _show(shell, tmp_path / "b" / "env.sh", "REVIEW_PASSES") == ["2"]


def test_three_review_passes_are_refused(tmp_path):
    done = _init("--run", str(tmp_path / "a"), "--scratch", str(tmp_path / "s"), "--tasks", "/t", "--schema", "/s",
                 "--review-passes", "3")
    assert done.returncode != 0 and not (tmp_path / "a" / "env.sh").exists()


# ------------------------------------------------- 5.3: the run's domain profile

_CLEAN_ENV = {key: value for key, value in os.environ.items() if key != "SCOPE_LINEAGE_DOMAIN_PROFILE"}
_PROBE = (
    "import argparse, sys; sys.path.insert(0, sys.argv[1]); "
    "from scope_lineage.cli_semantic import read_domain_profile; "
    "p = read_domain_profile(argparse.Namespace(domain_profile=None)); "
    "print(p if isinstance(p, int) else (p.qualifier_terms, p.name_convention))"
)


def _sourced(shell, env_file: Path, command: str, env=None) -> str:
    done = subprocess.run([shell, "-c", f". {shlex.quote(str(env_file))} && {command}"],
                          capture_output=True, text=True, env=_CLEAN_ENV if env is None else env)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def _profile_after_sourcing(shell, env_file: Path) -> str:
    """What a tool command started from a sourced env.sh reads as its domain profile."""
    return _sourced(shell, env_file, f"{shlex.quote(sys.executable)} -c {shlex.quote(_PROBE)} {shlex.quote(str(ROOT))}")


@pytest.mark.parametrize("shell", SHELLS)
def test_the_domain_profile_reaches_every_tool_command_through_the_environment(shell, tmp_path):
    profile = tmp_path / "my profile.json"
    profile.write_text('{"doc_format": "domain-profile/1", "qualifier_terms": ["冲正"], '
                       '"table_name_convention": {"full": ["df"]}}', encoding="utf-8")
    run = tmp_path / "run"
    done = _init(*_args(tmp_path, run), "--domain-profile", str(profile))
    assert done.returncode == 0, done.stderr
    assert _sourced(shell, run / "env.sh", 'printf "%s|%s" "$DOMAIN_PROFILE" "$SCOPE_LINEAGE_DOMAIN_PROFILE"') == (
        f"{profile}|{profile}")
    assert _profile_after_sourcing(shell, run / "env.sh") == "(('冲正',), {'full': ('df',)})"


@pytest.mark.parametrize("shell", SHELLS)
def test_without_a_domain_profile_the_variable_is_left_unset(shell, tmp_path):
    run = tmp_path / "run"
    assert _init(*_args(tmp_path, run)).returncode == 0
    script = '[ -z "$DOMAIN_PROFILE" ] && [ -z "${SCOPE_LINEAGE_DOMAIN_PROFILE+x}" ] && echo unset'
    assert _sourced(shell, run / "env.sh", script) == "unset"
    assert _profile_after_sourcing(shell, run / "env.sh") == "((), None)"
    # A profile left in the shell from another run does not leak into this one.
    leftover = {**_CLEAN_ENV, "SCOPE_LINEAGE_DOMAIN_PROFILE": str(tmp_path / "other.json")}
    assert _sourced(shell, run / "env.sh", script, env=leftover) == "unset"


def test_a_missing_domain_profile_is_refused(tmp_path):
    run = tmp_path / "run"
    done = _init(*_args(tmp_path, run), "--domain-profile", str(tmp_path / "absent.json"))
    assert done.returncode == 1 and "--domain-profile" in done.stderr and not (run / "env.sh").exists()
