"""LinkML and SHACL exports of an ontology candidate (``ontology-json/1``).

``ontology.json`` was designed so that this module is a **rename, not a re-derivation**:
the slot correspondence table in ``docs/*/ontology-doc.md`` is the specification, and
every line below implements one of its rows. Nothing here infers anything; if an export
says something the JSON does not, that is a bug.

Two rules shape the output.

1. **No tier is ever dropped.** Every class, slot, enum and shape that came from an
   assertion carries that assertion's tier, because an exported schema with no tier reads
   as a validated fact and most of these are an author's assumption. An *entity* and an
   *attribute* are the exception that proves the rule: the corpus did not infer them, it
   read their names out of the SQL, so they carry ``proven``.
2. **Neither format is stretched to fit.** Where a target language cannot express an
   assertion -- SHACL core has no composite uniqueness constraint, and an enum over a
   value set the SQL never proved closed would be a lie -- the assertion is published as
   an annotation or a comment that says so, rather than as a shape that validates the
   wrong thing.
3. **Nothing in the JSON is silently absent (WI P6).** A slot a target language has no
   room for still leaves as an annotation, because a downstream tool that consumes only
   the export must not end up with a smaller corpus than the one that was published.
   ``findings`` and ``open_items`` are the sharp case: they are the governance list, and
   an export that drops them reads as a corpus with no open questions. ``evidence`` is
   the one list published in summary rather than whole -- the count and the first task,
   because a schema wants the weight of the evidence and not its rows.

Both layers of the JSON leave: ``entities[]`` are the *table* entities -- how a concept is
represented in the warehouse -- and ``concepts[]`` are the business concepts the fold
proposed. A concept becomes a class under one of three abstract bases (``Entity`` /
``Event`` / ``Summary``), a table class says which concept it represents and in which
role, and both carry the tier of whichever assertion put them there.

No third-party writer is used: both formats are emitted as text by the small
deterministic writers at the bottom of this module, so the export adds no runtime
dependency to a distribution whose dependency list is a product decision.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .concepts import (
    CONCEPT_ENTITY,
    CONCEPT_EVENT,
    CONCEPT_SUMMARY,
    KIND_ORDER,
    TIER_PROVISIONAL,
)
from .ontology import (
    CARDINALITY_MANY_TO_ONE,
    CARDINALITY_MANY_TO_ONE_ASSUMED,
    CARDINALITY_ONE_TO_ONE_ASSUMED,
    COMPLETENESS_COMPLETE,
    CONSTRAINT_IN_SET,
    CONSTRAINT_NOT_NULL,
    CONSTRAINT_UNIQUE_PER,
    DOC_FORMAT,
    EVIDENCE_COLUMN_COMMENT,
    TIER_CONFIRMED,
    TIER_PROVEN,
    mermaid_entity_ids,
)

EXPORT_LINKML = "linkml"
EXPORT_SHACL = "shacl"
EXPORT_FORMATS = (EXPORT_LINKML, EXPORT_SHACL)

EXPORT_FILENAMES = {
    EXPORT_LINKML: "ontology.linkml.yaml",
    EXPORT_SHACL: "ontology.shacl.ttl",
}

# A placeholder namespace, and deliberately one: the corpus has no namespace of its own,
# and minting one that looks authoritative would be the export inventing a fact. Whoever
# loads this into a graph replaces it with their own base IRI.
BASE_IRI = "https://example.org/scope-lineage/ontology#"
SCHEMA_IRI = "https://example.org/scope-lineage/ontology/"
CONSTRAINT_IRI = "https://example.org/scope-lineage/ontology/constraint/"
LINKML_IRI = "https://w3id.org/linkml/"

# The cardinality claims under which the target holds at most one row per source row.
# `many_to_one_assumed` is here for the same reason it exists at all: the author wrote
# the join as if it were true, so the schema says so -- and the tier says who said it.
SINGLE_VALUED_CLAIMS = (
    CARDINALITY_MANY_TO_ONE,
    CARDINALITY_MANY_TO_ONE_ASSUMED,
    CARDINALITY_ONE_TO_ONE_ASSUMED,
)

# The concept layer's three kinds, as the base every concept class inherits from. The
# names are the vocabulary K1 already publishes; the category is the one word an
# ontologist reads them by, and it is exactly why the three are kept apart: 客户 is there
# the whole time, 消息发送 happened, 客户日汇总 is a figure computed over the two.
CONCEPT_BASE_CLASS = {
    CONCEPT_ENTITY: "Entity",
    CONCEPT_EVENT: "Event",
    CONCEPT_SUMMARY: "Summary",
}
CONCEPT_BASE_CATEGORY = {
    CONCEPT_ENTITY: "continuant",
    CONCEPT_EVENT: "occurrent",
    CONCEPT_SUMMARY: "aggregate",
}
CONCEPT_BASE_DESCRIPTION = {
    CONCEPT_ENTITY: "a business thing that persists through time (a continuant)",
    CONCEPT_EVENT: "something that happened to the business (an occurrent)",
    CONCEPT_SUMMARY: "a figure aggregated over entities or events (an aggregate)",
}
#: The class the three bases hang under, so a consumer can ask for "any concept".
CONCEPT_ROOT_CLASS = "Concept"

# SQL type head -> LinkML range. The head is the type with its parameters removed, so
# `decimal(18,2)`, `varchar(64)` and `map<string,string>` are matched as `decimal`,
# `varchar` and `map`. Anything unlisted is a string: an unknown type is a slot whose
# values are still worth validating as text, never a reason to drop the slot.
_INTEGER_TYPES = frozenset(
    {"int", "integer", "bigint", "smallint", "tinyint", "long", "short", "byte"}
)
_FLOAT_TYPES = frozenset({"decimal", "numeric", "double", "float", "real"})
_DECIMAL_TYPES = frozenset({"decimal", "numeric"})
_DATE_TYPES = frozenset({"date"})
_DATETIME_TYPES = frozenset({"timestamp", "timestamp_ntz", "timestamp_ltz", "datetime"})
_BOOLEAN_TYPES = frozenset({"boolean", "bool"})

_SAFE_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# ------------------------------------------------------------------ the type mapping


def _type_head(sql_type) -> str:
    """``decimal(18,2)`` -> ``decimal``; the parameters carry no range information."""
    head = str(sql_type or "").strip().lower()
    for separator in ("(", "<", "["):
        head = head.split(separator, 1)[0]
    return head.strip()


def linkml_range(sql_type) -> str:
    head = _type_head(sql_type)
    if head in _BOOLEAN_TYPES:
        return "boolean"
    if head in _DATETIME_TYPES:
        return "datetime"
    if head in _DATE_TYPES:
        return "date"
    if head in _FLOAT_TYPES:
        return "float"
    if head in _INTEGER_TYPES:
        return "integer"
    return "string"


def shacl_datatype(sql_type) -> str:
    head = _type_head(sql_type)
    if head in _BOOLEAN_TYPES:
        return "xsd:boolean"
    if head in _DATETIME_TYPES:
        return "xsd:dateTime"
    if head in _DATE_TYPES:
        return "xsd:date"
    if head in _DECIMAL_TYPES:
        return "xsd:decimal"
    if head in _FLOAT_TYPES:
        return "xsd:double"
    if head in _INTEGER_TYPES:
        return "xsd:integer"
    return "xsd:string"


# -------------------------------------------------------------------- the vocabulary


def entity_class_ids(entities: Sequence[Mapping]) -> dict[str, str]:
    """``entity id -> the identifier both exports call it``.

    The ER diagram already had to answer this question, and answering it twice is a way
    for one corpus to have two names for one table.
    """
    return mermaid_entity_ids(entities)


def constraint_ids(constraints: Sequence[Mapping]) -> list[str]:
    """``cst:001`` .. one per constraint, by position.

    ``ontology.json`` gives a constraint no id of its own -- it is identified by its
    target and kind. The exports need a handle, and the constraint list is already
    deterministically sorted, so the position *is* a stable identity.
    """
    return [f"cst:{index:03d}" for index in range(1, len(constraints) + 1)]


def finding_ids(findings: Sequence[Mapping]) -> list[str]:
    """``sl:finding_001`` .. one per finding, by position.

    A finding has no id in ``ontology.json`` either -- it is identified by its kind,
    entity and columns, and ``findings[]`` is deterministically sorted. Both exports use
    the same token so one governance item has one name wherever it is read.
    """
    return [f"sl:finding_{index:03d}" for index in range(1, len(findings) + 1)]


def concept_class_ids(
    concepts: Sequence[Mapping], class_ids: Mapping[str, str]
) -> dict[str, str]:
    """``concept id -> the identifier both exports call it``.

    ``concept:cust`` becomes ``concept_cust`` by the same rule every other identifier
    follows, and is made unique against the *table* class ids: a concept and a table are
    two classes in one schema, and one name may not mean both.
    """
    found: dict[str, str] = {}
    taken = set(class_ids.values())
    for concept in concepts:
        name = _unique_name(taken | set(found.values()), _identifier(concept["id"]))
        found[str(concept["id"])] = name
    return found


def _concept_relations_from(ontology: Mapping, concept: str) -> list[Mapping]:
    return [
        relation
        for relation in ontology.get("concept_relations") or []
        if str(relation["from"]) == concept
    ]


def _concept_description(concept: Mapping) -> str:
    """What the concept is called, by whom, and how sure the corpus is of its kind."""
    candidates = "; ".join(
        f"{item.get('text')} ({item.get('source')} x{item.get('count')})"
        for item in concept.get("name_candidates") or ()
    )
    kind = f"kind {concept.get('kind')} ({concept.get('kind_tier')})"
    return f"{kind}; name candidates: {candidates}" if candidates else kind


def _concept_table_notes(concept: Mapping) -> list[str]:
    """``<table> -> <role>`` per member: which tables are this concept, and as what."""
    return [
        f"{item.get('table')} -> {item.get('role')} ({item.get('membership_basis')})"
        for item in concept.get("tables") or ()
    ]


def _attribute_sources(attribute: Mapping) -> list[str]:
    """``<table>.<column>`` per column the fold lifted this concept attribute from."""
    return [
        f"{item.get('table')}.{item.get('column')}"
        for item in attribute.get("sources") or ()
    ]


def _duplicate_note(concept: Mapping) -> str:
    """K2 proposes, it does not merge: the export says so rather than joining the two."""
    others = ", ".join(str(item) for item in concept.get("possible_duplicate_of") or ())
    return f"possibly the same concept as {others}" if others else ""


def _representation_note(link: Mapping) -> str:
    return (
        f"{link.get('concept')}: {link.get('from_table')} and {link.get('to_table')} "
        f"are two representations of one concept"
        f" (evidence {len(link.get('evidence') or ())})"
    )


def _table_concept_notes(ontology: Mapping) -> dict[str, dict]:
    """``table -> {name: note}`` -- what the concept layer says about each table.

    A table may represent several concepts (it carries their keys), so the names are
    made unique per table rather than assumed to be one each.
    """
    notes: dict[str, dict] = {}
    for concept in ontology.get("concepts") or ():
        for item in concept.get("tables") or ():
            entry = notes.setdefault(str(item.get("table")), {})
            note = f"{concept.get('id')} ({item.get('role')})"
            entry[_unique_name(entry, "represents")] = note
    for link in ontology.get("concept_representation_links") or ():
        note = _representation_note(link)
        for table in (str(link.get("from_table")), str(link.get("to_table"))):
            entry = notes.setdefault(table, {})
            entry[_unique_name(entry, "representation_link")] = note
    return notes


def _unassigned_notes(ontology: Mapping) -> list[str]:
    """``<table> (<reason>)`` per table no concept claimed, and why it could not."""
    return [
        f"{item.get('table')} ({item.get('reason')})"
        for item in ontology.get("unassigned_tables") or ()
    ]


@dataclass(frozen=True)
class _Constraint:
    """One constraint, flattened, with the id the exports refer to it by."""

    id: str
    kind: str
    tier: str
    entity: str
    column: str
    columns: tuple
    values: tuple
    completeness: str

    @property
    def closed_set(self) -> bool:
        return self.kind == CONSTRAINT_IN_SET and self.completeness == COMPLETENESS_COMPLETE

    def note(self) -> str:
        """The one line that says what this constraint asserts and who says so."""
        text = f"{self.kind} ({self.tier})"
        if self.columns:
            text += " on " + ", ".join(self.columns)
        if self.kind == CONSTRAINT_IN_SET:
            text += "; observed values: " + ", ".join(self.values)
            if not self.closed_set:
                text += "; the SQL did not prove the set closed"
        return text


def _constraints(ontology: Mapping) -> list[_Constraint]:
    raw = list(ontology.get("constraints") or [])
    items = []
    for item_id, item in zip(constraint_ids(raw), raw):
        target = item.get("target") or {}
        column = str(target.get("column") or "")
        # A whole-table constraint carries `columns`; a column one carries `target.column`.
        # Normalized here so every constraint can say which columns it is about.
        columns = tuple(str(name) for name in item.get("columns") or ()) or (
            (column,) if column else ()
        )
        items.append(
            _Constraint(
                id=item_id,
                kind=str(item.get("kind")),
                tier=str(item.get("tier")),
                entity=str(target.get("entity")),
                column=column,
                columns=columns,
                values=tuple(str(value) for value in item.get("values") or ()),
                completeness=str(item.get("completeness") or ""),
            )
        )
    return items


def _relations_from(ontology: Mapping, entity: str) -> list[Mapping]:
    return [
        relation
        for relation in ontology.get("relations") or []
        if str(relation["from"]["entity"]) == entity
    ]


def _single_valued(relation: Mapping) -> bool:
    claim = str((relation.get("cardinality") or {}).get("claim"))
    return claim in SINGLE_VALUED_CLAIMS


def _identifier(value) -> str:
    """The Mermaid identifier rule, applied to anything that is not an entity name."""
    word = "".join(
        char if char.isascii() and (char.isalnum() or char == "_") else "_"
        for char in str(value or "")
    )
    return word or "unknown"


def _unique_name(taken: Iterable[str], base: str) -> str:
    names = set(taken)
    candidate, suffix = base, 2
    while candidate in names:
        candidate, suffix = f"{base}_{suffix}", suffix + 1
    return candidate


def _split_constraints(items: Sequence[_Constraint], columns: frozenset):
    """``(per column, as unique keys, left over)`` -- a constraint never lands twice."""
    per_column: dict[str, list] = {}
    unique_keys: list[_Constraint] = []
    leftover: list[_Constraint] = []
    for item in items:
        if item.kind == CONSTRAINT_UNIQUE_PER:
            fits = bool(item.columns) and set(item.columns) <= set(columns)
            (unique_keys if fits else leftover).append(item)
        elif item.column and item.column in columns:
            per_column.setdefault(item.column, []).append(item)
        else:
            leftover.append(item)
    return per_column, unique_keys, leftover


# ------------------------------------------------- the facts neither format validates


# A declared key hint and a relation hint are the two assertions in `ontology.json` with
# no tier, and inventing one for them would be the export asserting something the corpus
# never did. They carry their evidence kind and this sentence instead -- the same reading
# `ontology.md` gives them (「元数据线索，不是语料证据」).
METADATA_HINT_NOTE = "a catalog hint rather than a corpus assertion, so it has no tier"


def _evidence_facts(evidence) -> dict:
    """``{"evidence_count": n, "evidence_task": first task}`` -- the size, not the rows.

    The evidence list is the largest thing in the JSON and the least useful to a schema:
    a reader wants to know how much there is and where to start, then goes back to
    ``ontology.json`` for the statements. The full list stays there.
    """
    items = list(evidence or ())
    if not items:
        return {}
    facts: dict = {"evidence_count": len(items)}
    task = next((str(item["task"]) for item in items if item.get("task")), "")
    if task:
        facts["evidence_task"] = task
    return facts


def _evidence_note(evidence) -> str:
    """The same two facts, for the places that hold one string rather than a mapping."""
    facts = _evidence_facts(evidence)
    if not facts:
        return ""
    note = f"; evidence_count {facts['evidence_count']}"
    task = facts.get("evidence_task")
    return note + (f", first task {task}" if task else "")


def _naming_facts(entity: Mapping) -> dict:
    """``domain`` / ``project`` / ``owner``, when the catalog declared them."""
    hints = entity.get("naming_hints") or {}
    keys = ("domain", "project", "owner")
    return {key: str(hints[key]) for key in keys if hints.get(key)}


def _declared_hint_facts(entity: Mapping) -> list[tuple[str, str]]:
    """H3: ``(columns, note)`` per column comment that calls a column a key."""
    identity = entity.get("identity") or {}
    facts = []
    for hint in identity.get("declared_hints") or ():
        columns = ", ".join(str(column) for column in hint.get("columns") or ())
        text = str(hint.get("text") or "")
        evidence = str(hint.get("evidence") or EVIDENCE_COLUMN_COMMENT)
        note = f"declared key on {columns}: {text}"
        facts.append((columns, f"{note} ({evidence}; {METADATA_HINT_NOTE})"))
    return facts


def _relation_hint_facts(entity: Mapping) -> list[tuple[str, str]]:
    """O9: ``(from column, note)`` per comment pointing at another entity's column."""
    facts = []
    for hint in entity.get("relation_hints") or ():
        column = str(hint.get("from_column") or "")
        target = f"{hint['to']['entity']}.{hint['to']['column']}"
        evidence = str(hint.get("evidence") or EVIDENCE_COLUMN_COMMENT)
        note = f"{column} -> {target}: {hint.get('text') or ''} ({evidence}"
        note += f"; unresolved: {hint['unresolved']}" if hint.get("unresolved") else ""
        facts.append((column, f"{note}; {METADATA_HINT_NOTE})"))
    return facts


def _multiplicity_facts(entity: Mapping) -> list[tuple[str, str, str]]:
    """O3: ``(columns, note, tier)`` per "some task saw many rows per this key"."""
    identity = entity.get("identity") or {}
    facts = []
    for item in identity.get("multiplicity") or ():
        columns = ", ".join(str(column) for column in item.get("columns") or ())
        tier = str(item.get("tier") or "")
        note = f"{item.get('claim')} ({tier}) on {columns}"
        facts.append((columns, note + _evidence_note(item.get("evidence")), tier))
    return facts


def _synonym_facts(attribute: Mapping) -> list[tuple[str, str, str]]:
    """O5: ``(note, via, tier)`` per other column the corpus saw hold the same value."""
    facts = []
    for synonym in attribute.get("synonyms") or ():
        via, tier = str(synonym.get("via") or ""), str(synonym.get("tier") or "")
        target = f"{synonym.get('entity')}.{synonym.get('column')}"
        note = f"{target} (via {via}, {tier}){_evidence_note(synonym.get('evidence'))}"
        facts.append((note, via, tier))
    return facts


def _finding_note(finding: Mapping) -> str:
    columns = ", ".join(str(column) for column in finding.get("columns") or ())
    where = f"{finding.get('entity')}" + (f" [{columns}]" if columns else "")
    return f"{finding.get('kind')} on {where}: {finding.get('text') or ''}"


def _open_item_note(item: Mapping) -> str:
    columns = ", ".join(str(column) for column in item.get("columns") or ())
    where = f"{item.get('entity')}" + (f" [{columns}]" if columns else "")
    note = f"{item.get('kind')} ({item.get('tier')}) on {where}: {item.get('text') or ''}"
    return note + (f" (write back: {item['write_back']})" if item.get("write_back") else "")


# ---------------------------------------------------------------------------- LinkML


def render_export(ontology: Mapping, export: str) -> str:
    """One ontology candidate as ``export`` (``linkml`` or ``shacl``) text."""
    if export == EXPORT_LINKML:
        return render_linkml(ontology)
    if export == EXPORT_SHACL:
        return render_shacl(ontology)
    raise ValueError(f"unknown ontology export format: {export!r}")


def render_linkml(ontology: Mapping) -> str:
    """The corpus as one LinkML schema: a class per entity, a slot per attribute."""
    entities = list(ontology.get("entities") or [])
    class_ids = entity_class_ids(entities)
    constraints = _constraints(ontology)
    schema = _linkml_header(ontology.get("corpus") or {})
    schema["annotations"].update(_linkml_governance(ontology))
    unassigned = _unassigned_notes(ontology)
    if unassigned:
        schema["annotations"]["unassigned_tables"] = unassigned
    enums = _linkml_enums(constraints, class_ids)
    if enums:
        schema["enums"] = enums
    schema["classes"] = _linkml_classes(ontology, entities, class_ids, constraints)
    return "\n".join(_yaml_lines(schema)) + "\n"


def _linkml_classes(
    ontology: Mapping, entities: Sequence[Mapping], class_ids: Mapping, constraints: Sequence
) -> dict:
    """The three concept bases, then one class per table, then one per concept.

    The bases are emitted only when the corpus folded a concept: an abstract class with
    nothing under it asserts that this corpus has a concept layer, and an unfolded one
    does not.
    """
    concepts = list(ontology.get("concepts") or [])
    concept_ids = concept_class_ids(concepts, class_ids)
    notes = _table_concept_notes(ontology)
    classes: dict = {}
    if concepts:
        classes.update({CONCEPT_BASE_CLASS[kind]: _linkml_base(kind) for kind in KIND_ORDER})
    for entity in entities:
        node = _linkml_class(entity, class_ids, ontology, constraints)
        node["annotations"].update(notes.get(str(entity["id"]), {}))
        classes[class_ids[str(entity["id"])]] = node
    for concept in concepts:
        classes[concept_ids[str(concept["id"])]] = _linkml_concept(
            concept, concept_ids, ontology
        )
    return classes


def _linkml_base(kind: str) -> dict:
    return {
        "abstract": True,
        "title": CONCEPT_BASE_CLASS[kind],
        "description": CONCEPT_BASE_DESCRIPTION[kind],
        "annotations": {"concept_kind": kind, "category": CONCEPT_BASE_CATEGORY[kind]},
    }


def _linkml_concept(concept: Mapping, concept_ids: Mapping, ontology: Mapping) -> dict:
    """One concept as a class under its kind's base, with its members and relations."""
    kind = str(concept.get("kind") or "")
    node: dict = {
        "is_a": CONCEPT_BASE_CLASS.get(kind, CONCEPT_ROOT_CLASS),
        "title": str(concept.get("name") or ""),
        "description": _concept_description(concept),
    }
    annotations: dict = {
        "concept_id": str(concept["id"]),
        "tier": str(concept.get("tier") or ""),
        "kind_tier": str(concept.get("kind_tier") or ""),
        "name_tier": str(concept.get("name_tier") or ""),
        "tables": _concept_table_notes(concept),
    }
    # M1: one table standing in for a concept nobody has named yet. Annotated rather
    # than left out, so a consumer chooses: the class is there for a pipeline that wants
    # every table covered, and `provisional: true` is the one flag that filters it away.
    if str(concept.get("tier")) == TIER_PROVISIONAL:
        annotations["provisional"] = True
    duplicate = _duplicate_note(concept)
    if duplicate:
        annotations["possible_duplicate_of"] = duplicate
    node["annotations"] = annotations
    node["attributes"] = _linkml_concept_attributes(concept, concept_ids, ontology)
    return node


def _linkml_concept_attributes(
    concept: Mapping, concept_ids: Mapping, ontology: Mapping
) -> dict:
    tier = str(concept.get("tier") or "")
    slots: dict = {}
    for attribute in concept.get("attributes") or ():
        name = _unique_name(slots, _identifier(attribute.get("stem")))
        slots[name] = _linkml_concept_attribute(attribute, tier)
    for relation in _concept_relations_from(ontology, str(concept["id"])):
        target = concept_ids[str(relation["to"])]
        name = _unique_name(slots, _identifier(f"{relation['type']}_{target}"))
        slots[name] = _linkml_concept_relation(relation, target)
    return slots


def _linkml_concept_attribute(attribute: Mapping, tier: str) -> dict:
    """A concept attribute is a column the fold lifted, so it keeps the fold's tier."""
    slot: dict = {"range": linkml_range(attribute.get("type"))}
    if attribute.get("comment"):
        slot["description"] = str(attribute["comment"])
    slot["annotations"] = {
        "tier": tier,
        "sources": _attribute_sources(attribute),
    }
    return slot


def _linkml_concept_relation(relation: Mapping, target: str) -> dict:
    cardinality = relation.get("cardinality") or {}
    annotations: dict = {
        "relation_type": str(relation.get("type")),
        "tier": str(cardinality.get("tier")),
        "claim": str(cardinality.get("claim")),
        "task_count": int(relation.get("task_count") or 0),
        "evidence_count": len(relation.get("evidence") or ()),
    }
    if relation.get("roles"):
        annotations["roles"] = [str(role) for role in relation["roles"]]
    return {
        "range": target,
        "multivalued": not _single_valued(relation),
        "description": f"{relation.get('type')} ({cardinality.get('claim')})",
        "annotations": annotations,
    }


def _linkml_header(corpus: Mapping) -> dict:
    root = str(corpus.get("artifact_root") or "").rstrip("/").rsplit("/", 1)[-1]
    name = _identifier(root) if root else "ontology"
    return {
        "id": SCHEMA_IRI + name,
        "name": name,
        "title": "scope-lineage ontology candidate",
        "description": (
            "Exported from an ontology candidate over a SQL corpus. Every element is an "
            "observation, not a curated business ontology: read the tier annotation "
            "before trusting a slot."
        ),
        "prefixes": {"linkml": LINKML_IRI, "sl": BASE_IRI, "cst": CONSTRAINT_IRI},
        "default_prefix": "sl",
        "default_range": "string",
        "imports": ["linkml:types"],
        "annotations": {
            "source_doc_format": DOC_FORMAT,
            "task_count": int(corpus.get("task_count") or 0),
        },
    }


def _linkml_governance(ontology: Mapping) -> dict:
    """``findings`` and ``open_items`` as schema-level annotations.

    They are not schema -- they are the list of questions the corpus could not answer --
    but an export that leaves them out tells a downstream tool the corpus had none.
    """
    findings = list(ontology.get("findings") or ())
    annotations = {
        item_id: _finding_note(finding)
        for item_id, finding in zip(finding_ids(findings), findings)
    }
    for item in ontology.get("open_items") or ():
        annotations[f"sl:open_item_{item['id']}"] = _open_item_note(item)
    return annotations


def _linkml_entity_annotations(entity: Mapping) -> dict:
    """Everything an entity asserts that is not a class, a slot or a constraint."""
    annotations: dict = dict(_naming_facts(entity))
    groups = (
        ("declared_hint", [(key, note) for key, note in _declared_hint_facts(entity)]),
        ("relation_hint", list(_relation_hint_facts(entity))),
        ("multiplicity", [(key, note) for key, note, _ in _multiplicity_facts(entity)]),
    )
    for prefix, facts in groups:
        for key, note in facts:
            base = f"{prefix}_{_identifier(key)}"
            annotations[_unique_name(annotations, base)] = note
    return annotations


def _enum_name(class_id: str, column: str) -> str:
    return f"{class_id}__{_identifier(column)}_enum"


def _linkml_enums(constraints: Sequence[_Constraint], class_ids: Mapping) -> dict:
    """One enum per value set the SQL proved closed; an open set gets no enum."""
    enums: dict = {}
    for item in constraints:
        if not item.closed_set or item.entity not in class_ids:
            continue
        enums[_enum_name(class_ids[item.entity], item.column)] = {
            "description": f"the closed value set of column {item.column}",
            "annotations": {item.id: item.note()},
            "permissible_values": {value: {} for value in item.values},
        }
    return dict(sorted(enums.items()))


def _linkml_class(
    entity: Mapping, class_ids: Mapping, ontology: Mapping, constraints: Sequence
) -> dict:
    name = str(entity["id"])
    class_id = class_ids[name]
    attributes = list(entity.get("attributes") or [])
    columns = frozenset(str(attribute["column"]) for attribute in attributes)
    mine = [item for item in constraints if item.entity == name]
    per_column, unique_per, leftover = _split_constraints(mine, columns)
    keys = _candidate_keys(entity, columns)
    node: dict = {"title": name}
    if entity.get("comment"):
        node["description"] = str(entity["comment"])
    node["annotations"] = {
        "entity_kind": str(entity.get("kind") or ""),
        "tier": TIER_PROVEN,
        **_linkml_entity_annotations(entity),
    }
    node["attributes"] = _linkml_attributes(
        attributes, per_column, keys, class_id, _relations_from(ontology, name), class_ids
    )
    unique_keys = _linkml_unique_keys(keys, unique_per)
    if unique_keys:
        node["unique_keys"] = unique_keys
    if leftover:
        node.setdefault("annotations", {}).update(
            {item.id: item.note() for item in leftover}
        )
    return node


def _candidate_keys(entity: Mapping, columns: frozenset) -> list[Mapping]:
    identity = entity.get("identity") or {}
    return [
        key
        for key in identity.get("candidate_keys") or []
        if key.get("columns") and set(map(str, key["columns"])) <= set(columns)
    ]


def _identifier_column(keys: Sequence[Mapping]) -> str:
    """The one column LinkML may call ``identifier``, or ``""``.

    A single column the corpus *proved* (or a person confirmed) identifies a row. A
    composite key cannot be a LinkML identifier, and an assumed key must not become one:
    ``identifier`` is the primary key of the class, and there is no tier on it.
    """
    for key in keys:
        if len(key["columns"]) == 1 and str(key.get("tier")) in (TIER_PROVEN, TIER_CONFIRMED):
            return str(key["columns"][0])
    return ""


def _linkml_attributes(
    attributes: Sequence[Mapping],
    per_column: Mapping,
    keys: Sequence[Mapping],
    class_id: str,
    relations: Sequence[Mapping],
    class_ids: Mapping,
) -> dict:
    identity_column = _identifier_column(keys)
    key_tiers = {
        str(key["columns"][0]): str(key.get("tier")) for key in keys if len(key["columns"]) == 1
    }
    slots: dict = {}
    for attribute in attributes:
        column = str(attribute["column"])
        slots[column] = _linkml_attribute(
            attribute,
            per_column.get(column) or (),
            class_id,
            identity=column == identity_column,
            key_tier=key_tiers.get(column, ""),
        )
    for relation in relations:
        name = _unique_name(slots, _identifier(str(relation["id"])))
        slots[name] = _linkml_relation(relation, class_ids)
    return slots


def _linkml_attribute(
    attribute: Mapping,
    items: Sequence[_Constraint],
    class_id: str,
    *,
    identity: bool,
    key_tier: str,
) -> dict:
    column = str(attribute["column"])
    closed = next((item for item in items if item.closed_set), None)
    slot: dict = {
        "range": _enum_name(class_id, column) if closed else linkml_range(attribute.get("type"))
    }
    if attribute.get("comment"):
        slot["description"] = str(attribute["comment"])
    if any(item.kind == CONSTRAINT_NOT_NULL for item in items):
        slot["required"] = True
    if identity:
        slot["identifier"] = True
    annotations: dict = {"tier": TIER_PROVEN}
    if key_tier:
        annotations["key_tier"] = key_tier
    synonyms = [note for note, _, _ in _synonym_facts(attribute)]
    if synonyms:
        annotations["synonyms"] = synonyms
    annotations.update({item.id: item.note() for item in items if item is not closed})
    slot["annotations"] = annotations
    return slot


def _linkml_relation(relation: Mapping, class_ids: Mapping) -> dict:
    cardinality = relation.get("cardinality") or {}
    columns = ", ".join(
        f"{left} = {right}"
        for left, right in zip(relation["from"]["columns"], relation["to"]["columns"])
    )
    return {
        "range": class_ids[str(relation["to"]["entity"])],
        "multivalued": not _single_valued(relation),
        "description": f"{relation.get('kind')} on {columns}",
        "annotations": {
            "relation_id": str(relation["id"]),
            "tier": str(cardinality.get("tier")),
            "claim": str(cardinality.get("claim")),
            "basis": str(cardinality.get("basis") or ""),
            "task_count": int(relation.get("task_count") or 0),
            **_evidence_facts(relation.get("evidence")),
        },
    }


def _linkml_unique_keys(keys: Sequence[Mapping], unique_per: Sequence[_Constraint]) -> dict:
    """Every key LinkML can hold that ``identifier`` could not: composite, or assumed."""
    entries: dict = {}
    identity_column = _identifier_column(keys)
    for key in keys:
        columns = [str(column) for column in key["columns"]]
        if columns == [identity_column]:
            continue
        name = _unique_name(entries, "key_" + "_".join(_identifier(c) for c in columns))
        entries[name] = {
            "unique_key_slots": columns,
            "description": "a candidate key the corpus proposed",
            "annotations": {
                "tier": str(key.get("tier")),
                **_evidence_facts(key.get("evidence")),
            },
        }
    for item in unique_per:
        entries[_identifier(item.id)] = {
            "unique_key_slots": list(item.columns),
            "description": "a unique_per constraint the corpus asserted",
            "annotations": {"tier": item.tier, item.id: item.note()},
        }
    return entries


# ----------------------------------------------------------------------------- SHACL


# The one thing SHACL core cannot say. Both a `unique_per` constraint and a candidate
# key are a uniqueness claim over a tuple of columns, and SHACL core has no constraint
# component for that -- expressing it takes a `sh:sparql` constraint, which is a
# different dialect and a different runtime. So the claim is published as an annotation
# that says exactly this, rather than as a shape that validates something weaker.
COMPOSITE_KEY_LIMITATION = (
    "SHACL core has no composite uniqueness constraint, so this is an annotation rather "
    "than a validated shape"
)

SHACL_PREFIXES = (
    ("rdfs", "http://www.w3.org/2000/01/rdf-schema#"),
    ("sh", "http://www.w3.org/ns/shacl#"),
    ("sl", BASE_IRI),
    ("xsd", "http://www.w3.org/2001/XMLSchema#"),
)


def render_shacl(ontology: Mapping) -> str:
    """The corpus as SHACL shapes: one ``sh:NodeShape`` per entity."""
    entities = list(ontology.get("entities") or [])
    class_ids = entity_class_ids(entities)
    concepts = list(ontology.get("concepts") or [])
    concept_ids = concept_class_ids(concepts, class_ids)
    notes = _table_concept_notes(ontology)
    constraints = _constraints(ontology)
    lines = [f"@prefix {prefix}: <{iri}> ." for prefix, iri in SHACL_PREFIXES]
    lines.append("")
    lines.append(
        "# Exported from an ontology candidate over a SQL corpus. The base IRI is a "
        "placeholder;"
    )
    lines.append(
        "# every shape carries sl:tier for the assertion it came from -- read it before "
        "validating."
    )
    for kind in KIND_ORDER if concepts else ():
        lines.extend(["", *_shacl_kind_class(kind)])
    for entity in entities:
        lines.append("")
        lines.extend(_shacl_node_shape(entity, class_ids, ontology, constraints, notes))
    for concept in concepts:
        lines.append("")
        lines.extend(_shacl_concept_shape(concept, concept_ids, ontology))
    governance = _shacl_governance(ontology)
    if governance:
        lines.extend(["", *governance])
    return "\n".join(lines) + "\n"


def _shacl_kind_class(kind: str) -> list[str]:
    """One of the three concept bases, as a class the concept shapes hang under."""
    return [
        f"sl:{CONCEPT_BASE_CLASS[kind]}",
        "    a rdfs:Class ;",
        f"    rdfs:subClassOf sl:{CONCEPT_ROOT_CLASS} ;",
        f"    rdfs:label {_turtle_string(CONCEPT_BASE_CLASS[kind])} ;",
        f"    rdfs:comment {_turtle_string(CONCEPT_BASE_DESCRIPTION[kind])} ;",
        f"    sl:conceptKind {_turtle_string(kind)} ;",
        f"    sl:category {_turtle_string(CONCEPT_BASE_CATEGORY[kind])} .",
    ]


def _shacl_concept_shape(
    concept: Mapping, concept_ids: Mapping, ontology: Mapping
) -> list[str]:
    """One concept as a ``sh:NodeShape`` under its kind class, tier and members intact."""
    concept_id = str(concept["id"])
    class_id = concept_ids[concept_id]
    tier = str(concept.get("tier") or "")
    kind = CONCEPT_BASE_CLASS.get(str(concept.get("kind") or ""), CONCEPT_ROOT_CLASS)
    blocks = [
        _shacl_concept_attribute(attribute, tier)
        for attribute in concept.get("attributes") or ()
    ]
    blocks.extend(
        _shacl_concept_relation(relation, concept_ids[str(relation["to"])])
        for relation in _concept_relations_from(ontology, concept_id)
    )
    head = [
        f"sl:{class_id}Shape",
        "    a sh:NodeShape ;",
        f"    sh:targetClass sl:{class_id} ;",
        f"    rdfs:subClassOf sl:{kind} ;",
        f"    rdfs:label {_turtle_string(str(concept.get('name') or ''))} ;",
        f"    rdfs:comment {_turtle_string(_concept_description(concept))} ;",
        f"    sl:concept {_turtle_string(concept_id)} ;",
        f"    sl:kindTier {_turtle_string(str(concept.get('kind_tier') or ''))} ;",
        f"    sl:nameTier {_turtle_string(str(concept.get('name_tier') or ''))} ;",
        *_shacl_provisional_lines(concept),
        *(f"    sl:conceptTable {_turtle_string(n)} ;" for n in _concept_table_notes(concept)),
        *_shacl_duplicate_lines(concept),
        f'    sl:tier "{tier}"',
    ]
    return _turtle_statement(head, blocks)


def _shacl_provisional_lines(concept: Mapping) -> list[str]:
    """M1: the one flag a consumer filters a table-standing-in-for-a-concept away by."""
    if str(concept.get("tier")) != TIER_PROVISIONAL:
        return []
    return ["    sl:provisional true ;"]


def _shacl_duplicate_lines(concept: Mapping) -> list[str]:
    note = _duplicate_note(concept)
    return [f"    sl:possibleDuplicateOf {_turtle_string(note)} ;"] if note else []


def _shacl_concept_attribute(attribute: Mapping, tier: str) -> list[str]:
    stem = str(attribute.get("stem") or "")
    lines = [
        "sh:property [",
        f"        sh:path sl:{_identifier(stem)} ;",
        f"        sh:name {_turtle_string(stem)} ;",
        f"        sh:datatype {shacl_datatype(attribute.get('type'))} ;",
    ]
    if attribute.get("comment"):
        lines.append(f"        rdfs:comment {_turtle_string(str(attribute['comment']))} ;")
    lines.extend(
        f"        sl:source {_turtle_string(source)} ;"
        for source in _attribute_sources(attribute)
    )
    lines.append(f'        sl:tier "{tier}"')
    lines.append("    ]")
    return lines


def _shacl_concept_relation(relation: Mapping, target: str) -> list[str]:
    cardinality = relation.get("cardinality") or {}
    lines = [
        "sh:property [",
        f"        sh:path sl:{_identifier(str(relation.get('type')) + '_' + target)} ;",
        f"        sh:class sl:{target} ;",
    ]
    if _single_valued(relation):
        lines.append("        sh:maxCount 1 ;")
    lines.append(f"        sl:relationType {_turtle_string(str(relation.get('type')))} ;")
    lines.extend(
        f"        sl:role {_turtle_string(str(role))} ;" for role in relation.get("roles") or ()
    )
    lines.append(f"        sl:claim \"{cardinality.get('claim')}\" ;")
    lines.append(f"        sl:taskCount {int(relation.get('task_count') or 0)} ;")
    lines.append(f"        sl:evidenceCount {len(relation.get('evidence') or ())} ;")
    lines.append(f"        sl:tier \"{cardinality.get('tier')}\"")
    lines.append("    ]")
    return lines


def _shacl_governance(ontology: Mapping) -> list[str]:
    """``findings`` and ``open_items`` on one schema-level ``sl:Ontology`` node.

    They belong to no shape -- a contradiction between two tasks is about the corpus, not
    about one table -- so they hang off the document itself rather than being dropped.
    """
    findings = list(ontology.get("findings") or ())
    items = list(ontology.get("open_items") or ())
    unassigned = _unassigned_notes(ontology)
    if not findings and not items and not unassigned:
        return []
    blocks = [
        _shacl_annotation_block(
            "sl:finding",
            ("id", item_id),
            _finding_note(finding),
            kind=str(finding.get("kind") or ""),
        )
        for item_id, finding in zip(finding_ids(findings), findings)
    ]
    blocks.extend(
        _shacl_annotation_block(
            "sl:openItem",
            ("id", str(item["id"])),
            _open_item_note(item),
            kind=str(item.get("kind") or ""),
            tier=str(item.get("tier") or ""),
        )
        for item in items
    )
    head = [
        "sl:Ontology",
        *(f"    sl:unassignedTable {_turtle_string(note)} ;" for note in unassigned),
        '    rdfs:label "the governance items this corpus could not answer itself"',
    ]
    return _turtle_statement(head, blocks)


def _shacl_annotation_block(
    predicate: str, subject: tuple, note: str, **facts: str
) -> list[str]:
    """One blank node holding an assertion SHACL core has no shape for.

    ``subject`` is the ``(predicate name, value)`` that says what the block is about --
    an id for a governance item, the columns for an assertion about a key -- and
    ``facts`` are the remaining ``sl:`` triples, empty values dropped.
    """
    triples = [
        f"sl:{subject[0]} {_turtle_string(subject[1])}",
        f"rdfs:comment {_turtle_string(note)}",
        *(f"sl:{name} {_turtle_string(value)}" for name, value in facts.items() if value),
    ]
    lines = [f"{predicate} ["]
    lines.extend(f"        {triple} ;" for triple in triples[:-1])
    return [*lines, f"        {triples[-1]}", "    ]"]


def _shacl_node_shape(
    entity: Mapping,
    class_ids: Mapping,
    ontology: Mapping,
    constraints: Sequence,
    notes: Mapping[str, Mapping] | None = None,
) -> list[str]:
    name = str(entity["id"])
    class_id = class_ids[name]
    blocks: list[list[str]] = []
    for attribute in entity.get("attributes") or []:
        blocks.append(_shacl_attribute_shape(attribute))
    for item in constraints:
        if item.entity == name and item.kind != CONSTRAINT_UNIQUE_PER:
            blocks.append(_shacl_constraint_shape(item))
    for relation in _relations_from(ontology, name):
        blocks.append(_shacl_relation_shape(relation, class_ids))
    for item in constraints:
        if item.entity == name and item.kind == CONSTRAINT_UNIQUE_PER:
            blocks.append(_shacl_composite_key(item))
    for key in entity.get("identity", {}).get("candidate_keys") or []:
        blocks.append(_shacl_candidate_key(key))
    blocks.extend(_shacl_entity_blocks(entity))
    head = [
        f"sl:{class_id}Shape",
        "    a sh:NodeShape ;",
        f"    sh:targetClass sl:{class_id} ;",
        f"    rdfs:label {_turtle_string(name)} ;",
    ]
    if entity.get("comment"):
        head.append(f"    rdfs:comment {_turtle_string(str(entity['comment']))} ;")
    for name_, value in _naming_facts(entity).items():
        head.append(f"    sl:{name_} {_turtle_string(value)} ;")
    for name_, note in (notes or {}).get(name, {}).items():
        represents = name_.startswith("represents")
        predicate = "sl:represents" if represents else "sl:representationLink"
        head.append(f"    {predicate} {_turtle_string(note)} ;")
    head.append(f'    sl:tier "{TIER_PROVEN}"')
    return _turtle_statement(head, blocks)


def _shacl_entity_blocks(entity: Mapping) -> list[list[str]]:
    """The entity facts no shape validates: the two hint kinds, multiplicity, synonyms.

    Each is an assertion about the table rather than a constraint on its rows, so each is
    an annotation blank node that names what it is about and who says so.
    """
    hint = {"evidence": EVIDENCE_COLUMN_COMMENT}
    blocks = [
        _shacl_annotation_block("sl:declaredKeyHint", ("column", columns), note, **hint)
        for columns, note in _declared_hint_facts(entity)
    ]
    blocks.extend(
        _shacl_annotation_block("sl:relationHint", ("column", column), note, **hint)
        for column, note in _relation_hint_facts(entity)
    )
    blocks.extend(
        _shacl_annotation_block("sl:multiplicity", ("column", columns), note, tier=tier)
        for columns, note, tier in _multiplicity_facts(entity)
    )
    blocks.extend(
        _shacl_annotation_block(
            "sl:synonym", ("column", str(attribute["column"])), note, via=via, tier=tier
        )
        for attribute in entity.get("attributes") or ()
        for note, via, tier in _synonym_facts(attribute)
    )
    return blocks


def _shacl_attribute_shape(attribute: Mapping) -> list[str]:
    column = str(attribute["column"])
    lines = [
        "sh:property [",
        f"        sh:path sl:{_identifier(column)} ;",
        f"        sh:name {_turtle_string(column)} ;",
        f"        sh:datatype {shacl_datatype(attribute.get('type'))} ;",
    ]
    if attribute.get("comment"):
        lines.append(f"        rdfs:comment {_turtle_string(str(attribute['comment']))} ;")
    lines.append(f'        sl:tier "{TIER_PROVEN}"')
    lines.append("    ]")
    return lines


def _shacl_constraint_shape(item: _Constraint) -> list[str]:
    path = _identifier(item.column) if item.column else _identifier(item.kind)
    lines = ["sh:property [", f"        sh:path sl:{path} ;"]
    if item.kind == CONSTRAINT_NOT_NULL:
        lines.append("        sh:minCount 1 ;")
    if item.closed_set:
        values = " ".join(_turtle_string(value) for value in item.values)
        lines.append(f"        sh:in ( {values} ) ;")
    lines.append(f"        rdfs:comment {_turtle_string(item.note())} ;")
    lines.append(f"        sl:constraint {_turtle_string(item.id)} ;")
    lines.append(f'        sl:tier "{item.tier}"')
    lines.append("    ]")
    return lines


def _shacl_relation_shape(relation: Mapping, class_ids: Mapping) -> list[str]:
    cardinality = relation.get("cardinality") or {}
    lines = [
        "sh:property [",
        f"        sh:path sl:{_identifier(str(relation['id']))} ;",
        f"        sh:class sl:{class_ids[str(relation['to']['entity'])]} ;",
    ]
    if _single_valued(relation):
        lines.append("        sh:maxCount 1 ;")
    lines.append(f"        sl:relation {_turtle_string(str(relation['id']))} ;")
    lines.append(f"        sl:claim \"{cardinality.get('claim')}\" ;")
    lines.append(f"        sl:taskCount {int(relation.get('task_count') or 0)} ;")
    lines.extend(_shacl_evidence_lines(relation.get("evidence")))
    lines.append(f"        sl:tier \"{cardinality.get('tier')}\"")
    lines.append("    ]")
    return lines


def _shacl_evidence_lines(evidence) -> list[str]:
    """The evidence in summary: how much there is, and one task to start reading at."""
    facts = _evidence_facts(evidence)
    lines = []
    if facts.get("evidence_count"):
        lines.append(f"        sl:evidenceCount {facts['evidence_count']} ;")
    if facts.get("evidence_task"):
        lines.append(f"        sl:evidenceTask {_turtle_string(facts['evidence_task'])} ;")
    return lines


def _shacl_composite_key(item: _Constraint) -> list[str]:
    """``unique_per`` has no SHACL core form, so it is published as an annotation."""
    columns = ", ".join(_turtle_string(column) for column in item.columns)
    note = f"{item.note()}; {COMPOSITE_KEY_LIMITATION}"
    return [
        "sl:compositeKey [",
        f"        sl:constraint {_turtle_string(item.id)} ;",
        f"        sl:keyColumn {columns} ;",
        f"        rdfs:comment {_turtle_string(note)} ;",
        f'        sl:tier "{item.tier}"',
        "    ]",
    ]


def _shacl_candidate_key(key: Mapping) -> list[str]:
    columns = ", ".join(_turtle_string(str(column)) for column in key.get("columns") or ())
    note = f"candidate key; {COMPOSITE_KEY_LIMITATION}"
    return [
        "sl:candidateKey [",
        f"        sl:keyColumn {columns} ;",
        f"        rdfs:comment {_turtle_string(note)} ;",
        *_shacl_evidence_lines(key.get("evidence")),
        f"        sl:tier \"{key.get('tier')}\"",
        "    ]",
    ]


# ------------------------------------------------------------------- the two writers


def _yaml_key(key) -> str:
    text = str(key)
    return text if _SAFE_KEY.match(text) else _yaml_scalar(text)


def _yaml_scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    escaped = (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _yaml_lines(value: Mapping, indent: int = 0) -> list[str]:
    """Nested mappings, lists and scalars, in insertion order, always double-quoted.

    Deliberately not a general YAML writer: it emits the shapes this module builds, and
    quotes every string rather than deciding which ones need it, so the bytes are the
    same on every run and on every platform.
    """
    lines: list[str] = []
    pad = " " * indent
    for key, item in value.items():
        prefix = f"{pad}{_yaml_key(key)}:"
        if isinstance(item, Mapping):
            lines.append(prefix if item else f"{prefix} {{}}")
            lines.extend(_yaml_lines(item, indent + 2))
        elif isinstance(item, (list, tuple)):
            lines.append(prefix if item else f"{prefix} []")
            lines.extend(f"{pad}  - {_yaml_scalar(entry)}" for entry in item)
        else:
            lines.append(f"{prefix} {_yaml_scalar(item)}")
    return lines


def _turtle_string(value) -> str:
    escaped = (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _turtle_statement(head: list[str], blocks: Sequence[Sequence[str]]) -> list[str]:
    """One subject's predicate-object list, terminated with ``.`` and nothing else."""
    lines = list(head)
    for block in blocks:
        lines[-1] = lines[-1] + " ;"
        lines.append("    " + block[0])
        lines.extend(block[1:])
    lines[-1] = lines[-1] + " ."
    return lines
