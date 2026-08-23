# Artifact guide: which JSON path answers which question

A parse produces one artifact directory per task: `lineage.json` (the task document,
`schema_version: "2.0"`) and `diagnostics.json`. This file maps question types to the
paths that answer them. Prefer `scripts/query.py` — read paths directly only for
questions it does not surface, and even then extract with `python3 -c` / `jq`, never by
loading the whole file.

## The task document (lineage.json)

| Question | Path |
| --- | --- |
| Did the parse succeed? | `parse_status` (`ok`/`failed`), `syntax_status` (`strict_ok`/`recovered`) |
| What statements ran, in order? | `statement_sequence[]` — `statement_id` (`stmt:NNN`, script position), `stmt_kind`, `category`, `model_status` |
| What state did each table end in? | `final_table_states` (table → state id), `table_state_graph` (nodes/edges of every state transition, keyed by `state_id`) |
| Where does a final column's value come from? | `end_to_end_lineage[]` — final-state merged view: `{table, column, value_sources[], trace_complete, missing_reasons}`; each source is `{table, column, source_kind, state_id}` (`source_kind`: `physical_field` / `prior_table_state` / `generated` / ...) |
| Which rows survive / under what condition? | `end_to_end_lineage[].row_membership_sources`, `.value_condition_sources` |
| Declared scheduler dependencies? | `task_dependencies` |
| What was skipped or uncertain? | `diagnostics` (summary; full detail in diagnostics.json) |

Session-scoped relations (TEMP VIEW / CACHE TABLE) appear in `final_table_states` like
tables; the `session_scoped_relations_present` warning lists them — exclude them before
reconciling against a catalog.

## The statement documents (statement_lineage)

`statement_lineage.<statement_id>` embeds the complete per-statement document — this is
where field-level detail lives:

| Question | Path (inside one entry) |
| --- | --- |
| Which physical tables does this statement read? | `source_tables[]` |
| What does it write? | `target_table`, `stmt_kind`, `target_partition_*` |
| Column → physical columns, with transform? | `end_to_end_lineage[]`: `{column, transform, expression, physical_sources[{table, column, transform}], generated_sources[], source_kind, trace_complete}` |
| Step-by-step derivation of one column? | `field_mapping_chains[]`: `{target_field, chain_type, trace_status, ordered_steps[], root_source_fields[], expanded_expression, missing_reasons}`; each step: `{step_no, scope_id, step_type, transform, expression_sql, expanded_expression, input_fields, output_field, grain_effect}` |
| The query's structure (CTEs, subqueries, unions)? | `scope_graph`, `scopes.<scope_id>` (`kind`, `depends_on`, `outputs[]`, `joins[]`, `filters[]`, `logic_blocks[]`) |
| A staged, readable summary for retrieval? | `scope_profile.steps[]` |
| Did projections bind to real target columns? | `target_field_binding` (`status: applied` + ordinals) or `target_binding_absent_reason` |
| Statement-level joins/filters/aggregations? | `scopes.<id>.logic_blocks[]` and the join/filter/aggregation/window detail objects |

`statement_id` is the ONLY cross-reference key between task level and statement level
(`task_id` inside entries carries a different suffix scheme — do not join on it).

## Trust fields — read these before answering

- `trace_complete` (boolean, on e2e items): false means the trace stops early;
  `missing_reasons[]` says why.
- `trace_status` / `chain_status` on mapping chains: `complete` or not.
- `source_kind: generated` means the value is born in the query (literal, system
  function) — it has NO physical source, and that is the correct answer, not a gap.
- `AMBIGUOUS` sources carry a `candidates` list: the tool refuses to pick one; so must
  you.
- `expression` / `expression_sql` are verbatim evidence — quote them rather than
  paraphrasing SQL from memory.

## mapping.md

`scope-lineage render --lineage <dir>` writes `mapping.md` beside each lineage.json
(one section per statement for task documents) and `warnings.md` when there is anything
to warn about. Every line links back to contract ids, so cite the document freely — it
cannot drift from the artifact.
