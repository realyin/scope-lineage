"""``build_ontology``: a valid catalog, normalised into one ``ontology-json/3`` document.

Normalised means a reader never has to know how the catalog was written:
- every object carries ``status`` (default ``drafted``), ``source`` (default ``null``) and
  ``evidence`` (default ``[]``); an attribute inherits both from its concept, a binding
  from its representation;
- keys come out in one fixed order per object type, whatever order the author used;
- code and state values are text (``0`` and ``"0"`` are the same code);
  a cardinality end written as the number ``1`` is ``"1"``;
- a text ``arises_when`` becomes ``{condition}``;
- lists are sorted by id (terms by term then target, representations by table), so
  moving an object to another file does not change a byte of the output. Lists inside
  an object -- attributes, values, bindings -- keep the author's order, which means
  something (column order, state order).
Every event participant also becomes a ``participation`` relation, and a
``foreign_identifier`` naming another instance of the table's own concept is marked
``self_reference`` (validation guarantees a relation from that concept to itself).
"""

from __future__ import annotations

from .index import Index, build_index
from .model import CATALOG_FORMAT, ONTOLOGY_FORMAT, ONTOLOGY_SCHEMA, Catalog, CatalogError
from .references import derived_relation_id
from .validate import validate_catalog

UNCONFIRMED = "待确认"  # a code meaning that starts so is a guess, not a fact


def build_ontology(catalog: Catalog) -> dict:
    """The ``ontology-json/3`` document; ``CatalogError`` when the catalog has errors."""
    report = validate_catalog(catalog)
    if not report.ok:
        shown = "; ".join(error.render() for error in report.errors[:5])
        more = f" (and {len(report.errors) - 5} more)" if len(report.errors) > 5 else ""
        raise CatalogError(f"{len(report.errors)} error(s) in the catalog: {shown}{more}")
    lists = _lists(catalog)
    return {
        "doc_format": ONTOLOGY_FORMAT,
        "catalog": _catalog_header(catalog),
        "counts": _counts(lists),
        **lists,
    }


def validate_ontology_document(document: dict) -> dict:
    """Check a built document against the packaged ``ontology-json/3`` schema."""
    import jsonschema

    from .structure import packaged_schema

    jsonschema.validate(document, packaged_schema(ONTOLOGY_SCHEMA))
    return document


def _catalog_header(catalog: Catalog) -> dict:
    header = {"name": catalog.name}
    if "description" in catalog.manifest:
        header["description"] = catalog.manifest["description"]
    header["format"] = CATALOG_FORMAT
    return header


def _lists(catalog: Catalog) -> dict:
    def normalised(kind, normalise):
        return [normalise(obj) for _file, obj in catalog.records(kind)]

    concepts = normalised("concepts", _concept)
    relations = normalised("relations", _relation) + _participations(concepts)
    index = build_index(catalog)
    return {
        "domains": _by_id(normalised("domains", _domain)),
        "identifiers": _by_id(normalised("identifiers", _identifier)),
        "code_sets": _by_id(normalised("code_sets", _code_set)),
        "concepts": _by_id(concepts),
        "relations": _by_id(relations),
        "constraints": _by_id(normalised("constraints", _constraint)),
        "terms": sorted(normalised("terms", _term), key=lambda t: (t["term"], t["refers_to"])),
        "representations": sorted(
            normalised("mapping", lambda rep: _representation(rep, index)),
            key=lambda r: r["table"],
        ),
    }


def _by_id(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda item: item["id"])


def _counts(lists: dict) -> dict:
    counts = {key: len(value) for key, value in lists.items()}
    counts["attributes"] = sum(len(c["attributes"]) for c in lists["concepts"])
    counts["derived_relations"] = sum(1 for r in lists["relations"] if "derived_from" in r)
    counts["bindings"] = sum(len(r["bindings"]) for r in lists["representations"])
    return counts


# --- shared shape ----------------------------------------------------------------------


def _pick(obj: dict, keys: tuple) -> dict:
    return {key: obj[key] for key in keys if key in obj}


def _common(obj: dict, parent: dict | None = None) -> dict:
    parent = parent or {}
    common = {
        "status": obj.get("status", parent.get("status", "drafted")),
        "source": obj.get("source", parent.get("source")),
        "evidence": list(obj.get("evidence") or []),
    }
    if "notes" in obj:
        common["notes"] = obj["notes"]
    return common


# --- one normaliser per object type ----------------------------------------------------


def _domain(obj: dict) -> dict:
    return {**_pick(obj, ("id", "name", "description")), **_common(obj)}


def _identifier(obj: dict) -> dict:
    out = _pick(obj, ("id", "name", "identifies", "scope"))
    arises = obj.get("arises_when")
    if arises is not None:
        out["arises_when"] = {"condition": arises} if isinstance(arises, str) else dict(arises)
    out["spellings"] = [_pick(s, ("column", "table")) for s in obj.get("spellings") or []]
    out["maps_to"] = [
        {**_pick(m, ("identifier", "cardinality")), "via": list(m.get("via") or [])}
        for m in obj.get("maps_to") or []
    ]
    return {**out, **_pick(obj, ("format",)), **_common(obj)}


def _code_set(obj: dict) -> dict:
    values = [
        {
            "value": str(v["value"]),
            "meaning": v["meaning"],
            "retired": bool(v.get("retired", False)),
            "unconfirmed": _unconfirmed(v),
        }
        for v in obj["values"]
    ]
    return {**_pick(obj, ("id", "name", "definition")), "values": values, **_common(obj)}


def _unconfirmed(value: dict) -> bool:
    """Flagged, or a meaning nobody has filled in (empty, or still starting 待确认)."""
    meaning = str(value["meaning"]).strip()
    return bool(value.get("unconfirmed")) or not meaning or meaning.startswith(UNCONFIRMED)


def _concept(obj: dict) -> dict:
    out = _pick(obj, ("id", "kind", "name", "definition", "domain"))
    out["synonyms"] = list(obj.get("synonyms") or [])
    out.update(_pick(obj, ("identifiers", "primary_identifier")))
    if "states" in obj:
        out["states"] = _states(obj["states"])
    out.update(_pick(obj, ("occurred_at",)))
    if "participants" in obj:
        keys = ("role_name", "concept", "cardinality")
        out["participants"] = [_pick(p, keys) for p in obj["participants"]]
    out.update(_pick(obj, ("player", "context", "condition")))
    out["attributes"] = [_attribute(a, obj) for a in obj.get("attributes") or []]
    return {**out, **_common(obj)}


def _states(states: dict) -> dict:
    return {
        "attribute": states["attribute"],
        "values": [{"value": str(v["value"]), "name": v["name"]} for v in states["values"]],
        "transitions": [
            {"event": t["event"], "from": str(t["from"]), "to": str(t["to"])}
            for t in states.get("transitions") or []
        ],
    }


def _attribute(obj: dict, concept: dict) -> dict:
    keys = ("id", "name", "definition", "category", "type", "unit", "code_set", "derivation")
    return {**_pick(obj, keys), **_common(obj, concept)}


def _relation(obj: dict) -> dict:
    out = _pick(obj, ("id", "kind", "from", "to", "name", "inverse_name"))
    out["cardinality"] = {end: str(obj["cardinality"][end]) for end in ("from", "to")}
    return {**out, **_pick(obj, ("definition",)), **_common(obj)}


def _participations(concepts: list[dict]) -> list[dict]:
    """Each participant as ``event --role_name--> concept``: ``0..*`` events per player,
    one (``1``) or several (``1..*``) players per event."""
    relations = []
    for event in concepts:
        for participant in event.get("participants") or []:
            role_name = participant["role_name"]
            relations.append({
                "id": derived_relation_id(event["id"], role_name),
                "kind": "participation",
                "from": event["id"],
                "to": participant["concept"],
                "name": role_name,
                "cardinality": {
                    "from": "0..*",
                    "to": "1" if participant["cardinality"] == "one" else "1..*",
                },
                "derived_from": {"event": event["id"], "role_name": role_name},
                **_pick(event, ("status", "source")),
                "evidence": [],
            })
    return relations


def _constraint(obj: dict) -> dict:
    return {**_pick(obj, ("id", "kind", "on", "expression", "strength")), **_common(obj)}


def _term(obj: dict) -> dict:
    return {**_pick(obj, ("term", "refers_to", "preferred")), **_common(obj)}


def _representation(obj: dict, index: Index) -> dict:
    grain = obj["grain"]
    out = _pick(obj, ("table", "concept", "kind"))
    out["grain"] = {
        "identifiers": list(grain["identifiers"]),
        "extra": list(grain.get("extra") or []),
        "source": grain["source"],
    }
    out.update(_pick(obj, ("time",)))
    out["scope"] = list(obj.get("scope") or [])
    out.update(_pick(obj, ("refresh", "table_status", "replaced_by")))
    owners = index.binding_owners(obj["concept"]) or (obj["concept"],)
    own_ids = set().union(*(index.identifiers_of(owner) for owner in owners))
    out["bindings"] = [_binding(b, obj, own_ids) for b in obj["bindings"]]
    return {**out, **_common(obj)}


def _binding(obj: dict, representation: dict, own_ids: set) -> dict:
    out = _pick(obj, ("column", "to", "ref", "via"))
    if obj["to"] == "foreign_identifier" and obj["ref"] in own_ids:
        out["self_reference"] = True
    out.update(_pick(obj, ("derivation",)))
    if "code_map" in obj:
        out["code_map"] = {str(key): value for key, value in obj["code_map"].items()}
    return {**out, **_common(obj, representation)}
