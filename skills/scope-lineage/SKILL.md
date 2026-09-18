---
name: scope-lineage
description: >-
  Answer Spark/Hive SQL lineage questions with verifiable evidence using the scope-lineage
  CLI: parse SQL files or scheduler task JSON into field-level lineage artifacts, explain
  how a target column is derived step by step, find which tasks/columns depend on a table
  or column (impact analysis), and generate human-readable mapping.md documents. Use this
  skill whenever the user mentions 血缘 / lineage / 字段来源 / 加工步骤 / 影响分析 /
  mapping 文档 / 字段映射 / 任务画像 / 语义描述 / 字段含义, asks "这个字段怎么算出来的",
  "这个任务在做什么", "谁依赖这张表", "这个 SQL 读了哪些表", or wants to analyze,
  document, or audit warehouse SQL transformations — even if they do not name the
  scope-lineage tool.
---

# Scope Lineage

Turn Spark/Hive SQL into evidence-backed answers about field-level lineage. The
`scope-lineage` CLI does the parsing; this skill's job is to wire its inputs correctly,
extract answers from its artifacts efficiently, and keep the answers honest.

Relative paths in this file (`scripts/query.py`, `references/...`) resolve against THIS
file's own directory — if you are reading it from a clone at some other location, prefix
them with that directory; the working project you are answering questions about does not
need to contain these files.

## Three rules that make answers trustworthy

1. **Never load a whole lineage.json into context.** Lineage artifacts can be large.
   Always extract with `scripts/query.py` (or an equally targeted read). Full-file reads
   waste the context and bury the answer.
2. **Uncertainty travels with the answer.** Every artifact marks what it could NOT
   prove: `trace_complete: false`, `lineage_fact_gaps`, `AMBIGUOUS` sources, warnings.
   When these are present, say so and say why ("the trace stops at X because the schema
   for Y is missing") — presenting a partial trace as complete defeats the tool's whole
   purpose, which is that its answers can be trusted.
3. **Metadata wiring decides answer quality.** Parsing without schema/DDL metadata
   silently degrades (`SELECT *` stays unexpanded, projections bind to wrong columns).
   Read `references/metadata-inputs.md` before any parse of real tasks, and check for a
   local defaults file (below).

## Setup check (first use in a session)

```bash
scope-lineage --version 2>/dev/null \
  || python3 -c "import importlib.metadata as m; print(m.version('scope-lineage'))"
```

Need >= 0.2.0 (`--version` itself exists from 0.2.1; the fallback covers 0.2.0).
Not installed → `pipx install scope-lineage` (or `pip install scope-lineage`). Too old
→ upgrade in place. This check is not optional: a stale install silently produces the
removed pre-0.2.0 per-statement format, every downstream step here then misbehaves, and
the artifacts look superficially fine. (`scripts/query.py` detects such artifacts and
says so, but by then the parse has already been wasted.)

**Local defaults**: if `~/.scope-lineage/defaults.json` exists, use its values as the
default metadata flags — it holds the team's private metadata paths, which never appear
in this skill. Format:

```json
{"schema": "<path>", "schema_fallback": ["<path>"], "target_ddl_metadata": "<path>",
 "catalog_prefixes": "<comma,separated>"}
```

If it does not exist and the user is parsing real tasks, ask where their schema and
target-DDL metadata live rather than parsing bare (see rule 3).

## Workflows by question type

### "解析这个 SQL / 任务的血缘" — parse

```bash
scope-lineage parse \
  --sql-file <file.sql>            # or --task-file <task.json> / --input-dir <dir>
  --schema <rich-json-dir-or-file> \
  --schema-fallback <csv> \
  --target-ddl-metadata <ddl-dir> \
  --out <output-dir>
```

Then summarize from the artifact, not from the console:

```bash
python3 scripts/query.py summary <output-dir>/<task-name>
```

Report: parse/syntax status, statements modeled, final target tables, warning and gap
counts. If `parse_status` is not `ok` or gaps exist, lead with that.

### "字段 X 是怎么加工出来的" — derivation chain

```bash
python3 scripts/query.py chain <db.table.column> <artifact-dir...>
```

Output shows the final-state sources, the step-by-step mapping chain (scope, step type,
transform, expression per step), the physical root columns, and a bounded expanded-expression
preview. Add `--expanded` only when the complete expression is needed. Present the steps in order
with their expressions; quote `trace_status` /
`trace_complete` verbatim. Structure of everything printed: `references/artifact-guide.md`.

### "谁依赖表 T / 列 C" — impact analysis

```bash
python3 scripts/query.py impact <db.table[.column]> <artifacts-root>
```

Requires artifacts to exist for the task corpus first (parse `--input-dir` once, reuse
the output). Reports every `target_table.column <- source` edge. "No consumers found"
across N docs is a real answer — report N so the user knows the search space.

### "跨任务追溯上下游 N 层" — cross-task trace

```bash
python3 scripts/query.py trace [--upstream N] [--downstream N] <db.table[.column]> <artifacts-root>
```

Joins tasks by table name across the whole corpus and walks the lineage graph hop by
hop (default: one hop each direction). Each printed edge names the task and artifact
path that proves it; `no producing task in corpus` marks the physical boundary. Cycles
(e.g. MERGE self-references, mutually-fed tables) are reported once and not re-walked.
Under-qualified names (`db.table` for a recorded `catalog.db.table`) are resolved by
suffix and the resolution is printed. trace navigates; for the full per-field
derivation at any hop, follow up with `chain` on that task's artifact dir.

The first run builds a routing index at `<artifacts-root>/.scope-lineage-index.json`
and later runs refresh it incrementally by file fingerprint (stderr says
`built` / `reused` / `updated`). The index is a disposable cache — delete it to force a
full rebuild; artifacts remain the single source of truth.

### "生成 mapping 文档" — render

```bash
scope-lineage render --lineage <artifacts-dir>    # writes mapping.md next to each lineage.json
```

Task documents render one section per statement. `--out <dir>` mirrors the tree
elsewhere; `--field`, `--sections`, `--expanded` narrow or expand the content. The
document is a derived view — every fact links back to lineage.json ids.

### "这个任务在做什么 / 生成业务画像" — describe

```bash
scope-lineage describe --lineage <artifacts-dir>   # writes semantic.json + semantic.md next to each lineage.json
```

Produces a deterministic **semantic skeleton** of the task: target table and partition,
input tables with their column comments, output shape and grain, the stage-by-stage
processing chain, a flat rule list, and per-field semantics. `--out <dir>` mirrors the
tree elsewhere, same as `render`. When a whole corpus is available, run
`scope-lineage tables --lineage <artifacts-dir> --out <dir>` first and pass
`describe --tables <dir>/tables.json`: each input table then carries its upstream
producer's own grain and keys under `inputs[].card`, and the target table lists who reads
it under `task.downstream_consumers` — the two answers a single task cannot prove.
Run `scope-lineage glossary --lineage <artifacts-dir> --out <dir>` on the same corpus and
pass `describe --glossary <dir>/glossary.json` to fill `fields[].value_domain[]`: the
constants each column is compared against, whether the SQL proved the set closed, and the
meaning of each value when a human confirmed one in `glossary.overrides.json` or a comment
literally spells it out. **Take the "取值含义" column of a field dictionary from
`fields[].value_domain[].meaning` first** — `status: "confirmed"` is a fact, `candidate`
is a lead to write with `?`, and a value with no meaning is 待确认. Never infer a code's
meaning from its spelling.

Read `semantic.md` — not lineage.json — to answer "what does this task do", "what does
field X mean", "what is one row of the output table". It is written to be read whole;
lineage.json is not. Pull `semantic.json` by path (`output_shape`, `stages`, `rules`,
`fields`, `confidence`) when you need the structured form, and fall back to
`scripts/query.py chain` for one field's full derivation.

Every line in the skeleton carries one of three tags: `SQL事实` (verbatim from the SQL),
`元数据事实` (table/column comments and types), or `结构推断` (provable from the query
structure, with an evidence id). **`结构推断` is not a business definition.** "Groups by
`customer_id`, orders by `event_time` DESC, keeps row 1" is a structural fact; "takes the
customer's latest status" is your inference and must be labelled as such. The skeleton
deliberately contains no business entity names, no business table types (宽表/名单表/
指标表), and no "the goal of this task is…" — their absence is the design, not a gap.

When the user wants a business profile, generate `business_profile.md` from the skeleton
following `references/semantic-profile-prompt.md`. It delivers **three pieces plus an
appendix** in one file: a **task semantic card** (≤ 1 page, business language, no source
tags), a **field dictionary** (every output column, with a 7-row metric spec card per
measure), and an **open-questions list** (≤ 15 items a business owner can answer in five
minutes) — with the evidence, tag system, risk table and self-check moved into the
appendix. Fill `references/business-profile-template.md`. For a whole corpus, loop over
the task directories yourself — there is no batch mode in the CLI.

### "这个结果可信吗 / 为什么断了" — diagnostics

Read the relevant warning and gap entries (they are in `query.py summary` counts;
details live in the artifact's `diagnostics` and `diagnostics.json`). Interpret each
type using `references/diagnostics.md` — it maps every warning/gap type to what
happened and what the user can do about it (usually: supply metadata, or accept the
documented uncertainty).

## Reference files

- `references/artifact-guide.md` — the artifact's structure: which JSON path answers
  which question. Read when you need something query.py does not surface.
- `references/metadata-inputs.md` — the three metadata flags, what each one feeds, and
  the silent degradation when one is missing. Read before parsing real tasks.
- `references/diagnostics.md` — every warning/gap type, its meaning, and honest
  phrasing for reporting it. Read when artifacts show warnings or gaps.
- `references/semantic-profile-prompt.md` — how to turn a `describe` skeleton into a
  `business_profile.md`: the three-piece delivery (task semantic card / field dictionary /
  open-questions list) plus the evidence appendix, the `[推断]` `[待确认]` marking rule,
  the structural-word-to-plain-language table, the length budget per piece, and the
  self-consistency pass. Read when the user asks what a task does in business terms, not
  just where a field comes from.
- `references/business-profile-template.md` — the blank skeleton of those three pieces and
  the appendix, with `{…}` placeholders. Fill it rather than inventing a layout.
