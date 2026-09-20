[中文](../zh-CN/README.md) | English

# Scope Lineage Documentation Map

Scope Lineage turns Spark/Hive SQL into two kinds of machine-consumable facts:

- `lineage.json`: the structure, logic, and field provenance the SQL has already proven;
- `diagnostics.json`: the uncertainty, degradations, and fact gaps found while parsing.

If this is your first contact with the project, read in this order:

1. [Project README](../../README.md): what problem the tool solves and what the artifacts are worth;
2. [End-to-end workflow: from task JSON to profiles and ontology](workflow.md): the whole pipeline in one place — in what order `glossary` / `tables` / `describe` / `ontology` run after `parse`, what each step needs from the one before it, where a person or an agent enters, and how confirmed answers are written back; read this when you are unsure which command comes next;
3. [Installation and usage guide](getting-started.md): install, run your first parse, and learn the common CLI and Python API;
4. [Scope Lineage: turning complex SQL back into verifiable field transformation chains](value-and-use-cases.md): a full worked case covering transformation lineage, verifiable lineage, and practical value;
5. [Input formats](input-formats.md): how SQL, task JSON, Schema, and target-table metadata are passed in;
6. [Statement level or task level? Choose by scenario](contract-selection.md): field lineage and transformation-step analysis read the embedded statement documents; audits, incident forensics, and final table state read the task-level fields — pick the right level before reading the details;
7. [`lineage.json` output contract](lineage-json.md): work through the top-level fields, scopes, logic blocks, field mapping chains, and end-to-end lineage;
8. [`diagnostics.json` output contract](diagnostics-json.md): warnings, fact gaps, and which results must not be treated as proven facts.
9. [Task Lineage 2.0](task-lineage-v2.md): DELETE/TRUNCATE/UPDATE, row-set effects, and multi-statement final table state.
10. [`mapping.md` field mapping document](mapping-doc.md): use `scope-lineage render` to turn the contract into a mapping document readable by both humans and machines.
11. [`semantic.json` / `semantic.md` task-semantic description](semantic-doc.md): use `scope-lineage describe` to derive a deterministic semantic skeleton from the contract — output shape and grain, the processing chain, the rule list, and field semantics, each line carrying its source tag and evidence id; business naming is not part of it.
12. [`tables.json` / `tables.md` corpus-level table cards](tables-doc.md): use `scope-lineage tables` to aggregate a whole corpus into one card per table — who writes it, what a row represents, who reads it and which columns; `describe --tables` lets a task profile cite its upstream cards.
13. [`glossary.json` / `glossary.md` term and value dictionary](glossary-doc.md): use `scope-lineage glossary` to aggregate a whole corpus into one dictionary keyed by column name — comments merged across tables, observed constant values, and the enums the SQL proved closed; meanings come only from human confirmation and literal comment hits, and `describe --glossary` wires it into `fields[].value_domain`.
14. [`ontology.json` / `ontology.md` corpus-level ontology candidate](ontology-doc.md): use `scope-lineage ontology` to turn a whole corpus, on top of the cards and the dictionary, into a tiered ontology candidate — entities and identity keys, relations and provable cardinalities, constraints, and cross-task contradictions; the index opens with a Mermaid ER overview, every table card gains five sections (identity / relations / constraints / synonyms / open items), and human answers come back through `--overrides` as a fifth tier, `confirmed`; the business naming and the class hierarchy are left to a person or an agent.
15. [AI agent skill](agent-skill.md): let Claude Code, Codex, and other AI coding agents use lineage parsing, field transformation chains, and mapping documents directly.

## From question to field

| The question you need answered | Read this first |
| --- | --- |
| Which table does the task write, and with what write mode? | `target_table`, `stmt_kind`, `target_partition_*` |
| Which physical tables does the task read? | `source_tables` |
| How are CTEs, subqueries, and UNIONs connected? | `scope_graph`, `scopes.<scope_id>.depends_on` |
| What does one query block do? | `scopes.<scope_id>.logic_blocks[]`, `scope_profile.steps[]` |
| What is the SQL expression behind an output field? | `scopes.ROOT.outputs[]` |
| Which physical fields does a target field ultimately come from? | `end_to_end_lineage[]` |
| Which query blocks and transformation steps did a field pass through? | `field_mapping_chains[].ordered_steps[]` |
| What are the JOIN keys and the extra filters? | `logic_blocks[].join_relation_detail` |
| What are the aggregation's group by and metric expressions? | `logic_blocks[].aggregation_detail` |
| How does a window function partition and order? | `logic_blocks[].window_specification` |
| Was `SELECT *` actually expanded? | `scopes.*.outputs[]`, `diagnostics.json.warnings[]` |
| Is a lineage edge complete and trustworthy? | `trace_complete` / `trace_status`, `missing_reasons`, `ambiguities` |
| Why can a field's source not be determined? | `diagnostics.json.lineage_fact_gaps[]` |
| How do DELETE/TRUNCATE affect the final table? | v2 `statement_sequence[]`, `table_state_graph`, `final_table_states` |

## The boundary between facts and higher-level knowledge

Core outputs traceable facts; it does not generate business conclusions directly. For example:

- Core can prove that `paid_amount_30d` uses `SUM(CASE WHEN ...)` and comes from `dwd.order_detail.pay_amount`;
- an upper-layer Agent can explain that fact as "paid amount over the last 30 days";
- Core will not guess from the field name alone that this is a revenue, risk, or customer-value metric.

That boundary lets an AI's answer fall back to SQL expressions, scopes, fields, and diagnostic evidence, instead of resting on a single natural-language guess nobody can re-check.
