"""Where a table's page sits: its domain and the concept it represents.

With a built ``ontology-json/3`` document (``--ontology``), a table the catalog lists as a
representation belongs to that concept, with that representation kind, in that concept's
domain -- the catalog wins over the document's own ``concept`` key, which is used only for
a table the catalog does not list. The concept link is ``../concepts/<slug>.md``: the
page ``catalog render`` writes, reached from a directory beside its ``concepts/``.

Without an ontology the document's ``concept`` is shown as its id, unlinked, and the
table's database stands in for the domain. No company's table-name convention is read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..render.catalog_view import (
    REPRESENTATION_KINDS,
    CatalogView,
    catalog_table_name,
    concept_filename,
)
from .names import bare_table

CONCEPTS_HREF = "../concepts"
_KIND_TEXT = dict(REPRESENTATION_KINDS)


@dataclass(frozen=True)
class ConceptRef:
    id: str
    name: Optional[str] = None
    href: Optional[str] = None
    kind: Optional[str] = None

    def heading(self) -> str:
        return f"[{self.name}]({self.href})" if self.href else f"`{self.id}`"

    def phrase(self) -> str:
        """``本表是[客户](../concepts/customer.md)的核心表``; unlinked, the id in code."""
        name = self.heading() if self.href else f" {self.heading()} "
        if self.kind:
            return f"本表是{name}的{self.kind}表"
        return f"本表表现{name}".rstrip()


@dataclass(frozen=True)
class Place:
    order: tuple
    group: str
    label: str
    concept: Optional[ConceptRef]


class Places:
    def __init__(self, ontology: Optional[dict]) -> None:
        self.view = CatalogView(ontology) if ontology else None
        self._reps = {}
        if self.view is not None:
            self._reps = {
                catalog_table_name(table).lower(): rep
                for table, rep in self.view.representations.items()
            }

    def of(self, document: dict) -> Place:
        table = bare_table(document["table"])
        concept = self._concept(table, document)
        if concept is not None and concept.href and self.view is not None:
            domain = self.view.concepts[concept.id]["domain"]
            name = self.view.name(domain)
            return Place((0, domain), name, f"域：{name}", concept)
        database = table.split(".", 1)[0]
        return Place((1, database), f"库 {database}", f"库：{database}", concept)

    def _concept(self, table: str, document: dict) -> Optional[ConceptRef]:
        rep = self._reps.get(table)
        if rep is not None:
            return self._linked(rep["concept"], rep.get("kind"))
        declared = document.get("concept")
        if not declared:
            return None
        kind = declared.get("representation_kind")
        if self.view is not None and declared["concept"] in self.view.concepts:
            return self._linked(declared["concept"], kind)
        return ConceptRef(declared["concept"], kind=_kind_text(kind))

    def _linked(self, concept_id: str, kind) -> ConceptRef:
        assert self.view is not None
        return ConceptRef(
            concept_id,
            name=self.view.name(concept_id),
            href=f"{CONCEPTS_HREF}/{concept_filename(concept_id)}",
            kind=_kind_text(kind),
        )


def _kind_text(kind) -> Optional[str]:
    return _KIND_TEXT.get(kind, kind) if kind else None
