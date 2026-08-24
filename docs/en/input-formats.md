[中文](../zh-CN/input-formats.md) | English

# Core Input Formats

Scope Lineage Core accepts SQL content plus two kinds of optional metadata. It does not connect
to a scheduler or a metadata platform; the caller exports the files, and Core normalizes them and
parses them into versioned facts.

## How inputs change the value of the output

| Input | Required | Output it mainly affects | Result if omitted |
| --- | --- | --- | --- |
| SQL text | Yes | Every scope, logic block, table, and field lineage | Nothing can be parsed. |
| Task JSON wrapper | No | `task_id`, `task_dependencies`, batch output paths | SQL still parses, but there are no scheduler task dependencies. |
| Source-table Schema | No | `SELECT *` expansion, field binding, types/comments, `related_metadata` | Explicit columns still parse; stars may degrade and raise a warning. |
| Target-table DDL/Schema | No | `target_field_binding`, final target field names and positions | The INSERT column list or the SQL projection names are used, with no claim of authoritative positional correction. |
| Catalog-prefix configuration | No | Table identity in `target_table`, `source_tables`, and physical field sources | The fully qualified catalog table name from the SQL is preserved. |

The more complete the input, the more field facts Core can prove; but metadata never overrides SQL
facts. A Schema can state which columns a table has — it cannot stand in for the JOINs, filters,
and expressions the SQL actually uses.

Several sources can be combined in authority order:

~~~bash
scope-lineage parse \
  --input-dir exported_tasks \
  --schema rich-table-metadata \
  --schema-fallback schema_info.csv \
  --out /tmp/lineage
~~~

`--schema-fallback` is repeatable. It only fills in tables missing from the authoritative
`--schema`; when the same table has conflicting field definitions it does not silently merge them
or override the DDL order — v2 records this under
`diagnostics.json.metadata_coverage.metadata_conflicts`.

## SQL input

### One SQL file

```bash
scope-lineage parse --sql-file task.sql --out /tmp/lineage
```

The file may contain one statement or many. Only supported write statements produce artifacts,
and several write statements share one task directory: each write statement is recorded as a
`stmt:NNN` entry of `statement_lineage` inside one lineage.json.

### One task JSON

Use the current scheduler export structure:

```json
{
  "meta": {
    "task_id": "task-1002",
    "task_name": "customer_profile_daily",
    "task_type": "Spark SQL",
    "input_tables": ["ods.customer_base"],
    "output_tables": ["mart.customer_profile_snapshot"],
    "upstream_tasks": [
      {"task_id": "task-1001", "task_name": "customer_base_daily"}
    ],
    "downstream_tasks": [],
    "sql": "INSERT OVERWRITE TABLE ..."
  },
  "query_time": "2026-08-02 10:00:00",
  "data_source": "scheduler_api"
}
```

Core currently consumes:

- `meta.task_name`, falling back to `meta.task_id` and then the file name;
- `meta.sql`, which must be a non-empty string;
- `meta.upstream_tasks` and `meta.downstream_tasks`, written to `lineage.json.task_dependencies`.

The chosen task name is also one output-directory component. It may contain spaces and Unicode,
but absolute names, `.`, `..`, NUL, `/`, and `\` are rejected instead of being interpreted as
paths. For dependency evidence, `source_file` is the input basename in single-file mode and the
POSIX-style path relative to `--input-dir` in directory mode; it never records the caller's
absolute local path.

Dependency objects are normalized into these values where possible:

| Input key | Output location | Meaning |
| --- | --- | --- |
| `task_id` | `dependency.task_id` | Scheduler task ID. |
| `task_name` | `dependency.task_name` | Task display name. |
| `project_name` | `dependency.project_name` | Optional project name. |
| `task_group` | `dependency.task_group` | Optional task group. |
| Table-name field | `dependency.dependency_table` | The table the dependency relates to; the input adapter recognizes the field name. |
| The whole input object | `dependency.raw_record` | The original record, kept for traceability; not a substitute for the normalized fields. |

Other platform fields may stay in the input but are currently not copied into Core's output. The
legacy top-level `{"task_name": "...", "sql": "..."}` format is still supported, but without
`meta` it produces no declared task dependencies.

### Task directory

```bash
scope-lineage parse --input-dir exported_tasks --out /tmp/lineage
```

If the export directory intentionally contains other JSON documents, filter explicitly instead
of letting malformed inputs fail the batch or silently guessing their shape:

```bash
scope-lineage parse \
  --input-dir exported_tasks \
  --include-glob '*_info.json' \
  --exclude-glob '*_archived_info.json' \
  --out /tmp/lineage
```

Both glob flags are repeatable and apply only to `--input-dir`. Without them, every recursively
discovered `*.json` remains an input, preserving the fail-visible default.

Core reads `*.json` recursively and preserves each source file's relative parent directory. Two
inputs that use the same task name inside the same relative directory are treated as an output
conflict rather than silently overwritten.

## Catalog-prefix configuration

Spark/Hive environments may use three-part table names, `catalog.database.table`. Core preserves
the full name by default, because the three-part shape alone is not enough to decide safely
whether the first segment is a catalog or part of a business naming convention.

If you have confirmed that these two spellings mean the same physical table:

```text
warehouse_catalog.ods.customer_base
ods.customer_base
```

you can declare which leading catalog may be stripped for this run:

```bash
scope-lineage parse \
  --input-dir exported_tasks \
  --catalog-prefixes warehouse_catalog,spark_catalog \
  --out /tmp/lineage
```

A fixed deployment environment or a Python API call can use the environment variable instead:

```bash
export SCOPE_LINEAGE_CATALOG_PREFIXES="warehouse_catalog,spark_catalog"
```

Precedence and behavior:

| Configuration | Behavior |
| --- | --- |
| `--catalog-prefixes` passed | Use the comma-separated command-line list, overriding the environment variable. |
| No command-line flag, environment variable set | Use `SCOPE_LINEAGE_CATALOG_PREFIXES`. |
| Neither set | Strip no catalog; keep the full table name from the SQL. |
| Explicitly passed an empty string | Use an empty list, i.e. strip no catalog for this run. |

For example, after configuring `warehouse_catalog`, table identity in `lineage.json` is unified as:

```json
{
  "source_tables": ["ods.customer_base"],
  "end_to_end_lineage": [
    {
      "physical_sources": [
        {"table": "ods.customer_base", "column": "customer_id"}
      ]
    }
  ]
}
```

Note:

- configure only leading names you have confirmed to be catalogs; do not configure database names such as `ods` or `dwd`;
- one batch of output must use one policy, or the same physical table can end up with two identities;
- this is a deployment/batch-level parsing policy, not a business attribute of a SQL task, so it does not belong in task JSON;
- Schema and target-table metadata may still carry fully qualified names, but they do not stand in for this setting when deciding whether lineage keeps the catalog.

## Source-table Schema metadata

`--schema` accepts a JSON/CSV file, or a directory of rich JSON, used for source-field
resolution, `SELECT *` expansion, and field type/comment enrichment. Rich JSON with field indexes
and DDL is recommended; CSV is a compatibility fallback only.

### Recommended: JSON with Schema and DDL

One JSON per table; when a directory is passed, the table metadata files in it are read and the
latest version per table is selected by version time:

```json
{
  "table_name": "ods.customer_base",
  "full_table_name": "spark_catalog.ods.customer_base",
  "schema": [
    {
      "columnName": "customer_id",
      "columnType": "bigint",
      "columnComment": "Synthetic customer identifier",
      "columnIndex": 0,
      "isPartition": 0
    },
    {
      "columnName": "customer_name",
      "columnType": "string",
      "columnComment": "Synthetic display name",
      "columnIndex": 1,
      "isPartition": 0
    }
  ],
  "ddl": "CREATE TABLE spark_catalog.ods.customer_base (customer_id BIGINT, customer_name STRING) USING iceberg",
  "query_time": "2026-08-14 10:00:00",
  "data_source": "catalog_api"
}
```

Source-table order is decided by this hierarchy:

1. when `ddl` parses successfully, the DDL field order wins;
2. without a DDL, sort by `schema[].columnIndex`, which must start at 0 and be contiguous;
3. when the rich JSON's structure is invalid, a metadata error is raised — it never silently falls back to a guessed order.

`--schema` also accepts an aggregated lightweight JSON. It has no explicit field index and no DDL;
the `columns[]` array order is the field order:

```json
{
  "tables": [
    {
      "table_name": "ods.customer_base",
      "columns": [
        {"name": "customer_id", "type": "bigint"},
        {"name": "customer_name", "type": "string"}
      ]
    }
  ]
}
```

A field value needs at least `name`; `type` and `comment` are optional. The table key in a Schema
should use the full table name as the SQL can resolve it, e.g. `ods.customer_base`. The
lightweight JSON also accepts this shorthand:

```json
{
  "ods.customer_base": [
    {"name": "customer_id", "type": "bigint"},
    {"name": "customer_name", "type": "string"}
  ]
}
```

For a complete multi-table rich-JSON example see
[`examples/metadata/schema_info.json`](../../examples/metadata/schema_info.json).

### Fallback: CSV

Compatible CSV header:

```csv
table_name,column_name,column_type,column_comment
ods.customer_base,customer_id,bigint,Synthetic customer identifier
ods.customer_base,customer_name,string,Synthetic display name
```

`type`/`data_type`/`column_type` and `comment`/`column_comment` are compatible aliases. Row order
within one table in the CSV is taken as the field order, so it can still expand `SELECT *`; but
CSV has no explicit `columnIndex` and no DDL to cross-check. Rely on this only when the exporter
can guarantee row order.

The rich JSON's structure is identical to `--target-ddl-metadata`, so one directory containing all
table metadata can be passed to both flags. `--schema` treats its tables as source-field
candidates; `--target-ddl-metadata` performs authoritative positional binding only for the current
SQL's target table.

## Target-table DDL/Schema metadata

`--target-ddl-metadata` accepts a JSON file or a directory. In a directory, each target table gets
one JSON:

```json
{
  "table_name": "mart.customer_snapshot",
  "full_table_name": "spark_catalog.mart.customer_snapshot",
  "schema": [
    {
      "columnName": "customer_id",
      "columnType": "bigint",
      "columnIndex": 0,
      "isPartition": 0
    }
  ],
  "ddl": "CREATE TABLE ...",
  "query_time": "2026-08-02 09:00:00",
  "data_source": "catalog_api"
}
```

The DDL's and the Schema's field sets must agree. When several metadata records exist for one
table, Core selects a single latest version by `query_time` or `ddl_update_time`; an unsortable
set or a structural conflict fails explicitly.

Target structure precedence:

1. when `ddl` parses successfully, its field order and partition definitions are the authoritative fact;
2. `schema[]` is cross-checked against the DDL by field name and adds types, comments, and explicit positions;
3. without a DDL, sort by `schema[].columnIndex`, which must start at 0 and be contiguous;
4. CSV does not support authoritative target binding; it is only a fallback format for the source-table `--schema`.

Key key/values:

| Key | Value | Purpose |
| --- | --- | --- |
| `table_name` | `database.table` | The canonical name matched against the SQL target table. |
| `full_table_name` | fully qualified catalog name | Preserves catalog information and helps matching. |
| `schema[]` | array of field objects | Supplies authoritative field order, types, and partition markers. |
| `schema[].columnName` | string | The final target field name. |
| `schema[].columnIndex` | integer | Authoritative zero-based field position. |
| `schema[].isPartition` | 0/1 or boolean | Marks partition fields; static partitions occupy no SELECT projection slot. |
| `ddl` | CREATE TABLE string | The preferred authoritative field source when the DDL parses. |
| `query_time` / `ddl_update_time` | sortable timestamp | The basis for choosing among multiple metadata versions. |
| `data_source` | string | Metadata provenance marker, for traceability. |

## Failure policy

By default, any input that fails to load or any statement with `parse_status=failed` returns a
non-zero exit code. Other inputs that parsed successfully are still written to disk, so a local
problem inside a batch can be located. Pass `--allow-partial` only when the caller explicitly
accepts partial results; the option does not turn failed states into successes and it deletes no
diagnostics.

## Input errors versus lineage uncertainty

- A missing file, unreadable JSON, or empty `meta.sql`: an input error, and the CLI fails;
- SQL syntax that forms no supported write statement: `parse_status=failed`;
- SQL that parses but lacks a Schema, an alias, or a unique field source: lineage artifacts may still exist, with the uncertainty expressed through warnings, `trace_complete=false`, or a fact gap;
- `--allow-partial` only decides whether a batch command returns non-zero on a local failure; it raises the credibility of no lineage fact.
