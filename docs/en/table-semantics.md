English | [中文](../zh-CN/table-semantics.md)

# Table semantics (`table-semantics/1`): packet, validate, confirm

Table semantics answers, for one target table and in words a business reader uses: what
the table is, what one row is, how it is refreshed and how to read a day or a range, which
records it keeps, where its data comes from and who uses it, what each column means and
how it is computed, which code values a column holds, and what to watch out for.

The document is written by a model and held to the facts by machine. Core does the two
deterministic halves and never calls a model:

- `scope-lineage semantic packet` gathers every fact a writer needs about one table into a
  **material packet** — the table's metadata, each producing task with its SQL, the input
  tables, and the lineage facts the semantic profile already derives;
- `scope-lineage semantic validate` checks a written `table-semantics/1` document against
  its JSON Schema and against the packet (nine cross checks), and lists per item what to
  rewrite;
- `scope-lineage semantic confirm` writes a person's answers back into the documents.

Writing the document (the prompt, the rewrite loop) belongs to the agent skill. Rendering
the documents into pages (`semantic render`) is the next step and is not part of this
release.

A hand-written example document for a demo table lives in
[`examples/table-semantics/`](../../examples/table-semantics/), beside a confirmations file
for it; both are synthetic, like the demo corpus they describe.

## Where it sits

| Step | Who | Command | Output |
| --- | --- | --- | --- |
| 1. packet | machine | `semantic packet` | `<out>/<db.table>/packet.md` and `packet.json` |
| 2. write | model, through the agent skill | — | one `table-semantics/1` JSON per table |
| 3. validate | machine | `semantic validate` | a text summary, or a `--json` report whose failure list is the rewrite prompt |
| 4. render | machine | `semantic render` (next step) | one page per table |
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
  "packet_digest": "e21d636c4c7a990f",
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

## Relation to the ontology catalog and to `describe`

The two layers answer different questions. Table semantics is about one table, one
column, one piece of SQL; the [ontology catalog](ontology-catalog.md) is about business
concepts that span many tables. Table semantics is raw material for the catalog: its
`concept` key names the concept this table represents (`concept:<id>`) and the kind of
representation (the catalog's representation `kind`, such as `core`), so a table page and a
concept page can link to each other, and a cross-table problem the catalog finds (a column
that actually holds another identifier) comes back to the table's document as a `watch`.

The [task-semantic description](semantic-doc.md) (`describe`, the semantic card) is no
longer the deliverable for a reader: its builder is the source of the packet's lineage
facts, and the table-semantics document written from that packet is what a reader gets.
