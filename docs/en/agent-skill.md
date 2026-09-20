[中文](../zh-CN/agent-skill.md) | English

# The AI agent skill: giving agents the lineage capability directly

The repository ships an agent-neutral skill at [`skills/scope-lineage/`](../../skills/scope-lineage/).
It captures the three kinds of knowledge needed to "use this tool well" as files, and any AI coding
agent that can read markdown and run a shell can execute it:

1. **Metadata wiring** — what to feed `--schema` / `--schema-fallback` / `--target-ddl-metadata`,
   and which silent degradation follows from omitting one (`SELECT *` not expanded, a projection
   bound to the wrong column);
2. **How to read the artifacts** — which JSON path answers "how is this field computed", and how to
   reverse-look-up "who depends on this table";
3. **Honesty rules** — `trace_complete`, fact gaps, and `AMBIGUOUS` must travel with the answer;
   a guess must never be stated as a fact.

The companion script `scripts/query.py` (pure standard library) does targeted extraction. Lineage
artifacts can be large, and an agent should never read the whole file into context:

```bash
python3 skills/scope-lineage/scripts/query.py summary <artifact dir>            # task overview
python3 skills/scope-lineage/scripts/query.py chain  db.table.column <dir>      # field transformation chain
python3 skills/scope-lineage/scripts/query.py impact db.table[.col] <root dir>  # impact analysis
python3 skills/scope-lineage/scripts/query.py trace  db.table[.col] <root dir> \
    [--upstream N] [--downstream N]                # cross-task lineage walk, N hops each way
```

These four subcommands are useful to humans too — you can run them without installing any agent.
`chain` bounds expression text by default; add `--expanded` when the complete expression is needed.
Corpus scans retain only the artifact currently being inspected rather than accumulating every
decoded document. `trace` writes a routing index (`.scope-lineage-index.json`) at the corpus root
on first run and refreshes it incrementally by file fingerprint; the index is a disposable cache —
the artifacts stay the single source of truth.

One workflow in the skill does not go through `query.py`: for "what does this task do / what does this field mean", run `scope-lineage describe --lineage <artifact dir>` first to produce the `semantic.json` / `semantic.md` semantic skeleton and answer by reading `semantic.md` whole; when a business profile is wanted, generate two files from `references/semantic-profile-prompt.md`. `business_profile.md` is the reader's: three pieces — a task semantic card (≤ 1 page, business language, no source tags in the body), a field dictionary (every output column, with a 7-row metric spec card per measure) and an open-questions list (≤ 5 items a business owner can answer in five minutes) — followed by a short appendix only: A 已确认项 / B 备查项与待填取值 / C 风险边界, the three together capped at 1/3 of the body's character count. `business_profile.check.md` is the writer's QA record: input file verification, source tags and evidence, inferred items, the self-consistency pass and the generation self-check — no item dropped, but no longer taking up the reader's page.

The skill also ships a write-back script, `scripts/confirmations.py` (standard library too).
Once the business owner has filled in the `- 答案：` line of each open question in a
`business_profile.md`,

```
python3 skills/scope-lineage/scripts/confirmations.py apply <profile file> --by <name>
```

routes every answer by its own 回写目标 line — `术语` / `值域` merge into
`glossary.overrides.json`, `字段注释` / `表注释` merge into `metadata-patch.json`
(`--dry-run` only prints). `值域` also takes a **family key**, `值域:*.<column>=<value>`:
when one code table has been copied into three or more tables, the owner answers it once
and the answer reaches every table that observed the value. Re-run `glossary --overrides` and
`describe --glossary --metadata-patch`, and those items come back as confirmed facts
instead of open questions, so the list gets shorter every round.

For "how do the entities in this batch of tasks relate" there is one more: run `scope-lineage ontology --lineage <corpus> --out <dir>`, read the Mermaid ER overview in `<dir>/ontology.md` to find the entity, then the five ontology sections of `<dir>/tables/<table>.md`; a `hypothesis` or a `conflict` must be presented verbatim and marked `[待确认]`, and answered items are written back into `ontology.overrides.json` per `references/ontology-review-prompt.md` so the next run publishes them as `confirmed`.

## Installation

**Claude Code**:

```
/plugin marketplace add realyin/scope-lineage
```

Then install the `scope-lineage` plugin. From then on, conversations mentioning lineage, field
provenance, transformation steps, impact analysis, or mapping documents trigger the skill
automatically.

**Codex (native skill installation, recommended)**: Codex has its own Agent Skills mechanism, and
its skill directory format is identical to this repository's — it works as-is. Git is the
distribution channel (`pip install` deliberately does **not** carry the skill files; they are
excluded from the PyPI distribution):

```bash
git clone https://github.com/realyin/scope-lineage ~/tools/scope-lineage
ln -s ~/tools/scope-lineage/skills/scope-lineage ~/.codex/skills/scope-lineage
```

- **User level** `~/.codex/skills/`: shared by all projects, recommended; **project level**
  `.codex/skills/`: effective only in the current project. Once it is in the skills directory,
  Codex triggers it automatically from the SKILL.md description, the same experience as Claude
  Code.
- Updating: `git -C ~/tools/scope-lineage pull`, and the symlink follows automatically; if your
  agent version does not follow symlinks, copy the directory instead and re-copy on update.
- Upgrading the Core CLI still goes through `pip install --upgrade scope-lineage`. The two channels
  are independent, and the skill's self-check prompts for an upgrade when the version is too old.

**Agents with no skill mechanism (fallback)**: clone as above, then add one line to their rules
file (project-level `AGENTS.md` or the global equivalent):

> For questions about SQL lineage, field transformation, impact analysis, or mapping documents,
> first read `~/tools/scope-lineage/skills/scope-lineage/SKILL.md` and follow it.

Relative paths inside the skill (`scripts/query.py`, `references/...`) resolve against SKILL.md's
own directory, so **the project being analyzed does not need to contain these files** — you can ask
in any warehouse project. The skill's content depends on no agent-proprietary mechanism; every
agent reads the same guidance.

## Team-private metadata configuration

The schema / DDL metadata paths of a real corpus are private team information and **do not go into
the skill itself**. The convention is to put them in the local file
`~/.scope-lineage/defaults.json`:

```json
{
  "schema": "/path/to/rich-json-metadata-dir",
  "schema_fallback": ["/path/to/fallback-schema.csv"],
  "target_ddl_metadata": "/path/to/target-ddl-dir",
  "catalog_prefixes": "warehouse_catalog,spark_catalog"
}
```

`catalog_prefixes` is optional — leave it out unless you are sure the leading segment is a catalog.

The skill looks this file up before every parse and translates the keys into the matching flags;
when the file does not exist and a real task is being parsed, the skill asks where the metadata is
rather than parsing bare (a bare parse degrades silently — see
`skills/scope-lineage/references/metadata-inputs.md`).

## Version requirement

scope-lineage ≥ 0.2.0 is required. The skill's self-check uses `scope-lineage --version` (available
from 0.2.1; on 0.2.0 it falls back to
`python3 -c "import importlib.metadata as m; print(m.version('scope-lineage'))"`). Older versions
silently produce the removed per-statement format — `query.py` says so explicitly when it meets such
an artifact, but the parse itself has already been wasted.
