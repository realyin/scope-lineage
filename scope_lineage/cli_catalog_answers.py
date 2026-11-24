"""The catalog's answer commands as functions: ``search``, ``query``, ``context``,
``check-sql`` and ``pending add`` / ``pending list``.

``cli_catalog`` and ``cli_catalog_pending`` call these, and so may anything that serves
the same answers another way -- an HTTP or MCP server kept outside this package. That is
the point of the module: a served answer is the one ``--json`` prints (``json_text()``
is the same serialisation), its text is the one the command prints without ``--json``,
and an input the command refuses is refused here with the same sentence and the same
exit code (``CatalogAnswerError``). Exit codes keep the commands' meaning: 0 found, 1
nothing found (or, for ``check-sql``, an error or a warning; for ``pending list``, a line
that is not an entry), 2 an input the command cannot use.

The functions read only the paths they are handed and write only the pending file
``pending_add`` is handed; none runs SQL.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Iterable


class CatalogAnswerError(Exception):
    """An input the command refuses: ``message`` is what it prints on stderr."""

    def __init__(self, exit_code: int, message: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.message = message


@dataclass(frozen=True)
class CatalogAnswer:
    """One answer: ``result`` is what ``--json`` prints, ``exit_code`` the command's."""

    result: dict
    exit_code: int
    renderer: Callable[[dict], str]

    def json_text(self) -> str:
        """The ``--json`` output without its final newline."""
        return json.dumps(self.result, ensure_ascii=False, indent=2)

    def text(self) -> str:
        """What the command prints without ``--json``."""
        return self.renderer(self.result)


# ------------------------------------------------------------------ inputs


def load_ontology(path: str) -> dict:
    """A built ``ontology-json/3`` document; exit 2 unreadable, 1 another format."""
    from .render.catalog_view import ONTOLOGY_FORMAT

    source = Path(path)
    if not source.is_file():
        raise CatalogAnswerError(2, f"ontology path does not exist: {source}")
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise CatalogAnswerError(
            2, f"{source}: not a readable JSON document ({error})"
        ) from error
    if not isinstance(document, dict):
        raise CatalogAnswerError(
            2,
            f"{source}: not a readable JSON document "
            f"(top level is {type(document).__name__}, not an object)",
        )
    if document.get("doc_format") != ONTOLOGY_FORMAT:
        raise CatalogAnswerError(
            1,
            f"ontology expects a {ONTOLOGY_FORMAT} document; {source} declares "
            f"{document.get('doc_format')!r}",
        )
    return document


def load_semantics(directory: str | None) -> dict | None:
    """``{db.table: table-semantics document}`` under a directory; None without one."""
    from .cli_semantic import _semantic_documents

    if not directory:
        return None
    root = Path(directory)
    if not root.is_dir():
        raise CatalogAnswerError(2, f"--semantics directory does not exist: {root}")
    return _semantic_documents(root)[0]


# ------------------------------------------------------------------ answers


def search(
    document: dict,
    text: str,
    semantics: dict | None = None,
    *,
    kinds: Iterable[str] | None = None,
    limit: int = 10,
) -> CatalogAnswer:
    from .render.catalog_search import render_search_text, search_catalog

    kinds = list(kinds) if kinds else None
    result = search_catalog(document, text, semantics, kinds=kinds, limit=limit)
    return CatalogAnswer(result, 0 if result["hits"] else 1, render_search_text)


def query(document: dict, kind: str, term: str) -> CatalogAnswer:
    from .render.catalog_query import QUERY_KINDS, query_catalog, render_query_text

    if kind not in QUERY_KINDS:
        raise CatalogAnswerError(
            2, f"catalog query: kind must be one of {', '.join(QUERY_KINDS)}, not {kind!r}"
        )
    result = query_catalog(document, kind, term)
    return CatalogAnswer(result, 0 if result["matches"] else 1, render_query_text)


def context_columns(
    *,
    tables: Iterable[str] = (),
    columns: Iterable[str] = (),
    columns_of_table: Iterable[str] = (),
    concepts: Iterable[str] = (),
    focus: bool = False,
) -> list[str]:
    """The names ``--columns`` asks of the requested tables, or the refusal of ``catalog context``.

    ``columns_of_table`` is ``--columns``: comma-separated names, each looked up in every
    requested table (``table.col`` pins one of them).
    """
    tables, columns = list(tables), list(columns)
    columns_of_table, concepts = list(columns_of_table), list(concepts)
    if not (tables or columns or columns_of_table or concepts):
        raise CatalogAnswerError(
            2, "catalog context: name at least one --table, --column or --concept"
        )
    if columns_of_table and not tables:
        raise CatalogAnswerError(
            2,
            "catalog context: --columns names columns of the --table values; give at least "
            "one --table, or use --column db.table.column",
        )
    table_columns = [
        name.strip() for value in columns_of_table for name in value.split(",") if name.strip()
    ]
    if focus and not (columns or table_columns):
        raise CatalogAnswerError(
            2, "catalog context: --focus needs the columns to focus on (--column or --columns)"
        )
    return table_columns


def context(
    document: dict,
    semantics: dict | None,
    *,
    tables: Iterable[str] = (),
    columns: Iterable[str] = (),
    columns_of_table: Iterable[str] = (),
    concepts: Iterable[str] = (),
    brief: bool = False,
    focus: bool = False,
    page_states: dict | None = None,
) -> CatalogAnswer:
    """``catalog context``. ``page_states`` (no flag: a server passes it) marks the
    questions a browsing page answered or noted, ``{(table, question id): state}`` as
    ``render.catalog_context.page_index`` reads it; a state it refuses is exit 2."""
    from .render.catalog_context import context_pack, page_index, render_context_text

    tables, columns, concepts = list(tables), list(columns), list(concepts)
    table_columns = context_columns(
        tables=tables, columns=columns, columns_of_table=columns_of_table,
        concepts=concepts, focus=focus,
    )
    try:
        page_index(page_states)
    except ValueError as error:
        raise CatalogAnswerError(2, f"catalog context: {error}") from error
    pack = context_pack(
        document, semantics, tables=tables, columns=columns, concepts=concepts,
        table_columns=table_columns, brief=brief, focus=focus, page_states=page_states,
    )
    found = pack["concepts"] or pack["tables"] or pack["columns"]
    return CatalogAnswer(pack, 0 if found else 1, render_context_text)


def check_sql(document: dict, sql: str) -> CatalogAnswer:
    """Check SQL text against the catalog; it is parsed, never run."""
    from .render.catalog_sql_check import check_sql as check, render_check_sql_text
    from .scope.query_facts import QueryFactsError, query_facts

    try:
        statements = query_facts(sql)
    except QueryFactsError as error:
        raise CatalogAnswerError(2, f"catalog check-sql: {error}") from error
    result = check(document, statements)
    blocking = [f for f in result["findings"] if f["severity"] in ("error", "warning")]
    return CatalogAnswer(result, 1 if blocking else 0, render_check_sql_text)


# ------------------------------------------------------------------ pending


def pending_lines_from_sql(sql: str, *, question: str, date: str, sql_name: str) -> list[dict]:
    """One ``catalog-pending/1`` line a placeholder of the SQL; exit 1 when there is none."""
    from .render.catalog_pending import lines_from_placeholders
    from .scope.query_facts import QueryFactsError, query_facts

    try:
        statements = query_facts(sql)
    except QueryFactsError as error:
        raise CatalogAnswerError(2, f"catalog pending add: {error}") from error
    lines, empty = lines_from_placeholders(statements, question=question, date=date, sql=sql_name)
    if empty:
        where = "、".join(f"第 {item['statement']} 条语句" for item in empty)
        raise CatalogAnswerError(
            1, f"catalog pending add: {where}有 待确认 占位没有写缺什么；补上再记，什么也没写入"
        )
    if not lines:
        raise CatalogAnswerError(
            1, f"catalog pending add: {sql_name} has no /* 待确认：… */ placeholder"
        )
    return lines


def pending_add(
    path: str,
    *,
    question: str,
    missing: str | None = None,
    sql: str | None = None,
    sql_name: str | None = None,
    term: str | None = None,
    tables: Iterable[str] = (),
    columns: Iterable[str] = (),
    proposed: str | None = None,
    date: str | None = None,
) -> list[dict]:
    """Append to the pending file what ``catalog pending add`` appends; the lines written.

    ``missing`` is ``--missing``; ``sql`` is the text of the ``--from-sql`` file and
    ``sql_name`` what the lines record as its name. Nothing is written on a refusal.
    """
    from .cli_catalog_pending import _add_options_problem, _append, today
    from .render.catalog_pending import pending_line

    tables, columns = list(tables), list(columns)
    options = SimpleNamespace(
        question=question, missing=missing, from_sql=sql, term=term, proposed=proposed,
        table=tables, column=columns, date=date,
    )
    problem = _add_options_problem(options)
    if problem:
        raise CatalogAnswerError(2, f"catalog pending add: {problem}")
    date = date or today()
    if sql:
        lines = pending_lines_from_sql(
            sql, question=question, date=date, sql_name=sql_name or "-"
        )
    else:
        lines = [pending_line(
            missing=missing, question=question, date=date, tables=tables, columns=columns,
            term=term, proposed=proposed,
        )]
    try:
        _append(Path(path), lines)
    except OSError as error:
        raise CatalogAnswerError(2, f"catalog pending add: cannot write {path}: {error}") from error
    return lines


def read_pending_file(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise CatalogAnswerError(
            2, f"catalog pending list: cannot read {path}: {error}"
        ) from error


def pending_answer(
    text: str, document: dict | None = None, semantics: dict | None = None,
    status: str = "active",
) -> CatalogAnswer:
    """``catalog pending list`` of a pending file's text; ``status`` is ``--status``."""
    from .render.catalog_pending import pending_report, read_pending, render_pending_text

    entries, problems = read_pending(text.splitlines())
    report = pending_report(
        entries, problems, document=document, semantics=semantics, status=status
    )
    return CatalogAnswer(report, 1 if report["problems"] else 0, render_pending_text)


def pending_list(
    path: str, document: dict | None = None, semantics: dict | None = None,
    status: str = "active",
) -> CatalogAnswer:
    return pending_answer(read_pending_file(path), document, semantics, status)


def pending_reply(
    path: str,
    *,
    missing: str,
    reply: str,
    status: str,
    by: str | None = None,
    date: str | None = None,
) -> dict:
    """Append what ``catalog pending reply`` appends; the line written.

    Exit 2: a text that does not fit on one line, an unknown status, a bad date, or a file
    that cannot be read or written; exit 1: no entry of the file names ``missing``.
    Nothing is written on a refusal."""
    from .cli_catalog_pending import _append, _is_date, today
    from .render.catalog_pending import (
        BY_LIMIT,
        REPLY_LIMIT,
        REPLY_STATUSES,
        read_pending,
        reply_line,
        reply_text_problem,
        same_missing,
    )

    problem = (
        reply_text_problem(missing, "--missing", REPLY_LIMIT)
        or reply_text_problem(reply, "--reply", REPLY_LIMIT)
        or (reply_text_problem(by, "--by", BY_LIMIT) if by is not None else None)
    )
    if problem is None and status not in REPLY_STATUSES:
        problem = f"--status takes {', '.join(REPLY_STATUSES)}, not {status!r}"
    if problem is None and date is not None and not _is_date(date):
        problem = f"--date takes YYYY-MM-DD, not {date!r}"
    if problem:
        raise CatalogAnswerError(2, f"catalog pending reply: {problem}")
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise CatalogAnswerError(
            2, f"catalog pending reply: cannot read {path}: {error}"
        ) from error
    entries, _ = read_pending(text.splitlines())
    known = {same_missing(e["missing"]) for e in entries if e.get("kind") != "reply"}
    if same_missing(missing) not in known:
        raise CatalogAnswerError(
            1, f"catalog pending reply: no entry of {path} names {missing.strip()!r}; "
            "nothing written (catalog pending list shows what is there)"
        )
    line = reply_line(missing=missing, reply=reply, status=status, by=by,
                      date=date or today())
    try:
        _append(Path(path), [line])
    except OSError as error:
        raise CatalogAnswerError(
            2, f"catalog pending reply: cannot write {path}: {error}"
        ) from error
    return line


# ------------------------------------------------------------------ browsing
#
# The parts of the catalog one view of a browsing page shows (``render.catalog_browse``).
# They are answers without a command: the command line keeps ``query``, ``context`` and
# ``render`` for the same facts, and these exist so a server can send a page, a
# neighbourhood or a board instead of the whole document. They have no text form: their
# ``text()`` is the JSON. A request they cannot answer is exit 2, like a command's.


def _json_only(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2) + "\n"


def _browse(produce: Callable[[], dict], found: Callable[[dict], bool] = lambda _: True):
    try:
        result = produce()
    except ValueError as error:
        raise CatalogAnswerError(2, f"catalog browse: {error}") from error
    return CatalogAnswer(result, 0 if found(result) else 1, _json_only)


def browse_index(document: dict, semantics: dict | None = None) -> CatalogAnswer:
    """The catalog's name, counts and domains, and the index's 「用之前先看」 summary (no
    command; see above): ``catalog render --docs`` counts the same rows from the same
    table-semantics documents."""
    from .render.catalog_browse import browse_index as index

    return _browse(lambda: index(document, semantics))


def browse_list(
    document: dict, kind: str, semantics: dict | None = None, **request
) -> CatalogAnswer:
    """One page of concepts, tables or metrics (no command); an empty page is exit 0. With
    ``semantics``, a table row carries its row of the index's 「按表看」, and ``sort`` may
    order the tables by one of its numbers."""
    from .render.catalog_browse import browse_list as listing

    return _browse(lambda: listing(document, kind, semantics=semantics, **request))


def neighbourhood(document: dict, concept: str, **request) -> CatalogAnswer:
    """A concept's one-hop neighbourhood for a graph (no command); exit 1 when no concept
    matches."""
    from .render.catalog_browse import concept_neighbourhood

    return _browse(
        lambda: concept_neighbourhood(document, concept, **request),
        lambda result: result["centre"] is not None,
    )


def table_semantics(document: dict, semantics: dict | None, table: str) -> CatalogAnswer:
    """One table's semantics document whole (no command); exit 1 when it has none."""
    from .render.catalog_browse import table_semantics as one

    return _browse(
        lambda: one(document, semantics, table), lambda result: result["document"] is not None
    )


def table_units(document: dict, semantics: dict | None, table: str) -> CatalogAnswer:
    """The units of one table's measure columns, marked as ``catalog context`` marks them
    (no command); exit 1 when the catalog has no such table."""
    from .render.catalog_browse import table_units as units

    return _browse(
        lambda: units(document, semantics, table), lambda result: result["in_catalog"]
    )


def questions(
    document: dict,
    semantics: dict | None,
    pending_text: str | None = None,
    *,
    page_states: dict | None = None,
    **request,
) -> CatalogAnswer:
    """The board of registered questions (no command): the semantics documents' and, with
    ``pending_text`` (a pending file's text), the ``catalog pending list`` items.
    ``page_states`` marks what a browsing page answered or noted, and lets ``status`` be
    ``set_aside`` (``render.catalog_browse.questions_board``)."""
    from .render.catalog_browse import questions_board

    report = None
    if pending_text is not None:
        report = pending_answer(pending_text, document, semantics, status="all").result
    return _browse(lambda: questions_board(
        document, semantics, report, page_states=page_states, **request
    ))


# ------------------------------------------------------------------ page answers


QUESTION_TARGET = "question:"
ONLY_QUESTIONS = "only question:<id> answers are overlaid"


def overlay_answers(
    semantics: dict | None, confirmations: Iterable[dict]
) -> tuple[dict, list[dict]]:
    """``(semantics with the answers applied, the ones not applied)``.

    ``confirmations`` are ``semantic-confirmations/1`` entries a browsing page holds; only
    ``question:<id>`` targets are applied, by ``semantic confirm``'s own
    ``apply_confirmations``, to copies of the documents of the tables they name. The
    returned mapping keeps ``semantics``' keys, and every document no answer changed is
    the very object it was, so a caller's cache keyed by those objects stays valid;
    ``semantics`` and its documents are not changed. Each entry not applied is
    ``{table, target, reason}``: first the targets that are not questions, then those
    ``apply_confirmations`` refused (an unknown table or question, an empty answer, a
    question that no longer reads as ``asked``, an answer on disk changed without
    ``replace``). An entry it skipped -- the very answer is already on disk -- changes
    nothing and is not listed.
    """
    from .semantics.confirm import apply_confirmations
    from .semantics.names import bare_table

    semantics = semantics or {}
    keys: dict[str, str] = {}
    for key in semantics:
        keys.setdefault(bare_table(key), key)
    refused, wanted = [], []
    for entry in confirmations:
        if str(entry.get("target") or "").startswith(QUESTION_TARGET):
            wanted.append(entry)
        else:
            refused.append(
                {"table": entry.get("table"), "target": entry.get("target"), "reason": ONLY_QUESTIONS}
            )
    named = {bare_table(entry.get("table")) for entry in wanted}
    subset = {table: semantics[keys[table]] for table in named if table in keys}
    result = apply_confirmations(subset, wanted)
    changed = dict(semantics)
    for table in result.changed:
        changed[keys[table]] = result.documents[table]
    return changed, refused + result.unmatched
