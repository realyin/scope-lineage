"""The ``scope-lineage ontology`` subcommand: parser and runner.

Kept out of ``cli.py`` for the same reason ``tables`` and ``glossary`` are: its unit of
work is the *corpus*. It is also the one command derived on top of two other corpus
documents -- the table cards and the value dictionary -- so it accepts both as files
and builds whichever it was not given from the same corpus it just walked, in memory.
Either way each statement is profiled exactly once and all three corpus artifacts read
that one profile.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .render.ontology import build_ontology, render_ontology_index_markdown


def add_ontology_parser(subcommands) -> None:
    ontology_cmd = subcommands.add_parser(
        "ontology",
        help=(
            "Aggregate a corpus of Core artifacts into one ontology candidate: "
            "entities, relations, constraints and cross-task conflicts"
        ),
    )
    ontology_cmd.add_argument(
        "--lineage",
        required=True,
        help="One lineage.json file, or a directory searched recursively for lineage.json",
    )
    ontology_cmd.add_argument(
        "--out", required=True, help="Directory for ontology.json and ontology.md"
    )
    ontology_cmd.add_argument(
        "--tables",
        help=(
            "A tables.json written by `scope-lineage tables`; built in memory over the "
            "same corpus when it is not given"
        ),
    )
    ontology_cmd.add_argument(
        "--glossary",
        help=(
            "A glossary.json written by `scope-lineage glossary`; built in memory over "
            "the same corpus when it is not given"
        ),
    )
    ontology_cmd.add_argument(
        "--format",
        default="json,md",
        help="Comma-separated output formats: json, md (default: json,md)",
    )


def formats(value: str | None) -> set[str]:
    return {name.strip() for name in (value or "json,md").split(",") if name.strip()}


def _supplied_corpus(args: argparse.Namespace):
    """``(tables, glossary)``, either of them None, or the exit code of a bad flag."""
    from .cli import _load_corpus_document
    from .render.glossary import DOC_FORMAT as GLOSSARY_DOC_FORMAT
    from .render.table_cards import DOC_FORMAT as TABLES_DOC_FORMAT

    tables = _load_corpus_document(
        getattr(args, "tables", None), "--tables", TABLES_DOC_FORMAT
    )
    if isinstance(tables, int):
        return tables
    glossary = _load_corpus_document(
        getattr(args, "glossary", None), "--glossary", GLOSSARY_DOC_FORMAT
    )
    if isinstance(glossary, int):
        return glossary
    return tables, glossary


def run_ontology(args: argparse.Namespace) -> int:
    from .cli import _discover_lineage_documents, _load_contract_documents
    from .render.semantic_profile import build_semantic_profile

    supplied = _supplied_corpus(args)
    if isinstance(supplied, int):
        return supplied
    tables, glossary = supplied

    found = _discover_lineage_documents(args.lineage)
    if isinstance(found, int):
        return found
    loaded = _load_contract_documents(*found, args.out, "ontology builder")
    if isinstance(loaded, int):
        return loaded

    documents = [item.document for item in loaded.documents]
    profiles = []
    for item in loaded.documents:
        try:
            profiles.append(build_semantic_profile(item.document, item.diagnostics))
        except ValueError as error:
            print(f"{item.path}: {error}", file=sys.stderr)
            return 1
    ontology = build_ontology(
        documents,
        profiles,
        tables=tables,
        glossary=glossary,
        artifact_root=str(Path(args.lineage)),
    )
    _write_ontology(Path(args.out), ontology, formats(args.format))
    print(
        f"Modelled {len(ontology['entities'])} entity(ies), "
        f"{len(ontology['relations'])} relation(s), "
        f"{len(ontology['constraints'])} constraint(s) and "
        f"{len(ontology['findings'])} finding(s) from "
        f"{ontology['corpus'].get('task_count')} task(s) ({loaded.counters()})"
    )
    return 0


def _write_ontology(out: Path, ontology: dict, chosen: set[str]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    if "json" in chosen:
        (out / "ontology.json").write_text(
            json.dumps(ontology, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if "md" in chosen:
        (out / "ontology.md").write_text(
            render_ontology_index_markdown(ontology), encoding="utf-8"
        )
