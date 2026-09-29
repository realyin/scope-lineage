"""``merge_fragments``: ``catalog-fragment/1`` items into a loaded catalog, conflicts reported.

Every item is found again by its key -- an id; a term by its words and what they refer
to; a representation by its table -- across the whole catalog and the fragments merged
before it. An equal item is counted as unchanged; a different item under the same key
is a conflict, reported and not applied, so the first one stays and nothing is chosen
silently. Attributes go into their concept wherever that concept is declared; a concept
the catalog does not have is an error and its attributes are not applied. New
representations go into ``mapping/<group>`` (an existing file of that name in whatever
form it is written, else a new file in the manifest's form); the other kinds into their
top-level file, created the same way when the catalog has none.

The merge edits the loaded documents in memory and names the files it changed;
``write_documents`` writes those back. Nothing else is rewritten, so every file a merge
does not touch keeps its comments and layout.
"""

from __future__ import annotations

import copy
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, NamedTuple

from .fragment import TOP_LEVEL
from .loader import SUFFIXES
from .model import FILE_KINDS, Catalog, Document, Finding
from .structure import check_structure

# The order kinds are counted in, in reports.
KINDS = ("attribute", "code_set", "identifier", "constraint", "term", "representation")


@dataclass
class MergeResult:
    added: Counter = field(default_factory=Counter)
    unchanged: int = 0
    conflicts: list[Finding] = field(default_factory=list)
    errors: list[Finding] = field(default_factory=list)
    changed: set[str] = field(default_factory=set)
    tables: list[str] = field(default_factory=list)
    notes: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.conflicts and not self.errors


def base_problems(catalog: Catalog) -> list[Finding]:
    """What stops a merge: a base file that does not parse or does not fit its schema."""
    return [*catalog.problems, *check_structure(catalog)]


def merge_fragments(catalog: Catalog, fragments: list[tuple[str, dict]]) -> MergeResult:
    """Merge schema-valid fragments, in order, into ``catalog``'s documents."""
    merger = _Merger(catalog)
    for file, fragment in fragments:
        merger.merge(file, fragment)
    return merger.result


class _Merger:
    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog
        self.result = MergeResult()
        self.concepts: dict[str, tuple[dict, str]] = {}
        self.attributes: dict[str, tuple[dict, str, str]] = {}
        for file, concept in catalog.records("concepts"):
            concept_id = concept.get("id")
            if not isinstance(concept_id, str) or concept_id in self.concepts:
                continue
            self.concepts[concept_id] = (concept, file)
            for attribute in _dicts(concept.get("attributes")):
                self.attributes.setdefault(attribute.get("id"), (attribute, concept_id, file))
        # kind -> key -> (the item first declared under it, the file or fragment it came from)
        self.indexes: dict[str, dict] = {}
        for kind, _name in (*TOP_LEVEL, ("mapping", "representation")):
            index = self.indexes[kind] = {}
            for file, item in catalog.records(kind):
                index.setdefault(_key(kind, item), (item, file))

    def merge(self, file: str, fragment: dict) -> None:
        group = fragment["group"]
        for concept_id, attributes in (fragment.get("attributes") or {}).items():
            self._attributes(file, concept_id, attributes)
        for kind, name in TOP_LEVEL:
            for item in fragment.get(kind) or []:
                self._add(file, kind, name, item, kind)
        for item in fragment.get("representations") or []:
            if item["table"] not in self.result.tables:
                self.result.tables.append(item["table"])
            self._add(file, "mapping", "representation", item, f"mapping/{group}")
        self.result.notes += [(group, note) for note in fragment.get("notes") or []]

    def _attributes(self, file: str, concept_id: str, attributes: list) -> None:
        found = self.concepts.get(concept_id)
        if found is None:
            self.result.errors.append(Finding(
                "unknown_concept", file, concept_id,
                f"no such concept in the catalog; its {len(attributes)} attribute(s) not applied",
            ))
            return
        concept, concept_file = found
        for attribute in attributes:
            existing = self.attributes.get(attribute["id"])
            if existing is None:
                concept.setdefault("attributes", []).append(copy.deepcopy(attribute))
                self.attributes[attribute["id"]] = (attribute, concept_id, file)
                self._applied("attribute", concept_file)
            elif existing[1] != concept_id:
                self._conflict(file, "attribute", attribute["id"],
                               f"already declared on {existing[1]} in {existing[2]}")
            elif existing[0] == attribute:
                self.result.unchanged += 1
            else:
                self._conflict(file, "attribute", attribute["id"],
                               f"differs from the one on {concept_id} in {existing[2]}")

    def _add(self, file: str, kind: str, name: str, item: dict, stem: str) -> None:
        index = self.indexes[kind]
        key = _key(kind, item)
        existing = index.get(key)
        if existing is None:
            target = self._document(kind, stem)
            target.data[FILE_KINDS[kind].list_key].append(copy.deepcopy(item))
            index[key] = (item, file)
            self._applied(name, target.file)
        elif existing[0] == item:
            self.result.unchanged += 1
        else:
            self._conflict(file, name, _label(kind, item), f"differs from the one in {existing[1]}")

    def _document(self, kind: str, stem: str) -> _Target:
        """The file ``stem`` of ``kind`` in whatever form it exists, else a new one.

        A new file takes the manifest's form: a catalog written in JSON stays JSON, and
        merging into it never needs PyYAML. The manifest rather than the files beside the
        new one, because every catalog has exactly one manifest -- a directory that mixes
        forms would otherwise need a tie-break, and the answer would hang on file order.
        """
        names = {f"{stem}{suffix}" for suffix in SUFFIXES}
        for document in self.catalog.documents:
            if document.kind == kind and document.file in names:
                return _Target(document.file, document.data)  # a dict: the base passed its schema
        suffix = Path(self.catalog.manifest_file).suffix
        document = Document(kind, f"{stem}{suffix}", {FILE_KINDS[kind].list_key: []})
        self.catalog.documents.append(document)
        return _Target(document.file, document.data)

    def _applied(self, name: str, file: str) -> None:
        self.result.added[name] += 1
        self.result.changed.add(file)

    def _conflict(self, file: str, name: str, at: str, message: str) -> None:
        self.result.conflicts.append(
            Finding("merge_conflict", file, at, f"{name} {message}; the later one is not applied")
        )


class _Target(NamedTuple):
    file: str
    data: dict


def _key(kind: str, item: dict):
    if kind == "terms":
        return (item.get("term"), item.get("refers_to"))
    if kind == "mapping":
        return str(item.get("table")).lower()
    return item.get("id")


def _label(kind: str, item: dict) -> str:
    if kind == "terms":
        return f"{item['term']} -> {item['refers_to']}"
    if kind == "mapping":
        return item["table"]
    return item["id"]


def _dicts(value) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def write_documents(catalog: Catalog, out: Path, files: Iterable[str]) -> None:
    """Write the named documents under ``out``, each in the form its suffix says."""
    by_file = {document.file: document for document in catalog.documents}
    for file in sorted(files):
        target = out / file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_dump(by_file[file].data, target.suffix), encoding="utf-8")


def _dump(data, suffix: str) -> str:
    if suffix == ".json":
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    import yaml

    # safe_dump quotes every string YAML 1.1 would read as something else (``on``,
    # ``no``, a date), so the catalog's YAML 1.2 reading gets the same text back.
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100)
