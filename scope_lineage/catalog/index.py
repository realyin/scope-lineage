"""Every id in a structurally valid catalog, with its type, and the two id-level rules.

Built once, read by every reference rule. When an id is declared twice the first
declaration in path order is the one indexed; the second is reported (``duplicate_id``)
and otherwise ignored, so one duplicate does not fan out into a page of reference errors.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Optional

from .model import ID_PREFIX, Catalog, Finding

# Which file kind holds which object type (attributes live inside concepts).
_TYPE_OF_KIND = {
    "domains": "domain",
    "identifiers": "identifier",
    "code_sets": "code_set",
    "concepts": "concept",
    "relations": "relation",
    "constraints": "constraint",
}


@dataclass(frozen=True)
class Entry:
    type: str
    obj: dict
    file: str
    owner: Optional[str] = None  # the concept an attribute belongs to


@dataclass
class Index:
    entries: dict[str, Entry] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    # Every binding of every representation, in file order (read by R1 only).
    bindings: list[dict] = field(default_factory=list, repr=False)
    _attributes: Optional[dict] = field(default=None, repr=False)
    _identified: Optional[dict] = field(default=None, repr=False)

    def get(self, object_id) -> Optional[Entry]:
        return self.entries.get(object_id) if isinstance(object_id, str) else None

    def is_type(self, object_id, *types: str) -> bool:
        entry = self.get(object_id)
        return entry is not None and entry.type in types

    def concept_kind(self, object_id) -> Optional[str]:
        entry = self.get(object_id)
        return entry.obj.get("kind") if entry and entry.type == "concept" else None

    def of_type(self, object_type: str) -> list[tuple[str, Entry]]:
        return [(key, e) for key, e in self.entries.items() if e.type == object_type]

    def attributes_of(self, concept_id: str) -> set[str]:
        if self._attributes is None:
            self._attributes = _group(self.of_type("attribute"), lambda e: e.owner)
        return self._attributes.get(concept_id, set())

    def identifiers_of(self, concept_id: str) -> set[str]:
        """Listed on the concept, or declaring that they identify it."""
        if self._identified is None:
            self._identified = _group(
                self.of_type("identifier"), lambda e: e.obj.get("identifies")
            )
        entry = self.get(concept_id)
        listed = set(entry.obj.get("identifiers") or []) if entry else set()
        listed = {key for key in listed if self.is_type(key, "identifier")}
        return listed | self._identified.get(concept_id, set())

    def binding_owners(self, concept_id: str) -> Optional[tuple[str, ...]]:
        """The concepts whose attributes and identifiers a representation may bind as its own.

        A role view carries its player's too: the borrower table's customer_id *is* the
        customer's identifier. ``None`` when a role's player is itself broken -- that is
        already a ``role_player`` error, and every binding would repeat it.
        """
        if self.concept_kind(concept_id) != "role":
            return (concept_id,)
        player = self.get(concept_id).obj["player"]
        return (concept_id, player) if self.concept_kind(player) == "entity" else None

    def held_code_sets(self, binding: dict) -> list[str]:
        """The code sets a column's values relate to (``holds`` says how): the binding's
        ``code_sets``, else the bound attribute's ``code_set``."""
        if binding.get("code_sets"):
            return list(binding["code_sets"])
        entry = self.get(binding.get("ref"))
        if binding["to"] in ("attribute", "foreign_attribute") and entry and entry.type == "attribute":
            return [entry.obj["code_set"]] if entry.obj.get("code_set") else []
        return []

    def attribute_code_set_ids(self, attribute_id: str) -> list[str]:
        """The attribute's code sets by rule R1 (see ``attribute_code_set_ids``)."""
        entry = self.get(attribute_id)
        if entry is None or entry.type != "attribute":
            return []
        return attribute_code_set_ids(entry.obj, self.bindings)

    def has_self_relation(self, concept_id: str) -> bool:
        """Some relation, of any kind, runs from ``concept_id`` to itself."""
        return bool(self.self_relations(concept_id))

    def self_relations(self, concept_id: str) -> list[str]:
        """The ids, sorted, of the relations running from ``concept_id`` to itself."""
        return sorted(
            key
            for key, entry in self.of_type("relation")
            if entry.obj.get("from") == concept_id and entry.obj.get("to") == concept_id
        )

    def relation_ends(self, relation_id) -> Optional[tuple[str, str]]:
        """``(from, to)`` of a declared relation, or of the participation relation an
        event's participant becomes; ``None`` when ``relation_id`` names neither."""
        if self.is_type(relation_id, "relation"):
            relation = self.get(relation_id).obj
            return relation.get("from"), relation.get("to")
        for key, entry in self.of_type("concept"):
            for participant in entry.obj.get("participants") or []:
                if derived_relation_id(key, participant.get("role_name", "")) == relation_id:
                    return key, participant.get("concept")
        return None

    def add(self, object_type: str, obj: dict, file: str, owner: str | None = None) -> None:
        object_id = obj["id"]
        _check_prefix(self, object_type, object_id, file, owner)
        if object_id in self.entries:
            first = self.entries[object_id].file
            self.findings.append(
                Finding("duplicate_id", file, object_id, f"already declared in {first}")
            )
            return
        self.entries[object_id] = Entry(object_type, obj, file, owner)


ATTRIBUTE_BINDINGS = ("attribute", "foreign_attribute")


def attribute_code_set_ids(attribute: Mapping, bindings: Iterable[Mapping]) -> list[str]:
    """Rule R1 -- the code sets an attribute's codes are in: its own ``code_set``; when it
    has none, the ``code_sets`` of every column bound to it (as ``attribute`` or
    ``foreign_attribute``), each counted once, in the order first seen.

    One answer for the whole package: validation reads it through ``Index``, pages and
    queries through ``CatalogView``. ``bindings`` may hold any bindings; only those bound
    to the attribute count. A column's own lookup order is a different question
    (``Index.held_code_sets``).
    """
    if attribute.get("code_set"):
        return [attribute["code_set"]]
    found: list[str] = []
    for binding in bindings:
        if binding.get("to") not in ATTRIBUTE_BINDINGS or binding.get("ref") != attribute.get("id"):
            continue
        for code_set_id in binding.get("code_sets") or []:
            if code_set_id not in found:
                found.append(code_set_id)
    return found


def derived_relation_id(event_id: str, role_name: str) -> str:
    """A participant becomes ``rel:<event>.<role_name>``."""
    return f"rel:{event_id.split(':', 1)[1]}.{role_name}"


def _group(entries: list[tuple[str, Entry]], key_of) -> dict[str, set[str]]:
    groups: dict[str, set[str]] = {}
    for key, entry in entries:
        groups.setdefault(key_of(entry), set()).add(key)
    return groups


def build_index(catalog: Catalog) -> Index:
    index = Index()
    for kind, object_type in _TYPE_OF_KIND.items():
        for file, obj in catalog.records(kind):
            index.add(object_type, obj, file)
            if object_type == "concept":
                for attribute in obj.get("attributes") or []:
                    index.add("attribute", attribute, file, owner=obj["id"])
    for _file, representation in catalog.records("mapping"):
        bindings = representation.get("bindings")
        if isinstance(bindings, list):
            index.bindings += [b for b in bindings if isinstance(b, dict)]
    return index


def _check_prefix(index: Index, object_type: str, object_id: str, file: str, owner) -> None:
    expected = f"{ID_PREFIX[object_type]}:"
    if owner is not None:
        expected = f"attr:{owner.split(':', 1)[1]}."
    if not object_id.startswith(expected):
        what = f"an attribute of {owner}" if owner else f"a {object_type.replace('_', ' ')}"
        index.findings.append(
            Finding("id_prefix", file, object_id, f"{what} needs an id starting {expected!r}")
        )
