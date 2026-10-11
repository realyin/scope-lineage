[中文](../zh-CN/task-to-ontology.md) | English

# From task JSON and table schema to business semantics and ontology: where to start

> If you have a batch of task JSON and table schema and you want **task semantics, table semantics and a business ontology**, start here.
> Running `parse` → `tables` / `glossary` → `describe` → `ontology` and stopping gives key-fold candidates, not a business ontology:
> concept names come from key-column stems (English abbreviations such as `cust`, `acct`), and most tables are only provisional concepts.

## Pick a route first

| What you want | Route | What you get |
| --- | --- | --- |
| Field lineage, impact analysis, a mapping document | `parse`, then `scripts/query.py` or `render` | `lineage.json`, `mapping.md` |
| A quick structural scan of a corpus: which tables share which keys | The five-minute path in the [end-to-end workflow](workflow.md), ending at `ontology` | `ontology.json`: key-fold candidates, not a business ontology |
| What a task does, what a table means, which business concepts exist | **The route on this page**: table semantics, then the ontology catalog | `docs/`, `site/semantics/`, `site/concepts/` |

## The whole procedure at a glance

The operating manual is [`runbook.md`](../../skills/scope-lineage/references/runbook.md); the table below is its outline.
Every step in the manual has seven fields: purpose, precondition check, commands, outputs and self-check, common failures, completion test, next step.
When you do not know which step a run has reached, run the progress script `next_step.py` (manual 0.6): it reads only the run directory and prints the checklist below and the current step.

| Step | What | Who | Main output |
| --- | --- | --- | --- |
| S0 | Environment, version, run directory, ledger | Orchestrator | `env.sh`, `ledger.md` |
| S1 | Lineage parse | Orchestrator | `artifacts/` |
| S2 | Table cards and glossary | Orchestrator | `corpus/tables.json`, `corpus/glossary.json` |
| S3 | Pick tables and build packets | Orchestrator | `tables.txt`, `packets/` |
| S4 | Write | Sub-agent, one per table | `docs/<table>.json` |
| S5 | Validate and block | Orchestrator | Validation result |
| S6 | Review | Sub-agent, one per table | `reviews/<table>.md` |
| S7 | Fix | Sub-agent, one per table | Revised document, fix receipt |
| S8 | Advance status and re-review | Orchestrator and sub-agents | All `fixed` |
| S9 | Full validation and render the semantics pages | Orchestrator | `site/semantics/` |
| S10 | Ontology catalog: start, digest, draft, fragments, merge, fix-up, build and render | Orchestrator and sub-agents | `catalog/`, `merged/`, `onto/`, `site/concepts/` |
| S11 | Regression acceptance | Orchestrator and sub-agents | `round1/score/` |
| S12 | Write confirmations back (optional) | Orchestrator | Documents with confirmations |
| S13 | Deliver | Orchestrator | `RESULT.md` |

## Three rules you cannot skip

1. **Writing and reviewing are two independent calls.** The reviewer reads only the packet and the document, never the writer's reasoning. A writer checking its own work cannot find its own blind spots.
2. **Whether a step passed is decided by the output of its completion-test command**, not by your impression. If a precondition fails or the completion test does not hold, stop at that step.
3. **Start with a small sample.** At most 5 tables and 1 group; scale up only after the procedure and the quality hold.

## Roles and model tiers

The roles in the manual are prompt files, not specific models. Tiers are relative:

| Role | Steps | Tier | With only one model |
| --- | --- | --- | --- |
| Write, fix | S4, S7 | Second-strongest | The same model works, but open a new session each time and give it only the prompt and the packet |
| Review, re-review | S6, S8 | Strongest | New session, reads only the packet and the document; run it twice and take the union of the two reviews |
| Catalog draft, fragments | S10 | Second-strongest | Do not go weaker; after drafting, have a stronger model check that the concepts are complete |
| Answer | S11 | Cheap | Any |
| Grade | S11 | Strongest | New session, never sees the answerer's reasoning |

## How to start

The executing agent uses the [`scope-lineage-ontology`](../../skills/scope-lineage-ontology/SKILL.md) skill.
Once it is installed (see [AI agent skill](agent-skill.md)), say which task directory and table schema directory to use and what you want, and it loads by itself;
for an agent without a skill mechanism, hand it the following and replace the paths in angle brackets:

```text
Goal: use scope-lineage to produce table semantics and a business ontology catalog from the tasks and table schema below.
Task directory: <task JSON directory>
Table schema directory: <table metadata directory>
Run directory: <a new run directory>
First read <scope-lineage repository>/skills/scope-lineage-ontology/SKILL.md in full and follow it.
Start with a small sample: at most 5 tables.
```

## How to tell it went off course

| Symptom | What it means | What to do |
| --- | --- | --- |
| The run directory has only `ontology.json`, with no `packets/`, `docs/` or `reviews/` | The key-fold route was taken and table semantics was skipped | Go back to S0 and redo it by the manual |
| Concept names are English stems such as `cust` or `acct`, or `nan` | Same: names came from key-column stems | Same |
| There is `docs/` but no `reviews/` | There was no independent review | Go back to S6 |
| A concept page has only identifiers and no attributes, or an event has only one or two participants | The catalog draft is incomplete, and `catalog validate` cannot see what was left out | Run the omission check `catalog_check.py` from S10g and send its findings back to S10c and S10d |

## Next

- [`runbook.md`](../../skills/scope-lineage/references/runbook.md): the step-by-step manual.
- [Table semantics](table-semantics.md): document format, validation and status of `semantic *`.
- [Ontology catalog](ontology-catalog.md): `catalog-yaml/1` and `ontology-json/3`.
- [End-to-end workflow](workflow.md): the key-fold route and how the artifacts depend on each other.
