"""The ``scope-lineage catalog`` subcommand: ``validate``, ``build``, ``render``, ``query``.

Kept out of ``cli.py`` like the other corpus commands. Its first input is a catalog
directory a person maintains; ``build`` may also read a lineage corpus and a table-card
file and attach what they show as evidence. This module is where the two meet: the
``catalog`` package reads no lineage artifact and ``render`` reads no catalog file, so
the composition happens here, at the command line, and neither package imports the
other. Exit codes: 0 success (warnings allowed), 1 the catalog has errors or a query found
nothing, 2 an input could not be read.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .catalog import (
    CatalogError,
    build_ontology,
    load_catalog,
    render_summary,
    validate_catalog,
)

ONTOLOGY_FILENAME = "ontology.json"


def add_catalog_parser(subcommands) -> None:
    catalog_cmd = subcommands.add_parser(
        "catalog",
        help=(
            "Validate a concept-first ontology catalog (catalog-yaml/1), build it into "
            "ontology-json/3 with optional corpus evidence, render concept pages, query it"
        ),
    )
    actions = catalog_cmd.add_subparsers(dest="catalog_action", required=True)
    validate_cmd = actions.add_parser(
        "validate",
        help="Check structure, references and warnings; exit 1 when there are errors",
    )
    validate_cmd.add_argument("directory", help="The catalog directory (holds catalog.yaml)")
    validate_cmd.add_argument(
        "--json",
        action="store_true",
        help="Print the catalog-report/1 JSON (errors[], warnings[], counts) instead of text",
    )
    _add_build_parser(actions)
    _add_render_parser(actions)
    _add_query_parser(actions)


def _add_query_parser(actions) -> None:
    from .render.catalog_query import QUERY_KINDS

    query_cmd = actions.add_parser(
        "query",
        help=(
            "Answer one question from a built ontology.json: a concept, a table, a column, "
            "an identifier, an attribute, or a concept's one-hop neighbours; exit 1 when "
            "nothing matches"
        ),
    )
    query_cmd.add_argument("ontology", help=f"An {ONTOLOGY_FILENAME} written by `catalog build`")
    query_cmd.add_argument("kind", choices=QUERY_KINDS, help="What the term names")
    query_cmd.add_argument(
        "term",
        help=(
            "An id, a name, a synonym or a term; db.table for table (a catalog prefix is "
            "ignored); db.table.column for column; a spelling also finds an identifier"
        ),
    )
    query_cmd.add_argument(
        "--json",
        action="store_true",
        help="Print the structured answer ({query, matches[]}) instead of text",
    )


def _add_render_parser(actions) -> None:
    render_cmd = actions.add_parser(
        "render",
        help=(
            "Write the catalog's pages from a built ontology.json: index.md, "
            "identifiers.md, governance.md and one six-section page per concept"
        ),
    )
    render_cmd.add_argument("ontology", help=f"An {ONTOLOGY_FILENAME} written by `catalog build`")
    render_cmd.add_argument(
        "--out",
        required=True,
        help="Directory for index.md, identifiers.md, governance.md and concepts/<slug>.md",
    )


def _add_build_parser(actions) -> None:
    build_cmd = actions.add_parser(
        "build",
        help=f"Validate, then write {ONTOLOGY_FILENAME} (ontology-json/3); refuses on errors",
    )
    build_cmd.add_argument("directory", help="The catalog directory (holds catalog.yaml)")
    build_cmd.add_argument("--out", required=True, help=f"Directory for {ONTOLOGY_FILENAME}")
    build_cmd.add_argument(
        "--lineage",
        help=(
            "Also attach corpus evidence: one lineage.json, or a directory searched "
            "recursively for lineage.json (the tasks writing each table, their schedule, "
            "one hop of table lineage, the grain the SQL proves, each bound column's "
            "sources and expression, the JOINs behind each relation)"
        ),
    )
    build_cmd.add_argument(
        "--tables",
        help=(
            "Also attach table-card evidence from a tables.json written by "
            "`scope-lineage tables`: declared and used column counts per table, and the "
            "bindings on columns the metadata declares and no task uses"
        ),
    )


def run_catalog(args: argparse.Namespace) -> int:
    if args.catalog_action == "render":
        return _run_render(args)
    if args.catalog_action == "query":
        return _run_query(args)
    try:
        catalog = load_catalog(args.directory)
    except CatalogError as error:
        print(f"catalog: {error}", file=sys.stderr)
        return 2
    report = validate_catalog(catalog)
    if args.catalog_action == "validate":
        if args.json:
            print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(render_summary(report))
        return 0 if report.ok else 1
    if not report.ok:
        print(render_summary(report), file=sys.stderr)
        print("catalog: not built -- fix the errors above first", file=sys.stderr)
        return 1
    evidence = _evidence_inputs(args)
    if isinstance(evidence, int):
        return evidence
    return _write_ontology(catalog, Path(args.out), *evidence)


def _load_ontology(path: str):
    """A built ``ontology-json/3`` document, or the exit code (2 unreadable, 1 wrong format)."""
    from .cli import _load_corpus_document
    from .render.catalog_view import ONTOLOGY_FORMAT

    return _load_corpus_document(path, "ontology", ONTOLOGY_FORMAT)


def _run_render(args: argparse.Namespace) -> int:
    from .render.catalog_pages import CONCEPTS_DIR, render_catalog_pages

    document = _load_ontology(args.ontology)
    if isinstance(document, int):
        return document
    out = Path(args.out)
    pages = render_catalog_pages(document)
    for name, text in pages.items():
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    concepts = sum(1 for name in pages if name.startswith(f"{CONCEPTS_DIR}/"))
    print(f"Rendered {len(pages)} page(s) ({concepts} concept page(s)) -> {out}")
    return 0


def _run_query(args: argparse.Namespace) -> int:
    from .render.catalog_query import query_catalog, render_query_text

    document = _load_ontology(args.ontology)
    if isinstance(document, int):
        return document
    result = query_catalog(document, args.kind, args.term)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_query_text(result), end="")
    return 0 if result["matches"] else 1


def _evidence_inputs(args: argparse.Namespace):
    """``(lineage facts, tables document)``, either None, or the exit code of a bad flag.

    Read before anything is written, so a mistyped path leaves no half-built output.
    The corpus walk and the ``--tables`` check are the ones every corpus command uses.
    """
    from .cli import (
        _discover_lineage_documents,
        _load_contract_documents,
        _load_corpus_document,
    )
    from .render.catalog_evidence import lineage_facts
    from .render.table_cards import DOC_FORMAT as TABLES_DOC_FORMAT

    lineage = None
    if getattr(args, "lineage", None):
        found = _discover_lineage_documents(args.lineage)
        if isinstance(found, int):
            return found
        loaded = _load_contract_documents(*found, None, "catalog build")
        if isinstance(loaded, int):
            return loaded
        lineage = lineage_facts((item.document, item.diagnostics) for item in loaded.documents)
    tables = _load_corpus_document(getattr(args, "tables", None), "--tables", TABLES_DOC_FORMAT)
    if isinstance(tables, int):
        return tables
    return lineage, tables


def _write_ontology(catalog, out: Path, lineage=None, tables=None) -> int:
    from .render.catalog_evidence import attach_evidence

    document = attach_evidence(build_ontology(catalog), lineage=lineage, tables=tables)
    out.mkdir(parents=True, exist_ok=True)
    target = out / ONTOLOGY_FILENAME
    target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = document["counts"]
    print(
        f"Built {document['doc_format']} from catalog {catalog.name}: "
        f"{counts['concepts']} concept(s), {counts['relations']} relation(s) "
        f"({counts['derived_relations']} derived), {counts['representations']} "
        f"representation(s) -> {target}"
    )
    if "evidence" in document:
        print(f"  evidence: {_evidence_summary(document)}")
    return 0


def _evidence_summary(document: dict) -> str:
    inputs = document["evidence"]["inputs"]
    total = document["counts"]["representations"]
    parts = []
    if "lineage" in inputs:
        lineage = inputs["lineage"]
        joined = sum(
            1 for entry in document["evidence"]["relations"].values() if entry["joins"]["count"]
        )
        parts.append(
            f"lineage {lineage['tasks']} task(s), {lineage['representations_matched']} of "
            f"{total} representation(s) matched, {joined} of "
            f"{lineage['relations_checked']} relation(s) backed by a JOIN"
        )
    if "tables" in inputs:
        tables = inputs["tables"]
        parts.append(
            f"tables {tables['cards']} card(s), {tables['representations_matched']} of "
            f"{total} representation(s) matched"
        )
    return "; ".join(parts)
