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
        "metrics": _count(catalog, "metrics"),
        "terms": _count(catalog, "terms"),
        "representations": len(representations),
        "bindings": sum(_length(rep.get("bindings")) for rep in representations),
        "status": status_counts(catalog),
        "density": density(catalog, concepts),
    }


def density(catalog: Catalog, concepts: list[dict]) -> dict:
    """How much meaning the catalog carries beyond its shape: coverage ratios (``count`` of
    ``total``, ``ratio`` rounded to two places, null over nothing) and plain counts.

    Units are counted over measures, the attributes a unit belongs to; derivations over
    every attribute (the attribute is where the catalog writes one); code-set values over
    every code set; definitions over the declared relations.
    """
    attributes = [a for concept in concepts for a in _dicts(concept.get("attributes"))]
    measures = [a for a in attributes if a.get("category") == "measure"]
    code_sets = [code_set for _file, code_set in catalog.records("code_sets")]
    relations = [relation for _file, relation in catalog.records("relations")]
    constraints = [constraint for _file, constraint in catalog.records("constraints")]
    return {
        "attribute_unit": _coverage(measures, "unit"),
        "attribute_derivation": _coverage(attributes, "derivation"),
        "code_set_values": _coverage(code_sets, "values"),
        "relation_definition": _coverage(relations, "definition"),
        "states": sum(1 for concept in concepts if isinstance(concept.get("states"), dict)),
        "roles": sum(1 for concept in concepts if concept.get("kind") == "role"),
        "metrics": _count(catalog, "metrics"),
        "constraints": len(constraints),
        "constraints_with_rules": sum(1 for c in constraints if c.get("rules")),
    }


def _coverage(objects: list[dict], key: str) -> dict:
    count = sum(1 for obj in objects if _filled(obj.get(key)))
    total = len(objects)
    return {"count": count, "total": total, "ratio": round(count / total, 2) if total else None}


def _filled(value) -> bool:
    return bool(value.strip()) if isinstance(value, str) else bool(value)


def _dicts(value) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _count(catalog: Catalog, kind: str) -> int:
    return sum(1 for _ in catalog.records(kind))


def _length(value) -> int:
    return len(value) if isinstance(value, list) else 0
