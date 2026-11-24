"""``fill`` (``scripts/runlib.sh``) under bash and zsh, and every ``fill`` command the runbook prints.

The orchestrator fills the subagent templates T1–T9 with ``fill``; a filled template is
what a subagent is told. A wrong template, a mode from another template or a missing
premise (a re-review with no backed-up first review, a rewrite without its corrections
list) used to fill without a word. ``fill`` now reads each template's rules from the
``<!-- fill: … -->`` line under its heading and refuses those with exit 1. The function is
sourced from ``runlib.sh`` in a fresh shell, as an orchestrator's Bash call gets it through
``env.sh``; zsh is skipped where it is not installed.

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
REFS = ROOT / "skills" / "scope-lineage-ontology" / "references"
SHELLS = [
    pytest.param(shell, marks=pytest.mark.skipif(shutil.which(shell) is None, reason=f"{shell} is not installed"))
    for shell in ("bash", "zsh")
]
T = "demo_x.t"
WRITE = ("FACTS=无", "CONCEPT=不写 concept", "FAILURES=无")
AUTO = {"RUN", "TOOL", "SKILL", "LINEAGE_SKILL", "SCHEMAS", "SCRATCH", "TASKS", "PAGES", "SEMPAGES", "ENV", "ROUND_NAME"}


@pytest.fixture
def run(tmp_path):
    directory = tmp_path / "run"
    for name in ("docs", "reviews", "reviews_prev", "round1", "round2", "digest"):
        (directory / name).mkdir(parents=True)
    return directory


def _fill(shell, run, *args, **overrides):
    script = run.parent / "f.sh"
    skill = overrides.get("SKILL") or str(REFS.parent)
    script.write_text(f'. "{skill}/scripts/runlib.sh"\nfill "$@"\n', encoding="utf-8")
    env = dict(os.environ, TOOL=str(ROOT), RUN=str(run), SCRATCH=str(run.parent / "scratch"),
               TASKS="/x", PAGES=str(run / "site"), SEMPAGES=str(run / "site/semantics"))
    env.pop("SKILL", None)
    env.pop("SCHEMAS", None)
    env.update(overrides)
    return subprocess.run([shell, str(script), *args], env=env, capture_output=True, text=True)


@pytest.mark.parametrize("shell", SHELLS)
def test_a_pip_install_fills_from_the_skill_directory(shell, run, tmp_path):
    """No checkout: ``TOOL`` empty, the skill and the package's schemas found apart."""
    skill = tmp_path / "skills" / "scope-lineage-ontology"
    shutil.copytree(REFS.parent, skill)
    out = run.parent / "t1.md"
    done = _fill(shell, run, "T1", str(out), f"TABLE={T}", "MODE=新写", "CORRECTIONS=无", *WRITE,
                 TOOL="", SKILL=str(skill), SCHEMAS="/site-packages/scope_lineage/schemas")
    assert done.returncode == 0, done.stderr
    text = out.read_text(encoding="utf-8")
    assert f"{skill}/references/table-semantics-prompt.md" in text
    assert "/site-packages/scope_lineage/schemas/table-semantics.schema.json" in text
    assert "{TOOL}" not in text and "skills/scope-lineage" not in text.replace(str(skill), "")


@pytest.mark.parametrize("shell", SHELLS)
def test_a_checkout_needs_no_skill_or_schemas_variable(shell, run):
    out = run.parent / "t1.md"
    done = _fill(shell, run, "T1", str(out), f"TABLE={T}", "MODE=新写", "CORRECTIONS=无", *WRITE)
    assert done.returncode == 0, done.stderr
    text = out.read_text(encoding="utf-8")
    assert f"{ROOT}/skills/scope-lineage-ontology/references/table-semantics-prompt.md" in text
    assert f"{ROOT}/scope_lineage/schemas/table-semantics.schema.json" in text


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
def test_the_drafter_gets_the_owner_decisions_file_or_none(shell, run):
    """T5 carries the owner's decisions verbatim: ``@owner_decisions.md`` when it exists,
    「无」 when it does not -- never a hand-edited prompt."""
    _touch(run / "digest" / "digest.md")
    out = run.parent / "t5.md"
    base = ("MODE=新建", "SIZE=小样", "TOUCHED=无", "REWORK=无")
    done = _fill(shell, run, "catalog", str(out), *base, "DECISIONS=无")
    assert done.returncode == 0, done.stderr
    assert "{DECISIONS}" not in out.read_text(encoding="utf-8")
    decisions = _touch(run / "owner_decisions.md", "- 列 x_no 就是编号 id:x")
    refused = _fill(shell, run, "catalog", str(out), *base, "DECISIONS=无")
    assert refused.returncode == 1 and "owner_decisions.md" in refused.stderr
    done = _fill(shell, run, "catalog", str(out), *base, f"DECISIONS=@{decisions}")
    assert done.returncode == 0, done.stderr
    assert "- 列 x_no 就是编号 id:x" in out.read_text(encoding="utf-8")


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
    text = "\n".join(path.read_text(encoding="utf-8") for path in sorted((REFS / "templates").glob("T*.md")))
    templates = {}
    for heading in re.finditer(r"^## (T\d|T-[a-z-]+) .*?\n(?:\n)?<!-- fill: (.*?) -->$", text, re.M):
        rules = dict(part.strip().split("=", 1) for part in heading.group(2).split(";") if "[" not in part)
        body = re.search(r"^## " + re.escape(heading.group(1)) + r" .*?^----8<----\n(.*?)^----8<----$",
                         text, re.S | re.M)
        templates[heading.group(1)] = {
            "names": [name.strip().lower() for name in rules["names"].split(",")],
            "modes": [mode.strip() for mode in rules.get("MODE", "").split(",") if mode.strip()],
            "wanted": set(re.findall(r"\{([A-Z_]+)\}", body.group(1))),
        }
    return templates


def _commands() -> list[tuple[str, str]]:
    found = []
    pages = [REFS / "runbook.md", REFS / "runbook-templates.md", *sorted((REFS / "steps").glob("*.md")),
             *sorted((REFS / "templates").glob("*.md"))]
    for name in (str(page.relative_to(REFS)) for page in pages):
        for line in (REFS / name).read_text(encoding="utf-8").splitlines():
            for command in re.findall(r"(?:^|`)(fill [^`]+?)(?:`|;|$)", line.strip()):
                if not command.startswith("fill()"):
                    found.append((name, command.strip()))
    return found


def test_every_fill_command_in_the_runbook_fits_its_template():
    templates = _templates()
    assert len(templates) == 10, sorted(templates)
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
    text = (REFS / "steps" / "S10a.md").read_text(encoding="utf-8")
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


@pytest.mark.parametrize("shell", SHELLS)
def test_the_second_review_needs_the_first_pass_kept_aside(shell, run):
    out = run.parent / "t9.md"
    _touch(run / "docs" / f"{T}.json")
    _touch(run / "reviews" / f"{T}.md")
    refused = _fill(shell, run, "second-review", str(out), f"TABLE={T}", "FACTS=无")
    assert refused.returncode == 1 and "pass1.md" in refused.stderr
    _touch(run / "reviews_prev" / f"{T}.pass1.md")
    done = _fill(shell, run, "补审", str(out), f"TABLE={T}", "FACTS=无")
    assert done.returncode == 0, done.stderr
    assert "## 两遍审读合并" in out.read_text(encoding="utf-8")


# ---- the owner's confirmations: FACTS from a file, replayed after every write ---------


@pytest.mark.parametrize("shell", SHELLS)
def test_facts_from_a_file_read_line_by_line_in_their_own_block(shell, run):
    """``semantic facts`` writes a header line and one fact per line, or 「无」 alone; either
    reads as one block under its bullet, not as bullets of the template's own list."""
    _touch(run / f"reviews/{T}.md")
    facts = _touch(run.parent / "facts.txt",
                   f"表 {T} 已确认的事实：\n- 按粒度列唯一：是（unique: yes）\n- 列 c 的码值「1」：开\n")
    out = run.parent / "t4.md"
    done = _fill(shell, run, "fix", str(out), f"TABLE={T}", "MODE=核对", f"FACTS=@{facts}")
    assert done.returncode == 0, done.stderr
    text = out.read_text(encoding="utf-8")
    assert (f"：\n\n```text\n表 {T} 已确认的事实：\n- 按粒度列唯一：是（unique: yes）\n- 列 c 的码值「1」：开\n```\n"
            in text)
    _touch(facts, "无\n")
    assert _fill(shell, run, "fix", str(out), f"TABLE={T}", "MODE=核对", f"FACTS=@{facts}").returncode == 0
    assert "：\n\n```text\n无\n```\n" in out.read_text(encoding="utf-8")


def test_every_prompt_with_facts_is_filled_from_the_confirmations():
    """No runbook command hands a writer or reviewer 「无」 by hand: a run with confirmations
    would lose them on every rewrite. Each FACTS file is written by ``semantic facts`` in
    the same block."""
    wanted = {name for name, template in _templates().items() if "FACTS" in template["wanted"]}
    assert wanted == {"T1", "T2", "T3", "T4", "T9"}
    facts = [(where, command) for where, command in _commands() if " FACTS=" in command]
    assert len(facts) >= 7, facts
    bad = [f"{where}: {command}" for where, command in facts
           if 'FACTS=@"$SCRATCH/prompts/' not in command and "FACTS=@\"$SCRATCH/prompts/<表>.facts.txt\"" not in command]
    assert not bad, "\n".join(bad)
    for page in [REFS / "runbook-templates.md", *sorted((REFS / "steps").glob("*.md"))]:
        text = page.read_text(encoding="utf-8")
        for block in re.findall(r"```bash\n(.*?)```", text, re.S):
            if " FACTS=@" in block:
                assert "sl semantic facts --confirmations \"$RUN/confirmations\"" in block, page.name


def test_every_facts_call_reads_the_documents():
    """``semantic facts --documents`` lets an observed row's line say when the columns a
    query counted are not the document's grain columns (D16): every call of the runbook
    passes the run's documents."""
    pages = [REFS / "runbook-templates.md", *sorted((REFS / "steps").glob("*.md"))]
    calls = [(page.name, line) for page in pages for line in page.read_text(encoding="utf-8").splitlines()
             if "semantic facts --confirmations" in line]
    assert len(calls) >= 7, calls
    bad = [f"{name}: {line}" for name, line in calls if '--documents "$RUN/docs"' not in line]
    assert not bad, "\n".join(bad)


def test_the_writer_is_given_the_observation_forms_validation_accepts():
    """The writer prompt's 「观测事实」 section gives the sentence check 10 relaxes for (the form
    「观测（查询 …」, the partition, a pN that does not multiply rows in that partition, the
    other partitions unobserved) and never lets an observation be written as unique or
    proven; the catalog prompts write an observed grain as ``inferred`` with a note."""
    from scope_lineage.semantics.checks_meaning import _OBSERVED_FORM

    prompt = (REFS / "table-semantics-prompt.md").read_text(encoding="utf-8")
    section = prompt.split("## 观测事实", 1)[1].split("\n## ", 1)[0]
    form = re.search(r"「(观测（查询[^」]*在该分区内不放大[^」]*)」", section)
    assert form and _OBSERVED_FORM.search(form.group(1)), section
    assert "别的分区未观测" in form.group(1)
    assert _form_passes_check_10(form.group(1))
    for rule in ("不是定义", "`proven`", "裸「唯一」", "\"unconfirmed\": true", "工具写"):
        assert rule in section, rule
    version = re.search(r"table-semantics-prompt@(\d+)", prompt.splitlines()[0]).group(1)
    assert f'{{"prompt": "table-semantics-prompt@{version}"}}' in prompt
    for name in ("catalog-fragment-prompt.md", "templates/T5.md", "templates/T6.md"):
        text = (REFS / name).read_text(encoding="utf-8")
        assert "observed in" in text and "`inferred`" in text and "不写 `declared`" in text, name


def _form_passes_check_10(form: str) -> bool:
    """The writer's join sentence, filled in, is one check 10 relaxes for: no warning with
    the observation it reports, a warning without it."""
    from scope_lineage.semantics.checks_meaning import check_fan_out
    from scope_lineage.semantics.confirmed import confirmed_state

    table = "demo_dwd.dwd_probe_user_df"
    sentence = (form.replace("<查询>", "probe_1").replace("<分区>", "dt=20261119")
                .replace("<日期>", "2026-11-20").replace("<T>", table)
                .replace("<键>", "open_id").replace("<pN>", "p1"))
    assert "<" not in sentence, sentence
    rule = {"id": "p1", "kind": "join", "join_type": "LEFT_OUTER", "expression": "a.open_id = b.open_id",
            "task": "t0", "right": "subq:b", "right_tables": [table], "right_aliases": ["b"],
            "columns": ["demo_ods.ods_probe_call_df.open_id", f"{table}.open_id"],
            "fan_out": {"status": "risk", "reason": "右侧未被证明按连接键唯一", "path": "grain"}}
    document = {"summary": {"row": {"note": "每个 id 一行。"},
                            "watch": [{"kind": "risk", "text": sentence}]}}
    packet = {"lineage": {"rules": [rule]}}
    entry = {"table": "demo_dwd.dwd_party_customer_info_df", "target": f"input:{table}",
             "by": "demo-reviewer", "date": "2026-11-21",
             "value": {"query": "probe_1", "on": "2026-11-20", "rows": 120,
                       "partition": {"column": "dt", "values": ["20261119"]},
                       "columns": ["open_id"], "unique": "yes", "within": "each_partition",
                       "keys": 120, "duplicate_keys": 0}}
    confirmed = confirmed_state([entry])["demo_dwd.dwd_party_customer_info_df"]
    warned = [item for item in check_fan_out(document, packet, None) if item["status"] != "pass"]
    relaxed = [item for item in check_fan_out(document, packet, confirmed) if item["status"] != "pass"]
    return bool(warned) and relaxed == []


def _observation_section() -> str:
    prompt = (REFS / "table-semantics-prompt.md").read_text(encoding="utf-8")
    return prompt.split("## 观测事实", 1)[1].split("\n## ", 1)[0]


def test_an_observation_sentence_is_no_proof_and_keeps_its_condition():
    """An observation is not proof, so a pN kept in an "unproven" risk list beside it is no
    contradiction (writer and review item 14); the sentence may name the join by pN alone;
    a FACTS line counted under a condition (「条件 …」) keeps that condition in the sentence."""
    section = _observation_section()
    review = (REFS / "table-semantics-review-prompt.md").read_text(encoding="utf-8")
    item = review.split("\n14. ", 1)[1].split("\n15. ", 1)[0]
    for text in (section, item):
        assert "未证明" in text and "不算矛盾" in text, text
    assert "不必写表名" in section
    assert "「条件 …」" in section and "无条件" in section


def test_check_mode_may_fix_what_a_rule_says_of_its_join_but_not_its_sql():
    """T4's check mode, after an observation is written back, may change what a rule's text
    or watch says about whether its join multiplies rows; `rules[].sql` stays forbidden."""
    t4 = (REFS / "templates" / "T4.md").read_text(encoding="utf-8")
    check = t4.split("**核对模式**", 1)[1].split("\n**", 1)[0]
    assert "`rules[].text`" in check and "`rules[].watch`" in check, check
    assert "放大行数" in check
    assert "不改列的 `meaning`、`code_values`、`rules[].sql`" in check


def test_s5_keeps_two_observation_warnings_a_writer_cannot_clear():
    """Two check 3 / 4 warnings stay without a T1 round: a real contradiction between the
    declared grain and the observation already written side by side with a conflict
    watch, and observed values on a column that is no code column."""
    s5 = (REFS / "steps" / "S5.md").read_text(encoding="utf-8")
    whitelist = s5.split("**WARN 白名单**", 1)[1].split("\n**", 1)[0]
    assert "只有这五种" in whitelist
    assert "声明与观测不一致" in whitelist and "conflict" in whitelist
    assert "有观测取值、没有码值表" in whitelist


def test_a_written_document_is_replayed_before_it_is_validated_or_recorded():
    """S4's check and S5's validation replay the confirmations first; T4 replays before
    ``semantic fixed``, so the fix record is the replayed document's."""
    replay = ('sl semantic confirm "$RUN/docs" --confirmations "$RUN/confirmations" --reviews "$RUN/reviews" '
              '--require-asked --only')
    for name in ("S4.md", "S5.md"):
        text = (REFS / "steps" / name).read_text(encoding="utf-8")
        blocks = [block for block in re.findall(r"```bash\n(.*?)```", text, re.S) if replay in block]
        assert blocks, name
        assert all(block.index(replay) < block.index("sl semantic validate") for block in blocks), name
    t4 = (REFS / "templates" / "T4.md").read_text(encoding="utf-8")
    assert replay in t4 and t4.index(replay) < t4.index('sl semantic fixed "$RUN"')


def test_every_replay_of_the_run_requires_asked():
    """A rewrite renumbers questions: no replay may pin an answer on a question by id alone."""
    pages = [*sorted((REFS / "steps").glob("*.md")), *sorted((REFS / "templates").glob("T*.md"))]
    replays = [(page.name, line) for page in pages for line in page.read_text(encoding="utf-8").splitlines()
               if "sl semantic confirm " in line]
    assert {name for name, _ in replays} >= {"S4.md", "S5.md", "S12.md", "T4.md"}, replays
    assert all("--require-asked" in line for _, line in replays), replays


def _prompt(name: str) -> str:
    return (REFS / name).read_text(encoding="utf-8").split("----8<----", 2)[1]


def test_the_drafter_follows_the_owners_answers_in_the_digest():
    """``catalog digest`` prints ``- Answered qN: <question> -> <answer>``. Measured with a
    real model, T5 used such an answer only when told to, and went on asking 「待 owner 确认」
    on points already answered; an answer in tension with the table's SQL was dropped."""
    body = _prompt("templates/T5.md")
    rule = body[body.index("**已回答的问题**"):]
    rule = rule[: rule.index("\n**义务清单**")]
    assert "- Answered qN" in rule
    for sentence in ("依据 digest Answered qN", "不写「待 owner 确认」", "只用于本表", "与 SQL 有张力"):
        assert sentence in rule, sentence
    assert "Answered" in body[body.index("**回复**"):]


def test_after_confirmation_the_digest_is_rebuilt_and_the_catalog_edited_by_hand():
    s12 = (REFS / "steps" / "S12.md").read_text(encoding="utf-8")
    after = s12[s12.index("**下一步**"):]
    assert "S10b" in after and "S10f" in after and "不回 S10c" in after
    assert "标识符" in after and "关系" in after
    s10b = (REFS / "steps" / "S10b.md").read_text(encoding="utf-8")
    assert "Answered" in s10b and "S10f" in s10b[s10b.index("**下一步**"):]
