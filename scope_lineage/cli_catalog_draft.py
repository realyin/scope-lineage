"""``scope-lineage catalog digest`` and ``catalog merge``: drafting a catalog from table semantics.

``digest`` condenses a directory of ``table-semantics/1`` documents into the material a
drafter reads (``digest.md`` + ``digest.json``), and with ``--catalog`` names the tables
and columns the catalog does not cover yet. ``merge`` copies a catalog and merges
``catalog-fragment/1`` files into the copy, then validates it and reports coverage.

Exit codes. digest: 0 written; 1 no legal document, a document was skipped, or an
``--only`` table has no document; 2 an input could not be read. merge: 0 merged and
valid (warnings allowed); 1 a fragment fails its schema or the base catalog its schemas
(nothing written), or the merge found conflicts or unknown concepts, or the merged
catalog has validation errors (written, so the errors can be read in place); 2 an input
could not be read, or ``--out`` is the base (without ``--in-place``), inside it, or not
empty.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .catalog import (
    CatalogError,
    base_problems,
    check_fragment,
    digest_tables,
    load_catalog,
    merge_fragments,
    render_coverage,
    render_digest_markdown,
    render_summary,
    table_coverage,
    validate_catalog,
    write_documents,
)
from .catalog.merge import KINDS
from .semantics.names import bare_table

DIGEST_JSON = "digest.json"
DIGEST_MD = "digest.md"


def add_draft_parsers(actions) -> None:
    digest = actions.add_parser(
        "digest",
        help=(
            "Condense table-semantics/1 documents into catalog-drafting material "
            f"({DIGEST_MD} + {DIGEST_JSON}); with --catalog, name what it does not cover"
        ),
    )
    digest.add_argument("directory", help="Directory of table-semantics/1 JSON documents")
    digest.add_argument(
        "--catalog",
        help="A catalog directory: list tables with no representation and columns with no binding",
    )
    digest.add_argument(
        "--only", nargs="+", action="extend", default=None, metavar="TABLE",
        help="Only these tables (db.table, a catalog prefix is ignored)",
    )
    digest.add_argument("--out", required=True, help=f"Directory for {DIGEST_MD} and {DIGEST_JSON}")
    merge = actions.add_parser(
        "merge",
        help=(
            "Merge catalog-fragment/1 files into a copy of a catalog, report conflicts, "
            "validate the result and report coverage; exit 1 on conflicts or errors"
        ),
    )
    merge.add_argument("base", help="The catalog directory to start from (holds catalog.yaml)")
    merge.add_argument("fragments", nargs="+", help="catalog-fragment/1 JSON files, merged in order")
    target = merge.add_mutually_exclusive_group(required=True)
    target.add_argument("--out", help="A new or empty directory for the merged catalog")
    target.add_argument(
        "--in-place", action="store_true", help="Write the merge into the base catalog itself"
    )


# ------------------------------------------------------------------ digest


def run_digest(args: argparse.Namespace) -> int:
    from .cli_semantic import _renderable_documents

    directory = Path(args.directory)
    if not directory.is_dir():
        print(f"directory does not exist: {directory}", file=sys.stderr)
        return 2
    catalog = None
    if args.catalog:
        try:
            catalog = load_catalog(args.catalog)
        except CatalogError as error:
            print(f"--catalog: {error}", file=sys.stderr)
            return 2
    documents, skipped = _renderable_documents(directory)
    if not documents:
        print(f"no table-semantics/1 document under {directory}", file=sys.stderr)
        return 1
    if args.only:
        documents = _only(documents, args.only)
        if isinstance(documents, int):
            return documents
    digest = digest_tables(documents, catalog)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / DIGEST_JSON).write_text(
        json.dumps(digest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / DIGEST_MD).write_text(render_digest_markdown(digest), encoding="utf-8")
    print(f"Digested {len(digest['tables'])} table(s) (skipped={skipped}) -> {out}")
    if "catalog" in digest:
        gaps = digest["catalog"]
        unbound = sum(len(columns) for columns in gaps["columns_without_binding"].values())
        print(
            f"  catalog {gaps['name']}: {len(gaps['tables_without_representation'])} table(s) "
            f"without a representation, {unbound} column(s) without a binding"
        )
    return 1 if skipped else 0


def _only(documents: list[dict], only: list[str]):
    wanted = {bare_table(name) for name in only}
    found = {bare_table(document["table"]) for document in documents}
    missing = sorted(wanted - found)
    if missing:
        print(f"--only: no document for {', '.join(missing)}", file=sys.stderr)
        return 1
    return [document for document in documents if bare_table(document["table"]) in wanted]


# ------------------------------------------------------------------ merge


def run_merge(args: argparse.Namespace) -> int:
    fragments = _read_fragments(args.fragments)
    if isinstance(fragments, int):
        return fragments
    base = Path(args.base)
    try:
        catalog = load_catalog(base)
    except CatalogError as error:
        print(f"catalog merge: {error}", file=sys.stderr)
        return 2
    out = base if args.in_place else Path(args.out)
    if not args.in_place and _refuse_out(base, out):
        return 2
    problems = base_problems(catalog)
    if problems:
        for finding in problems:
            print(f"error   {finding.render()}", file=sys.stderr)
        print("catalog merge: nothing merged -- fix the base catalog first", file=sys.stderr)
        return 1
    result = merge_fragments(catalog, fragments)
    if out != base:
        shutil.copytree(base, out, ignore=shutil.ignore_patterns(".*"), dirs_exist_ok=True)
    write_documents(catalog, out, result.changed)
    print(_merge_summary(len(fragments), out, result))
    merged = load_catalog(out)
    report = validate_catalog(merged)
    print(render_summary(report))
    print(render_coverage(table_coverage(merged, result.tables)))
    return 0 if result.ok and report.ok else 1


def _read_fragments(paths: list[str]):
    """``[(file, fragment)]`` in order, or the exit code: 2 unreadable, 1 not the schema."""
    fragments = []
    for name in paths:
        try:
            fragments.append((name, json.loads(Path(name).read_text(encoding="utf-8"))))
        except (OSError, ValueError) as error:
            print(f"catalog merge: {name}: not a readable JSON document ({error})", file=sys.stderr)
            return 2
    findings = [finding for name, data in fragments for finding in check_fragment(data, name)]
    for finding in findings:
        print(f"error   {finding.render()}", file=sys.stderr)
    if findings:
        print("catalog merge: nothing merged -- fix the fragment(s) first", file=sys.stderr)
        return 1
    return fragments


def _refuse_out(base: Path, out: Path) -> bool:
    base_path, out_path = base.resolve(), out.resolve()
    if out_path == base_path:
        message = "--out is the base catalog; pass --in-place to write into it"
    elif base_path in out_path.parents:
        message = "--out is inside the base catalog; choose a directory outside it"
    elif out.exists() and (not out.is_dir() or any(out.iterdir())):
        message = f"--out {out} is not empty; choose a new or empty directory"
    else:
        return False
    print(f"catalog merge: {message}", file=sys.stderr)
    return True


def _merge_summary(count: int, out: Path, result) -> str:
    added = ", ".join(f"{kind}={result.added[kind]}" for kind in KINDS if result.added[kind])
    lines = [
        f"Merged {count} fragment(s) into {out}: added {added or 'nothing'}; "
        f"{result.unchanged} unchanged; {len(result.conflicts)} conflict(s), "
        f"{len(result.errors)} unknown concept(s)"
    ]
    if result.changed:
        lines.append(f"  files written: {', '.join(sorted(result.changed))}")
    lines += [f"conflict {finding.render()}" for finding in result.conflicts]
    lines += [f"error   {finding.render()}" for finding in result.errors]
    lines += [f"note    ({group}) {note}" for group, note in result.notes]
    return "\n".join(lines)
