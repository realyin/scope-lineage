[中文](README.zh-CN.md) | English

# Examples

Every file here is synthetic data, but the input structure matches the current production corpus.
The examples fall into three groups:

```text
examples/
├── sql/                    # Spark SQL files handed straight to Core
├── tasks/                  # task JSON exported by a scheduler (recursive directories supported)
├── metadata/
    ├── schema_info.json    # recommended: field indexes, DDL, types, and comments
    ├── schema_info.csv     # fallback: a compatible format read in row order
    └── target_tables/      # one DDL/Schema JSON per target table
└── sample_data/            # synthetic CSV used only to explain the sample logic; Core reads no row data
```

## Coverage

| Example | Main syntax and lineage problems |
| --- | --- |
| `sql/customer_profile_daily.sql` | Several CTEs, JOIN, window function, CASE, aggregation, static partition |
| `sql/order_channel_metrics.sql` | UNION ALL, normalizing several sources, aggregation, conditional metric |
| `sql/customer_profile_merge.sql` | MERGE, matched update, not-matched insert |
| `sql/select_star_with_schema.sql` | Schema-dependent `SELECT *` expansion |
| `sql/multi_statement_publish.sql` | Several write statements inside one task |
| `sql/subscription_account_snapshot.sql` | A complex desensitized sample with 19 source tables, 20 JOINs, multi-level subqueries, conditional aggregation, a window function, and 112 target fields |
| `tasks/**/*.json` | Real `meta/query_time/data_source` wrappers, task dependencies, and directory batch input |

## Running them

Parse a bare SQL file:

```bash
scope-lineage parse \
  --sql-file examples/sql/customer_profile_daily.sql \
  --schema examples/metadata/schema_info.json \
  --target-ddl-metadata examples/metadata/target_tables \
  --out /tmp/scope-lineage/sql
```

Parse one scheduler task JSON:

```bash
scope-lineage parse \
  --task-file examples/tasks/customer/customer_profile_daily.json \
  --schema examples/metadata/schema_info.json \
  --target-ddl-metadata examples/metadata/target_tables \
  --out /tmp/scope-lineage/task
```

Parse a whole task directory recursively:

```bash
scope-lineage parse \
  --input-dir examples/tasks \
  --schema examples/metadata/schema_info.json \
  --schema-fallback examples/metadata/subscription_account_snapshot/source_tables \
  --target-ddl-metadata examples/metadata/target_tables \
  --out /tmp/scope-lineage/corpus
```

Parse the complex subscription-billing account snapshot sample:

```bash
scope-lineage parse \
  --task-file examples/tasks/subscription/subscription_account_snapshot.json \
  --schema examples/metadata/subscription_account_snapshot/source_tables \
  --schema-fallback examples/metadata/target_tables/demo_mart.subscription_account_snapshot_metadata.json \
  --target-ddl-metadata examples/metadata/target_tables/demo_mart.subscription_account_snapshot_metadata.json \
  --contract-version 2.0 \
  --out /tmp/scope-lineage/subscription-account
```

The matching synthetic row data lives in `examples/sample_data/subscription_account_snapshot/`. It
is used by later documentation to explain charge classification, two-level aggregation, and the
final metric computation; it is not a runtime input to Core's static analysis.

The task JSON fields that matter directly to parsing are `meta.task_name`, `meta.sql`,
`meta.upstream_tasks`, and `meta.downstream_tasks`. The remaining fields are kept in the examples to
represent the real upstream export format faithfully; Core does not copy platform attributes such
as owner or schedule period into `lineage.json`.

Every public asset is either fully synthetic or desensitized demonstration content that preserves
the structure; none of it contains real table names, field names, row data, people, emails,
projects, or local paths.
