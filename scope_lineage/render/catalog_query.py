"""``catalog query``: one question to a built ``ontology-json/3`` document, one short answer.

Eight kinds of question, each answered from the document alone:

- ``concept``    -- by id, name, synonym or term: identity, attributes, states, tables;
- ``table``      -- ``db.table`` (a catalog prefix is ignored): the concept it carries and
  what every bound column points at (another concept's attribute repeated here, with the
  column it is reached through; another instance of the same concept, with the relation),
  with the evidence merged at build time;
- ``column``     -- ``db.table.column``: the attribute or identifier it holds, or the
  identifier it spells when the catalog only names it as a spelling;
- ``identifier`` -- by id, name or physical spelling: what it identifies, where it is bound;
- ``attribute``  -- by id, name or term: its concept, code values and every table column;
- ``related``    -- a concept's one-hop neighbourhood: relations, events, roles, tables,
  and the tables carrying its identifiers;
- ``carriers``   -- every table, of any concept, that binds one of a concept's identifiers
  (as ``identifier`` or ``foreign_identifier``): where the concept can be joined in;
- ``scope``      -- a kind of filter (``validity``/有效记录, ``deletion``/删除, ``dedup``/去重,
  ``partition``/分区, ``other``/其他) or a keyword: the tables whose scope lines or cited
  business rules state it, each with those lines.

``query_catalog`` returns ``{"query": {kind, term}, "matches": [...]}`` -- the structure
an agent reads (``--json``); ``render_query_text`` is the few lines a person reads.
Names match exactly, ignoring case and surrounding spaces; nothing is guessed.
"""

from __future__ import annotations

from collections.abc import Mapping

from .catalog_concept_page import reading_text
from .catalog_query_text import render_query_text
from .catalog_scopes import query_scopes, rules_citing
from .catalog_view import (
    CatalogView,
    catalog_table_name,
    concept_filename,
    usage_hint,
)

__all__ = ["QUERY_KINDS", "query_catalog", "render_query_text"]

QUERY_KINDS = (
    "concept",
    "table",
    "column",
    "identifier",
    "attribute",
    "related",
    "carriers",
    "scope",
)
CONCEPTS_DIR = "concepts"


def query_catalog(document: Mapping, kind: str, term: str) -> dict:
    if kind not in QUERY_KINDS:
        raise ValueError(f"unknown query kind {kind!r}; one of {', '.join(QUERY_KINDS)}")
    view = CatalogView(document)
    answer = {
        "concept": _concept_matches,
        "table": _table_matches,
        "column": _column_matches,
        "identifier": _identifier_matches,
        "attribute": _attribute_matches,
        "related": _related_matches,
        "carriers": _carrier_matches,
        "scope": query_scopes,
    }[kind]
    return {"query": {"kind": kind, "term": term}, "matches": answer(view, term)}


def _fold(text) -> str:
    return str(text).strip().casefold()


def _ref(view: CatalogView, object_id: str) -> dict:
    return {"id": object_id, "name": view.name(object_id)}


def _first_level(candidates: list, term: str, levels) -> list[tuple[dict, str]]:
    """The candidates the first matching level finds, each with that level's name."""
    key = _fold(term)
    for matched_by, values in levels:
        found = [c for c in candidates if key in {_fold(v) for v in values(c)}]
        if found:
            return [(c, matched_by) for c in found]
    return []


def _by_term(view: CatalogView, term: str, index: Mapping) -> list:
    refs = [t["refers_to"] for t in view.terms if _fold(t["term"]) == _fold(term)]
    return [index[ref] for ref in dict.fromkeys(refs) if ref in index]


# ---------------------------------------------------------------- concept


def find_concepts(view: CatalogView, term: str) -> list[tuple[dict, str]]:
    levels = (
        ("id", lambda c: [c["id"]]),
        ("name", lambda c: [c["name"]]),
        ("synonym", lambda c: c["synonyms"]),
    )
    found = _first_level(list(view.concepts.values()), term, levels)
    return found or [(c, "term") for c in _by_term(view, term, view.concepts)]


def _concept_matches(view: CatalogView, term: str) -> list[dict]:
    return [_concept_answer(view, c, matched_by) for c, matched_by in find_concepts(view, term)]


def _concept_answer(view: CatalogView, concept: dict, matched_by: str) -> dict:
    primary = concept.get("primary_identifier")
    states = (concept.get("states") or {}).get("values") or []
    answer = {
        "id": concept["id"],
        "matched_by": matched_by,
        "name": concept["name"],
        "kind": concept["kind"],
        "definition": concept.get("definition"),
        "domain": _ref(view, concept["domain"]),
        "status": concept["status"],
        "source": concept["source"],
        "synonyms": list(concept["synonyms"]),
        "identifiers": [
            {"id": i["id"], "name": i["name"], "primary": i["id"] == primary}
            for i in view.identifiers_of(concept["id"])
        ],
        "attributes": [
            {"id": a["id"], "name": a["name"], "category": a["category"]}
            for a in concept.get("attributes") or []
        ],
        "states": [state["name"] for state in states],
        "tables": _tables(view, concept["id"]),
        "page": f"{CONCEPTS_DIR}/{concept_filename(concept['id'])}",
    }
    return answer


def _tables(view: CatalogView, concept_id: str) -> list[dict]:
    return [{"table": r["table"], "kind": r["kind"]} for r in view.representations_of(concept_id)]


# ------------------------------------------------------------ table/column


def _table_matches(view: CatalogView, term: str) -> list[dict]:
    rep = view.representations.get(catalog_table_name(term))
    if rep is None:
        return []
    keys = (
        "kind",
        "grain",
        "time",
        "refresh",
        "scope",
        "table_status",
        "replaced_by",
        "status",
        "notes",
    )
    answer = {"table": rep["table"], "concept": _ref(view, rep["concept"])}
    answer.update({key: rep[key] for key in keys if key in rep})
    hint = usage_hint(rep)
    if hint:
        answer["usage"] = hint
    answer["columns"] = [_column(view, rep, binding) for binding in rep["bindings"]]
    answer["constraints"] = rules_citing(view, rep["table"])
    evidence = view.rep_evidence(rep["table"])
    if evidence:
        answer["evidence"] = evidence
    return [answer]


def _column(view: CatalogView, rep: dict, binding: dict) -> dict:
    """One bound column: what it binds to, its code map, derivation and evidence."""
    answer = {"column": binding["column"], "to": binding["to"]}
    if binding.get("ref"):
        answer.update(ref=binding["ref"], ref_name=view.name(binding["ref"]))
    if binding["to"] == "foreign_attribute":
        answer.update(via=binding["via"], concept=_owner(view, binding["ref"]))
    if binding.get("self_reference"):
        owner = _owner(view, binding["ref"]) or {}
        answer["self_reference"] = True
        answer["self_relations"] = [
            {"id": r["id"], "name": r["name"]} for r in view.self_relations_of(owner.get("id"))
        ]
    for key in ("code_map", "derivation"):
        if key in binding:
            answer[key] = binding[key]
    evidence = view.binding_evidence(rep["table"], binding["column"])
    if evidence:
        answer["evidence"] = evidence
    return answer


def _owner(view: CatalogView, ref: str) -> dict | None:
    """The concept an attribute belongs to, or the one an identifier identifies."""
    if ref in view.attributes:
        return _ref(view, view.attributes[ref][1]["id"])
    if ref in view.identifiers:
        return _ref(view, view.identifiers[ref]["identifies"])
    return None


def _column_matches(view: CatalogView, term: str) -> list[dict]:
    table_part, _, column = str(term).strip().rpartition(".")
    table = catalog_table_name(table_part)
    rep = view.representations.get(table)
    bound = [b for b in (rep or {}).get("bindings") or [] if b["column"] == column]
    if bound:
        return [_bound_column(view, rep, binding) for binding in bound]
    return [
        {"table": table, "column": column, "spelling_of": _ref(view, identifier["id"])}
        for identifier in view.identifiers.values()
        if any(_spells(s, table, column) for s in identifier["spellings"])
    ]


def _bound_column(view: CatalogView, rep: dict, binding: dict) -> dict:
    answer = {"table": rep["table"], **_column(view, rep, binding)}
    owner = _owner(view, binding.get("ref") or "")
    if owner:
        answer["concept"] = owner
    return answer


def _spells(spelling: Mapping, table: str, column: str) -> bool:
    return spelling["column"] == column and spelling.get("table") in (None, table)


# ------------------------------------------------------------- identifier


def _identifier_matches(view: CatalogView, term: str) -> list[dict]:
    levels = (("id", lambda i: [i["id"]]), ("name", lambda i: [i["name"]]))
    found = _first_level(list(view.identifiers.values()), term, levels)
    if not found:
        table_part, _, column = str(term).strip().rpartition(".")
        table = catalog_table_name(table_part) if table_part else None
        found = [
            (identifier, "spelling")
            for identifier in view.identifiers.values()
            if any(_spelled_as(s, table, column) for s in identifier["spellings"])
        ]
    return [_identifier_answer(view, identifier, how) for identifier, how in found]


def _spelled_as(spelling: Mapping, table, column: str) -> bool:
    if spelling["column"] != column:
        return False
    return table is None or spelling.get("table") in (None, table)


def _identifier_answer(view: CatalogView, identifier: dict, matched_by: str) -> dict:
    keys = ("scope", "arises_when", "spellings", "maps_to", "format", "status", "notes")
    answer = {
        "id": identifier["id"],
        "matched_by": matched_by,
        "name": identifier["name"],
        "identifies": _ref(view, identifier["identifies"]),
    }
    answer.update({key: identifier[key] for key in keys if key in identifier})
    answer["bound_columns"] = [
        {"table": rep["table"], "column": binding["column"], "to": binding["to"]}
        for rep, binding in view.bindings_of(identifier["id"])
    ]
    return answer


# -------------------------------------------------------------- attribute


def _attribute_matches(view: CatalogView, term: str) -> list[dict]:
    attributes = [attribute for attribute, _ in view.attributes.values()]
    levels = (("id", lambda a: [a["id"]]), ("name", lambda a: [a["name"]]))
    found = _first_level(attributes, term, levels)
    if not found:
        index = {key: attribute for key, (attribute, _) in view.attributes.items()}
        found = [(attribute, "term") for attribute in _by_term(view, term, index)]
    return [_attribute_answer(view, attribute, how) for attribute, how in found]


def _attribute_answer(view: CatalogView, attribute: dict, matched_by: str) -> dict:
    keys = ("definition", "category", "type", "unit", "derivation", "status")
    answer = {
        "id": attribute["id"],
        "matched_by": matched_by,
        "name": attribute["name"],
        "concept": _ref(view, view.attributes[attribute["id"]][1]["id"]),
    }
    answer.update({key: attribute[key] for key in keys if key in attribute})
    code_set = view.code_sets.get(attribute.get("code_set"))
    if code_set:
        answer["code_set"] = {"id": code_set["id"], "values": code_set["values"]}
    answer["columns"] = [
        {"table": rep["table"], **_column(view, rep, binding)}
        for rep, binding in view.bindings_of(attribute["id"])
    ]
    return answer


# ---------------------------------------------------------------- related


def _related_matches(view: CatalogView, term: str) -> list[dict]:
    return [_neighbourhood(view, concept) for concept, _ in find_concepts(view, term)]


def _neighbourhood(view: CatalogView, concept: dict) -> dict:
    concept_id = concept["id"]
    relations = view.relations_of(concept_id)
    answer = {
        "concept": _ref(view, concept_id),
        "relations": [
            _relation(view, concept_id, r) for r in relations if r["kind"] != "participation"
        ],
        "events": [
            _participation(view, r, r["from"])
            for r in relations
            if r["kind"] == "participation" and r["to"] == concept_id
        ],
        "roles": [
            {"id": role["id"], "name": role["name"], "condition": role["condition"]}
            for role in view.roles_played_by(concept_id)
        ],
        "tables": _tables(view, concept_id),
        "carriers": _carriers(view, concept_id),
    }
    if concept["kind"] == "event":
        answer["participants"] = [
            _participation(view, r, r["to"])
            for r in relations
            if r["kind"] == "participation" and r["from"] == concept_id
        ]
    if concept.get("player"):
        answer["player"] = _ref(view, concept["player"])
    return answer


def _carrier_matches(view: CatalogView, term: str) -> list[dict]:
    return [_carrier_answer(view, concept) for concept, _ in find_concepts(view, term)]


def _carrier_answer(view: CatalogView, concept: dict) -> dict:
    answer = {
        "concept": _ref(view, concept["id"]),
        "identifiers": [_ref(view, i["id"]) for i in view.identifiers_of(concept["id"])],
        "tables": _carriers(view, concept["id"]),
    }
    if concept.get("player"):
        answer["player"] = _ref(view, concept["player"])
    return answer


def _carriers(view: CatalogView, concept_id: str) -> list[dict]:
    return [
        {
            "table": rep["table"],
            "concept": _ref(view, rep["concept"]),
            "columns": [_carrier_column(view, binding) for binding in bindings],
        }
        for rep, bindings in view.carriers_of(concept_id)
    ]


def _carrier_column(view: CatalogView, binding: dict) -> dict:
    column = {
        "column": binding["column"],
        "identifier": _ref(view, binding["ref"]),
        "to": binding["to"],
    }
    if binding.get("self_reference"):
        column["self_reference"] = True
    return column


def _relation(view: CatalogView, concept_id: str, relation: dict) -> dict:
    other = relation["to"] if relation["from"] == concept_id else relation["from"]
    joins = view.relation_joins(relation["id"])
    return {
        "id": relation["id"],
        "kind": relation["kind"],
        "reading": reading_text(view, concept_id, relation),
        "other": _ref(view, other),
        "cardinality": relation["cardinality"],
        "joins": joins["count"] if joins else None,
        **_backing(view, relation),
    }


def _participation(view: CatalogView, relation: dict, other: str) -> dict:
    joins = view.relation_joins(relation["id"])
    key = "event" if other == relation["from"] else "concept"
    return {
        key: _ref(view, other),
        "role_name": relation["name"],
        "tables": len(view.representations_of(other)),
        "joins": joins["count"] if joins else None,
        **_backing(view, relation),
    }


def _backing(view: CatalogView, relation: dict) -> dict:
    """What the catalog itself says about where the relation lives, JOINs or not."""
    return {
        "carried_together": view.carried_together(relation),
        "evidence": list(relation.get("evidence") or []),
    }
