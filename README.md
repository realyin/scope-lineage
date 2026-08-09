# Scope Lineage

[中文](README.zh-CN.md) | English

Scope Lineage is a scope-aware, column-level lineage parser for Spark/Hive SQL. It statically
turns SQL plus optional generic schema/DDL metadata into two versioned artifacts:

- `lineage.json`: scope graph, field mappings, end-to-end lineage, and parse status;
- `diagnostics.json`: detailed warnings and degradation evidence.

This repository is the open-source foundation layer only. It does not contain warehouse-specific
modeling, business-domain presets, Insight reports, or refactoring recommendations.

## Install from source

```bash
git clone https://github.com/realyin/sparksql-knowleage-parse.git
cd sparksql-knowleage-parse
python -m pip install -e ".[dev]"
```

The first package release is prepared as `scope-lineage 0.1.0`; until it is uploaded to a package
index, install it from this repository.

## Command line

```bash
scope-lineage parse \
  --sql-file examples/simple_insert.sql \
  --schema examples/table_cols.csv \
  --out /tmp/scope-lineage
```

The command writes only:

```text
/tmp/scope-lineage/simple_insert/
  lineage.json
  diagnostics.json
```

Use `--target-ddl-metadata` when INSERT projections must be bound to authoritative target columns
by position. Use `--allow-partial` only when callers explicitly accept failed statements being
written with diagnostics.

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

The supported public surface is explicitly declared by `lineage_parser.PUBLIC_CORE_API`.
Downstream projects should use that facade or consume the JSON contracts rather than importing
private implementation modules.

## Contract compatibility

Both output documents require `schema_version: "1.0"` and are validated before writing. Within
major version 1, consumers must tolerate additive optional fields. Removing fields, renaming them,
or changing their meaning requires a new major contract version.

- [Lineage contract (Chinese)](docs/zh-CN/lineage-json.md)
- [Diagnostics contract (Chinese)](docs/zh-CN/diagnostics-json.md)

## Scope and limitations

- Spark/Hive dialect, static analysis only; SQL is never executed.
- Primarily targets `INSERT` and `MERGE` warehouse statements.
- Preserves CTEs, subqueries, UNION branches, aggregates, windows, and intermediate scopes.
- Missing schema metadata may leave `SELECT *` as an explicit degraded placeholder.
- Unsupported or recovered syntax remains visible through parse status and diagnostics.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest -q tests/core tests/architecture/test_core_boundaries.py
python -m ruff check lineage_parser tests
python -m build
python tests/architecture/verify_distribution.py dist/*
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md) before submitting examples or
parser changes. All fixtures must be synthetic and free of private SQL, identifiers, and paths.

## License

Apache License 2.0. See [LICENSE](LICENSE).
