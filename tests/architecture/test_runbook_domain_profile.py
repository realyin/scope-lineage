"""5.3: every runbook command that reads a domain profile gets the run's one profile.

``semantic packet``, ``semantic validate`` and ``ontology`` read ``domain-profile/1``
(``--domain-profile``). The runbook calls them from many steps and from subagent
templates; adding the flag to each call is how one gets forgotten, and a packet built
with the profile then validated without it reads check 12 two ways. So the runbook never
passes the flag: ``init_run.py --domain-profile`` writes ``DOMAIN_PROFILE`` into
``env.sh``, ``runlib.sh`` exports it as ``SCOPE_LINEAGE_DOMAIN_PROFILE``, and the tool
reads that variable when no flag is given. These tests keep every call on that path:
through ``sl`` (which only exists after ``env.sh`` is sourced), with ``env.sh`` sourced in
the subagent templates, and never with a flag of its own.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scope_lineage.domain_profile import DOMAIN_PROFILE_ENV

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "scope-lineage-ontology"
TEMPLATES = SKILL / "references" / "templates"

# A call of one of the three commands that read the profile, however it is spelled.
_PROFILED = r"(?:semantic\s+(?:packet|validate)|ontology)(?=\s|$)"
_CALL = re.compile(rf"(?:^|[\s;&|(`])(?P<tool>sl|scope-lineage)\s+{_PROFILED}")


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """Lines a run executes: fenced code in markdown, every line of a script."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if path.suffix != ".md":
        return list(enumerate(lines, start=1))
    picked, fenced = [], False
    for number, line in enumerate(lines, start=1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            picked.append((number, line))
    return picked


def _calls() -> list[tuple[str, int, str, str]]:
    found = []
    for path in sorted(SKILL.rglob("*")):
        if path.suffix not in {".md", ".py", ".sh"} or not path.is_file():
            continue
        for number, line in _code_lines(path):
            for match in _CALL.finditer(line):
                found.append((path.relative_to(ROOT).as_posix(), number, match.group("tool"), line))
    return found


CALLS = _calls()


def test_the_runbook_calls_the_profiled_commands() -> None:
    """The scan finds the calls it guards (a silent regex would pass everything)."""
    commands = {re.search(_PROFILED, line).group(0).split()[-1] for *_rest, line in CALLS}
    assert {"packet", "validate"} <= commands
    assert any(path.startswith("skills/scope-lineage-ontology/references/templates/") for path, *_ in CALLS)


@pytest.mark.parametrize(("path", "number", "tool", "line"), CALLS)
def test_every_call_goes_through_sl(path: str, number: int, tool: str, line: str) -> None:
    assert tool == "sl", f"{path}:{number} calls the tool without env.sh: {line.strip()}"


@pytest.mark.parametrize(("path", "number", "tool", "line"), CALLS)
def test_no_call_passes_its_own_profile(path: str, number: int, tool: str, line: str) -> None:
    assert "--domain-profile" not in line, (
        f"{path}:{number}: the runbook's profile comes from env.sh, not a flag: {line.strip()}")


@pytest.mark.parametrize(
    ("path", "number", "tool", "line"),
    [call for call in CALLS if call[0].startswith("skills/scope-lineage-ontology/references/templates/")],
)
def test_a_subagent_sources_env_sh_before_the_call(path: str, number: int, tool: str, line: str) -> None:
    """A subagent starts a fresh shell: the call must source env.sh on the same line."""
    assert line.lstrip().startswith(". {ENV} &&"), f"{path}:{number}: {line.strip()}"


def test_runlib_exports_the_variable_the_tool_reads() -> None:
    text = (SKILL / "scripts" / "runlib.sh").read_text(encoding="utf-8")
    assert f'export {DOMAIN_PROFILE_ENV}="$DOMAIN_PROFILE"' in text
    init = (SKILL / "scripts" / "init_run.py").read_text(encoding="utf-8")
    assert '"--domain-profile"' in init and '"DOMAIN_PROFILE"' in init
