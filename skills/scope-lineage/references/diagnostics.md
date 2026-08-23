# Diagnostics triage: reporting uncertainty honestly

The tool's core promise is that it marks what it cannot prove instead of guessing.
An answer that drops those marks breaks the promise at the last mile. This file is the
agent-facing triage layer; the complete contract (every field, every type, jq recipes)
is `docs/zh-CN/diagnostics-json.md` in the scope-lineage repository.

## The reporting rules

1. Warnings and gaps are part of the answer, not an appendix. Lead with them when they
   affect what was asked ("the trace for X stops at scope Y — the schema for
   `ods.z` is missing"), mention them briefly when they do not.
2. Distinguish the three causes and say which one applies:
   - **input problem** — metadata missing (`metadata_incomplete` in
     `analysis_status.blocking_reasons`, `star_not_expanded`, tables absent from
     `metadata_coverage`): fixable by the user, say what to supply;
   - **SQL problem** — the query itself is wrong or ambiguous
     (`ambiguous_unqualified`, `duplicate_alias`, `star_except_column_not_found`):
     the SQL needs changing;
   - **modeling boundary** — the tool deliberately does not model it
     (`unsupported_statement`, `merge_delete_ignored`): nothing is broken, state the
     boundary.
3. Never resolve an `AMBIGUOUS` source yourself. The artifact carries `candidates`
   because the SQL does not determine the answer; present the candidates.
4. `source_kind: generated` is a complete answer (literal/system value, no physical
   source). Do not call it a gap.

## Fast triage order

1. `parse_status` / `syntax_status` — `failed` or `recovered` first: the artifact may
   describe a query that cannot run as written (`syntax_errors[]` has positions).
2. `analysis_status.blocking_reasons` — `metadata_incomplete` ranked before
   `lineage_fact_gap` means: fix inputs before judging the parser. The same task often
   goes to zero gaps once schemas are supplied.
3. `lineage_fact_gaps[]` with `root_impact: true` — these reach the final target
   columns; gaps without root impact are internal and usually worth only a mention.
   Each gap names `needed_fact` (what would close it) and `missing_reasons`.
4. `warnings[]` grouped by `type` — most types are governance signals, not errors.

## Warning types most likely to need explaining

| Type | What happened | Honest phrasing |
| --- | --- | --- |
| `star_not_expanded` | No schema → `SELECT *` kept as a placeholder | "columns behind `*` are not enumerated; field coverage is partial until a schema for T is supplied" |
| `star_modifier_not_applied` | `EXCEPT (...)` exists but the star could not expand | "the exclusion could not be applied — the placeholder still includes the excluded columns" |
| `ambiguous_unqualified` | An unqualified column matches several inputs | list the candidates; do not pick |
| `target_field_binding_fallback` | Authoritative DDL binding did not fully apply | point at `target_field_binding.issues[]`; column names may be positional guesses |
| `session_scoped_relations_present` | TEMP VIEW / CACHE TABLE relations in the states | exclude them from catalog reconciliation; the lineage hops themselves are valid |
| `unsupported_statement` | A statement kind the task model does not model | state it was recorded, not modeled — coverage counts should exclude it |
| `recovered` (syntax_status) | sqlglot dropped tokens to keep parsing | "lineage describes a repaired reading of the SQL; it may not run as written" |
| `merge_branch_not_representable` | `WHEN NOT MATCHED BY SOURCE` (third Spark branch kind) | read `merge_branch_qualifier`; absence of `merge_branch` ≠ not a MERGE |
| `resolution_rounds_exhausted` | Expression resolution hit its round ceiling | "resolution text may be incomplete for this statement" — rare; worth reporting upstream |

## Gap entries

Each `lineage_fact_gaps[]` item is self-describing: `gap_type` (category),
`object_name` (affected field), `expression_sql` (the evidence), `missing_reasons`
(direct causes), `needed_fact` (what closes it), `root_impact` (does it reach a target
column). A useful report quotes `object_name` + `needed_fact` and stops — the entry
already is the explanation.
