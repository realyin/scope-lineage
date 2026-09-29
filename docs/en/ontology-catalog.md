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
question from it; `catalog digest` and `catalog merge` help draft a catalog from table
semantics (see [Drafting](#drafting-catalog-digest-and-catalog-merge)).

> **Transition.** This catalog, drafted from table semantics, is the business ontology. The
> existing [`scope-lineage ontology`](ontology-doc.md) command, which folds a lineage corpus
> bottom-up by shared key stems into `ontology-json/2` **key-fold candidates**, is a
> structural scan and drafting evidence, not the business ontology; it stays for **one
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
`id: code:<slug>`, `name`, `values: [{value, meaning, retired?, unconfirmed?}]`,
`definition?`. A value is text or an integer; `0` and `"0"` are the same code. A value seen
in the data whose meaning nobody has confirmed carries `unconfirmed: true`, or leaves
`meaning` empty or starting 「待确认」 (followed by the catalog's guess); pages and queries
print it as 「值（含义待确认：guess）」 and `governance.md` lists the code sets holding one.

```yaml
code_sets:
  - id: code:loan_status
    name: 借据状态
    values:
      - {value: "1", meaning: normal}
      - {value: "2", meaning: overdue}
      - {value: "3", meaning: settled, retired: false}
      - {value: "9", meaning: 待确认，疑似核销}
      - {value: "0", meaning: "", unconfirmed: true}
```

When the values live in a code table (a dictionary table) and the catalog does not list
them, `lookup` says where to look them up -- one source per code set. `values` may then
be `[]`, and `empty_code_set` is not reported:

| Field | Required | Meaning |
| --- | --- | --- |
| `table` | yes | `db.table`; case does not matter, `build` writes it lower-case |
| `code_column` | yes | the column holding the code: what a translated column stores |
| `meaning_columns` | yes | `[{column, lang?}]`: the columns holding the meaning, one per language if there are several |
| `key_column` | no | the code table's surrogate key: a fact table may store it instead of the code |
| `filter` | no | `{column: literal}`: when one code table holds several code sets, the constant equality conditions that pick out this set's rows |
| `valid_from` / `valid_to` | no, both or neither | the columns bounding each row's validity window |

```yaml
code_sets:
  - id: code:waiver_reason
    name: 豁免原因
    values: []
    lookup:
      table: demo_dim.dim_code_dict
      code_column: code_val
      meaning_columns: [{column: code_desc, lang: zh}, {column: code_desc_en, lang: en}]
      key_column: dict_key
      filter: {code_type: WaiverReason}
      valid_from: valid_begin
      valid_to: valid_end
```

`lookup` says only "look the code up, by equality, in one table". An expression on the
code side (`substr(...)` before the lookup) and a two-step translation through a mapping
table (the code turned into another table's code first, then looked up) are out of its
scope: write them in the binding's `derivation`.

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

`name` and `inverse_name` are bare verb phrases, without the other end's concept: the pages
read a relation as "<name> <the other concept's name>" (拥有的 / 关联的 in a concept page's
overview) and the appendix as "<from> <name> <to>"; read from the target's side, it is
`inverse_name` and the source's name. A self relation (`from` and `to` the same concept) has
its concept at both ends, so with an `inverse_name` both directions are given: the overview
reads "<name> / <inverse_name> <concept name>", the appendix and `catalog query related`
read "<concept> <name> <concept> / <concept> <inverse_name> <concept>"; a self relation
without an `inverse_name` reads one way, with `name`. Customer → complaint ticket takes
`name: 申请` ("files") and `inverse_name: 申请人为` ("is filed by"), which read 「申请 投诉工单」 and 「申请人为 客户」;
`name: 申请投诉工单` ("files a complaint ticket") reads 「申请投诉工单 投诉工单」.

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

The mapping layer, in the files under `mapping/` (`.yaml` or `.json`): which table carries which concept, in what role,
and what each column is. A representation is keyed by its `table` (`db.table`; one
representation per table).

| Field | Required | Meaning |
| --- | --- | --- |
| `table` | yes | `db.table`; case does not matter, `build` writes it lower-case |
| `concept` | yes | the concept it represents |
| `kind` | yes | `core` / `extension` (1:1 with the core) / `dependent` / `event_detail` / `state_history` / `identifier_map` / `role_view` / `summary` / `intermediate` |
| `grain` | yes | `{identifiers: [id], extra: [text], source: declared/inferred/proven}` |
| `time` | yes | `snapshot` / `incremental` / `zipper` / `unknown` |
| `scope` | no | which records the table holds, in words; `render` files each line under a kind of filter by keywords (see `scopes.md`) |
| `refresh` | no | update frequency |
| `table_status` | yes | `active` / `deprecated` |
| `replaced_by` | no | the table that replaces a deprecated one |
| `bindings` | yes | `[{column, to, ref?, via?, relation?, derivation?, code_map?, code_sets?, holds?, lang?}]` |

A binding's `to` says what the column is:

| `to` | `ref` | Meaning |
| --- | --- | --- |
| `attribute` | required | an attribute of the represented concept (a role view may also bind its player's) |
| `identifier` | required | an identifier of the represented concept (a role view may also bind its player's) |
| `foreign_identifier` | required | another concept's identifier — a relation, physically; or the represented concept's own identifier (another instance of the same concept), provided the catalog has a relation whose two ends are that concept; an optional `relation: rel:<id>` names the relation this column realises |
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

`code_map` holds code meanings specific to this table; a meaning not confirmed yet starts
with 「待确认：」 ("to be confirmed:"), and pages show that prefix as written.

`code_sets` names the code sets this column's values relate to, in lookup order: look in
the first, and when the value is not there, in the next -- the fallback SQL writes as
`coalesce(g1.code_desc, g2.code_desc)`. Falling back in order is a fact about the
**column**, not about any one code set, so it is written on the binding, not in a code set.
It sits beside `code_map`, which holds meanings specific to this table, written into the
catalog. When the bound attribute has a `code_set`, that set should be in `code_sets`, or
a warning says so (`binding_code_sets_miss_attribute`):

```yaml
      - column: reason_cd
        to: attribute
        ref: attr:fee_waiver.reason
        code_sets: [code:waiver_reason, code:waiver_channel]
```

`holds` says what a value of the column is, of those code sets (its `code_sets`, or, when it
names none, the bound attribute's `code_set`): `code`, `meaning` or `key` (the code table's
`key_column`), listed in order of preference -- by convention the translated form first and the
raw code last. Absent means `[code]`, which is how every column above reads; writing `[code]`
builds the same document. With more than one form, a value is one of them, whether a lookup
found nothing or one source of the table writes it one way and another source the other way;
when each happens is not structured -- write it in `derivation`. `lang` says which language a
stored meaning is in (only with `meaning`; for a code set with a `lookup`, one of its
`meaning_columns[].lang`). The order of `code_sets` and the order of `holds` are independent:
`code_sets: [A, B], holds: [key, code]` is "A's key, else B's, else the raw code".

```yaml
      - column: reason_desc            # coalesce(d.code_desc, t.reason_cd)
        to: attribute
        ref: attr:fee_waiver.reason
        holds: [meaning, code]
        lang: zh
```

A code set's `value` is always the code -- the value its code table, or the SQL's inline
dictionary, is keyed by -- even when the columns store the translated meaning or the key: write
that on each such column with `holds`, and give each column its own `code_sets` in the order its
SQL looks them up (a meaning column, a key column and the code column each carry their own).

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

A concept may have several self relations (one level apart, two levels apart, …), each with
columns of its own. Then every self-referencing column names the one it realises with
`relation`; otherwise the pages, queries and JOIN evidence attribute it to every self relation
of the concept (and `self_reference_relation_unnamed` warns). With one self relation it may be
left out, and nothing changes:

```yaml
      - {column: orig_loan_no, to: foreign_identifier, ref: id:loan_no, relation: rel:loan_renews_loan}
```

`relation` may also go on a `foreign_identifier` holding another concept's identifier (to say
which of several relations between two concepts it is), including an event participant's
derived `rel:<event slug>.<role_name>`. It accepts only a relation with one end the table's
concept (for a role view, or its player) and the other the concept `ref` identifies (or a role
that concept plays); a self-referencing column accepts only a relation from its concept to itself.

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
| `duplicate_table` | a table is represented twice (table names ignore case) |
| `duplicate_column` | a column is bound twice in one representation |
| `binding_attribute` | the attribute is not the represented concept's (or, for a role view, its player's) |
| `binding_identifier` | the identifier is not the represented concept's (or, for a role view, its player's) |
| `binding_foreign_identifier` | `ref` is not an identifier at all (or does not exist) |
| `self_reference_without_relation` | the identifier is the represented concept's own, and no relation has that concept at both ends |
| `binding_relation` | a binding's `relation` is not a relation (or does not exist); its ends are not the table's concept and the concept `ref` identifies; or the column is self-referencing and the relation does not run from its concept to itself |
| `binding_foreign_attribute` | `ref` is not an attribute, or is the represented concept's own (for a role view, or its player's) — bind that as `attribute` |
| `binding_foreign_attribute_via` | `via` is not a column of this table, that column is not a `foreign_identifier`, or the identifier it holds does not identify the attribute's concept |
| `binding_code_set` | an entry of a binding's `code_sets` is not a code set |
| `binding_holds_code_set` | a binding's `holds` has `meaning` or `key`, and it names no `code_sets` while the bound attribute has no `code_set` -- a meaning or a key of no code set |
| `binding_lang` | a binding has `lang` and its `holds` has no `meaning` |

An identifier "is the concept's" when the concept lists it in `identifiers` or the
identifier `identifies` the concept. A subtype may therefore list its supertype's
identifier (the demo's installment loan lists `id:loan_no`).

### Warnings

| Rule | Meaning |
| --- | --- |
| `drafted_ratio` | how many objects are still `drafted` — nothing unconfirmed should be read as settled |
| `concept_without_definition` | a concept has no definition |
| `relation_without_name` | a relation has no verb |
| `empty_code_set` | a code set lists no values and has no `lookup` |
| `binding_code_sets_miss_attribute` | a binding lists `code_sets`, and the bound attribute's `code_set` is not among them |
| `binding_key_without_key_column` | a binding's `holds` has `key`, and none of its code sets has a `lookup` with a `key_column` -- the catalog cannot translate that key |
| `binding_lang_unknown` | a binding's `lang` is not the language of any meaning column of its code sets' `lookup`s (code sets listing their values are not checked) |
| `unmapped_binding` | a column is bound `to: unmapped` |
| `self_reference_relation_unnamed` | a self-referencing column names no `relation` while its concept has two or more self relations — which one it realises cannot be told, so it is attributed to each |
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
`scope_lineage/schemas/ontology-v3.schema.json`. Before writing, `build` checks the document
it built (with any `--lineage/--tables` evidence) against that schema; on a mismatch it
lists each path, writes nothing and exits `1` -- the builder and the schema disagree, which
is a scope-lineage bug, not a fault in the catalog:

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
- keys come out in one fixed order per object type; code and state values are text, and
  every code value carries a boolean `unconfirmed` (flagged `unconfirmed: true`, or a meaning
  that is empty or starts 「待确认」); a cardinality end written `1` is `"1"`; a text
  `arises_when` becomes `{condition}`;
- table names are lower-case (a representation's `table` and `replaced_by`, a spelling's
  `table`, the `via` of `maps_to`, a code set's `lookup` `table`): Hive table names ignore case and the lineage contract
  spells every table in lower case, so the evidence merge and queries match;
- top-level lists are sorted — by `id`, terms by term then target, representations by
  table — so moving an object to another file changes nothing. Lists inside an object
  (attributes, state values, bindings) keep the author's order;
- bindings carry `via` and `relation` through as written; a `foreign_identifier` holding the concept's
  own identifier carries `self_reference: true`; `relation` is an optional addition, and a
  catalog without it builds as before;
- a code set's `lookup` comes out in the key order of the table above (its `filter`
  sorted by column, the literals as text), a binding's `code_sets` in the author's order. Both are optional
  additions and `doc_format` stays `ontology-json/3`; a catalog that writes neither builds
  byte-for-byte the same document as before;
- a binding's `holds` and `lang` follow its `code_sets`, as written; `holds: [code]` is not written
  out (it is what an absent `holds` means), so a catalog without `holds` builds byte-for-byte as before;
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
| `representations["db.table"]` | `table_comment` | `--tables` | the table comment on the table card |
| `representations["db.table"]` | `declared_columns` / `used_columns` | `--tables` | how many columns the metadata declares and the corpus uses |
| `bindings["db.table.column"]` | `sources` / `expression` | `--lineage` | the physical source columns and the final expression (at most 200 characters), only for a binding without a hand-written `derivation` |
| `bindings["db.table.column"]` | `declared_only` | `--tables` | the metadata declares the column and no task in the corpus touches it |
| `code_sets["code:..."]` | `table` / `missing_columns` | `--tables` | when the table a code set's `lookup` names has a card that does not declare some of the lookup's columns: which ones (present only then; `build` also prints a `lookup_column_missing` warning on stderr) |
| `relations["rel:..."]` | `joins` | `--lineage` | `count` and up to three `samples` of JOINs linking the two concepts' tables on columns bound to one identifier of theirs |
| `relations["rel:..."]` | `source_joins` | `--lineage` | JOINs inside a producing task: in a statement writing one end's table, the JOINs made to fill that table's foreign key column; `count` and up to three `samples` (with one more field, `column`: the foreign key filled); counted apart from `joins`, present only when there is such a JOIN |

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
      "table_comment": "Loan snapshot",
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
    },
    "rel:repayment.loan": {
      "joins": {"count": 1, "samples": [{"task": "ads_collection_overdue_borrower_daily", "statement_id": "stmt:001", "on": "demo_dwd.dwd_lending_loan_df.loan_no = demo_dwd.dwd_lending_repayment_di.loan_no"}]},
      "source_joins": {"count": 1, "samples": [{"task": "dwd_lending_repayment_daily", "statement_id": "stmt:001", "column": "demo_dwd.dwd_lending_repayment_di.loan_no", "on": "demo_ods.ods_repay_txn_di.loan_no = demo_dwd.dwd_lending_loan_df.loan_no"}]}
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
  and backed by no JOIN has `count: 0`, one that could not be checked has no `joins` (and no
entry at all unless it has `source_joins`). A JOIN
  counts when one side is a table of each concept and **both** key columns of one key pair
  are bound (as `identifier` or `foreign_identifier`) to the same identifier, one that
  identifies either end: the relation's own concepts, or for a role the player its tables
  bind. A customer id met by a phone number, or two customer ids linking a call to a contact,
  is not a sample of a call–contact relation. Participation relations are counted the same
  way. A relation whose two ends are one concept counts only JOINs with a `self_reference`
  key column realising it (its `relation` names it, or it names none) on at least one side
  (a table joined to itself included): the same instance met in two tables says nothing about
  the relation.
- **JOINs inside a producing task** (`source_joins`) are a second kind of evidence, **never
  added into** `joins`: `joins` answers "is the relation joined this way downstream",
  `source_joins` answers "is the foreign key looked up this way when the table is produced".
  A JOIN counts when the statement writes a table of one end; that table binds a column as
  `foreign_identifier` to an identifier K of the other end; one key column of the JOIN is a
  **lineage source** of that column, and the other key column holds K (bound to K, or a
  registered spelling of K). In the demo the repayment task joins its source's `loan_no` to
  the loan table's `loan_no`, filling exactly the repayment table's foreign key to the loan,
  so `rel:repayment.loan` gets 1. Only the written end needs a table, so a relation with an
  end that has none can have this key too (its entry then has no `joins` and is not counted
  in `relations_checked`). An `identifier` binding is never an anchor (a table's own key does
  not point at the other end); a source table spelling several concepts' identifiers says
  nothing about which concept it represents, and nothing is inferred from it. A relation
  whose two ends are one concept takes only `self_reference` columns; a binding that names a
  `relation` is attributed to that relation alone.
- The `build` summary line names the two apart: `N of M relation(s) backed by a JOIN between
  catalog tables` (`joins`) and `K relation(s) by a JOIN inside a producing task`
  (`source_joins`).
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
scope-lineage catalog render out/ontology.json --out out/pages \
  [--semantics out/pages/semantics]
```

`render` reads the built document only — never the catalog directory — so the pages show
exactly what was built, evidence included. Headings are Chinese, like the other rendered
documents; names are the catalog's own.

`--semantics` names the directory of table pages `semantic render` wrote (`<db.table>.md`).
With it, every table a concept page lists (数据在哪 / 记录在 in the overview, and the A2
数据清单 inventory in the appendix) links to that table's table-semantics page, the link
computed relative to `concepts/`; a table with no page in the directory stays unlinked.
Without it the pages are byte-for-byte unchanged. The table pages link back to the concept
pages with `semantic render --ontology`; see [table semantics](table-semantics.md). The page of
a code table a code set's `lookup` names opens with 「本表是码值集…的码值来源」 ("this table
holds the codes of ..."), linked to `code_sets.md`.

Linking both ways takes a fixed order: the `--semantics` directory must already exist (exit 2
when it does not), and `semantic render --ontology` reads the built `ontology.json` — so
build, then render the table pages, then render the concept pages:

```bash
scope-lineage catalog build <catalog-dir> --out out/catalog
scope-lineage semantic render <documents> --out out/pages/semantics \
  --ontology out/catalog/ontology.json
scope-lineage catalog render out/catalog/ontology.json --out out/pages \
  --semantics out/pages/semantics
```

| File | What it holds |
| --- | --- |
| `index.md` | the concepts by domain (name, kind, definition, number of tables, status), the identifiers, the code sets (and the tables their values live in), a summary of the governance gaps and of the record scopes |
| `concepts/<slug>.md` | one page per concept (`concept:fee_waiver` → `fee_waiver.md`): a one-page overview, then seven sections as its appendix |
| `identifiers.md` | every identifier in full, with the columns bound to it |
| `code_sets.md` | every code set: its values, or the table and condition to look them up by (`lookup`); the attributes it codes; the columns whose `code_sets` consult it, in their order, and what each stores (`holds`) |
| `governance.md` | every gap of every concept, one list per kind of gap; the code values whose meaning is not confirmed; plus the denormalised columns per table (informational, not a gap) |
| `scopes.md` | every table's record scope grouped by the kind of filter it states; the tables declaring none; the business rules and value domains that cite a table |

A concept page opens with one line naming the kind, the domain and the page's drafted share,
then **一页纸概览** (the one-page overview): plain Chinese, names only (no ids such as `id:…` or
`attr:…`, no English enum words, no table wider than two columns), answering what a reader
asks first. A line with nothing to say is left out; a confirmed item is marked ✓:

| Line | Content |
| --- | --- |
| 是什么 | the concept's definition |
| 怎么认出来 | one bullet per identifier: its name, when it arises (「一开始就有」 without `arises_when`, else the condition and its state), its uniqueness scope in words (「全局唯一」 or 「每个客户×App 一个」), and whether it is the primary one |
| 状态 | the state values in order joined by →, the events moving them written on the arrows (`未认证 —实名认证→ 已认证`); transitions between values that are not neighbours follow in brackets |
| 数据在哪 | an entity's core and extension tables (a role's role-view tables), each with the table comment or the first line of its notes (≤30 characters); a deprecated table reads 「已废弃，改用 …」; then how many more tables carry the concept's identifiers and over how many domains (see appendix A3). For an event the line is 「记录在」 and lists its event-detail tables |
| 拥有的 | the compositions whose whole this concept is: 「verb other-name」 |
| 关联的 | the other associations, compositions and generalizations, read from this concept's side: `inverse_name` when the concept is the relation's `to` end, the whole sentence when there is none; a self relation with an `inverse_name` both ways ("<name> / <inverse_name> <concept name>") |
| 参与的事件 | the events the concept takes part in, grouped by the event's domain |
| 扮演的角色 | the roles this concept plays, with their condition (≤30 characters) |
| 参与者 / 发生时间 | events only: each participant as 「role name → concept name」; the name of the occurred-at attribute |
| 承担者 / 成立条件 | roles only |
| 要注意 | at most 5: the constraints on the concept, its attributes or identifiers that are hard or business rules, confirmed first, each as its expression (≤60 characters, cut with …) |

After the overview comes **附录** (the appendix): sections A1–A7 answer the seven things a
reader opens the page for (A1's table
has a 编号 row with the concept id):

| Section | Content |
| --- | --- |
| A1 定义与身份 | definition, kind, status, synonyms; identifiers (arising condition, uniqueness scope, physical spellings, mappings); the state machine (values, transition events); an event's participants, a role's player, context and condition |
| A2 数据清单 | the tables, grouped by representation kind (核心, 扩展, 从属, 事件明细, 状态历史, 标识映射, 角色视图, 汇总, 中间): a note (the table card's comment, the representation's `notes`), grain (identifiers, source, and what lineage proves), time semantics and how to read by them (a snapshot 「按单个 dt 分区取数」, a zipper by its validity window), refresh, record scope, producing tasks, deprecation and replacement; one hop of lineage per table |
| A3 带本概念标识的表 | every column, in the tables of any concept, binding one of this concept's identifiers as `identifier` or `foreign_identifier`: table, the table's concept, column, identifier, and how (a self reference is marked). A concept with no table of its own still shows where it can be joined in; a role has no identifier of its own and points to its player |
| A4 属性 | by category (描述, 状态, 度量, 时间): definition, type and unit, code values (value=meaning; for values in a code table, how to look them up), every table column that holds it (with its code map; a column consulting code sets in order reads 「先查 A，查不到查 B」, look in A, then B; a column with `holds` adds what it stores, 「存含义（zh）或码」 (stores the meaning, in zh, or the code), after the code sets as 「（码值：查 A；存代理键）」; one another table repeats is marked 「冗余（经 via column）」), how it is derived |
| A5 关系 | association, composition and generalization read from this concept's side, with cardinality and JOIN count (a self relation's far end reads 「本概念」 with the columns that carry it — a column naming a `relation` only under that one, a column naming none under every self relation — and one with an `inverse_name` reads both ways); JOINs inside a producing task (`source_joins`), when there are any, as 「生产任务内连接 N 次（如 …，填 <foreign key column>）」, apart from the JOIN count; when the count is 0 or could not be taken, what the catalog itself shows: the tables holding both ends (representing one or binding its identifier; a role through its player's identifiers; a self relation only through a self-referencing column realising it) and the relation's `evidence`; the events it takes part in (its role, how many tables the event has); the roles it plays, or — on a role's page — the player it belongs to |
| A6 约束 | the constraints on the concept, its attributes, identifiers and relations, by kind, with strength and status |
| A7 治理缺口 | drafted share, unmapped columns, attributes no table holds, state or coded attributes without values, whether the concept has any table; with evidence also the conflicts, bound columns nobody uses and relations no JOIN backs |

Anything that came from the corpus is labelled 「血缘」; without evidence those cells show
「—」 rather than a guess.

`scopes.md` files every `scope` line under a kind of filter by keywords; a line stating two
kinds is listed under both, and one stating none goes to 「其他」. Chinese keywords match
anywhere, English ones as whole words (an underscore separates words, so `is_deleted` says
`deleted`):

| Kind | kind | Keywords (a selection) |
| --- | --- | --- |
| 有效记录/记录状态 | `validity` | 有效, 生效, 状态, `valid`, `active`, `status` |
| 删除/注销 | `deletion` | 删除, 注销, 作废, `deleted`, `cancelled`, `void` |
| 去重/最新 | `dedup` | 去重, 最新, `distinct`, `latest`, `row_number`, `rn` |
| 分区/快照日期 | `partition` | 分区, 快照, `dt`, `ds`, `partition`, `snapshot` |
| 其他 | `other` | none of the above |

The same page lists the tables that declare no `scope`, and the constraints of kind
`business_rule` / `value_domain` that cite a representation's table in their `evidence` or
expression.

## Query: `catalog query`

```bash
scope-lineage catalog query out/ontology.json concept 用户
scope-lineage catalog query out/ontology.json table spark_catalog.demo_dwd.dwd_lending_loan_df --json
```

| Kind | Term | Answer |
| --- | --- | --- |
| `concept` | id, name, synonym or term | identity, identifiers, attributes, states, tables, the page to read, and the concept page's one-page overview (`overview`, the same fields as the page) |
| `table` | `db.table` (a catalog prefix is ignored) | the concept it carries, its time semantics and how to read by them (`usage`), the table comment and `notes`, its record scope, the business rules and value domains citing it (`constraints`), and what every bound column points at, with evidence; a denormalised column reads `→ 冗余属性 <attribute> of <concept>（经 <via>）`, a self-referencing one names its relation; for a code table (one a code set's `lookup` names), the code sets it holds and how each is looked up (`code_sets`), and when the table is also represented, the representation's answer gains `code_sets`; exit code `0` |
| `column` | `db.table.column` | the attribute or identifier it holds and its concept (a column with `code_sets` lists them in order, each with how it is looked up; one with `holds` says what it stores, 「存含义（zh）或码」, and carries `holds` and `lang`) — or, in a code table, what kind of column it is (code, meaning, surrogate key, filter, validity: `role`) and which code sets it serves — or the identifier it spells; a self-referencing column carries `self_relations` (the self relations it realises: the one its `relation` names, or all of them) |
| `identifier` | id, name or physical spelling | what it identifies, its scope and spellings, the columns bound to it |
| `attribute` | id, name or term | its concept, code values (with a `lookup`, `code_set` also carries how and in which table to look them up), derivation and every table column |
| `related` | a concept's id, name, synonym or term | one hop: relations read from its side (a self relation with an `inverse_name` both ways), events, participants, roles, player, tables, and the tables carrying its identifiers (`carriers`); every relation and event carries `carried_together` (the tables holding both ends) and `evidence`, printed when no JOIN backs it; with JOINs inside a producing task also `source_joins` (the count), printed as 「生产任务内连接 N 次」 apart from `joins` |
| `carriers` | a concept's id, name, synonym or term | every column, in the tables of any concept, binding one of its identifiers: table, the table's concept, column, identifier, and how |
| `scope` | a kind of filter (`validity`/有效记录, `deletion`/删除, `dedup`/去重, `partition`/分区, `other`/其他; the label or either half of it works too) or a keyword | the tables whose scope lines or cited rules state it, each with those lines (and their kinds), the rules and how to read the table |

Names match exactly, ignoring case and surrounding spaces, in that order (id, then name,
then synonym, then term); nothing is guessed. Table and column names in `table`, `column`
and an `identifier` spelling ignore case too. The text answer is a few lines; for a `concept`
it leads with the same 是什么 / 怎么认出来 / 数据在哪 (记录在 for an event) as the page's overview:

```text
客户 concept:customer · 实体 · 客户与账户 · 已确认（owner）
  是什么：A person the shop has registered, whether or not they ever borrow.
  怎么认出来：客户号：一开始就有，全局唯一（主标识） ✓；认证客户号：assigned when the customer passes identity verification（进入「已认证」状态时），全局唯一
  数据在哪：demo_dwd.dwd_party_customer_info_df（Customer master, one row per …） ✓；demo_dwd.dwd_party_customer_ext_df；另有 4 张表带本概念的标识，分布在 2 个域
  标识符：客户号 id:customer_id（主）、认证客户号 id:verified_customer_no
  属性：性别、注册时间、认证状态
  状态：未认证、已认证
  表：demo_dwd.dwd_party_customer_ext_df（扩展）、demo_dwd.dwd_party_customer_info_df（核心）
  页面：concepts/customer.md
```

For a concept with no table of its own, `carriers` finds where it can be joined in:

```text
带 渠道 concept:channel 标识的表（渠道编码 id:channel_code）
  - demo_dwd.dwd_party_account_map_df（应用账户）：channel_code → 外部标识符 渠道编码
  - demo_dws.dws_lending_loan_summary_1d（借据）：channel_code → 外部标识符 渠道编码
```

`--json` prints `{"query": {"kind", "term"}, "matches": [...]}` for an agent. Exit code: `0`
something matched, `1` nothing did, `2` the file could not be read (`1` too when it is not an
`ontology-json/3` document).

## Drafting: `catalog digest` and `catalog merge`

Once a batch of tables has [table semantics](table-semantics.md) (`table-semantics/1`), a
catalog can be drafted from them without an ad-hoc script each time:

1. `catalog digest` condenses the table semantics into drafting material and, against an
   existing catalog, names the tables and columns it does not cover yet;
2. a person or a model drafts the concepts and relations from it (`concepts/`,
   the `relations` and `identifiers` files); a fragment cannot add a concept or change an
   existing identifier, so every new concept the groups need (an event with its time
   attribute), every new identifier and every new spelling of an existing one is written
   here;
3. the tables are split into groups and each group gets one fragment (`catalog-fragment/1`):
   attributes, code sets, constraints, terms, and each table's representation with its
   column bindings;
4. `catalog merge` merges the fragments into a copy of the catalog, reports conflicts,
   validates the result and prints a coverage report;
5. `catalog build` / `catalog render`, then the owner reviews.

The agent skill's full workflow and the fragment prompt are in
`skills/scope-lineage/references/catalog-fragment-prompt.md`.

### `catalog-fragment/1`

A fragment is what drafting one group of tables produces. Every item has **exactly** the
shape of the catalog file it lands in (the schema's item definitions are copies of the
catalog schemas', and a test keeps them equal), so a merge moves items and never
translates them. The "merged into" column names files by their stem: a file the catalog has
keeps its form (`.yaml` / `.yml` / `.json`), and a new one takes the form of the manifest
`catalog.*` (step 4 of `catalog merge` below).

| Key | Holds | Merged into |
| --- | --- | --- |
| `doc_format` | `catalog-fragment/1` (required) | — |
| `group` | the group name: lower-case letters, digits, `_`, `-` (required) | new representations go to `mapping/<group>.*` |
| `attributes` | `{"concept:<id>": [attribute, ...]}`, shaped like a concept's `attributes` | the `concepts/` file that declares the concept |
| `code_sets` | code sets, shaped like the `code_sets` file's items (with `lookup` when the values live in a code table) | `code_sets.*` |
| `identifiers` | identifiers, shaped like the `identifiers` file's items; only ones that are really missing | `identifiers.*` |
| `constraints` | constraints, shaped like the `constraints` file's items; only ones with evidence | `constraints.*` |
| `terms` | terms, shaped like the `terms` file's items | `terms.*` |
| `representations` | representations and bindings, shaped like the `mapping/` files' items | `mapping/<group>.*` |
| `notes` | questions or conflicts for the owner, as a list of text | printed in the merge report only |

The example
[`examples/catalog-fragments/disbursement.json`](../../examples/catalog-fragments/disbursement.json)
adds a disbursement table to the demo catalog (an excerpt):

```json
{
  "doc_format": "catalog-fragment/1",
  "group": "disbursement",
  "attributes": {
    "concept:disbursement": [
      {"id": "attr:disbursement.pay_method", "name": "放款方式", "definition": "How the money reached the borrower.", "category": "descriptive", "type": "string", "code_set": "code:pay_method"}
    ]
  },
  "code_sets": [
    {"id": "code:pay_method", "name": "放款方式", "values": [{"value": "BANK", "meaning": "bank transfer"}, {"value": "WALLET", "meaning": "in-app wallet"}]}
  ],
  "representations": [
    {
      "table": "demo_dwd.dwd_lending_disbursement_di",
      "concept": "concept:disbursement",
      "kind": "event_detail",
      "grain": {"identifiers": ["id:disbursement_txn_no"], "source": "inferred"},
      "time": "incremental",
      "table_status": "active",
      "bindings": [
        {"column": "disburse_txn_no", "to": "identifier", "ref": "id:disbursement_txn_no"},
        {"column": "pay_method", "to": "attribute", "ref": "attr:disbursement.pay_method"},
        {"column": "remark", "to": "unmapped"},
        {"column": "dt", "to": "technical"}
      ]
    }
  ],
  "notes": ["remark holds free text; is any of it a business attribute?"]
}
```

The schema is `scope_lineage/schemas/catalog-fragment.schema.json`.

### `catalog digest`

```bash
scope-lineage catalog digest out/semantics [--catalog examples/catalog-demo] \
  [--only demo_dwd.dwd_party_customer_info_df ...] --out out/digest
```

Reads every legal `table-semantics/1` document in the directory (the toolchain's own
documents, such as a confirmations file, are passed over; a document that fails its schema
is skipped with a line on stderr) and writes `digest.md` and `digest.json`
(`catalog-digest/1`) in table order. One section per table:

- the one-line summary, and the concept and representation kind the document names;
- what a row is, the grain columns (with their source and whether they are unique), the
  time semantics (`snapshot` / `incremental` / `zipper`) and how to read it, the scope;
- identifier, foreign-identifier, state, time, measure and descriptive columns (each with
  its meaning, and its codes when it has them); technical columns by name only;
- the tables it is built from (with their role) and the tables that read it; what to watch
  and the open questions.

With `--catalog` a "catalog coverage" section comes first: tables with no representation,
and columns of represented tables with no binding (table names match ignoring case and a
catalog prefix); a table a code set's `lookup` names counts as a code-set source
(`code_set_sources`: table → code set ids), not as a table with no representation; each
table's section also ends with its standing in the catalog. The
output is deterministic: the same inputs give byte-identical files.

Exit codes: `0` written; `1` no legal document, a document was skipped (the rest is still
written), or a table named by `--only` has no document; `2` the directory or `--catalog`
cannot be read.

### `catalog merge`

```bash
scope-lineage catalog merge examples/catalog-demo \
  examples/catalog-fragments/disbursement.json --out out/merged
scope-lineage catalog merge <catalog-dir> <group>.json ... --in-place
```

1. Every fragment is read and checked against its schema first; if one fails, nothing is
   written. A base catalog whose files do not parse or do not fit their schemas is not
   merged either.
2. The base catalog is copied to `--out` (a new or empty directory; hidden files are not
   copied). An `--out` equal to the base is refused unless `--in-place` is given; an
   `--out` inside the base is refused too.
3. Fragments are merged in command-line order. Each item is looked up by its key across the
   whole catalog and the fragments merged before it: attributes, code sets, identifiers
   and constraints by `id`, terms by `term` + `refers_to`, representations by `table`. An
   equal item counts as unchanged; **the same key with different content is a conflict**,
   listed in the report, and the later item is not applied. Attributes go into the file
   that declares their concept; an unknown concept is an error and its attributes are not
   applied; an attribute id already declared on another concept is a conflict too.
4. Only the files that changed are rewritten (YAML read with YAML 1.2 booleans and written
   back safely; JSON written back as JSON); every other file stays byte-identical. Comments
   in a rewritten YAML file are lost.
   A file the catalog does not have yet (`constraints`, `mapping/<group>`) is created in the
   manifest's form: an all-JSON catalog gets `.json` files and the merge never needs PyYAML.
5. `catalog validate` runs in-process on the result and its errors and warnings are
   printed; last comes the coverage report: for each table in the fragments, whether it has
   a representation and how many columns bind to each target (`identifier`,
   `foreign_identifier`, `attribute`, `foreign_attribute`, `technical`, `unmapped`).

```text
Merged 1 fragment(s) into out/merged: added attribute=1, code_set=1, constraint=1, term=2, representation=1; 1 unchanged; 0 conflict(s), 0 unknown concept(s)
  files written: code_sets.yaml, concepts/lending.yaml, constraints.yaml, mapping/disbursement.yaml, terms.yaml
note    (disbursement) remark holds free text; is any of it a business attribute?
Catalog demo-lending (catalog-yaml/1): 0 error(s), 3 warning(s)
...
Coverage: 1 table(s) in the fragments, 1 with a representation, 1 unmapped column(s)
  demo_dwd.dwd_lending_disbursement_di  concept:disbursement  event_detail  8 column(s): identifier=1 foreign_identifier=2 attribute=3 technical=1 unmapped=1
```

| Exit code | Meaning |
| --- | --- |
| `0` | merged, and the result validates without errors (warnings allowed) |
| `1` | a fragment or the base catalog fails its schemas (nothing written); or there are conflicts, unknown concepts, or validation errors after the merge (written, so they can be read in place) |
| `2` | a fragment or the base catalog cannot be read; `--out` is the base (without `--in-place`), inside it, or not empty |

## Writing YAML safely

- The catalog reads YAML with 1.2 booleans: only `true` / `false` are booleans, so `on:`
  (a constraint key) and codes such as `no` or `off` stay text.
- Quote cardinality ends (`"1"`) and code values that must keep leading zeros (`"01"`).
- A date written bare (`2026-01-31`) is read as the text `"2026-01-31"`.
