"""The ontology catalog (``catalog-yaml/1``): the concept-first source of truth.

A catalog is a directory people maintain -- domains, identifiers, code sets, concepts
(entities, events, roles with their attributes and states), relations, constraints,
terms, and the mapping of tables and columns onto them. This package reads it
(``load_catalog``), checks it (``validate_catalog``) and normalises it into one
``ontology-json/3`` document (``build_ontology``). For drafting, it condenses
table-semantics documents into material (``digest_tables``) and merges
``catalog-fragment/1`` files into a catalog (``merge_fragments``). It reads no lineage
artifact and imports nothing from the rest of the package: the catalog comes first,
evidence is attached to it later.
"""

from .build import build_ontology, ontology_findings, validate_ontology_document
from .coverage import render_coverage, table_coverage
from .digest import DIGEST_FORMAT, digest_tables, render_digest_markdown
from .fragment import FRAGMENT_FORMAT, check_fragment
from .loader import load_catalog
from .merge import MergeResult, base_problems, merge_fragments, write_documents
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
    "DIGEST_FORMAT",
    "FRAGMENT_FORMAT",
    "ONTOLOGY_FORMAT",
    "REPORT_FORMAT",
    "Catalog",
    "CatalogError",
    "Finding",
    "MergeResult",
    "ValidationReport",
    "base_problems",
    "build_ontology",
    "check_fragment",
    "digest_tables",
    "load_catalog",
    "merge_fragments",
    "ontology_findings",
    "render_coverage",
    "render_digest_markdown",
    "render_summary",
    "table_coverage",
    "validate_catalog",
    "validate_ontology_document",
    "write_documents",
]
