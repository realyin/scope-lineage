"""The ``scope-lineage semantic`` subcommands: ``packet``, ``validate``, ``confirm``.

Kept out of ``cli.py`` like ``tables`` and ``catalog``. This module is where the inputs
are loaded -- the lineage walk ``describe`` uses, the task JSON reader ``parse`` uses,
the schema loaders behind ``--schema`` / ``--schema-fallback`` -- and handed to
:mod:`scope_lineage.semantics` as plain data, so that package reads contract-derived
views only. ``cli`` is imported inside the runners so this module can be imported from
``cli`` without a cycle.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .metadata.schema_metadata import (
    column_details_for_table,
    load_schema_sources,
    partition_columns_for_table,
    table_details_for_table,
)
from .scope.sql_comments import redact_comments_in_sql
from .semantics import (
    CONFIRMATIONS_FORMAT,
    DOC_FORMAT,
    UnknownTables,
    apply_confirmations,
    build_packets,
    render_packet_markdown,
    render_validation_text,
    schema_errors,
    validation_report,
)
from .semantics.names import bare_table
from .semantics.packet import PACKET_FORMAT
from .semantics.validate import REPORT_FORMAT, check_file

# The toolchain's own documents that may sit beside the ones `validate` checks.
_OTHER_FORMATS = frozenset({CONFIRMATIONS_FORMAT, PACKET_FORMAT, REPORT_FORMAT})


def add_semantic_parser(subcommands) -> None:
    semantic = subcommands.add_parser(
        "semantic",
        help="Table semantics: build material packets, validate written documents, apply confirmations",
    )
    actions = semantic.add_subparsers(dest="semantic_command", required=True)
    _add_packet_parser(actions)
    validate = actions.add_parser(
        "validate",
        help="Check table-semantics/1 documents against their schema and their packets",
    )
    validate.add_argument("directory", help="Directory of table-semantics/1 JSON documents")
    validate.add_argument("--packets", required=True, help="The --out of `semantic packet`")
    validate.add_argument(
        "--json", action="store_true",
        help="Print the table-semantics-validation/1 report instead of the text summary",
    )
    confirm = actions.add_parser(
        "confirm", help="Apply a semantic-confirmations/1 file to table-semantics documents"
    )
    confirm.add_argument("directory", help="Directory of table-semantics/1 JSON documents")
    confirm.add_argument("--confirmations", required=True, help="A semantic-confirmations/1 file")
    confirm.add_argument(
        "--out", help="Write the confirmed documents here instead of rewriting them in place"
    )


def _add_packet_parser(actions) -> None:
    packet = actions.add_parser(
        "packet",
        help="Write one material packet (packet.md + packet.json) per target table",
    )
    packet.add_argument(
        "--lineage", required=True,
        help="One lineage.json file, or a directory searched recursively for lineage.json",
    )
    packet.add_argument(
        "--tasks", required=True,
        help="Directory of the task JSON files the lineage was parsed from (for their SQL)",
    )
    packet.add_argument("--schema", help="Schema metadata, as `parse --schema` reads it")
    packet.add_argument(
        "--schema-fallback", action="append", default=[],
        help="Additional schema source for tables absent from --schema; repeatable",
    )
    packet.add_argument(
        "--tables",
        help="A tables.json from `scope-lineage tables`; default: cards built from --lineage",
    )
    packet.add_argument(
        "--only", nargs="+", action="extend", default=None, metavar="TABLE",
        help="Only these target tables (db.table, a catalog prefix is ignored)",
    )
    packet.add_argument("--out", required=True, help="Directory for <db.table>/packet.{md,json}")


def run_semantic(args: argparse.Namespace) -> int:
    if args.semantic_command == "packet":
        return _run_packet(args)
    if args.semantic_command == "validate":
        return _run_validate(args)
    return _run_confirm(args)


# ------------------------------------------------------------------ packet


def _run_packet(args: argparse.Namespace) -> int:
    from .cli import _discover_lineage_documents, _load_contract_documents, _load_corpus_document
    from .render.table_cards import DOC_FORMAT as TABLES_DOC_FORMAT

    found = _discover_lineage_documents(args.lineage)
    if isinstance(found, int):
        return found
    paths, base, single_file = found
    if args.only and not single_file:
        paths = _related_paths(paths, args.only, input_producers=not args.tables)
    loaded = _load_contract_documents(paths, base, single_file, None, "semantic packet")
    if isinstance(loaded, int):
        return loaded
    cards = _load_corpus_document(args.tables, "--tables", TABLES_DOC_FORMAT)
    tasks = _task_records(args.tasks)
    documents = [(item.document, item.diagnostics) for item in loaded.documents]
    metadata = _metadata_lookup(args, _tables_described(documents, args.only))
    for value in (cards, tasks, metadata):
        if isinstance(value, int):
            return value
    try:
        packets = build_packets(
            documents,
            tasks=tasks, metadata=metadata, cards=cards, only=args.only,
        )
    except UnknownTables as error:
        print(str(error), file=sys.stderr)
        return 1
    _write_packets(Path(args.out), packets)
    missing = sum(1 for p in packets for task in p["tasks"] if task["sql"] is None)
    print(
        f"Packed {len(packets)} table(s) from {len(loaded.documents)} task(s) "
        f"(tasks_without_sql={missing}, {loaded.counters()})"
    )
    return 0


def _related_paths(paths: list[Path], only: list[str], *, input_producers: bool) -> list[Path]:
    """The lineage documents an ``--only`` run needs, found without profiling the corpus.

    A document that writes or reads a table names it, so a byte search for the table's
    last name segment finds every candidate (identifiers are lower-case in the contract);
    only those are parsed. With ``--tables`` the cards already hold the consumers and the
    input producers, so only the producers are kept. Without it the cards are built from
    what is kept: the producers, every document that names the table (its consumers),
    and, found by a second search, the producers of the producers' input tables.
    """
    from .semantics.packet import document_reads, document_writes

    wanted = {bare_table(name) for name in only}
    first = _parsed(_mentioning(paths, wanted))
    producers = {path: doc for path, doc in first.items() if document_writes(doc) & wanted}
    if not input_producers:
        return sorted(producers)
    inputs = set().union(*(document_reads(doc) for doc in producers.values())) - wanted
    rest = [path for path in paths if path not in first]
    second = _parsed(_mentioning(rest, inputs))
    upstream = [path for path, doc in second.items() if document_writes(doc) & inputs]
    return sorted([*first, *upstream])


def _mentioning(paths: list[Path], tables: set[str]) -> list[Path]:
    needles = {table.rsplit(".", 1)[-1].encode("utf-8") for table in tables}
    if not needles:
        return []
    found = []
    for path in paths:
        try:
            data = path.read_bytes()
        except OSError:
            found.append(path)  # unreadable: the walk reports it, not this filter
            continue
        if any(needle in data for needle in needles):
            found.append(path)
    return found


def _parsed(paths: list[Path]) -> dict[Path, dict]:
    parsed = {}
    for path in paths:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            document = {}
        parsed[path] = document if isinstance(document, dict) else {}
    return parsed


def _write_packets(out: Path, packets: list[dict]) -> None:
    for packet in packets:
        directory = out / packet["table"]
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "packet.json").write_text(
            json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (directory / "packet.md").write_text(render_packet_markdown(packet), encoding="utf-8")


def _task_records(directory: str):
    """``{name, source_file, sql}`` per task JSON under ``directory``, or the exit code.

    Read with ``parse``'s own task reader, so a task is found under the name ``parse``
    gave it; the SQL's comments are masked the way ``parse`` masks them by default.
    """
    from .cli import _load_task_input

    root = Path(directory)
    if not root.is_dir():
        print(f"--tasks directory does not exist: {root}", file=sys.stderr)
        return 2
    records = []
    for path in sorted(root.rglob("*.json")):
        try:
            item = _load_task_input(path, root, None)
        except (OSError, ValueError) as error:
            print(f"{path}: not a task JSON, skipped ({error})", file=sys.stderr)
            continue
        records.append({
            "name": item.task_name,
            "source_file": path.relative_to(root).as_posix(),
            "sql": redact_comments_in_sql(item.sql),
        })
    return records


def _tables_described(documents: list, only) -> set[str] | None:
    """With ``--only``, the tables a packet describes: the targets and their inputs."""
    from .semantics.packet import document_reads, document_writes

    if not only:
        return None
    wanted = {bare_table(name) for name in only}
    producers = [doc for doc, _ in documents if document_writes(doc) & wanted]
    return wanted.union(*(document_reads(doc) for doc in producers))


def _metadata_lookup(args: argparse.Namespace, tables: set[str] | None = None):
    """``db.table -> {comment, description, layer, domain, columns, partition facts}``,
    None, or the exit code. ``tables`` narrows a metadata directory to the files naming
    them, so an ``--only`` run does not parse every table's DDL."""
    paths = [path for path in [args.schema, *args.schema_fallback] if path]
    if not paths:
        return None
    try:
        schema = load_schema_sources(paths, only_tables=tables)
    except (OSError, ValueError) as error:
        print(f"--schema: {error}", file=sys.stderr)
        return 2

    def lookup(table: str) -> dict | None:
        columns = column_details_for_table(schema, table)
        details = table_details_for_table(schema, table)
        if not columns and not details:
            return None
        name, description = details.get("table_name_cn"), details.get("table_desc")
        return {
            "comment": name or description,
            "description": description if name and description != name else None,
            "layer": details.get("table_label_layer"),
            "domain": details.get("domain"),
            "partitioned": details.get("is_partitioned"),
            "partition_columns": partition_columns_for_table(schema, table),
            "columns": columns,
        }

    return lookup


# ------------------------------------------------------------------ validate


def _run_validate(args: argparse.Namespace) -> int:
    directory, packets = Path(args.directory), Path(args.packets)
    for path, flag in ((directory, "directory"), (packets, "--packets")):
        if not path.is_dir():
            print(f"{flag} does not exist: {path}", file=sys.stderr)
            return 2
    files = sorted(directory.rglob("*.json"))
    if not files:
        print(f"no JSON document under {directory}", file=sys.stderr)
        return 1
    checked = [_check_path(path, directory, packets) for path in files]
    entries = [entry for entry in checked if entry is not None]
    report = validation_report(entries)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_validation_text(report), end="")
    return 1 if any(entry["schema_errors"] for entry in entries) else 0


def _check_path(path: Path, directory: Path, packets: Path) -> dict | None:
    """One file's report entry; None for this toolchain's other documents.

    A confirmations file kept beside the documents it answers is skipped rather than
    reported as a broken document; any other JSON -- a model that wrote the wrong
    ``doc_format`` included -- is checked, and fails the schema.
    """
    file = path.relative_to(directory).as_posix()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return check_file(None, None, file, unreadable=f"not a readable JSON document ({error})")
    if isinstance(document, dict) and document.get("doc_format") in _OTHER_FORMATS:
        return None
    table = document.get("table") if isinstance(document, dict) else None
    return check_file(document, _read_packet(packets, table), file)


def _read_packet(packets: Path, table) -> dict | None:
    if not isinstance(table, str) or not table:
        return None
    path = packets / bare_table(table) / "packet.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------ confirm


def _run_confirm(args: argparse.Namespace) -> int:
    directory = Path(args.directory)
    if not directory.is_dir():
        print(f"directory does not exist: {directory}", file=sys.stderr)
        return 2
    confirmations = _read_confirmations(Path(args.confirmations))
    if confirmations is None:
        return 2
    documents, files = _semantic_documents(directory)
    result = apply_confirmations(documents, confirmations)
    out = Path(args.out) if args.out else directory
    for table in sorted(result.documents if args.out else result.changed):
        target = out / files[table]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(result.documents[table], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(
        f"Applied {len(result.applied)} confirmation(s) to {len(result.changed)} table(s) "
        f"(unmatched={len(result.unmatched)})"
    )
    for item in result.unmatched:
        print(f"  unmatched: {item['table']} {item['target']}: {item['reason']}")
    return 0


def _read_confirmations(path: Path) -> list | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"--confirmations: not a readable JSON document ({error})", file=sys.stderr)
        return None
    errors = schema_errors(document, CONFIRMATIONS_FORMAT)
    for error in errors:
        print(f"--confirmations {error['at'] or '(document)'}: {error['message']}", file=sys.stderr)
    return None if errors else document["confirmations"]


def _semantic_documents(directory: Path) -> tuple[dict, dict]:
    documents, files = {}, {}
    for path in sorted(directory.rglob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(document, dict) and document.get("doc_format") == DOC_FORMAT:
            table = bare_table(document.get("table"))
            documents[table] = document
            files[table] = path.relative_to(directory)
    return documents, files
