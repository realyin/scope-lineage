# Changelog

## Unreleased

- Fixed MERGE lineage corruption when the statement is preceded by a CTE: qualify
  reorders the column traversal, so pairing pre- and post-qualify columns by position
  pasted a MERGE action's target references onto unrelated CTE projections and
  neighbouring UPDATE assignments. Correlated target references are now protected across
  qualify by identity, and an unrestorable reference fails the statement instead of
  publishing a positional guess
- Resolved MERGE `row_membership_sources` through the built USING scope, so a CTE- or
  subquery-backed USING reports its physical root fields instead of the query block's
  name, a UNION reports every branch instead of the literal `UNKNOWN`, and a condition
  the USING relation does not expose reports a new `merge_condition_source_unresolved`
  fact gap instead of a fabricated column

## 0.1.1 - 2026-08-15

- Added opt-in task-level `schema_version: "2.0"` output with ordered statements and
  table-state transitions for write and mutation operations
- Made rich JSON table schema metadata authoritative over CSV fallbacks, preserving column order,
  DDL, and other structured metadata while reporting conflicts
- Added installation, CLI usage, input-format, schema-precedence, and release documentation

## 0.1.0 - 2026-08-14

Initial public release preparation:

- Added opt-in task-level `schema_version: "2.0"` contracts that preserve statement order and
  model table-state transitions across INSERT, overwrite, CTAS, MERGE, DELETE, UPDATE, and
  TRUNCATE, including partition-scoped replacement/reset behavior
- Separated final-field value provenance, value-condition provenance, and row-membership
  provenance so DELETE predicates are not misrepresented as field value sources
- Added schema fallback merging with conflict reporting, metadata coverage diagnostics, target
  binding reason codes, compact JSON output, and configurable CLI quality gates
- Added a SQLGlot compatibility CI matrix for the oldest, previous, and latest supported releases
- Adapted MERGE scope handling for SQLGlot 30.17 and constrained the verified range to
  `sqlglot>=30,<30.18`; MERGE now uses an explicit USING scope instead of SQLGlot's removed
  root Subquery wrapper
- Fixed MERGE action scalar-subquery lineage so nested predicates are not emitted as target
  assignments, correlated target references remain physical self-sources, and scalar outputs bind
  through their own scopes instead of the USING scope
- Resolve CTE references lexically when collecting physical inputs, preserving an unqualified
  physical table that shares a name with a CTE in a different query block
- Versioned `lineage.json` and `diagnostics.json` 1.0 contracts with mandatory validation
- Pure Core writer API for emitting only Lineage and Diagnostics artifacts
- `scope-lineage parse` CLI for SQL files, exported task JSON, and recursive task directories;
  it still emits only Core artifacts
- Explicit `--catalog-prefixes` / `SCOPE_LINEAGE_CATALOG_PREFIXES` normalization policy; full
  catalog-qualified table identities are preserved by default
- Explicit `PUBLIC_CORE_API` facade for downstream Python consumers
- Wheel and source-distribution manifests contain only Lineage Core
- CI verifies Python 3.9–3.12, archive contents, and a repository-external installation
- Scope-aware column lineage parser for Spark/Hive SQL
- schema metadata loading for `SELECT *` expansion
- target DDL/Schema metadata loading for positional INSERT binding
- production-shaped synthetic examples for task wrappers, task dependencies, complex Spark SQL,
  Schema CSV/JSON, and target-table DDL metadata
- public documentation centered on AI-ready SQL task knowledge bases
- field-level documentation for every major Lineage and Diagnostics object, including scope values,
  logic blocks, mapping chains, end-to-end trace semantics, fact gaps, and safe AI consumption
