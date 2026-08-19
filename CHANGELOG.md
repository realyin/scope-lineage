# Changelog

## Unreleased

- Documented that `value_sources[]` lists participation paths rather than a set of columns. The
  dedup key is `(table, column, transform)` and includes the transform deliberately, so one
  physical column appears once per way it participates — a derived column on a real slowly
  changing dimension carries 33 entries that dedupe to 16 columns, the same 16 its sibling
  carries as 17. Read as a column set, that looks like the lineage was smeared across the whole
  table, and it has been reported as pollution twice. The document now gives the dedupe recipe
  and warns off the filter that suggests itself — keeping only `DIRECT`/`EXPRESSION`/
  `CONDITIONAL` empties the lineage of every aggregate and window metric, because their value
  arguments carry `AGGREGATE` and `WINDOW` too

## 0.1.9 - 2026-08-19

- Stopped reporting a table qualified by its own name as an unexpanded alias. `qualify` names
  an unaliased table after itself, so `FROM ods.pay` yields references written `pay.uid` while
  the physical id stays `ods.pay`; the exemption for "the alias *is* the physical source"
  compared the two directly and never matched. A fully resolved direct physical source was
  therefore reported as `expanded_expression_contains_unexpanded_alias`, demoting the output to
  partially_resolved and the statement to `partial`. It needed the same table read both in the
  enclosing `FROM` and inside a projection subquery to surface, which is why it hid: the `FROM`
  registers the binding and the subquery puts that same qualifier into the expression text,
  which the textual check cannot tell apart. A genuine local alias is still reported — `s` in
  `FROM ods.source s` is neither the id nor its table name. One real task goes from 7 gaps and
  `partial` to none and `complete`, with its physical sources unchanged

- Recovered the physical sources of a scalar subquery used as a projection. Column references
  inside a nested query are skipped when the enclosing expression is resolved, and rightly so:
  they belong to the subquery's sources, and resolving them outward binds them to whatever the
  outer scope exposes under the same alias. But nothing picked them up afterwards — a scalar
  subquery is not a FROM-clause source, so it never became an input of the outer scope, and the
  projection fell through to the constant fallback with the whole `(SELECT …)` recorded as a
  CONSTANT value and its tables nowhere in the lineage. In the plain shape this was silent: no
  gap, `analysis_status` complete. They now resolve against the subquery's own scope, which
  sqlglot already builds, and a correlated reference still binds outward because alias lookup
  walks parent scopes. Across the real tasks that use the shape, 14 physical source edges come
  back and 5 subqueries stop being reported as constants

- Stopped a dynamic-partition `INSERT OVERWRITE` from claiming the target's previous values
  survived it. The write effect was chosen from `target_partition_mode != "none"`, so
  `PARTITION(dt='20260101')` and `PARTITION(dt)` were treated alike and both carried the
  target's previous `value_sources` forward. Only the first deserves that: a valued spec
  replaces the partitions it names and the rest of the table stands, while a bare
  `PARTITION(dt)` depends on `spark.sql.sources.partitionOverwriteMode`, whose default is
  STATIC — every existing partition is dropped before the new data lands. Every column of such
  a target therefore came back with a `prior_table_state` edge from a state the overwrite had
  destroyed, which is what a consumer folding state-evolution edges reads as "this column was
  left alone". The setting is now read from the script when present and applies to the
  statements after it. A dynamic-partition overwrite now agrees with the unpartitioned one it
  has always resembled: a column the write does not supply gets no row rather than a false
  one. 46 of 200 real tasks lose 1,818 such edges; gap counts, statuses and syntax results are
  unchanged

- Documented that a window field's sources carry three different roles under one
  `transform: "WINDOW"`: the aggregate's value argument, the `PARTITION BY` keys and the
  `ORDER BY` keys. A window partitioned by many columns therefore lists all of them as
  sources, which reads as "the whole table was smeared onto one field" if the roles are not
  separated — a reading that has already produced a false pollution report. The roles are on
  the column that *defines* the window (`columns[].window.partition_by` / `order_by`), not on
  the downstream field, and `end_to_end_lineage` flattens the chain without a back-pointer,
  so both documents now say where to look and how to tell a value source from grouping
  context. No behaviour change

## 0.1.8 - 2026-08-19

- Normalized schema column names the way table names already were. sqlglot's `qualify`
  lower-cases unquoted identifiers, so every column reference the resolver sees is
  lower-case; `normalize_table_name` lower-cases for exactly that reason and says so in its
  docstring, but column names were passed through verbatim. A metadata export that spells
  its columns in upper case therefore matched nothing. Nothing failed loudly: `SELECT *`
  expansion copies schema names into a scope's column list, so an inner scope advertised
  `V1` while the outer scope asked for `v1`, source chains broke to `scope:"UNKNOWN"`, and
  explicitly referenced columns were re-added as case-variant duplicates — while
  `metadata_coverage` still reported every table covered, because coverage only checks table
  names. One real 5-branch MERGE went from 16,122 lineage fact gaps and `partial` to none
  and `complete`; the same schema differing only in case is now the same lineage

- Stopped a MERGE's USING alias from being captured by an inner table of the same name.
  `USING (SELECT record_id AS biz_no, 'prod' AS etl_source FROM ods.src t1) t1` resolved
  every `t1.<col>` against the subquery's *internal* sources, where the inner table won — so
  a renamed projection was published as `ods.src.biz_no`, a column that table does not have,
  and the literal became `ods.src.etl_source`, a physical field. With `trace_complete` true
  and no warning: a confident wrong answer, and precisely what this project's README
  criticises other tools for. A column the subquery passes straight through still binds
  directly to the table, which is the lexical source an earlier fix preserves; only a
  derived column is redirected. 25 fabricated columns in one real task go to none

- Gave `syntax_errors[]` an order that holds across processes. sqlglot builds one message
  per entry of `Expression.required_args`, which is a `set`, and CPython randomises string
  hashing per process — so a statement missing two required keywords wrote the same entries
  in an order that changed between runs. `syntax_errors` is a required field of
  `lineage.json`, and this project treats byte-for-byte determinism as a contract invariant,
  so anyone diffing artifacts across runs saw a phantom change. Sorted by position first, so
  errors genuinely ordered by where they occur keep that order and the description only
  breaks ties

## 0.1.7 - 2026-08-19

- Said where the reader looks when a source table's columns were never supplied. The fact
  was already in `metadata_coverage`, but `analysis_status` said `partial` for
  `lineage_fact_gap` and the document carried thousands of records — every one of those
  words meaning "the parser could not handle this SQL". `blocking_reasons` now names
  `metadata_incomplete` ahead of `lineage_fact_gap`, and a warning lists the source tables
  that were missing. Sources only: a target without a schema entry is an ordinary shape and
  is never why a source-side reference failed

- Resolved `col.field` on a struct column written without a table alias. `alias.col.field`
  carries three parts and was handled; the two-part form had its first part looked up as a
  table alias, found nothing, and reported the column as an unbound alias. Whether the alias
  is there is not the author's choice alone — qualify adds it when it knows the column set
  and cannot when the input is a `SELECT *` — so the same SQL resolved or did not depending
  on how deep it sat. A name more than one input exposes stays unresolved

- Modelled a PIVOT's output columns. `PIVOT (max(amt) FOR k IN ('A', 'B'))` turns the values
  of `k` into columns named A and B whose values come from the aggregate, and neither the
  names nor that lineage existed: a `SELECT *` over a pivoted relation saw the pivoted
  subquery's own columns instead, so every downstream reference to a pivoted name was a gap —
  32 in one real task. The pivot's alias now becomes an input edge when it has one, and a
  star over a pivoted source expands to the IN list. A non-literal IN list still reports a
  gap rather than guessing names

- Stopped qualifying every statement twice. `qualify` mutates the tree it is given and
  returns that same object, so the `qualified is src_expr` comparison that guarded the "did
  qualify fail?" branch was true either way, and the branch re-ran qualify on every
  statement to learn what the first call already knew. `_qualify_ast` now reports success
  directly. Cost only — no output changes, both baselines untouched

- Stopped reading an unexpanded `a.*` as a regex pattern. A qualified star cannot always be
  expanded when its projection is first read — a CTE backed by a UNION only gets its columns
  in a later pass — so it is parked as a placeholder for the fixpoint expansion to finish.
  Spark's regex column selection, added in 0.1.6, then matched that placeholder as a pattern,
  and `a.*` is a valid one: a 63-column star collapsed into the single column whose name
  began with "a", and the placeholder was gone before the pass that would have expanded it
  properly ever ran. Three real tasks go from 44, 64 and 14 gaps to none

- Let a bare column bind through a regex column selection. Spark's `` `(rk)?+.+` `` names
  the columns a source exposes by pattern, and the match runs after column resolution — but
  a scope projecting one was read as already materialized, with a single concrete column
  literally called `(rk)?+.+`. Every other name was then judged absent from it, so a bare
  reference with two inputs lost the only input that could supply it. A pattern means "not
  yet knowable", which the resolver already models and already keeps in play. Of the 36 real
  tasks a regex projection can reach, 1 improves and 35 are unchanged

- Marked the fact gaps that a repaired parse produces, with a new optional
  `derived_from_recovered_syntax` on each. When sqlglot cannot place a token it drops the
  rest, and a statement that said `FROM` becomes one with no source at all — so the gaps
  that follow describe the truncation, not the query. They sat in the same list as gaps
  about genuinely missing metadata, and counting the two together turned one syntax problem
  into 1298 apparent capability gaps in a single real task. `syntax_status` already said the
  parse was repaired; the marker means a consumer no longer has to correlate two documents
  to know which gaps to exclude. Statement lineage needed its own answer, since a truncation
  is invisible once the tree is rendered back out

- Backquoted reserved-word column names in a table's DDL before parsing it. sqlglot's Spark
  dialect does not terminate on `CREATE TABLE db.t (a DOUBLE, not DOUBLE)` — the same 51
  characters hang 30.0.0, 30.16.0 and 30.17.0 alike — so a table whose export happened to
  name a column `not` did not make a task's answer worse, it made the task never finish, and
  no caller could put a timeout around it. Three more tables were being rejected outright by
  the milder version of the same problem, losing 3005 columns apiece. Quoting is an
  equivalent rewrite, and of 314 real DDLs it touches, 308 yield facts identical to before

## 0.1.6 - 2026-08-18

- Roughly halved lineage resolution time on wide statements by remembering answers that
  depend only on their inputs: compiled patterns built from identifier names, the field
  references of an expression, and whether an expression reaches into a struct. A 743 KB
  task that previously exceeded two minutes and returned `partial` now completes in 67
  seconds with no gaps
- Expanded Spark's quoted regex column selection. `` `(dt)?+.+` `` selects every column
  whose name matches the pattern — its possessive quantifier making it the idiom for "every
  column except dt" — and reading it as a literal name produced a column no table has, which
  took every downstream reference to that scope down with it
- Resolved a reference to a LATERAL VIEW's output column when the qualifier is the column
  rather than the view's alias, so `arr.field` binds to the view that exposes `arr`. Two
  views exposing the same name stay a gap rather than being resolved by writing order
- Modelled Spark's `CACHE [LAZY] TABLE ... AS SELECT` as the relation-from-a-SELECT it is.
  It was skipped as an unsupported statement, so the relation it builds was read back as an
  external table nobody has metadata for and every reference to it became a gap — 1205 in a
  single real task. It reports `stmt_kind: "CTAS"` with a new optional `is_cached_relation`
  flag, since the relation lives only for the session
- Made a table's DDL authoritative over its exported column array rather than validating one
  against the other. A partition column declared only in `PARTITIONED BY` is an ordinary
  export shape, not a contradiction, and rejecting it discarded usable metadata
- Limited an unusable metadata file to the table it describes. The loader raised, so two
  malformed files among 3434 left every table without columns; rejected tables are now
  reported through `metadata_conflicts` and only a load that produced no table at all raises

## 0.1.4 - 2026-08-17

- Declared a MERGE's target relation as a ROOT input carrying its alias, so `target.x` can
  be mapped back to the relation it names, while holding it out of `alias_source_bindings`
  so the correlated reference a MERGE action preserves is not read as a failed expansion

## 0.1.3 - 2026-08-17

- Stopped re-parsing each statement from generated SQL during task-level modelling. sqlglot
  does not round-trip a WITH carried by an individual UNION branch, so the clauses merged,
  same-named CTEs shadowed each other, and the whole statement degraded to an unqualified
  parse; the AST parsed from the original script is now used directly
- Report `normalized_sql_not_equivalent` when the rendered statement loses a CTE to
  shadowing, so a consumer is not handed SQL that looks runnable and is not
- Stopped reading `COUNT(*)`'s dependency on the whole row as an unexpanded projection
  wildcard; only a source that is actually an unexpanded `SELECT *` reports one now
- Declared the USING relation as an input of a MERGE's ROOT scope. That scope is synthetic,
  so the pass that walks SQLGlot scopes never reached it and the scope reported no inputs at
  all, leaving `source` unbindable for expressions that resolve a qualifier by alias
- Expanded physical-table references in expressions that also reference a query block; the
  alias-expansion helper skipped physical sources entirely, so the alias stayed in the text
  and its field never reached the physical source list
- Report `column_not_in_table_schema` when a qualifier names a table whose schema proves
  the column does not exist; the qualified path previously took a qualifier as proof and
  published the reference as a physical field
- Resolve statements against tables the same script creates, so a `CREATE ... AS SELECT`
  feeding a later statement no longer leaves that statement's columns unexpandable and no
  longer reports the script-local table as missing warehouse metadata
- Finish expression expansion when substitution reintroduces a qualifier belonging to the
  consuming scope, recovering the physical field behind a LATERAL VIEW over a query block
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

## 0.1.2 - 2026-08-16

- Documentation and packaging only; no library changes

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
