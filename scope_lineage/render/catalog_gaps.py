"""What one concept's catalog entry still lacks, and where the evidence disagrees with it.

Section A7 of every concept page and the whole of ``governance.md`` read these. A gap is
something a reviewer can act on: an object still ``drafted``, a column nobody bound, an
attribute no table carries, a state or coded attribute without its values, a concept with
no table at all -- and, once ``catalog build`` merged evidence, a grain the SQL does not
prove, a bound column nobody uses, a relation no JOIN in the corpus backs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .catalog_view import CONFIDENCE_TEXT, CatalogView
from .markdown_text import expr_span


@dataclass
class ConceptGaps:
    drafted: int = 0
    total: int = 0
    no_representation: bool = False
    unmapped_columns: list = field(default_factory=list)
    unbound_attributes: list = field(default_factory=list)
    missing_codes: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    declared_only: list = field(default_factory=list)
    unjoined_relations: list = field(default_factory=list)


def concept_gaps(view: CatalogView, concept_id: str) -> ConceptGaps:
    concept = view.concepts[concept_id]
    reps = view.representations_of(concept_id)
    gaps = ConceptGaps(no_representation=not reps)
    gaps.drafted, gaps.total = _drafted(view, concept_id)
    for rep in reps:
        for binding in rep["bindings"]:
            key = f"{rep['table']}.{binding['column']}"
            if binding["to"] == "unmapped":
                gaps.unmapped_columns.append(key)
            if binding.get("ref") and view.binding_evidence(rep["table"], binding["column"]).get(
                "declared_only"
            ):
                gaps.declared_only.append(key)
        gaps.conflicts += [
            (rep["table"], c) for c in view.rep_evidence(rep["table"]).get("conflicts") or []
        ]
    for attribute in concept.get("attributes") or []:
        if not view.bindings_of(attribute["id"]):
            gaps.unbound_attributes.append(attribute["id"])
        if _lacks_codes(view, attribute):
            gaps.missing_codes.append(attribute["id"])
    gaps.unjoined_relations = [
        r["id"]
        for r in view.relations_of(concept_id)
        if (view.relation_joins(r["id"]) or {}).get("count") == 0
    ]
    return gaps


def _drafted(view: CatalogView, concept_id: str) -> tuple[int, int]:
    """``(drafted, all)`` over every object that says something about the concept."""
    concept = view.concepts[concept_id]
    reps = view.representations_of(concept_id)
    objects = [
        concept,
        *(concept.get("attributes") or []),
        *view.identifiers_of(concept_id),
        *reps,
        *(binding for rep in reps for binding in rep["bindings"]),
        *view.relations_of(concept_id),
        *view.constraints_on(concept_id),
    ]
    return sum(1 for obj in objects if obj.get("status") == "drafted"), len(objects)


def _lacks_codes(view: CatalogView, attribute: dict) -> bool:
    """A state or coded attribute whose values the catalog does not list."""
    if attribute.get("category") != "state" and "code_set" not in attribute:
        return False
    code_set = view.code_sets.get(attribute.get("code_set"))
    return not (code_set and code_set.get("values"))


def share_text(drafted: int, total: int) -> str:
    percent = round(100 * drafted / total) if total else 0
    return f"{drafted}/{total}（{percent}%）"


def conflict_text(view: CatalogView, table: str, conflict: dict) -> str:
    """One disagreement between the catalog and the corpus, as one sentence."""
    proof = view.rep_evidence(table).get("grain_proof") or {}
    keys = "、".join(expr_span(key) for key in proof.get("keys") or []) or "无键"
    if conflict["rule"] == "grain_not_proven":
        confidence = CONFIDENCE_TEXT.get(str(conflict.get("confidence")), "无")
        return f"{expr_span(table)}：目录声明粒度已证明，血缘只到{confidence}（{keys}）"
    declared = "、".join(expr_span(key) for key in conflict.get("declared") or [])
    proven = "、".join(expr_span(key) for key in conflict.get("proven") or [])
    return f"{expr_span(table)}：目录声明粒度 {declared}，血缘证明的是 {proven}"
