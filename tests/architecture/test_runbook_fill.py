"""``fill`` (runbook 0.1) under bash and zsh, and every ``fill`` command the runbook prints.

The orchestrator fills the subagent templates T1–T8 with ``fill``; a filled template is
what a subagent is told. A wrong template, a mode from another template or a missing
premise (a re-review with no backed-up first review, a rewrite without its corrections
list) used to fill without a word. ``fill`` now reads each template's rules from the
``<!-- fill: … -->`` line under its heading and refuses those with exit 1. The function is
taken from the runbook itself and run in a fresh shell, as an orchestrator's Bash call
runs it; zsh is skipped where it is not installed.

The last test reads every ``fill`` command in the runbook and its templates and checks it
against the template it names, so a template change cannot leave a command behind.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REFS = ROOT / "skills" / "scope-lineage" / "references"
SHELLS = [
    pytest.param(shell, marks=pytest.mark.skipif(shutil.which(shell) is None, reason=f"{shell} is not installed"))
    for shell in ("bash", "zsh")
]
T = "demo_x.t"
WRITE = ("FACTS=无", "CONCEPT=不写 concept", "FAILURES=无")
AUTO = {"RUN", "TOOL", "SCRATCH", "TASKS", "PAGES", "SEMPAGES", "ENV", "ROUND_NAME"}


def _fill_source() -> str:
    text = (REFS / "runbook.md").read_text(encoding="utf-8")
    found = re.search(r"^fill\(\) \{.*?^PY\n\}$", text, re.S | re.M)
    assert found, "runbook 0.1 has no fill function"
    return found.group(0)


@pytest.fixture
def run(tmp_path):
    directory = tmp_path / "run"
    for name in ("docs", "reviews", "reviews_prev", "round1", "round2", "digest"):
        (directory / name).mkdir(parents=True)
    return directory


def _fill(shell, run, *args):
    script = run.parent / "f.sh"
    script.write_text(_fill_source() + '\nfill "$@"\n', encoding="utf-8")
    env = dict(os.environ, TOOL=str(ROOT), RUN=str(run), SCRATCH=str(run.parent / "scratch"),
               TASKS="/x", PAGES=str(run / "site"), SEMPAGES=str(run / "site/semantics"))
    return subprocess.run([shell, str(script), *args], env=env, capture_output=True, text=True)


def _touch(path: Path, text: str = "") -> Path:
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("shell", SHELLS)
def test_names_resolve_to_the_same_template(shell, run):
    _touch(run / f"reviews/{T}.md")
    outs = []
    for name in ("T4", "fix", "修订"):
        out = run.parent / f"{name}.md"
        done = _fill(shell, run, name, str(out), f"TABLE={T}", "MODE=核对", "FACTS=无")
        assert done.returncode == 0, done.stderr
        outs.append(out.read_text(encoding="utf-8"))
    assert outs[0] == outs[1] == outs[2]
    assert "fill:" not in outs[0]                     # the rule line stays out of the prompt


@pytest.mark.parametrize("shell", SHELLS)
def test_a_parameter_the_template_does_not_have_is_refused(shell, run):
    done = _fill(shell, run, "T3", str(run.parent / "o.md"), f"TABLE={T}", "MODE=首修", "FACTS=无")
    assert done.returncode == 1 and "{MODE}" in done.stderr


@pytest.mark.parametrize("shell", SHELLS)
def test_a_mode_from_another_template_is_refused(shell, run):
    _touch(run / f"reviews/{T}.md")
    done = _fill(shell, run, "fix", str(run.parent / "o.md"), f"TABLE={T}", "MODE=新写", "FACTS=无")
    assert done.returncode == 1 and "首修 / 核对" in done.stderr


@pytest.mark.parametrize("shell", SHELLS)
def test_rereview_needs_the_backed_up_first_review(shell, run):
    done = _fill(shell, run, "rereview", str(run.parent / "o.md"), f"TABLE={T}", "FACTS=无")
    assert done.returncode == 1 and "reviews_prev" in done.stderr


@pytest.mark.parametrize("shell", SHELLS)
def test_review_mode_follows_the_old_review(shell, run):
    _touch(run / f"docs/{T}.json")
    assert _fill(shell, run, "review", str(run.parent / "a.md"), f"TABLE={T}", "MODE=重写后首审", "FACTS=无").returncode == 1
    assert _fill(shell, run, "review", str(run.parent / "b.md"), f"TABLE={T}", "MODE=首审", "FACTS=无").returncode == 0
    _touch(run / f"reviews/{T}.prior.md")
    _touch(run / f"reviews/{T}.prior.json")
    assert _fill(shell, run, "review", str(run.parent / "c.md"), f"TABLE={T}", "MODE=首审", "FACTS=无").returncode == 1
    assert _fill(shell, run, "review", str(run.parent / "d.md"), f"TABLE={T}", "MODE=重写后首审", "FACTS=无").returncode == 0


@pytest.mark.parametrize("shell", SHELLS)
def test_a_rewrite_must_carry_its_corrections(shell, run):
    out = str(run.parent / "o.md")
    assert _fill(shell, run, "write", out, f"TABLE={T}", "MODE=新写", "CORRECTIONS=无", *WRITE).returncode == 0
    _touch(run / f"reviews/{T}.prior.md")
    assert _fill(shell, run, "write", out, f"TABLE={T}", "MODE=新写", "CORRECTIONS=无", *WRITE).returncode == 1
    corrections = run.parent / "corrections.txt"
    assert _fill(shell, run, "write", out, f"TABLE={T}", "MODE=新写", f"CORRECTIONS=@{corrections}", *WRITE).returncode == 1
    _touch(corrections, "## A 段")
    assert _fill(shell, run, "write", out, f"TABLE={T}", "MODE=新写", f"CORRECTIONS=@{corrections}", *WRITE).returncode == 0
    _touch(run / f"docs/{T}.json")
    assert _fill(shell, run, "write", out, f"TABLE={T}", "MODE=新写", f"CORRECTIONS=@{corrections}", *WRITE).returncode == 1


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("name", ["T7", "T8"])
def test_two_rounds_get_two_scratch_paths(shell, name, run):
    paths = []
    for round_dir in ("round1", "round2"):
        _touch(run / round_dir / "sheet.md")
        _touch(run / round_dir / "grading.md")
        extra = ["ROUND_LABEL=r1"] if name == "T8" else []
        out = run.parent / f"{name}-{round_dir}.md"
        done = _fill(shell, run, name, str(out), f"ROUND={run}/{round_dir}", *extra)
        assert done.returncode == 0, done.stderr
        scratch = re.escape(str(run.parent / "scratch"))
        paths.append(set(re.findall(scratch + r"/[^`，\s]+", out.read_text(encoding="utf-8"))))
    assert paths[0] and paths[1] and not (paths[0] & paths[1])


@pytest.mark.parametrize("shell", SHELLS)
def test_a_missing_table_is_named_before_any_premise(shell, run):
    done = _fill(shell, run, "fix", str(run.parent / "o.md"), "MODE=首修", "FACTS=无")
    assert done.returncode == 1 and "TABLE" in done.stderr and "{TABLE}" not in done.stderr


# ---- every fill command the runbook prints --------------------------------------------

def _templates() -> dict[str, dict]:
    text = (REFS / "runbook-templates.md").read_text(encoding="utf-8")
    templates = {}
    for heading in re.finditer(r"^## (T\d) .*?\n(?:\n)?<!-- fill: (.*?) -->$", text, re.M):
        rules = dict(part.strip().split("=", 1) for part in heading.group(2).split(";") if "[" not in part)
        body = re.search(r"^## " + heading.group(1) + r" .*?^----8<----\n(.*?)^----8<----$", text, re.S | re.M)
        templates[heading.group(1)] = {
            "names": [name.strip().lower() for name in rules["names"].split(",")],
            "modes": [mode.strip() for mode in rules.get("MODE", "").split(",") if mode.strip()],
            "wanted": set(re.findall(r"\{([A-Z_]+)\}", body.group(1))),
        }
    return templates


def _commands() -> list[tuple[str, str]]:
    found = []
    for name in ("runbook.md", "runbook-templates.md"):
        for line in (REFS / name).read_text(encoding="utf-8").splitlines():
            for command in re.findall(r"(?:^|`)(fill [^`]+?)(?:`|;|$)", line.strip()):
                if not command.startswith("fill()"):
                    found.append((name, command.strip()))
    return found


def test_every_fill_command_in_the_runbook_fits_its_template():
    templates = _templates()
    assert len(templates) == 8, sorted(templates)
    commands = _commands()
    assert len(commands) >= 12, commands
    problems = []
    for where, command in commands:
        words = re.findall(r'(?:[^\s"]+|"[^"]*")+', command)
        template = next((t for t in templates.values() if words[1].lower() in t["names"]), None)
        if template is None:
            problems.append(f"{where}: {command}: no template named {words[1]}")
            continue
        given = {}
        for word in words[3:]:
            key, eq, value = word.partition("=")
            if eq and re.fullmatch(r"[A-Z_]+", key):
                given[key] = value.strip('"')
        for key in given:
            if key not in template["wanted"]:
                problems.append(f"{where}: {command}: {key} is not a placeholder of {words[1]}")
        if "MODE" in template["wanted"] and given.get("MODE", template["modes"][0]) not in template["modes"]:
            problems.append(f"{where}: {command}: MODE={given.get('MODE')} is not one of {template['modes']}")
        if "…" not in command:
            missing = template["wanted"] - AUTO - set(given)
            if missing:
                problems.append(f"{where}: {command}: leaves {sorted(missing)} unfilled")
    assert not problems, "\n".join(problems)


# ---- S10a route C: put rewritten tables back into an old catalog ---------------------

CATALOG = {
    "catalog.json": {"doc_format": "catalog-yaml/1", "name": "demo"},
    "identifiers.json": {"identifiers": [{"id": "id:one", "spellings": [{"column": "k", "table": "demo_dwd.t_one"}]},
                                         {"id": "id:other", "spellings": [{"column": "k", "table": "demo_dwd.t_two"}]}]},
    "concepts/demo.json": {"concepts": [{"id": "concept:one", "evidence": ["demo_dwd.t_one"],
                                         "attributes": [{"id": "attr:one.a", "evidence": ["demo_dwd.t_one.a"]}]}]},
    "mapping/demo.json": {"representations": [{"table": "demo_dwd.t_one"}, {"table": "demo_dwd.t_two"}]},
}


def _route_c(tmp_path: Path, catalog: dict[str, dict]):
    """The runbook's route C block (without its copy and validate lines) over ``catalog``."""
    text = (REFS / "runbook.md").read_text(encoding="utf-8")
    found = re.search(r"```bash\n(# 接回旧目录\n.*?)```", text, re.S)
    assert found, "runbook S10a has no block starting with '# 接回旧目录'"
    block = "\n".join(line for line in found.group(1).splitlines() if not line.startswith(("cp -R ", "sl ")))
    run = tmp_path / "run"
    for name, data in catalog.items():
        path = run / "catalog" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    (run / "tables.txt").write_text("demo_dwd.t_one\ndemo_dwd.t_new\n", encoding="utf-8")
    script = tmp_path / "c.sh"
    script.write_text(block, encoding="utf-8")
    done = subprocess.run(["bash", str(script)], env=dict(os.environ, RUN=str(run)), capture_output=True, text=True)
    return run, done


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
def test_route_c_strips_the_rewritten_tables_and_lists_what_names_them(tmp_path):
    run, done = _route_c(tmp_path, CATALOG)
    assert done.returncode == 0 and "exit=1" not in done.stdout, done.stderr
    assert "STRIPPED 1 / 2" in done.stdout and "demo_dwd.t_new: 旧目录里没有它的表现（新表）" in done.stdout
    kept = json.loads((run / "catalog/mapping/demo.json").read_text(encoding="utf-8"))
    assert kept == {"representations": [{"table": "demo_dwd.t_two"}]}
    touched = (run / "catalog_touched.txt").read_text(encoding="utf-8").splitlines()
    assert sorted(line.split("\t")[1] for line in touched) == ["attr:one.a", "concept:one", "id:one"]


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
@pytest.mark.parametrize("broken", ["identifiers.json", "mapping/demo.json"])
def test_route_c_stops_on_a_file_that_is_not_one_keyed_list(tmp_path, broken):
    catalog = {**CATALOG, broken: {**CATALOG[broken], "extra": []}}
    _, done = _route_c(tmp_path, catalog)
    assert "exit=1" in done.stdout and "顶层应当只有一个键" in done.stderr
