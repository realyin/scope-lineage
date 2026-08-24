[中文](../zh-CN/diagnostics-json.md) | English

# The `diagnostics.json` output contract and field reference

This page describes **statement-level** diagnostics (the `schema_version: "1.0"` shape). Since
0.2.0 the diagnostics.json written out is the task-level aggregate (`schema_version: "2.0"`):
aggregated per task and containing `analysis_status`, `metadata_coverage`, and
`statement_diagnostics.<statement_id>` — where each entry is exactly the statement-level shape
described here; see
[Task Lineage 2.0](task-lineage-v2.md) and
`scope_lineage/schemas/diagnostics-v2.schema.json`.

## 1. What problem it solves

Static SQL analysis cannot produce a unique, complete answer on every input. Common reasons
include:

- `SELECT *` with no Schema, so the actual field set is unknown;
- same-named fields from several JOIN inputs, with no qualifier in the SQL;
- an alias not bound to a unique input;
- an upstream scope that does not output the referenced field;
- platform SQL that used recovered parsing or custom syntax;
- an expression resolved only as far as a logical scope, with the final physical source not yet proven.

`diagnostics.json` exists to record these boundaries. It lets downstream distinguish:

- **proven facts**: safe to enter a knowledge graph and automated impact analysis;
- **usable, with a caveat**: lineage exists, but it deserves governance or human attention;
- **fact gaps**: no definite conclusion can be produced; SQL, Schema, alias, or parser capability must be supplied.

It comes from the same parse as the `lineage.json` beside it and must be consumed as a pair.

Authoritative Schema:

```text
scope_lineage/schemas/diagnostics.schema.json
```

## 2. Top-level keys and values

| Key | Value type | Required | Meaning |
| --- | --- | --- | --- |
| `schema_version` | string | Yes | Fixed at `1.0` for the statement-level shape. |
| `fallback_used` | boolean | No | Whether a degraded parse path was used; absent is equivalent to `false`. It does not mean "the result must be wrong", but it does require checking the warnings and the lineage status. |
| `warnings` | array<object> | No | The complete warning list; absent or an empty array means there are no warnings. |
| `stats` | object | No | SQL structure statistics, for complexity indexing and quality observation. |
| `lineage_fact_gaps` | array<object> | No | The complete list of gaps where no definite lineage fact could be formed. |

A minimal file for a successful parse with no warnings and no gaps can be just:

```json
{
  "schema_version": "1.0",
  "stats": {
    "scope_count": 2,
    "physical_table_count": 1
  }
}
```

An absent optional key means the same as an empty value. For instance, no `warnings` does not mean
the file failed to generate.

## 3. `warnings[]`: reminders and governance signals

Every warning contains at least:

| Key | Value | Meaning |
| --- | --- | --- |
| `type` | string | A stable, machine-groupable type. |
| `scope` | string | The scope ID where the warning occurred; global problems may use a special identifier. |
| `msg` | string | A human-facing evidence statement, usually containing the relevant field or expression fragment. |

Example:

```json
{
  "type": "star_not_expanded",
  "scope": "ROOT",
  "msg": "SELECT * could not be expanded: no schema; missing_schema_sources=ods.raw_events"
}
```

### 3.1 Warnings versus fact gaps

- a warning means "pay attention" and does not necessarily break field lineage;
- a fact gap means some source fact was not proven, and downstream automation must be limited;
- one task can have warnings and no fact gaps. A magic number, for instance, does not stop a field's source from being traced;
- `star_not_expanded` reduces field completeness, but table-level sources may still be valid.

### 3.2 Common warning types

The actual set grows through 1.x, so consumers should tolerate new type strings. Common types
include:

| Type | Description | Suggested action |
| --- | --- | --- |
| `star_not_expanded` | Schema is missing or the source columns cannot be determined, so `SELECT *` was not expanded. | Supply source-table Schema; do not count field-level coverage as complete. |
| `star_except_column_not_found` | `SELECT * EXCEPT (...)` excludes a column that this star does not produce. sqlglot accepts this; Spark fails analysis. | Fix the SQL; the statement will not run on Spark, and lineage is produced as if the exclusion had no effect. |
| `star_modifier_not_supported` | The star carries `REPLACE` / `RENAME` / `ILIKE`. Spark syntax allows only `EXCEPT` (`SqlBaseParser.g4`: `ASTERISK exceptClause?`); the rest are other engines' constructs, which sqlglot's base parser accepts indiscriminately. | Fix the SQL; the tool does not model these modifiers and expands as if none were present. |
| `star_modifier_not_applied` | The star carries `EXCEPT`, but the star itself could not be expanded (no Schema), so the exclusion could not be applied. | Supply source-table Schema; the placeholder column stands for "all columns", including the ones that should have been excluded. |
| `unresolved_alias` | An expression qualifier is not bound to an input. | Check the SQL alias, custom syntax, or parser support. |
| `duplicate_alias` | An alias is reused within one scope, so field sources may be ambiguous. | Fix the SQL, or disambiguate using field/Schema evidence. |
| `column_not_found` | The field is in none of the known sources. | Check the field name and Schema completeness. |
| `ambiguous_unqualified` | An unqualified field matches several inputs. | Add a qualifier in the SQL; a source must not be chosen arbitrarily. |
| `merge_delete_ignored` | `WHEN ... THEN DELETE` is a row-level operation and produces no `ROOT` output field; `msg` states whether it came from the `MATCHED` or the `NOT MATCHED BY SOURCE` branch. | No action needed; do not count that branch as missing in field-level coverage. |
| `merge_branch_not_representable` | This write comes from `WHEN NOT MATCHED BY SOURCE` — the third of Spark's three WHEN clauses, while contract 1.0's `merge_branch` enum names only two. | Read `merge_branch_qualifier` for the clause kind; do not read an absent `merge_branch` as "this is not a MERGE write" (the statement kind is in the top-level `stmt_kind`). |
| `identifiers_quoted_for_parse` | A column name collides with a SQL keyword (such as `not`, `like`, `out`, `using`) and was unquoted in the original, so the tool added backticks to those identifiers to complete the parse; `msg` lists every identifier it quoted. | No action needed, lineage is normal. Consider quoting those column names in the source SQL rather than relying on the tool's repair. |
| `session_scoped_relations_present` | This script produced relations that live only for the session and are never stored (`TEMP VIEW` / `GLOBAL TEMP VIEW` / `CACHE [LAZY] TABLE`); `msg` lists every such relation name. | Before reconciling against the catalog, exclude these relations from `final_table_states` and from table-level coverage counts; the field lineage itself is valid, and both hops are preserved separately. |
| `filter_in_join_on_clause` | A JOIN ON contains row filtering such as a constant comparison. | When explaining the logic, distinguish join keys from condition filters. |
| `magic_number` | An expression contains an unexplained numeric constant. | Ask for the definition when generating upper-layer business knowledge. |
| `complex_aggregate_with_case` | A CASE is nested inside an aggregate. | A metric explanation should keep the CASE branches, not just record SUM/COUNT. |
| `duplicate_table_in_union` | The same physical table is a **FROM/JOIN source** of several UNION branches. Being read only by a branch's filtering subquery (such as `NOT EXISTS`) does not count. | Confirm whether a branch was copied without changing its source; anti-join deduplication is a normal pattern and no longer triggers this. |
| `target_field_binding_fallback` | Authoritative target-field binding was not fully applied. | See `lineage.json.target_field_binding.issues[]`. |

Warnings are not a fixed closed enum; machine processing should set policies for known types and
preserve and display unknown ones.

## 4. `stats`: parse structure statistics

The statistics the public Core currently emits:

| Key | Value | Meaning and value |
| --- | --- | --- |
| `scope_count` | integer | Total size of logical scopes plus physical source nodes. |
| `physical_table_count` | integer | Number of physical input tables. |
| `cte_count` | integer | Number of CTEs. |
| `subquery_count` | integer | Number of subqueries. |
| `union_count` | integer | Number of UNION scopes. |
| `union_branch_count` | integer | Number of UNION branches. |
| `max_depth` | integer | Maximum depth of scope dependencies. |
| `case_when_count` | integer | Number of CASE WHENs. |
| `window_function_count` | integer | Number of window functions. |
| `join_count` | integer | Number of JOINs. |
| `aggregate_function_count` | integer | Number of aggregate functions. |

These values can drive retrieval ranking and complexity bucketing — for example, having an Agent
analyze tasks with high `max_depth` and many JOINs/UNIONs first; they cannot on their own prove SQL
risk or business importance.

## 4.5 Read `metadata_coverage` before `lineage_fact_gaps`

> **This section applies to contract 2.0 only.** A v1 `diagnostics.json` has only
> `schema_version`, `warnings`, `stats`, and (when gaps exist) `lineage_fact_gaps` — it has
> **no** `metadata_coverage` and no `analysis_status`; looking for those two keys in a v1 artifact
> finds nothing. Under v1, to judge "is this gap caused by metadata", read
> `related_metadata.input_tables[*].metadata_complete` in `lineage.json`.

**This is the required order for reading a 2.0 diagnostics document, not a suggestion.**

Field-level gaps do not distinguish causes: the tool being unable to parse some SQL, and this run
simply never receiving the source table's columns, produce records that **look exactly alike**
(`missing_reasons: ["no_physical_source_fields"]`). When you prioritize by gap count, the second
kind completely drowns the first.

So when a **source table** is missing column metadata, the artifact says so outright in two places:

- `metadata_incomplete` appears in `analysis_status.blocking_reasons`, and **ahead of `lineage_fact_gap`** — cause first, symptom second;
- `warnings[]` carries one entry of `type: "metadata_incomplete"` naming the source tables that are missing.

When you see `metadata_incomplete`, **the field-level gaps in this document must not be counted as
tool capability gaps**; supply the metadata and rerun first.

> Only source tables are counted. A target table having no schema entry is normal (target DDL is
> passed separately via `--target-ddl-metadata`), and it cannot possibly be the cause of a
> source-side reference failing to resolve — counting it would pin a metadata label on gaps that
> have nothing to do with metadata.

Without this distinction, a run missing all source metadata can produce many field-level gaps while
`blocking_reasons` says only `lineage_fact_gap`; downstream reports then misread missing input as
insufficient parser capability. With the metadata supplied, those gaps disappear.

To confirm whether a batch of gaps is caused by missing metadata, the fastest test is: run the same
SQL again with `schema=None`, and if the gap count and distribution match this run, the metadata
did not take effect this run.

## 5. `lineage_fact_gaps[]`: unproven facts

The Schema keeps the gap value extensible, because different parse gaps need to carry different
evidence. The common fields Core currently generates are:

| Key | Value | Meaning |
| --- | --- | --- |
| `gap_id` | string | An in-document unique ID such as `lineage_gap:0001`. |
| `gap_type` | string | The gap's major category. |
| `gap_bucket` | string | A processing bucket by expression shape or binding stage. |
| `gap_sub_bucket` | string | A more specific gap subcategory. |
| `scope_id` | string | The scope the problem is in. |
| `object_type` | string | The affected object, such as `output`, `output.union_branch_mapping`, or `aggregation_detail.aggregate_items`. |
| `object_name` | string | The affected field or expression name. |
| `expression_sql` | string/null | The expression whose source could not be fully resolved. |
| `expression_resolution_status` | string | Expression resolution status, such as unresolved or partially resolved. |
| `source_kind` | string | The current source category; usually `unresolved` when undetermined. |
| `missing_reasons[]` | array<string> | The direct reasons the parser observed. |
| `needed_fact` | string | The fact that must be supplied to close the gap. |
| `root_impact` | boolean | Whether it affects a final target field. |
| `owner_hint` | string | Whether parser fact backfill, internal completion, or review is suggested. |
| `evidence_path` | string | A path to the corresponding fact in `lineage.json`. |
| `evidence_summary` | object | A summary such as the scope's input count, candidate sources, and target impact. |
| `downstream_impact` | object | The affected scope outputs and final target fields. |
| `derived_from_recovered_syntax` | boolean (optional) | Appears only when `syntax_status = "recovered"`, always `true`. It means this gap came from a repaired parse — the parser dropped tokens it could not place, and the gap describes **the truncation itself**, not a fact about this SQL. Exclude these first when counting capability gaps. The only reliable conclusion here is "this statement did not parse", and you should go back to the SQL itself; exclude these tasks when counting capability gaps. |

Example:

```json
{
  "gap_id": "lineage_gap:0001",
  "gap_type": "alias_binding_missing",
  "gap_bucket": "alias_binding",
  "gap_sub_bucket": "alias_binding_unresolved",
  "scope_id": "ROOT",
  "object_type": "output",
  "object_name": "customer_id",
  "expression_sql": "x.customer_id",
  "expression_resolution_status": "unresolved",
  "source_kind": "unresolved",
  "missing_reasons": ["alias_not_bound_to_input_source:x"],
  "needed_fact": "input alias to source binding",
  "root_impact": true,
  "owner_hint": "parser_fact_backfill",
  "evidence_path": "lineage.scopes.ROOT.outputs[0]",
  "evidence_summary": {
    "has_target_impact": true,
    "scope_input_count": 2,
    "candidate_source_ids": ["ods.customer", "ods.order"],
    "candidate_output_fields": [],
    "expression_ref_count": 1
  },
  "downstream_impact": {
    "output_fields": ["customer_id"],
    "target_columns": ["mart.customer_summary.customer_id"]
  }
}
```

### 5.1 `gap_type`

| Type | What is missing |
| --- | --- |
| `alias_binding_missing` | The binding from an alias to an input scope/table. |
| `scope_output_mapping_missing` | The mapping from an upstream scope's output field to the current reference. |
| `expression_source_unresolved` | The expression's physical or generated source. |
| `expression_resolution_incomplete` | Some sources are known, but the expression resolution is not yet complete. |
| `expression_expansion_bounded` | Source facts are known, but full expression text was not inlined because an expansion guard was reached; continue through `evidence_summary.unexpanded_refs`. |

### 5.2 `gap_bucket`

| Bucket | Typical problem |
| --- | --- |
| `alias_binding` | A qualifier has no corresponding input. |
| `upstream_output_mapping` | A reference to an upstream scope output that was not proven. |
| `bare_unqualified_field` | A bare field cannot be bound uniquely across several or zero inputs. |
| `qualified_expression_unresolved` | A qualified expression still did not resolve to a source. |
| `other_expression_unresolved` | Other expression source gaps. |
| `capacity_guard` | Expansion stopped at a declared size/substitution guard; this is not an alias-binding failure. |

### 5.3 Deciding whether it is fit for automation

At minimum, apply this gate:

```text
parse_status == ok
AND syntax_status == strict_ok (or the caller explicitly accepts recovered)
AND the target field's trace_complete == true
AND the target field has no lineage_fact_gap with root_impact=true
```

Do not look at the warning count alone, and do not ignore `trace_complete=false` just because
`physical_sources` is non-empty.

## 6. Relationship to `lineage.json.diagnostics`

`lineage.json` keeps only the summary:

```json
{
  "diagnostics": {
    "fallback_used": false,
    "warning_count": 3,
    "warning_types": {"magic_number": 1},
    "lineage_fact_gap_count": 1,
    "lineage_fact_gap_types": {"alias_binding_missing": 1},
    "lineage_fact_gap_samples": [{"gap_id": "lineage_gap:0001"}],
    "stats": {"scope_count": 6},
    "full_diagnostics_file": "diagnostics.json"
  }
}
```

| Need | Where to read |
| --- | --- |
| A quality badge on a list page | `lineage.json.diagnostics` |
| Aggregating by warning/gap type | The summary suffices; read the companion file when you need the full objects |
| Displaying every warning and its evidence | `diagnostics.json` |
| Locating every affected field | `diagnostics.json.lineage_fact_gaps[]` |
| Automated gating of one field | The lineage trace status + the complete fact gaps |

## 7. Consumption examples

List every warning:

```bash
jq -r '.warnings[]? | [.type, .scope, .msg] | @tsv' diagnostics.json
```

List the fact gaps that affect a final target:

```bash
jq -r '.lineage_fact_gaps[]? |
  select(.root_impact == true) |
  [.gap_id, .gap_type, .scope_id, .object_name, .needed_fact] |
  @tsv' diagnostics.json
```

A Python quality gate:

```python
import json
from pathlib import Path

from scope_lineage import validate_diagnostics_document

diagnostics = json.loads(Path("diagnostics.json").read_text(encoding="utf-8"))
validate_diagnostics_document(diagnostics)

blocking_gaps = [
    gap
    for gap in diagnostics.get("lineage_fact_gaps", [])
    if gap.get("root_impact") is True
]
if blocking_gaps:
    raise RuntimeError(f"lineage has {len(blocking_gaps)} target-impacting fact gaps")
```

## 8. Safe interpretation rules

1. `fallback_used=true` is not the same as failure, but the degraded status must be displayed;
2. warnings are reminders and should not all be escalated to blockers;
3. a fact gap is an unproven fact and must not be silently guessed away by an AI;
4. `evidence_path` locates a fact back in the lineage; it is not a filesystem path;
5. `owner_hint` is a handling suggestion, not the identity of a business owner;
6. unknown warning/gap types must be preserved, not dropped because the consumer does not recognize them;
7. `diagnostics.json` and `lineage.json` must come from the same output directory and the same parse;
8. 1.x may add optional diagnostic fields, and consumers should tolerate unknown keys.
