---
name: scope-lineage
description: >-
  Answer Spark/Hive SQL lineage questions with verifiable evidence using the scope-lineage
  CLI: parse SQL files or scheduler task JSON into field-level lineage artifacts, explain
  how a target column is derived step by step, find which tasks/columns depend on a table
  or column (impact analysis), and generate human-readable mapping.md documents. Use this
  skill whenever the user mentions 血缘 / lineage / 字段来源 / 加工步骤 / 影响分析 /
  mapping 文档 / 字段映射 / 任务画像 / 语义描述 / 字段含义 / 实体关系 / 本体 / 表关系 /
  ER 图, asks "这个字段怎么算出来的", "这个任务在做什么", "谁依赖这张表",
  "这个 SQL 读了哪些表", "这批任务里的表是什么关系", or wants to analyze,
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
  --sql-file <file.sql>            # or --task-file <task.json> / --input-dir <dir> (repeatable)
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
meaning from its spelling. A value is stored unquoted in `value` with the author's literal
in `sql_literal` (show the literal, key an override on the unquoted form), `closed_set` is
the whole column's verdict, and a column only carries values it outputs itself or inherits
from a source it passes through unchanged — a CASE condition's constant belongs to the
column being tested. With `--tables`, a JOIN onto a physical table whose card proves the ON
clause's columns unique is re-decided `safe` (`basis: "table_card"`), and the statement's
keys and `key_confidence` are recomputed with it.

Read `semantic.md` — not lineage.json — to answer "what does this task do", "what does
field X mean", "what is one row of the output table". It is written to be read whole;
lineage.json is not. Pull `semantic.json` by path (`output_shape`, `stages`, `rules`,
`fields`, `confidence`) when you need the structured form, and fall back to
`scripts/query.py chain` for one field's full derivation.

`confidence.findings[]` carries a `severity`: `warn` is a lead somebody has to act on,
`info` is true and needs no action. A task instance covers one day, so a partition filter
naming that day is the design, not a defect — `hardcoded_date_literal`,
`partition_literal_mismatch` and `table_comment_missing` are therefore `info`, section 6
counts them in one line instead of listing them, and a profile must not turn them into
使用注意 or into questions. The day itself is published as `task.instance_dates[]` and on
section 1's 「本实例取数日」 line (worded as this instance's day, replaced on every run), and a metric's date filter reads `kind: "instance_date"`.

Every line in the skeleton carries one of three tags: `SQL事实` (verbatim from the SQL),
`元数据事实` (table/column comments and types), or `结构推断` (provable from the query
structure, with an evidence id). **`结构推断` is not a business definition.** "Groups by
`customer_id`, orders by `event_time` DESC, keeps row 1" is a structural fact; "takes the
customer's latest status" is your inference and must be labelled as such. The skeleton
deliberately contains no business entity names, no business table types (宽表/名单表/
指标表), and no "the goal of this task is…" — their absence is the design, not a gap.

#### 确认回写：让答完的问题不再被问第二遍

The open-questions list is only worth writing if the answers come back. It is now capped
at **five items** and asks only what changes a number or a meaning, so the bulk of the
"what does this code mean" work runs through a generated form instead. Step 1 is to
generate that form; steps 2-4 collect what came back:

```bash
# 1. the fill-in form: the corpus's most-used values that nobody has explained yet
scope-lineage glossary --lineage <corpus> --out <dir> \
  --template <dir>/glossary.overrides.template.md [--template-top 20]
# the owner writes the meanings into the .md and the same-named .json

# 2-4. the answered five-item list, routed back into the same two files
python3 skills/scope-lineage/scripts/confirmations.py apply <task-dir>/business_profile.md \
  --by <name> [--overrides <dir>/glossary.overrides.json] [--patch <dir>/metadata-patch.json]
scope-lineage glossary --lineage <corpus> --out <dir> --overrides <dir>/glossary.overrides.json
scope-lineage describe --lineage <corpus> --glossary <dir>/glossary.json \
  --metadata-patch <dir>/metadata-patch.json
```

`--template` writes two files at one path — the markdown a person fills in and the
same-named `.json` that `--overrides` reads back. It asks the columns that carry evidence
first, then ranks by how much of the corpus rests on the column, and it leaves out what
nobody can answer or nobody needs to: match patterns, day literals, bare numbers with no
enumerated context, and anything already confirmed. An entry left blank comes back as
`blank` in the run summary and is **not** written in as a confirmed empty meaning.

Each row's 候选来源 column says which evidence that value has — `comment_enum`,
`comment_mention`, `case_label`, `case_label(桶 N)`, `same_name_confirmed` or `—`. Three of
them are evidence an Agent may answer a value **from** instead of asking a person
(`comment_enum`, a 1:1 `case_label`, `same_name_confirmed`); a `comment_mention` is a
sentence that merely says the value and a `case_label(桶 N)` is the bucket N values share,
and both are leads for a human rather than answers. Follow
`references/glossary-review-prompt.md` for that pass: it writes the evidence answers into
`glossary.overrides.json` itself, each with a mandatory `basis` and
`confirmed_by: "agent:<name>"`, never overwriting a human confirmation, and turns at most
8 of what is left into an open-questions file. A confirmation signed `agent:` with no
`basis` is refused and reported under `overrides_applied.rejected`
(`reason: "missing_basis"`); a misspelled slot lands in `overrides_applied.ignored_fields`.
Check both lists every round, next to `unmatched`.

The script routes each answer by its own 回写目标 line — `术语` / `值域` into the glossary
overrides, `字段注释` / `表注释` into a `metadata-patch/1` file — and never overwrites an
entry somebody already confirmed (`--dry-run` prints both documents instead of writing
them). The next profile then reads `value_domain[].meaning.status: "confirmed"`,
`fields[].target_comment_source: "patch"` and `inputs[].comment_source: "patch"`, must
**not** ask those questions again, and lists them under appendix A (已确认项) instead — so
each round the 待确认清单 gets shorter. `parse --metadata-patch` applies the same file when a
corpus is re-parsed; both paths write the same document.

When the user wants a business profile, generate **two files** from the skeleton following
`references/semantic-profile-prompt.md`. `business_profile.md` is what the reader gets:
**three pieces plus a short appendix** — a **task semantic card** (≤ 1 page, business
language, no source tags), a **field dictionary** (every output column, with a 7-row metric
spec card per measure), an **open-questions list** (≤ 5 items a business owner can answer in
five minutes, restricted to column-position mismatches, comment-versus-derivation conflicts,
unproven keys under a fan-out risk, and misnamed fields), and appendices **A 已确认项 /
B 备查项与待填取值 / C 风险边界**, which together must stay **≤ 1/3 of the body's character
count**. `business_profile.check.md`, written next to it, is the writer's QA record — input
file verification, the source-tag evidence table, the inferred-items list, the
self-consistency pass and the 14-item self-check — a required quality gate that keeps every
item but no longer sits in the reader's document. Fill
`references/business-profile-template.md` and `references/business-profile-check-template.md`.
For a whole corpus, loop over the task directories yourself — there is no batch mode in the
CLI.

### "整理这批任务的实体关系 / 本体" — ontology

```bash
scope-lineage tables    --lineage <corpus> --out <dir>
scope-lineage glossary  --lineage <corpus> --out <dir>
scope-lineage ontology  --lineage <corpus> --out <dir> \
  --tables <dir>/tables.json --glossary <dir>/glossary.json
```

A corpus-level question `describe` can never answer: **how do these tables relate**. The
run writes `ontology.json` (machine), `ontology.md` (index) and `tables/<db.table>.md`
(the table card with five ontology sections appended). `--tables` / `--glossary` only save
a recomputation — the bytes are identical without them. Add `--export linkml,shacl` when
the user wants the candidate in an RDF toolchain: it writes `ontology.linkml.yaml` and
`ontology.shacl.ttl` beside the JSON, each element still carrying its tier.

**Read in this order.** `ontology.md` first: its Mermaid `erDiagram` is the whole corpus
on one screen, its headline line says 「待人工判定 N 条 / G 组（已确认 M 条）」, and the
entity table says which card is worth opening (the 图中 id column maps a diagram box back
to its table). The last section, 「待人工判定清单（N 条，折叠为 G 组）」, is every open
question in one place, folded by (kind, table family, question shape): one row per group,
with a stable `open:group:` id, the representative question, an `影响` score, how many
items it covers and a write-back pattern whose `<table>` the reviewer fills in per table.
A relation's group is about its far side — "is that table unique on these columns" — so
every task joining one dimension is one question. Groups rank by impact (a relation's
producers plus their tasks; a key's assumed edges; a finding's items), then by size, then
by the representative's rank; the first 50 print and the rest are summarised in one line. The item-by-item list lives in `open_items[]` in the
JSON, and the family members in `families[]`. Then the one card you need — never the JSON,
and never all the cards. A card's sections 7-11 are 身份 / 关系 / 约束 / 属性同义 / 待人工判定; sections 1-6
are the ordinary table card.

**Every assertion carries a tier, and the tier is the answer.** `proven` 已证明 is written
in the SQL. `implied` 可推得 follows from what the SQL does. `hypothesis` 作者假设 is what
an author assumed and nobody proved. `conflict` 矛盾 is two tasks disagreeing. `confirmed`
已确认 exists only because a person answered the question in `ontology.overrides.json`.

- **Never report an `assumed` claim as a fact.** `many_to_one_assumed` means "the author
  joined this table directly and therefore assumed it is unique by that key" — write it
  that way, not as "this is a many-to-one relationship". The same for a `hypothesis`
  candidate key: it is a key somebody assumed, not a primary key.
- **`hypothesis` and `conflict` items must be surfaced verbatim and marked `[待确认]`.**
  They are the reason this document exists. Summarising them away, or averaging them into
  a confident sentence, is the single worst thing to do with this artifact.
- A `cardinality_conflict` is a **governance finding**, not an ontology fact: one task
  deduplicates a table by k and another joins it directly on k, so either the second
  multiplies rows or the first is dead weight. Report both sides and who to ask. Two more
  findings read the same way: `competing_candidate_keys` (two authors assumed two
  different identities for one table — at most one of them is it) and `key_hint_conflict`
  (a column comment names one column the key and every corpus guess names another).
- `identity.declared_hints[]` is what the **metadata** says about identity — a column
  comment calling a column 主键 / 唯一键 / primary key. It is a hint, never a key: report
  it as "the catalog's column comment says so", and note that where it agrees with a
  corpus guess the tier is already `implied` rather than `hypothesis`.
- An `in_set` constraint with `completeness: "unknown"` is a floor, never a ceiling: those
  values were *observed*, and the column may hold others.
- Core names no entity and infers no class hierarchy. If a business name is wanted, it is
  your inference over `naming_hints` and must be labelled `[推断]`.

**When the user wants the open items turned into questions**, follow
`references/ontology-review-prompt.md`. It runs in two passes: first close what the corpus
already answers (a producing task's proven grain, a column comment naming the key, two
tasks joining on the same key set) by writing those confirmations yourself, each with a
`basis` saying what closed it; then turn **at most 8** of what is left into a
five-line-per-item list a business owner can answer. The evidence pass needs the task
profiles — `semantic.md` beside each `lineage.json` — so run `describe` over the corpus
first if they are not there. The answers go back through `ontology.overrides.json`:

```bash
scope-lineage ontology --lineage <corpus> --out <dir> \
  --overrides <dir>/ontology.overrides.json
```

An override may carry `scope_columns` ("unique within one `dt`", the normal shape of a
snapshot table), plus `basis` and `note` recording why the answer is believed. Confirmed
assertions come back at tier `confirmed` and drop off the open list, so the headline
counter is how a second round sees what the first one bought. Check two lists every round:
`overrides_applied.unmatched` (an override that matched nothing, with a `reason` naming the
unknown entity or column) and `overrides_applied.ignored_fields` (a misspelled slot that
did not take effect). Both are where a typo in a reviewed file shows up.

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
  `business_profile.md` plus its `business_profile.check.md`: the three-piece delivery (task
  semantic card / field dictionary / open-questions list) plus the A/B/C appendix capped at
  1/3 of the body, the `[推断]` `[待确认]` marking rule, the structural-word-to-plain-language
  table, the length budget per piece, and the self-consistency pass. Read when the user asks
  what a task does in business terms, not just where a field comes from.
- `references/business-profile-template.md` — the blank skeleton of those three pieces and
  the A/B/C appendix, with `{…}` placeholders. Fill it rather than inventing a layout.
- `references/business-profile-check-template.md` — the blank skeleton of
  `business_profile.check.md`: input file verification, source tags and evidence, inferred
  items, the self-consistency result and the generation self-check. Written beside the
  profile, never merged into it.
- `references/glossary-review-prompt.md` — how to work the 取值含义待填模板: the three
  kinds of evidence that let an Agent answer a value itself (the column's own comment
  enumerates it, a CASE in the corpus labels it 1:1, a human confirmed the same value on
  the same column name elsewhere), the two that look like evidence and are not (a comment
  mention, a shared bucket label), the per-column conflict check, each answer written back
  with a mandatory `basis`, and how to turn the rest into at most 8 questions a business
  owner can answer — one of which may bind a whole code table by listing every key. Read when the user asks
  what a corpus's codes mean, or before filling in a generated template.
- `references/ontology-review-prompt.md` — how to turn a corpus ontology's 待人工判定
  items into a question list a business owner can answer in five minutes, and how the
  answers are filed back into `ontology.overrides.json`. Read when the user asks about
  entity relationships, keys or an ontology over a batch of tasks.
- `../../docs/en/workflow.md` (`docs/zh-CN/workflow.md` for the Chinese version) — the
  end-to-end order of everything above: what `parse` / `tables` / `glossary` / `describe` /
  `ontology` need from each other, a runnable five-minute pass over `examples/`, where each of
  the three review workflows fits, and how confirmed answers flow back through
  `glossary.overrides.json` / `ontology.overrides.json` / `metadata-patch.json`. Read when the
  user asks how the whole thing is used, or when you are unsure which command comes next.
- `scripts/confirmations.py` — the write-back half: reads the answered 待确认清单 out of a
  `business_profile.md` and merges it into `glossary.overrides.json` /
  `metadata-patch.json`. Run it after the business owner answers, then re-run `glossary`
  and `describe` with those two files.
