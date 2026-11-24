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
  metrics.yaml          # metrics: [...]
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
| `scope` | yes | `global`, or `{per?: [<concept id>, ...], by?: [{column, table?}]}` (at least one): `per`, unique only within each combination of those concepts; `by`, unique only within each value of these physical columns (a discriminator that is no business concept, such as a source system or an environment; the shape of `spellings`) |
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
`id: code:<slug>`, `name`, `values: [{value, meaning, key?, retired?, unconfirmed?}]`,
`definition?`. A value is text or an integer; `0` and `"0"` are the same code. `key` (text or an
integer) is the surrogate key an inline dictionary pairs with the code: a column storing keys
(`holds: [key]`) is translated through it and no longer warns `binding_key_without_key_column`;
pages and queries print 「值=含义（代理键 k）」. A value seen
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

`lookup` names a **physical code table** (`db.table`) and nothing else. A dictionary defined
inline in SQL (a `VALUES` CTE, a `CASE` mapping, a literal list) is not a table: write its
codes as the code set's `values` and name the task that produces it in `evidence`; do not
give the CTE a name and use it as `lookup.table`. A lookup to a table that does not exist
would make `catalog query table` answer for a table that is not there.

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
`code_set?`, `derivation?` (how it is computed, in words), `additivity?` (`additive` — adds
up over every dimension / `semi_additive` — over some, not over time, like a balance /
`non_additive` — never, like a ratio or a rate).

An attribute's code sets are its own `code_set`; when it has none, they are the `code_sets`
of the columns bound to it (as `attribute` or `foreign_attribute`), each counted once, in
the order first seen. Every reader of "this attribute's codes" uses this one rule: the A4
「码值」 cell, `catalog query attribute`, the missing-codes gap and the attributes
`code_sets.md` lists under a code set. An attribute that writes a `code_set` keeps exactly
that one; its columns' other sets are not added to it.

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
without an `inverse_name` reads one way, with `name`. Borrower → loan takes
`name: 持有` ("holds") and `inverse_name: 持有人为` ("is held by"), which read 「持有 借据」 and 「持有人为 借款人」;
`name: 持有借据` ("holds a loan") reads 「持有借据 借据」.

### Constraint

A condition that must hold. `id: cons:<slug>`, `kind` (`unique` / `cardinality` /
`mandatory` / `value_domain` / `referential` / `temporal` / `state_transition` /
`derivation` / `business_rule`), `on` (a concept, attribute, relation or identifier),
`expression` (text), `strength` (`hard` / `soft`). Optional: `rules` — the table-semantics
rules the constraint carries, each `<db.table>#<rule id>` (`demo_dwd.t#r2`; the digest lists
every table's rules), and `predicate` — the condition as one column test `{column, op,
value}`, `op` one of `=` `!=` `<` `<=` `>` `>=` `in` `not_in` `is_null` `not_null` `like`
(`in` / `not_in` take a list, `is_null` / `not_null` no value).

```yaml
constraints:
  - id: cons:loan_no_unique
    kind: unique
    on: id:loan_no
    expression: no two loans share a loan_no, whatever the channel
    strength: hard
  - id: cons:principal_positive
    kind: value_domain
    on: attr:loan.principal
    expression: principal > 0
    strength: hard
    rules: [demo_dwd.dwd_lending_loan_df#r1]
    predicate: {column: principal_amt, op: ">", value: 0}
```

### Metric

A number the business reads off a concept. `id: metric:<slug>`, `name`, `on` (the concept
counted or added up), `aggregation` (`sum` / `count` / `count_distinct` / `avg` / `min` /
`max` / `ratio` / `other`). Optional: `definition`, `measure` (the attribute aggregated),
`filter` (which instances count, in words), `constraints` (the `cons:` ids that scope it),
`time_window` (in words), `dimensions` (what it may be broken down by: attributes of `on`,
or concepts linked to `on` -- an event's participants, the other end of a relation),
`additivity` (as on an attribute), `unit`, and the common fields. `on` must be a concept,
`measure` an attribute, each dimension an attribute or a concept linked to `on`, each
constraint a constraint (`metric_on`, `metric_measure`, `metric_dimension`,
`metric_constraint`). An attribute used as `measure` or as a dimension must belong to `on` or
to a concept linked to `on`; a linked role counts with its player, whose attributes its
tables bind as their own.

```yaml
metrics:
  - id: metric:principal_outstanding
    name: 在贷本金
    on: concept:loan
    measure: attr:loan.principal
    aggregation: sum
    filter: loans not settled
    dimensions: [attr:loan.loan_status, concept:borrower]
    additivity: semi_additive
    unit: CNY
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
| `bindings` | yes | `[{column, to, ref?, via?, relation?, derivation?, time_role?, code_map?, code_sets?, code_sets_by?, holds?, lang?}]` |

A binding's optional `time_role` says what time the column carries: `valid_from` /
`valid_to` (the validity window of a zipper row), `partition`, `event_time`, `record_time`
(when the row was written) or `business_date` (the business day it counts for).

A binding's `to` says what the column is:

| `to` | `ref` | Meaning |
| --- | --- | --- |
| `attribute` | required | an attribute of the represented concept (a role view may also bind its player's) |
| `identifier` | required | an identifier of the represented concept (a role view may also bind its player's) |
| `foreign_identifier` | required | another concept's identifier — a relation, physically; or the represented concept's own identifier (another instance of the same concept), provided the catalog has a relation whose two ends are that concept; an optional `relation: rel:<id>` names the relation this column realises |
| `foreign_attribute` | required | an attribute of another concept X, repeated on this row (a wide table); `via` is required and names the column of this table bound as `foreign_identifier` to an identifier of X. It may also be the represented concept's own attribute, but only another record's of the same concept: the `via` column must be bound as `foreign_identifier` to an identifier of the concept the attribute belongs to (the self-referencing column of the row above); in a role view, a column holding the player's identifier carries the player's attributes this way, never the role's |
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

`code_sets_by` says how that list is read. `lookup`, the same as leaving it out, is the lookup
order above. `source` says each source or branch writing the column -- a UNION branch, or one
of several statements writing the table -- uses one of the code sets, its own: the order means
nothing, and a value is never looked up in a second set. Pages and queries then print
「按来源分别查 A、B」 (each source looks up its own of A, B) instead of 「先查 A，查不到查 B」; which
branch uses which set can be said in `derivation`. `code_sets_by` needs `code_sets`, and
`source` needs at least two (over one set both readings are the same); otherwise
`binding_code_sets_by` fails. `lookup` is not written out by `build`. It changes nothing else:
`binding_code_sets_miss_attribute` and `holds` read the list the same either way.

```yaml
      - column: reason_label           # branch 1: CASE over source A's codes; branch 2: over source B's
        to: attribute
        ref: attr:fee_waiver.reason
        code_sets: [code:waiver_reason, code:waiver_channel]
        code_sets_by: source
        holds: [meaning, code]
```

`holds` says what a value of the column is, of those code sets (its `code_sets`, or, when it
names none, the bound attribute's `code_set`): `code`, `meaning` or `key` (the code table's
`key_column`), listed by convention with the translated form first and the raw code last. Absent means `[code]`, which is how every column above reads; writing `[code]`
builds the same document. With more than one form, a value is one of them, whether a lookup
found nothing or one source of the table writes it one way and another source the other way
(whether the code sets themselves are looked up in order or one per source is `code_sets_by`);
which form each source writes is not structured -- write it in `derivation`. `lang` says which language a
stored meaning is in (only with `meaning`; for a code set with a `lookup`, one of its
`meaning_columns[].lang`). The order of `code_sets` and the order of `holds` are independent:
`code_sets: [A, B], holds: [key, code]` is "A's key, else B's, else the raw code".
A column written by several sources that store different forms (one branch the key, another the
raw code) writes `[key, code]` too; there the order of `holds` is only the convention, not an
order of precedence or a fallback, and which branch writes which form goes in `derivation`:

```yaml
      - column: reason_key             # branch 1: the dictionary's dict_key; branch 2: the raw code
        to: attribute
        ref: attr:fee_waiver.reason
        code_sets: [code:waiver_reason]
        holds: [key, code]
```

```yaml
      - column: reason_desc            # coalesce(d.code_desc, t.reason_cd)
        to: attribute
        ref: attr:fee_waiver.reason
        holds: [meaning, code]
        lang: zh
```

A code set's `value` is always the code -- the value its code table, or the SQL's inline
dictionary, is keyed by; an inline dictionary written as `values` (above) keeps the source code in
`value` and the translated label in `meaning` -- even when the columns store the translated meaning or the key: write
that on each such column with `holds`, and give each column its own `code_sets` in the order its
SQL looks them up (a meaning column, a key column and the code column each carry their own).
Edge cases:

- One column written by several sources -- UNION branches, or several statements writing the
  table -- each using its own source's code set: list them all in `code_sets` and write
  `code_sets_by: source`; pages and queries print 「按来源分别查 A、B」. Leave the key out only for a
  real fallback (a lookup in A, then B, on every row).
- One attribute split into per-source code sets: the attribute writes no `code_set`; each
  column writes its own source's set in `code_sets`, and the attribute's codes are all of them
  (the rule under Attribute). A column whose `holds` has `meaning` or `key` then needs its own
  `code_sets`, or it fails `binding_holds_code_set`.
- An attribute with no code set at all (no `code_set` of its own, no `code_sets` on any column bound
  to it; no dictionary is joined and the codes are unknown): a column storing the name with the record
  still writes `holds: [meaning]` (with `lang`), so it reads apart from the code column. Once any column
  gives the attribute a code set, this column must name its own `code_sets`; `key` always needs a code set.
- A CASE branch (such as ELSE) with no source code: invent no code; write the rule in `derivation`
  (and, if useful, the code set's `definition`).
- A code set listing only `values` has no key column: give each value its `key` (the surrogate key
  the inline dictionary pairs with that code) and a `holds: [key]` column is translated; without
  `key` the column warns `binding_key_without_key_column` (the catalog cannot translate that key),
  and `[key]` is still right.
- A column that looks a code table up only to translate a code is a code column: bind it as
  `attribute`. `code_sets` is also accepted on a `foreign_identifier` (its `holds` then needs
  `code_sets`); it shows in queries and `code_sets.md`, not on `identifiers.md`.
- A recode (`Y/N` → `1/0`, a code mapped to another set's code, a two-step mapping to a target code):
  the column stores the target set's code; no `holds`; write the mapping in `derivation`.

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
| `metric_on` / `metric_measure` / `metric_dimension` / `metric_constraint` | a metric's `on` is not a concept, its `measure` not an attribute, a dimension neither an attribute nor a concept linked to `on`, a `constraints` entry not a constraint; an attribute used as `measure` or dimension belongs to neither `on` nor a concept linked to it (a linked role with its player) |
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
| `binding_foreign_attribute` | `ref` is not an attribute; or it is the represented concept's own (for a role view, or its player's) while the `via` column is not a `foreign_identifier` naming another record of the attribute's concept — this row's own attribute is bound as `attribute` |
| `binding_foreign_attribute_via` | `via` is not a column of this table, that column is not a `foreign_identifier`, or the identifier it holds does not identify the attribute's concept |
| `binding_code_set` | an entry of a binding's `code_sets` is not a code set |
| `binding_code_sets_by` | a binding has `code_sets_by` and no `code_sets`, or `code_sets_by: source` with fewer than two |
| `binding_holds_code_set` | a binding's `holds` has `meaning` or `key`, and it names no `code_sets` while the bound attribute has no `code_set` -- a meaning or a key of no code set. Not raised when `holds` has only `meaning` and the bound attribute has no code set at all by the rule under Attribute |
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
| `binding_key_without_key_column` | a binding's `holds` has `key`, and none of its code sets has a `lookup` with a `key_column` or `values` carrying a `key` -- the catalog cannot translate that key |
| `binding_lang_unknown` | a binding's `lang` is not the language of any meaning column of its code sets' `lookup`s (code sets listing their values are not checked) |
| `unmapped_binding` | a column is bound `to: unmapped` |
| `grain_identifier_unbound` | a representation's grain names an identifier that no column of the table binds (`identifier` or `foreign_identifier`); whose identifier it is is not checked, a summary table's grain may be another concept's |
| `self_reference_relation_unnamed` | a self-referencing column names no `relation` while its concept has two or more self relations — which one it realises cannot be told, so it is attributed to each |
| `unknown_file` | a file the layout does not name; it was ignored |

Semantic completeness — places where the catalog says less than its own shape asks for:

| Rule | Meaning |
| --- | --- |
| `state_attribute_without_states` | a concept has a `state` attribute with a code set (by the rule under Attribute) and no `states` |
| `measure_without_unit` | a `measure` attribute has no `unit`, and its `notes` do not carry 「待 owner 确认：单位」 (the sentence a drafter writes when the material gives no unit; such a measure is not warned) |
| `zipper_without_validity` | a `zipper` representation has no binding with `time_role: valid_from`, or none with `valid_to` |
| `participation_without_event` | a declared `participation` relation has no event at either end |
| `generalization_cycle` | `generalization` relations run in a circle (named once, from its smallest concept) |
| `relation_without_definition` | a declared relation has no `definition` |

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
constraints, metrics, terms and bindings.)

`counts.density` measures how much meaning the catalog carries. Each coverage is
`{count, total, ratio}` (`ratio` rounded to two places, `null` when `total` is 0):
`attribute_unit` (measures with a `unit`, over measures), `attribute_derivation` (attributes
with a `derivation`, over all attributes), `code_set_values` (code sets listing values),
`relation_definition` (declared relations with a `definition`). Plain counts: `states`
(concepts with `states`), `roles`, `metrics`, `constraints`, `constraints_with_rules`. The
text form prints them on one `density:` line.

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
- keys come out in one fixed order per object type; code and state values are text (so is a
  code value's `key`), and every code value carries a boolean `unconfirmed` (flagged `unconfirmed: true`, or a meaning
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
- a top-level `metrics` list (sorted by id; `constraints` and `dimensions` always lists) and
  `counts.metrics` sit beside the constraints; a constraint's `rules` and `predicate`, an
  attribute's `additivity` and a binding's `time_role` are carried as written. All are
  additions: `doc_format` stays `ontology-json/3`;
- a binding's `code_sets_by`, `holds` and `lang` follow its `code_sets`, as written;
  `code_sets_by: lookup` and `holds: [code]` are not written out (they are what an absent key
  means), so a catalog without them builds byte-for-byte as before;
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
| `representations["db.table"]` | `refresh` | `--lineage` | those tasks' schedule cycle, or the cron when the cycle is missing or the literal `unknown` (any case); `unknown` only with no cron either |
| `representations["db.table"]` | `upstream_tables` / `downstream_tables` | `--lineage` | one hop of table lineage: what the writers read, what the readers write |
| `representations["db.table"]` | `grain_proof` | `--lineage` | the best grain any writer proves: `confidence` (`proven` / `candidate` / `none`), `keys` (target column names; keys a WHERE pins are left out), `basis`, `task` |
| `representations["db.table"]` | `conflicts` | `--lineage` | `grain_not_proven` (declared `proven`, lineage cannot prove it), `grain_not_exposed` (declared `proven`, lineage proves a key the write does not expose on target columns), `grain_mismatch` (both proven, different columns) or `table_identity_ambiguous` (corpus names that are not one table all match this catalog table, listed in `names`; no other lineage evidence is attached) |
| `representations["db.table"]` | `table_comment` | `--tables` | the table comment on the table card |
| `representations["db.table"]` | `declared_columns` / `used_columns` | `--tables` | how many columns the metadata declares and the corpus uses |
| `bindings["db.table.column"]` | `sources` / `expression` | `--lineage` | the physical source columns and the final expression (at most 200 characters), only for a binding without a hand-written `derivation` |
| `bindings["db.table.column"]` | `declared_only` | `--tables` | the metadata declares the column and no task in the corpus touches it |
| `code_sets["code:..."]` | `table` / `missing_columns` | `--tables` | when the table a code set's `lookup` names has a card that does not declare some of the lookup's columns: which ones (present only then; `build` also prints a `lookup_column_missing` warning on stderr) |
| `relations["rel:..."]` | `joins` | `--lineage` | `count` and up to three `samples` of JOINs linking the two concepts' tables on columns bound to one identifier of theirs; `by_column` (when `count` > 0): how many of them involve each catalog column on either side, `db.table.column` → n; the samples keep one JOIN per column while the limit allows |
| `relations["rel:..."]` | `source_joins` | `--lineage` | JOINs inside a producing task: in a statement writing one end's table, the JOINs made to fill that table's foreign key column; `count` and up to three `samples` (with one more field, `column`: the foreign key filled), and `by_column`: how many fill each foreign key column, `db.table.column` → n, the samples keeping one JOIN per column while the limit allows; counted apart from `joins`, present only when there is such a JOIN |

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
      "joins": {"count": 1, "samples": [{"task": "ads_collection_overdue_borrower_daily", "statement_id": "stmt:001", "on": "demo_dwd.dwd_lending_borrower_df.customer_id = demo_dwd.dwd_lending_loan_df.customer_id"}], "by_column": {"demo_dwd.dwd_lending_borrower_df.customer_id": 1, "demo_dwd.dwd_lending_loan_df.customer_id": 1}}
    },
    "rel:repayment.loan": {
      "joins": {"count": 1, "samples": [{"task": "ads_collection_overdue_borrower_daily", "statement_id": "stmt:001", "on": "demo_dwd.dwd_lending_loan_df.loan_no = demo_dwd.dwd_lending_repayment_di.loan_no"}], "by_column": {"demo_dwd.dwd_lending_loan_df.loan_no": 1, "demo_dwd.dwd_lending_repayment_di.loan_no": 1}},
      "source_joins": {"count": 1, "samples": [{"task": "dwd_lending_repayment_daily", "statement_id": "stmt:001", "column": "demo_dwd.dwd_lending_repayment_di.loan_no", "on": "demo_ods.ods_repay_txn_di.loan_no = demo_dwd.dwd_lending_loan_df.loan_no"}], "by_column": {"demo_dwd.dwd_lending_repayment_di.loan_no": 1}}
    }
  }
}
```

(Abridged.) How the evidence is matched:

- **Tables** match on their last two dotted segments: the demo's loan task writes
  `spark_catalog.demo_dwd.dwd_lending_loan_df`, and it lands on the representation
  `demo_dwd.dwd_lending_loan_df`. A table the corpus never names gets no entry.
  The limit: the catalog names tables `db.table`, so it cannot tell two catalogs' tables of
  the same name apart. When the names matched to one catalog table are not spellings of one
  table (`cat1.ods.t` and `cat2.ods.t` with `SCOPE_LINEAGE_CATALOG_PREFIXES` unset; `ods.t`
  beside one `cat1.ods.t` is one table), the table gets only the conflict
  `table_identity_ambiguous`, listing those names, and no lineage evidence (no
  `grain_proof`, no binding sources, and JOINs touching it are not counted for relations).
  Configure the catalogs in `SCOPE_LINEAGE_CATALOG_PREFIXES` if they are one table.
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
  [--semantics out/pages/semantics] [--docs <documents>]
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

`--docs` names the directory of table-semantics documents (`<db.table>.json`, the directory
`catalog context --semantics` takes; not the pages `--semantics` takes). With it `index.md`
also counts what those documents say; without it no number below is shown. The options are
independent: `--semantics` only links, `--docs` only counts.

`index.md` opens with 用之前先看 (what to look at before using the catalog): one fixed
sentence that the page states what the catalog has and lacks structurally, and that whether
answers are right is a matter of acceptance testing; one fixed sentence that question
answering uses the built catalog file together with the table-semantics documents; then the
summary of the governance gaps. With `--docs` the summary gains two rows, and a section
按表看 (by table) follows it:

| Row | How it is counted |
| --- | --- |
| 唯一键有血缘证据的表 (unique key with lineage evidence) | tables whose grain lineage proved (`grain_proof.confidence` is `proven`) out of all tables; and how many of those the table's document calls not unique (`summary.row.unique` is `no`). Shown only when the catalog was built with `--lineage` |
| 单位有材料依据的度量属性 (measure units the material supports) | measure attributes at least one of whose bound columns has a `unit` in its table's document, out of those that can be judged; an attribute none of whose bound columns a document describes cannot be judged and is counted apart |

The by-table section has one row per catalog table, ordered by table name and by nothing
else (no score, no ranking by problems). The table name links to its table-semantics page
when `--semantics` gave one.

| Column | Value |
| --- | --- |
| 表 | the table |
| 概念 | the concept it represents, linked |
| 唯一键的证据 | 已证明 (lineage proved the grain) or 无; only with `--lineage` evidence |
| 表语义的说法 | the document's `summary.row.unique`: 唯一 / 不唯一 / 未知; only with `--lineage` evidence |
| 度量列 | columns bound to a measure attribute (counted from the catalog) |
| 其中单位无材料依据 | of those, the columns whose attribute the material does not support, as a count and a share |
| 未绑定列 | the table's columns bound to `unmapped`, the same source as the gap summary |
| 注意事项 | the number of the document's `summary.watch` items, and how many are of kind `conflict` |

The unit is judged per attribute, by the same rule and the same function that mark a unit in
`catalog context --semantics` (`material_unit`): a column whose unit the context pack marks
as not given by the material is exactly a column counted under 其中单位无材料依据. When the
documents cover only some tables, a cell that needs a document shows `—` for a table without
one, a note under the section says how many tables are covered, and the not-unique count in
the summary counts only the covered tables and says so.

| File | What it holds |
| --- | --- |
| `index.md` | first what to look at before using the catalog (the governance gap summary, and with `--docs` two more rows and a row per table); then the concepts by domain (name, kind, definition, number of tables, status), the identifiers, the code sets (and the tables their values live in), and a summary of the record scopes |
| `concepts/<slug>.md` | one page per concept (`concept:fee_waiver` → `fee_waiver.md`): a one-page overview, then seven sections as its appendix |
| `identifiers.md` | every identifier in full, with the columns bound to it |
| `code_sets.md` | every code set: its values, or the table and condition to look them up by (`lookup`); the attributes it codes (by the rule under Attribute); the columns whose `code_sets` consult it (row 「查它的列」), how each consults them (in order, or each source its own: `code_sets_by`) and what each stores (`holds`) |
| `governance.md` | every gap of every concept, one list per kind of gap; the code values whose meaning is not confirmed; plus the denormalised columns per table (informational, not a gap; those repeating another record of the same concept are marked so) |
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
| A4 属性 | by category (描述, 状态, 度量, 时间): definition, type and unit, code values (value=meaning; for values in a code table, how to look them up; with several code sets, each after its name, 「A：1=…；B：0=…」), every table column that holds it (with its code map; a column consulting code sets in order reads 「先查 A，查不到查 B」, look in A, then B, and one with `code_sets_by: source` reads 「按来源分别查 A、B」, each source in its own; a column with `holds` adds what it stores, 「存含义（zh）或码」 (stores the meaning, in zh, or the code), after the code sets as 「（码值：查 A；存代理键）」; one another table repeats is marked 「冗余（经 via column）」, one repeated from another record of the same concept 「冗余（同一<concept>的另一条记录，经 via column）」), how it is derived |
| A5 关系 | association, composition and generalization read from this concept's side, with cardinality and JOIN count (a self relation's far end reads 「本概念」 with the columns that carry it — a column naming a `relation` only under that one, a column naming none under every self relation — and one with an `inverse_name` reads both ways); JOINs inside a producing task (`source_joins`), when there are any, as 「生产任务内连接 N 次（如 …，填 <foreign key column>）」, apart from the JOIN count; when the count is 0 or could not be taken, what the catalog itself shows: the tables holding both ends (representing one or binding its identifier; a role through its player's identifiers; a self relation only through a self-referencing column realising it) and the relation's `evidence`; the events it takes part in (its role, how many tables the event has); the roles it plays, or — on a role's page — the player it belongs to |
| A6 约束 | the constraints on the concept, its attributes, identifiers and relations, by kind, with strength and status; the expression is followed by the rules a constraint carries (承接规则) and the catalog tables it comes from (来源表, the judgement `catalog query table` uses) |
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
`business_rule` / `value_domain` that come from a representation's table: their `rules` name it
(`<db.table>#rN`), or their `evidence` or expression cites it. An expression cites a table by its whole name, which may be followed by
`.column`: a rule about `db.t_order_refund` does not cite `db.t_order`.

## Query: `catalog query`

```bash
scope-lineage catalog query out/ontology.json concept 用户
scope-lineage catalog query out/ontology.json table spark_catalog.demo_dwd.dwd_lending_loan_df --json
```

| Kind | Term | Answer |
| --- | --- | --- |
| `concept` | id, name, synonym or term | identity, identifiers, attributes, states, tables, the page to read, and the concept page's one-page overview (`overview`, the same fields as the page) |
| `table` | `db.table` (a catalog prefix is ignored) | the concept it carries, its time semantics and how to read by them (`usage`), the representation's `refresh` (a 刷新 line; none without it), the table comment and `notes`, its record scope, the business rules and value domains coming from it (`constraints`: its `rules` name the table, or its `evidence` or expression cites it), and what every bound column points at, with evidence (a column bound to an attribute carries the attribute's `type`, printed 「；类型 …」); a denormalised column reads `→ 冗余属性 <attribute> of <concept>（经 <via>）`, a self-referencing one names its relation; for a code table (one a code set's `lookup` names), the code sets it holds and how each is looked up (`code_sets`), and when the table is also represented, the representation's answer gains `code_sets`; exit code `0` |
| `column` | `db.table.column` | the attribute or identifier it holds and its concept (an attribute's `type` too, printed 「；类型 …」; a denormalised attribute with its `via`, plus `other_instance: true` when it is another record's of the same concept; a column with `code_sets` lists them in order, each with how it is looked up, and carries `code_sets_by` when it is `source` (the text reads 「按来源分别查 A、B」); one with `holds` says what it stores, 「存含义（zh）或码」, and carries `holds` and `lang`) — or, in a code table, what kind of column it is (code, meaning, surrogate key, filter, validity: `role`) and which code sets it serves — or the identifier it spells; a self-referencing column carries `self_relations` (the self relations it realises: the one its `relation` names, or all of them) |
| `identifier` | id, name or physical spelling | what it identifies, its scope and spellings, the columns bound to it |
| `attribute` | id, name or term | its concept, its `notes` when it has any (printed 「备注：…」), code values (with a `lookup`, `code_set` also carries how and in which table to look them up; an attribute with no `code_set` of its own answers with `code_sets`, the sets its columns name, each shaped like `code_set` plus its `name`), derivation and every table column |
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

## Search: `catalog search`

`catalog query` only knows the catalog's own names. With a business word or a whole question in hand, `search`
turns it into those names first:

```bash
scope-lineage catalog search out/ontology.json 每个渠道上个月的还款金额是多少
scope-lineage catalog search out/ontology.json loan_no --kind identifier --limit 5 --json
```

Every concept, metric, attribute, identifier, code set and table is one entry; the entries are ranked by how
close they are to the text and the best `--limit` (10 by default) are returned. Each carries its kind, id,
name, a one-line `summary`, where it lives (`where`) and the fields that matched (`matched_in`).

| Entry | Text that takes part | `where` |
| --- | --- | --- |
| `concept` | name, synonyms, terms referring to it, id, definition | its representation tables |
| `metric` | name, terms, id, definition and filter | the concept it is computed on |
| `attribute` | name, terms, id, definition, the names of the columns bound to it | its concept and the bound table columns |
| `identifier` | name, terms, id, physical spellings, notes | the concept it identifies |
| `code_set` | name, terms, id, the meaning of each value | none |
| `table` | table name, table comment, the name of the concept it carries; with `--semantics`, also what the table-semantics document says it is and is good for | the concept it carries |

The match is lexical and needs no extra dependency: Chinese is cut into windows of two adjacent characters, so a
business word matches inside a longer name; letters and digits are cut into words, ignoring case. A match in a
name scores above one in a definition, a rare word above a common one, a name the text spells out whole above
one it only touches. Words that only frame a question are left out of the text first: a two-character
window made only of question and function characters (每个, 多少, 是否, 哪些), one holding a particle such as
的 or 吗, and a few question verbs (统计, 写出, 说明); a window with any other character stays (还款, 个人).
Only the text is filtered, never the catalog.

A question that names two things should list both. A concept's attributes, identifiers and tables are its
members, and one concept can bring many members that each match more words than the other thing's concept.
So once a concept's members hold two places, its next member waits until every concept the text names (in
that concept's own name, synonym, term or id) is listed; the waiting members then follow by score. A text
about one thing, or a `--kind` list without `concept`, has nothing waiting and keeps plain score order; a
column name still finds its attribute or identifier first. The JSON shape does not change.

Scores only order the list and are not comparable across searches. `search` offers
candidates; it does not choose for the reader and never changes the catalog: once chosen, take the id to
`query` or `context`.

```text
1. [概念] 借款人 concept:borrower — A customer while they hold at least one loan that is not settled.
   在：demo_dwd.dwd_lending_borrower_df
```

`--kind` is repeatable and keeps only those kinds; `--json` prints `{"query": {"text", "kinds", "limit"}, "hits": [...]}`.
Exit codes: `0` there are candidates, `1` nothing is close, `2` the file or the `--semantics` directory cannot be read.

## Context pack: `catalog context`

Writing one query takes two kinds of knowledge at once: from the catalog, what the table carries, its keys and
time columns, and where it joins; from table semantics, how to read the table, what it is not for, what to
watch, and which questions nobody has answered. `context` gives all of it in one answer, taking from the
table-semantics document only the parts a query depends on:

```bash
scope-lineage catalog context out/ontology.json --semantics docs/ \
  --concept 客户 --table demo_dwd.dwd_party_customer_info_df \
  --column demo_dwd.dwd_party_customer_info_df.gender_cd
```

| Option | What it gives |
| --- | --- |
| `--concept` (id, id without its prefix, name, synonym or term; or a metric's id, id without `metric:`, name or term) | definition, identifiers, representation tables, the constraints on it and on its attributes, identifiers and relations, each metric in full (measure and bound columns, aggregation, filter, time window, dimensions, additivity, unit, the text of the constraints it cites, and its `notes` when it has any); a term no concept matches is tried as a metric, and the metric's concept is packed with that metric first, named in `via_metric` (`{id, name}`) |
| `--table` (`db.table`) | catalog side: the concept carried, grain columns and their source, time shape and refresh (the text's 刷新 line adds the cycle the table-semantics document wrote, 表语义写的周期), time columns with their roles, record scope, for each foreign-identifier column the table and column it joins to (`joins`, with the JOINs the corpus showed and where: only the sample JOINs that involve this column -- a JOIN inside a producing task by the column it fills, one between catalog tables by its two sides --, one entry for the same evidence however many relations carry it, `relations` naming them; `count` is this column's own from the build's `by_column`, and a column whose JOINs kept no sample gets a count-only line; a document built before `by_column` counts this column's samples when they are complete, and when the build cut them short says how many JOINs were not sampled (`unsampled`) and that whether they are this column's is not recorded -- with no sample of this column, one line naming the relation's count (`relation_count`) -- rebuild to know), constraints, the names of the metrics on its concept, disagreements between evidence and catalog; table-semantics side (`semantics`): what it is, what one row is, how to read it, scope lines and the rules they cite (with SQL), good for and not for, things to watch, open questions (an answered one with its answer), the downstream tasks and tables that read it, one line per column |
| `--column` (`db.table.column`) | the catalog binding (what it points at, definition, the attribute's `type` for a column bound to an attribute -- an identifier, technical or unmapped column has none, so nothing is printed --, unit, code values, derivation, time role, lineage expression, and the bound attribute's `notes` when it has any, printed 「备注：…」); the table-semantics entry for the column: meaning, derivation, branches, code values, what NULL means, what to watch; and the table-level notes and open questions that name this column (an answered one with its answer) |
| `--columns` (`col[,col...]`) | the same as `--column` for columns of the `--table` values, named without the table and separated by commas; needs a `--table`. With one `--table` every name is that table's. With several, a bare name goes to every requested table that has the column (the catalog binds it on the table, or the table's semantics document describes it; case is ignored), `table.col` pins the requested table of that name and `db.table.col` is taken as written; a name already asked is not asked again |
| `--brief` | a short `--table` pack: every catalog fact, what it is, what one row is, how to read it, scope, good for, not for, things to watch, open questions and the text of the cited rules stay; columns are listed by name grouped by category (entries keep `column` and `category`), cited rules lose their SQL, downstream readers are named by the table they write (by their task when they write none); a join column's sample JOINs whose two tables are both outside the catalog are folded into one count (`seen_outside_catalog`, 「另有 n 条产出任务内部的连接证据两边的表都不在目录里」), while a JOIN involving a catalog table is always listed; a column whose table is in the same pack points to the table's notes instead of repeating them |
| `--focus` | with `--column`/`--columns`: each table's watch items, open questions and cited rules narrowed to its requested columns; `semantics.focus` (`columns`, `left_out` counts) says what was left out |

`--table`, `--column`, `--columns` and `--concept` are repeatable and can be mixed. A column of a table named by
`--table` comes in full in the same pack, so one call answers the table and the columns a query touches:

```bash
scope-lineage catalog context out/ontology.json --semantics docs/ \
  --table demo_dwd.dwd_party_customer_info_df --columns gender_cd,register_time --brief --focus
```

`--focus` decides by reference, not by reading prose: a watch item names a column through a `column:<name>`
entry in `refs`, an open question through one in `about` (case is ignored). An item that names no column is about
the whole table and is always kept; a table none of whose columns was requested is left whole. A rule carries no
column reference of its own, so it stays while a scope line or a kept item cites it and leaves only with the items
that cited it. The text says `聚焦 …：略去只点名其他字段的注意 n 条、待确认问题 n 条、规则 n 条；去掉 --focus 可看全部`,
so nothing disappears silently. `--brief` and `--focus` leave concepts and `--column` answers as they are.
Without them the pack is unchanged. Provenance in the table-semantics document (`sources`,
`confidence`), upstream tables and the processing steps stay out of the pack: they say how the
table was built, not how to query it; downstream readers are kept, because "what does a change here reach"
is asked of a table. A table with no table-semantics document has `semantics` equal to
`{"present": false}` and the text says so -- a reader must be able to tell "nothing to watch" from "nobody
wrote it down". A column only the table-semantics document knows is still answered by `--column`, with an
empty `catalog`.

**An answered question carries its answer.** A table-semantics question whose `status` is `answered` (one
written back with `semantic confirm`, say) also carries `answer`, `answered_by` and `answered_on` -- those the
document has -- under the table and under a named column, and the text gives the answer on the line after the
question as `  - 回答：…（who，date）`. A question not answered is as before. The answer stays under the open
questions rather than in a section of its own; `--focus` keeps or leaves it out by `about` as before, and the
left-out counts are counted as before.

**A measure's unit against the material.** With `--semantics`, the unit of a `measure` attribute -- on a
column's binding, and on a metric over that measure (`--concept` with a concept or a metric) -- is compared with
the table semantics. The judgement is the attribute's: when any column bound to it has a `unit` in its table's
document, the unit is supported and printed as before. Otherwise the binding or the metric gains
`material_unit`: `{"given": false}` with a unit, printed `单位：<unit>（材料未给，目录所填未经确认）` (the catalog
filled it in, nobody confirmed it); `{"given": false}` with no unit, printed `单位：材料未给`; and
`{"given": true, "units": [...]}` when the catalog has no unit while the material gives one, printed
`单位：<unit>（目录未填）`. An attribute none of whose bound columns a document describes is not judged.
`doc_format` stays `catalog-context/1`. Where such a mark says the material gives no unit, the sentence 「待 owner 确认：单位」 in the
attribute's or metric's `notes` says the same and is left out of the printed notes; every other sentence stays. Without `--semantics` nothing is compared, so an unconfirmed unit
reads like a confirmed one: ask for a metric with `--semantics` too.

```text
# 表 demo_dwd.dwd_party_customer_info_df

## 目录
- 承载概念：客户（concept:customer），表的种类 core
- 粒度：customer_id（proven）
```

**Where a table's constraints come from.** The constraints listed under a table are those on its concept, and
each comes from the tables its `rules` name or that its `evidence` or expression cites (`tables`; the same
judgement `catalog query table`, `scopes.md` and the concept page use, catalog tables only). Under the table each
gets a `relation`, the first that holds: `this_table` (this table is a source); `upstream` (a source is upstream
of this table in the lineage evidence, followed hop after hop through catalog tables: when this table's rows come
from that table the condition is already carried in, when this table only joins it for extra fields it does not
apply -- the evidence does not say which, so the text says both and names the source); `downstream` (done when a
downstream table is built, not here); `unrelated` (no lineage relation, so whether it holds here is not known).
A constraint with a source on each side is listed upstream, and `also_downstream` names its sources that read this table. A `unique` constraint from
upstream gets its own sentence: the table's grain may differ, so uniqueness may not hold. Without lineage
evidence in the catalog the only relations are `this_table` and `other_table`. The text prints one segment a
relation, each line naming its sources. A constraint from another table on an attribute this table binds no column to is not listed
but counted (one from this table's own rules is always listed, so that segment is what `catalog query table` lists) (`constraints_unbound`, `{relation: n}`), and a constraint naming no table is listed as before with
neither key. With `--concept`, each constraint names its `tables` too.

**Two or more tables: how they join.** With two or more `--table` values the pack adds one entry per pair of
requested tables (`links`, and a `# 关联 a ↔ b` section after the table blocks), so the agent does not work out the
join, the side that multiplies rows and the filters by itself:

```bash
scope-lineage catalog context out/ontology.json \
  --table demo_dwd.dwd_lending_loan_df --table demo_dwd.dwd_lending_loan_status_his
```

- **Backed pairs** (`pairs`): the column pairs the catalog backs between the two tables -- both columns hold the same
  identifier (`basis: identifier`) or the corpus recorded a JOIN on exactly that pair (`basis: seen_join`, with the
  relation). It is the judgement `check-sql` makes for `join_not_recorded`, read from one shared module
  (`render/catalog_joins.py`), so the advice and the check cannot disagree.
- **Rows per key** (`sides`): for each table, whether the skeleton's join columns cover its recorded grain --
  `one` (one row per key), `one_once_filtered` (the grain columns left open are a snapshot's partition or a
  zipper's window columns, which the filters below pin), `several` (names the grain columns left open: a SUM / COUNT over the other
  table's columns is inflated), or `unknown` when the catalog records no grain; it is not guessed.
- **Filters** (`filters`): the partition columns of a `snapshot` table (each partition a full copy, so one is read)
  and each zipper's validity columns, grouped as `check-sql` groups them for `missing_partition_filter`.
- **Partitions that are not filters** (`partitions`): `{table, columns, reading, period_columns}` for each table
  whose partition is not a full copy. `reading` is `write_batch` for an `incremental` table -- the partition is the
  batch that first wrote a row, not the day the event happened, so a period is read across partitions -- or
  `unstated` when the representation's `time` is `zipper`, `unknown` or missing. `period_columns` are the columns
  bound `time_role: event_time` (else `business_date`). The text says it in one line, and the skeleton writes no
  partition predicate for these tables.
- **Skeleton** (`skeleton`): `SELECT * FROM a JOIN b ON … WHERE …` with string placeholders (`'<dt>'`,
  `'<as_of_date>'`, `'<period_start>'` / `'<period_end>'`), so it parses, and one comment line per caution. A
  `write_batch` table gets a comment that its partition is the write batch and, when it has exactly one period
  column, `col >= '<period_start>' AND col < '<period_end>'` on it (with several, the comment names them and no
  predicate is written; with none, the comment points at the table's 「取数」). It uses plain `JOIN` and says the join type is
  the writer's choice. Backed pairs are often different paths (a key and a self reference to it, two different
  parties), so they are not all AND-ed: `ON` takes the pair meeting the most grain columns of the two sides, then
  any pair on unused columns that closes a grain column still open (`in_skeleton`); every other backed pair is a
  comment line, an alternative to choose by the question.
- **No backed pair**: the entry says so, gives no skeleton, and lists in `bridges` the catalog tables that have
  backed pairs with both (one hop, names only; no longer paths are searched).

```text
# 关联 demo_dwd.dwd_lending_loan_df ↔ demo_dwd.dwd_lending_loan_status_his

- 目录支持的关联列对（与 check-sql 的判断相同）：
  - demo_dwd.dwd_lending_loan_df.loan_no = demo_dwd.dwd_lending_loan_status_his.loan_no：同一标识 借据号（id:loan_no）（骨架的 ON 用这一对）
  - demo_dwd.dwd_lending_loan_df.orig_loan_no = demo_dwd.dwd_lending_loan_status_his.loan_no：同一标识 借据号（id:loan_no）
- demo_dwd.dwd_lending_loan_df 一侧：粒度 loan_no；骨架的关联列覆盖了粒度，每个关联键一行
- demo_dwd.dwd_lending_loan_status_his 一侧：粒度 loan_no、start_date；骨架的关联列没覆盖 start_date，按下面的过滤钉住（分区取一个值、拉链取一个时点）后每个关联键一行
- 要过滤：demo_dwd.dwd_lending_loan_status_his 按拉链有效期列 start_date、end_date
```

```sql
-- 关联方式（JOIN、LEFT JOIN 等）由写 SQL 的人决定：目录不说明该用哪一种
-- b（demo_dwd.dwd_lending_loan_status_his）要按粒度里的 start_date（拉链有效期列）钉住（分区取一个值、拉链取一个时点）才每个关联键一行，否则对上多行
-- 另一对有目录依据的关联列：a.orig_loan_no = b.loan_no（同一标识 id:loan_no）；可能是另一条关联路径，意思不同，按问题替换或补进 ON，不要不加判断地 AND 上
-- 拉链有效期的开闭（> 还是 >=、未失效的结束日期怎么写）以表的约定为准
SELECT *
FROM demo_dwd.dwd_lending_loan_df a
JOIN demo_dwd.dwd_lending_loan_status_his b
  ON  a.loan_no = b.loan_no  -- 同一标识 id:loan_no
WHERE b.start_date <= '<as_of_date>'
  AND b.end_date > '<as_of_date>'
```

A single `--table` gets no `links`. A table with a partition column carries `partition` (`{columns, reading,
period_columns}`, `reading` also `full_copy` for a snapshot), and its 「目录」 block says beside the time columns how
to read it: 「每个分区一份全量，只取一个分区」, 「写入批次，不是事件日期，按事件时间列 … 过滤时段」, or that the catalog does
not record which (read the 「取数」 line).

`--json` prints `catalog-context/1`: `{"doc_format", "query", "concepts", "tables", "columns", "missing"}`, plus `links` with two or more tables;
names that were not found are listed in `missing`; `query` also carries `"brief": true` and `"focus": true`
when those options were given, and `query.columns` lists `--columns` as `db.table.column` after `--column`.
A `--columns` name no requested table has is listed once in `missing` with the tables tried
(`{"kind": "column", "term", "tables"}`); a metric whose `on` is no concept of the catalog, as
`{"kind": "concept", "term", "metric": {id, name}}`. Exit codes: `0` at
least one was found, `1` none was, `2` no option was given, `--columns` without a `--table`,
`--focus` without a column, or the file or the `--semantics` directory cannot be read.

## SQL check: `catalog check-sql`

`search` and `context` tell an agent what to query; nothing checked the query it then wrote. `check-sql`
parses the SELECT statements, and the query inside `INSERT ... SELECT` and `CREATE TABLE ... AS SELECT`
(the table written is not a read), with the lineage parser (same dialect, same text repairs, same qualification;
CTEs, subqueries, UNION branches and table aliases resolved to physical tables) and compares them with the
built ontology:

```bash
scope-lineage catalog check-sql out/ontology.json query.sql
echo "SELECT l.loan_no FROM demo_dwd.dwd_lending_loan_df l" | scope-lineage catalog check-sql out/ontology.json - --json
```

Every rule fires only on what the catalog and the query together settle; where they cannot tell, it says
nothing or says `info`:

| Rule | Severity | Fires when | Stays silent when |
| --- | --- | --- | --- |
| `table_not_in_catalog` | info | a physical table has no representation | the table is represented (a CTE name is never taken for a table) |
| `unknown_column` | error | a column is not bound on a table whose column list is complete: the table card count `evidence.representations[t].declared_columns` (`build --tables`) is present and equals the bound columns | the column is bound; the table's list is not known to be complete (then `column_unchecked`) |
| `column_unchecked` | info | a column is not bound on a table the catalog binds only partly, or that has no table card | -- |
| `join_not_recorded` | warning | judged once per JOIN between two reads (JOIN ON, or WHERE across two aliases): none of its equality pairs binds the same identifier (`identifier` / `foreign_identifier`) or appears in a JOIN the corpus evidence recorded; one finding lists every pair asked and the pairs the catalog records between the two tables | at least one pair is recorded (the others, such as a date or an environment, only narrow the join); a pair has a side that reaches no single physical column, or that the catalog does not bind |
| `missing_partition_filter` | warning | a read of a `snapshot` table with a `time_role: partition` column (each partition a full copy), or a zipper's `valid_from` / `valid_to` columns, has no WHERE or JOIN ON predicate on any column of that group anywhere in the statement that reaches this read | any column of the group is used in a predicate that reaches the read (through a CTE too); the table has no such time role; the partition of an `incremental` table (the write batch: a period is read across partitions), of a zipper, or of a table whose `time` is `unknown` |
| `fan_out_unaggregated` | warning | a SUM or COUNT (not DISTINCT, not windowed) over columns of one directly read table A, while a table B read directly in the same SELECT and joined to A has a recorded grain that the join columns plus B's predicate-pinned columns do not cover; only B decides, A's own grain does not matter | B's grain is covered by the join columns and pinned columns (a zipper's window pins its start) or by the GROUP BY; B is reduced in a subquery first; a SEMI / ANTI join; `COUNT(*)`; B has no recorded grain |
| `code_value_unknown` | warning | a column whose binding or attribute lists code values is compared with `=` or `IN` to a literal not among them; lists the values | the value is listed (`1` matches `'1'`); the code set's values live in a lookup table; the column stores meanings or keys (`holds`) |
| `pending_definition` | info | the query holds a `待确认` placeholder (below); written right after `<column> <op>` or `<column> IN (`, it carries the physical table and column that column reaches | the comment does not start with `待确认` and a colon; the marker is inside a string |

Where the full column list lives: the built document records a table's columns only as its bindings, and a
catalog may bind some of a table's columns and not others. The only statement of how many columns a table
has is the table card count that `build --tables` attaches, so without it `unknown_column` never claims a
column is absent. `missing_partition_filter` reads `time_role` and the representation's `time` only: a `dt` column
bound as `technical` without a time role is not taken for a partition, however it is named. A partition whose form
the catalog leaves `unknown` gets no finding at all, not even an `info`: an agent acts on every line it reads, and a
line that cannot say whether a partition predicate is needed pushes it to add one; `context` says in that case to
follow the table's 「取数」.

```text
# 第 1 条语句
- 错误 [unknown_column] 表 demo_dwd.dwd_lending_loan_df 没有列 loan_amount：目录按表卡记录了它的全部 8 列。
- 警告 [code_value_unknown] demo_dwd.dwd_lending_loan_df.loan_status 与 '5' 比较，但目录列出的取值里没有它。可用的值：1=normal、2=overdue、3=settled、9=待确认，疑似核销。
```

`--json` prints `catalog-sql-check/1`: `{"doc_format", "statements", "tables", "placeholders", "findings"}`; each finding has
`rule`, `severity`, `statement` (its position in the script, from 1), the `table` / `column` / `alias` it is
about, a Chinese `message`, and in `catalog` what the catalog records instead (its columns, the recorded join
pairs, the time columns, the many side's grain, the valid values). Statements holding no query at all are
skipped. Exit codes: `0` no error or warning (info allowed), `1` at least one error or warning, `2` the
ontology or the SQL file cannot be read, the SQL does not parse strictly (the message gives the line, the
column and the text around where parsing broke), or it holds no query.

### Placeholders for a missing definition

For a business word the catalog does not define (what counts as "reached", which code values mean "not
contacted", how a category is decided) the agent does not guess: it leaves a placeholder in the query saying
which definition is missing, and the query still parses. A placeholder is a comment starting with `待确认`
and a colon (`:` or `：`), written beside a neutral predicate or value:

```sql
SELECT COUNT(*) AS cnt
FROM demo_dwd.dwd_party_customer_info_df c
WHERE c.dt = '2024-01-31'
  AND c.gender_cd IN (/* 待确认：性别码除 F、M、U 外还有哪些值 */ 'F', 'M')
  AND /* 待确认：注销的客户算不算 */ 1 = 1
```

`check-sql` lists each one under `placeholders` in its result (`statement`, `text`, `written`, `table`,
`column`) and gives one `pending_definition` finding (info) each; the exit code does not change. When the
placeholder sits right after `<column> <op>` (`=`, `<>`, `!=`, `<`, `>`, `<=`, `>=`) or `<column> IN (`,
`written` is the column as written and `table` / `column` the one physical column it reaches through
aliases, CTEs and subqueries; a placeholder before the predicate, after the value, beside `1 = 1` or after an
expression is tied to no column, and neither is a name reaching two tables (or a bare name in a scope with
two sources). The comments are read from the token stream, not the tree: sqlglot attaches a comment to a
nearby node (`/* … */ 1 = 1` lands on the whole `AND`, `, /* … */ 'v' AS c` on the projection before it),
so the tree cannot say what it sits next to; the gaps between tokens hold only whitespace and comments, so
the same words inside a string are never read as a placeholder. A `--` line comment counts too.

## Missing definitions: `catalog pending`

A placeholder lives only as long as the conversation, and the same gap is hit again next time. `catalog
pending` keeps them in an append-only JSON Lines file for the catalog's owner:

```bash
scope-lineage catalog pending add pending.jsonl --from-sql query.sql --question "一月底有多少女性和男性客户"
scope-lineage catalog pending add pending.jsonl --missing "注销的客户算不算" --question "上月新增客户数" \
  --table demo_dwd.dwd_party_customer_info_df
scope-lineage catalog pending list pending.jsonl --ontology out/ontology.json --semantics semantics/ [--json]
```

`add` appends one `catalog-pending/1` line per missing definition: `--missing` (with `--term` for the
business word itself, `--table`, `--column`, `--proposed` for a proposed definition) writes one line;
`--from-sql` writes one per placeholder of the SQL file (a placeholder tied to a column records that column
and its table, one tied to nothing every table its statement reads). Both need `--question` (the question
as asked); the date is `--date`, or today when it is not given (taken in that one place, the command line).
Existing lines are never rewritten. Exit codes: `0` appended; `1` the SQL has no placeholder, or a
placeholder says nothing (nothing written); `2` bad options, an input cannot be read, or the SQL does not
parse.

```json
{"doc_format": "catalog-pending/1", "date": "2026-11-20", "missing": "性别码除 F、M、U 外还有哪些值", "question": "一月底有多少女性和男性客户", "tables": ["demo_dwd.dwd_party_customer_info_df"], "columns": ["demo_dwd.dwd_party_customer_info_df.gender_cd"], "source": {"sql": "query.sql", "statement": 1, "written": "c.gender_cd"}}
```

`list` folds the lines naming the same missing thing into one item (text equal after NFKC, case folding and
collapsing whitespace -- no fuzzy merging), most hit first, with the questions behind it, the tables and
columns, proposed definitions, dates and line numbers. With `--semantics` it marks the questions a
table-semantics document records `about` the same column (with their `status`); with `--ontology`, the
catalog objects whose own name, synonym, term or id now is the item's text or term -- so the owner sees
which entries are answered. It records and reports; it never edits the catalog or decides a definition.
`--json` prints `catalog-pending-list/1`. Exit codes: `0` every line read; `1` some line is not a
`catalog-pending/1` entry (the rest are still listed); `2` an input cannot be read.

```text
# 待确认的定义：4 条记录，3 项

## 1. 注销的客户算不算（2 次）
- 问到它的问题：一月底有多少女性和男性客户；上月新增客户数
- 涉及：demo_dwd.dwd_party_customer_info_df
- 记录日期：2026-11-20 至 2026-11-21（第 2、3 行）
- 表语义：这一项没有指明列，无法对照已记录的问题
- 目录还没有同名对象

## 2. 性别码除 F、M、U 外还有哪些值（1 次）
- 问到它的问题：一月底有多少女性和男性客户
- 涉及：demo_dwd.dwd_party_customer_info_df.gender_cd
- 记录日期：2026-11-20（第 1 行）
- 表语义已记录的问题：demo_dwd.dwd_party_customer_info_df q1（open）性别码值除了 F、M、U 以外，还会不会出现其他值？
- 目录还没有同名对象

## 3. 豁免（1 次）
- 问到它的问题：上月豁免了多少罚息
- 提议的定义：罚息减免记录
- 记录日期：2026-11-21（第 4 行）
- 表语义：这一项没有指明列，无法对照已记录的问题
- 目录现在有同名对象（核对是否已回答）：[概念] 豁免 concept:fee_waiver
```

## Serving the answers: HTTP and MCP

`search`, `context`, `query`, `check-sql` and `pending list/add` can also be answered by a long-running
server instead of the command line. The servers live in this repository's [`service/`](../../service/README.md)
directory, packaged separately (`scope-lineage-service`); the core package gains no dependency from them. The
HTTP server uses the standard library only and binds `127.0.0.1` by default; the MCP server speaks stdio,
built on the official Python SDK. Both call the very functions the command line calls
(`scope_lineage.cli_catalog_answers`), so the same input gets the JSON `--json` prints, and the exit codes keep
their meaning (found / nothing found / input unusable). Neither runs SQL; the only file either writes is the
pending file it was started with. A file that changes on disk is read again on the next request, with no
restart.

```bash
pip install -e . -e service
scope-lineage-service http out/ontology.json --semantics semantics/ --pending pending.jsonl
scope-lineage-service mcp out/ontology.json --semantics semantics/
```

The HTTP server also serves a read-only browse page at `/` (open `http://127.0.0.1:8765/` in a browser):
domains, concepts, metrics and tables; a concept's neighbourhood drawn as a graph with the join conditions of
each relation; a table's catalog facts beside its table-semantics document; and a board of the open questions
(the table-semantics documents' and the pending file's). Lists arrive a page at a time, so a large catalog
is never sent whole. The page is built on browse answers in
`scope_lineage.cli_catalog_answers` (`browse_index`, `browse_list`, `neighbourhood`, `table_semantics`,
`table_units`, `questions`) that no command prints: the command line keeps `query`, `context` and `render` for
the same facts. The home view shows the 「用之前先看」 summary of `index.md` and, with `--semantics`, the table
list carries the 「按表看」 columns: both come from the functions that write `index.md`, so the numbers are
the same as `catalog render --docs` gives for the same documents; the list stays in name order unless the
reader sorts it by one of those columns.

An answered table-semantics question on the board carries `answer`, `answered_by` and `answered_on` too. A
browse page that holds answers and notes not yet written back to the documents may hand them to `context` and
`questions` as `page_states` (no command flag): a mapping keyed by `(table, question id)` whose value is
`{"written": false}` (an answer the page overlaid, not written back) or a page note `{"kind", "reason", "by",
"date"}` (with an optional `choice`, `yes` / `no`, and `to` for a redirect). A question noted `partial`,
`deferred` or `redirect` stays `open` and gains `page`; one noted `invalid` or `not_applicable` gets the
status `set_aside`, with `page` too. In the pack's text an answer from the page reads
`回答（页面填写，尚未写回）：…`, the first three notes follow their question in parentheses, and a set-aside
question is listed after the open ones, one line each, as `已搁置：…（reason）`. The board takes the status
filter `set_aside` only when given `page_states` (even an empty one); `all` includes those items, and the
counts and concept facets follow the status filter as they do for the others. The documents gain no key;
without `page_states`, or with an empty one, every output is what it was before they existed (apart from the
answers of answered questions). A note on a question the document already answers has no effect: the
document's answer stands.

Started with `--ask`, the page also gets an ask panel: a model on the server answers a data question by the
skill's `catalog-answers.md` walk, with the answers above as its only tools, and the page shows the steps, the
SQL, the basis of each condition and each 待确认 placeholder (a definition typed beside one is appended to the
pending file). It never runs SQL; it costs money and sends catalog text to the model provider, so it is off
by default. `--ask-models FILE` lists several models -- Anthropic, or any endpoint speaking the OpenAI Chat
Completions API, such as a privately hosted model -- and the asker picks one per question; keys come from
environment variables the file names. See [service/README.md](../../service/README.md).

## Drafting: `catalog digest` and `catalog merge`

Once a batch of tables has [table semantics](table-semantics.md) (`table-semantics/1`), a
catalog can be drafted from them without an ad-hoc script each time:

1. `catalog digest` condenses the table semantics into drafting material and, against an
   existing catalog, names the tables and columns it does not cover yet;
2. a person or a model drafts the concepts and relations from it (`concepts/`,
   the `relations` and `identifiers` files); a fragment cannot add a concept or change an
   existing identifier, so every new concept the groups need (an event with its time
   attribute), every new identifier and every new spelling of an existing one is written
   here, and so is every attribute of one group's concept that another group's tables will
   reference (a name column beside a foreign identifier column, say). A fragment adds
   attributes only to its own group's concepts: an attribute of another group's concept that
   the catalog lacks goes in the fragment's `notes`, the column is bound to an attribute of its
   own concept for now, and after the merge it becomes a `foreign_attribute`;
3. the tables are split into groups and each group gets one fragment (`catalog-fragment/1`):
   attributes, code sets, constraints, terms, and each table's representation with its
   column bindings;
4. `catalog merge` merges the fragments into a copy of the catalog, reports conflicts,
   validates the result and prints a coverage report;
5. `catalog build` / `catalog render`, then the owner reviews.

The agent skill's full workflow and the fragment prompt are in
`skills/scope-lineage-ontology/references/catalog-fragment-prompt.md`.

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
| `code_sets` | code sets, shaped like the `code_sets` file's items (with `lookup` when the values live in a code table; a dictionary defined inline in a task's `VALUES` / `CASE` is written as `values`, with the task named in `evidence`, never as `lookup`) | `code_sets.*` |
| `identifiers` | identifiers, shaped like the `identifiers` file's items; only ones that are really missing | `identifiers.*` |
| `constraints` | constraints, shaped like the `constraints` file's items; only ones with evidence | `constraints.*` |
| `metrics` | metrics, shaped like the `metrics` file's items | `metrics.*` |
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
  [--lineage out/lineage [--schema examples/metadata]] [--tables out/tables/tables.json] \
  [--only demo_dwd.dwd_party_customer_info_df ...] [--packets out/packets] \
  [--confirmations out/confirmations] --out out/digest
```

Reads every legal `table-semantics/1` document in the directory (the toolchain's own
documents, such as a confirmations file, are passed over; a document that fails its schema
is skipped with a line on stderr) and writes `digest.md` and `digest.json`
(`catalog-digest/1`) in table order. One section per table:

- the one-line summary, and the concept and representation kind the document names;
- what a row is, the grain columns (with their source and whether they are unique), the
  time semantics (`snapshot` / `incremental` / `zipper`) and how to read it, the scope;
- identifier, foreign-identifier, state, time, measure and descriptive columns (each with
  its meaning, and its codes when it has them; in `digest.json` also its `derivation`,
  `null_meaning` and `watch` when the document has them, and with `--tables` — a
  `tables.json` from `scope-lineage tables` — its physical `type`); technical columns by
  name only;
- the table's `rules` (`[{id, kind, text}]`, `- Rule r1 (filter): ...` in `digest.md`); a
  constraint that carries one names it `<db.table>#<id>` in its `rules`;
- the tables it is built from (with their role) and the tables that read it; what to watch
  and the open questions;
- the answered questions with their answers (`answered_questions`: `[{id, text, answer}]`,
  plus `answered_by` and `answered_on` when recorded; `- Answered q1: <question> -> <answer>
  (<by>, <on>)` in `digest.md`). A table with no answered question has no such key and no
  such line. Only answers written into the documents (`semantic confirm`) count: an answer a
  browsing page still holds in its record file is not read.

With `--catalog` a "catalog coverage" section comes first: tables with no representation,
and columns of represented tables with no binding (table names match ignoring case and a
catalog prefix); a table a code set's `lookup` names counts as a code-set source
(`code_set_sources`: table → code set ids), not as a table with no representation; each
table's section also ends with its standing in the catalog. The
output is deterministic: the same inputs give byte-identical files.

A document that is `packet_stale` (written against another packet), `invalid` (fails a
check of `semantic validate`) or has no packet is still digested, but its table is named on
stderr, one line per flag, as `semantic render` does: the documents are judged against
`--packets` (default: `packets/` beside the documents directory, when it exists); without
packets a line says that nothing was checked. `invalid` holds the documents to the owner's
confirmations as checks 3 and 4 of `semantic validate` do: `--confirmations` is a
`semantic-confirmations/1` file or a directory of them (default: `confirmations/` beside the
documents directory, when it exists; a line on stderr says when they are read). The output
and the exit code do not change.

With `--lineage` (one `lineage.json`, or a directory searched for them, as `catalog build
--lineage` reads it) each listed column also says, from the statements that write its
table, which joined inputs its value is read through and under which constant conditions
-- the facts a code set's `lookup.filter`, the order of a binding's `code_sets` and a
binding's `holds` are written from, so the drafter need not go back to the SQL for them:

- `lookups`: the joined inputs the value is read through, in the order the expression
  reads them (the argument order of a `COALESCE(d1.x, d2.x, a.c)` fallback). Each is
  `{table, where, reads, key, rule}`: the rows of `table` where every `where` column equals its
  string literal, the column `reads` of those rows, the joined input's physical join columns
  `key` (one per key pair, in pair order; absent when the JOIN compares an expression, so no
  column can be named -- never guessed), and the JOIN's logic block id in the lineage;
- `fallback`: the non-looked-up physical columns the same value falls back to (the raw
  code at the end of a `COALESCE`), only beside `lookups`, and only those reaching the value
  through the same source as some lookup;
- `lookups_by: "source"`: the column is written by several sources -- UNION branches, or
  several statements writing the table -- and they read separately: each lookup gains
  `source` (the UNION branch scope id when one statement writes them all, otherwise
  `<task>/<statement>`, with `/<branch>` when it splits too), and only lookups of one source
  are in fallback order. A UNION splits only when no expression above it combines several
  inputs: a `COALESCE` whose main input is a UNION CTE is still one fallback. A UNION inside a
  joined input is that one input, not a source. The key's name matches the catalog's
  `code_sets_by: source`;
- `other_sources`: with `lookups_by`, `{source: [db.table.column]}` for the physical columns a
  source with no lookup stores directly -- not a fallback. A source that only copies the
  target's own column forward carries what another source wrote and is not listed;
- `key_of`: for a column with no `lookups` of its own, the reads it is the join key of,
  `{table, where, key, rule, read_by}`, `read_by` naming the columns of the same table that read
  through that JOIN. They are ordered the way those columns fall back through them, not in
  JOIN order; when two columns fall back in opposite orders the JOIN order is kept and
  `key_of_order: "unknown"` says so. A read with an empty `read_by` (`read by no column`) is a
  dead join or a row filter, not evidence for a code set, and drafting builds none for it --
  code sets are built only for the `where` combinations some column reads.
- `joined_in`: on a measure column only, the JOINs whose right side the value is brought in
  through, one entry a JOIN: `{rule, keys, fan_out}` -- `rule` the JOIN's logic block id in
  the lineage (the numbering `lookups[].rule` uses), `keys` its left join keys as the columns
  of **this** table they reach by pass-through steps, `fan_out` the fan-out status the
  statement alone gives it (`safe` / `risk` / `unknown`; no table cards, so it may be more
  cautious than the packet's). Only JOINs above the first aggregate on the path count (one
  below is folded by it); an entry is written only when every key reaches a column of this
  table; several statements writing the column add their own entries with `source`
  (`<task>/<statement>`). Nothing is compared or filtered by `fan_out`: keys that do not cover
  the table's row grain mean rows sharing the key carry the same value, and `catalog_check.py`
  makes that comparison. The md says `joined in through <rule> on <keys> (fan-out: <status>)`.
  When drafting, a value that does repeat gets, in the `notes` of its measure attribute and of
  each metric over it, 「在 <库.表> 里同 <键> 的多行带同一个值，按 <键> 每组取一行后再加」; its
  `additivity` is not changed for this -- the value is still additive at its own grain, what is
  wrong is summing it over this table's rows. One the SQL shows does not repeat gets
  `<attribute id> repeats skip: <reason>` in `catalog_changes.md`. `catalog_check.py --digest`
  reports, as `measure_repeats_within_grain`, an `additive` measure attribute with neither.

What counts: only a value that enters through a JOIN (or passes through a joined
subquery / CTE) has conditions; a condition is a single equality with a string literal, in
the JOIN's `ON`, in the `WHERE` of a joined subquery / CTE, or in the same query's `WHERE`
on the joined alias itself. Numbers (`rn = 1`), `${…}` parameters, `IN` lists and
comparisons on partition columns are not conditions: partitions are judged as the packet
judges them, by `--schema`'s partition columns when given, otherwise by the lineage's
partitioned flag and the `dt`/`ds`/`pt`/`p_date` name rule. A JOIN with no such condition
only supplements a field and is not listed; a value read from an inline `VALUES` list or
another non-table source is not listed either. The wording is neutral -- "reads rows of
<table> where <column> = '<literal>'" -- because the same shape picks a role, a language or
a row version as often as a dictionary type. With `--catalog` as well, a read whose table and
`where` equal a code set's `lookup.table` and `lookup.filter` gains `code_set: <id>`, and a
`reads` that is that code set's meaning or key column gains `reads_as: "meaning"` / `"key"`.
When the read names its `key` and the key does not include the code set's `lookup.code_column`
-- a stored meaning looked up back to its code -- it is not that code set's translation: it gains
`code_set_mismatch: {code_set, code_column}` instead of `code_set` (the md says
`code set <id> looks up by <column> (reverse lookup?)`). A read with no `key` is tagged by table
and filter as before.

A `key_of` entry on a column that is one of the table's grain columns or an `identifier`
column gains `keyed_by: "row_identifier"`, and so does the same read (rule and table) in each
column reading it: the join picks rows describing the same record -- an attribute row of
this entity, a participant of this call -- not a code's translation. The column it reads is
an attribute, not evidence for a code set. A read keyed by a foreign identifier carries no
mark and may still be another entity's attribute row.

`catalog-digest/1` does not move with `key`, `lookups_by`, `source`, `other_sources`,
`code_set_mismatch`, `keyed_by` and `joined_in`; two meanings narrow: `fallback` is a true fallback of the
same source only, and `code_set` needs a matching join column when the key is known.

```json
{
  "column": "c_desc",
  "meaning": "type description",
  "lookups": [
    {"table": "demo_dim.dim_code_dict", "where": {"code_type": "TypeA"}, "reads": "code_desc", "key": ["code_val"], "rule": "logic:ROOT:join:002", "code_set": "code:type_a", "reads_as": "meaning"},
    {"table": "demo_dim.dim_code_dict", "where": {"code_type": "TypeB"}, "reads": "code_desc", "key": ["code_val"], "rule": "logic:ROOT:join:001"}
  ],
  "fallback": ["demo_ods.ods_order_df.c"]
}
```

A column one UNION branch reads off a dictionary key while the other stores its code:

```json
{
  "column": "st_id",
  "meaning": "status key",
  "lookups_by": "source",
  "lookups": [
    {"table": "demo_dim.dim_code_dict", "where": {"code_type": "TypeOut"}, "reads": "dict_key", "key": ["code_val"], "rule": "logic:union:main:b01:join:001", "source": "union:main:b01"}
  ],
  "other_sources": {"union:main:b02": ["demo_ods.ods_order_b_df.st"]}
}
```

`digest.md` gives each such column one line under "Joined inputs read (from the lineage)".
A table no statement in the lineage writes is digested as usual with nothing added, and the
command prints how many there were. Without `--lineage` the output is byte-identical to
what it was; the lineage, packets, table semantics and catalog build are not changed by it.

Exit codes: `0` written; `1` no legal document, a document was skipped (the rest is still
written), a table named by `--only` has no document, a `--lineage` directory holds no
`lineage.json`, or `--tables` declares another format; `2` the directory, `--catalog`,
`--lineage`, `--tables` or `--schema` cannot be read, or `--schema` is given without `--lineage`.

### `catalog merge`

```bash
scope-lineage catalog merge examples/catalog-demo \
  examples/catalog-fragments/disbursement.json --out out/merged
scope-lineage catalog merge <catalog-dir> <group>.json ... --in-place
scope-lineage catalog merge <catalog-dir> <group>.json ... --in-place --atomic
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
6. `--atomic` (with `--out` or `--in-place`) does steps 2-5 in a hidden staging copy beside
   the target and puts the result in place only when there are no conflicts, no unknown
   concepts and no validation errors: `--in-place` replaces the changed files one by one,
   `--out` receives the whole staged directory. Otherwise nothing is written (`--out` is not
   created, the base is untouched), the same report is printed and stderr says
   `--atomic: nothing written`. Without `--atomic` the result is written in every case.

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
| `1` | a fragment or the base catalog fails its schemas (nothing written); or there are conflicts, unknown concepts, or validation errors after the merge (written, so they can be read in place; with `--atomic`, nothing written) |
| `2` | a fragment or the base catalog cannot be read; `--out` is the base (without `--in-place`), inside it, or not empty |

## Writing YAML safely

- The catalog reads YAML with 1.2 booleans: only `true` / `false` are booleans, so `on:`
  (a constraint key) and codes such as `no` or `off` stay text.
- Quote cardinality ends (`"1"`) and code values that must keep leading zeros (`"01"`).
- A date written bare (`2026-01-31`) is read as the text `"2026-01-31"`.
