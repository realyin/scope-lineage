"""``scope-lineage semantic probes check``: read the inputs, hand them to
:mod:`scope_lineage.semantics.probes`, print the report.

The probes file, the packets, the documents and the sensitive-column list are read here
and passed on as plain data. No SQL is ever run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .semantics.names import bare_table
from .semantics.probes import CHECK_FORMAT, SENSITIVE_FILE, check_probes, parse_sensitive
from .semantics.schema import DOC_FORMAT


def add_probes_parser(actions) -> None:
    probes = actions.add_parser(
        "probes",
        help="Platform queries for open questions (question-probes/1): check them statically",
    )
    commands = probes.add_subparsers(dest="probes_command", required=True)
    check = commands.add_parser(
        "check",
        help=(
            "Check a question-probes/1 file (C1-C9) against the packets and the documents; "
            "never runs a query"
        ),
    )
    check.add_argument("probes", help="A question-probes/1 file")
    check.add_argument("--packets", required=True, help="The --out of `semantic packet`")
    check.add_argument(
        "--docs", metavar="DIR",
        help=(
            "The table-semantics/1 documents: every item's question must still read as asked "
            "(C7), and their identifier columns are kept out of the output (C5)"
        ),
    )
    check.add_argument(
        "--sensitive", metavar="FILE",
        help=(
            "Column names no query may output, one per line (a column name, or "
            f"db.table.column; # starts a comment). Default: {SENSITIVE_FILE} beside "
            "--packets (the run directory), when it exists"
        ),
    )
    check.add_argument(
        "--json", action="store_true",
        help=f"Print the {CHECK_FORMAT} report instead of the text summary",
    )


def run_probes(args: argparse.Namespace) -> int:
    """Exit 0 when nothing fails, 1 when a check fails, 2 when an input cannot be read."""
    packets_dir = Path(args.packets)
    if not packets_dir.is_dir():
        print(f"--packets does not exist: {packets_dir}", file=sys.stderr)
        return 2
    try:
        document = json.loads(Path(args.probes).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"cannot read {args.probes}: {error}", file=sys.stderr)
        return 2
    documents = None
    if args.docs:
        if not Path(args.docs).is_dir():
            print(f"--docs does not exist: {args.docs}", file=sys.stderr)
            return 2
        documents = _documents(Path(args.docs))
    sensitive, source = _sensitive(args, packets_dir)
    if isinstance(sensitive, int):
        return sensitive
    tables = {bare_table(item.get("table")) for item in _items(document)}
    packets = {table: _packet(packets_dir, table) for table in sorted(tables) if table}
    report = check_probes(document, packets, documents, sensitive)
    report = {"doc_format": report.pop("doc_format"), "probes": str(args.probes),
              "sensitive": None if sensitive is None else {
                  "path": str(source[0]), "source": source[1],
                  "names": len(sensitive.names) + len(sensitive.columns)},
              **report}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text(report), end="")
    return 1 if report["summary"]["failures"] else 0


def _items(document) -> list[dict]:
    items = document.get("items") if isinstance(document, dict) else None
    return [item for item in items or [] if isinstance(item, dict)]


def _sensitive(args: argparse.Namespace, packets: Path):
    """The sensitive-column list and (path, source); (None, None) when there is none, or
    (2, None) when it cannot be read. A list read is announced on stderr."""
    path, source = args.sensitive, "--sensitive"
    if not path:
        default = packets.parent / SENSITIVE_FILE
        if not default.is_file():
            return None, None
        path, source = default, "default"
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        print(f"cannot read the sensitive-column list {path}: {error}", file=sys.stderr)
        return 2, None
    sensitive, problems = parse_sensitive(text)
    if problems:
        for problem in problems:
            print(f"{path}: {problem}", file=sys.stderr)
        return 2, None
    count = len(sensitive.names) + len(sensitive.columns)
    print(f"sensitive columns: {path} ({count} name(s), from {source})", file=sys.stderr)
    return sensitive, (path, source)


def _documents(directory: Path) -> dict[str, dict]:
    found = {}
    for path in sorted(directory.rglob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(document, dict) and document.get("doc_format") == DOC_FORMAT:
            found[bare_table(document.get("table"))] = document
    return found


def _packet(packets: Path, table: str) -> dict | None:
    try:
        return json.loads((packets / table / "packet.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def render_text(report: dict) -> str:
    summary = report["summary"]
    lines = [
        f"question-probes check: {report['probes']}",
        "SQL is parsed (sqlglot, Spark dialect), never run",
        f"items: {summary['items']} (data {summary['data']}, human {summary['human']}, "
        f"corpus {summary['corpus']})",
        f"checks: {' '.join(summary['checks'])}",
    ]
    sensitive = report["sensitive"]
    if sensitive:
        lines.append(f"sensitive columns: {sensitive['path']} ({sensitive['names']} name(s), "
                     f"from {sensitive['source']})")
    if summary["full_scans"]:
        lines.append(f"full scans flagged: {summary['full_scans']}")
    for warning in report["warnings"]:
        lines.append(f"WARN {warning}")
    for error in report["schema_errors"]:
        lines.append(f"FAIL schema {error['at'] or '(document)'}: {error['message']}")
    for item in report["items"]:
        where = f"{item['table']} {item['question']} part {item['part']}"
        for finding in item["findings"]:
            lines.append(f"{finding['level']} {item['id']} ({where}) {finding['check']}: "
                         f"{finding['message']}")
    verdict = "FAIL" if summary["failures"] else "PASS"
    lines.append(f"RESULT: {verdict} ({summary['failures']} failure(s), "
                 f"{summary['warnings']} warning(s))")
    return "\n".join(lines) + "\n"
