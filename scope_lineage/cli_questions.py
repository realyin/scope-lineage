"""The ``scope-lineage questions`` subcommands: ``validate``, ``sheet``, ``grading-sheet``, ``score``.

Kept out of ``cli.py`` like the other command groups. Files are read here -- YAML (with
the catalog's YAML 1.2 booleans) or JSON -- and handed to :mod:`scope_lineage.questions`
as plain data. Exit codes: 0 success (warnings allowed), 1 a document has errors or a
filter or grade names a question the set does not have, 2 an input could not be read.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any

from .questions import (
    GRADES_FORMAT,
    SET_FORMAT,
    SelectionError,
    graded_ids_outside,
    label_rounds,
    parse_answers,
    render_answer_sheet,
    render_grading_sheet,
    render_score_markdown,
    score_report,
    select_questions,
    validate_document,
)

_YAML_SUFFIXES = (".yaml", ".yml")


def add_questions_parser(subcommands) -> None:
    questions = subcommands.add_parser(
        "questions",
        help=(
            "Acceptance questions for generated pages: validate a question set or grades, "
            "write the answerer's and the grader's sheets, sum a grading round"
        ),
    )
    actions = questions.add_subparsers(dest="questions_command", required=True)
    validate = actions.add_parser(
        "validate",
        help=f"Check a {SET_FORMAT} or {GRADES_FORMAT} file; exit 1 when it has errors",
    )
    validate.add_argument("file", help="A question set or a grades file (.yaml, .yml or .json)")
    sheet = actions.add_parser(
        "sheet", help="Write the answerer's sheet: ids, tables and question text only"
    )
    sheet.add_argument("set", help=f"A {SET_FORMAT} file")
    sheet.add_argument(
        "--pages",
        help=(
            "The pages directory the answerer may read (named in the sheet's header); a "
            "question whose table has no page there is warned on stderr"
        ),
    )
    _add_subset_arguments(sheet)
    sheet.add_argument("--out", required=True, help="The sheet (.md)")
    grading = actions.add_parser(
        "grading-sheet",
        help="Write the grader's material: question, reference answer, evidence and answer",
    )
    grading.add_argument("set", help=f"A {SET_FORMAT} file")
    grading.add_argument(
        "--answers", required=True, help="The answerer's markdown: one `## <id>` section per answer"
    )
    _add_subset_arguments(grading)
    grading.add_argument("--out", required=True, help="The grading sheet (.md)")
    _add_score_parser(actions)


def _add_score_parser(actions) -> None:
    score = actions.add_parser(
        "score",
        help=(
            "Sum a grading round: total, by type, by table, by gap, lost points, and "
            "earlier rounds as comparison columns (score.md + score.json)"
        ),
    )
    score.add_argument("grades", help=f"A {GRADES_FORMAT} file: the round to score")
    score.add_argument("--set", required=True, help=f"The {SET_FORMAT} file it grades")
    score.add_argument(
        "--previous", nargs="+", action="extend", default=[], metavar="GRADES",
        help="Earlier rounds' grades, oldest first, shown beside this one",
    )
    _add_subset_arguments(score)
    score.add_argument("--out", required=True, help="Directory for score.md and score.json")


def _add_subset_arguments(parser) -> None:
    parser.add_argument(
        "--ids", nargs="+", action="extend", default=None, metavar="ID",
        help="Only these question ids",
    )
    parser.add_argument(
        "--only-table", nargs="+", action="extend", default=None, metavar="TABLE",
        help="Only questions about these tables (or concepts), matched case-insensitively",
    )


def run_questions(args: argparse.Namespace) -> int:
    if args.questions_command == "validate":
        return _run_validate(args)
    if args.questions_command == "sheet":
        return _run_sheet(args)
    if args.questions_command == "grading-sheet":
        return _run_grading_sheet(args)
    return _run_score(args)


def _run_validate(args: argparse.Namespace) -> int:
    document = _read(args.file)
    if isinstance(document, int):
        return document
    errors = validate_document(document)
    doc_format = document.get("doc_format") if isinstance(document, dict) else None
    items = _count(document)
    print(f"{args.file}: {doc_format}, {items}, {len(errors)} error(s)")
    for error in errors:
        print(f"  {error['at'] or '(document)'}: {error['message']}")
    return 1 if errors else 0


def _count(document) -> str:
    if not isinstance(document, dict):
        return "0 item(s)"
    if isinstance(document.get("questions"), list):
        return f"{len(document['questions'])} question(s)"
    if isinstance(document.get("grades"), list):
        return f"{len(document['grades'])} grade(s)"
    return "0 item(s)"


def _run_sheet(args: argparse.Namespace) -> int:
    loaded = _selected_set(args)
    if isinstance(loaded, int):
        return loaded
    document, questions = loaded
    _write(Path(args.out), render_answer_sheet(document, questions, pages=args.pages))
    print(f"Wrote {len(questions)} question(s) to {args.out}")
    if args.pages:
        _warn_pageless(Path(args.pages), questions)
    return 0


def _warn_pageless(pages: Path, questions: list[dict]) -> None:
    """Name each table a question asks about that has no ``<db.table>.md`` under ``pages``.

    The answerer reads only the pages; a question about a table without one can only be
    answered "not found". Pages are matched by file name anywhere under ``pages``, a
    catalog prefix and case ignored; a question about a concept is not checked.
    """
    from .semantics.names import bare_table

    if not pages.is_dir():
        print(f"warning: --pages does not exist: {pages}", file=sys.stderr)
        return
    have = {bare_table(path.stem) for path in pages.rglob("*.md")}
    missing: dict[str, list[str]] = {}
    for question in questions:
        table = question.get("table")
        if table and bare_table(table) not in have:
            missing.setdefault(table, []).append(question["id"])
    for table, ids in missing.items():
        print(f"warning: no page under {pages} for the table of {', '.join(ids)} ({table})",
              file=sys.stderr)


def _run_grading_sheet(args: argparse.Namespace) -> int:
    loaded = _selected_set(args)
    if isinstance(loaded, int):
        return loaded
    document, questions = loaded
    try:
        parsed = parse_answers(Path(args.answers).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        print(f"{args.answers}: cannot be read: {error}", file=sys.stderr)
        return 2
    known = {q["id"] for q in document["questions"]}
    _warn("no answer for", [q["id"] for q in questions if q["id"] not in parsed.answers])
    _warn("answers for ids the set does not have", [a for a in parsed.answers if a not in known])
    _warn("answer headings repeated (the first is kept)", parsed.duplicates)
    text = render_grading_sheet(document, questions, parsed.answers, set_label=args.set)
    _write(Path(args.out), text)
    print(f"Wrote {len(questions)} question(s) to {args.out}")
    return 0


def _run_score(args: argparse.Namespace) -> int:
    loaded = _selected_set(args)
    if isinstance(loaded, int):
        return loaded
    document, questions = loaded
    rounds = []
    for path in [*args.previous, args.grades]:
        grades = _load(path, GRADES_FORMAT)
        if isinstance(grades, int):
            return grades
        rounds.append((path, grades))
    unknown = graded_ids_outside(document["questions"], rounds[-1][1])
    if unknown:
        print(f"{args.grades}: graded ids the set does not have: {', '.join(unknown)}",
              file=sys.stderr)
        return 1
    for path, grades in rounds[:-1]:
        _warn(f"{path}: graded ids the set does not have (ignored)",
              graded_ids_outside(document["questions"], grades))
    labels = label_rounds([(grades.get("round"), Path(path).stem) for path, grades in rounds])
    report = score_report(
        questions, [(label, grades) for label, (_, grades) in zip(labels, rounds)],
        set_label=args.set, subject=document.get("subject") or "",
    )
    _warn("not graded (left out of the total)", report["ungraded"])
    out = Path(args.out)
    _write(out / "score.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    _write(out / "score.md", render_score_markdown(report))
    total = report["total"]
    print(
        f"{report['round']}: {total['points']} / {total['max']} ({total['percent']}%), "
        f"graded {total['graded']} of {total['questions']}; wrote {out}/score.md, score.json"
    )
    return 0


# ------------------------------------------------------------------ inputs


def _selected_set(args: argparse.Namespace) -> tuple[dict, list[dict]] | int:
    document = _load(args.set, SET_FORMAT)
    if isinstance(document, int):
        return document
    try:
        questions = select_questions(
            document["questions"], ids=args.ids, tables=args.only_table
        )
    except SelectionError as error:
        print(f"{args.set}: {error}", file=sys.stderr)
        return 1
    return document, questions


def _load(path: str, doc_format: str) -> dict | int:
    """A valid document of ``doc_format``, or the exit code after saying why not."""
    document = _read(path)
    if isinstance(document, int):
        return document
    errors = validate_document(document)
    found = document.get("doc_format") if isinstance(document, dict) else None
    if found != doc_format:
        errors = [{"at": "doc_format", "message": f"expected {doc_format}, got {found!r}"}]
    for error in errors:
        print(f"{path}: {error['at'] or '(document)'}: {error['message']}", file=sys.stderr)
    return 1 if errors else document


def _read(path: str) -> Any:
    """The file's data as plain JSON values, or 2 after saying why it cannot be read."""
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
        if source.suffix.lower() in _YAML_SUFFIXES:
            return _plain(_parse_yaml(text))
        return json.loads(text)
    except ImportError:
        print(f"{path}: reading YAML needs PyYAML: pip install 'scope-lineage[catalog]' "
              "(or write the file as .json)", file=sys.stderr)
    except (OSError, UnicodeDecodeError, ValueError) as error:
        print(f"{path}: cannot be read: {' '.join(str(error).split())}", file=sys.stderr)
    return 2


def _parse_yaml(text: str) -> Any:
    import yaml

    from .catalog.loader import yaml_loader

    try:
        return yaml.load(text, Loader=yaml_loader())  # noqa: S506 - a SafeLoader subclass
    except yaml.YAMLError as error:
        raise ValueError(str(error)) from None


def _plain(value: Any) -> Any:
    """YAML's extra scalar types folded into JSON ones: dates as ISO text, keys as text."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


def _warn(what: str, ids: list[str]) -> None:
    if ids:
        print(f"warning: {what}: {', '.join(ids)}", file=sys.stderr)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
