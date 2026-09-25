"""``validate_catalog``: structure first, then references and warnings, then counts.

References are checked only once every file has passed its schema. A broken file would
otherwise hide its objects from the index and every reference to them would be reported
as missing -- one real error buried under many echoes.
"""

from __future__ import annotations

from collections import Counter

from .model import Catalog, ValidationReport
from .references import check_references
from .soft_checks import soft_checks, status_counts, unknown_file_warnings
from .structure import check_structure


def validate_catalog(catalog: Catalog) -> ValidationReport:
    errors = [*catalog.problems, *check_structure(catalog)]
    warnings = unknown_file_warnings(catalog)
    references_checked = not errors
    if references_checked:
        errors += check_references(catalog)
        warnings = soft_checks(catalog) + warnings
    return ValidationReport(
        catalog=catalog.name,
        errors=errors,
        warnings=warnings,
        counts=count_objects(catalog),
        references_checked=references_checked,
    )


def count_objects(catalog: Catalog) -> dict:
    concepts = [concept for _file, concept in catalog.records("concepts")]
    representations = [rep for _file, rep in catalog.records("mapping")]
    kinds = Counter(str(concept.get("kind")) for concept in concepts)
    return {
        "domains": _count(catalog, "domains"),
        "identifiers": _count(catalog, "identifiers"),
        "code_sets": _count(catalog, "code_sets"),
        "concepts": len(concepts),
        "concepts_by_kind": {kind: kinds[kind] for kind in sorted(kinds)},
        "attributes": sum(_length(concept.get("attributes")) for concept in concepts),
        "relations": _count(catalog, "relations"),
        "constraints": _count(catalog, "constraints"),
        "terms": _count(catalog, "terms"),
        "representations": len(representations),
        "bindings": sum(_length(rep.get("bindings")) for rep in representations),
        "status": status_counts(catalog),
    }


def _count(catalog: Catalog, kind: str) -> int:
    return sum(1 for _ in catalog.records(kind))


def _length(value) -> int:
    return len(value) if isinstance(value, list) else 0
