### 键折叠候选（旧 ontology）— key-fold candidates

**What it is for, and what it is not.** `scope-lineage ontology` folds tables into
"concepts" by a rule: tables that share a key-column stem become one concept, named from
column comments. That makes it a quick structural scan of a corpus — which tables share
which keys, which joins were proven or assumed, what the SQL contradicts — and a source of
cross-evidence while drafting a catalog. It is **not** the business ontology and is not the
route for business questions: a rule cannot tell a code dictionary from an entity, can
split one business thing across two stems, and never produces events. On real corpora the
table semantics → catalog route (previous section, 「business ontology: where to start」)
gets exactly those right. Use this section when the user asks for key-level structure
(shared keys, join cardinality, governance findings) or explicitly for the key-fold output;
word its "concepts" as key-fold candidates, never as the warehouse's business concepts.

```bash
scope-lineage tables    --lineage <corpus> --out <dir>
scope-lineage glossary  --lineage <corpus> --out <dir>
scope-lineage ontology  --lineage <corpus> --out <dir> \
  --tables <dir>/tables.json --glossary <dir>/glossary.json
```

The run writes `ontology.json` (machine, `ontology-json/2`),
`ontology.md` (the index), `concepts/<file>.md` (one per folded concept,
`concept-md/1`), `appendix.md` (everything table-level, `ontology-appendix-md/1`) and
`tables/<db.table>.md` (the table card with five ontology sections appended). The JSON is concept-first: `concepts[]` are the key-fold concepts,
`relations[]` the relations **between concepts**, `tables[]` the warehouse tables that
*represent* them and `table_relations[]` the JOINs that are the **evidence** (0.4.0 renamed
the old `entities[]` and `relations[]`; `--legacy-keys` writes the old names for one
release). `--tables` / `--glossary` only save
a recomputation — the bytes are identical without them. Add `--export linkml,shacl` when
the user wants the candidate in an RDF toolchain: it writes `ontology.linkml.yaml` and
`ontology.shacl.ttl` beside the JSON, each element still carrying its tier.

**Read in this order.** `ontology.md` first (its first line says it is key-fold candidates,
not the business ontology), and it reads concept-first: 「本体总览」 says
how many concepts of each kind the key fold proposes, how many are still 临时概念, and
「待人工判定 N 条 / G 组（已确认 M 条）」; the concept `flowchart` is the key-fold structure on one
screen. **To read one concept, open its own file**: every row of the 「概念」 table links to
`concepts/<file>.md` (`concept:cust` → `concepts/cust.md`), and that file — not the table
list — is what describes one folded concept: its 表现 (which tables represent it, in which
role, at which grain, each linked to its card), every attribute with the columns behind
it, its constraints, its relations with the table-level JOINs each was read off as
evidence, its open questions, what voted for its name and kind, and the exact
`concepts.overrides.json` key to answer under. A 临时概念 has no file: it is a question,
and the answer to it is a `merge_into`. The index says how many there are and prints the
**top 20 by impact** — the same order `--review-batches` queues them in; the whole list
is in `appendix.md` under the same heading.
Everything table-level is in `appendix.md`: the Mermaid `erDiagram`, the table list
(its 图中 id column maps a diagram box back to its table), the table relations (each naming
the concept relation it folded into), that provisional list and the folded open list;
`ontology.md` keeps only 「附录索引」, one line per section with its count and a link. That last section,
「待人工判定清单（N 条，折叠为 G 组）」, is every open
question in one place, folded by (kind, table family, question shape): one row per group,
with a stable `open:group:` id, the representative question, an `影响` score, how many
items it covers and a write-back pattern whose `<table>` the reviewer fills in per table.
A relation's group is about its far side — "is that table unique on these columns" — so
every task joining one dimension is one question. Groups rank by impact (a relation's
producers plus their tasks; a key's assumed edges; a finding's items), then by size, then
by the representative's rank; the first 50 print and the rest are summarised in one line. The item-by-item list lives in `open_items[]` in the
JSON, and the family members in `families[]`. Then the one card you need — never the JSON,
and never all the cards. A card's sections 7-11 are 身份 / 关系 / 约束 / 属性同义 / 待人工判定;
sections 1-6 are the ordinary table card. Section 7 opens with which concept this table
represents and which other tables represent the same one; section 8 shows the concept
relations its joins fed, with the table-level JOINs beneath them as evidence.

**Every assertion carries a tier, and the tier is the answer.** `proven` 已证明 is written
in the SQL. `implied` 可推得 follows from what the SQL does. `hypothesis` 作者假设 is what
an author assumed and nobody proved. `conflict` 矛盾 is two tasks disagreeing. `confirmed`
已确认 exists only because a person answered the question in `ontology.overrides.json`.

- **Never report an `assumed` claim as a fact.** `many_to_one_assumed` means "the author
  joined this table directly and therefore assumed it is unique by that key" — write it
  that way, not as "this is a many-to-one relationship". The same for a `hypothesis`
  candidate key: it is a key somebody assumed, not a primary key.
- **`hypothesis` and `conflict` items must be surfaced verbatim and marked `[待确认]`.**
  They are the reason this document exists. Summarising them away, or averaging them into
  a confident sentence, is the single worst thing to do with this artifact.
- A `cardinality_conflict` is a **governance finding**, not an ontology fact: one task
  deduplicates a table by k and another joins it directly on k, so either the second
  multiplies rows or the first is dead weight. Report both sides and who to ask. Two more
  findings read the same way: `competing_candidate_keys` (two authors assumed two
  different identities for one table — at most one of them is it) and `key_hint_conflict`
  (a column comment names one column the key and every corpus guess names another).
- `identity.declared_hints[]` is what the **metadata** says about identity — a column
  comment calling a column 主键 / 唯一键 / primary key. It is a hint, never a key: report
  it as "the catalog's column comment says so", and note that where it agrees with a
  corpus guess the tier is already `implied` rather than `hypothesis`.
- An `in_set` constraint with `completeness: "unknown"` is a floor, never a ceiling: those
  values were *observed*, and the column may hold others.
- Core names no entity and infers no class hierarchy. If a business name is wanted, it is
  your inference over `naming_hints` and must be labelled `[推断]`.

**When the user wants the open items turned into questions**, follow
`references/ontology-review-prompt.md`. It runs in two passes: first close what the corpus
already answers (a producing task's proven grain, a column comment naming the key, two
tasks joining on the same key set) by writing those confirmations yourself, each with a
`basis` saying what closed it; then turn **at most 8** of what is left into a
five-line-per-item list a business owner can answer. The evidence pass needs the task
profiles — `semantic.md` beside each `lineage.json` — so run `describe` over the corpus
first if they are not there. The answers go back through `ontology.overrides.json`:

```bash
scope-lineage ontology --lineage <corpus> --out <dir> \
  --overrides <dir>/ontology.overrides.json
```

An override may carry `scope_columns` ("unique within one `dt`", the normal shape of a
snapshot table), plus `basis` and `note` recording why the answer is believed. Confirmed
assertions come back at tier `confirmed` and drop off the open list, so the headline
counter is how a second round sees what the first one bought. Check two lists every round:
`overrides_applied.unmatched` (an override that matched nothing, with a `reason` naming the
unknown entity or column) and `overrides_applied.ignored_fields` (a misspelled slot that
did not take effect). Both are where a typo in a reviewed file shows up.

**When the user wants the key-fold concepts themselves reviewed** (not what the corpus is
*about* — that is the table semantics → catalog route,
「business ontology: where to start」 above), read `ontology.md`'s 「本体总览」 and 「概念」
parts, open the concept files the table links to for the ones in question, and follow `references/concept-review-prompt.md`. It is the same corpus's
*second* review round and it answers different questions: the kind of
each concept (entity / event / summary, with the votes in `kind_evidence[]`), its business
name (never better than a hypothesis — `name_candidates[]` is ranked, and a concept whose
`name_tier` is `stem_only` was named by nothing but the key stem, an English abbreviation
nobody asked for), which concepts are one
thing written twice (`possible_duplicate_of`), which one is two things, and which member
tables were read as the wrong kind of copy. The round opens on the 「临时概念」 table: a
table no business key placed is published as a concept of its own at
`tier: "provisional"`, and deciding what each of those really is — a copy of an existing
concept, part of a new one, or its own thing — is the first thing the prompt asks for. Same evidence discipline as the round above:
close what the corpus answers yourself with a `basis` on every entry, ask a business owner
**at most 8**, never self-answer a split. The answers go back through a separate file:

```bash
scope-lineage ontology --lineage <corpus> --out <dir> \
  --concept-overrides <dir>/concepts.overrides.json
```

Confirmed names, kinds and roles come back at tier `confirmed`; a `merge_into` folds one
concept's tables, attributes and key stem into another (and, because it is applied before
the concept relations are folded, moves that concept's edges with it); `splits[]` publishes
`concept:<stem>-<n>` per named group. Check `concept_overrides_applied.unmatched` and
`.ignored_fields` every round, exactly as above.
