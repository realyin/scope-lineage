"""``scope-lineage semantic status`` and ``semantic digest``: the run directory, read back.

A run keeps one directory per step, each overridable::

    <run>/packets/<db.table>/packet.json   semantic packet --out <run>/packets
    <run>/docs/<db.table>.json             written, validated and fixed by the model
    <run>/reviews/<db.table>.md            the independent review, with front matter
    <run>/pages/<db.table>.md              semantic render <run>/docs --out <run>/pages

``status`` reads what is there, validates each document in-process against its packet
and reports each table's stage (:mod:`scope_lineage.semantics.status`); ``--next`` lists
the tables a step still needs, in batches, so a rerun after an interruption picks up
where the last one stopped. ``digest`` prints a document's digest for a review's front
matter.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .semantics.digests import document_digest
from .semantics.names import bare_table
from .semantics.status import (
    STEPS,
    TableFiles,
    next_batches,
    render_status_text,
    status_report,
    table_status,
)

_DIRECTORIES = ("packets", "docs", "reviews", "pages")


def add_status_parsers(actions) -> None:
    status = actions.add_parser(
        "status",
        help="Report each table's stage in a run directory; --next lists what a step needs",
    )
    status.add_argument("run", help="Run directory: packets/ docs/ reviews/ pages/")
    for name in _DIRECTORIES:
        status.add_argument(f"--{name}", help=f"Directory instead of <run>/{name}")
    status.add_argument(
        "--only", nargs="+", action="extend", default=None, metavar="TABLE",
        help="Only these tables (db.table); a table with nothing in the run is no_packet",
    )
    status.add_argument(
        "--json", metavar="PATH",
        help="Write the table-semantics-status/1 report to PATH (- for stdout)",
    )
    status.add_argument(
        "--next", choices=STEPS,
        help="List the tables this step still needs, in batches (table-semantics-next/1)",
    )
    status.add_argument(
        "--batch-size", type=_positive, default=5, help="Tables per batch with --next (5)"
    )
    status.add_argument("--out", help="Write the --next batches here instead of stdout")
    digest = actions.add_parser(
        "digest", help="Print the digest of table-semantics documents, for a review's front matter"
    )
    digest.add_argument("files", nargs="+", help="table-semantics/1 JSON documents")


def _positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def run_status(args: argparse.Namespace) -> int:
    run = Path(args.run)
    if args.json == "-" and args.next and not args.out:
        print("--json - and --next without --out both want stdout", file=sys.stderr)
        return 2
    if not run.is_dir():
        print(f"run directory does not exist: {run}", file=sys.stderr)
        return 2
    directories = {name: Path(getattr(args, name) or run / name) for name in _DIRECTORIES}
    entries = [table_status(files) for files in _table_files(directories, args.only)]
    report = status_report(entries, {name: str(path) for name, path in directories.items()})
    stdout_taken = args.json == "-" or (args.next and not args.out)
    if args.json:
        _emit(report, args.json)
    if args.next:
        _emit(next_batches(entries, args.next, args.batch_size), args.out or "-")
    if not stdout_taken:
        print(render_status_text(report), end="")
    return 0


def run_digest(args: argparse.Namespace) -> int:
    code = 0
    for file in args.files:
        try:
            document = json.loads(Path(file).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            print(f"{file}: not a readable JSON document ({error})", file=sys.stderr)
            code = 1
            continue
        print(f"{document_digest(document)}  {file}")
    return code


def _emit(document: dict, target: str) -> None:
    text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if target == "-":
        print(text, end="")
        return
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _table_files(directories: dict[str, Path], only) -> list[TableFiles]:
    packets = _packets(directories["packets"])
    documents = _documents(directories["docs"])
    reviews = _reviews(directories["reviews"])
    if only:
        tables = {bare_table(name) for name in only}
    else:
        tables = set(packets) | set(documents) | set(reviews)
    return [
        _files(table, packets.get(table), documents.get(table), reviews.get(table),
               directories)
        for table in sorted(tables)
    ]


def _files(table: str, packet, document, review, directories) -> TableFiles:
    page = directories["pages"] / f"{table}.md"
    fresh = None
    if document is not None and page.is_file():
        fresh = page.stat().st_mtime >= document["path"].stat().st_mtime
    fields = {} if document is None else {
        key: document[key] for key in ("document", "file", "unreadable") if key in document
    }
    return TableFiles(table=table, packet=packet, review=review, page_fresh=fresh, **fields)


def _packets(directory: Path) -> dict[str, dict | None]:
    found: dict[str, dict | None] = {}
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("*/packet.json")):
        packet = _read_json(path)
        found[bare_table(path.parent.name)] = packet if isinstance(packet, dict) else None
    return {table: packet for table, packet in found.items() if packet is not None}


def _documents(directory: Path) -> dict[str, dict]:
    """``table -> {path, file, document | unreadable}``; the first file per table wins.

    The toolchain's other documents kept beside them are skipped, as ``validate`` does.
    """
    from .cli_semantic import _OTHER_FORMATS

    found: dict[str, dict] = {}
    if not directory.is_dir():
        return found
    for path in sorted(directory.rglob("*.json")):
        item: dict = {"path": path, "file": path.relative_to(directory).as_posix()}
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            item["unreadable"] = f"not a readable JSON document ({error})"
            document = None
        else:
            item["document"] = document
        if isinstance(document, dict) and document.get("doc_format") in _OTHER_FORMATS:
            continue
        named = document.get("table") if isinstance(document, dict) else None
        table = bare_table(named if isinstance(named, str) and named else path.stem)
        found.setdefault(table, item)
    return found


def _reviews(directory: Path) -> dict[str, str]:
    if not directory.is_dir():
        return {}
    reviews = {}
    for path in sorted(directory.glob("*.md")):
        try:
            reviews[bare_table(path.stem)] = path.read_text(encoding="utf-8")
        except OSError:
            continue
    return reviews


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
