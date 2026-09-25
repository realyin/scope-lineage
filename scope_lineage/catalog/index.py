"""Every id in a structurally valid catalog, with its type, and the two id-level rules.

Built once, read by every reference rule. When an id is declared twice the first
declaration in path order is the one indexed; the second is reported (``duplicate_id``)
and otherwise ignored, so one duplicate does not fan out into a page of reference errors.
"""

from __future__ import annotations

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
