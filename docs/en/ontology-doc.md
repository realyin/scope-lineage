English | [中文](../zh-CN/ontology-doc.md)

# `ontology.json` / `ontology.md` corpus-level ontology candidate (`ontology-json/1`)

`scope-lineage ontology` walks every `lineage.json` under one corpus root and, on top of
the [table cards](tables-doc.md) and the [value dictionary](glossary-doc.md), answers one
question no single table can: **how do these tables relate**. Entities (a table plus its
identity keys), attributes (a column plus its comment, its observed roles and its
synonyms), relations (JOIN key pairs plus a provable cardinality), constraints (not null,
value set, unique per key, partition) and the contradictions between tasks.

Every JOIN in a corpus is an assertion about two entities and their keys; every "dedup by
k, then join" is an assertion that the deduplicated table holds many rows per k; every
closed `IN` list is an assertion about a column's value set. This document collects those
assertions and labels each with its confidence tier and its evidence.

## Position: an ontology **candidate**, not a business ontology

- Every assertion carries a `tier` and an `evidence` list and traces back to a concrete
  statement by task name, `statement_id` and `logic_block_id`; an assertion with no
  evidence is not published at all.
- Core gives no entity a business name, a type or a parent class, and does no business
  naming. `naming_hints` holds metadata facts only (table comment, domain, project,
  owner); the naming and the modelling are left to a person or an agent who knows the
  business.
- The slots deliberately line up with the usual ontology languages (entity ~ owl:Class,
  attribute ~ owl:DatatypeProperty, relation ~ owl:ObjectProperty, constraint ~
  sh:NodeShape), and `--export` writes LinkML and SHACL from that correspondence; no
  OWL file is emitted.
- Stability is graded as in the other derived documents: key names are stable within
  `ontology-json/1`, the Chinese wording may be adjusted, and a machine should read the
  JSON rather than the Markdown.

## Usage

```bash
# A corpus directory: lineage.json is searched recursively, artifacts go to --out
scope-lineage ontology --lineage /path/to/corpus --out /path/to/ontology

# Reuse the cards and the dictionary you already built (both are built in memory over
# the same corpus when they are not supplied); --overrides merges the table-level human
# confirmations and --concept-overrides the concept layer's, and a confirmed assertion
# is published at the fifth tier, confirmed
scope-lineage ontology --lineage /path/to/corpus --out /path/to/ontology \
  --tables /path/to/tables/tables.json --glossary /path/to/glossary/glossary.json \
  --overrides /path/to/ontology.overrides.json \
  --concept-overrides /path/to/concepts.overrides.json

# Across corpora: --tables repeats, and the cards are merged before anything is built
scope-lineage ontology --lineage /path/to/corpus --out /path/to/ontology \
  --tables /path/to/a/tables.json --tables /path/to/b/tables.json
```

Three artifacts:

| File | Read by | Contents |
| --- | --- | --- |
| `ontology.json` | machines / RAG / knowledge-graph loaders | the main artifact, `doc_format: "ontology-json/1"` |
| `ontology.md` | people | an index: the concept layer (its diagram, the concept and concept-relation tables and the unplaced tables) first, then the Mermaid ER overview plus the entity, relation, constraint and findings tables and the consolidated open list (the last two folded into groups by table family), `doc_format: "ontology-index-md/1"` |
| `tables/<db.table>.md` | people / RAG chunked per table | the table card's six sections plus five ontology sections, `doc_format: "ontology-md/1"`; the filename rule is exactly `scope-lineage tables`' own |

Python API (consumes the contract documents, same path the files are written from):

```python
from scope_lineage import build_ontology, build_semantic_profile, build_table_cards
from scope_lineage import render_ontology_index_markdown, render_ontology_table_card_markdown

profiles = [build_semantic_profile(document) for document in documents]
cards = build_table_cards(profiles, artifact_root="/path/to/corpus")
ontology = build_ontology(documents, profiles, tables=cards, artifact_root="/path/to/corpus")
index = render_ontology_index_markdown(ontology)
card = render_ontology_table_card_markdown(cards["tables"][0], ontology)
```

- `--lineage` behaves exactly as it does for `tables` / `glossary`: one `lineage.json`, or
  a directory tree searched recursively for them; a document of an unknown version is
  skipped and counted in directory mode.
- `--tables` / `--glossary` only save a recomputation: the bytes are identical either way.
  With `--tables`, the cards in that file are the base the ontology sections are appended
  to; without it the same cards are built in memory over the same corpus.
- `--tables` **repeats**: several documents are folded into one with the
  [card merge rules](tables-doc.md#merging-across-corpora---merge) before the ontology is
  built, so a key proven in another corpus can carry a relation here. See "Cross-corpus
  evidence" below.
- `--format` takes `json`, `md` or both (default `json,md`); when `md` is not among them
  neither `ontology.md` nor `tables/` is written. Anything else is an argument error
  (exit code 2).
- `--export` takes `linkml`, `shacl` or both (repeatable, or one comma-separated list)
  and exports nothing by default; it is independent of `--format`. See
  [Exporting LinkML / SHACL](#exporting-linkml--shacl).
- Determinism: the same corpus produces the same bytes whatever order it was walked in.

## Incremental runs: `--incremental` / `--no-cache` / `--cache-from`

One or two tasks changed, and the rerun still reads and re-derives every task in the
corpus. `--incremental` narrows that pass to the tasks whose fingerprints moved:

```bash
scope-lineage ontology --lineage /path/to/corpus --out /path/to/ontology --incremental
```

- It writes two disposable things under `--out`: `.scope-lineage-corpus-index.json` (the
  sha256 of each task's `lineage.json` / `diagnostics.json`, plus one sha256 over the
  options that steer the derivation) and `.cache/` (the facts each task contributed
  before the corpus-level merge).
- The cache holds **only the fields the corpus-level merge reads**. The reader-facing
  half of a semantic profile -- `stages`, `confidence`, each field's step-by-step
  `derivation` -- is never merged and so is never stored. Which fields count is each
  builder's own list (`PROFILE_FIELDS_READ`, beside the code that reads it); editing
  one invalidates the whole index and recomputes everything.
- The stored facts are **versioned**: `payload_version` (`corpus-cache/3` today). A
  cache file or an index of another version is ignored and recomputed -- an older
  version held something else, not the same thing with fewer keys.
- **The corpus-level merge still runs over every task**: only the per-task half is
  reused, which is what makes an incremental run byte-identical to a full one.
- **Another corpus's cache can be reused too** (Q7): `--cache-from <dir>` names a further
  fact cache -- the `--out` of another run, or the `.cache/` inside it. The same task parsed
  into another directory (re-parsed, or walked again as part of a larger corpus) is borrowed
  rather than re-derived when its `lineage.json` / `diagnostics.json` bytes and the options
  digest match, and the borrowed file is copied into this run's own `.cache/`, so the next
  run finds it locally and the lending directory can go away. Repeatable, tried in the order
  given and after this run's own cache; it implies `--incremental`, and `--no-cache` still
  wins. The corpus path is **not** part of the options digest: the same task has to derive
  the same facts wherever it was parsed.
- Fact files are keyed by task name, and two corpora may hold different tasks under one
  name. What decides a borrow is the fingerprint and the options digest recorded inside the
  file, not the file's name, so a task of the same name and other contents is recomputed.
- A changed option invalidates the whole index and recomputes everything: the **content**
  of the `--overrides` file, `--format`, the `glossary.json` / `tables.json` read back,
  and the tool version. An index or a cache file written by another subcommand (a
  `command` or `doc_format` that disagrees) is ignored the same way.
- The summary line gains `reused=N, recomputed=M, removed=K`: how many tasks were reused,
  re-derived, and have disappeared from the corpus. With `--cache-from` the first counter
  reads `reused=N (borrowed=B)`, `B` being the tasks borrowed from another corpus.
- Without `--incremental` the run is the full one it always was, reading and writing
  neither index nor cache; `--no-cache` deletes both first and then runs in full.

## The five confidence tiers

| Tier | In the Markdown | Definition | Example |
| --- | --- | --- | --- |
| `proven` | 已证明 | written in the SQL | the join key pair exists; a partition column; a key a producing task proved; a DIRECT rename |
| `implied` | 可推得 | follows from what the SQL does | a task deduplicates a table by k before joining it → that table holds many rows per k (otherwise the dedup is pointless); a UNION column alignment |
| `hypothesis` | 作者假设 | the author assumed it and the SQL does not prove it | joining a physical table directly on k assumes it is unique by k; whether an observed value set is the complete one |
| `conflict` | 矛盾 | two tasks disagree | T1 deduplicates a table by k, T2 joins the same table directly on k — a governance finding, not an ontology fact |
| `confirmed` | 已确认 | **only ever from a human write-back**; the corpus can never reach this tier on its own | somebody confirmed a relation's cardinality or a table's identity key in `ontology.overrides.json` |

## The `ontology.json` structure

```jsonc
{
  "doc_format": "ontology-json/1",
  "corpus": {"artifact_root": "…", "task_count": 12, "lineage_digests": {"task_a": "…"},
             "external_evidence_tables": 2},   // only when merged cards hold tables this corpus never touched
  "entities": [
    {"id": "ods.customer", "kind": "physical_table",
     "family": "ods.customer",   // Q3: the family key, the name without _di / _tmp / _mid01
     "comment": null,
     "identity": {
       "candidate_keys": [{"columns": ["id"], "tier": "hypothesis",
                           "evidence": [{"task": "task_a", "statement_id": "stmt:001",
                                         "kind": "joined_as_right_without_dedup",
                                         "logic_block_id": "logic:ROOT:join:001"}]}],
       "declared_hints": [{"columns": ["id"], "evidence": "column_comment",
                           "text": "customer primary key"}],
       "multiplicity": [{"columns": ["driver_id"], "tier": "implied",
                         "claim": "multiple_rows_per_key", "evidence": [{"kind": "group_by"}]}],
       "partition_columns": ["dt"]},
     "attributes": [
       {"column": "state", "type": "string", "comment": null,
        "observed_roles": ["filter", "output"], "used_in_corpus": true,
        "not_null_observed": false,
        "synonyms": [{"entity": "mart.t", "column": "order_state", "tier": "proven",
                      "via": "direct_rename", "evidence": [{"task": "task_a"}]}],
        "samples": ["PAID", "NEW"]}],
     "naming_hints": {"table_comment": null, "domain": null, "project": null, "owner": null},
     "relation_hints": [{"from_column": "pay_id",
                         "to": {"entity": "ods.pay", "column": "id"},
                         "evidence": "column_comment", "text": "payment, references ods.pay.id"}]}
  ],
  "families": [
    {"family": "ods.pay", "tables": ["ods.pay_df", "ods.pay_di"], "size": 2}
  ],
  "concepts": [
    {"id": "concept:cust", "name": "客户", "name_tier": "hypothesis",
     "name_candidates": [
       {"text": "客户", "source": "key_column_comment", "count": 2,
        "name_evidence": [{"table": "ods.customer_base", "column": "cust_no"}]},
       {"text": "cust", "source": "key_stem", "count": 1, "name_evidence": []}],
     "possible_duplicate_of": ["concept:customer"],   // another concept proposed the same name
     "kind": "entity", "kind_tier": "implied",
     "kind_evidence": [{"signal": "word_hint", "vote": "entity",
                        "table": "ods.customer_base",
                        "detail": "ods.customer_base 客户信息表"}],
     "identity": {"stem": "cust", "columns_seen": ["cust_no", "customer_id"]},
     "tables": [{"table": "dwd.customer_df", "role": "primary",
                 "membership_basis": "key:proven",
                 "key_columns": ["cust_no"], "grain": "group_by"},
                {"table": "ods.customer_base", "role": "primary",
                 "membership_basis": "declared_hint",
                 "key_columns": ["cust_no"], "grain": null},
                {"table": "dwd.message_send_di", "role": "reference",
                 "membership_basis": "reference",
                 "key_columns": ["cust_no"], "grain": null}],
     "attributes": [{"stem": "cust", "type": "string", "comment": "客户编号",
                     "sources": [{"table": "ods.customer_base", "column": "cust_no"}]}],
     "tier": "implied"}
  ],
  "unassigned_tables": [
    {"table": "ods.staging_rows", "reason": "generic_key_only"}   // keyed by `id` alone,
                                                                 // and no hint and no JOIN placed it
  ],
  "concept_overrides_applied": {"concepts": 0, "merges": 0, "splits": 0,  // K4b
                                "unmatched": [], "ignored_fields": []},
  "relations": [
    {"id": "rel:001",
     "from": {"entity": "ods.driver", "columns": ["id"]},
     "to": {"entity": "ods.pay", "columns": ["driver_id"]},
     "kind": "join_association",
     "cardinality": {"claim": "one_to_many", "tier": "implied", "basis": "group_by"},
     "join_types": ["LEFT_OUTER"], "task_count": 1,
     "evidence": [{"task": "task_a", "statement_id": "stmt:001",
                   "scope_id": "ROOT", "logic_block_id": "logic:ROOT:join:001"}]},
    {"id": "rel:002",
     "from": {"entity": "ods.driver", "columns": ["pay_id"]},
     "to": {"entity": "ods.pay", "columns": ["id"]},
     "kind": "hinted",
     "cardinality": {"claim": "many_to_one_assumed", "tier": "hypothesis",
                     "basis": "column_comment"},
     "join_types": [], "task_count": 0,
     "evidence": [{"kind": "column_comment", "column": "pay_id",
                   "text": "payment, references ods.pay.id"}]}
  ],
  "concept_relations": [
    {"from": "concept:msg", "to": "concept:cust", "type": "participation",
     "roles": ["发送方", "接收方"],          // the entity's roles in the event
     "cardinality": {"claim": "many_to_one", "tier": "proven",
                     "basis": ["rel:003"]},  // the table-level edges that claimed it
     "task_count": 2, "evidence": ["rel:003", "rel:004"]}
  ],
  "concept_representation_links": [          // two tables of one concept, joined
    {"concept": "concept:cust", "from_table": "dwd.customer_df",
     "to_table": "ods.customer_base", "evidence": ["rel:005"]}
  ],
  "concept_relations_unmapped": {"total": 1,  // counted by the end that failed
     "by_reason": {"from_table_unplaced": 1, "to_table_unplaced": 0}},
  "constraints": [
    {"target": {"entity": "ods.orders", "column": "state"}, "kind": "in_set",
     "tier": "proven", "values": ["NEW", "PAID"], "completeness": "complete",
     "evidence": [{"task": "task_a", "statement_id": "stmt:001", "context": "filter_in"}]}
  ],
  "findings": [
    {"kind": "cardinality_conflict", "entity": "ods.pay", "columns": ["driver_id"],
     "tasks": {"multiple_rows_per_key": ["task_a"], "assumed_unique": ["task_b"]},
     "text": "…"},
    {"kind": "competing_candidate_keys", "entity": "ods.pay",
     "columns": ["driver_id", "dt"],
     "keys": [{"columns": ["driver_id"], "evidence": [{"task": "task_a"}]},
              {"columns": ["driver_id", "dt"], "evidence": [{"task": "task_b"}]}],
     "tasks": {"assumed_unique": ["task_a", "task_b"]}, "text": "…"}
  ],
  "finding_groups": [],   // the groups in open_item_groups whose kind is finding
  "open_items": [
    {"id": "open:key:ods.customer=id", "kind": "candidate_key",
     "entity": "ods.customer", "columns": ["id"], "tier": "hypothesis",
     "write_back": "键:ods.customer=id", "text": "…"}
  ],
  "open_item_groups": [
    {"group_id": "open:group:key:ods.customer=id", "kind": "candidate_key",
     "family": "ods.customer", "shape": "id",
     "representative": "open:key:ods.customer=id",
     "items": ["open:key:ods.customer=id"], "count": 1, "impact": 2,
     "write_back_pattern": "键:<table>=id"}
  ],
  "overrides_applied": {"relations": 0, "keys": 0, "unmatched": [],
                        "ignored_fields": []}
}
```

Slot by slot (every slot `ontology-json/1` publishes):

| Slot | Values | Meaning |
| --- | --- | --- |
| `corpus` | `artifact_root` / `task_count` / `lineage_digests` / `external_evidence_tables` | the same corpus block the table cards carry: the walked root, the task count, one lineage digest per task, and how many tables lent evidence only without becoming entities (P7; absent when none did) |
| `entities[].kind` | `physical_table` / `produced_table` | a table some task in the corpus writes is a `produced_table` |
| `entities[].family` | `<database>.<table name without its copy suffixes>` | Q3: which table family this table belongs to, derived from its own name alone (the rule is under "Table families and the folded open list"); the same table name in two databases is two families |
| `entities[].comment`, `naming_hints` | table comment / domain / project / owner | metadata carried over verbatim; Core infers no business semantics from it |
| `entities[].identity.candidate_keys[]` | `columns` + `tier` + `evidence` | the key a producing task proved (`producer_key_confidence`) and the key a consuming task assumed (`joined_as_right_without_dedup`) stand side by side; they are never merged into one "primary key" |
| `entities[].identity.candidate_keys[].scope_columns` | a list of column names | H2: the key is unique only within one value of these columns (the normal shape of a snapshot table); it can only come from a human confirmation |
| `entities[].identity.declared_hints[]` | `columns` + `evidence: column_comment` + `text` | H3: a column comment calling the column a key, carried over verbatim; it is a metadata hint and not a candidate key, and where it agrees with one, that key rises from `hypothesis` to `implied` |
| `entities[].relation_hints[]` | `from_column` + `to.entity` / `to.column` + `evidence: column_comment` + `text` (+ `unresolved`) | O9: a column comment pointing at another table's column (「关联 <表>.<列>」 and its kin), carried over verbatim and resolved against the corpus's own entities; one that cannot be resolved carries `unresolved` (`unknown_entity: X` / `ambiguous_entity: X` / `unknown_column: X`) and acts on nothing; the key is absent when a table's comments point at nothing |
| `entities[].identity.multiplicity[]` | `claim: multiple_rows_per_key` | O3: some task grouped or window-partitioned this table by these columns |
| `entities[].identity.partition_columns` | a list of column names | the partition columns a producing task writes (a metadata fact) |
| `entities[].attributes[].type`, `comment` | metadata | the column type and comment from the table card, carried over verbatim |
| `entities[].attributes[]` | one per column the metadata declares | attributes cover the whole table, not only the columns the corpus read or wrote, and follow the order of the table card's `columns[]` |
| `entities[].attributes[].observed_roles` | `filter`, `partition_filter`, `join_key`, `group_by`, `window_partition`, `window_order`, `output` | the consumer usages the table card recorded; a column nobody read carries an empty list |
| `entities[].attributes[].used_in_corpus` | `true` / `false` | whether any task in this corpus wrote or read the column; `false` alongside an empty `observed_roles` reads as "the metadata declares it and this corpus never went near it" |
| `entities[].attributes[].not_null_observed` | `true` / `false` | some task in the corpus filtered this column with `NOT x IS NULL` |
| `entities[].attributes[].synonyms[].via` | `direct_rename` / `union_alignment` | O5: two column names for one value |
| `entities[].attributes[].samples[]` | array of strings | A6: the table card's sample values, carried across unchanged — they come only from a file passed to `tables --samples` (already redacted and cut), and the key is absent when that column has none |
| `families[]` | `family` + `tables[]` + `size` | Q3: every table family the corpus names and the tables inside it, sorted by `family`; read it before answering a group, to check that the family really is one table written several times |
| `concepts[]` | `id` / `name` / `kind` / `identity` / `tables[]` / `attributes[]` / `tier` | K1: the tables that share one business key, folded into one concept; `entities[]` stay the table-level representations a concept merely points at (rules under "The concept layer" below) |
| `concepts[].kind`, `kind_tier`, `kind_evidence[]` | `entity` / `event` / `summary`; one of the five tiers; one vote per signal | K1: signals that agree earn `implied`, signals that disagree earn `hypothesis`, and every signal's vote is published as it was cast |
| `concepts[].tables[].role` | `primary` / `snapshot` / `detail` / `summary` / `intermediate` / `reference` | K1: which copy of the concept this table is; `reference` is a table that is not unique by the key but *carries* it, which is how an event table takes part in 客户 |
| `concepts[].tables[].membership_basis` | `key:<tier>` / `declared_hint` / `reference` | K1: what makes this table a member -- a candidate key the corpus read (carrying its own tier), a primary-key hint the catalog declared, or a JOIN |
| `concepts[].identity` | `stem` + `columns_seen[]` | K1: the concept's key stem, and the key columns the corpus reduced to it |
| `concepts[].name`, `name_tier`, `name_candidates[]` | text; always `hypothesis`; `text` / `source` / `count` / `name_evidence[]` | K2: candidates ranked by `count` desc, then by source order (key column comment → table comment → key stem); `name` is the first of them, and a comment is metadata that goes stale, so it never rises above `hypothesis` |
| `concepts[].possible_duplicate_of[]` | concept ids | K2: another concept's first name candidate is the same word. They are **not** merged; both point at each other and the review round decides. The key is absent when nothing else claimed the name |
| `unassigned_tables[]` | `table` + `reason` (`no_candidate_key` / `generic_key_only` / `key_spans_several_stems`) | K1: the tables no concept could take, and why -- "we could not tell" is an answer |
| `relations[].id` | `rel:NNN` | numbered after sorting, stable for one corpus |
| `relations[].kind` | `join_association` / `union_sibling` / `hinted` | a JOIN key pair, or two branches of one UNION; `hinted` is O9's edge -- proposed by a column comment and written by no task in the corpus (`task_count` 0, empty `join_types`) |
| `relations[].cardinality.claim` | `one_to_many` / `many_to_one` / `many_to_one_assumed` / `one_to_one_assumed` / `unknown` | O2, in the direction `from` → `to`; `one_to_one_assumed` can only come from a human confirmation |
| `relations[].cardinality.tier` | one of the five tiers | the confidence tier of this cardinality claim |
| `relations[].cardinality.basis` | `group_by` / `ranking_window` / `producer_key_confidence` / `right_side_not_deduplicated` / `union_branch_alignment` / `no_uniqueness_evidence` / `human_confirmation` / `column_comment` | what the cardinality rests on |
| `relations[].join_types`, `task_count` | the union of JOIN types, the task count | the JOIN types the same entity pair was joined with across tasks, merged |
| `relations[].evidence[].left_via_scopes` | a list of scope ids | where one side of the JOIN was a CTE, the scopes the walk pierced through to reach a physical table (`right_via_scopes` for the other side) |
| `concept_relations[]` | `from` / `to` / `type` / `cardinality` / `task_count` / `evidence[]` | K3: the table-level relations above, folded onto the concepts -- `evidence[]` is the member edges' ids and `task_count` the distinct tasks behind them (rules under "Concept relations" below) |
| `concept_relations[].from`, `to` | concept ids | K3: the two ends answer two different questions -- `from` is **what this table is** (the concept its own key or a declared hint placed it on, never a `reference` and never the columns this edge joined on), `to` is **what it points at** (the concept the `to` columns name, falling back to that table's own identity when they name none -- or when they name the very concept the `from` table already is) |
| `concept_relations[].type` | `association` / `participation` / `aggregation` / `derivation` / `self_reference` | K3: read off the two endpoints' `kind`, never off a word |
| `concept_relations[].roles[]` | a list of texts | K3: `participation` only -- what the entity is to the event, taken from the `from` side's column comment and stripped as a key comment is (发送方编号 → 发送方), or from the column name when the metadata says nothing. One group can carry several (发送方 and 接收方 are two edges between the same two concepts) |
| `concept_relations[].cardinality` | `claim` / `tier` / `basis[]` | K3: the strongest member claim -- tier first (`proven` > `confirmed` > `implied` > `hypothesis`), then a definite claim over `unknown`; `basis[]` names the table-level relations that carried it |
| `concept_representation_links[]` | `concept` + `from_table` + `to_table` + `evidence[]` | K3: both ends on one concept while the two *tables* are both representations of it (a snapshot joined onto its primary) -- a seam in K1's fold rather than a relation, so it gets its own section |
| `concept_relations_unmapped` | `total` + `by_reason` (`from_table_unplaced` / `to_table_unplaced`) | K3: the table-level relations that could not be folded, counted by **which end** failed to answer; the `from` end is asked first, so an edge that fails both is counted once under `from_table_unplaced`. A wrong fold is worse than a missing one |
| `constraints[].kind` | `not_null` / `in_set` / `unique_per` / `partition` | O6 |
| `constraints[].values`, `completeness` | a value list, `complete` / `unknown` | `in_set` only: only a closed `IN` list or an exhaustive CASE is `complete` |
| `constraints[].columns` | a list of column names | `unique_per` only: the candidate keys plus the partition columns |
| `constraints[].note` | one sentence | `not_null` only: "the task discarded the NULLs with a filter; the source itself may still hold some" |
| `findings[].kind` | `cardinality_conflict` / `competing_candidate_keys` / `key_hint_conflict` / `relation_hint_conflict` / `producer_key_conflict` / `ambiguous_bare_name` | O7, O8 and O9; the last two are carried over from the table cards |
| `findings[].tasks` | role → task names | which tasks stand on each side of the contradiction |
| `findings[].keys[]` | two sets of `columns` + `evidence` | `competing_candidate_keys` only: the two competing key sets with the evidence behind each |
| `open_items[]` | `id` / `kind` / `entity` / `relation` / `columns` / `tier` / `write_back` / `text` | H5: the whole corpus's open list, one entry per `hypothesis` key, `hypothesis` relation and finding; a relation appears once, not once per side |
| `open_items[].id` | `open:key:<table>=<col+col>` / `open:rel:<relation write-back key>` / `open:finding:<kind>:<table>=<cols>` | derived from the question itself, so the same question keeps the same id in the next round |
| `open_items[].kind` | `candidate_key` / `relation` / `finding` | the array order is the suggested answering order: findings, then relations by `task_count` descending, then candidate keys |
| `open_items[].write_back` | `键:<table>=<col+col>` / `关系:<write-back key>` / `null` | where the answer is filed in `ontology.overrides.json`; a cross-task contradiction has no single target and carries `null` |
| `open_item_groups[]` | `group_id` / `kind` / `family` / `shape` / `representative` / `items[]` / `count` / `impact` / `write_back_pattern` | Q3: the list above folded by (kind, table family, question shape) -- one group is one question asked of a whole family; a relation groups by its **far** side, so `family` is the far table's; `items[]` holds every item id in it and `representative` the highest-ranked one |
| `open_item_groups[].group_id` | `open:group:key:<family>=<col+col>` / `open:group:rel:<far family>=<far col+col>` / `open:group:finding:<family>=<kind>` | derived from the content as well, so it survives the next round; section 11 of a card cites it beside the item id |
| `open_item_groups[].impact` | a non-negative integer | what answering the group unblocks: for a relation the tables joining the far side plus the tasks that do, for a candidate key the assumed edges confirming it would prove, for a finding the items it holds; the array order is `impact` descending, then `count` descending, then the representative's rank |
| `open_item_groups[].write_back_pattern` | `键:<table>=<col+col>` / `关系:<near end>.<col+col>-><table>.<col+col>` / `null` | the group's write-back key, where `<table>` is the table the group is about (the far one for a relation) and a near side the members disagree on reads `<from_table>` / `<from_columns>`: answer once, then file it per table in the family; a finding with no single target carries `null` |
| `finding_groups[]` | the same shape as `open_item_groups[]` | the subset of `open_item_groups[]` whose `kind` is `finding`, published on its own because the index's 待人工判定 table renders only those |
| `overrides_applied` | `relations` / `keys` / `unmatched` / `ignored_fields` | how many human confirmations this run merged, which of them matched nothing in the corpus, and which fields this release does not understand |
| `concept_overrides_applied` | `concepts` / `merges` / `splits` / `unmatched` / `ignored_fields` | K4b: how many field confirmations, merges and splits the reviewed `concepts.overrides.json` applied, and which ids, tables or field names matched nothing in the corpus |

## The inference rules

| Rule | Content |
| --- | --- |
| O1 relations | a JOIN's `join_key_pairs` are grouped into edges by (left table, right table); a CTE side is pierced to its physical table by R3's driving-input walk and the path is recorded; the branches of a UNION pair up as `union_sibling` with columns aligned by position |
| O2 cardinality | the right side grouped or ranked by the join keys before the JOIN → `one_to_many` (`implied`); a physical right side whose key some producing task proved unique → `many_to_one` (`proven`); a physical table joined directly → `many_to_one_assumed` (`hypothesis`); anything else `unknown` |
| O3 multiplicity | any task grouping or window-partitioning table T by key set K → T holds many rows per K (`implied`); a key set spanning two tables asserts nothing about either |
| O5 synonyms | a DIRECT `end_to_end_lineage` entry whose column names differ → `direct_rename` (`proven`); differently named columns in the same UNION position → `union_alignment` (`implied`); both ends record each other |
| O6 constraints | a `NOT x IS NULL` filter → `not_null` (`hypothesis`, with the note that the task discarded NULLs and the source may still hold some); an enumerable code → `in_set`; a partition column → `partition` (`proven`); a produced table's candidate keys plus its partition columns → `unique_per` (key confidence `proven` → `proven`, `candidate` → `hypothesis`). **One claim, one entry**: constraints sharing an (entity, kind, columns/values) are merged into one, keeping the strongest `tier` among them and the union of their `evidence[]` in corpus order -- a table two tasks write with the same key set is one constraint proved twice, not two constraints |
| O7 conflicts | "deduplicated" and "joined directly" on the same (table, key set) → `cardinality_conflict`; two `hypothesis` candidate keys on one table where one is a strict subset of the other or the two are disjoint → `competing_candidate_keys` (at most one of them is the identity); the cards' `producer_key_conflict` and `ambiguous_bare_name` are carried over verbatim |
| O8 metadata key hints | a column comment holding `主键` / `唯一键` / `唯一编号` / `主键id` / `primary key` / `unique` (case-insensitive) → `declared_hints`; a hint that agrees with a `hypothesis` candidate key (hint columns are a subset of the key's) raises that key to `implied` (comment and structure are two independent sources pointing at one column); candidate keys that are all `hypothesis` and none of which hold the hinted column → `key_hint_conflict` |
| O9 comment relation hints | a column comment pointing at `<table>.<column>` or `<表> 的 <列>` with `关联` / `对应` / `引用` / `见` / `外键` / `FK` / `references` / `->` (case-insensitive; the table name is matched by the cards' own dotted-suffix rule, case-folded, and a bare name resolves only when one entity could be it) → `relation_hints[]`; a `hypothesis` relation already published for the same (from entity, to entity) and the same column pair → raised to `implied` with a `column_comment` evidence item; none → a new `kind: hinted` relation (`many_to_one_assumed` / `hypothesis` / `column_comment`, `task_count` 0) that joins the open list for a person to confirm; a `proven` relation out of the same column landing on another table → `relation_hint_conflict` |

## The concept layer (entity / event / summary)

`entities[]` answer "what is this **table**". That is not what a business asks. A business
asks about 客户 (the customer), and the warehouse spells the customer as
`ods.customer_base`, `dwd.customer_df`, `dwd.customer_di` and a few staging copies. It
also asks about 消息发送 (message sending), which is not a thing but something that
*happened* -- a sibling of the customer, not a child of it.

K1/K2 fold that layer on top of the table-level ontology: **the entity is 「客户」, not
「客户信息表」; a table is how a concept is represented.** Not one field of `entities[]`
changes -- a concept merely points at them, and the table-level reading is the only way
to check the fold.

### The seed: a key stem

| # | Rule |
| --- | --- |
| 1 | **Key stem**: lowercase the column, split on `_`, drop the leading and trailing whole segments that only say "this is a key" (`_no` / `_id` / `_code` / `_cd` / `_num` / `_key`), never the last segment left -- `cust_no` and `cust_id` are both `cust`. Columns the corpus itself proved synonymous (O5) are folded to one spelling first, so `customer_id` reaches `cust` because some task proved the two columns hold the same value, never because the two words look alike |
| 2 | **Generic stems**: `id` / `uuid` / `dt` / `etl` / `create` / `update` / `row` / `seq` / `rn` / `pk` are the closed list; one evidence rule adds to it -- a stem whose key columns carry three or more *different* non-empty comments that share no two-character Chinese fragment once 编号/编码/代码 are taken off is generic too (渠道编码 / 省份编码 / 状态编码 agree on nothing that matters) |
| 3 | **Seeding**: an entity whose candidate key at **any** tier (a warehouse rarely proves its own keys, and reading only `proven` leaves nearly every table unplaced) reduces, once time and partition columns are set aside, to exactly one non-generic stem seeds that stem's concept and joins it as `key:<tier>`; the tier travels with the membership |
| 4 | **Declared hints**: when no candidate key lands, `identity.declared_hints[]` is read -- a column comment calling a column the primary or unique key seeds the same way, with basis `declared_hint` |
| 5 | **JOIN participation**: when a relation's (`join_association` / `hinted`) **`to`** columns reduce to a concept's stem, the `from` entity joins that concept as `reference`. An event table is never unique by 客户 -- it merely *carries* the customer number, and that is how it takes part. A `reference` membership is deliberately the weakest one: it casts no kind vote and lends no attribute |
| 6 | **No seed**: a key that is all generic, a key that spans two stems, or no key and no hint and no JOIN onto any concept -- the table goes to `unassigned_tables[]` with the reason |

### Member roles

The cascade runs from the most specific evidence to the least, first match wins:

| Role | Test |
| --- | --- |
| `intermediate` | the table name ends in `_tmp` / `_mid<n>` / `_step<n>` / `_stage<n>` / `_bak`, or exactly one task both writes and reads it |
| `detail` | the key carries a time or event column beyond the stem (and it is not a partition column) |
| `primary` | a full snapshot (`_df` / `_hf` / `_mf` / `_wf` / `_all`) or no period suffix at all, and the key is the stem alone once partition columns are set aside |
| `summary` | the producing statement's `output_shape.grain.basis` is `group_by` or `single_row` |
| `snapshot` | a period increment (`_di` / `_hi` / `_mi` / `_wi`), the key is the stem alone once partition columns are set aside, and there is no event time |
| `reference` | not unique by the key, merely carrying it -- the membership came from a JOIN rather than from the table's own key |

### The concept kind

| Signal | Vote | What it reads |
| --- | --- | --- |
| `key_event_column` | `event` | a member's key holds a timestamp or event-id column that is not a partition column |
| `driving_rows_over_log_source` | `event` | the producing grain is "one row of the driving table", and that driving table looks log-like by name or comment |
| `increment_with_event_time` | `event` | the member is a `_di` / `_hi` increment and carries a non-partition time column |
| `all_members_summary` | `summary` | every member's role is `summary` |
| `word_hint` | any of the three | words in the name and the comment: 发送/回款/交易/日志/记录/流水/事件/log/event/hist → `event`; 信息/档案/主数据/维/dim/info → `entity`; 汇总/日报/统计/agg/report → `summary`. **Secondary evidence**: it never decides once a structural signal has spoken |

`event` among the structural signals wins; otherwise `summary` among them; otherwise the
word hints decide, and an unvoted concept is an `entity`. When **every** signal voted the
same way, `kind_tier` is `implied`; as soon as two votes differ it is `hypothesis`, and
`kind_evidence[]` names each signal, its vote and the table it read, so a reviewer sees
exactly where the disagreement is.

### Naming candidates

| Source | How | Negative |
| --- | --- | --- |
| `key_column_comment` | **annotation blocks** (`【…】` / `[…]`) and the trailing aside come off first, then **at most one** trailing key marker (编号/编码/代码/号码/标识/号): 合同号 → 合同, 交易流水号 → 交易流水. Fewer than two Chinese characters left means no candidate at all (编号, 客编号), and the 号 inside a whole word -- `账号`, `卡号`, `型号` -- never comes off (贷款账号 stays 贷款账号) | the Chinese stoplist (唯一, 主键, 标识, 编号, 编码, 代码, 序号, 流水号) matches as a **prefix**, because 唯一键, 唯一主键 and 主键id are all the marker plus noise; the latin one (id, unique, key, guid, uuid, pk, no, code) matches whole, because `id` and `key` open plenty of real English phrases; a single Chinese character, or no Chinese and equal to the stem, also yields nothing |
| `table_comment` | annotation blocks (`【…】` / `[…]`) and the trailing aside come off first, then pipeline words (中间过程/过程表/临时/备份/backup/tmp) wherever they sit, then the storage words (信息表/明细表/汇总表/临时表/记录表/快照/维表/日表/表 …); only the **most representative** rank of members is read (`primary` / `snapshot` → `detail` / `summary` → `intermediate` / `reference`, the first rank that answers at all), and members of that rank that disagree keep their longest common prefix | a comment that is only a suffix (「信息表」) yields nothing |
| `key_stem` | the stem itself (`cust`), as a last resort | -- |

Stripping suffixes is a Chinese metadata convention, so it **only applies to text that
holds Chinese**: an English snake-case comment is kept exactly as the catalog wrote it,
and the only latin suffixes stripped are the ones a `_` already marked as a segment
(`_id` / `_no` / `_df` …). Ranking asks first whether a candidate still reads as a table
name -- anything that kept an `_`, a `backup` or a `tmp` sinks below everything else,
and is kept rather than dropped because it is still evidence -- then by `count` desc,
then by the source order above. `name` is the first of them, `name_tier` is always
`hypothesis`, and every candidate keeps a `name_evidence` saying which table and column
supplied it -- so disagreeing metadata is visible rather than averaged away.

When two concepts' first candidates land on the same word (the stems `contr` and
`contra` both proposing 「合同」), they are **not** merged: the corpus proved two
distinct keys, and whether that is one thing spelled twice or two things sharing a
word is not a question this layer can answer. Each gets a `possible_duplicate_of`
pointing at the other, and the review round decides.

### Concept relations

The table-level `relations[]` answer "which two **tables** did a task join, on which
columns, and how many rows does that imply". That is not what a business asks. It asks
whether 「消息发送」 involves 「客户」 and in which role -- 发送方 or 接收方 -- and whether
「客户日汇总」 aggregates that event or that entity. K3 folds each table-level edge onto
two concepts, groups the result by (from concept, to concept), and publishes it as
`concept_relations[]`.

**The two ends of an edge answer two different questions.** Reading both the same way
folds nearly every edge onto itself:

| End | The question | How it is answered |
| --- | --- | --- |
| `from` | what this table **is** | the concept its own candidate key (at any tier) or a declared primary-key hint placed it on. **Not** the columns this edge joined on, and **never** a `reference` membership a JOIN lent it -- an event table joins 客户 precisely **on** `cust_no`, and is a `reference` member of 客户 for that very reason, so reading its columns answers 客户 → 客户 |
| `to` | what it **points at** | the concept named by the stem the `to` columns reduce to (the same `key_stem` K1 seeds with, folded across the same O5 synonyms); only when no stem is named does it fall back to that table's own identity. **One mirror-image exception**: when those columns name the very concept the `from` table *is*, they say nothing new (the two tables share that key, which is why the JOIN could be written at all), so a `to` table the corpus placed elsewhere wins -- 客户 joined onto 消息发送 on `cust_no` is a participation written the other way round, not 客户 → 客户. A `to` table that really is the same concept (a self-join, or a snapshot of it) has nothing else to reach for and keeps the stem's answer |

An end that answers neither leaves the edge out, counted in
`concept_relations_unmapped`: `from_table_unplaced` is a `from` table with no identity of
its own (only reached by a JOIN, or placed on no concept at all), and
`to_table_unplaced` is a `to` side whose columns named no stem and whose table has no
identity either. The `from` end is asked first, so an edge that fails both is counted
once, under `from_table_unplaced`. A wrong fold is worse than a missing one.

The type is read off the two endpoints' `kind`, never off a word:

| Type | The endpoints | What it says |
| --- | --- | --- |
| `association` | entity ↔ entity | an association between two entities |
| `participation` | event ↔ entity | the entity takes part in the event; `roles[]` says as what (发送方 / 接收方 / 客户) |
| `aggregation` | summary ↔ event, summary ↔ entity | the summary aggregates that event or that entity |
| `derivation` | event ↔ event, summary ↔ summary | one is derived from the other of the same kind |
| `self_reference` | one concept on both sides | 上级客户 → 客户 and its like; the business really has that relation, so it is kept |

When both ends land on one concept and the two *tables* are both representations of it
(a snapshot joined onto its own primary), that is not a relation the business has -- it
is a seam in K1's fold. Those edges stay out of `concept_relations[]` and are published
in `concept_representation_links[]` instead: the concept, the two tables, and the
table-level relation ids that said so. A table joined to **itself** is the other case,
and stays a `self_reference`.

`cardinality` is the **strongest** member claim: tier first (`proven` > `confirmed` >
`implied` > `hypothesis` -- what the corpus proved outranks what a reviewer confirmed for
a single pair of tables, because this layer folds the corpus), then a definite claim over
`unknown`; `basis[]` names the table-level relations that carried it. `evidence[]` is
every member relation's id and `task_count` the distinct tasks behind them (the tasks
that **wrote** the edge, the same discipline `relations[].task_count` keeps).

A concept carrying `possible_duplicate_of` is **not** merged: its relations stay on its
own id. Whether the two are one thing is the review round's question, and answering it
here would only hide it.

The order is fixed: by type (`association` → `participation` → `aggregation` →
`derivation` → `self_reference`), then by the `from` concept id, then by the `to`
concept id; `concept_representation_links[]` is ordered by concept, then the two tables.

### How the concept layer is rendered

`ontology.md` opens on 「概念层」, **before** the table-level ER: a reader of this file is
asking a business question, and the ER diagram below is the evidence the answer was read
off rather than the answer. Four blocks, in a fixed order:

| Block | Contents |
| --- | --- |
| The concept diagram | one box per concept, labelled `<name>（<kind>）` and filled by kind (`classDef entity` / `event` / `summary`). It is a `flowchart LR` rather than an `erDiagram` because Mermaid's ER diagram has no `classDef`, and the boxes here carry a business name and a kind -- the kind being half of what there is to see. The edges come from `concept_relations[]`, labelled 「type: cardinality」, with `?` for a cardinality that is only the author's assumption and a `participation`'s roles in brackets. `concept_representation_links[]` is **not** drawn: that is a seam in K1's fold, not a relation. Past 40 concepts (`CONCEPT_MERMAID_LIMIT`) it keeps the 40 with the most concept relations and says how many it left out |
| The concept table | one row per concept: the name, the kind with its tier, how many tables represent it (counted per `role`, **not** listed), the first three name candidates (`CONCEPT_NAME_CANDIDATES_SHOWN`), and whatever `possible_duplicate_of` points at |
| The concept-relation table | one row per relation: the type, both concept names, the participation roles, the cardinality with its tier, and how many table-level edges are behind it |
| The unplaced tables | one line: how many tables landed on no concept and the three most common reasons (`UNASSIGNED_REASONS_SHOWN`) with a count each; the table-by-table list stays in `ontology.json`'s `unassigned_tables[]` |

Section 7 of each table card, 身份（本体）, gains an opening line saying which copy of which
concept this table is and what put it there: 「本表是「客户」（`concept:cust`，实体）的主表视图
（`key:proven`）。」 A table can be a member of two concepts at once -- defined by one key and
carrying another -- and then each membership gets its own line; a table nothing could place
says 「未归入任何概念（`no_candidate_key`）。」, because "we could not tell" is an answer and
deserves to be printed.

## Table families and the folded open list

A warehouse writes one logical table many times: `_di` is today's increment, `_df` the
full snapshot, `_tmp` and `_mid01` the steps that built it. The ontology asks each copy
the same question, so the flat list repeats one decision a dozen times -- honest, and
unreadable. Q3 folds it, mechanically:

| # | Rule |
| --- | --- |
| 1 | **Table family**: lowercase the name, split it on `_`, and strip trailing segments while they are period suffixes (`_di` / `_df` / `_hi` / `_hf` / `_mi` / `_mf` / `_wi` / `_wf` / `_all`), stage suffixes (`_tmp` / `_mid<digits>` / `_step<digits>` / `_stage<digits>` / `_bak` / `_new` / `_old` / `_v<digits>`) or a purely numeric tail. Whole segments only, so `_dim` is not `_di` and `_info` is not `_i`; the database stays, and the last segment is never stripped (a table really called `tmp` is its own family) |
| 2 | **Group key**: (kind, table family, question shape). A candidate key's shape is its column set; a finding's is the finding `kind`; **a relation groups by its far side** -- an edge's open question is "is that table unique on these columns", which neither the producer nor the name it gives its own column changes, so the key is (far table's family, far columns) and the family fold only merges the copies of that far table |
| 3 | **Inside a group**: the items keep the flat list's order, the first of them is the `representative`, and `count` is how many there are |
| 4 | **Impact**: `impact` is what answering the group unblocks -- for a relation, the number of tables that join the far side plus the number of tasks that do; for a candidate key, the number of assumed edges that confirming it would prove; for a finding, the number of items it holds |
| 5 | **Between groups**: by `impact` descending, then `count` descending, then where the representative ranks in the flat list. Ranking a folded list by size still reads "most repeated" rather than "most worth answering"; findings are no longer forced to the front, because they already have their own section above |
| 6 | **Write-back pattern**: the group's write-back key, where `<table>` is **the table the group is about** (the entity for a key or a finding, the far table for a relation); everything else in the key becomes a placeholder only when the members disagree on it (a relation's near table → `<from_table>`, its near columns → `<from_columns>`), because a placeholder that can only be filled one way is noise |

The fold is **a view, not a merge**: every question is still in `open_items[]`, and an
answer in `ontology.overrides.json` still binds one concrete table. A group that has been
answered therefore shrinks by the number of tables confirmed rather than disappearing
whole -- `items[]` and the cards say which tables those were.

So both index sections print one row per group: 「待人工判定（N 条，折叠为 G 组）」 for the
findings and 「待人工判定清单（N 条，折叠为 G 组）」 for everything open, the latter with an
`影响` column carrying the number it is ranked on. Each prints the first 50 groups
(`OPEN_ITEM_GROUPS_SHOWN`) and summarises the rest in one line, 「另有 K 组 M 条」, pointing
at `open_item_groups[]` / `finding_groups[]` in `ontology.json`. The flat, item-by-item
list is no longer in the markdown; it is in the JSON.

## The per-table card: five sections appended to the table card

`<dir>/tables/<db.table>.md`, written by `ontology --out <dir>`, *is* the `scope-lineage
tables` card (1 what this table is / 2 what one row means / 3 columns / 4 who writes it /
5 who reads it / 6 governance leads), with these appended after it:

| Section | Contents |
| --- | --- |
| 7. 身份（本体） | opens with which copy of which concept this table is (「本表是「客户」（`concept:cust`，实体）的主表视图（`key:proven`）。」, one line per membership), or 「未归入任何概念（`<reason>`）。」 when nothing placed it; then 「属性 N（语料用到 n）」, the same count the entity table in `ontology.md` carries; then candidate keys, the metadata key hints, multiplicity and partition columns side by side, each with its tier in Chinese and its evidence ids; a confirmed key prints who confirmed it, when, and on what basis on the same line, and a key with `scope_columns` reads 「在 `dt` 内唯一」; the four answer four different questions and are never merged into one "primary key" |
| 8. 关系 | one table for outgoing and one for incoming edges: the other end (linked to its card), the key pair, the JOIN types, the cardinality claim, the tier, the basis token in plain words, the task count and the evidence ids; a 「注释线索」 sub-block follows when this table's column comments point somewhere (O9): own column → other table.column, the comment verbatim, and the reason where it could not be resolved; no hints, no sub-block |
| 9. 约束 | a SHACL-shaped list: the constraint kind, the target column or the whole table, the value set and its completeness, the tier, the evidence |
| 10. 属性同义 | this table's column ↔ the synonym, the basis (a renaming projection / the same UNION position), the tier, the evidence |
| 11. 待人工判定 | the findings about this table plus every `hypothesis` assertion (candidate key / cardinality / constraint), each marked `[待确认]`, carrying the write-back key its answer is filed under, and citing both its id in `open_items[]` and its group in `open_item_groups[]` (「清单 `open:…`，组 `open:group:…`」 -- the group id tells whoever answers which other tables of the family the answer covers) |

The filename rule is exactly `tables`' own (`<db.table>.md`, with anything a file system
would choke on replaced by `_`), so a corpus can be run through `tables` and then through
`ontology`, the latter overwriting the former's card directory in place, and the relative
links between the cards still hold.

## The Mermaid ER mapping rules

The first section of `ontology.md` is an `erDiagram` block. Mermaid entity names are
identifiers, so every character of an entity id outside `[A-Za-z0-9_]` — including `.` and
`-` — is replaced by `_`; when two different entities flatten to the same name, the later
one (in the corpus's own sort order) takes a numeric suffix rather than merging two
entities into one box. The entity table's "图中 id" column is that lookup. An entity block
lists the candidate-key columns and marks them `PK`; an entity without candidate keys is
declared bare rather than with an empty `{}`.

| Cardinality claim | ER symbol | Reading |
| --- | --- | --- |
| `one_to_many` | `\|\|--o{` | one row on the left, many on the right |
| `many_to_one` | `}o--\|\|` | many rows on the left, one on the right (proved by some producing task) |
| `many_to_one_assumed` | `}o--\|\|` | the same shape, but only the author's assumption |
| `one_to_one_assumed` | `\|\|--\|\|` | one to one; only ever from a human confirmation |
| `unknown` | `}o--o{` | no uniqueness evidence, which also covers every `union_sibling` edge |

The edge label carries the join keys (`a = b`, comma separated for several columns); an
edge at tier `hypothesis` gets a trailing `?`, and an edge whose key set is named by a
`cardinality_conflict` gets a `!`. Past 60 entities the diagram keeps the 60 with the
highest relation degree and says above it how many were left out; the full list is still
in the entity table.

```mermaid
erDiagram
    ods_orders {
        string order_id PK
    }
    ods_customer
    ods_orders }o--|| ods_customer : "customer_id = id ?"
```

## Writing confirmations back: `ontology.overrides.json`

Every line under 待人工判定 is a question, and a question that has been answered must stop
being asked. Folded, the unit of answering is a group: take its `write_back_pattern`,
replace `<table>` with each table the family holds in `families[]`, and file one override
per table -- **a confirmation always binds a concrete table**; there is no such thing as
confirming a family. An agent turns those items into a list a business owner can answer,
following
`skills/scope-lineage/references/ontology-review-prompt.md`, the answers are merged into
`ontology.overrides.json`, and the corpus is re-run with `--overrides`:

```json
{
  "relations": {
    "ods.orders.customer_id->ods.customer.id": {
      "cardinality": "many_to_one",
      "basis": "two tasks join on this key set",
      "confirmed_by": "王某",
      "date": "2026-09-19"
    }
  },
  "keys": {
    "ods.customer": {
      "columns": ["id"],
      "scope_columns": ["dt"],
      "basis": "the column comment names it the primary key",
      "note": "a snapshot table: one full copy per partition",
      "confirmed_by": "王某",
      "date": "2026-09-19"
    }
  }
}
```

| Slot | Values | Meaning |
| --- | --- | --- |
| the key of `relations` | `<from entity>.<col+col>-><to entity>.<col+col>` | character for character the write-back key the card prints under 待人工判定; copy it rather than reconstructing it |
| `relations[].cardinality` | one of the five claims | the confirmed cardinality; leaving it out keeps the corpus's own claim and only raises the tier to `confirmed` |
| the key of `keys` | an entity id | that table's identity key; a key the corpus never guessed can be added outright |
| `keys[].columns` | a list of column names | the columns that make up the identity, in the order the card shows them; every one of them must be an attribute of that entity (declared or used by the corpus), or the whole entry is not merged |
| `keys[].scope_columns` | a list of column names | the key is unique only within one value of these columns (the normal shape of a snapshot table); the card renders it as 「在 `dt` 内唯一」 |
| `confirmed_by`, `date` | free text | who confirmed it and when, written into the evidence verbatim |
| `basis`, `note` | free text | why the answer is believed, and anything else worth recording, published beside `confirmed_by` / `date`; `basis` is published as `confirmed_basis` — `basis` on a cardinality is a machine token, and one slot cannot be a vocabulary and a sentence at once |
| `overrides_applied.unmatched` | a list of `{"key": …, "reason": …}` | confirmations with nothing to match in the corpus — never dropped, listed so a reviewer can see them; `reason` is `unknown_entity: X` / `unknown_column: X` / `missing_columns` / `unknown_relation` / `unparsable_key` |
| `overrides_applied.ignored_fields` | a list of `{"key": …, "fields": ["…"]}` | fields this release does not understand (usually a misspelled slot name) — listed rather than silently dropped |

After the merge those assertions carry `tier: "confirmed"` and `basis:
"human_confirmation"`, and one more evidence item, `{"kind": "human_confirmation",
"confirmed_by": …, "date": …, "confirmed_basis": …, "note": …}`. `confirmed` is the one tier the corpus can never produce
by itself. A confirmation does not silence the corpus's own `findings`: whether a
contradiction still exists is decided by O7 the next time the corpus is parsed.

## Writing concept confirmations back: `concepts.overrides.json`

Everything the concept layer publishes is a **candidate**: the name is always a
`hypothesis`, the kind is decided by votes, and whether two stems are one thing is a
question this layer refuses to answer for anybody. `concepts.overrides.json`
(`doc_format: "concept-overrides/1"`) is the only way those candidates reach `confirmed`.
An agent works one round following
`skills/scope-lineage/references/concept-review-prompt.md` -- kind → name → merges →
splits → roles -- writing what the corpus itself answers into this file, turning the rest
into questions, merging the answers when they come back, and re-running the corpus with
`--concept-overrides`:

```json
{
  "doc_format": "concept-overrides/1",
  "concepts": {
    "concept:cust": {
      "name": "客户",
      "kind": "entity",
      "roles": {"tmp.cust_step01": "intermediate"},
      "basis": "the key column comment names it 客户编号",
      "note": "reviewed with the owner of the 客户 domain",
      "confirmed_by": "agent:concept-review",
      "date": "2026-09-22"
    },
    "concept:party": {
      "merge_into": "concept:cust",
      "basis": "O5 proved the two key columns hold the same value",
      "confirmed_by": "王某",
      "date": "2026-09-22"
    }
  },
  "splits": [
    {
      "from": "concept:acct",
      "into": [
        {"name": "签约账户", "tables": ["ods.acct_base"]},
        {"name": "申请账户", "tables": ["ods.acct_apply"]}
      ]
    }
  ]
}
```

| Slot | Values | Meaning |
| --- | --- | --- |
| the key of `concepts` | `concept:<stem>` | the concept id, character for character as the concept table and card section 7 print it |
| `name` | free text | the confirmed business name; `name_tier` becomes `confirmed` |
| `kind` | `entity` / `event` / `summary` | the confirmed kind; `kind_tier` becomes `confirmed`. Anything else is reported as `unknown_kind: X` and does not take effect |
| `roles` | `{"<table>": "<role>"}` | moves one member table to another role, one of K1's six; that member gains `role_tier: "confirmed"` |
| `merge_into` | another concept id | folds this concept into that one: its tables, attributes and key stem all travel, and its id is kept in the survivor's `merged_from[]` |
| `splits[]` | `{"from": …, "into": [{"name", "tables"}]}` | splits one concept by naming tables; the new ids are `concept:<stem>-<n>`, numbered as `into[]` lists them. Tables nobody claimed stay on the original, which stops being published when they all leave |
| `confirmed_by`, `date` | free text | who confirmed it and when; an agent answering on evidence writes `agent:<name>` rather than impersonating a person |
| `basis`, `note` | free text | why the answer is believed and anything else worth recording, published in the concept's `confirmation` (`basis` as `confirmed_basis` -- `membership_basis` beside it is a machine token, and one word cannot be a vocabulary and a sentence at once) |
| `concept_overrides_applied.concepts` / `merges` / `splits` | integers | how many field confirmations, merges and splits took effect |
| `concept_overrides_applied.unmatched` | a list of `{"key": …, "reason": …}` | confirmations with nothing to match in the corpus — never dropped, listed; `reason` is `unknown_concept` / `unknown_concept: <id>` / `unknown_table: <table>` / `unknown_kind: <value>` / `unknown_role: <value>` / `merge_into_self` |
| `concept_overrides_applied.ignored_fields` | a list of `{"key": …, "fields": ["…"]}` | fields this release does not understand (usually a misspelled slot name) — listed rather than silently dropped; stray keys on the document itself are filed under `(document)` |

**The order is deliberate**: the field edits first (name, kind, roles), then the merges,
then the splits -- the order a reviewer arrives at them, and the last two change which
tables a concept holds. The whole pass runs **before** K3 folds the concept relations, so
a merge carries the folded concept's edges with it instead of leaving them on an id
nothing publishes any more.

## Slot correspondence with OWL / SHACL / LinkML

The JSON carries everything, and the exporter (`--export linkml,shacl`, the next
section) is a thin layer. The slots are deliberately aligned as below so that layer did
not need this document's structure to change; the OWL column is a correspondence only,
with no exporter behind it:

| ontology.json | OWL / RDFS | SHACL | LinkML |
| --- | --- | --- | --- |
| `entities[]` | `owl:Class` | `sh:NodeShape` | `class` |
| `entities[].attributes[]` | `owl:DatatypeProperty` | `sh:property` + `sh:datatype` | `attribute` / `slot` |
| `relations[]` | `owl:ObjectProperty` (+ cardinality axioms) | `sh:property` + `sh:class` + `sh:maxCount` | a slot with a `range` |
| `constraints[].kind = in_set` / `not_null` | — | `sh:in` / `sh:minCount` | `enum` / `required` |
| `constraints[].kind = unique_per` | — | no native uniqueness; needs a SPARQL constraint | `unique_keys` |
| `tier` / `evidence` | annotation properties (`rdfs:comment` or a custom annotation) | annotations | `annotations` |

## Exporting LinkML / SHACL

`--export` turns the table above into files. That layer is a **rename, not a
re-derivation**: the JSON already carries everything, and the exporter only translates
the slots into another vocabulary. If an export says something the JSON does not, that is
a bug.

```bash
# Writes ontology.linkml.yaml and ontology.shacl.ttl beside ontology.json
scope-lineage ontology --lineage /path/to/corpus --out /path/to/ontology \
  --export linkml,shacl

# --export repeats, and is independent of --format: json only still exports
scope-lineage ontology --lineage /path/to/corpus --out /path/to/ontology \
  --format json --export linkml --export shacl
```

| File | Target format | Contents |
| --- | --- | --- |
| `ontology.linkml.yaml` | a LinkML schema | a class per entity, a slot per attribute, an enum per closed value set |
| `ontology.shacl.ttl` | SHACL (Turtle) | an `sh:NodeShape` per entity, an `sh:property` per assertion |

Nothing is exported by default; `--export` accepts `linkml` and `shacl` only, and any
other value is an argument error (exit code 2). Both formats are emitted as text by this
repository's own deterministic writers, so the export adds **no new runtime dependency**;
the same corpus twice gives the same bytes, for the same reason `ontology.json` does.

### How the slots land

| ontology.json | LinkML | SHACL |
| --- | --- | --- |
| `entities[]` | a `class`, whose id is the safe identifier the Mermaid ER already uses, with the warehouse name in `title` | `sh:NodeShape` + `sh:targetClass`, with the warehouse name in `rdfs:label` |
| `entities[].attributes[]` | a slot under `attributes`, `range` from the SQL type, `description` from the column comment | `sh:property` + `sh:path` + `sh:datatype` |
| a single-column `proven` / `confirmed` candidate key | `identifier: true` on the slot | no native form, see the limitations below |
| every other candidate key (composite, or unproven) | a `unique_keys` entry, with the tier in `annotations.tier` | an `sl:candidateKey` annotation block |
| `relations[]` | a slot on the source class, `range` is the target class, `multivalued` from the cardinality | `sh:property` + `sh:class` (plus `sh:maxCount 1` when it is many-to-one) |
| `constraints[].kind = not_null` | `required: true` on the slot | `sh:minCount 1` |
| `constraints[].kind = in_set` (closed) | an `enum`, and the slot's `range` points at it | `sh:in ( … )` |
| `constraints[].kind = in_set` (open) | an annotation only, no enum | an `rdfs:comment` only |
| `constraints[].kind = unique_per` | a `unique_keys` entry | an `sl:compositeKey` annotation block, see the limitations below |
| `constraints[].kind = partition` | one annotation on the slot | an `sh:property` carrying only an `rdfs:comment` |
| `tier` | `annotations.tier` | `sl:tier` |
| `entities[].naming_hints` `domain` / `project` / `owner` | one annotation each on the class | `sl:domain` / `sl:project` / `sl:owner` on the node shape |
| `entities[].identity.declared_hints[]` | one `declared_hint_<column>` annotation per hint, column and text | an `sl:declaredKeyHint` annotation block |
| `entities[].relation_hints[]` | one `relation_hint_<column>` annotation per hint, resolved target or the reason it is not | an `sl:relationHint` annotation block |
| `entities[].identity.multiplicity[]` | one `multiplicity_<columns>` annotation, claim and tier | an `sl:multiplicity` annotation block |
| `entities[].attributes[].synonyms[]` | a `synonyms` list annotation on the slot, each entry with its `via` and tier | an `sl:synonym` annotation block |
| `findings[]` | a schema-level `sl:finding_NNN` annotation | an `sl:finding` block on the `sl:Ontology` node |
| `open_items[]` | a schema-level `sl:open_item_<id>` annotation | an `sl:openItem` block on the `sl:Ontology` node |
| `evidence[]` | `evidence_count` plus `evidence_task`, never the list | `sl:evidenceCount` plus `sl:evidenceTask` |

SQL types map as below, and a parameterized type is matched on its head: `decimal(18,2)`
is `decimal` and `map<string,string>` is `map`. A type nothing recognizes lands on
`string` rather than dropping the column -- the corpus usually does not know a physical
table's types at all.

| SQL type | LinkML `range` | SHACL `sh:datatype` |
| --- | --- | --- |
| `string` / `varchar` / `char` / anything else | `string` | `xsd:string` |
| `tinyint` / `smallint` / `int` / `bigint` | `integer` | `xsd:integer` |
| `decimal` / `numeric` | `float` | `xsd:decimal` |
| `float` / `double` / `real` | `float` | `xsd:double` |
| `date` | `date` | `xsd:date` |
| `timestamp` | `datetime` | `xsd:dateTime` |
| `boolean` | `boolean` | `xsd:boolean` |

### No tier is lost on the way out

Every element that came from an assertion carries that assertion's tier:
`annotations.tier` in LinkML, `sl:tier` in SHACL.

```yaml
      channel_code:
        range: "string"
        annotations:
          tier: "proven"
          key_tier: "hypothesis"
```

```turtle
    sh:property [
        sh:path sl:rel_001 ;
        sh:class sl:dim_channel ;
        sh:maxCount 1 ;
        sl:relation "rel:001" ;
        sl:claim "many_to_one_assumed" ;
        sl:taskCount 2 ;
        sl:tier "hypothesis"
    ] ;
```

An entity and an attribute carry `proven` themselves: they were not inferred, the corpus
read their names out of the SQL. A relation carries the tier of its cardinality, and a
constraint carries its own.

### Limitations: neither format is stretched to fit

- **SHACL core has no composite uniqueness constraint.** A `unique_per` and a candidate
  key are both "this tuple of columns is unique", and SHACL core has no constraint
  component for that (expressing it takes `sh:sparql`, a different dialect and a
  different runtime). So both are published as `sl:compositeKey` / `sl:candidateKey`
  annotation blocks whose `rdfs:comment` states this limitation, rather than as a shape
  that validates something weaker.
- **An open value set gets no enum.** `completeness: "unknown"` means the corpus observed
  these values and could not prove the set closed; writing that as an enum would pass an
  observation off as a fact. Both formats emit an annotation listing the observed values
  instead.
- **A constraint's id in the exports is its position.** A constraint has no id of its own
  in `ontology.json`, so the exports number it `cst:001` .. by its position in
  `constraints[]`; that array is already deterministically sorted, so the position *is* a
  stable identity.
- **The base IRI is a placeholder** (`https://example.org/scope-lineage/ontology#`). The
  corpus has no namespace of its own, and minting one that looks authoritative would be
  the export inventing a fact; whoever loads the graph replaces it with theirs.
- **Only `evidence` is summarized rather than exported whole.** Every other slot of
  `ontology-json/1` reaches both exports: a downstream tool that reads only the export
  must not end up with a smaller corpus than the one that was published, and `findings`
  and `open_items` are the sharp case -- an export without them reads as a corpus with no
  open questions, so they are published on the schema itself. `evidence` is the exception
  because of size: each assertion carries how much evidence it has and the first task to
  read, and the statements stay in `ontology.json`.
- **A metadata hint carries no tier, because the JSON gives it none.** A declared key hint
  and a relation hint are the catalog's prose, not a corpus assertion; they are published
  with their `column_comment` evidence and a note saying exactly that, rather than with an
  invented tier. Every other exported assertion carries its own.
- **No OWL.** Of the three targets only OWL needs an extra ontological commitment for
  assertions such as cardinality axioms, and that is not a choice an exporter should make
  on its user's behalf.

## Cross-corpus evidence: repeating `--tables`

A JOIN straight onto a physical table can only be `proven` when **somebody else** proved
that table unique by the join keys (`cardinality.basis` is `producer_key_confidence`), and
the task that proved it need not be in the tree this run walked:

```bash
scope-lineage tables   --lineage /path/to/a --out /path/to/a-tables
scope-lineage ontology --lineage /path/to/b --out /path/to/onto \
  --tables /path/to/a-tables/tables.json --tables /path/to/b-tables/tables.json
```

- The `--tables` documents are merged first (`merge_table_cards`), so the ontology faces a
  single set of cards and asks "what does the card say" in exactly one way, whichever
  corpus the answer came from.
- **Only the part this corpus can use is merged** (Q6). Before merging, the table names
  this corpus wrote in its contracts are turned into their **bucket keys** (`table_key`:
  the last segment, without the database prefix), and only cards falling into those
  buckets come in. This is not a sampling: `same_table` holds only between two names
  ending in the same segment, so grouping never crosses a bucket, and taking a whole
  bucket yields exactly the groups the full merge would have published -- including the
  `ambiguous_bare_name` finding, which needs every qualified card in the bucket to be
  present. Memory, the name index and every per-card scan therefore scale with **this
  corpus**, not with the batch it borrowed from: a corpus of a few tasks reaching for a
  whole warehouse's cards no longer pays for the warehouse.
- `corpus.external_evidence_tables` still counts the tables that were **on offer**: a card
  that was never merged was never read, not decided against, and the number may not change
  meaning because the merge changed internally. The merged document gains a top-level
  `cards_narrowed` (`tables_considered` / `tables_merged`) accordingly, absent when nothing
  was narrowed.
- A relation whose right side a **foreign** card proved is published `proven` as usual, and
  its `evidence[]` gains one more entry:
  `{"task": …, "statement_id": …, "corpus": …, "kind": "producer_key_confidence"}`. A proof
  from this corpus adds nothing — that task is already in the reader's own artifacts and
  `cardinality.producer` names it. Across corpora the `corpus` is mandatory, or the
  evidence line points at a task the reader cannot find.
- `relations[].task_count` counts **only the tasks that wrote the JOIN**. A borrowed proof
  is evidence, never another author of the edge, so foreign evidence is not counted.
- Identity keys and partition constraints carry the same stamp: a producer that came from a
  merged card carries its `corpus`, one from this corpus does not.
- The evidence ids in `ontology.md` read `` `<corpus>/<task>/<statement_id>` `` accordingly;
  without a `corpus` they are byte-identical to what they always were.
- **Evidence is not scope**: an entity is published only for a table the `--lineage` corpus
  **read or wrote**. A merged-in table this corpus never touched lends its proven keys,
  producers and consumers to the verdicts above and nothing else: no `entities[]` row, no
  box in the ER diagram, no constraints or findings, and no `tables/<db.table>.md`. A
  corpus of a few tasks would otherwise publish an ER diagram of thousands of entities
  that nobody can read and that is not this corpus's model.
- The one exception is a table **a relation of this corpus references**: both ends of a
  relation must be entities, or the ER diagram is missing a box and the reader sees an
  omission rather than a deliberate exclusion.
- The number left out is published as `corpus.external_evidence_tables` (absent when there
  is none), and `ontology.md` says so in one line: 「另有 N 张表仅作为外部证据参与，未建实体」.

## Relationship with `tables` / `glossary`

The three corpus artifacts stack, answer three different questions, and do not substitute
for one another:

- [`tables`](tables-doc.md) answers "**what is this table**": who writes it, what one row
  means, who reads it and which columns. The ontology's entities, attributes, candidate
  keys and partition columns all come from the cards, which is why `--tables` changes
  nothing but the runtime.
- [`glossary`](glossary-doc.md) answers "**what does this value mean**": comments merged
  across tables, observed constant values, the enums the SQL proved closed. The ontology's
  `in_set` constraints *are* the dictionary's enumerable codes, and `completeness` is the
  dictionary's own `closed_set` verdict, so `--glossary` changes nothing but the runtime
  either.
- `ontology` answers "**how do these tables relate**": relation edges, cardinality,
  multiplicity, synonyms, cross-task contradictions. It is the first conclusion that
  requires more than one task — a single task's `describe` can never reach it.

All three share one semantic profile: the CLI parses and profiles one corpus exactly once.

## Determinism and the golden files

- The same corpus run twice, or walked in any order, yields byte-identical
  `ontology.json`, `ontology.md` and cards.
  `tests/core/test_ontology_properties.py` holds that as a property, together with
  "nothing was invented" and "every assertion below `proven` carries a tier and evidence
  that dereferences".
- `tests/core/fixtures/ontology/` pins the whole output of a five-task corpus
  (`ontology.json`, the `ontology.md` with its ER diagram, and three merged cards), so any
  change of wording or ordering shows up on the golden.

## Boundaries and what comes next

- `--export` emits LinkML and SHACL only; OWL is still a slot correspondence with no
  exporter behind it.
- No embedding, no storage, no LLM call, no business vocabulary — those belong to
  downstream projects.
- Incremental runs within one corpus exist (`--incremental`, see "Incremental runs"), and
  so does reuse *across* corpora: `tables --merge` folds several corpora's cards into one,
  `ontology --tables` repeats and merges them first, and foreign evidence always carries
  its `corpus` (see "Cross-corpus evidence"). Cross-corpus reuse of the *profiles* now
  exists too -- `--cache-from` feeds one corpus's per-task fact cache to another's run
  (Q7, see "Incremental runs").
- Only the per-task half is ever borrowed: the corpus-level merge still runs over every
  task, so a `--cache-from` run is byte-identical to a full one. What does not exist is a
  cross-corpus *index* -- several corpora sharing one content-addressed cache directory --
  so it is on the caller to point `--cache-from` at the right place.
