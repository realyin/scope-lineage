"""The ontology catalog (``catalog-yaml/1``): the concept-first source of truth.

A catalog is a directory people maintain -- domains, identifiers, code sets, concepts
(entities, events, roles with their attributes and states), relations, constraints,
terms, and the mapping of tables and columns onto them. This package reads it
(``load_catalog``), checks it (``validate_catalog``) and normalises it into one
``ontology-json/3`` document (``build_ontology``). It reads no lineage artifact and
imports nothing from the rest of the package: the catalog comes first, evidence is
attached to it later.
"""

from .build import build_ontology, validate_ontology_document
from .loader import load_catalog
from .model import (
    CATALOG_FORMAT,
    ONTOLOGY_FORMAT,
    REPORT_FORMAT,
    Catalog,
    CatalogError,
    Finding,
    ValidationReport,
)
from .report import render_summary
from .validate import validate_catalog

__all__ = [
    "CATALOG_FORMAT",
    "ONTOLOGY_FORMAT",
    "REPORT_FORMAT",
    "Catalog",
    "CatalogError",
    "Finding",
    "ValidationReport",
    "build_ontology",
    "load_catalog",
    "render_summary",
    "validate_catalog",
    "validate_ontology_document",
]
