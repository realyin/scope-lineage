# Metadata inputs: three flags, and what silently breaks without them

The parser runs without any metadata — but three capabilities degrade SILENTLY when
their input is missing, and the output looks superficially fine. This is the single
most common way to get a low-quality artifact while believing everything worked.

| Flag | Feeds | Without it |
| --- | --- | --- |
| `--schema` | Source-table schemas: expands `SELECT *` / `t.*` into concrete columns, fills column types/comments | Stars stay unexpanded (`star_not_expanded` warning, `projection_wildcard_unexpanded` gaps with `root_impact`); field-level coverage silently shrinks |
| `--schema-fallback` (repeatable) | Tables ABSENT from `--schema` only | Tables known only to the fallback get no schema at all |
| `--target-ddl-metadata` | Authoritative target-table DDL: binds projections to real target columns BY POSITION | `target_field_binding` never applies. Spark writes `INSERT ... SELECT` by position, not by alias — when aliases differ from real column names (or are auto-generated like `_col_6`), state columns are built under wrong names and downstream lineage breaks there |

Wiring rules:

- `--schema` accepts a rich-JSON directory (one JSON per table, with column order and
  partition flags) or a single JSON/CSV file. When both a rich-JSON source and a CSV
  exist, the rich JSON is `--schema` and the CSV is `--schema-fallback` — reversing
  them makes every table that exists only in the JSON invisible.
- `--catalog-prefixes` (or `SCOPE_LINEAGE_CATALOG_PREFIXES`; the flag wins) strips
  leading catalog names from table identities. It is a deployment policy: never bake it
  into task JSON, and by default catalogs are preserved.
- `--partition-overwrite-mode static|dynamic` declares the cluster's
  `spark.sql.sources.partitionOverwriteMode`; a `SET` inside the script always wins.

## Team defaults file

Private metadata paths belong in `~/.scope-lineage/defaults.json`, never in this skill
or any published text:

```json
{
  "schema": "/path/to/rich-json-metadata-dir",
  "schema_fallback": ["/path/to/fallback.csv"],
  "target_ddl_metadata": "/path/to/ddl-metadata-dir",
  "catalog_prefixes": "some_catalog"
}
```

When the file exists, translate each key to its flag on every parse unless the user
overrides. When it does not and the user is parsing real tasks, ask for their metadata
locations instead of parsing bare — explain what degrades (the table above) so they can
make an informed choice. Parsing bare is fine for quick synthetic experiments.

## Reading the coverage report back

After parsing with metadata, `diagnostics.json` carries `metadata_coverage` (v2 task
documents): which source tables had schema, which were missing. Check it FIRST when
gaps appear — `analysis_status.blocking_reasons` listing `metadata_incomplete` before
`lineage_fact_gap` means the gaps are an input problem, not a parser limitation, and
supplying the missing schemas usually drives the same task to zero gaps.
