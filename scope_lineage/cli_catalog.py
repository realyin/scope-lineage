"""The ``scope-lineage catalog`` subcommand: ``validate``, ``build``, ``render``, ``query``,
``context``, ``search``, ``check-sql``.

``digest`` and ``merge``, which draft a catalog from table semantics, live in
``cli_catalog_draft``; ``pending``, which keeps the definitions an agent found missing for
the catalog's owner, lives in ``cli_catalog_pending``.

Kept out of ``cli.py`` like the other corpus commands. Its first input is a catalog
directory a person maintains; ``build`` may also read a lineage corpus and a table-card
file and attach what they show as evidence. This module is where the two meet: the
``catalog`` package reads no lineage artifact and ``render`` reads no catalog file, so
the composition happens here, at the command line, and neither package imports the
other. ``check-sql`` is the same composition for a hand-written query: the parser
(``scope.query_facts``) turns it into plain facts and ``render.catalog_sql_check`` compares
them with the built document. ``build`` checks what it built against the ``ontology-json/3`` schema before it
writes. Exit codes: 0 success (warnings allowed), 1 the catalog has errors, the built
document does not fit its schema, or a query found nothing, 2 an input could not be read.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .catalog import (
    CatalogError,
    build_ontology,
    load_catalog,
    ontology_findings,
    render_summary,
    validate_catalog,
)
from .cli_catalog_draft import add_draft_parsers, run_digest, run_merge
from .cli_catalog_pending import add_pending_parser, run_pending

ONTOLOGY_FILENAME = "ontology.json"


def add_catalog_parser(subcommands) -> None:
    catalog_cmd = subcommands.add_parser(
        "catalog",
        help=(
            "Validate a concept-first ontology catalog (catalog-yaml/1), build it into "
            "ontology-json/3 with optional corpus evidence, render concept pages, query it; "
            "draft it from table semantics (digest, merge)"
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
    _add_context_parser(actions)
    _add_search_parser(actions)
    _add_check_sql_parser(actions)
    add_pending_parser(actions)
    add_draft_parsers(actions)


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


def _add_search_parser(actions) -> None:
    from .render.catalog_search import SEARCH_KINDS

    search_cmd = actions.add_parser(
        "search",
        help=(
            "From a business word or a whole question to the catalog's own names: rank "
            "concepts, metrics, attributes, identifiers, code sets and tables against the "
            "text and print the best few to choose from; exit 1 when nothing is close"
        ),
    )
    search_cmd.add_argument("ontology", help=f"An {ONTOLOGY_FILENAME} written by `catalog build`")
    search_cmd.add_argument("text", help="A word, a column name or a question")
    search_cmd.add_argument(
        "--semantics",
        help="A directory of table-semantics documents: also match what each table says it is",
    )
    search_cmd.add_argument(
        "--kind", action="append", choices=SEARCH_KINDS, default=None,
        help="Only this kind of object (repeatable); every kind by default",
    )
    search_cmd.add_argument("--limit", type=int, default=10, help="How many hits (default 10)")
    search_cmd.add_argument(
        "--json", action="store_true", help="Print {query, hits[]} instead of text"
    )


def _add_check_sql_parser(actions) -> None:
    check_cmd = actions.add_parser(
        "check-sql",
        help=(
            "Check a hand-written SELECT against a built ontology.json: tables the catalog "
            "does not know, columns a table does not have, joins the catalog does not record, "
            "partition filters left out, sums inflated by a one-to-many join, code values "
            "outside a code set; exit 1 on an error or a warning, 2 when the SQL does not parse"
        ),
    )
    check_cmd.add_argument("ontology", help=f"An {ONTOLOGY_FILENAME} written by `catalog build`")
    check_cmd.add_argument("sql", help="A file of one or more SELECT statements, or - for stdin")
    check_cmd.add_argument(
        "--json", action="store_true", help="Print the catalog-sql-check/1 JSON instead of text"
    )


def _add_context_parser(actions) -> None:
    context_cmd = actions.add_parser(
        "context",
        help=(
            "Everything one question needs about a few tables, columns and concepts, in one "
            "answer: from ontology.json the keys, time columns, join targets, constraints and "
            "metrics; from the table-semantics documents how to read each table, what it is "
            "not for, what to watch and its open questions; exit 1 when nothing matches"
        ),
    )
    context_cmd.add_argument("ontology", help=f"An {ONTOLOGY_FILENAME} written by `catalog build`")
    context_cmd.add_argument(
        "--semantics",
        help=(
            "A directory of table-semantics documents (<db.table>.json); without it every "
            "table says it has no semantics document"
        ),
    )
    context_cmd.add_argument(
        "--table", action="append", default=[], metavar="DB.TABLE",
        help="A table to pack: catalog facts, how to read it, one line a column (repeatable)",
    )
    context_cmd.add_argument(
        "--column", action="append", default=[], metavar="DB.TABLE.COLUMN",
        help="A column to answer in full: binding, code values, derivation, notes (repeatable)",
    )
    context_cmd.add_argument(
        "--columns", action="append", default=[], metavar="COL[,COL...]",
        help=(
            "Columns of the --table values, comma-separated, each answered in full like "
            "--column in the same pack: a bare name goes to every requested table that has "
            "the column (bound in the catalog or in its semantics document), table.col pins "
            "one (repeatable; needs a --table)"
        ),
    )
    context_cmd.add_argument(
        "--brief", action="store_true",
        help=(
            "A short table pack: every catalog fact, how to read it, not-for, watch items and "
            "open questions stay; columns are listed by name, cited rules without their SQL, "
            "downstream readers by name"
        ),
    )
    context_cmd.add_argument(
        "--focus", action="store_true",
        help=(
            "Narrow each table's watch items, open questions and cited rules to its requested "
            "columns (--column/--columns); items that name no column are always kept, and the "
            "pack says how many were left out"
        ),
    )
    context_cmd.add_argument(
        "--concept", action="append", default=[], metavar="CONCEPT",
        help=(
            "A concept by id, name, synonym or term, or a metric by id or name (packs the "
            "metric's concept, that metric first): tables, constraints, metrics (repeatable)"
        ),
    )
    context_cmd.add_argument(
        "--json", action="store_true",
        help="Print the catalog-context/1 JSON instead of text",
    )


def _add_render_parser(actions) -> None:
    render_cmd = actions.add_parser(
        "render",
        help=(
            "Write the catalog's pages from a built ontology.json: index.md, "
            "identifiers.md, governance.md, scopes.md and one page per concept "
            "(a one-page overview, then seven sections as its appendix)"
        ),
    )
    render_cmd.add_argument("ontology", help=f"An {ONTOLOGY_FILENAME} written by `catalog build`")
    render_cmd.add_argument(
        "--out",
        required=True,
        help="Directory for index.md, identifiers.md, governance.md and concepts/<slug>.md",
    )
    render_cmd.add_argument(
        "--semantics",
        help=(
            "A directory of `semantic render` pages (<db.table>.md): link each table a "
            "concept page lists to its table-semantics page"
        ),
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
    if args.catalog_action == "context":
        return _run_context(args)
    if args.catalog_action == "search":
        return _run_search(args)
    if args.catalog_action == "check-sql":
        return _run_check_sql(args)
    if args.catalog_action == "pending":
        return run_pending(args)
    if args.catalog_action == "digest":
        return run_digest(args)
    if args.catalog_action == "merge":
        return run_merge(args)
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
    links = _semantic_links(args.semantics, out / CONCEPTS_DIR)
    if isinstance(links, int):
        return links
    pages = render_catalog_pages(document, links)
    for name, text in pages.items():
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    concepts = sum(1 for name in pages if name.startswith(f"{CONCEPTS_DIR}/"))
    print(f"Rendered {len(pages)} page(s) ({concepts} concept page(s)) -> {out}")
    return 0


def _semantic_links(directory, concepts: Path):
    """``db.table -> link`` from the concept pages to each rendered table-semantics page.

    The pages are found by name (``<db.table>.md``, the index aside), and each link is
    relative to ``concepts/`` so the two sets of pages can move together. None without
    the flag; the exit code for a directory that does not exist.
    """
    if not directory:
        return None
    root = Path(directory)
    if not root.is_dir():
        print(f"--semantics directory does not exist: {root}", file=sys.stderr)
        return 2
    base = os.path.relpath(root.resolve(), concepts.resolve())
    return {
        path.stem: Path(base, path.name).as_posix()
        for path in sorted(root.glob("*.md"))
        if path.name != "index.md"
    }


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


def _semantics_option(directory):
    """``{db.table: document}`` from ``--semantics``, None without it, 2 for a bad path."""
    from .cli_semantic import _semantic_documents

    if not directory:
        return None
    root = Path(directory)
    if not root.is_dir():
        print(f"--semantics directory does not exist: {root}", file=sys.stderr)
        return 2
    return _semantic_documents(root)[0]


def _run_search(args: argparse.Namespace) -> int:
    from .render.catalog_search import render_search_text, search_catalog

    document = _load_ontology(args.ontology)
    if isinstance(document, int):
        return document
    semantics = _semantics_option(args.semantics)
    if isinstance(semantics, int):
        return semantics
    result = search_catalog(document, args.text, semantics, kinds=args.kind, limit=args.limit)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_search_text(result), end="")
    return 0 if result["hits"] else 1


def _run_context(args: argparse.Namespace) -> int:
    from .render.catalog_context import context_pack, render_context_text

    if not (args.table or args.column or args.columns or args.concept):
        print("catalog context: name at least one --table, --column or --concept", file=sys.stderr)
        return 2
    if args.columns and not args.table:
        print(
            "catalog context: --columns names columns of the --table values; give at least "
            "one --table, or use --column db.table.column",
            file=sys.stderr,
        )
        return 2
    table_columns = [
        name.strip() for value in args.columns for name in value.split(",") if name.strip()
    ]
    if args.focus and not (args.column or table_columns):
        print("catalog context: --focus needs the columns to focus on (--column or --columns)",
              file=sys.stderr)
        return 2
    document = _load_ontology(args.ontology)
    if isinstance(document, int):
        return document
    semantics = _semantics_option(args.semantics)
    if isinstance(semantics, int):
        return semantics
    pack = context_pack(
        document, semantics, tables=args.table, columns=args.column, concepts=args.concept,
        table_columns=table_columns, brief=args.brief, focus=args.focus,
    )
    if args.json:
        print(json.dumps(pack, ensure_ascii=False, indent=2))
    else:
        print(render_context_text(pack), end="")
    return 0 if pack["concepts"] or pack["tables"] or pack["columns"] else 1


def _run_check_sql(args: argparse.Namespace) -> int:
    from .render.catalog_sql_check import check_sql, render_check_sql_text
    from .scope.query_facts import QueryFactsError, query_facts

    document = _load_ontology(args.ontology)
    if isinstance(document, int):
        return document
    try:
        sql = sys.stdin.read() if args.sql == "-" else Path(args.sql).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        print(f"catalog check-sql: cannot read {args.sql}: {error}", file=sys.stderr)
        return 2
    try:
        statements = query_facts(sql)
    except QueryFactsError as error:
        print(f"catalog check-sql: {error}", file=sys.stderr)
        return 2
    result = check_sql(document, statements)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_check_sql_text(result), end="")
    blocking = [f for f in result["findings"] if f["severity"] in ("error", "warning")]
    return 1 if blocking else 0


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
    findings = ontology_findings(document, ONTOLOGY_FILENAME)
    if findings:
        for finding in findings:
            print(finding.render(), file=sys.stderr)
        print(
            f"catalog: not built -- the document does not fit its schema "
            f"({len(findings)} problem(s)); this is a scope-lineage bug, please report it",
            file=sys.stderr,
        )
        return 1
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
    for code_set_id, gap in (document.get("evidence") or {}).get("code_sets", {}).items():
        print(
            f"  warning [lookup_column_missing] {code_set_id}: the table card of {gap['table']} "
            f"declares no {', '.join(gap['missing_columns'])}",
            file=sys.stderr,
        )
    return 0


def _evidence_summary(document: dict) -> str:
    inputs = document["evidence"]["inputs"]
    total = document["counts"]["representations"]
    parts = []
    if "lineage" in inputs:
        lineage = inputs["lineage"]
        relations = document["evidence"]["relations"].values()
        joined = sum(1 for entry in relations if (entry.get("joins") or {}).get("count"))
        sourced = sum(1 for entry in relations if "source_joins" in entry)
        parts.append(
            f"lineage {lineage['tasks']} task(s), {lineage['representations_matched']} of "
            f"{total} representation(s) matched, {joined} of "
            f"{lineage['relations_checked']} relation(s) backed by a JOIN between catalog "
            f"tables, {sourced} relation(s) by a JOIN inside a producing task"
        )
    if "tables" in inputs:
        tables = inputs["tables"]
        parts.append(
            f"tables {tables['cards']} card(s), {tables['representations_matched']} of "
            f"{total} representation(s) matched"
        )
    return "; ".join(parts)
