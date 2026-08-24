[中文](../zh-CN/getting-started.md) | English

# Scope Lineage Installation and Usage Guide

Scope Lineage is an offline static analyzer for Spark/Hive SQL. It reads SQL plus optional
metadata and outputs:

- `lineage.json`: tables, scopes, expressions, field mapping chains, and end-to-end field lineage;
- `diagnostics.json`: parse warnings, statistics, and fact gaps that could not be proven.

It needs no Spark cluster, no database connection, and no LLM. The runtime requires Python
3.9–3.12.

## 1. Installation

### Option 1: install the CLI with pipx (recommended)

If `pipx` is already installed:

```bash
pipx install scope-lineage
scope-lineage --help
```

`pipx` creates an isolated environment for the command-line tool, avoiding dependency
conflicts with your other Python projects. To upgrade later:

```bash
pipx upgrade scope-lineage
```

### Option 2: pip inside a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install scope-lineage
scope-lineage --help
```

On Windows PowerShell, activate the virtual environment with:

```powershell
.venv\Scripts\Activate.ps1
```

## 2. Your first parse

Create `demo.sql`:

```sql
INSERT OVERWRITE TABLE mart.order_summary
SELECT
  customer_id,
  COUNT(*) AS order_count,
  SUM(amount) AS total_amount
FROM ods.orders
WHERE status = 'PAID'
GROUP BY customer_id;
```

Run:

```bash
scope-lineage parse \
  --sql-file demo.sql \
  --out ./scope-lineage-output
```

The output directory uses the SQL file name as the default task name:

```text
scope-lineage-output/
└── demo/
    ├── lineage.json
    └── diagnostics.json
```

You can pretty-print the results directly:

```bash
python -m json.tool scope-lineage-output/demo/lineage.json
python -m json.tool scope-lineage-output/demo/diagnostics.json
```

## 3. Choosing an input mode

The `parse` command requires exactly one of these three input modes:

| Scenario | Flag | Example |
| --- | --- | --- |
| One plain SQL file | `--sql-file` | `scope-lineage parse --sql-file task.sql --out ./output` |
| One task JSON exported by a scheduler | `--task-file` | `scope-lineage parse --task-file task.json --out ./output` |
| Recursive batch parse of a JSON directory | `--input-dir` | `scope-lineage parse --input-dir tasks --out ./output` |

The SQL file name is the default task name; you can override it explicitly:

```bash
scope-lineage parse \
  --sql-file task.sql \
  --task-name customer_profile_daily \
  --out ./output
```

`--task-name` applies only to a single SQL file or task JSON; directory batch mode uses the
name carried by each task record. When one file contains several write statements it is still
**one task, one directory**: each statement is recorded as a `statement_lineage` entry
(`stmt:001`, `stmt:002`, …) inside the same lineage.json.

For task JSON, put the SQL and the task information under `meta`:

```json
{
  "meta": {
    "task_id": "demo-1002",
    "task_name": "customer_profile_daily",
    "sql": "INSERT OVERWRITE TABLE mart.customer_profile SELECT customer_id FROM ods.customer_base",
    "upstream_tasks": [
      {"task_id": "demo-1001", "task_name": "customer_base_daily"}
    ],
    "downstream_tasks": []
  },
  "data_source": "scheduler_export"
}
```

Task dependencies are written to `lineage.json.task_dependencies`. For the full field
conventions see [Core input formats](input-formats.md).

## 4. Add metadata to improve field-lineage completeness

Explicit fields parse without any metadata. Supply Schema and target-table metadata when you hit
`SELECT *`, positional target-field binding, or a need for types and comments. These are two
inputs with different jobs:

| Input | Recommended format | Problem it solves |
| --- | --- | --- |
| `--schema` | JSON file/directory with `schema[]` and optional `ddl`; CSV only as a fallback | Provides source-table fields, expands `SELECT *` in authoritative order, and fills in types and comments. |
| `--target-ddl-metadata` | JSON with `schema[]` and `ddl` | Binds the INSERT projection against the authoritative target-table structure, identifying field positions and partitions. |

### Source-table Schema: JSON first

Create `ods.orders_metadata.json`. Providing both `schema[].columnIndex` and the DDL is
recommended:

```json
{
  "table_name": "ods.orders",
  "full_table_name": "spark_catalog.ods.orders",
  "schema": [
    {
      "columnName": "customer_id",
      "columnType": "bigint",
      "columnComment": "Synthetic customer identifier",
      "columnIndex": 0,
      "isPartition": 0
    },
    {
      "columnName": "amount",
      "columnType": "decimal(18,2)",
      "columnComment": "Synthetic order amount",
      "columnIndex": 1,
      "isPartition": 0
    },
    {
      "columnName": "status",
      "columnType": "string",
      "columnComment": "Synthetic order status",
      "columnIndex": 2,
      "isPartition": 0
    }
  ],
  "ddl": "CREATE TABLE spark_catalog.ods.orders (customer_id BIGINT, amount DECIMAL(18,2), status STRING) USING iceberg",
  "query_time": "2026-08-14 10:00:00",
  "data_source": "catalog_api"
}
```

Pass it when parsing:

```bash
scope-lineage parse \
  --sql-file demo.sql \
  --schema ods.orders_metadata.json \
  --out ./scope-lineage-output
```

`--schema` also accepts a directory holding one such JSON per source table. The effective
precedence for source-field order is:

1. when `ddl` parses successfully, the DDL field order wins;
2. without a DDL, sort by `schema[].columnIndex`, which must start at 0 and be contiguous;
3. for the compatible lightweight JSON without `columnIndex`, the `columns[]` array order;
4. CSV is processed last, by file row order.

CSV is the compatibility fallback format. Row order within one table is taken as the field order:

```csv
table_name,column_name,column_type,column_comment
ods.orders,customer_id,bigint,Synthetic customer identifier
ods.orders,amount,"decimal(18,2)",Synthetic order amount
ods.orders,status,string,Synthetic order status
```

CSV carries no explicit `columnIndex` and no DDL to cross-check against. If your exporter cannot
guarantee row order, do not rely on CSV to expand `SELECT *`.

### Check coverage before parsing: `--metadata-preflight`

Missing table metadata never fails a parse, but it quietly degrades conclusions: a table
with unknown schema cannot be excluded from an unqualified column's candidate set, so
fields may come out `AMBIGUOUS` — looking like a SQL problem when it is a metadata gap.
Run a coverage check before the real parse:

```bash
scope-lineage parse --input-dir tasks --out ./output \
  --schema schema.json --metadata-preflight
```

Preflight mode runs the same parsing pipeline but writes **no lineage artifacts**: it
prints every table missing from the schema with the tasks referencing it (sorted by
referencing-task count), writes a machine-readable `metadata_gaps.json` into `--out`,
and **returns non-zero when gaps exist**. Chaining the two commands is the
review-before-parse gate:

```bash
scope-lineage parse --input-dir tasks --out ./output --schema schema.json \
  --metadata-preflight && \
scope-lineage parse --input-dir tasks --out ./output --schema schema.json
```

Gaps → the first step exits non-zero and the second never runs; supplement the metadata
and retry. No gaps → the real parse proceeds automatically. A normal batch parse that
finds gaps also writes the same `metadata_gaps.json` next to its artifacts and prints a
one-line pointer, but does not stop — the preflight is where the gate belongs.

### Target-table DDL/Schema: authoritative JSON

`--target-ddl-metadata` accepts a JSON file or a directory that supplies the target table's
authoritative field names, order, types, and partitioning. Create
`mart.order_summary_metadata.json`:

```json
{
  "table_name": "mart.order_summary",
  "full_table_name": "spark_catalog.mart.order_summary",
  "schema": [
    {
      "columnName": "customer_id",
      "columnType": "bigint",
      "columnComment": "Synthetic customer identifier",
      "columnIndex": 0,
      "isPartition": 0
    },
    {
      "columnName": "order_count",
      "columnType": "bigint",
      "columnComment": "Order count",
      "columnIndex": 1,
      "isPartition": 0
    },
    {
      "columnName": "total_amount",
      "columnType": "decimal(18,2)",
      "columnComment": "Total order amount",
      "columnIndex": 2,
      "isPartition": 0
    }
  ],
  "ddl": "CREATE TABLE spark_catalog.mart.order_summary (customer_id BIGINT, order_count BIGINT, total_amount DECIMAL(18,2)) USING iceberg",
  "query_time": "2026-08-14 10:00:00",
  "data_source": "catalog_api"
}
```

Pass source-table and target-table metadata together:

```bash
scope-lineage parse \
  --sql-file demo.sql \
  --schema ods.orders_metadata.json \
  --target-ddl-metadata mart.order_summary_metadata.json \
  --out ./scope-lineage-output
```

The effective precedence for the target structure is:

1. when `ddl` parses successfully, its field order and partition definitions win;
2. `schema[]` is cross-checked against the DDL by field name and supplies types, comments, and `columnIndex`;
3. without a DDL, sort by `schema[].columnIndex`, which must start at 0 and be contiguous;
4. CSV cannot be used as `--target-ddl-metadata`; it is only a fallback format for the source-table `--schema`.

If one rich-JSON directory contains every source and target table, pass that same directory to
both `--schema` and `--target-ddl-metadata`; the former supplies source-field expansion, the
latter performs positional binding only for the target table of this write.

For the target metadata's JSON structure and version-selection rules, see
[Target-table DDL/Schema metadata](input-formats.md#target-table-ddlschema-metadata).

After cloning the source repository you can also run the complete example directly:

```bash
scope-lineage parse \
  --task-file examples/tasks/customer/customer_profile_daily.json \
  --schema examples/metadata/schema_info.json \
  --target-ddl-metadata examples/metadata/target_tables \
  --out /tmp/scope-lineage
```

## 5. How to read the results

Always read both files together:

| The question you want answered | Primary fields |
| --- | --- |
| Which table is written, which physical tables are read? | `target_table`, `source_tables` |
| How are CTEs, subqueries, and UNIONs connected? | `scope_graph`, `scopes` |
| Where do JOINs, filters, aggregates, and windows happen? | `scopes.*.logic_blocks` |
| Which scopes and expressions does a field pass through? | `field_mapping_chains` |
| Where does each target field ultimately come from? | `end_to_end_lineage` |
| Is the result complete, and where is it still ambiguous? | `trace_complete`, `missing_reasons`, `ambiguities` |
| Why can a fact not be determined? | `diagnostics.json.lineage_fact_gaps` |

The most basic consumption rules are:

1. confirm `lineage.json.parse_status` is not `failed`;
2. check `diagnostics.json.warnings` and `lineage_fact_gaps`;
3. for field-level conclusions, check `trace_complete`, `missing_reasons`, and `ambiguities`;
4. never treat recovered syntax, candidate sources, or metadata gaps as proven facts.

For the full field reference see the [`lineage.json` output contract](lineage-json.md) and the
[`diagnostics.json` output contract](diagnostics-json.md).

## 6. Batch tasks and failure policy

Parse a directory in batch:

```bash
scope-lineage parse \
  --input-dir exported-tasks \
  --schema table-metadata \
  --target-ddl-metadata table-metadata \
  --out ./output
```

By default the command returns a non-zero exit code as soon as one input fails to load or one
statement has `parse_status=failed`; the other successful results are still written to disk. Use
this only when the caller explicitly accepts partial results:

```bash
scope-lineage parse \
  --input-dir exported-tasks \
  --out ./output \
  --allow-partial
```

`--allow-partial` only changes the exit code. It does not turn failures into successes and it
hides no diagnostics.

Task-level DELETE/TRUNCATE/UPDATE and multi-statement final state are always produced — since
0.2.0 the task document (contract 2.0) is the only artifact. `--contract-version` still accepts
`2.0` for one release so that an explicit `1.0` request fails with a clear message instead of an
unknown-argument error. Add a quality gate when a pipeline should reject uncertain results:

~~~bash
scope-lineage parse \
  --input-dir exported-tasks \
  --quality-policy strict \
  --out ./output
~~~

For the full semantics see [Task Lineage 2.0](task-lineage-v2.md).

## 7. Catalog prefixes

Three-part table names are preserved in full by default. Configure removal explicitly only when
you have confirmed the leading segment is a removable catalog:

```bash
scope-lineage parse \
  --sql-file task.sql \
  --catalog-prefixes warehouse_catalog,spark_catalog \
  --out ./output
```

A fixed runtime environment can instead set:

```bash
export SCOPE_LINEAGE_CATALOG_PREFIXES="warehouse_catalog,spark_catalog"
```

The command-line setting wins over the environment variable. Do not misconfigure database names
such as `ods` or `dwd` as catalogs.


### When your cluster's overwrite mode differs from the Spark default

How much data `INSERT OVERWRITE TABLE t PARTITION(dt)` (a partition spec with no value) deletes
depends on `spark.sql.sources.partitionOverwriteMode`: `static` (Spark's own default) deletes the
whole table, `dynamic` deletes only the partitions actually written this run. Scripts usually do
not set it, and this tool infers Spark's default.

**If your cluster is configured as `dynamic`** (the Environment page of the Spark Web UI confirms
it), pass `--partition-overwrite-mode dynamic`, otherwise every overwrite that gives no partition
value — the everyday way partitioned tables are written — has its effect judged in the opposite
direction. A `SET` in the script always wins over this flag.

## 8. Python API

```python
from scope_lineage import parse_task_lineage, write_task_lineage

sql = "INSERT INTO mart.user_ids SELECT id FROM ods.users"

task = parse_task_lineage(sql, task_name="user_ids", schema={"ods.users": ["id"]})
write_task_lineage(task, "./scope-lineage-output/user_ids")

# One statement document (the shape embedded in each statement_lineage entry):
from scope_lineage import parse_scope_lineage, to_lineage_dict

statement = parse_scope_lineage(sql, task_name="user_ids", schema={"ods.users": ["id"]})
document = to_lineage_dict(statement)
print(document["target_table"])
```

`write_task_lineage()` validates and writes both contract files; `to_lineage_dict()` produces the
statement-document dict, suitable for in-memory consumption. Downstream code should call through
the `scope_lineage` public facade rather than depending on internal module paths.

## 9. FAQ

### `scope-lineage` not found after installation

- If you installed into a virtual environment, confirm the environment is activated;
- with `pipx`, run `pipx ensurepath` and then reopen the terminal;
- run `python -m pip show scope-lineage` to confirm it landed in the current Python environment.

### `SELECT *` was not fully expanded

Provide `--schema` for the relevant source tables. Without a Schema the tool will not guess which
fields the star stands for; it records the gap in the diagnostics instead.

### A plain `SELECT` produced no artifacts

Scope Lineage targets offline write tasks. The input needs a supported `INSERT`, CTAS, or `MERGE`
write statement; a standalone query is not treated as a publishing task and produces no lineage
artifacts.

### How do I see every flag?

```bash
scope-lineage parse --help
```

## Next steps

- [Documentation map and question-to-field index](README.md)
- [Complete input formats](input-formats.md)
- [`lineage.json` output contract](lineage-json.md)
- [`diagnostics.json` output contract](diagnostics-json.md)
- [Example walkthrough](../../examples/README.md)
