---
name: scope-lineage
description: >-
  Answer Spark/Hive SQL lineage questions with verifiable evidence using the scope-lineage
  CLI: parse SQL files or scheduler task JSON into field-level lineage artifacts, explain
  how a target column is derived step by step, find which tasks/columns depend on a table
  or column (impact analysis), and generate human-readable mapping.md documents. Use this
  skill whenever the user mentions 血缘 / lineage / 字段来源 / 加工步骤 / 影响分析 /
  mapping 文档 / 字段映射 / 任务画像 / 语义描述 / 表语义 / 字段含义 / 实体关系 / 本体 / 表关系 /
  ER 图 / 验收 / 问题集 / 判分, asks "这个字段怎么算出来的", "这个任务在做什么", "谁依赖这张表",
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

The minimum version depends on the workflow (`--version` itself exists from 0.2.1; the
fallback covers 0.2.0):

| Workflow | Needs |
| --- | --- |
| parse, derivation chain, impact, cross-task trace, render | >= 0.2.0 |
| describe, `tables`, `glossary`, `ontology` (key-fold candidates) | >= 0.3.0 |
| concept-level impact (`concept-impact`, key-fold `ontology-json/2` only), `catalog build` / `query` / `render` / `validate`, table semantics (`semantic *`), `catalog digest` / `merge`, acceptance (`questions *`) | >= 0.5.0 |
| confirmed answers in material packets (`semantic packet --glossary` / `--metadata-patch`) | >= 0.6.0 |
| code-set lookups in a catalog (a code set's `lookup`, a binding's `code_sets`, `code_sets_by`, `holds`, `lang`) | >= 0.7.0 (0.6.0 rejects them as schema errors) |
| lookup facts in the drafting digest (`catalog digest --lineage` / `--schema`) | >= 0.7.0 (0.6.0 rejects the flags) |
| the table-semantics loop this skill describes (`semantic fixed`, `semantic validate --only`, `table-semantics-status/2`, prompts `@8` / `@8` / `@5`) | >= 0.7.0 |
| prompts `@9` / `@9` / `@6` (they read the 0.8.0 packet's new facts) | >= 0.8.0 |

When unsure which workflows the session will need, require >= 0.8.0. A release candidate run
from a checkout may still print the previous number (`scope-lineage 0.7.x (…, source <commit>)`):
it counts as 0.8.0 when `CHANGELOG.md` opens with `## Unreleased` and
`references/table-semantics-prompt.md` names `@9` (`references/runbook.md` S0). A table-semantics
run directory made with an older release: rebuild its packets; every document whose packet changed
is then `packet_stale` and is rewritten whole (runbook S3 and S4).
Not installed → `pipx install 'scope-lineage[catalog]'` (or `pip install 'scope-lineage[catalog]'`):
the `catalog` extra brings PyYAML, which `catalog` and the acceptance commands (`questions`) need to
read `.yaml` / `.yml` files; when every catalog, question set and grades file is JSON, plain
`scope-lineage` is enough. Too old → upgrade in place. This check is not optional: a stale install silently produces the
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
python3 scripts/confirmations.py apply <task-dir>/business_profile.md \
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

### "整理这批任务的实体关系 / 本体 / 这批表对应哪些业务概念" — business ontology: where to start

业务本体（有哪些概念、客户是哪几张表、概念之间什么关系、有哪些事件）一律走**表语义 → 本体目录**，
不要用下一节的 `scope-lineage ontology` 回答：

1. 目录已经有了（`catalog-yaml/1` 或它 build 出的 `ontology.json`）→ 直接问目录，见
   「"客户是什么 / 这张表装的是什么 / 这个字段指什么" — 用目录回答业务问题」。
2. 还没有目录，这批表已经有表语义 → 按「"从表语义起草本体目录" — drafting procedure (digest → fragments → merge)」
   跑 `catalog digest` → 起草 → 片段 → `catalog merge` / `build` / `render`，再用 `catalog query` 回答。
3. 连表语义也没有 → 先按「"这张表是什么意思 / 给这批表写表语义" — table semantics」写表语义
   （`semantic *`），再走第 2 步。

键折叠候选（下一节）可以在起草时作为交叉证据旁读，但它的概念不是业务本体，不能直接当答案。

### 键折叠候选（旧 ontology）— key-fold candidates

**What it is for, and what it is not.** `scope-lineage ontology` folds tables into
"concepts" by a rule: tables that share a key-column stem become one concept, named from
column comments. That makes it a quick structural scan of a corpus — which tables share
which keys, which joins were proven or assumed, what the SQL contradicts — and a source of
cross-evidence while drafting a catalog. It is **not** the business ontology and is not the
route for business questions: a rule cannot tell a code dictionary from an entity, can
split one business thing across two stems, and never produces events. On real corpora the
table semantics → catalog route (previous section, 「business ontology: where to start」)
gets exactly those right. Use this section when the user asks for key-level structure
(shared keys, join cardinality, governance findings) or explicitly for the key-fold output;
word its "concepts" as key-fold candidates, never as the warehouse's business concepts.

```bash
scope-lineage tables    --lineage <corpus> --out <dir>
scope-lineage glossary  --lineage <corpus> --out <dir>
scope-lineage ontology  --lineage <corpus> --out <dir> \
  --tables <dir>/tables.json --glossary <dir>/glossary.json
```

The run writes `ontology.json` (machine, `ontology-json/2`),
`ontology.md` (the index), `concepts/<file>.md` (one per folded concept,
`concept-md/1`), `appendix.md` (everything table-level, `ontology-appendix-md/1`) and
`tables/<db.table>.md` (the table card with five ontology sections appended). The JSON is concept-first: `concepts[]` are the key-fold concepts,
`relations[]` the relations **between concepts**, `tables[]` the warehouse tables that
*represent* them and `table_relations[]` the JOINs that are the **evidence** (0.4.0 renamed
the old `entities[]` and `relations[]`; `--legacy-keys` writes the old names for one
release). `--tables` / `--glossary` only save
a recomputation — the bytes are identical without them. Add `--export linkml,shacl` when
the user wants the candidate in an RDF toolchain: it writes `ontology.linkml.yaml` and
`ontology.shacl.ttl` beside the JSON, each element still carrying its tier.

**Read in this order.** `ontology.md` first (its first line says it is key-fold candidates,
not the business ontology), and it reads concept-first: 「本体总览」 says
how many concepts of each kind the key fold proposes, how many are still 临时概念, and
「待人工判定 N 条 / G 组（已确认 M 条）」; the concept `flowchart` is the key-fold structure on one
screen. **To read one concept, open its own file**: every row of the 「概念」 table links to
`concepts/<file>.md` (`concept:cust` → `concepts/cust.md`), and that file — not the table
list — is what describes one folded concept: its 表现 (which tables represent it, in which
role, at which grain, each linked to its card), every attribute with the columns behind
it, its constraints, its relations with the table-level JOINs each was read off as
evidence, its open questions, what voted for its name and kind, and the exact
`concepts.overrides.json` key to answer under. A 临时概念 has no file: it is a question,
and the answer to it is a `merge_into`. The index says how many there are and prints the
**top 20 by impact** — the same order `--review-batches` queues them in; the whole list
is in `appendix.md` under the same heading.
Everything table-level is in `appendix.md`: the Mermaid `erDiagram`, the table list
(its 图中 id column maps a diagram box back to its table), the table relations (each naming
the concept relation it folded into), that provisional list and the folded open list;
`ontology.md` keeps only 「附录索引」, one line per section with its count and a link. That last section,
「待人工判定清单（N 条，折叠为 G 组）」, is every open
question in one place, folded by (kind, table family, question shape): one row per group,
with a stable `open:group:` id, the representative question, an `影响` score, how many
items it covers and a write-back pattern whose `<table>` the reviewer fills in per table.
A relation's group is about its far side — "is that table unique on these columns" — so
every task joining one dimension is one question. Groups rank by impact (a relation's
producers plus their tasks; a key's assumed edges; a finding's items), then by size, then
by the representative's rank; the first 50 print and the rest are summarised in one line. The item-by-item list lives in `open_items[]` in the
JSON, and the family members in `families[]`. Then the one card you need — never the JSON,
and never all the cards. A card's sections 7-11 are 身份 / 关系 / 约束 / 属性同义 / 待人工判定;
sections 1-6 are the ordinary table card. Section 7 opens with which concept this table
represents and which other tables represent the same one; section 8 shows the concept
relations its joins fed, with the table-level JOINs beneath them as evidence.

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

**When the user wants the key-fold concepts themselves reviewed** (not what the corpus is
*about* — that is the table semantics → catalog route,
「business ontology: where to start」 above), read `ontology.md`'s 「本体总览」 and 「概念」
parts, open the concept files the table links to for the ones in question, and follow `references/concept-review-prompt.md`. It is the same corpus's
*second* review round and it answers different questions: the kind of
each concept (entity / event / summary, with the votes in `kind_evidence[]`), its business
name (never better than a hypothesis — `name_candidates[]` is ranked, and a concept whose
`name_tier` is `stem_only` was named by nothing but the key stem, an English abbreviation
nobody asked for), which concepts are one
thing written twice (`possible_duplicate_of`), which one is two things, and which member
tables were read as the wrong kind of copy. The round opens on the 「临时概念」 table: a
table no business key placed is published as a concept of its own at
`tier: "provisional"`, and deciding what each of those really is — a copy of an existing
concept, part of a new one, or its own thing — is the first thing the prompt asks for. Same evidence discipline as the round above:
close what the corpus answers yourself with a `basis` on every entry, ask a business owner
**at most 8**, never self-answer a split. The answers go back through a separate file:

```bash
scope-lineage ontology --lineage <corpus> --out <dir> \
  --concept-overrides <dir>/concepts.overrides.json
```

Confirmed names, kinds and roles come back at tier `confirmed`; a `merge_into` folds one
concept's tables, attributes and key stem into another (and, because it is applied before
the concept relations are folded, moves that concept's edges with it); `splits[]` publishes
`concept:<stem>-<n>` per named group. Check `concept_overrides_applied.unmatched` and
`.ignored_fields` every round, exactly as above.

### "这个概念改了会影响谁" — concept-level impact

```bash
python3 scripts/query.py concept-impact <concept id | 概念名> \
  --ontology <ontology-dir>/ontology.json --lineage <artifacts-root> \
  [--depth N] [--attribute <属性名>] [--json]
```

`impact` / `trace` 回答的是表和列，业务方问的是概念。这个子命令把两层接起来：从
`ontology.json`（必须是 `ontology-json/2`）取这个概念的**表现表**（含 role）与**概念关系**
（方向、type、cardinality、tier），再用与 `trace` 同一套语料下游机制，列出每张表现表的
**下游任务**——按任务去重，每条说明读的是哪张表、在第几跳（`--depth` 默认 1）。
`--attribute <属性名>` 把答案收窄到该属性 `sources[]` 的源列：只留读到这些列的任务，
并只列出 JOIN 列包含该属性的概念关系。`--json` 输出同一份答案
（`{concept, tables[], relations[], downstream[], attribute?}`）。

先跑一次 `scope-lineage ontology`（见上一节「键折叠候选」）拿到 `ontology.json`，语料产物用同一个
`--lineage` 根目录，首次运行会复用/生成 `.scope-lineage-index.json`。概念可以按 id、
按完整概念名、或按唯一前缀指定；前缀撞上多个概念时脚本列出候选并退出 2，**不猜**。
本体缺失或版本过旧、概念或属性不存在，都是一句话 + 退出码 2。回答时把 tier 带上：
`hypothesis` 的关系是作者假设，不能说成事实（见上一节的分级规则）。这里的「概念」是键折叠候选，
回答时照此称呼，不要说成业务本体的概念。

**只认键折叠的 `ontology-json/2`。**`catalog build` 写的 `ontology-json/3`（业务目录）会被拒绝：一句话 + 退出码 2，
提示里的「re-run `scope-lineage ontology`」说的是键折叠候选，不是让你把目录换掉。问的是业务目录里的概念时，
先用 `catalog query <dir>/ontology.json carriers <概念>`（带这个概念标识符的表）和 `related <概念>`（它自己的表、
一跳关系与事件及同表携带的表）列出表，再对这些表跑 `impact` / `trace` 看下游任务；见下一节。

### "客户是什么 / 这张表装的是什么 / 这个字段指什么" — 用目录回答业务问题

有人维护的本体目录（`catalog-yaml/1`）时，业务问题先问目录，不要从 SQL 重新推。

```bash
scope-lineage catalog build <catalog-dir> --out <dir> \
  [--lineage <artifacts-root>] [--tables <tables.json>]     # once: ontology.json + evidence
scope-lineage catalog query <dir>/ontology.json <kind> <term> --json
scope-lineage catalog render <dir>/ontology.json --out <pages-dir>   # the fallback
```

**query 优先，页面兜底。** `query` 的八种 kind 各答一类问题：`concept`（这是什么）、
`table`（这张表承载什么、怎么取数、记录范围、每列指向什么）、`column`（`库.表.列` 是哪个属性/标识符）、
`identifier`（怎么唯一识别、落在哪些列）、`attribute`（这个属性在哪些表列、码值、口径）、
`related`（一跳邻居：关系、事件、角色、表）、`carriers`（哪些表带着这个概念的标识符）、
`scope`（哪些表只收有效记录、去掉删除注销、去重、按分区快照）。`--json` 的 `{query, matches[]}` 直接引用；
没有匹配时退出 1，**如实说目录里没有**，不要拿近似名去猜。只有一个问题要连着看概念页
（开头的一页纸概览，附录 A1–A7：定义、数据清单、带本概念标识的表、属性、关系、约束、治理缺口）时，才读 `render` 出的
`concepts/<slug>.md`；不要把整个 `ontology.json` 读进上下文。答案里带上状态
（`drafted` = 草拟，未经确认）和证据标签（「血缘」是语料证明的，不是目录的声明）；
`conflicts` 或页面附录 A7 的「证据与目录矛盾」要原样转述。细节见
`references/catalog-questions.md`。

### "这张表是什么意思 / 给这批表写表语义" — table semantics

一张表对业务读者意味着什么（一行是什么、怎么取数、收哪些记录、每个字段什么意思、要注意什么），由模型按提示词写、
CLI 对照材料包校验、独立审读、修订，再渲染成页面（`semantic packet` / `status` / `validate` / `digest` / `fixed` /
`render` / `confirm`）。**要给一批表写表语义时，照 `references/runbook.md` 的 S0–S9 一步一步做**，派子代理用
`references/runbook-templates.md` 的 T1（写作）、T2 / T3（审读、复审）、T4（修订）；状态与下一步查 runbook 附录 A。
不可违反的三条：

1. **每张表的每一步各是一个独立子代理**：写作、审读、修订互不共享上下文，审读不能是写作者自己（审读用最强模型）。
2. **验收题集不给写作、审读、修订**：那是考卷。
3. **低级问题不修；材料包变了就整份重写**（不许只改 `packet_digest`）；写作或修订两轮后仍有校验 FAIL 的表标为
   blocked，不渲染、不进目录，交 owner。

只读已经渲染好的页面时：✓ 是已确认，⚠ 是矛盾或风险，✗n 是校验未通过（文末「校验」一节），`值（含义待确认）`
是只有值没有含义的码值。格式、十三项检查、确认文件和 `semantic status` 的阶段与标记见
`../../docs/zh-CN/table-semantics.md`。

### "从表语义起草本体目录" — drafting procedure (digest → fragments → merge)

一批表已经有表语义（`table-semantics/1`）后，本体目录（`catalog-yaml/1`）从它们起草，不写临时脚本：
`catalog digest` → 起草概念、标识符、关系与共用码值集并分组 → 每组一个片段（`catalog-fragment/1`）→ `catalog merge` →
`catalog build` → `semantic render --ontology` → `catalog render --semantics`。**照 `references/runbook.md` 的 S10a–S10g 做**；
起草（第 2 步）用 runbook-templates 的 T5，片段用 T6（它包着 `references/catalog-fragment-prompt.md`，码值集、`holds`、
`code_sets` 的规则都在那份提示词里）。不可违反的三条：

1. **digest 是起草的全部输入**，不要把整份表语义读进一次调用；digest 固定带 `--lineage`（有元数据再带 `--schema`）。
2. **片段不能新增概念、不能改已有标识符**：新概念（事件连同它的时间属性）、新标识符、新拼写、跨组属性在起草这一步写好。
3. **合并冲突逐条交回对应的组**，不要手工挑一个；合并后的手工修正只改 `merged/` 并留记录。

片段格式、合并规则和退出码见 `../../docs/zh-CN/ontology-catalog.md` 的「起草」一节。

### "这些页面能不能用 / 给页面打分" — 验收

表语义页和概念页写好后，用 owner 给的问题集（`question-set/1`）考页面：作答者只读页面答题，判分者对照参考答案和材料
判 2/1/0，`scope-lineage questions validate` / `sheet` / `grading-sheet` / `score` 做确定性的部分。**照
`references/runbook.md` 的 S11 做**，作答用 runbook-templates 的 T7（便宜模型即可），判分用 T8（最强模型）。不可违反的三条：

1. **作答与判分是两个独立子代理**：作答者只拿题单和页面目录，看不到题集、参考答案、材料包或 SQL。
2. **`sheet`、`grading-sheet`、`score` 带同一组 `--ids` / `--only-table`**，否则会混进没答、没判的题（只给警告、退出 0）。
3. **不自己出题自己考**；留出集只在收尾时跑一次。

读 YAML 题集要 `catalog` extra（PyYAML）。格式与命令见 `../../docs/zh-CN/questions.md`。

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
- `references/ontology-review-prompt.md` — how to turn the key-fold candidates' 待人工判定
  items into a question list a business owner can answer in five minutes, and how the
  answers are filed back into `ontology.overrides.json`. Read when the user asks about the
  keys and join cardinalities of a batch of tasks (for the business ontology, see the
  catalog references below).
- `references/concept-review-prompt.md` — the concept layer's own review round: the fixed
  order (the provisional concepts first, then kind → name → merges → splits → roles), the
  six kinds of evidence that let an Agent answer one itself, the five kinds worth a
  business owner's time, and how the answers are filed back into
  `concepts.overrides.json`. Read when the user wants the key-fold concepts reviewed; which
  business concepts a corpus is about is answered by the catalog, not by this round.
- `references/catalog-questions.md` — answering business questions from an ontology
  catalog: which `catalog query` kind answers which question, when to fall back to the
  rendered concept page, how to report status, evidence and conflicts, and what to say when
  nothing matches. Read when a catalog (`catalog-yaml/1`) or its `ontology.json` exists.
- `references/catalog-fragment-prompt.md` — the prompt one sub-agent per group follows to
  draft a `catalog-fragment/1` file from table semantics: what to read, the fragment shape,
  one attribute per business meaning, a binding for every column, and the `catalog merge`
  self-check. Read when drafting a catalog from table semantics.
- `references/table-semantics-review-prompt.md` — the independent review checklist (16 items, from
  grain and derived-code NULLs to page consistency, sibling tables and tool verdicts the SQL
  overrules) that finds factual errors validation cannot, the first review after a rewrite with the
  old review at hand, and the front matter (`reviewed_doc_digest`, `reviewed_packet_digest`,
  high / medium / low counts) every review opens with. Read when running the review step.
- `references/table-semantics-fix-prompt.md` — how to apply review findings, re-read the page for
  contradictions, and record the finished fix with `semantic fixed`. Read when running the fix step.
- `references/table-semantics-prompt.md` — the prompt a model writes one
  `table-semantics/1` document from, given one table's `packet.md`: the one-page summary
  first, then every column in table order, the steps, the rules with their SQL quoted and
  the producing task, every item with its sources; how to write when the SQL overrules a
  packet verdict; which packet facts are clues rather than facts (a producer's header comment,
  a governance finding, an update-time column, a downstream known only by task name, a
  partition day derived from a create or update time); and the rewrite section to hand back
  with `semantic validate`'s failures. Read when the user asks what a table means, or
  wants a batch of tables documented.
- `references/runbook.md` — the step-by-step operating manual (Chinese) for producing table
  semantics, the ontology catalog and the pages, and for the acceptance round: one shared variable
  block and calling convention, steps S0–S13 each with purpose, preconditions, copy-ready commands,
  self-checks, known failures and a done criterion, plus the status → next-step table, the run
  directory layout, an error / exit-code index and the cost rules. Read it before running any of
  those three workflows; it overrides looser wording elsewhere in this file.
- `references/runbook-templates.md` — the orchestrator's checklist, the fill-in sub-agent prompts
  T1–T8 (draft, review, re-review, fix, catalog drafting step 2 with the grouping plan, fragment,
  answer, grade), the run ledger and the delivery report. Hand a sub-agent exactly one filled template.
- `references/answer-prompt.md` — the acceptance answerer: read only the pages, cite page and
  section, mark only what the pages truly cannot decide as owner-to-confirm, no over-hedging, one
  `## <id>` section per answer. Read when running the answer step of an acceptance round.
- `references/grade-prompt.md` — the acceptance grader: 2/1/0, the owner-only, over-hedging and
  wrong-reference-answer rules, the seven gaps, and the `question-grades/1` YAML it outputs. Read
  when running the grading step.
- `../../docs/en/workflow.md` (`../../docs/zh-CN/workflow.md` for the Chinese version) — the
  end-to-end order of everything above: what `parse` / `tables` / `glossary` / `describe` /
  `ontology` (key-fold candidates) / `semantic` / `catalog` need from each other, a runnable five-minute pass over `examples/`, where each of
  the three review workflows fits, and how confirmed answers flow back through
  `glossary.overrides.json` / `ontology.overrides.json` / `metadata-patch.json`. Read when the
  user asks how the whole thing is used, or when you are unsure which command comes next.
- `scripts/confirmations.py` — the write-back half: reads the answered 待确认清单 out of a
  `business_profile.md` and merges it into `glossary.overrides.json` /
  `metadata-patch.json`. Run it after the business owner answers, then re-run `glossary`
  and `describe` with those two files.
