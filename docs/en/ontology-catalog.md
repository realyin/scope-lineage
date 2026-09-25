English | [中文](../zh-CN/ontology-catalog.md)

# Ontology catalog (`catalog-yaml/1`) and `ontology-json/3`

The ontology catalog is a directory of YAML (or JSON) files that a person maintains. It
says what the business is about **before** it says which tables hold it: domains,
entities, events and roles, their identifiers, attributes and states, the relations and
constraints between them, the words people use for them — and then, in a separate mapping
layer, which table represents which concept and what each column binds to.

**The catalog is the new, concept-first source of truth for the ontology.** Generators
(lineage, table cards, an LLM) may propose changes to it; they do not own it.
`scope-lineage catalog validate` checks a catalog, `scope-lineage catalog build`
normalises it into one machine-readable `ontology-json/3` document (optionally with the
evidence a lineage corpus and its table cards show), `scope-lineage catalog render` turns
that document into one page per concept and `scope-lineage catalog query` answers one
question from it.

> **Transition.** The existing [`scope-lineage ontology`](ontology-doc.md) command, which
> derives an `ontology-json/2` candidate bottom-up from a lineage corpus, stays for **one
> more release** and keeps working unchanged. The catalog does not read it and it does not
> read the catalog. Lineage and table-card evidence is attached with `catalog build
> --lineage/--tables`; the value dictionary is not read yet.

A complete synthetic catalog — a fictional consumer-lending shop — lives in
[`examples/catalog-demo/`](../../examples/catalog-demo/); every example below is taken
from it.

## Layout

```text
catalog/
  catalog.yaml          # manifest: doc_format, name, description (required)
  domains.yaml          # domains: [...]
  identifiers.yaml      # identifiers: [...]
  code_sets.yaml        # code_sets: [...]
  concepts/*.yaml       # concepts: [...]   entities, events, roles; one file per domain is usual
  relations.yaml        # relations: [...]
  constraints.yaml      # constraints: [...]
  terms.yaml            # terms: [...]
  mapping/*.yaml        # representations: [...]   one file per domain is usual
```

- Any file may be `.yaml`, `.yml` or `.json`, and the formats may be mixed. Reading YAML
  needs the optional dependency PyYAML: `pip install 'scope-lineage[catalog]'`. A catalog
  written entirely in JSON needs nothing extra.
- Only `catalog.yaml` (or `catalog.yml` / `catalog.json`) is required. A missing file is an
  empty list. Files of the same kind are concatenated; where an object is written does not
  change the build.
- A file the layout does not name (a misspelt `domain.yaml`, a note in `concepts/`) is
  reported as an `unknown_file` warning rather than silently skipped.

```yaml
doc_format: catalog-yaml/1
name: demo-lending
description: A fictional consumer-lending shop.
```

## Common fields

Every object carries these fields in addition to its own.

| Field | Values | Default | Meaning |
| --- | --- | --- | --- |
| `id` | `<prefix>:<slug>`; lower-case letters, digits, `_` and `.` | — (required; terms and representations have none) | globally unique; the prefix must match the object type |
| `status` | `drafted` / `confirmed` / `deprecated` | `drafted` | only `confirmed` has been signed off by an owner |
| `source` | `owner` / `comment` / `task` / `sql` / `llm` / `mixed` | none | where the statement came from |
| `evidence` | list of strings: a table, `table.column`, a lineage id, a task name | `[]` | pointers a reviewer can follow |
| `notes` | text | — | free text |

Attributes inherit `status` and `source` from their concept, bindings from their
representation, unless they set their own.

## The elements

### Domain

A business area that groups related concepts. `id: domain:<slug>`, `name`, `description`.

```yaml
domains:
  - id: domain:lending
    name: 贷款
    description: Loans from disbursement to settlement.
    status: confirmed
    source: owner
```

### Identifier

A business number that uniquely identifies one entity or event **within a scope**.

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | `id:<slug>` |
| `name` | yes | business name |
| `identifies` | yes | the entity or event it identifies |
| `scope` | yes | `global`, or `{per: [<concept id>, ...]}`: unique only within each combination of those concepts |
| `arises_when` | no | the condition under which the identifier exists: text, or `{condition, state: <concept id>#<state value>}` |
| `spellings` | no | physical spellings: `[{column, table?}]`; no `table` means "this column name, wherever it appears" |
| `maps_to` | no | correspondences: `[{identifier, cardinality, via?: [table]}]`, cardinality `one_to_one` / `one_to_many` / `many_to_one` / `many_to_many` |
| `format` | no | what a value looks like |

```yaml
identifiers:
  - id: id:verified_customer_no
    name: 认证客户号
    identifies: concept:customer
    scope: global
    arises_when:
      condition: assigned when the customer passes identity verification
      state: concept:customer#verified
    spellings:
      - column: verified_customer_no
  - id: id:app_account_id
    name: 应用账户号
    identifies: concept:app_account
    scope:
      per: [concept:channel]
```

### Code set

A finite set of values and their business meanings, shareable by several attributes.
`id: code:<slug>`, `name`, `values: [{value, meaning, retired?}]`, `definition?`. A value
is text or an integer; `0` and `"0"` are the same code.

```yaml
code_sets:
  - id: code:loan_status
    name: 借据状态
    values:
      - {value: "1", meaning: normal}
      - {value: "2", meaning: overdue}
      - {value: "3", meaning: settled, retired: false}
```

### Concept: entity, event, role

`id: concept:<slug>`, `kind`, `name`, `definition`, `domain`, `synonyms?`, `attributes`,
plus the fields of its kind:

| Kind | What it is | Kind-specific fields |
| --- | --- | --- |
| `entity` | a thing with a stable identity that exists on its own and is referred to again and again | `identifiers` (list), `primary_identifier` (one of them), `states?` |
| `event` | something that happens at a point in time, has participants, and is never changed afterwards (only offset by a reversing event) | `identifiers?`, `occurred_at` (one of its own attributes), `participants: [{role_name, concept, cardinality: one/many}]` |
| `role` | what an entity is within one business context; it does not change the entity | `player` (an entity), `context` (a domain), `condition` (text) |

A missing `definition` is allowed but warned about. `role_name` is a slug
(`[a-z0-9_]+`) because it becomes part of an id (see the build).

```yaml
concepts:
  - id: concept:repayment
    kind: event
    name: 还款
    definition: A customer pays money back against one or more loans.
    domain: domain:lending
    identifiers: [id:repayment_txn_no]
    occurred_at: attr:repayment.repaid_at
    participants:
      - {role_name: payer, concept: concept:customer, cardinality: one}
      - {role_name: loan, concept: concept:loan, cardinality: many}
    attributes:
      - id: attr:repayment.repaid_at
        name: 还款时间
        definition: When the payment was received.
        category: time
        type: timestamp
  - id: concept:borrower
    kind: role
    name: 借款人
    domain: domain:lending
    player: concept:customer
    context: domain:lending
    condition: holds at least one loan whose status is not settled
```

### Attribute

One business property of a concept, written inside the concept. `id:
attr:<concept slug>.<slug>` (the concept slug must be the owning concept's), `name`,
`definition`, `category` (`descriptive` / `state` / `measure` / `time`), `type`, `unit?`,
`code_set?`, `derivation?` (how it is computed, in words).

### State

The stages of an entity's life cycle, moved by events. Written as the entity's `states`:
the `attribute` that holds the state (one of the entity's own), the `values`, and the
`transitions` — each an `event` moving the entity `from` one value `to` another.

```yaml
    states:
      attribute: attr:loan.loan_status
      values:
        - {value: normal, name: 正常}
        - {value: overdue, name: 逾期}
        - {value: settled, name: 结清}
      transitions:
        - {event: concept:repayment, from: overdue, to: normal}
        - {event: concept:fee_waiver, from: overdue, to: settled}
```

### Relation

A business link between two concepts. `id: rel:<slug>`, `kind`, `from`, `to`, `name` (a
verb), `inverse_name?`, `cardinality: {from, to}` with each end one of `"1"`, `"0..1"`,
`"0..*"`, `"1..*"` (quote `"1"` in YAML; a bare `1` is accepted too), `definition?`.

| Kind | Meaning | Example |
| --- | --- | --- |
| `association` | two independent concepts linked by a verb | borrower owes loan |
| `composition` | one belongs to the other and does not exist without it | customer holds app account |
| `participation` | an entity or role takes part in an event | derived from event participants — do not write these |
| `generalization` | one is a kind of the other | installment loan is a kind of loan |
| `derivation` | one is derived from the other (metrics, later) | — |

Each end's cardinality is how many of that end relate to one of the other end: in
`customer holds app_account {from: "1", to: "0..*"}`, one account has one customer and a
customer has any number of accounts.

### Constraint

A condition that must hold. `id: cons:<slug>`, `kind` (`unique` / `cardinality` /
`mandatory` / `value_domain` / `referential` / `temporal` / `state_transition` /
`derivation` / `business_rule`), `on` (a concept, attribute, relation or identifier),
`expression` (text), `strength` (`hard` / `soft`).

```yaml
constraints:
  - id: cons:loan_no_unique
    kind: unique
    on: id:loan_no
    expression: no two loans share a loan_no, whatever the channel
    strength: hard
```

### Term

A word people use, and what it refers to. `term`, `refers_to` (any id), `preferred`. Terms
have no id.

```yaml
terms:
  - {term: 借据, refers_to: concept:loan, preferred: true}
  - {term: 对客借据, refers_to: concept:loan, preferred: false}
```

### Representation and binding

The mapping layer, in `mapping/*.yaml`: which table carries which concept, in what role,
and what each column is. A representation is keyed by its `table` (`db.table`; one
representation per table).

| Field | Required | Meaning |
| --- | --- | --- |
| `table` | yes | `db.table` |
| `concept` | yes | the concept it represents |
| `kind` | yes | `core` / `extension` (1:1 with the core) / `dependent` / `event_detail` / `state_history` / `identifier_map` / `role_view` / `summary` / `intermediate` |
| `grain` | yes | `{identifiers: [id], extra: [text], source: declared/inferred/proven}` |
| `time` | yes | `snapshot` / `incremental` / `zipper` / `unknown` |
| `scope` | no | which records the table holds, in words |
| `refresh` | no | update frequency |
| `table_status` | yes | `active` / `deprecated` |
| `replaced_by` | no | the table that replaces a deprecated one |
| `bindings` | yes | `[{column, to, ref?, via?, derivation?, code_map?}]` |

A binding's `to` says what the column is:

| `to` | `ref` | Meaning |
| --- | --- | --- |
| `attribute` | required | an attribute of the represented concept (a role view may also bind its player's) |
| `identifier` | required | an identifier of the represented concept (a role view may also bind its player's) |
| `foreign_identifier` | required | another concept's identifier — a relation, physically; or the represented concept's own identifier (another instance of the same concept), provided the catalog has a relation whose two ends are that concept |
| `foreign_attribute` | required | an attribute of another concept X, repeated on this row (a wide table); `via` is required and names the column of this table bound as `foreign_identifier` to an identifier of X |
| `technical` | none | partition, load time, surrogate keys |
| `unmapped` | none | not decided yet (warned about) |

```yaml
representations:
  - table: demo_dwd.dwd_lending_loan_df
    concept: concept:loan
    kind: core
    grain:
      identifiers: [id:loan_no]
      source: proven
    time: snapshot
    table_status: active
    bindings:
      - {column: loan_no, to: identifier, ref: id:loan_no}
      - {column: customer_id, to: foreign_identifier, ref: id:customer_id}
      - {column: orig_loan_no, to: foreign_identifier, ref: id:loan_no}
      - column: loan_status
        to: attribute
        ref: attr:loan.loan_status
        code_map: {"1": normal, "2": overdue, "3": settled}
      - column: customer_gender_cd
        to: foreign_attribute
        ref: attr:customer.gender
        via: customer_id
      - {column: dt, to: technical}
```

The demo's loan table has two columns the format could not express before.
`customer_gender_cd` is the customer's gender, repeated on the loan row next to the
customer number: it is bound as `foreign_attribute`, and `via: customer_id` says which
customer it describes. `orig_loan_no` is the loan a renewal renews — another instance of
the same concept: it is bound as `foreign_identifier` to the loan's own identifier, which
is allowed only because the catalog declares a relation from loan to loan:

```yaml
relations:
  - id: rel:loan_renews_loan
    kind: association
    from: concept:loan
    to: concept:loan
    name: renews
    inverse_name: is renewed by
    cardinality: {from: "0..1", to: "0..1"}
```

## Validation

```bash
scope-lineage catalog validate examples/catalog-demo
scope-lineage catalog validate examples/catalog-demo --json
```

Validation runs in two stages. **Structure**: every file against its JSON Schema (shipped
in the package as `scope_lineage/schemas/catalog-*.schema.json`, one per file kind; unknown
keys are errors, so a misspelt key cannot go unnoticed). **References and warnings** run
only once the structure is clean, because a broken file hides its objects and every
reference to them would otherwise be reported as missing.

Exit code: `0` valid (warnings allowed), `1` errors, `2` the catalog could not be read (no
directory, no manifest, YAML without PyYAML).

### Errors

| Rule | What is wrong |
| --- | --- |
| `parse_error` | the file is not valid YAML / JSON |
| `schema` | the file does not match its schema; the finding names the path, e.g. `concepts[0].kind` |
| `duplicate_id` | an id is declared twice (also: a declared relation id equals a derived participation id) |
| `id_prefix` | the prefix does not match the object type, or an attribute id is not under its concept's slug |
| `identifier_identifies` | `identifies` is not an entity or an event |
| `identifier_scope` | a `scope.per` entry is not a concept |
| `identifier_state` | `arises_when.state` names a concept without states, or a state it does not have |
| `identifier_maps_to` | a `maps_to` target is not an identifier |
| `concept_domain` | `domain` is not a domain |
| `concept_identifier` | an `identifiers` entry is not an identifier |
| `primary_identifier` | `primary_identifier` is not in the concept's `identifiers` |
| `role_player` | a role's `player` is not an entity |
| `role_context` | a role's `context` is not a domain |
| `event_participant` | a participant is not an entity or a role |
| `duplicate_role_name` | two participants of one event share a `role_name` |
| `event_occurred_at` | `occurred_at` is not one of the event's own attributes |
| `state_attribute` | `states.attribute` is not one of the entity's own attributes |
| `state_event` | a transition's `event` is not an event |
| `state_value` | a transition's `from` / `to` is not one of the state values |
| `attribute_code_set` | an attribute's `code_set` is not a code set |
| `duplicate_code_value` | a code set lists the same value twice |
| `relation_endpoint` | a relation's `from` / `to` is not a concept |
| `constraint_on` | `on` is not a concept, attribute, relation or identifier |
| `term_refers_to` | `refers_to` does not exist |
| `representation_concept` | the representation's `concept` is not a concept |
| `representation_grain` | a grain identifier is not an identifier |
| `duplicate_table` | a table is represented twice |
| `duplicate_column` | a column is bound twice in one representation |
| `binding_attribute` | the attribute is not the represented concept's (or, for a role view, its player's) |
| `binding_identifier` | the identifier is not the represented concept's (or, for a role view, its player's) |
| `binding_foreign_identifier` | `ref` is not an identifier at all (or does not exist) |
| `self_reference_without_relation` | the identifier is the represented concept's own, and no relation has that concept at both ends |
| `binding_foreign_attribute` | `ref` is not an attribute, or is the represented concept's own (for a role view, or its player's) — bind that as `attribute` |
| `binding_foreign_attribute_via` | `via` is not a column of this table, that column is not a `foreign_identifier`, or the identifier it holds does not identify the attribute's concept |

An identifier "is the concept's" when the concept lists it in `identifiers` or the
identifier `identifies` the concept. A subtype may therefore list its supertype's
identifier (the demo's installment loan lists `id:loan_no`).

### Warnings

| Rule | Meaning |
| --- | --- |
| `drafted_ratio` | how many objects are still `drafted` — nothing unconfirmed should be read as settled |
| `concept_without_definition` | a concept has no definition |
| `relation_without_name` | a relation has no verb |
| `empty_code_set` | a code set lists no values |
| `unmapped_binding` | a column is bound `to: unmapped` |
| `unknown_file` | a file the layout does not name; it was ignored |

### Report

The text form prints one line per finding: `error` / `warning`, the rule, the file, the
object and the message. `--json` prints the same as `catalog-report/1`:

```json
{
  "doc_format": "catalog-report/1",
  "catalog": "demo-lending",
  "ok": true,
  "references_checked": true,
  "errors": [],
  "warnings": [
    {
      "rule": "unmapped_binding",
      "file": "mapping/party.yaml",
      "at": "demo_dwd.dwd_party_customer_ext_df.ext_json",
      "message": "column not yet bound to anything in the concept layer"
    }
  ],
  "counts": {
    "domains": 3,
    "concepts": 10,
    "concepts_by_kind": {"entity": 5, "event": 4, "role": 1},
    "representations": 9,
    "status": {"drafted": 20, "confirmed": 30, "deprecated": 0}
  }
}
```

(`counts` is abridged here; it also counts identifiers, code sets, attributes, relations,
constraints, terms and bindings.)

## Build: `ontology-json/3`

```bash
scope-lineage catalog build examples/catalog-demo --out out/
```

`build` validates first and **refuses to write anything** when there is an error. Otherwise
it writes `out/ontology.json`, whose schema ships as
`scope_lineage/schemas/ontology-v3.schema.json`:

```json
{
  "doc_format": "ontology-json/3",
  "catalog": {"name": "demo-lending", "description": "...", "format": "catalog-yaml/1"},
  "counts": {"domains": 3, "concepts": 10, "relations": 12, "derived_relations": 7},
  "domains": [],
  "identifiers": [],
  "code_sets": [],
  "concepts": [],
  "relations": [
    {
      "id": "rel:repayment.loan",
      "kind": "participation",
      "from": "concept:repayment",
      "to": "concept:loan",
      "name": "loan",
      "cardinality": {"from": "0..*", "to": "1..*"},
      "derived_from": {"event": "concept:repayment", "role_name": "loan"},
      "status": "confirmed",
      "source": "sql",
      "evidence": []
    }
  ],
  "constraints": [],
  "terms": [],
  "representations": []
}
```

(Lists abridged.) What "normalised" means:

- every object has `status`, `source` (`null` when unknown) and `evidence`; attributes and
  bindings inherit from their concept / representation;
- keys come out in one fixed order per object type; code and state values are text; a
  cardinality end written `1` is `"1"`; a text `arises_when` becomes `{condition}`;
- top-level lists are sorted — by `id`, terms by term then target, representations by
  table — so moving an object to another file changes nothing. Lists inside an object
  (attributes, state values, bindings) keep the author's order;
- bindings carry `via` through as written; a `foreign_identifier` holding the concept's
  own identifier carries `self_reference: true`;
- each event participant becomes a `participation` relation `rel:<event slug>.<role_name>`
  from the event to the participant, cardinality `{from: "0..*", to: "1"}` for `one` or
  `"1..*"` for `many`, carrying `derived_from` and the event's status and source. Such an
  id must not also be declared by hand.

## Evidence: `--lineage` and `--tables`

The catalog says what a person believes; a lineage corpus and its table cards show what the
warehouse does. `build` can read both and file what they show beside the catalog:

```bash
scope-lineage parse --input-dir examples/catalog-demo-corpus/tasks \
  --schema examples/catalog-demo-corpus/schema_info.json --out out/lineage
scope-lineage tables --lineage out/lineage --out out/tables
scope-lineage catalog build examples/catalog-demo --out out/ \
  --lineage out/lineage --tables out/tables/tables.json
```

[`examples/catalog-demo-corpus/`](../../examples/catalog-demo-corpus/) holds eight synthetic
scheduler tasks that write and read the demo's tables. The evidence lands in one top-level
`evidence` block of `ontology.json`, keyed by the catalog's own names. **No catalog object is
changed**, and without either flag there is no `evidence` key at all, so the document is
byte for byte what it was.

| Where | Key | From | What it says |
| --- | --- | --- | --- |
| `representations["db.table"]` | `producing_tasks` | `--lineage` | the tasks whose statements write the table |
| `representations["db.table"]` | `refresh` | `--lineage` | those tasks' schedule cycle (or cron) |
| `representations["db.table"]` | `upstream_tables` / `downstream_tables` | `--lineage` | one hop of table lineage: what the writers read, what the readers write |
| `representations["db.table"]` | `grain_proof` | `--lineage` | the best grain any writer proves: `confidence` (`proven` / `candidate` / `none`), `keys`, `basis`, `task` |
| `representations["db.table"]` | `conflicts` | `--lineage` | `grain_not_proven` (declared `proven`, lineage cannot prove it) or `grain_mismatch` (both proven, different columns) |
| `representations["db.table"]` | `declared_columns` / `used_columns` | `--tables` | how many columns the metadata declares and the corpus uses |
| `bindings["db.table.column"]` | `sources` / `expression` | `--lineage` | the physical source columns and the final expression (at most 200 characters), only for a binding without a hand-written `derivation` |
| `bindings["db.table.column"]` | `declared_only` | `--tables` | the metadata declares the column and no task in the corpus touches it |
| `relations["rel:..."]` | `joins` | `--lineage` | `count` and up to three `samples` of JOINs linking the two concepts' tables on columns bound to one identifier of theirs |

```json
{
  "inputs": {
    "lineage": {"tasks": 8, "statements": 8, "representations_matched": 7, "relations_checked": 7},
    "tables": {"cards": 15, "representations_matched": 7}
  },
  "representations": {
    "demo_dwd.dwd_lending_loan_df": {
      "producing_tasks": ["dwd_lending_loan_daily"],
      "refresh": ["day"],
      "upstream_tables": ["demo_ods.ods_loan_contract_df", "demo_ods.ods_loan_penalty_di"],
      "downstream_tables": ["demo_ads.ads_collection_overdue_loan_df", "demo_dwd.dwd_lending_borrower_df"],
      "grain_proof": {"confidence": "candidate", "keys": ["loan_no"], "basis": "driving_table_rows", "task": "dwd_lending_loan_daily"},
      "conflicts": [{"rule": "grain_not_proven", "declared_source": "proven", "confidence": "candidate"}],
      "declared_columns": 8,
      "used_columns": 8
    }
  },
  "bindings": {
    "demo_dwd.dwd_lending_loan_df.principal_amt": {"sources": ["demo_ods.ods_loan_contract_df.principal"], "expression": "`l`.`principal`"},
    "demo_dwd.dwd_lending_loan_status_his.loan_status": {"declared_only": true}
  },
  "relations": {
    "rel:borrower_owes_loan": {
      "joins": {"count": 1, "samples": [{"task": "ads_collection_overdue_borrower_daily", "statement_id": "stmt:001", "on": "demo_dwd.dwd_lending_borrower_df.customer_id = demo_dwd.dwd_lending_loan_df.customer_id"}]}
    }
  }
}
```

(Abridged.) How the evidence is matched:

- **Tables** match on their last two dotted segments: the demo's loan task writes
  `spark_catalog.demo_dwd.dwd_lending_loan_df`, and it lands on the representation
  `demo_dwd.dwd_lending_loan_df`. A table the corpus never names gets no entry.
- **Grain**: partition columns are left out of both sides before a grain is compared, so a
  catalog grain that names `stat_date` does not disagree with a statement that writes one
  `stat_date` partition. A declared grain whose identifier has no bound column is not
  compared at all.
- **Relations** are counted only when both ends have a representation; a relation checked
  and backed by no JOIN has `count: 0`, one that could not be checked has no entry. A JOIN
  counts when one side is a table of each concept and **both** key columns of one key pair
  are bound (as `identifier` or `foreign_identifier`) to the same identifier, one that
  identifies either end: the relation's own concepts, or for a role the player its tables
  bind. A customer id met by a phone number, or two customer ids linking a call to a contact,
  is not a sample of a call–contact relation. Participation relations are counted the same
  way. A relation whose two ends are one concept counts only JOINs with a `self_reference`
  key column on at least one side (a table joined to itself included): the same instance met
  in two tables says nothing about the relation.
- The corpus is read with the same readers `tables` and `ontology` use; a JOIN side that is
  a CTE is followed down to the physical table its rows come from. A key column is the
  physical column whose value the ON clause compares: a renamed column (`caller_phone AS
  dialed_no`) is reported under its physical name, and a key computed from one column
  (`TRIM`, `CAST`, `COALESCE(x, '')`) as that column. A key computed from several columns
  (`IF(a.id = '' AND b.phone IS NOT NULL, b.id, a.id)`) is none of them — a column its
  condition only reads is never reported as a key — and stands under the name the ON clause
  wrote, on the table of the scope that ON reference names.

## Pages: `catalog render`

```bash
scope-lineage catalog render out/ontology.json --out out/pages
```

`render` reads the built document only — never the catalog directory — so the pages show
exactly what was built, evidence included. Headings are Chinese, like the other rendered
documents; names are the catalog's own.

| File | What it holds |
| --- | --- |
| `index.md` | the concepts by domain (name, kind, definition, number of tables, status), the identifiers, a summary of the governance gaps |
| `concepts/<slug>.md` | one page per concept (`concept:fee_waiver` → `fee_waiver.md`), six sections |
| `identifiers.md` | every identifier in full, with the columns bound to it |
| `governance.md` | every gap of every concept, one list per kind of gap; plus the denormalised columns per table (informational, not a gap) |

The six sections of a concept page answer the six things a reader opens it for:

| Section | Content |
| --- | --- |
| 1. 定义与身份 | definition, kind, status, synonyms; identifiers (arising condition, uniqueness scope, physical spellings, mappings); the state machine (values, transition events); an event's participants, a role's player, context and condition |
| 2. 数据清单 | the tables, grouped by representation kind (核心, 扩展, 从属, 事件明细, 状态历史, 标识映射, 角色视图, 汇总, 中间): grain (identifiers, source, and what lineage proves), time semantics, refresh, record scope, producing tasks, deprecation and replacement; one hop of lineage per table |
| 3. 属性 | by category (描述, 状态, 度量, 时间): definition, type and unit, code values (value=meaning), every table column that holds it (with its code map; one another table repeats is marked 「冗余（经 via column）」), how it is derived |
| 4. 关系 | association, composition and generalization read from this concept's side, with cardinality and JOIN count (a self relation's far end reads 「本概念」 with the columns that carry it); the events it takes part in (its role, how many tables the event has); the roles it plays, or — on a role's page — the player it belongs to |
| 5. 约束 | the constraints on the concept, its attributes, identifiers and relations, by kind, with strength and status |
| 6. 治理缺口 | drafted share, unmapped columns, attributes no table holds, state or coded attributes without values, whether the concept has any table; with evidence also the conflicts, bound columns nobody uses and relations no JOIN backs |

Anything that came from the corpus is labelled 「血缘」; without evidence those cells show
「—」 rather than a guess.

## Query: `catalog query`

```bash
scope-lineage catalog query out/ontology.json concept 用户
scope-lineage catalog query out/ontology.json table spark_catalog.demo_dwd.dwd_lending_loan_df --json
```

| Kind | Term | Answer |
| --- | --- | --- |
| `concept` | id, name, synonym or term | identity, identifiers, attributes, states, tables, the page to read |
| `table` | `db.table` (a catalog prefix is ignored) | the concept it carries and what every bound column points at, with evidence; a denormalised column reads `→ 冗余属性 <attribute> of <concept>（经 <via>）`, a self-referencing one names its relation |
| `column` | `db.table.column` | the attribute or identifier it holds and its concept — or the identifier it spells |
| `identifier` | id, name or physical spelling | what it identifies, its scope and spellings, the columns bound to it |
| `attribute` | id, name or term | its concept, code values, derivation and every table column |
| `related` | a concept's id, name, synonym or term | one hop: relations read from its side, events, participants, roles, player, tables |

Names match exactly, ignoring case and surrounding spaces, in that order (id, then name,
then synonym, then term); nothing is guessed. The text answer is a few lines:

```text
客户 concept:customer · 实体 · 客户与账户 · 已确认（owner）
  A person the shop has registered, whether or not they ever borrow.
  标识符：客户号 id:customer_id（主）、认证客户号 id:verified_customer_no
  属性：性别、注册时间、认证状态
  状态：未认证、已认证
  表：demo_dwd.dwd_party_customer_ext_df（扩展）、demo_dwd.dwd_party_customer_info_df（核心）
  页面：concepts/customer.md
```

`--json` prints `{"query": {"kind", "term"}, "matches": [...]}` for an agent. Exit code: `0`
something matched, `1` nothing did, `2` the file could not be read (`1` too when it is not an
`ontology-json/3` document).

## Writing YAML safely

- The catalog reads YAML with 1.2 booleans: only `true` / `false` are booleans, so `on:`
  (a constraint key) and codes such as `no` or `off` stay text.
- Quote cardinality ends (`"1"`) and code values that must keep leading zeros (`"01"`).
- A date written bare (`2026-01-31`) is read as the text `"2026-01-31"`.
