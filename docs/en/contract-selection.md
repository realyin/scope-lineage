[中文](../zh-CN/contract-selection.md) | English

# Statement level or task level? Choose the layer by scenario

Since 0.2.0 the tool produces one artifact: the task document (schema_version 2.0, see
[Task Lineage 2.0](task-lineage-v2.md)). The former 1.0 "statement document" did not disappear —
it is **embedded in full** as an entry of `statement_lineage.<statement_id>`, and its shape is
still described by the [`lineage.json` output contract](lineage-json.md). This page is not about
field details; it answers one question: **which layer your scenario should read.**

## The one-line test

> **If your question is "where does the data come from", read the statement document; if your
> question is "what did the task do", read the task-level fields.**

More concretely: if you catch yourself asking a question with a time order in it — "did it
**truncate first** and **then** insert?" "is yesterday's data still there **after it ran**?" —
that is a task-level question. A statement document is a snapshot taken of one write statement,
and a snapshot cannot answer "which came first"; the task-level fields are the recording of the
whole task.

## Scenario table

| What you are doing | Which layer | Why, in one line |
| --- | --- | --- |
| **Field lineage analysis** (which upstream tables and columns does this field come from) | **Statement document** | The answer sits in `end_to_end_lineage[].physical_sources`, ready to use |
| **Field transformation-step analysis** (how is this metric computed, step by step) | **Statement document** | The chains (`field_mapping_chains`), expressions, and JOIN/filter logic are all in the statement document's evidence layer, and it can be rendered into a human-readable `mapping.md` |
| **Table-level dependency / impact analysis** (an upstream table changed — who is affected) | **Statement document** | `source_tables` / `target_table` are directly readable |
| **Building a lineage graph for a data map / data-asset platform** | **Statement document** | Platforms organize assets by "target table", and each entry has exactly one `target_table` — the granularity lines up |
| **Auditing what data a task changed** (what was deleted, truncated, updated) | **Task level** | Statement documents do not model DELETE / UPDATE / TRUNCATE; they only record them under `skipped_statements` |
| **Deciding what a table looks like after the task ran** (empty? whole table replaced? only yesterday's partition?) | **Task level** | This is a "final state" question, and only the task-level `final_table_states` / `table_state_graph` record state |
| **Investigating a data-loss incident** ("why is the table empty / why is there less data") | **Task level** | You need to reconstruct statement execution order and each step's effect on the table |
| **Data-quality attribution** (why did this row disappear / why was it not updated) | **Task level** | "Does the row still exist" is decided by DELETE / MERGE conditions, and only the task-level `row_membership_sources` separates that |
| **Compliance / security review** (where does a sensitive field flow, including paths deleted or modified in between) | **Task level** | You need the complete task-level facts, and must not miss statements the statement document does not model |
| **CI quality gates** | No choice needed | `--quality-policy` / `--fail-on-*` apply to the whole task parse, and facts from both layers count |

## Two typical scenarios, expanded

**Field lineage analysis → statement document.** You want to know where
`mart.customer_summary.order_count` comes from — open the `statement_lineage` entry that writes
it, and `end_to_end_lineage` says outright "from `dwd.order_detail.order_id`, via an aggregate".
Done. The task-level `end_to_end_lineage` can answer the same question, but only after you get
several things right first: drop the `prior_table_state` edges that mean "from the table's own
previous state", fold temporary views with `fold_session_scoped`, check `source_state` — get one
step wrong and the conclusion is wrong. **If a statement document can answer the question, do not
make trouble for yourself at the task level.**

**Field transformation-step analysis → statement document.** You want to explain to a business
stakeholder that "this metric first groups by customer, then computes the 30-day paid amount, then
takes the top-ranked record" — the statement document's
`field_mapping_chains[].ordered_steps[]` records what each layer did, step by step, each step
carrying its original SQL expression, and `scope-lineage render` can emit a human-readable
`mapping.md`. This is exactly what the statement document was designed for.

## How the two layers line up

When a task-level and a statement-level fact refer to the same statement, match them on
**`statement_id`** (of the form `stmt:002`) — that is the key of both `statement_sequence[]` and
`statement_lineage`. **Do not use `task_id`**: the `task_id` inside an entry follows a different
suffix convention, and the same name can silently point at a different statement (see the
top-level field table in [lineage-json.md](lineage-json.md) and the "Compatibility and
consumption" section of [task-lineage-v2.md](task-lineage-v2.md)).

## Advice for new consumers

The statement-level evidence is embedded, complete, in every `statement_lineage` entry, so a
consumer program only has to read this one artifact: read the entries for lineage and field
explanations, read the task-level fields for audits and state judgments. When reading the
task-level `end_to_end_lineage`, handle prior-state edge folding, session-scoped relations, and
window context columns as [task-lineage-v2.md](task-lineage-v2.md) describes — those are the known
easy-to-get-wrong spots, and more than half of that document is about how not to read it wrong.
The formerly standalone v1 artifact was removed in 0.2.0; for migration see "Migrating from the
removed contract 1.0" in the project README.
