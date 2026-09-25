"""The ``scope-lineage catalog`` subcommand: ``validate`` and ``build``.

Kept out of ``cli.py`` like the other corpus commands. Unlike them it reads no lineage
artifact at all: its one input is a catalog directory a person maintains. Exit codes:
0 the catalog is valid (warnings allowed), 1 it has errors, 2 it could not be read.
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
            "Validate a concept-first ontology catalog (catalog-yaml/1) or build it "
            "into ontology-json/3"
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
    build_cmd = actions.add_parser(
        "build",
        help=f"Validate, then write {ONTOLOGY_FILENAME} (ontology-json/3); refuses on errors",
    )
    build_cmd.add_argument("directory", help="The catalog directory (holds catalog.yaml)")
    build_cmd.add_argument("--out", required=True, help=f"Directory for {ONTOLOGY_FILENAME}")


def run_catalog(args: argparse.Namespace) -> int:
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
    return _write_ontology(catalog, Path(args.out))


def _write_ontology(catalog, out: Path) -> int:
    document = build_ontology(catalog)
    out.mkdir(parents=True, exist_ok=True)
    target = out / ONTOLOGY_FILENAME
    target.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    counts = document["counts"]
    print(
        f"Built {document['doc_format']} from catalog {catalog.name}: "
        f"{counts['concepts']} concept(s), {counts['relations']} relation(s) "
        f"({counts['derived_relations']} derived), {counts['representations']} "
        f"representation(s) -> {target}"
    )
    return 0
