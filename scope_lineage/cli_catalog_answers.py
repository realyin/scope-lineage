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
        report = pending_answer(pending_text, document, semantics).result
    return _browse(lambda: questions_board(
        document, semantics, report, page_states=page_states, **request
    ))


# ------------------------------------------------------------------ page answers


QUESTION_TARGET = "question:"
ONLY_QUESTIONS = "only question:<id> answers are overlaid"  # the reason before page targets
ONLY_PAGE_TARGETS = (
    "only the targets a browsing page answers are overlaid: question:<id>, summary.row "
    "{unique, grain_columns}, column:<c>.meaning (a text) and column:<c>.code_values (one "
    "{value, meaning})"
)
ROW_TARGET = "summary.row"
ROW_KEYS = frozenset({"unique", "grain_columns"})
CODE_KEYS = frozenset({"value", "meaning"})


def page_target(entry: dict) -> bool:
    """Whether ``entry`` is one of the shapes a browsing page produces: a ``question:<id>``
    answer, a ``summary.row`` object of exactly ``unique`` and ``grain_columns``, a
    ``column:<c>.meaning`` text, or a ``column:<c>.code_values`` single ``{value, meaning}``
    object (never a list: a list replaces every code value of the column)."""
    target, value = str(entry.get("target") or ""), entry.get("value")
    if target.startswith(QUESTION_TARGET):
        return True
    if target == ROW_TARGET:
        return isinstance(value, dict) and set(value) == ROW_KEYS
    column, _, slot = target.partition(".")
    if not column.startswith("column:") or len(column) == len("column:"):
        return False
    if slot == "meaning":
        return isinstance(value, str)
    if slot == "code_values":
        return isinstance(value, dict) and set(value) == CODE_KEYS
    return False


def overlay_answers(
    semantics: dict | None, confirmations: Iterable[dict], *, indexed: bool = False
) -> tuple[dict, list[dict]]:
    """``(semantics with the answers applied, the ones not applied)``.

    ``confirmations`` are ``semantic-confirmations/1`` entries a browsing page holds; only
    the shapes a page produces (``page_target``) are applied -- ``question:<id>`` answers,
    ``summary.row`` ``{unique, grain_columns}``, ``column:<c>.meaning`` and one
    ``column:<c>.code_values`` object --, by ``semantic confirm``'s own
    ``apply_confirmations``, to copies of the documents of the tables they name. The
    returned mapping keeps ``semantics``' keys, and every document no answer changed is
    the very object it was, so a caller's cache keyed by those objects stays valid;
    ``semantics`` and its documents are not changed. Each entry not applied is
    ``{table, target, reason}``: first the shapes no page produces (``ONLY_PAGE_TARGETS``),
    then those ``apply_confirmations`` refused (an unknown table, question or column, an
    empty answer, a question that no longer reads as ``asked``, an answer on disk changed
    without ``replace``). An entry it skipped -- the very answer is already on disk --
    changes nothing and is not listed. ``indexed``: each entry not applied also carries
    ``index``, its position in ``confirmations``, so a caller that grouped entries (one page
    record exported as a structured entry and a ``question:`` entry) can tell which group
    a refusal belongs to -- a structured target does not name its question.

    Entries are applied one by one, as ``semantic confirm`` applies them: the overlay has no
    groups. A caller that wants a record's entries to stand or fall together drops every
    entry of a record with a refusal and overlays again.
    """
    from .semantics.confirm import apply_confirmations
    from .semantics.names import bare_table

    semantics = semantics or {}
    confirmations = list(confirmations)
    keys: dict[str, str] = {}
    for key in semantics:
        keys.setdefault(bare_table(key), key)
    refused, wanted, positions = [], [], []
    for index, entry in enumerate(confirmations):
        if page_target(entry):
            wanted.append(entry)
            positions.append(index)
        else:
            item = {"table": entry.get("table"), "target": entry.get("target"),
                    "reason": ONLY_PAGE_TARGETS}
            if indexed:
                item["index"] = index
            refused.append(item)
    named = {bare_table(entry.get("table")) for entry in wanted}
    subset = {table: semantics[keys[table]] for table in named if table in keys}
    result = apply_confirmations(subset, wanted)
    changed = dict(semantics)
    for table in result.changed:
        changed[keys[table]] = result.documents[table]
    unmatched = result.unmatched
    if indexed:
        unmatched = [{**item, "index": positions[at]}
                     for item, at in zip(result.unmatched, result.unmatched_at)]
    return changed, refused + unmatched
