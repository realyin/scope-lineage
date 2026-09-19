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

No third-party writer is used: both formats are emitted as text by the small
deterministic writers at the bottom of this module, so the export adds no runtime
dependency to a distribution whose dependency list is a product decision.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .ontology import (
    CARDINALITY_MANY_TO_ONE,
    CARDINALITY_MANY_TO_ONE_ASSUMED,
    CARDINALITY_ONE_TO_ONE_ASSUMED,
    COMPLETENESS_COMPLETE,
    CONSTRAINT_IN_SET,
    CONSTRAINT_NOT_NULL,
    CONSTRAINT_UNIQUE_PER,
    DOC_FORMAT,
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


# ---------------------------------------------------------------------------- LinkML


def render_export(ontology: Mapping, export: str) -> str:
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
    enums = _linkml_enums(constraints, class_ids)
    if enums:
        schema["enums"] = enums
    schema["classes"] = {
        class_ids[str(entity["id"])]: _linkml_class(entity, class_ids, ontology, constraints)
        for entity in entities
    }
    return "\n".join(_yaml_lines(schema)) + "\n"


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
    node["annotations"] = {"entity_kind": str(entity.get("kind") or ""), "tier": TIER_PROVEN}
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
    annotations = {"tier": TIER_PROVEN}
    if key_tier:
        annotations["key_tier"] = key_tier
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
            "annotations": {"tier": str(key.get("tier"))},
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
    for entity in entities:
        lines.append("")
        lines.extend(_shacl_node_shape(entity, class_ids, ontology, constraints))
    return "\n".join(lines) + "\n"


def _shacl_node_shape(
    entity: Mapping, class_ids: Mapping, ontology: Mapping, constraints: Sequence
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
    head = [
        f"sl:{class_id}Shape",
        "    a sh:NodeShape ;",
        f"    sh:targetClass sl:{class_id} ;",
        f"    rdfs:label {_turtle_string(name)} ;",
    ]
    if entity.get("comment"):
        head.append(f"    rdfs:comment {_turtle_string(str(entity['comment']))} ;")
    head.append(f'    sl:tier "{TIER_PROVEN}"')
    return _turtle_statement(head, blocks)


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
    lines.append(f"        sl:tier \"{cardinality.get('tier')}\"")
    lines.append("    ]")
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
