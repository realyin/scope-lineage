English | [中文](../zh-CN/table-semantics.md)

# Table semantics (`table-semantics/1`): packet, validate, confirm, render

Table semantics answers, for one target table and in words a business reader uses: what
the table is, what one row is, how it is refreshed and how to read a day or a range, which
records it keeps, where its data comes from and who uses it, what each column means and
how it is computed, which code values a column holds, and what to watch out for.

The document is written by a model and held to the facts by machine. Core does the
deterministic work and never calls a model:

- `scope-lineage semantic packet` gathers every fact a writer needs about one table into a
  **material packet** — the table's metadata, each producing task with its SQL, the input
  tables, and the lineage facts the semantic profile already derives;
- `scope-lineage semantic validate` checks a written `table-semantics/1` document against
  its JSON Schema and against the packet (nine cross checks), and lists per item what to
  rewrite;
- `scope-lineage semantic confirm` writes a person's answers back into the documents;
- `scope-lineage semantic render` renders the documents as one page per table and an
  index, linked both ways with the ontology catalog's concept pages.

Writing the document (the prompt, the rewrite loop) belongs to the agent skill: the prompt
is `skills/scope-lineage/references/table-semantics-prompt.md`, and the skill's `SKILL.md`
gives the order of the steps.

A hand-written example document for a demo table lives in
[`examples/table-semantics/`](../../examples/table-semantics/), beside a confirmations file
for it; both are synthetic, like the demo corpus they describe.

## Where it sits

| Step | Who | Command | Output |
| --- | --- | --- | --- |
| 1. packet | machine | `semantic packet` | `<out>/<db.table>/packet.md` and `packet.json` |
| 2. write | model, through the agent skill | — | one `table-semantics/1` JSON per table |
| 3. validate | machine | `semantic validate` | a text summary, or a `--json` report whose failure list is the rewrite prompt |
| 4. render | machine | `semantic render` | one page per table, `<db.table>.md`, and `index.md` |
| 5. confirm | a person answers, the machine applies | `semantic confirm` | the documents with `confirmed` marks |

## Five minutes on the demo

Every input is synthetic and ships with the repository:

```bash
scope-lineage parse --input-dir examples/catalog-demo-corpus/tasks \
  --schema examples/catalog-demo-corpus/schema_info.json --out out/lineage
scope-lineage semantic packet --lineage out/lineage \
  --tasks examples/catalog-demo-corpus/tasks \
  --schema examples/catalog-demo-corpus/schema_info.json --out out/packets
scope-lineage semantic validate examples/table-semantics --packets out/packets
scope-lineage semantic confirm examples/table-semantics \
  --confirmations examples/table-semantics/confirmations.json --out out/confirmed
scope-lineage semantic validate out/confirmed --packets out/packets --json > out/validation.json
scope-lineage catalog build examples/catalog-demo --out out/catalog
scope-lineage semantic render out/confirmed --out out/pages/semantics \
  --validation out/validation.json --ontology out/catalog/ontology.json
scope-lineage catalog render out/catalog/ontology.json --out out/pages \
  --semantics out/pages/semantics
```

`validate` prints one line per document (`demo_dwd.dwd_party_customer_info_df: 52/52
checks passed (100.0%)`) and a total. The example's `packet_digest` pins the packet as the
installed SQLGlot renders it; with another SQLGlot version the digest check may report the
example as stale while every other check still passes.

## `semantic packet`

### Inputs

| Option | Required | What it is |
| --- | --- | --- |
| `--lineage` | yes | one `lineage.json`, or a tree of them — the same walk `describe` uses, with each document's `diagnostics.json` |
| `--tasks` | yes | the task JSON directory the lineage was parsed from; read with `parse`'s own task reader, for each task's SQL |
| `--schema` / `--schema-fallback` | no | schema metadata, the same options and loaders as `parse`; without them the columns and comments come from the lineage |
| `--tables` | no | a `tables.json` from `scope-lineage tables`; without it the table cards are built from `--lineage` first |
| `--only` | no | one or more target tables (`db.table`; a catalog prefix is ignored); an unknown name exits 1 |
| `--out` | yes | the output directory: one `<db.table>/` per target table |

A packet is written for every table a task finally writes (session views and temporary
tables are not target tables). A task whose JSON is missing from `--tasks` is packed
without SQL; the summary line counts them as `tasks_without_sql`.

With `--only` the corpus is not profiled as a whole. A document that writes or reads a
table names it, so only the lineage documents whose bytes contain a requested table's name
are parsed: with `--tables`, just the ones that write it; without, those plus the
producers of its input tables, from which the cards are built. The packet is the same as a
full run's; the summary line's task count says how many documents were read.

### What a packet holds

`packet.json` (`table-semantics-packet/1`) and `packet.md` hold the same facts; the
validator reads the JSON, a model reads the markdown.

| `packet.md` section | `packet.json` key | Content |
| --- | --- | --- |
| 1. 目标表 | `target` | table comment, layer, domain, where the metadata came from (`schema` / `lineage` / `fields`), every column in table order with type, comment and whether it is a partition column |
| 2. 生产任务 | `tasks[]` | per producing task: id, schedule, cycle, description, declared upstream and downstream tasks, the script's header comments, the statements that write this table, and the SQL |
| 3. 输入表 | `inputs[]` | per input table: comment, layer, roles in this table's statements, the tasks that produce it, every column with how it is used, and the time facts below |
| 4. 血缘事实 | `lineage` | `columns[]` (per target column: each producing statement's transform, physical source columns, expression and derivation steps), `rules[]` (filters, joins, dedups, unions and CASE branches, numbered `p1…`), `keys[]` (shape, grain basis, candidate keys, `key_confidence`, `proven`), `partition[]`, `upstream_tables`, `upstream_tasks`, `downstream[]` (consumer task, the tables it writes, whether lineage or task registration says so) |
| 5. 目标列顺序 | — | the column order the document must follow |

The lineage facts are the semantic profile's (`describe`'s builder), read with the table
cards so downstream consumers and joins another task proved unique are known. The profile
is an input here, not a deliverable.

Each input carries the facts check 9 needs: `partition_read` (`equality` for a single
partition, `range` otherwise, `none` when unfiltered) with the `partition_filters` behind
it, `date_filters` (non-partition filters on a date- or time-like column), and
`name_convention` (`full` for a `_df` / `_da` style name, `incremental` for `_di` / `_hi`,
`unknown` otherwise) — a naming convention, published so a reader sees what the check
assumed. `full_snapshot` is `equality` read of a `full` name.

Whether a filter reads partitions is decided per conjunct, because the lineage's own flag
is a name rule over a whole `WHERE` clause (`dt = x AND status = 0` marks neither half).
Each filter rule carries `partition_filter` and the `partition_basis` it rests on:

| `partition_basis` | When |
| --- | --- |
| `metadata` | every column of the filter has a partition fact in the schema metadata (`isPartition` on the column, or the DDL's `PARTITIONED BY`); a column flagged there is a partition column whatever its name |
| `partition_name` | the metadata marks the table partitioned (`is_partition`) without naming the column, and the filter compares a `dt` / `ds` / `pt` / `p_date` column with a constant or a `${...}` parameter |
| `lineage` | neither: the lineage's flag stands |

The same facts mark `partition` on the target's and the inputs' columns.

### Owners and emails

A packet is handed to a model, so it never carries a person: every owner key
(`owner`, `owner_email`, `target_table_owner`, …) is dropped wherever it appears, every
comment is masked the way `parse` masks comments by default (email, phone, ID number), the
SQL's comments are masked the same way, and a last pass masks any email address left
anywhere in the packet, SQL included.

### The digest

`packet_digest` is sixteen hex digits over every fact in the packet. The same inputs give
the same digest; any change to the metadata, the SQL or a lineage fact changes it. A
document copies the digest of the packet it was written from, and check 8 compares it with
the current packet.

## The `table-semantics/1` format

One JSON document per target table. The schema is shipped as
`scope_lineage/schemas/table-semantics.schema.json` and rejects unknown keys.

```json
{
  "doc_format": "table-semantics/1",
  "table": "demo_dwd.dwd_party_customer_info_df",
  "packet_digest": "d6ca0cf34298f8c1",
  "generator": {"prompt": "table-semantics-prompt@0", "model": "hand-written example"},
  "summary": {"what": "...", "row": {}, "refresh": {}, "scope": [], "upstream": [],
              "downstream": [], "good_for": [], "not_for": [], "watch": [], "questions": []},
  "columns": [],
  "steps": ["..."],
  "rules": [],
  "task": {"name": "dwd_party_customer_info_daily", "purpose": "...", "outputs": ["demo_dwd.dwd_party_customer_info_df"]},
  "concept": {"concept": "concept:customer", "representation_kind": "core"}
}
```

| Key | Content |
| --- | --- |
| `table` | `db.table`, no catalog prefix |
| `packet_digest` | copied from the packet |
| `generator` | the prompt (and optionally the model) that wrote it |
| `summary` | the one-page summary, all ten keys required (arrays may be empty) |
| `columns[]` | every target column, in table order |
| `steps[]` | the processing in one to seven sentences |
| `rules[]` | filters, joins, dedups, derivations and unions: business wording plus the SQL quoted as written |
| `task` or `tasks[]` | the producing task(s): `name`, `purpose`, `outputs`, optionally `cycle`, `upstream_tasks`, `downstream_tasks` — exactly one of the two keys |
| `concept` | optional link to the ontology catalog: `concept:<id>` and the table's representation kind |
| `confirmed[]` | written by `semantic confirm`: every applied confirmation (`target`, `by`, `date`) |

### Sources and confidence

Every item that states something carries `sources`, drawn from `comment`, `sql`,
`sql_comment`, `metadata`, `task`, `inferred` and `confirmed`; it may carry `confidence`
(`high` / `medium` / `low`) and a `watch` sentence for a conflict or a risk. The sourced
items are `summary.row`, `summary.refresh`, each `summary.scope[]` and `summary.upstream[]`,
each column, each code value and each rule.

### The one-page summary

| Key | Content |
| --- | --- |
| `what` | one sentence: what the table is |
| `row` | what one row is: `text`, `grain_columns`, `grain_source` (`declared` / `inferred` / `proven`), `unique` (`yes` / `no` / `unknown`), `note` for the risk when it is not unique |
| `refresh` | `cycle`, `time` (`snapshot` / `incremental` / `zipper` / `unknown`) and `how_to_read`: how to take one day and how to take a range |
| `scope[]` | which records the table keeps, in business words, citing rules through `rule_refs` |
| `upstream[]` | each input table's `role` (`main` / `enrich` / `filter` / `dedup` / `union_branch` / `lookup` / `other`) and what it `provides` |
| `downstream[]` | consuming `task` and optionally the `table` it writes |
| `good_for[]` / `not_for[]` | typical uses and their limits |
| `watch[]` | conflicts, risks, deprecations and coverage gaps, each with a `kind` and optional `refs` such as `column:x` or `rule:r2` |
| `questions[]` | at most five open questions for the owner: `id` (`q1`…), `text`, `about`, `status` (`open` / `answered`), and once answered `answer`, `answered_by`, `answered_on` |

### Columns and rules

A column holds `column`, `meaning` (the business name), `category` (`identifier`,
`foreign_identifier`, `descriptive`, `state`, `measure`, `time`, `technical`),
`derivation` (in business words; `branches[]` when branches differ), `source_columns`
(`db.table.column` references the derivation reads), `code_values[]` (`value`, `meaning`,
`sources`, and `unconfirmed: true` for a guess), optionally `unit`, `null_meaning` and
`watch`, plus `sources` and `confidence`.

A rule holds `id` (`r1`…), `kind` (`filter`, `join`, `dedup`, `derive`, `union`, `other`),
`text`, `sql` (the SQL fragment as written in the script) and `sources`.

### What the schema leaves to the checks

The schema checks shape only. Two counts a model often gets wrong are deliberately left to
check 7 so they land in the rewrite list instead of failing the whole document: an empty
`sources`, and more than five questions.

## `semantic validate`

```bash
scope-lineage semantic validate <documents> --packets <packet dir> [--json]
```

Every `*.json` under `<documents>` is read; the toolchain's own other documents
(`semantic-confirmations/1`, packets, reports) are skipped, anything else is checked. A
document that fails the schema is reported with its errors and not cross-checked. A valid
document is checked against `<packet dir>/<table>/packet.json`:

| # | Check | Fails when | Warns when |
| --- | --- | --- | --- |
| 1 | `coverage` | a target column is missing, a column is extra or repeated, or the order differs from the table's | — |
| 2 | `source_columns` | a source column is neither in that column's lineage nor in any input table | it is only in an input table's metadata, not in the column's lineage |
| 3 | `code_values` | a code value not marked `unconfirmed` appears neither in the related comments nor in the SQL | — |
| 4 | `grain` | a grain column is not a target column, or `grain_source: proven` has no proven key in the packet | the claimed grain columns differ from the proven key |
| 5 | `rules` | a non-partition filter is not cited by any `rules[].sql`, a quoted `sql` is not found in the task SQL (normalized), or a `rule_refs` entry names no rule | the packet has no SQL to check a quote against |
| 6 | `neighbours` | an upstream table is not a lineage input, or a downstream task (or the table it is said to write) is not known | the downstream task is known but the tables it writes are not |
| 7 | `sources` | a sourced item has an empty `sources`, or there are more than five questions | — |
| 8 | `digest` | `packet_digest` differs from the packet's (stale), or there is no packet for the table | — |
| 9 | `time` | `refresh.time` is `incremental` while every input is a full snapshot read by one partition and no filter touches a business date | `refresh.time` is `snapshot` while the write filters on a business date |

Check 9 exists because a daily full snapshot described as incremental leads a reader to
add partitions together and count every row once per day.

The normalization for check 5 lower-cases, drops identifier quotes, table qualifiers,
whitespace and a leading `WHERE` / `AND` / `ON`, so the lineage's `` `latest`.`rn` = 1 ``,
a quoted `WHERE rn = 1` and the script's `latest.rn=1` compare equal.

The lineage renders every predicate through SQLGlot, while `rules[].sql` quotes the script
as written, so check 5 compares both in one space. A fragment counts in two forms: its
loose text, and — when SQLGlot parses it in the lineage's dialect — the text SQLGlot renders
for it. The task SQL counts as its loose text, its rendered text, and one unit per `WHERE`,
`HAVING` and `ON` predicate and per conjunct of each, rendered as written and with every
column a subquery or CTE computes replaced by the expression behind it. A quote is found
when any of its forms occurs in the script or equals a unit; a filter is cited when one of
its forms meets a form of a quote or of a unit the quote equals. So the script's
`nvl(x, 0) = 1`, `substr(n, 1, 2) = 'AB'` and `x is not null` cite the lineage's
`COALESCE(x, 0) = 1`, `SUBSTRING(n, 1, 2) = 'AB'` and `NOT x IS NULL`, and a quoted
`a.dt = '${bizdate}'` cites `DATE_FORMAT(time_inst, 'yyyyMMdd') = '${bizdate}'` when the
subquery `a` computes `dt` that way. A fragment or script SQLGlot cannot parse keeps the
loose text match.

### Report

A table's pass rate is the share of checked items that did not fail; a warning is listed
but does not count against it. The text summary prints each table's line and then its
failures, one per line, in the form a rewrite prompt can take as it stands:

```text
demo_dwd.dwd_party_customer_info_df: 46/51 checks passed (90.2%), 5 fail, 1 warn
  FAIL [1 coverage] columns: 缺少目标表的列 verified_customer_no（表内第 2 列）；补上这一列
  WARN [2 source_columns] columns[0].source_columns[1]: ...
  FAIL [9 time] summary.refresh.time: 写了 incremental，但上游 demo_ods.ods_core_customer_df 都按单一分区取全量快照，...
Validated 1 document(s): 0 clean, 1 with failures, 0 with warnings only, 0 with schema errors
```

`--json` prints the same as a `table-semantics-validation/1` document:

```json
{
  "doc_format": "table-semantics-validation/1",
  "tables": [
    {
      "table": "demo_dwd.dwd_party_customer_info_df",
      "file": "demo_dwd.dwd_party_customer_info_df.json",
      "schema_errors": [],
      "counts": {"pass": 45, "warn": 1, "fail": 5},
      "pass_rate": 0.902,
      "checks": {"coverage": {"pass": 5, "warn": 0, "fail": 1}},
      "failures": [
        {"check": "coverage", "status": "fail", "at": "columns", "message": "..."}
      ]
    }
  ],
  "summary": {"documents": 1, "clean": 0, "tables_with_failures": 1,
              "tables_with_warnings_only": 0, "tables_with_schema_errors": 0, "pass_rate": 0.902}
}
```

### Exit codes

| Code | When |
| --- | --- |
| 0 | every document is schema-valid (cross-check failures are reported, not fatal) |
| 1 | at least one document has a schema error, or the directory holds no JSON |
| 2 | the documents directory or `--packets` does not exist |

## `semantic confirm`

```bash
scope-lineage semantic confirm <documents> --confirmations <file> [--out <dir>]
```

The confirmations file is a `semantic-confirmations/1` document (schema:
`scope_lineage/schemas/semantic-confirmations.schema.json`). Each entry names one table,
one target, the answer (`value`), who gave it (`by`) and when (`date`, `YYYY-MM-DD`):

```json
{
  "doc_format": "semantic-confirmations/1",
  "confirmations": [
    {
      "table": "demo_dwd.dwd_party_customer_info_df",
      "target": "question:q1",
      "value": "不会。注册系统只允许 F、M、U 三个值。",
      "by": "demo-reviewer",
      "date": "2026-09-26"
    }
  ]
}
```

| Target | `value` | Effect |
| --- | --- | --- |
| `question:<id>` | the answer text | `status: answered`, `answer`, `answered_by`, `answered_on` |
| `column:<c>.meaning` | the meaning text | replaces `meaning`; the column's `sources` gains `confirmed` |
| `column:<c>.code_values` | a list of `{value, meaning}`, or one such object | a list replaces the code values, one object is merged into them; each confirmed value gains `confirmed` and `unconfirmed: false` |
| `summary.row` | an object of row fields, or the row text | merged into `summary.row`; its `sources` gains `confirmed` |

Every applied confirmation is logged under `confirmed[]`, and applying the same file twice
changes nothing the second time. A confirmation whose table, question or column does not
exist, whose value has the wrong shape, or whose value would make the document fail the
schema is **not applied and not dropped**: the summary line counts it as `unmatched` and
names it with the reason. Without `--out` the changed documents are rewritten in place;
with `--out` every document is written there and the originals are left alone. A malformed
confirmations file exits 2.

## `semantic render`

```bash
scope-lineage semantic render <documents> --out <dir> \
  [--validation <report.json>] [--ontology <ontology.json>]
```

Renders every legal `table-semantics/1` document under `<documents>` as one page,
`<dir>/<db.table>.md`, and writes `<dir>/index.md`. The toolchain's other documents
(confirmations, packets, reports) are passed over; a document that does not fit the schema
is reported on stderr and not rendered, and the exit code is 1.

| Option | Required | Meaning |
| --- | --- | --- |
| `<documents>` | yes | The directory of `table-semantics/1` documents |
| `--out` | yes | The output directory |
| `--validation` | no | A `table-semantics-validation/1` report written by `semantic validate --json`: the page marks the failed items and ends with a 校验 section, the index shows the pass rate |
| `--ontology` | no | An `ontology.json` written by `catalog build`: each table's domain and concept come from the catalog, the concept linked to `../concepts/<slug>.md` |

### The table page

The page follows the order of a hand-made sample page:

| Part | Content |
| --- | --- |
| Title line | The table name; under it the domain (with `--ontology` the domain of the table's concept, else the database name), 「本表是 <concept> 的 <representation kind>表」, and how many items on the page are confirmed; with a report, the pass rate too |
| 一页纸 | What the table is, what a row is (grain columns, where the grain comes from, whether it is unique), refresh and how to read, which records it keeps (citing its rules), where the data comes from (each upstream table and its role), who uses it, good for / not for, what to watch (each with its kind), open questions (an answered one with its answer, who answered and when) |
| 字段 | Five groups: identifiers (标识与关联), states and codes (状态与码值 — every column with code values is here, with an extra 码值 column), amounts (金额 — the unit after the meaning) and time (时间), each a 字段 / 含义 / 口径 / 来源 table; descriptive and technical columns (描述与技术列) as one line. A 口径 spells out each branch (`线上：…；线下：…`), then the general wording, then when the column is empty |
| 加工过程 | The producing task (its cycle and purpose), then the steps |
| 规则（原文） | Each rule's id and kind, its business wording and its SQL |
| 来源说明 | What the source words and the marks mean; the prompt the page was written with and the packet digest it was written against |
| 校验 | Only with `--validation`: the pass rate, and each failed item and warning with its check, its place and how to fix it |

The marks on a page:

| Mark | Meaning |
| --- | --- |
| ✓ | The item's `sources` include `confirmed` (written by `semantic confirm`), or the question was answered; shown beside what it confirms (a column's meaning, a code value, a rule, …) |
| ⚠ | The item carries a `watch`, whose text follows; a column or rule named only by the summary's watch list (`column:<name>`, `rule:<id>`) shows 「⚠（见要注意）」 |
| ✗n | The report's n-th failed item falls on this item (numbered in report order); a failure about the whole table (a missing column, an uncited filter, a stale digest) is listed in the 校验 section only |
| `值（含义待确认）` | A code value marked `unconfirmed: true` (or whose meaning starts with 待确认) |
| （中置信）（低置信） | The item's `confidence` is not `high` |

### The index

`index.md` lists every table by domain, then by concept: the table (linked to its page),
what it is (`summary.what`), the validation pass rate (— without a report, 未校验 when the
report does not cover the table) and the number of open questions (still `open`); the
by-concept tables add the representation kind. With `--ontology` the domain is that of the
concept the table represents and each concept heading links to its concept page; without
it the database name stands in for the domain and the concept is the document's own
`concept`, shown as its id without a link. Tables that represent no concept are listed last
under 未关联概念. No company's table-name convention is used for grouping.

### Links to and from the concept pages

The catalog decides which concept a table belongs to: a table the catalog lists as a
representation takes the catalog's concept and representation kind; only a table the
catalog does not list falls back to the document's own `concept`. A table page links to
`../concepts/<slug>.md`, the concept page `catalog render` writes, so `--out` belongs in a
subdirectory of the `catalog render` output, such as `<pages>/semantics`. The other
direction is `catalog render --semantics <pages>/semantics`; see the
[ontology catalog](ontology-catalog.md). Both flags are optional; without them both
outputs are byte-for-byte what they were before this feature.

### Exit codes

| Code | When |
| --- | --- |
| 0 | Every document was rendered |
| 1 | A document does not fit the schema (the rest are still rendered), no document could be rendered, or `--validation` / `--ontology` declares the wrong `doc_format` |
| 2 | The document directory, `--validation` or `--ontology` does not exist or cannot be read |

## Relation to the ontology catalog and to `describe`

The two layers answer different questions. Table semantics is about one table, one
column, one piece of SQL; the [ontology catalog](ontology-catalog.md) is about business
concepts that span many tables. Table semantics is raw material for the catalog: its
`concept` key names the concept this table represents (`concept:<id>`) and the kind of
representation (the catalog's representation `kind`, such as `core`), so a table page and a
concept page can link to each other (`semantic render --ontology` and
`catalog render --semantics`), and a cross-table problem the catalog finds (a column
that actually holds another identifier) comes back to the table's document as a `watch`.

The [task-semantic description](semantic-doc.md) (`describe`, the semantic card) is no
longer the deliverable for a reader: its builder is the source of the packet's lineage
facts, and the table-semantics document written from that packet is what a reader gets.
