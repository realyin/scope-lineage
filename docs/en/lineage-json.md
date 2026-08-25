[中文](../zh-CN/lineage-json.md) | English

# The `lineage.json` output contract and field reference

This page describes the **statement document** contract (`schema_version: "1.0"`) — since 0.2.0
it is no longer written as a standalone file but embedded in full as an entry of the task
document's `statement_lineage.<statement_id>`; the field definitions here apply verbatim to every
entry. For the task document itself (the task-level ordered state contract) see
[Task Lineage 2.0](task-lineage-v2.md), whose authoritative schema is
`scope_lineage/schemas/lineage-v2.schema.json`; this contract's authoritative schema
`lineage.schema.json` still ships with the package, and every embedded entry is validated against
it before writing.
If you are unsure which layer your scenario should read, start with
[choosing the layer by scenario](contract-selection.md): field lineage and transformation-step
analysis only need the statement document; statement order, DELETE/TRUNCATE, and final table state
are task level.

## 1. What it actually outputs

`lineage.json` is not a set of simple "input table → output table" edges; it is a structured fact
document for one SQL task. It answers five kinds of question at once:

1. **Task facts**: which table is written, with which statement, and how it is partitioned;
2. **Structural facts**: which CTEs, subqueries, UNION branches, and ROOT query blocks the SQL was split into;
3. **Logic facts**: which JOINs, filters, aggregates, windows, and field expressions each query block executed;
4. **Field facts**: which scopes each target field passed through, and which physical fields or generated values it ultimately comes from;
5. **Confidence facts**: whether the lineage is complete, where ambiguity exists, and what evidence is still missing.

The authoritative JSON Schema lives at:

```text
scope_lineage/schemas/lineage.schema.json
```

The document explains field semantics and consumption methods; the Schema decides whether a
structure is legal. When the two conflict, the current version's Schema and the actual
serialization code win.

## 2. From SQL to facts: a minimal example

Input:

```sql
INSERT OVERWRITE TABLE mart.customer_summary PARTITION (dt='${bizdate}')
SELECT
  c.customer_id,
  COUNT(DISTINCT o.order_id) AS order_count
FROM ods.customer c
LEFT JOIN dwd.order_detail o
  ON c.customer_id = o.customer_id
WHERE c.dt = '${bizdate}'
GROUP BY c.customer_id;
```

`lineage.json` expresses it as:

```json
{
  "schema_version": "1.0",
  "task_id": "customer_summary",
  "target_table": "mart.customer_summary",
  "stmt_kind": "INSERT_OVERWRITE",
  "parse_status": "ok",
  "syntax_status": "strict_ok",
  "target_partition_spec": {"dt": "${bizdate}"},
  "target_partition_columns": ["dt"],
  "target_partition_mode": "static",
  "source_tables": ["dwd.order_detail", "ods.customer"],
  "scope_graph": {
    "nodes": ["ROOT", "dwd.order_detail", "ods.customer"],
    "edges": [
      {"from": "ods.customer", "to": "ROOT"},
      {"from": "dwd.order_detail", "to": "ROOT"}
    ]
  },
  "end_to_end_lineage": [
    {
      "column": "order_count",
      "transform": "AGGREGATE",
      "trace_complete": true,
      "physical_sources": [
        {"table": "dwd.order_detail", "column": "order_id", "transform": "AGGREGATE"}
      ]
    }
  ]
}
```

This fragment omits the full `scopes` and `field_mapping_chains`. Real output also preserves JOIN
conditions, filter fields, GROUP BY, original expressions, field transformation steps, and a
diagnostics summary.

## 3. The top-level object: keys and values

### 3.1 Complete top-level field table

| Key | Value type | Required | Meaning and use |
| --- | --- | --- | --- |
| `schema_version` | string | Yes | Fixed at `1.0` for a statement document. Consumers check the major version first. |
| `task_id` | string | Yes | The task identifier of this write statement; batch inputs and multi-statement tasks may derive separate identifiers from the input name. **Do not use it to correlate v1 and v2 artifacts**: for a multi-write script, v1 suffixes by write ordinal (`task#0`, `task#1`) and v2 by script position (`task#1`, `task#3`), so the same `task#1` points at different statements in the two artifacts. The correlation key is `statement_id`, below. |
| `statement_id` | string | Conditional | Script-position form `stmt:NNN` (e.g. `stmt:002`); **it takes the same value as v2's `statement_sequence[].statement_id` for the same statement** — this is the **only specified correlation key** between the v1 and v2 artifacts. Emitted when the script text was parsed (the CLI, `parse_all_scope_lineage`, or `parse_scope_lineage` given SQL); not emitted when the caller passes an already-parsed AST (`tree=`) — the script position is unknowable there, and guessing one would silently match the wrong statement. |
| `statement_index` | integer | Conditional | Zero-based script position, counting **every** statement in the script (including unmodeled ones such as SET and DELETE), on the same basis as v2's `statement_sequence[].statement_index`. It appears and is absent together with `statement_id`. |
| `target_table` | string | Yes | What the SQL actually writes, e.g. `mart.customer_summary`. `INSERT OVERWRITE DIRECTORY` writes a file path rather than a table, and the value then looks like `directory:/warehouse/export/daily`, with a `directory:` prefix. **Consumers registering warehouse tables should exclude such values first**; lineage for these statements is produced as usual, and because the target is not a table, `target_field_binding` does not appear. |
| `stmt_kind` | enum string | Yes | `INSERT_OVERWRITE`, `INSERT`, `CTAS`, `MERGE`, or `UNKNOWN`. Note the field is not named `statement_type`. |
| `is_session_scoped_relation` | boolean | No | Present only when `true`. The relation this statement produces lives only for the session and is never stored: `TEMP VIEW`, `GLOBAL TEMP VIEW`, and `CACHE [LAZY] TABLE` all qualify. **Consumers must not register a new warehouse table on this basis**, and should exclude these when counting table-level coverage. The test comes from AST facts rather than naming patterns: a `CREATE VIEW` without `TEMPORARY` registers in the catalog and survives across sessions, so it does **not** carry this marker. `is_cached_relation` is the pre-existing subset of this field for CACHE syntax, with unchanged meaning. |
| `parse_status` | enum string | Yes | `ok` means a verifiable lineage document was formed; `failed` means parsing failed and normal lineage must not be consumed. |
| `syntax_status` | enum string | Yes | `strict_ok`, `recovered`, or `failed`. `recovered` means the parser went through recovery, and the diagnostics must be read alongside. |
| `syntax_errors` | array<object> | Yes | Syntax errors or recovery evidence. Elements may carry `description`, `line`, `col`, and context fragments. |
| `skipped_statements` | array<object> | Conditional | Top-level statements not modeled as a projection write by v1. Contains a stable `statement_id`, zero-based `statement_index`, `statement_kind`, `category`, `model_status`, `reason`, `normalized_sql`, and a note on the supported range; row changes should be modeled with v2 instead. **Statements whose `category` is `control_statement` (such as `SET`) or `empty_statement` are ignored by design and are only recorded — they no longer raise an `unsupported_statement` warning**; to know what was ignored, read this field (it appears only in `lineage.json`, not in `diagnostics.json`).<br>The single-statement API `parse_scope_lineage` models only the **first** write statement in a script: later write statements are recorded here with `category: additional_write_statement` and `model_status: not_modeled` (with `target_table`), and one `additional_write_statements_not_modeled` warning lists the unmodeled targets. Those statements are themselves supported — to model all of them, use `parse_all_scope_lineage` (which is what the CLI does) or contract 2.0. |
| `target_partition_spec` | object | Yes | Map of partition name to partition value. A dynamic partition's value may be `null`. |
| `target_partition_columns` | array<string> | Yes | The target table's partition column names. |
| `target_partition_mode` | enum string | Yes | `none`, `static`, `dynamic`, or `mixed`, describing **how the `PARTITION(...)` clause is written**: a value given is `static`, no value is `dynamic`, no clause at all is `none`. **It is unrelated to the session setting `spark.sql.sources.partitionOverwriteMode`** and does not state how much data this overwrite deletes — the two have similar names and different meanings. The actual blast radius of an overwrite is expressed by v2's `effect.rowset_effect`; see task-lineage-v2.md. |
| `target_field_binding` | object | Conditional | Emitted when target-table DDL/Schema is provided; states whether target fields were bound in authoritative order. |
| `target_binding_absent_reason` | enum string | Conditional | **Present only when there is no `target_field_binding`**, saying which of the cases applies. `statement_defines_its_own_columns` (CTAS: creating the table defines the columns), `binding_not_applicable_for_statement` (MERGE: target columns are resolved outside of binding), `target_is_not_a_table` (writing a file path), `metadata_not_provided` (the caller passed no `--target-ddl-metadata`), **`target_table_not_found` (a directory was passed but this table is missing — only this one carries risk**: Spark's `INSERT ... SELECT` writes by position, so an unbound projection may land in the wrong column).<br>Two places where the key does **not** appear: statements that failed to parse (`parse_status: "failed"`), and the few statements that return early in parsing and never reach the binding stage — consumers must not assume this set is closed over the artifact.<br>A MERGE caveat: when target DDL is provided, a `*` branch takes its column names from that DDL, in target order; without it, the source column names are used. Both are classified as `binding_not_applicable_for_statement`, and the artifact does not distinguish them. |
| `task_dependencies` | object | Yes | Upstream and downstream task declarations preserved from the task JSON, plus a dependency-source summary. |
| `source_tables` | array<string> | Yes | The deduplicated list of every physical input table resolved. Suited to table-level search and first-pass impact analysis. |
| `related_metadata` | object | Yes | Field types and comments for input and output tables, plus observations about metadata completeness. |
| `partition_columns` | array<string> | No | Compatibility field; records partition columns identified during parsing. New consumers should prefer `target_partition_columns`. |
| `scopes` | object/map | Yes | Keys are scope IDs, values are that query block's complete facts. This is the most detailed SQL structure layer. |
| `scope_graph` | object | Yes | `nodes[]` are scope/physical-table nodes; `edges[]` mean data flows from `from` to `to`. |
| `field_mapping_chains` | array<object> | Yes | The ordered transformation chain of each target field, explaining how the field crosses scopes to reach its final target. |
| `scope_profile` | object | Yes | A deterministic summary table derived from the scope facts, suited to indexing, retrieval, and giving an AI low-cost context. |
| `end_to_end_lineage` | array<object> | Yes | Aggregated lineage from each final target field to physical fields, constants, or row-set sources. |
| `diagnostics` | object | Yes | A summary of the full diagnostics: warning count, gap count, type distribution, samples, and stats. |

### 3.2 Why `scopes`, `field_mapping_chains`, and `end_to_end_lineage` all exist

The three are not duplicates:

| Layer | Question it answers | Typical consumer |
| --- | --- | --- |
| `scopes` | What exactly does this SQL do inside each query block? | SQL explanation, logic review, code navigation |
| `field_mapping_chains` | In what order does a field pass through several query blocks? | Evidence display, field transformation explanation, debugging |
| `end_to_end_lineage` | Which physical fields is a final field definitely from? | Impact analysis, search indexes, knowledge-graph edges |

Reading only `end_to_end_lineage` builds a graph quickly; when you need to explain "why", go back
along `field_mapping_chains` and `scopes` for the evidence.

## 4. Identifiers and reference rules

### 4.1 Scope IDs

Common IDs:

| Form | Meaning |
| --- | --- |
| `ROOT` | The top-level SELECT/MERGE projection that writes the target table. |
| `cte:<name>` | A CTE query block, e.g. `cte:order_summary`. |
| `subq:<name>` | A subquery query block. |
| `union:<name>` | A UNION combining query block. |
| `union:<name>:b01` | The first branch of a UNION. |
| `<database>.<table>` | A physical table node in the scope graph. |

`scopes` is a JSON object, not an array:

```json
{
  "scopes": {
    "cte:order_summary": {"kind": "cte", "depends_on": ["dwd.order_detail"]},
    "ROOT": {"kind": "root", "depends_on": ["cte:order_summary", "ods.customer"]}
  }
}
```

Here the key `cte:order_summary` is a stable reference and the value is that query block's facts.
`scope_graph.edges[].from/to`, the `scope` inside field sources, and the scope fragment of logic
IDs all reference these IDs.

### 4.2 Other stable references

| ID | Example | Purpose |
| --- | --- | --- |
| `input_ref_id` | `input:ROOT:001` | Distinguishes each FROM/JOIN input within one scope, so the same table referenced several times is not confused. |
| `logic_block_id` | `logic:ROOT:join:001` | Locates a JOIN, filter, aggregate, window, or other logic block. |
| `mapping_chain_id` | `mc:001` | A short in-document mapping chain ID. |
| `chain_id` | `chain:ROOT:customer_id:position:0` | A semantic ID carrying target scope, field, and position. |
| `gap_id` | `lineage_gap:0001` | A fact gap ID in `diagnostics.json`. |

## 5. `scope_graph`: the query-block dependency graph

Structure:

```json
{
  "scope_graph": {
    "nodes": ["ROOT", "cte:order_summary", "dwd.order_detail"],
    "edges": [
      {"from": "dwd.order_detail", "to": "cte:order_summary"},
      {"from": "cte:order_summary", "to": "ROOT"}
    ]
  }
}
```

- `nodes[]`: the full set of physical tables and logical scopes;
- `edges[].from`: the data provider;
- `edges[].to`: the query block consuming that data.

This graph preserves intermediate structure. Simple table lineage would only yield
`dwd.order_detail → mart.customer_summary`; the scope graph can express
`dwd.order_detail → cte:order_summary → ROOT`, letting an AI know which layer the aggregate
happened in.

## 6. `scopes.<scope_id>`: detailed facts for each query block

### 6.1 The main fields of a scope value

| Key | Value | Meaning |
| --- | --- | --- |
| `kind` | enum string | `physical_table`, `cte`, `subquery`, `union`, `union_branch`, or `root`. |
| `role` | string | A deterministic structural role such as `aggregate`, `dedup`, `join`; this is a SQL structure summary, not a business-domain judgment. |
| `depends_on` | array<string> | Physical tables or other scope IDs it depends on directly. |
| `alias_in_parent` | string | This scope's alias in the parent query. |
| `writes_to` | string | The target table the ROOT scope writes. |
| `raw_sql` | string/null | The normalized SQL of this query block. |
| `raw_sql_available` | boolean | Whether this scope has reusable SQL text. |
| `raw_sql_quality` | object | Whether the SQL text is clean, and whether it contains placeholders or recovery evidence. |
| `source_coverage` | object | Whether the actual sources in `raw_sql` cover the declared sources, and whether any are missing or extra. |
| `input_edges[]` | array<object> | Concise edges for FROM/JOIN/lateral view inputs. |
| `input_source_refs[]` | array<object> | The stable identity, physical-source resolution, and binding trace of each input. |
| `alias_source_bindings[]` | array<object> | Bindings from SQL aliases to input references, scopes, or physical tables. |
| `expression_source_bindings[]` | array<object> | How qualifiers/fields inside expressions bind to sources. |
| `logic_blocks[]` | array<object> | Referenceable logic units: JOIN, filter, aggregate, window, and so on. |
| `outputs[]` | array<object> | Detailed output-field facts for this scope. |
| `field_usage[]` | array<object> | Which fields of each input source are used by logic blocks or output fields. |
| `columns[]` | array<object> | A compatibility projection view; new consumers should prefer the richer `outputs[]`. |
| `union_branch_alignment` | object | UNION branches, field positions, and alignment status. Emitted only for the relevant scopes. |
| `joins[]` | array<object> | A compatibility JOIN structure preserving left and right inputs, type, ON expression, and fields. For exact relations prefer `logic_blocks[].join_relation_detail`. |
| `filters[]` | array<object> | Compatibility WHERE conditions and referenced fields. For an exact condition breakdown prefer `filter_predicate_detail`. |
| `group_by[]` / `having[]` | array | Structured clause facts for grouping and post-aggregate filtering. |
| `order_by[]` | array<object> | Sort expressions, fields, and directions. Ordering inside a window also appears in `window_specification`. |
| `distinct` | boolean | Whether this SELECT uses DISTINCT. |
| `lateral_views[]` | array<object> | Structured facts for LATERAL VIEW/UDTF. |

A MERGE's `ROOT` is a write scope synthesized by Core; it does not correspond to a single SQLGlot
query scope. In contract 1.0, `scopes.ROOT.raw_sql` holds the normalized `USING` row-set SQL so
that it stays stable across SQLGlot versions; it does not represent the complete MERGE statement.
The write expressions of each `WHEN MATCHED` / `WHEN NOT MATCHED` branch should be read from
`merge_branch` and `merge_when_index` inside `ROOT.columns[]` / `ROOT.outputs[]`.

Spark has **three** kinds of WHEN clause, and the `merge_branch` enum names only two of them. The
third, `WHEN NOT MATCHED BY SOURCE`, emits **no `merge_branch`**; it is carried by
`merge_branch_qualifier` (value `not_matched_by_source`) instead, together with a
`merge_branch_not_representable` warning explaining the absence. `merge_when_index` is given as
usual. Emitting a name that already exists in the enum would make consumers compute the wrong
row-set semantics: `not_matched` means "not present in the target, insert from source", whereas
this clause means exactly "present in the target, with no matching row in the source".

The branch also decides the **name-resolution domain of the assignment's right-hand side**, which
matches Spark: `MATCHED` sees both target and source (same name on both sides and unqualified →
`ambiguous_unqualified`, with no source arbitrarily chosen); `NOT MATCHED` sees only the source;
`NOT MATCHED BY SOURCE` sees only the target, and a reference there qualified with the source alias
cannot be resolved in Spark, so Core records `dangling_column_ref_dropped` and emits no source
edge. If the written value contains a scalar subquery, the ROOT field first references that
subquery's stable scope output, and the scope chain then expands to the physical fields; fields
inside the subquery are never mis-bound to the `USING` scope.
A correlated field inside a scalar subquery that references the MERGE target row is preserved as a
physical self-reference to the target table and appears in `source_tables`.

CTE names bind by the lexical scope of the query block they are in. For example, a nested query
declaring `WITH staging AS (...)` does not hide a physical table named `staging` without a database
prefix in a sibling query block; the latter still enters `source_tables`.

### 6.2 `input_edges[]` and `input_source_refs[]`

`input_edges[]` suits drawing structure diagrams:

```json
{
  "source_id": "cte:order_summary",
  "source_type": "scope",
  "position": "join",
  "alias": "summary",
  "join_type": "LEFT_OUTER",
  "join_condition": "`base`.`customer_id` = `summary`.`customer_id`"
}
```

`input_source_refs[]` suits exact binding and tracing:

```json
{
  "input_ref_id": "input:ROOT:003",
  "source_id": "cte:order_summary",
  "source_type": "scope",
  "physical_source_ids": ["dwd.order_detail"],
  "source_resolution": {
    "status": "resolved",
    "cardinality": "single_source",
    "physical_source_tables": ["dwd.order_detail"]
  },
  "field_resolution_required": true,
  "binding_status": "resolved",
  "binding_trace": [],
  "trace_status": "complete"
}
```

When the same physical table is joined twice, fields cannot be bound by table name alone; use
`input_ref_id` to distinguish the input instances.

## 7. `logic_blocks[]`: SQL processing logic

Every logic block has at least:

| Key | Value | Meaning |
| --- | --- | --- |
| `logic_block_id` | string | A stably referenceable logic ID. |
| `logic_type` | string | Such as `join`, `filter`, `aggregate`, `group_by`, `window`. |
| `raw_expression` | string/null | The expression close to the original SQL. |
| `normalized_expression` | string/null | A normalized expression for comparison and search. |
| `fingerprint` | string/null | A dedup fingerprint formed from the type plus the normalized expression. |
| `fields[]` | array<object> | Fields the expression references directly; elements carry at least `scope` and `column`. |
| `output_fields[]` | array<string> | The scope output fields this logic produces or affects. |
| `input_sources[]` | array<string> | The input scopes/physical tables the logic involves. |
| `field_usage[]` | array<object> | Which logic block and which output use a field. |
| `expression_features` | object | Functions, operators, and boolean features such as CASE/CAST/window/aggregate/UDF. |
| `final_target_columns[]` | array<string> | The target fields this logic ultimately affects. |

Different logic types also carry dedicated details:

| Detail key | Content |
| --- | --- |
| `join_relation_detail` | `join_type`, `join_key_pairs[]`, `condition_filters[]`, `trace_status`, `missing_reasons[]`. Distinguishes true join keys from extra filters inside ON. When the join reads the statement's own target table it also carries `target_self_reference` — the referencing alias, and, when both the target partition and the reference's partition predicate are literal dates, the provable day offset (`partition_offset_days`, `offset_proven: true`); anything less stays `offset_proven: false` rather than guessed. A negative offset is the classic carry-forward shape — the tool states the offset, the consumer names the pattern. |
| `filter_predicate_detail` | The `conjuncts[]` a WHERE/HAVING condition breaks down into, field resolution, subquery dependencies, and partition-filter judgments. |
| `aggregation_detail` | `group_by_items[]`, `aggregate_items[]`, `having`, and the expression source of each item. |
| `window_specification` | The window function, `partition_by[]`, `order_by[]`, post-window filtering, and trace status. |

For example, the same `customer_id` serves different purposes as a JOIN key, a WHERE filter, and a
SELECT output; `logic_blocks` preserves that context instead of flattening them into one
semantics-free field set.

## 8. `outputs[]`: scope output fields

A typical output field:

```json
{
  "name": "paid_amount_30d",
  "output_ordinal": 2,
  "transform": "AGGREGATE",
  "expression": "SUM(CASE WHEN pay_status = 'PAID' THEN pay_amount ELSE 0 END)",
  "expanded_expression": "SUM(CASE WHEN `dwd.order_detail`.`pay_status` = 'PAID' THEN `dwd.order_detail`.`pay_amount` ELSE 0 END)",
  "expression_type": "aggregate_expression",
  "expression_role": "metric_calculation",
  "grain_effect": "changed",
  "sources": [
    {"scope": "dwd.order_detail", "column": "pay_status"},
    {"scope": "dwd.order_detail", "column": "pay_amount"}
  ],
  "source_logic_blocks": ["logic:cte:order_summary:aggregate:002"],
  "downstream_fields": [{"scope": "ROOT", "column": "paid_amount_30d"}],
  "final_target_columns": ["mart.customer_profile_snapshot.paid_amount_30d"],
  "consumer_readiness": {"status": "ready", "blocked_reasons": []}
}
```

Main keys:

| Key | Meaning |
| --- | --- |
| `name` | The output name in this scope. |
| `output_ordinal` | Zero-based output position; with duplicate field names or several MERGE branches, name alone is not enough to tell them apart. |
| `transform` | Coarse-grained transform: `DIRECT`, `EXPRESSION`, `AGGREGATE`, `WINDOW`, `CONDITIONAL`, `CONSTANT`, `UNION`, `EXPAND_ALL`. |
| `expression` | The SQL expression in this scope. |
| `expanded_expression` | The expression expanded to physical-source qualified names as far as possible. |
| `expression_resolution` | Resolution status, physical/generated/row-set sources, missing reasons, and cross-scope trace. |
| `expression_type` | Structural type such as direct, conditional, aggregate, window, arithmetic, constant, UDF. |
| `expression_role` | Purpose such as direct projection, standardization, cleaning, metric calculation, record selection. |
| `grain_effect` | `preserved`, `changed`, `may_change`, or `unknown`. |
| `sources[]` | Direct input fields; may carry a qualifier, binding scope, and input ref. |
| `source_logic_blocks[]` | The IDs of the logic blocks that produce this field. |
| `downstream_fields[]` | Downstream scope fields consuming this output. |
| `target_columns[]` / `final_target_columns[]` | The current target and the final physical target fields. |
| `consumer_readiness` | Whether the facts needed for safe downstream consumption are present; lists reasons when blocked. |
| `merge_branch` / `merge_when_index` | Which WHEN branch a field belongs to in a MERGE. `merge_branch` is **absent** on `WHEN NOT MATCHED BY SOURCE` (see §7); `merge_when_index` is always given. |
| `merge_branch_qualifier` | The kind of WHEN clause the enum cannot name; currently only `not_matched_by_source`. Absent on the two branches the enum does name. |

### `SELECT * EXCEPT (...)`

The star's exclusion list **is applied**: excluded columns appear on no output surface
(`columns[]` / `outputs[]` / `field_mapping_chains[]` / `end_to_end_lineage[]` /
`related_metadata`).

Two things to watch:

- Exclusion changes the **number** of projections, while target-DDL binding is positional. When the post-exclusion projection count matches the target column count, binding is enabled; when it does not, the whole thing degrades to fallback. Both changes are corrections — the extra column that used to be there was previously treated as a real output column and took part in binding.
- Spark syntax allows only one star modifier, `EXCEPT`. `REPLACE` / `RENAME` / `ILIKE` are other engines' constructs; the tool does not model them and only raises a `star_modifier_not_supported` warning.


### 8.1 Aggregated STRUCT member projection

When an upstream output selects a STRUCT via `MAX/MIN(STRUCT(...))` or
`MAX/MIN(NAMED_STRUCT(...))` and a downstream expression then accesses one of its members,
`expanded_expression` preserves the aggregate and the member projection; it must not be flattened
into a plain leaf field. For example:

```sql
MAX(NAMED_STRUCT(
  'update_time', `ods.layer`.`update_time`,
  'layer_name', `ods.layer`.`layer_name`
)).layer_name
```

Its output must preserve all of:

- the complete `MAX(NAMED_STRUCT(...)).layer_name` transformation semantics;
- `update_time` as a row-selection/comparison input;
- `layer_name` as both the returned value and a comparison input;
- the `scope_output_trace` from the outer output back to the upstream aggregate output.

Plain non-aggregated STRUCT member access can still be expanded to the selected leaf field. The
distinction prevents consumers from misreading "take a field from an aggregate-selected STRUCT" as
a plain direct projection.

### 8.2 Field classification enums

`transform` is the compatible coarse-grained classification:

| Value | Meaning |
| --- | --- |
| `DIRECT` | A direct field projection. |
| `EXPRESSION` | Derived by a plain expression. |
| `AGGREGATE` | An aggregate expression. |
| `WINDOW` | A window expression. |
| `CONDITIONAL` | A CASE WHEN / IF conditional expression. |
| `CONSTANT` | A constant or system-generated value. |
| `UNION` | An output after UNION positional alignment. |
| `EXPAND_ALL` | A placeholder when `SELECT *` or `alias.*` was not fully expanded. |

#### `WINDOW` mixes three roles — do not treat them as the same dependency

The sources of a window field are all marked `transform: WINDOW`, but their effect on the
resulting value differs completely:

| Role | In `SUM(amt) OVER (PARTITION BY id ORDER BY dt)` | Decides the value? |
| --- | --- | --- |
| Value argument | `amt` | Yes |
| Partition key | `id` | No, it only decides which group the row falls into |
| Order key | `dt` | No, it only decides the order within the group |

All three columns appear in `sources[]` with `transform: "WINDOW"`. So when a window partitions by
many columns, all of those columns become sources too — **this is a faithful record**: replace any
partition column and the grouping changes, and the window result may change with it.

The roles are persisted, but they hang off **the column that defines the window**, not off the
downstream field. `columns[].window` gives `partition_by[]` and `order_by[]`, and only the column
whose `transform` is `WINDOW` has that structure.

To decide which of a downstream field's sources are window context, walk up `sources[]` to the
column that carries `window`:

```
ROOT.begin_date        transform=EXPRESSION       ← only 1 direct source at this level
  └ subq:s2.start_dt   DIRECT
     └ subq:s1.start_dt   EXPRESSION              ← date_add(dt, rn - 1)
        ├ subq:s0.dt   DIRECT                     ← value source
        └ subq:s0.rn   WINDOW   window={partition_by[15], order_by[1]}
```

`rn`'s 15 `partition_by` columns and 1 `order_by` column are **context**; the real value source of
`start_dt` is `dt`. Note that `begin_date` has only one direct source at this level — those 16
context columns only appear once `end_to_end_lineage` flattens the whole chain.

Windows such as `row_number()` and `rank()` have no value argument; their value is "decided
entirely by partitioning and ordering". The value source of such a downstream field must be found
in the expression outside the window — in the example above that is the `dt` inside `date_add(...)`,
which appears as `DIRECT`/`EXPRESSION` rather than `WINDOW`.

This is a convention, not a defect: partition keys really do affect the result, Core records that
faithfully, and the consumer separates "where the value comes from" from "what the grouping/ordering
context is".

`expression_type` offers a structural classification better suited to new consumers:

| Value | Meaning |
| --- | --- |
| `direct_projection` | A direct field projection. |
| `conditional_expression` | CASE WHEN / IF. |
| `type_cast` | CAST or a type conversion. |
| `function_expression` | Plain functions such as COALESCE, TRIM, SUBSTR. |
| `aggregate_expression` | Aggregates such as SUM, COUNT, AVG, MIN, MAX. |
| `window_expression` | Window expressions such as ROW_NUMBER, RANK. |
| `arithmetic_expression` | Arithmetic derivation such as +, -, *, /. |
| `constant_expression` | A constant or system-value expression. |
| `udf_expression` | A non-builtin function or UDF. |
| `unknown_expression` | Cannot currently be classified stably. |

`expression_role` states the expression's purpose in data processing:

| Value | Meaning |
| --- | --- |
| `direct_projection` | Referenced as is. |
| `field_derivation` | Generic field derivation. |
| `standardization` | Code, status, or format standardization. |
| `cleaning` | Null, outlier, or text cleaning. |
| `type_conversion` | Type conversion. |
| `metric_calculation` | Metric computation. |
| `record_selection` | Record-selection helpers such as dedup or ordered picking. |
| `constant_fill` | Constant fill. |
| `unknown` | Purpose cannot be judged stably from the structure. |

`grain_effect` states the expression's local effect on row grain:

| Value | Meaning |
| --- | --- |
| `preserved` | The expression itself does not change detail grain. |
| `changed` | An aggregate or similar behavior has already changed the grain. |
| `may_change` | A window/dedup or similar behavior may affect record selection. |
| `unknown` | Current evidence is insufficient. |

Do not consume `transform` alone. For field explanations, prefer the combination of
`expression_type`, `expression_features`, `expression_role`, and `grain_effect`; judging the grain
of the whole model additionally requires looking at GROUP BY, windows, DISTINCT, and the scope
context.

### 8.3 `field_usage[]`: how input fields are used

```json
{
  "source_id": "dwd.order_detail",
  "source_type": "physical_table",
  "used_fields": ["customer_id", "order_id", "pay_amount"],
  "used_field_details": [
    {"name": "pay_amount", "type": "decimal(18,2)", "comment": "Paid amount"}
  ],
  "used_by_logic_blocks": ["logic:cte:order_summary:aggregate:002"],
  "used_by_output_fields": ["paid_amount_30d"],
  "source_metadata": {}
}
```

| Key | Meaning |
| --- | --- |
| `source_id` / `source_type` | The identity and type of the direct input scope/physical table. |
| `used_fields[]` | The field names this scope actually uses. |
| `used_field_details[]` | Schema details such as field type and comment, when available. |
| `used_by_logic_blocks[]` | Which logic blocks read those fields. |
| `used_by_output_fields[]` | Which scope output fields use those fields directly. |
| `source_metadata` | Generic source metadata available to Core; an empty object when there is no input. |

It suits questions like "is this field of this table a JOIN key, a filter field, or an input to an
output expression in this query block". Cross-scope final-target impact should still use the
mapping chain or end-to-end lineage.

### 8.4 `columns[]`: the compatibility parse view

`columns[]` is closer to the parser's raw column model and usually contains `name`, `transform`,
`expression`, and `sources[]`, and may keep transform-specific extras such as `agg_function`,
`case_branches`, `window`, or UNION branches.

New consumers should prefer `outputs[]`, which adds expression resolution, logic-block references,
downstream fields, final targets, and consumer readiness. `columns[]` is mainly for:

- compatibility with earlier consumers;
- debugging the parser's raw column resolution;
- inspecting extra structures specific to certain transforms.

When target-field binding succeeds, ROOT `columns[]` may also contain `parsed_name`,
`target_column_ordinal`, `target_field_resolution`, `target_field_corrected`, and
`target_metadata_table`, with the same semantics as the identically named audit keys in the
end-to-end fields.

## 9. `field_mapping_chains[]`: step-by-step field transformation chains

This is the main evidence for "why this end-to-end lineage came out".

```json
{
  "mapping_chain_id": "mc:001",
  "chain_id": "chain:ROOT:customer_id:position:0",
  "chain_type": "field_mapping",
  "target_scope_id": "ROOT",
  "target_field": "customer_id",
  "target_position": 0,
  "chain_status": "resolved",
  "root_source_fields": ["ods.customer_base.customer_id"],
  "final_output_fields": ["mart.customer_profile_snapshot.customer_id"],
  "ordered_steps": [
    {
      "step_no": 1,
      "scope_id": "ROOT",
      "step_type": "direct_projection",
      "input_fields": ["ods.customer_base.customer_id"],
      "output_field": "mart.customer_profile_snapshot.customer_id",
      "expression_sql": "`base`.`customer_id`",
      "expanded_expression": "`ods.customer_base`.`customer_id`",
      "transform": "DIRECT",
      "grain_effect": "preserved"
    }
  ],
  "missing_reasons": [],
  "trace_status": "complete"
}
```

Key consumption rules:

- `ordered_steps[]` expresses, by `step_no`, the transformation order from upstream to target;
- `root_source_fields[]` contains only proven root physical fields;
- when `trace_status=incomplete`, look at `missing_reasons[]` and do not treat the chain as complete evidence;
- `target_position` distinguishes same-named outputs and preserves INSERT positional semantics.

## 10. `end_to_end_lineage[]`: final field lineage

Each element corresponds to one final output position:

| Key | Value | Meaning |
| --- | --- | --- |
| `column` | string | The final target field name after binding. |
| `parsed_column` | string | The original SQL projection name; differs from `column` when the target DDL corrected the field name. |
| `name_is_generated` | boolean | Present only when true: `column` is a parser-generated placeholder name (e.g. `_col_6`, an anonymous projection in the SQL) that no target metadata bound — consumers must not treat it as a real column name. Once binding renames it to a real target field the key is absent, and the original placeholder stays visible via `parsed_column`. The same key with the same semantics appears on field mapping chains, whose `target_field` publishes the same name. |
| `output_ordinal` / `target_column_ordinal` | integer | The SQL output position and the target field position. |
| `target_field_resolution` | enum string | `ddl_position`, `schema_position`, or `insert_column_list`. |
| `target_field_corrected` | boolean | Whether the SQL projection name was corrected using target metadata. |
| `target_metadata_table` | string | Which target-table metadata was used. |
| `transform` | string | The final field's coarse-grained transform type. |
| `expression` | string/null | The final projection expression. |
| `trace_complete` | boolean | Whether it has been traced to a definite source. |
| `trace_incomplete_reasons[]` | array<string> | Reasons for incompleteness. |
| `physical_sources[]` | array<object> | Proven `{table, column, transform}` physical sources. |
| `generated_sources[]` | array<object> | Non-physical field sources such as constants and system values. |
| `rowset_sources[]` | array<object> | Window or row-set-level semantic sources. |
| `source_kind` | enum string | `physical`, `generated`, `mixed`, `rowset`, or `unresolved`. |
| `ambiguities[]` | array<object> | Positions where a source cannot be chosen uniquely, and the candidate chains. Candidates are not proven sources. |

### 10.1 Physical, generated, and row-set sources

- `physical_sources`: real table fields, e.g. `ods.customer.customer_id`;
- `generated_sources`: constants, NULL, system values, e.g. a fixed string label;
- `rowset_sources`: sources such as window functions that depend on a set of rows rather than a single field;
- `mixed`: depends on several kinds of source at once.

### 10.2 Ambiguity must not be merged into fact

When `trace_complete=false` and `ambiguities[]` is present:

```json
{
  "column": "id",
  "trace_complete": false,
  "trace_incomplete_reasons": ["ambiguous_unqualified"],
  "physical_sources": [],
  "ambiguities": [
    {
      "scope": "ROOT",
      "column": "id",
      "candidate_count": 2,
      "candidates": [
        {"scope": "ods.customer", "column": "id", "trace_complete": true},
        {"scope": "ods.order", "column": "id", "trace_complete": true}
      ]
    }
  ]
}
```

Downstream must not write both candidates into `physical_sources`, and must not pick one
arbitrarily. The correct behavior is to preserve the ambiguous state and, together with
`diagnostics.json`, request a Schema, an alias, or a SQL fix.

Cross-layer consistency guarantee: a field mapping chain whose `root_source_fields`
contains `AMBIGUOUS.<column>` always has `trace_status: "incomplete"` (with
`ambiguous_unqualified:<column>` in `missing_reasons`), matching this section's
`trace_complete=false` — even when the chain's expression expansion happens to resolve
a single physical source. That result is a product of qualification inference, not a
proven attribution, and the chain layer must not declare completeness from it.

## 11. `target_field_binding`: positional target-field binding

When `--target-ddl-metadata` is provided, the SQL's Nth projection can bind to the Nth
non-static-partition field of the target DDL/Schema:

| Key | Meaning |
| --- | --- |
| `status` | `applied`, `fallback`, or `not_applied`. |
| `method` | `ddl_position`, `schema_position`, `insert_column_list`, or `sql_projection`. |
| `metadata_table` / `metadata_source_file` | The target metadata used and its source file. |
| `projection_count` | The number of SQL projections. |
| `target_column_count` | The number of bindable target fields. |
| `corrected_column_count` | How many field names the target metadata corrected. |
| `static_partition_columns[]` | Static partition columns already given values in the SQL; they occupy no SELECT projection slot. |
| `dynamic_partition_columns[]` | Dynamic partition columns whose values must come from the SELECT projection. |
| `issues[]` | Why binding could not be applied or was degraded. |

Its value is preventing `SELECT expr AS temporary_alias` from being mistaken for the final target
field name, while preserving the correction evidence.

## 12. `task_dependencies` and `related_metadata`

### 12.1 `task_dependencies`

```json
{
  "upstream_tasks": [
    {
      "dependency_id": "taskdep:upstream:001",
      "direction": "upstream",
      "task_id": "task-1001",
      "task_name": "order_detail_daily",
      "dependency_type": "declared",
      "dependency_table": null,
      "source": "task_info.meta.upstream_tasks",
      "source_file": "customer_profile_daily.json",
      "raw_record": {}
    }
  ],
  "downstream_tasks": [],
  "source_summary": {
    "source_format": "task_info_meta",
    "upstream_count": 1,
    "downstream_count": 0,
    "has_declared_task_dependencies": true
  }
}
```

These task dependencies come from declarations in the input task JSON; they are not the same thing
as table dependencies derived by parsing SQL. A knowledge graph can build "task dependency edges"
and "table/field lineage edges" separately. `source_file` is provenance without machine identity:
the basename for a single task file, or a POSIX-style path relative to the batch input root.

### 12.2 `related_metadata`

- `input_tables`: keys are input table names, values contain `column_details[]` (the
  **used** field subset for this task, not the full table; empty for a table referenced
  only through row-set dependencies such as `COUNT(*)`), field types/comments,
  `metadata_complete`, and `table_column_count` (the table's **full width** in the
  supplied schema, absent when the schema does not know the table — this is what lets a
  reader tell "a few columns used" apart from "the table's full width");
- `output_tables`: keys are target table names, values are the corresponding target metadata;
- `metadata_complete`: whether the metadata the caller supplied covers the known fields — not a claim that the real catalog is always complete.

Source refs (`scopes[].columns[].sources` and similar) carry an additional `rowset` key,
present only when true: the `column="*"` ref is a **row-set dependency** (`COUNT(*)`,
`ROW_NUMBER()` — expressions that read zero columns), not "all columns flow"; the latter
is the unexpandable-`SELECT *` fallback star, which carries no such key. Consumers must
not count a `rowset`-marked star as column usage.

## 13. `scope_profile`: a deterministic summary suited to AI retrieval

Each item of `scope_profile.steps[]` contains:

| Key | Meaning |
| --- | --- |
| `scope_id` / `name` / `kind` / `role` | Query-block identity and structural role. |
| `operations[]` | The operations that occur in this scope, such as `join`, `filter`, `aggregate`, `window`. |
| `direct_inputs[]` | The scopes or physical tables that are direct inputs. |
| `direct_source_tables[]` | The physical tables this scope reads directly. |
| `physical_source_tables[]` | Every physical table involved after passing through upstream scopes. |
| `output_columns` | The number of output fields. |
| `logic` | A concise structure of joins, filters, aggregations, window functions, CASE, DISTINCT, UNION, and so on. |
| `business_summary` | A deterministic summary generated from structural templates; it must not be taken as a complete business definition. |

For RAG, index `scope_profile` and `end_to_end_lineage` first, and load the full `scopes` only
after a task is matched — that keeps the context small.

## 14. `diagnostics`: the quality summary inside lineage

```json
{
  "fallback_used": false,
  "warning_count": 3,
  "warning_types": {"magic_number": 1, "filter_in_join_on_clause": 1},
  "lineage_fact_gap_count": 0,
  "lineage_fact_gap_types": {},
  "lineage_fact_gap_samples": [],
  "stats": {"scope_count": 6, "join_count": 2},
  "full_diagnostics_file": "diagnostics.json"
}
```

It is only for quick filtering. For the complete warnings and every fact gap, read
[`diagnostics.json`](diagnostics-json.md) in the same directory.

## 15. Common scenarios and reading paths

| Scenario | Suggested reading |
| --- | --- |
| Table-level impact analysis | `source_tables`, `target_table` |
| Field-level impact analysis | `end_to_end_lineage[].physical_sources`, `column` |
| Explaining how a metric is computed | ROOT `outputs[]` → `field_mapping_chains[]` → the related `logic_blocks[]` |
| Finding where a field is filtered | `scopes.*.logic_blocks[logic_type=filter].fields[]` |
| Finding JOIN keys | `logic_blocks[].join_relation_detail.join_key_pairs[]` |
| Deciding whether grain changes | `outputs[].grain_effect`, `aggregation_detail`, `window_specification` |
| Building a knowledge graph | scope graph + task dependencies + end-to-end physical source edges |
| Building a task summary for an Agent | `scope_profile` + `end_to_end_lineage` + diagnostics summary |
| Answering "why is this uncertain" | `trace_incomplete_reasons`, `ambiguities`, `diagnostics.json.lineage_fact_gaps` |

## 16. Query examples

List target fields and their physical sources:

```bash
jq -r '.end_to_end_lineage[] |
  [.column, (.physical_sources | map(.table + "." + .column) | join(",")), (.trace_complete|tostring)] |
  @tsv' lineage.json
```

List every scope and its direct dependencies:

```bash
jq -r '.scopes | to_entries[] | [.key, .value.kind, (.value.depends_on|join(","))] | @tsv' lineage.json
```

List every filter expression:

```bash
jq -r '.scopes | to_entries[] as $scope |
  $scope.value.logic_blocks[]? |
  select(.logic_type == "filter") |
  [$scope.key, .logic_block_id, .raw_expression] | @tsv' lineage.json
```

Consume and validate from Python:

```python
import json
from pathlib import Path

from scope_lineage import validate_lineage_document

document = json.loads(Path("lineage.json").read_text(encoding="utf-8"))
validate_lineage_document(document)

for field in document["end_to_end_lineage"]:
    if not field["trace_complete"]:
        continue
    sources = [f'{item["table"]}.{item["column"]}' for item in field["physical_sources"]]
    print(field["column"], sources)
```

Beyond the JSON Schema shape check there are two more validation layers, answering
different questions:

- `validate_cross_references(document)`: does every referenced id exist (returns a list
  of violations);
- `validate_contract_invariants(document)`: **do independently derived views of the same
  fact agree with each other** — chain-layer vs end-to-end trace completeness, physical
  sources vs `source_tables` containment, sentinel-value semantics. Defects where every
  layer looks individually plausible but the conjunction is contradictory (such as an
  AMBIGUOUS-rooted chain claiming completeness) are only caught here.

The CLI runs all three layers in one pass, auditing existing artifacts on disk:

```bash
scope-lineage validate --lineage /path/to/corpus
```

Every violation is printed and the command exits non-zero when any is found.

## 17. Safe consumption rules

1. Check `schema_version`, `parse_status`, and `syntax_status` first;
2. when `parse_status=failed`, an empty `scopes` does not mean the SQL has no lineage;
3. when `syntax_status=recovered`, the recovery risk must be surfaced;
4. fields with `trace_complete=false` must not enter the "proven lineage" set;
5. `ambiguities[].candidates` are candidates, not multi-source facts;
6. `generated_sources` must not be disguised as physical table fields;
7. without a Schema, `SELECT *` may keep an `EXPAND_ALL`/`*` degraded representation;
8. a full quality judgment must pair this with the `diagnostics.json` from the same run;
9. 1.x consumers must tolerate newly added optional fields; removal, renaming, or a semantic change requires a major bump.

Before writing, Core runs JSON Schema and cross-reference validation: dangling scopes, fields, or
graph edges are never published as a successful artifact.
