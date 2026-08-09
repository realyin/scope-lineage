# Scope Lineage: a parsing foundation for AI-ready SQL knowledge bases

[中文](README.zh-CN.md) | English

Scope Lineage is an open-source static analyzer for Spark/Hive SQL. Its goal is not merely to
draw a table-lineage graph. It turns SQL tasks into stable, traceable facts that Agents, RAG
systems, search indexes, and knowledge graphs can consume as the foundation of an AI-ready SQL
task knowledge base.

Passing raw SQL or a simple `input table -> output table` edge to an LLM loses CTEs, subqueries,
UNION branches, field expressions, filters, aggregates, and uncertainty. Scope Lineage preserves
those intermediate structures and writes versioned `lineage.json` and `diagnostics.json`
artifacts, allowing AI applications to reason from verifiable facts instead of guessing at SQL
semantics.

> This repository is the first open-source Core layer: SQL/task ingestion, scope parsing,
> column-level lineage, and diagnostics. Embeddings, knowledge-graph storage, business-semantic
> generation, warehouse modeling, and refactoring recommendations belong to upper layers and are
> not included here.

## What it provides

- Offline static analysis for Spark/Hive warehouse SQL; no Spark cluster or query execution is
  required.
- Inputs from one `.sql` file, an exported scheduler task JSON, or a recursive task directory.
- `INSERT INTO`, `INSERT OVERWRITE`, CTAS, and `MERGE` write statements.
- Preserved CTE, subquery, JOIN, UNION/UNION ALL, aggregate, window, and intermediate scopes.
- Field mappings, expressions, physical source fields, end-to-end lineage, and scope dependencies.
- Optional Schema metadata for `SELECT *` expansion, field types, and comments.
- Optional target DDL/Schema metadata for authoritative positional INSERT binding.
- Declared upstream and downstream task dependencies retained from task JSON.
- Explicit status and diagnostics for parse failures, syntax recovery, ambiguity, and missing
  metadata; guesses are not presented as proven facts.
- Versioned JSON Schema contracts validated before artifacts are written.

## How it supports an AI knowledge base

```mermaid
flowchart LR
    A["SQL files / scheduler task JSON"] --> B["Scope Lineage Core"]
    M["Schema / target DDL metadata"] --> B
    B --> L["lineage.json: verifiable SQL facts"]
    B --> D["diagnostics.json: boundaries and uncertainty"]
    L --> K["SQL task knowledge base"]
    D --> K
    K --> R["Agents / RAG / search / knowledge graphs"]
```

The Core owns deterministic parsing and fact representation. It does not force a vector database,
graph database, or model choice. The same facts can support code search, task Q&A, impact analysis,
governance review, and later business-knowledge generation.

## Why another project

The open-source ecosystem already contains mature projects; Scope Lineage does not claim to be the
first SQL parser or lineage tool:

- [SQLGlot](https://github.com/tobymao/sqlglot) is a general SQL parser, transpiler, and optimizer,
  and is the parsing engine used by this project.
- [SQLLineage](https://sqllineage.readthedocs.io/) provides general table- and column-level SQL
  lineage.
- [OpenLineage](https://openlineage.io/docs/guides/spark/) focuses on standardized lineage events
  collected from running Spark jobs.
- [DataHub](https://github.com/datahub-project/datahub/blob/master/docs/api/tutorials/lineage.md) is
  a full metadata platform that can also infer column lineage from SQL.

Scope Lineage specializes in offline Spark/Hive tasks and unifies intermediate scopes, field
transformations, task dependencies, metadata enrichment, end-to-end evidence, and parse diagnostics
as a versioned fact contract for AI knowledge bases. Based on the published positioning of the
projects above, we have not found an open-source tool with exactly this complete objective and
artifact boundary. This is a direction for the project to validate and build—not a claim that no
other SQL-lineage solution exists.

## Install

Install the current version from source:

```bash
git clone https://github.com/realyin/sparksql-knowleage-parse.git
cd sparksql-knowleage-parse
python -m pip install -e ".[dev]"
```

The package name is `scope-lineage`; the current `0.1.x` series is Alpha.

## Quick start

Parse one SQL file:

```bash
scope-lineage parse \
  --sql-file examples/sql/customer_profile_daily.sql \
  --schema examples/metadata/schema_info.csv \
  --target-ddl-metadata examples/metadata/target_tables \
  --out /tmp/scope-lineage
```

Parse one scheduler task export in the current `meta/query_time/data_source` format:

```bash
scope-lineage parse \
  --task-file examples/tasks/customer/customer_profile_daily.json \
  --schema examples/metadata/schema_info.csv \
  --target-ddl-metadata examples/metadata/target_tables \
  --out /tmp/scope-lineage
```

Parse a task directory recursively:

```bash
scope-lineage parse \
  --input-dir examples/tasks \
  --schema examples/metadata/schema_info.csv \
  --target-ddl-metadata examples/metadata/target_tables \
  --out /tmp/scope-lineage-corpus
```

Nested input paths are preserved in the output. When one task contains multiple supported write
statements, each statement receives its own artifacts. Use `--allow-partial` only when callers
explicitly accept invalid inputs or failed statements. See the complete synthetic corpus in
[examples/README.zh-CN.md](examples/README.zh-CN.md) and the detailed
[Core input formats](docs/zh-CN/input-formats.md).

## Inputs

Task JSON may use the current scheduler-export wrapper:

```json
{
  "meta": {
    "task_id": "demo-task-1002",
    "task_name": "customer_profile_daily",
    "input_tables": ["ods.customer_base", "dwd.order_detail"],
    "output_tables": ["mart.customer_profile_snapshot"],
    "upstream_tasks": [
      {"task_id": "demo-task-1001", "task_name": "order_detail_daily"}
    ],
    "downstream_tasks": [],
    "sql": "INSERT OVERWRITE TABLE ..."
  },
  "query_time": "2026-08-02 10:00:00",
  "data_source": "scheduler_api_demo"
}
```

Schema metadata accepts CSV or JSON. A production-shaped CSV can carry types and comments:

```csv
table_name,column_name,column_type,column_comment
ods.customer_base,customer_id,bigint,Synthetic customer identifier
ods.customer_base,customer_name,string,Synthetic customer name
```

`--target-ddl-metadata` accepts one JSON file or a directory with one document per target table.
Schema metadata resolves source fields and expands `SELECT *`; target metadata provides
authoritative target order for INSERT binding.

## Outputs

Each supported write statement creates only two Core artifacts:

```text
<output>/<task-id>/
├── lineage.json
└── diagnostics.json
```

`lineage.json` contains task identity, target and partition facts, parse status, task dependencies,
source tables, related metadata, the scope graph, scope facts, field-mapping chains, physical source
fields, and end-to-end lineage. `diagnostics.json` contains complete warnings, syntax-recovery
evidence, unresolved references, and degradation reasons. AI consumers should read both documents
and must not treat recovered syntax, ambiguous candidates, or missing metadata as proven lineage.

## Python API

```python
from lineage_parser import parse_scope_lineage, to_lineage_dict, write_lineage

result = parse_scope_lineage(
    "INSERT INTO mart.user_ids SELECT id FROM ods.users",
    task_id="user_ids",
    schema={"ods.users": ["id"]},
)

document = to_lineage_dict(result)
write_lineage(result, "/tmp/scope-lineage/user_ids")
```

The supported public surface is declared by `lineage_parser.PUBLIC_CORE_API`. Consumers should use
that facade or the JSON contracts instead of importing internal modules.

## Contracts and limits

Both output documents currently require `schema_version: "1.0"` and are validated before writing.
Within major version 1, consumers must tolerate additive optional fields. Removal, renaming, or a
semantic change requires a new major contract version.

- [Lineage contract (Chinese)](docs/zh-CN/lineage-json.md)
- [Diagnostics contract (Chinese)](docs/zh-CN/diagnostics-json.md)
- [Core input formats (Chinese)](docs/zh-CN/input-formats.md)

Current limits:

- Static analysis does not prove that SQL will execute successfully on a real Spark cluster.
- Standalone `UPDATE`/`DELETE` is outside the current projection model; update/insert branches
  inside `MERGE` are supported.
- Dynamic SQL, template expansion, and platform-specific syntax may require preprocessing.
- Without Schema metadata, `SELECT *` may remain an explicit degraded placeholder.
- Scope Lineage supplies facts to a knowledge base; it is not a complete knowledge-base product.

## Development

```bash
python -m pytest -q tests/core tests/architecture/test_core_boundaries.py
python -m ruff check lineage_parser tests
python -m build
python tests/architecture/verify_distribution.py dist/*
```

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md) before submitting changes.
All fixtures must be synthetic and free of private SQL, internal identifiers, and local paths.

## License

Apache License 2.0. See [LICENSE](LICENSE).
