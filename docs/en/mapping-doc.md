[中文](../zh-CN/mapping-doc.md) | English

# The `mapping.md` field mapping document (mapping-md/1)

`scope-lineage render` turns a `lineage.json` (plus the `diagnostics.json` beside it) into
`mapping.md`, a field mapping document readable by both humans and machines.

> The rendered document itself is written in Chinese — its section titles and line labels are
> fixed Chinese strings, and they are part of the format. This page quotes them verbatim where the
> grammar depends on them.

## Positioning: a derived view, not a contract

- mapping.md is a **derived view** of the versioned contract: every fact in it comes from
  `lineage.json` / `diagnostics.json`, and the document carries no "orphan facts" from outside
  the contract.
- **The facts themselves always live in `lineage.json`.** Long-lived machine integrations should
  consume the JSON contracts directly; mapping.md targets reading, retrieval chunking (RAG
  chunks), and lightweight parsing.
- Stability tiers:
  1. the contract ids the document references (`mapping_chain_id`, `chain_id`, `logic_block_id`,
     scope_id) are as stable as `lineage.json` itself and can be used as join keys back into the
     JSON;
  2. the line grammar is only guaranteed stable within one `doc_format` major version (currently
     `mapping-md/1`); a line-grammar change increments that version number;
  3. section wording and layout may be adjusted without incrementing the version number, so
     machines must not depend on any text shape not listed in the "Line grammar" section below.

## Usage

```bash
# One statement: mapping.md is written next to lineage.json
scope-lineage render --lineage /path/to/task/lineage.json

# A corpus directory: lineage.json is found recursively; --out mirrors the input tree
scope-lineage render --lineage /path/to/corpus --out /path/to/docs

# Only one field's transformation steps; only some sections; add fully expanded expressions
scope-lineage render --lineage lineage.json \
  --field paid_amount --sections overview,steps --expanded
```

Python API (consumes contract document dicts, the same code path as file rendering):

```python
from scope_lineage import render_mapping_markdown

markdown = render_mapping_markdown(lineage_document, diagnostics_document)
```

- Both contract shapes are accepted: a **statement document** (`schema_version: "1.0"`) and a
  **task document** (`schema_version: "2.0"` with `artifact_kind: "task_lineage"`). For a task
  document the renderer emits one `## <statement_id>` section per write statement, in
  `statement_sequence` order, each holding that statement's complete mapping document; entries no
  `statement_sequence` row points at are rendered after the ordered ones. Any other version is
  skipped and counted in directory mode (`skipped_unknown_version=N` in the run summary) and
  raises an error in single-file mode.
- When there is no `diagnostics.json` in the same directory, rendering proceeds as usual, but
  section 9 states "无 diagnostics 文档" ("no diagnostics document") explicitly rather than staying
  silent.

## Document structure mapped to lineage.json fields

| Section | `--sections` name | Content | Fact source |
| --- | --- | --- | --- |
| 1. 概览 (Overview) | overview | Task, target table, statement kind, partitioning, parse status, target-binding summary | Top-level fields, `target_field_binding`; with no binding, the reason is given in Chinese from `target_binding_absent_reason`, and only `target_table_not_found` (the one case that risks landing in the wrong column) is marked ⚠ |
| 2. 来源表 (Source tables) | sources | Physical source tables and metadata completeness | `source_tables`, `related_metadata.input_tables` |
| 3. 来源表关系 (Source-table relations) | relations | An overview of physical-table relations + UNION merging (scope-level join details are in section 6) | `logic_blocks[].join_relation_detail`, `union_branch_alignment` |
| 4. 字段映射总表 (Field mapping table) | mapping | One row per target field, end to end (the "generated source" column appears only when there are constant fields) | `end_to_end_lineage[]` |
| 5. 加工步骤明细 (Transformation steps) | steps | The step-by-step chain per field | `field_mapping_chains[].ordered_steps[]` |
| 6. 加工逻辑汇总 (Logic summary) | logic | What each scope does: summary, filter conditions, that scope's join details | `scope_profile.steps[]` + `logic_blocks[].join_relation_detail` |
| 7. scope 结构图 (Scope graph) | graph | A mermaid data-flow diagram | `scope_graph` |
| 8. 任务依赖 (Task dependencies) | deps | The declared upstream and downstream tasks | `task_dependencies` |
| 9. 不确定性与缺口 (Uncertainty and gaps) | gaps | Only what affects lineage conclusions: incompletely traced fields, fact gaps, a warning-count pointer | `end_to_end_lineage[].trace_complete`, `diagnostics.json` |

Section numbering is fixed (filtering with `--sections` does not renumber), so sections can be
cited.

## Line grammar (mapping-md/1)

Machine readability comes from the document's own stable grammar, not from a second JSON.

### Front matter

The document head is a **flat** YAML front matter block: one `key: value` per line, where the
value is always a JSON scalar (directly `json.loads`-able). It contains no timestamp and no
renderer version, so rendering the same input is byte-identical. The keys are fixed:

```yaml
---
doc_format: "mapping-md/1"
schema_version: "1.0"
task_name: "..."
target_table: "..."
stmt_kind: "..."
---
```

`task_name` takes its value from the top-level `task_id` key of `lineage.json` — that contract key
actually carries a name-based statement identifier (batch/multi-statement inputs derive suffixes
such as `_1`), not the scheduler's numeric task_id, so the document labels it by what it really
means.

### Step lines

One line per transformation step in section 5, with this grammar (a Python regex, sharing its
source with `scope_lineage.render.mapping_markdown.STEP_LINE_PATTERN`):

```
^- 步骤 (?P<no>\d+)/(?P<total>\d+)：
  (?P<inputs>`[^`]*`(?:、`[^`]*`)*) → (?P<output>`[^`]*`)；
  (?P<step_type>[a-z_]+)(?:；粒度=(?P<grain>[a-z_]+))?；表达式：(?P<expression>.*)$
```

(It is really one line; the line breaks here are only for layout.)

- Every input/output field id sits in its own single-backtick code span, joined with `、`; extract
  field ids from a span with `FIELD_ID_SPAN_PATTERN` (`` `([^`]*)` ``).
- The content after the `表达式：` ("expression:") label is **taken greedily to end of line** and
  is wrapped in a code span (a longer backtick fence is used when the expression contains
  backticks, i.e. the standard markdown rule). So `；`, `→`, and `|` inside a SQL literal cannot
  break the grammar.
- Real newlines inside rendered values are always normalized to the literal `\n`, keeping "one
  fact per line".
- `粒度=changed` ("grain=changed") appears only when that step's aggregation changed the row grain.
- The expression prefers the contract's `display_expression` (FROM aliases already resolved to real
  table names), falling back to the verbatim `expression_sql` when it is unavailable.

### Evidence lines and relation lines

- Each field subsection ends with an evidence line:
  `- 证据：mapping_chain_id=<id>；chain=<chain_id>`.
- Section 3 answers "how are the **physical tables** related": join keys are pushed through to
  physical fields and then aggregated by (left table, right table), with key columns shown as short
  field names (the table names are already in the row's first two columns); when the same pattern
  repeats across several scopes it is merged into one row counting "N 处" ("N occurrences");
  CTE-to-CTE joins and joins whose key push-through yields nothing new **do not enter this
  section** (they are plumbing between intermediate results, and the details are in section 6);
  when an equality key between two physical tables cannot be split out, a `⚠ 未拆分` ("not split")
  row is kept. UNION merge relations are in the same section.
- Scope-level join details hang **under the corresponding scope name in section 6**, starting with
  `- <JOIN 类型> JOIN：\`左\` ⋈ \`右\`（@ <scope_id>；logic_block_id=<id>）`; left and right are the
  objects actually joined in the SQL (physical tables or CTE/subquery scopes), with no forced
  push-through — pushing through when two CTEs from the same origin are joined degenerates into a
  meaningless self-equality pair. When scope_profile folds a union branch away, its join details
  fall back to the parent union scope's subsection (the inline `@ <scope_id>` keeps the real
  attribution); when neither is present they land in a catch-all "其他连接" ("other joins")
  subsection, so no join fact is ever lost.
- The equality-key line prefers the short scope-level form (a column with the same name on both
  sides is abbreviated to a single column name; different names use `alias.column = alias.column`);
  physical push-through is appended as `（物理：表.字段 = 表.字段）` ("physical: …") only when it
  adds information (the physical fields differ on the two sides).
- The verbatim ON text is kept only when equality keys **could not be split out** (self-joins,
  `ON TRUE`, and the like, marked ⚠); when the split succeeds, keys plus extra conditions cover the
  ON completely and the original text can be looked up in `lineage.json`.
- Cells of the relation overview table **never hold arbitrary expressions**; a `|` inside a cell is
  escaped as `\|`.

### warnings.md (warnings-md/1)

**Advisory parse warnings do not go into mapping.md** — they describe the parsing process, do not
change proven facts, and mixed into the mapping document they would drown out what actually affects
the conclusions. A statement with warnings gets an extra `warnings.md` in the same directory:

- front matter: `doc_format: "warnings-md/1"`, `schema_version`, `task_id`, `target_table`;
- grouped by warning type, each group titled `## <type>（N 条）`, the first line of a group being a
  one-sentence Chinese gloss of that type (known types come from a built-in glossary; unknown types
  show only the type name), and each entry rendered as `- @ <scope>：` plus the verbatim message in
  a code span;
- when there are no warnings at all, the file is not generated.

Section 9 of mapping.md keeps a one-line count pointer (`- 解析警告：N 条（提示类信息，见同目录
warnings.md）`) and otherwise keeps only what affects lineage conclusions: incompletely traced
fields and `lineage_fact_gaps`.

### Uncertainty markers

The `⚠` prefix is used consistently, and a guess is never rendered as a fact:

- section 4, status column: `⚠ trace_incomplete`;
- section 5, chain level: `- ⚠ trace_status=<status>: <reason>`;
- section 3, self-joins and similar: the join-key column reads `⚠ 未拆分` ("not split"), and the
  condition in the details uses the neutral label "连接条件（未拆分）" ("join condition (not
  split)") — equality keys and filter conditions are not distinguished there, and it must not be
  read as "a non-equality extra condition";
- section 9: no diagnostics document, and the list of incompletely traced fields.

### Chunk self-containment

Each field gets one `###` subsection whose title carries the full identity:

- a normal write: `### 字段 <target table>.<field>`;
- a MERGE field with the same name in several branches:
  `### 字段 <target table>.<field>（merge:<branch> 分支 <index>）`;
- a directory write (`target_table` carrying the `directory:` prefix):
  `### 字段 <field>（写入目录 <path>）`, without inventing a pseudo table name.

After chunking on `###`, any single subsection still locates itself when retrieved alone.

## Determinism

Rendering the same pair of input documents twice is byte-identical: fields are sorted by
`target_column_ordinal` (falling back to `output_ordinal`), relations by `logic_block_id`, and graph
nodes by name. The property is locked by the golden baseline tests
(`tests/core/fixtures/lineage_contract/<case>/mapping.md`).
