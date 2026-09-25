"""The catalog's vocabulary: formats, file kinds, what a load produces, what a check reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, NamedTuple, Optional

CATALOG_FORMAT = "catalog-yaml/1"
ONTOLOGY_FORMAT = "ontology-json/3"
REPORT_FORMAT = "catalog-report/1"

MANIFEST_STEM = "catalog"
MANIFEST_SCHEMA = "catalog-manifest"
ONTOLOGY_SCHEMA = "ontology-v3"


class FileKind(NamedTuple):
    """One kind of catalog file: where it lives, the list it holds, its schema."""

    name: str
    list_key: str
    schema: str
    directory: bool


FILE_KINDS: dict[str, FileKind] = {
    kind.name: kind
    for kind in (
        FileKind("domains", "domains", "catalog-domains", False),
        FileKind("identifiers", "identifiers", "catalog-identifiers", False),
        FileKind("code_sets", "code_sets", "catalog-code-sets", False),
        FileKind("concepts", "concepts", "catalog-concepts", True),
        FileKind("relations", "relations", "catalog-relations", False),
        FileKind("constraints", "constraints", "catalog-constraints", False),
        FileKind("terms", "terms", "catalog-terms", False),
        FileKind("mapping", "representations", "catalog-mapping", True),
    )
}

# The id prefix each object type must carry (spec: "前缀与对象类型一致").
ID_PREFIX = {
    "domain": "domain",
    "identifier": "id",
    "code_set": "code",
    "concept": "concept",
    "attribute": "attr",
    "relation": "rel",
    "constraint": "cons",
}


class CatalogError(Exception):
    """The catalog cannot be read at all (as opposed to read and found wanting)."""


@dataclass(frozen=True)
class Finding:
    """One error or warning: which rule, in which file, about what, and why."""

    rule: str
    file: Optional[str]
    at: Optional[str]
    message: str

    def to_dict(self) -> dict:
        return {"rule": self.rule, "file": self.file, "at": self.at, "message": self.message}

    def render(self) -> str:
        where = " ".join(part for part in (self.file, self.at) if part)
        return f"[{self.rule}] {where}: {self.message}" if where else f"[{self.rule}] {self.message}"


@dataclass(frozen=True)
class Document:
    """One parsed catalog file other than the manifest."""

    kind: str
    file: str
    data: object


@dataclass
class Catalog:
    root: Path
    manifest: object
    manifest_file: str
    documents: list[Document] = field(default_factory=list)
    problems: list[Finding] = field(default_factory=list)
    unknown_files: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        if isinstance(self.manifest, dict) and isinstance(self.manifest.get("name"), str):
            return self.manifest["name"]
        return self.root.name

    def records(self, kind: str) -> Iterator[tuple[str, dict]]:
        """Every object of one file kind as ``(file, object)``, in file order.

        Defensive on purpose: a document that failed its schema may hold anything, and
        counting must still work on it.
        """
        list_key = FILE_KINDS[kind].list_key
        for document in self.documents:
            if document.kind != kind or not isinstance(document.data, dict):
                continue
            items = document.data.get(list_key)
            for item in items if isinstance(items, list) else []:
                if isinstance(item, dict):
                    yield document.file, item


@dataclass
class ValidationReport:
    catalog: str
    errors: list[Finding]
    warnings: list[Finding]
    counts: dict
    references_checked: bool

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "doc_format": REPORT_FORMAT,
            "catalog": self.catalog,
            "ok": self.ok,
            "references_checked": self.references_checked,
            "errors": [finding.to_dict() for finding in self.errors],
            "warnings": [finding.to_dict() for finding in self.warnings],
            "counts": self.counts,
        }
