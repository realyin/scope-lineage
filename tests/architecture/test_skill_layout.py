"""One file per step, one file per role, and an index that names them all.

The runbook was one 1,500-line file and the templates another 900-line one; an orchestrator
found its step by searching, and a person could not see the procedure's shape. Each step
and each template is its own file now, ``runbook.md`` and ``runbook-templates.md`` are the
indexes, and ``next_step.py`` prints the file to read. These tests keep the pieces and the
indexes from drifting apart.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "skills"
SKILL = SKILLS / "scope-lineage"
REFS = SKILL / "references"
STEPS = REFS / "steps"
TEMPLATES = REFS / "templates"

_spec = importlib.util.spec_from_file_location("next_step", SKILL / "scripts" / "next_step.py")
next_step = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(next_step)
STEP_IDS = [step for step, _ in next_step.STEPS]


@pytest.mark.parametrize("step", STEP_IDS)
def test_every_step_the_progress_script_knows_has_its_own_file(step):
    path = STEPS / f"{step}.md"
    assert path.is_file(), path
    heading = "### " if re.fullmatch(r"S10[a-g]", step) else "## "
    assert path.read_text(encoding="utf-8").startswith(f"{heading}{step} "), path


def test_the_runbook_is_an_index_that_links_every_step_file():
    text = (REFS / "runbook.md").read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 120
    linked = set(re.findall(r"\]\((steps/[^)]+\.md)\)", text))
    assert linked == {f"steps/{path.name}" for path in STEPS.glob("*.md")}
    assert "### 0.5 主流程总览" in text and "### 0.6 每一步做完：跑进度脚本" in text


def test_every_template_is_one_file_and_the_templates_index_links_it():
    names = sorted(path.name for path in TEMPLATES.glob("*.md"))
    assert names == sorted([f"T{n}.md" for n in range(1, 10)] + ["checklist.md", "ledger.md", "result.md"])
    for n in range(1, 10):
        text = (TEMPLATES / f"T{n}.md").read_text(encoding="utf-8")
        assert text.startswith(f"## T{n} ") and text.count("<!-- fill: ") == 1 and text.count("\n----8<----\n") == 2
    index = (REFS / "runbook-templates.md").read_text(encoding="utf-8")
    assert len(index.splitlines()) <= 80
    assert set(re.findall(r"\]\((templates/[^)]+\.md)\)", index)) == {f"templates/{name}" for name in names}


def test_no_step_file_is_a_wall_of_text():
    sizes = {path.name: len(path.read_text(encoding="utf-8").splitlines()) for path in STEPS.glob("*.md")}
    assert {name: size for name, size in sizes.items() if size > 170} == {}


def _skill_files():
    # catalog-elements.md is sections of docs/ontology-catalog.md, bundled as they are: its links are the docs' own
    return [path for skill in ("scope-lineage", "scope-lineage-ontology") for path in (SKILLS / skill).rglob("*.md")
            if path.name != "catalog-elements.md"]


def test_every_file_a_skill_document_points_to_exists():
    missing = []
    for path in _skill_files():
        text = path.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)#\s]+\.(?:md|py|sh|json|yaml))\)", text):
            if not target.startswith("http") and not (path.parent / target).exists():
                missing.append(f"{path.relative_to(SKILLS)}: ({target})")
        for target in re.findall(r"`((?:\$SKILL/|\{SKILL\}/)?(?:references|scripts|steps|templates|workflows)/[\w./-]+\.(?:md|py|sh))`", text):
            relative = target.replace("$SKILL/", "").replace("{SKILL}/", "")
            bases = [SKILL] if target.startswith(("$SKILL", "{SKILL}")) else [path.parent, SKILL, SKILL / "references", path.parents[1]]
            if not any((base / relative).exists() for base in bases):
                missing.append(f"{path.relative_to(SKILLS)}: `{target}`")
    assert missing == []


def test_the_progress_script_prints_the_file_of_the_current_step(tmp_path):
    done = subprocess.run([sys.executable, str(SKILL / "scripts" / "next_step.py"), str(tmp_path)], capture_output=True, text=True)
    assert f"{SKILL}/references/steps/S0.md" in done.stdout, done.stdout


WORKFLOWS = SKILL / "workflows"


def test_the_lineage_skill_is_a_router_with_one_file_per_workflow():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 250
    names = {path.name for path in WORKFLOWS.glob("*.md")}
    assert len(names) >= 12
    assert set(re.findall(r"\]\(workflows/([^)]+\.md)\)", text)) == names
    for path in WORKFLOWS.glob("*.md"):
        assert path.read_text(encoding="utf-8").startswith("### "), path
