"""``scope-lineage catalog pending add|list|reply``: missing definitions.

An agent answering a data question writes ``/* 待确认：… */`` where the catalog gives no
definition (``scope.sql_placeholders``). ``add`` appends what is missing to a JSON Lines
file (``catalog-pending/1``) -- one line from options, or one a placeholder of a SQL file
-- and never rewrites a line already there. ``list`` reads the file back for the catalog's
owner: the same missing thing grouped, how often and in which questions it came up, and,
given ``--semantics`` and ``--ontology``, the question a table already records about the
same column and the catalog object that now carries the name. ``reply`` appends the
owner's reply to one group -- a line of its own, not a hit -- and ``list`` shows each
group's latest reply, leaving out those a reply closed unless ``--status`` asks. Files are read and written
here; ``render.catalog_pending`` works on plain data and reads no clock: the one place
the date comes from when ``--date`` is not given is ``today`` below.

Exit codes. add: 0 appended; 1 the SQL holds no placeholder, or a placeholder says
nothing (nothing appended); 2 bad options, an input could not be read, or the SQL does
not parse. list: 0 every line read; 1 some line is not a ``catalog-pending/1`` entry
(the rest are still listed); 2 an input could not be read. reply: 0 appended; 1 no
entry names that missing thing (nothing appended); 2 bad options or text, or the file
could not be read or written.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

from .render.catalog_pending import LIST_STATUSES, REPLY_STATUSES

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def today() -> str:
    """The date a line records when ``--date`` is not given: the local calendar day."""
    return datetime.date.today().isoformat()


def add_pending_parser(actions) -> None:
    pending = actions.add_parser(
        "pending",
        help=(
            "Keep the definitions an agent found missing (catalog-pending/1 JSON Lines) for "
            "the catalog's owner: add them from options or a SQL file's 待确认 placeholders, "
            "list them grouped with the questions that hit them"
        ),
    )
    steps = pending.add_subparsers(dest="pending_action", required=True)
    add = steps.add_parser(
        "add",
        help=(
            "Append one missing definition (--missing), or one a placeholder of a SQL file "
            "(--from-sql); never rewrites existing lines; exit 1 when the SQL has none"
        ),
    )
    add.add_argument("pending", help="The catalog-pending/1 file (created when absent)")
    add.add_argument("--question", required=True, help="The question it came up in")
    add.add_argument("--missing", help="What definition is missing, in the asker's words")
    add.add_argument(
        "--from-sql", metavar="FILE",
        help="A SQL file: one line a /* 待确认：… */ placeholder in it (instead of --missing)",
    )
    add.add_argument("--term", help="The business word itself, when --missing is a sentence")
    add.add_argument(
        "--table", action="append", default=[], metavar="DB.TABLE",
        help="A table it concerns (repeatable)",
    )
    add.add_argument(
        "--column", action="append", default=[], metavar="DB.TABLE.COLUMN",
        help="A column it concerns (repeatable); its table is listed too",
    )
    add.add_argument("--proposed", help="A definition the asker proposes, for the owner to judge")
    add.add_argument("--date", help="YYYY-MM-DD to record (default: today)")
    listing = steps.add_parser(
        "list",
        help=(
            "Group the entries naming the same missing thing, with hits and questions; mark "
            "recorded table-semantics questions and catalog objects that now carry the name"
        ),
    )
    listing.add_argument("pending", help="A catalog-pending/1 file")
    listing.add_argument(
        "--ontology", help="An ontology.json: mark entries whose name or term the catalog carries"
    )
    listing.add_argument(
        "--semantics",
        help="A directory of table-semantics documents: mark questions recorded on the same column",
    )
    listing.add_argument(
        "--status", choices=LIST_STATUSES, default="active",
        help=(
            "Which groups to list by their latest reply: active (default: every group no "
            "reply closed), open (no reply), answered, resolved, rejected, or all"
        ),
    )
    listing.add_argument(
        "--json", action="store_true", help="Print the catalog-pending-list/1 JSON instead of text"
    )
    reply = steps.add_parser(
        "reply",
        help=(
            "Append the owner's reply to the entries naming one missing thing (a reply line, "
            "not a hit); exit 1 when no entry names it"
        ),
    )
    reply.add_argument("pending", help="The catalog-pending/1 file")
    reply.add_argument(
        "--missing", required=True,
        help="The missing thing replied to, as an entry names it (compared as list groups)",
    )
    reply.add_argument("--reply", required=True, help="The reply, on one line")
    reply.add_argument(
        "--status", required=True, choices=REPLY_STATUSES,
        help=(
            "answered (defined, the catalog does not carry it yet), resolved (the catalog "
            "carries it) or rejected (it will not be defined); the last two close the group"
        ),
    )
    reply.add_argument("--by", help="Who replies")
    reply.add_argument("--date", help="YYYY-MM-DD to record (default: today)")


def run_pending(args: argparse.Namespace) -> int:
    if args.pending_action == "add":
        return _run_add(args)
    if args.pending_action == "reply":
        return _run_reply(args)
    return _run_list(args)


def _run_reply(args: argparse.Namespace) -> int:
    from .cli_catalog import _refused_or
    from .cli_catalog_answers import pending_reply

    line = _refused_or(
        pending_reply, args.pending, missing=args.missing, reply=args.reply,
        status=args.status, by=args.by, date=args.date,
    )
    if isinstance(line, int):
        return line
    print(f"Appended reply ({line['status']}) to {line['missing']!r} -> {args.pending}")
    return 0


def _run_add(args: argparse.Namespace) -> int:
    from .render.catalog_pending import pending_line

    problem = _add_options_problem(args)
    if problem:
        print(f"catalog pending add: {problem}", file=sys.stderr)
        return 2
    date = args.date or today()
    if args.from_sql:
        lines = _lines_from_sql(args, date)
        if isinstance(lines, int):
            return lines
    else:
        lines = [pending_line(
            missing=args.missing, question=args.question, date=date, tables=args.table,
            columns=args.column, term=args.term, proposed=args.proposed,
        )]
    try:
        _append(Path(args.pending), lines)
    except OSError as error:
        print(f"catalog pending add: cannot write {args.pending}: {error}", file=sys.stderr)
        return 2
    print(f"Appended {len(lines)} missing definition(s) -> {args.pending}")
    return 0


def _add_options_problem(args: argparse.Namespace):
    if bool(args.missing) == bool(args.from_sql):
        return "give exactly one of --missing and --from-sql"
    if args.from_sql and (args.term or args.proposed or args.table or args.column):
        return (
            "--term, --proposed, --table and --column describe one missing definition; with "
            "--from-sql each placeholder gives its own"
        )
    if not args.question.strip() or (args.missing is not None and not args.missing.strip()):
        return "--question and --missing must say something"
    if any(column.count(".") < 2 for column in args.column):
        return "--column takes db.table.column"
    if args.date is not None and not _is_date(args.date):
        return f"--date takes YYYY-MM-DD, not {args.date!r}"
    return None


def _is_date(text: str) -> bool:
    if not _DATE.match(text):
        return False
    try:
        datetime.date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _lines_from_sql(args: argparse.Namespace, date: str):
    from .cli_catalog import _refused_or
    from .cli_catalog_answers import pending_lines_from_sql

    try:
        sql = Path(args.from_sql).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        print(f"catalog pending add: cannot read {args.from_sql}: {error}", file=sys.stderr)
        return 2
    return _refused_or(
        pending_lines_from_sql, sql, question=args.question, date=date, sql_name=args.from_sql
    )


def _append(path: Path, lines: list[dict]) -> None:
    """Append the lines; a last line without its newline gets one first, nothing else."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lead = ""
    if path.exists() and path.stat().st_size:
        with path.open("rb") as handle:
            handle.seek(-1, 2)
            lead = "" if handle.read(1) == b"\n" else "\n"
    text = lead + "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def _run_list(args: argparse.Namespace) -> int:
    from .cli_catalog import _load_ontology, _print_answer, _refused_or, _semantics_option
    from .cli_catalog_answers import pending_answer, read_pending_file

    text = _refused_or(read_pending_file, args.pending)
    if isinstance(text, int):
        return text
    document = None
    if args.ontology:
        document = _load_ontology(args.ontology)
        if isinstance(document, int):
            return document
    semantics = _semantics_option(args.semantics)
    if isinstance(semantics, int):
        return semantics
    return _print_answer(pending_answer(text, document, semantics, args.status), args.json)
