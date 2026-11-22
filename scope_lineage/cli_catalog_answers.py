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
    """The columns a context pack answers in full, or the refusal of ``catalog context``.

    ``columns_of_table`` is ``--columns``: comma-separated names of the one table given.
    """
    tables, columns = list(tables), list(columns)
    columns_of_table, concepts = list(columns_of_table), list(concepts)
    if not (tables or columns or columns_of_table or concepts):
        raise CatalogAnswerError(
            2, "catalog context: name at least one --table, --column or --concept"
        )
    if columns_of_table:
        if len(tables) != 1:
            raise CatalogAnswerError(
                2,
                "catalog context: --columns names columns of one table; give exactly one "
                "--table, or use --column db.table.column",
            )
        columns += [
            f"{tables[0]}.{name.strip()}"
            for value in columns_of_table
            for name in value.split(",")
            if name.strip()
        ]
    if focus and not columns:
        raise CatalogAnswerError(
            2, "catalog context: --focus needs the columns to focus on (--column or --columns)"
        )
    return columns


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
) -> CatalogAnswer:
    from .render.catalog_context import context_pack, render_context_text

    tables, concepts = list(tables), list(concepts)
    full = context_columns(
        tables=tables, columns=columns, columns_of_table=columns_of_table,
        concepts=concepts, focus=focus,
    )
    pack = context_pack(
        document, semantics, tables=tables, columns=full, concepts=concepts,
        brief=brief, focus=focus,
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
    text: str, document: dict | None = None, semantics: dict | None = None
) -> CatalogAnswer:
    """``catalog pending list`` of a pending file's text."""
    from .render.catalog_pending import pending_report, read_pending, render_pending_text

    entries, problems = read_pending(text.splitlines())
    report = pending_report(entries, problems, document=document, semantics=semantics)
    return CatalogAnswer(report, 1 if problems else 0, render_pending_text)


def pending_list(
    path: str, document: dict | None = None, semantics: dict | None = None
) -> CatalogAnswer:
    return pending_answer(read_pending_file(path), document, semantics)
