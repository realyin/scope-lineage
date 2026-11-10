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

## Start here: task JSON + table schema → business semantics and ontology

If you are handed a directory of task JSON and a table-schema directory and asked for task
semantics, table semantics or a business ontology, do not improvise from the workflows below:
**use the `scope-lineage-ontology` skill** (`../scope-lineage-ontology/SKILL.md` in this
repository). It runs `references/runbook.md` S0–S13 as a loop driven by
`scripts/next_step.py`, with independent write / review / fix sub-agents and the S10g omission
check. `scope-lineage ontology` alone gives key-fold candidates, never the business ontology.

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
| prompts `@10` / `@10` / `@7` (a rewrite's corrections list, the validity-window sentence the 0.9.0 validator accepts, a fix log the next rewrite reads) | >= 0.9.0 |
| prompts `@11` / `@10` / `@8` (a snapshot partition read conditionally when the material says the source deletes old rows; a fix keeps `sources` / `confidence` in step with reworded items) | >= 0.9.0 |
| prompts `@12` / `@11` / `@8` (the packet's `join_condition` / 未读 labels and five new governance leads; review severity anchors), a catalog with `metrics`, constraint `rules` / `predicate`, attribute `additivity`, binding `time_role` | >= 0.11.0 |
| filters that bind a bare `WHERE` column to its source when a SELECT alias shares its name (0.11.0 and older rewrote it into the alias expression) | >= 0.11.1 |
| row conditions on constant columns closed rather than gaps, GROUP BY keys bound to source columns first, unbound `${…}` table names reported as `input_incomplete`, check 9's date-filter shapes (`period` / `snapshot_pick` / `cutoff`), and a runbook that runs from a pip install (`SKILL` / `SCHEMAS`) | >= 0.11.2 |

When unsure which workflows the session will need, require >= 0.11.2 (`references/runbook.md`
S0). A table-semantics run directory made with an older release: rebuild its packets; every document whose packet changed
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

Each workflow is one file under `workflows/`. Find the row that matches the question, read that one file, and follow it.
Paths inside those files (`scripts/...`, `references/...`) are relative to this skill directory, like the paths here.
A workflow that names another by its quoted heading means the file with that heading in the table.

| When the question is | Read | Heading in that file |
| --- | --- | --- |
| 解析一个 SQL 或任务的血缘 | [`workflows/parse.md`](workflows/parse.md) | "解析这个 SQL / 任务的血缘" — parse |
| 某个字段是怎么加工出来的 | [`workflows/chain.md`](workflows/chain.md) | "字段 X 是怎么加工出来的" — derivation chain |
| 谁依赖某张表或某一列 | [`workflows/impact.md`](workflows/impact.md) | "谁依赖表 T / 列 C" — impact analysis |
| 跨任务追溯上下游 N 层 | [`workflows/trace.md`](workflows/trace.md) | "跨任务追溯上下游 N 层" — cross-task trace |
| 生成 mapping 文档 | [`workflows/render.md`](workflows/render.md) | "生成 mapping 文档" — render |
| 这个任务在做什么；生成任务语义骨架、业务画像、术语与值域确认 | [`workflows/describe.md`](workflows/describe.md) | "这个任务在做什么 / 生成业务画像" — describe |
| 要业务本体（概念、关系、事件）时先看：该走哪条路 | [`workflows/business-ontology.md`](workflows/business-ontology.md) | "整理这批任务的实体关系 / 本体 / 这批表对应哪些业务概念" — business ontology: where to start |
| 键折叠候选（旧 `ontology` 命令）：结构扫描、概念层评审 | [`workflows/key-fold.md`](workflows/key-fold.md) | 键折叠候选（旧 ontology）— key-fold candidates |
| 某个概念改了会影响谁 | [`workflows/concept-impact.md`](workflows/concept-impact.md) | "这个概念改了会影响谁" — concept-level impact |
| 用本体目录回答业务问题（客户是什么、这张表装的是什么） | [`workflows/catalog-answers.md`](workflows/catalog-answers.md) | "客户是什么 / 这张表装的是什么 / 这个字段指什么" — 用目录回答业务问题 |
| 一张表是什么意思；给一批表写表语义 | [`workflows/table-semantics.md`](workflows/table-semantics.md) | "这张表是什么意思 / 给这批表写表语义" — table semantics |
| 从表语义起草本体目录 | [`workflows/catalog-drafting.md`](workflows/catalog-drafting.md) | "从表语义起草本体目录" — drafting procedure (digest → fragments → merge) |
| 页面能不能用；给页面打分 | [`workflows/acceptance.md`](workflows/acceptance.md) | "这些页面能不能用 / 给页面打分" — 验收 |
| 结果可信吗；血缘为什么断了 | [`workflows/diagnostics.md`](workflows/diagnostics.md) | "这个结果可信吗 / 为什么断了" — diagnostics |

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
- `references/runbook.md` — the index of the step-by-step operating manual (Chinese) for producing
  table semantics, the ontology catalog and the pages, and for the acceptance round: the overview
  table of S0–S13 and which file holds each step. Each step is one file, `references/steps/<step>.md`
  (`S0.md` … `S13.md`, `S10a.md` … `S10g.md`), with purpose, preconditions, copy-ready commands,
  self-checks, known failures and a done criterion; `references/steps/00-before.md` holds the
  run's `env.sh`, the calling convention, the sample rule and the ledger; `appendix-A.md` …
  `appendix-D.md` hold the status → next-step table, the run directory layout, an error /
  exit-code index and the cost rules. Read the index, then only the file of the step you are on;
  the steps override looser wording elsewhere in this file.
- `references/runbook-templates.md` — the index of the templates and how to fill them. Each is one
  file under `references/templates/`: the fill-in sub-agent prompts `T1.md` … `T8.md` (draft,
  review, re-review, fix, catalog drafting step 2 with the grouping plan, fragment, answer,
  grade), the orchestrator's `checklist.md`, the run `ledger.md` and the delivery `result.md`.
  Hand a sub-agent exactly one filled template.
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
- `scripts/init_run.py` — writes a run's `env.sh` from `--run`, `--scratch`, `--tasks`, `--schema`
  (and the optional paths), quoted so nothing is expanded; never overwrites one. Run it first, as
  `references/steps/00-before.md` 0.1 says; nobody writes `env.sh` by hand.
- `scripts/runlib.sh` — the run's shell functions `sl`, `fill`, `note`, `load_tables`; sourced by
  the last line of `env.sh`, never run on its own.
- `scripts/fill.py` — what `fill` calls: fills one template of `references/templates/` and
  refuses (exit 1) a wrong template, mode or missing premise.
- `scripts/next_step.py` — where a runbook run stands: reads only the run directory's files and
  prints the S0–S13 checklist, the current step, why, and the file of that step to read, and each table's next action from
  appendix A while table semantics is in progress. It reads `status.json` rather than
  recomputing stages, and asks for a fresh one when it is missing or stale. Run it after every
  step, as `references/runbook.md` 0.6 says.
- `scripts/catalog_check.py` — what a built catalog left undone, which `catalog validate` cannot
  see: concepts with no attribute, an event table's foreign identifier whose concept is not a
  participant, a name / description column bound to the table's own concept beside a code
  column that points at another concept, a state attribute with codes and no `states`, a
  measure with no unit, a code-like column bound as a plain attribute, and (with `--digest`
  and `--changes`) a filter / dedup / derive rule of the digest that no constraint carries and
  no `skip` line names. Run it on `onto/ontology.json` as `references/steps/S10g.md` says;
  exit 1 when it has findings.
- `scripts/make_corrections.py` — the corrections list a whole rewrite hands its writer: reads
  the old review, the first review behind a re-review, the fix log and the rebuilt packet, and
  sorts every old finding into fixed (follow it), worth a look (check it first) or out, saying
  which ones it could not read or check; with the old document (`--prior-doc`) it adds the old
  wording beside each unchecked item and the old watch / question points whose cited material
  is still in the new packet. Run it as `references/steps/S4.md` says.
- `scripts/confirmations.py` — the write-back half: reads the answered 待确认清单 out of a
  `business_profile.md` and merges it into `glossary.overrides.json` /
  `metadata-patch.json`. Run it after the business owner answers, then re-run `glossary`
  and `describe` with those two files.
