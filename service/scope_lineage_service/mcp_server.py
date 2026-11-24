"""An MCP server over stdio exposing the catalog answer commands as tools.

Built on the official Python SDK (``mcp``), which speaks both the current per-request
protocol and the older initialize handshake, so this module only declares tools. Each
tool returns one text item: by default what the command prints, with ``format="json"``
exactly what it prints for ``--json`` (without the final newline). A nothing-found
answer is an ordinary result (the text says so); an input the command refuses is a tool
error carrying the command's own sentence. No tool runs SQL; ``add_pending`` -- offered
only when the server was started with a pending file -- is the one tool that writes, and
only to that file.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from scope_lineage.cli_catalog_answers import CatalogAnswer, CatalogAnswerError
from scope_lineage.render.catalog_query import QUERY_KINDS
from scope_lineage.render.catalog_search import SEARCH_KINDS

from . import __version__
from .state import CatalogState

SearchKind = Literal[SEARCH_KINDS]  # type: ignore[valid-type]
QueryKind = Literal[QUERY_KINDS]  # type: ignore[valid-type]
Format = Annotated[
    Literal["text", "json"],
    Field(description=(
        "text (default): the readable answer the command prints; json: the structured "
        "answer, exactly what the command prints with --json"
    )),
]
Tables = Annotated[list[str], Field(description="Tables as db.table (a catalog prefix is ignored)")]

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True,
                            openWorldHint=False)

INSTRUCTIONS = """\
Answers data questions from one ontology catalog (ontology-json/3) and, when given, the
table-semantics documents beside it. A usual walk: search_catalog to turn the asker's words
into the catalog's own names; catalog_context for the tables, columns and concepts the
question needs (keys, time columns, joins, constraints, metrics, how to read each table,
what to watch); write the SQL yourself; check_sql to hold it to the catalog before showing
it. query_catalog answers one exact lookup. Where the catalog gives no definition, write a
/* 待确认：… */ placeholder instead of guessing, and record it with add_pending when that
tool is offered. Nothing here runs SQL against any database."""


def _answer(produce, fmt: str) -> str:
    try:
        answer: CatalogAnswer = produce()
    except CatalogAnswerError as error:
        raise ToolError(error.message) from None
    return answer.json_text() if fmt == "json" else answer.text()


def build_server(state: CatalogState) -> MCPServer:
    """An MCP server answering from ``state``; ``run()`` serves it over stdio."""
    server = MCPServer(
        "scope-lineage-catalog", instructions=INSTRUCTIONS, version=__version__,
    )

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def search_catalog(
        text: Annotated[str, Field(description="A business word, a column name or a whole question")],
        kinds: Annotated[
            list[SearchKind] | None,
            Field(description="Only these kinds of catalog object; every kind when omitted"),
        ] = None,
        limit: Annotated[int, Field(ge=1, description="How many hits to return (default 10)")] = 10,
        format: Format = "text",
    ) -> str:
        """Find the catalog's own names for the asker's words: rank concepts, metrics,
        attributes, identifiers, code sets and tables against the text (also matching what
        each table's semantics document says it is) and return the best few to choose from.
        Use it first, before naming any table or column. Same as `scope-lineage catalog search`."""
        return _answer(lambda: state.search(text, kinds, limit), format)

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def catalog_context(
        tables: Annotated[
            list[str], Field(description="Tables to pack, as db.table: catalog facts, how to read it, one line a column")
        ] = [],  # pydantic copies a mutable default per call
        columns: Annotated[
            list[str], Field(description="Columns to answer in full, as db.table.column: binding, code values, derivation, notes")
        ] = [],
        columns_of_table: Annotated[
            list[str],
            Field(description=(
                "Column names looked up in every table given in tables (each item may be "
                "comma-separated; table.col pins one table), answered in full like columns"
            )),
        ] = [],
        concepts: Annotated[
            list[str], Field(description="Concepts by id, name, synonym or term: their tables, constraints, metrics")
        ] = [],
        brief: Annotated[
            bool, Field(description="A short table pack: columns by name only, cited rules without their SQL")
        ] = False,
        focus: Annotated[
            bool,
            Field(description=(
                "Keep only the watch items, open questions and rules that concern the requested "
                "columns (needs columns or columns_of_table)"
            )),
        ] = False,
        format: Format = "text",
    ) -> str:
        """Everything one question needs about a few tables, columns and concepts in one
        answer: keys, time columns, join targets, constraints and metrics from the catalog;
        how to read each table, what it is not for, what to watch and its open questions from
        the table-semantics documents. Name at least one table, column or concept. Same as
        `scope-lineage catalog context`."""
        request = dict(
            tables=tables, columns=columns, columns_of_table=columns_of_table,
            concepts=concepts, brief=brief, focus=focus,
        )
        return _answer(lambda: state.context(**request), format)

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def query_catalog(
        kind: Annotated[QueryKind, Field(description="What the term names")],
        term: Annotated[
            str,
            Field(description=(
                "An id, a name, a synonym or a term; db.table for a table; db.table.column for "
                "a column"
            )),
        ],
        format: Format = "text",
    ) -> str:
        """Answer one exact lookup from the catalog: a concept, a table, a column, an
        identifier, an attribute, or a concept's one-hop neighbours. An answer with no match
        says so. Same as `scope-lineage catalog query`."""
        return _answer(lambda: state.query(kind, term), format)

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def check_sql(
        sql: Annotated[str, Field(description="One or more SELECT statements, as text")],
        format: Format = "text",
    ) -> str:
        """Check hand-written SQL against the catalog before showing it: tables the catalog
        does not know, columns a table does not have, joins the catalog does not record,
        partition filters left out, sums inflated by a one-to-many join, code values outside a
        code set, and 待确认 placeholders. The SQL is parsed, never run. Same as
        `scope-lineage catalog check-sql`."""
        return _answer(lambda: state.check_sql(sql), format)

    if state.pending_path is not None:
        _add_pending_tools(server, state)
    return server


def _add_pending_tools(server: MCPServer, state: CatalogState) -> None:
    @server.tool(annotations=READ_ONLY, structured_output=False)
    def list_pending(format: Format = "text") -> str:
        """The definitions recorded as missing in this server's pending file, grouped by
        what is missing, with the questions behind each, the table-semantics questions that
        record the same column, the catalog objects that now carry the name and the owner's
        latest reply (groups a reply resolved or rejected are left out). Same as
        `scope-lineage catalog pending list`."""
        return _answer(state.pending_list, format)

    @server.tool(
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                    idempotentHint=False, openWorldHint=False),
        structured_output=False,
    )
    def add_pending(
        question: Annotated[str, Field(description="The question as the asker put it")],
        missing: Annotated[
            str | None,
            Field(description="What definition is missing, in the asker's words (or give sql)"),
        ] = None,
        sql: Annotated[
            str | None,
            Field(description="SQL text: one line is recorded per /* 待确认：… */ placeholder in it (instead of missing)"),
        ] = None,
        sql_name: Annotated[
            str | None, Field(description="With sql: the name the lines record for it")
        ] = None,
        term: Annotated[
            str | None, Field(description="With missing: the business word itself, when missing is a sentence")
        ] = None,
        tables: Annotated[
            list[str], Field(description="With missing: tables it concerns, as db.table")
        ] = [],
        columns: Annotated[
            list[str], Field(description="With missing: columns it concerns, as db.table.column")
        ] = [],
        proposed: Annotated[
            str | None, Field(description="With missing: a definition the asker proposes")
        ] = None,
        date: Annotated[
            str | None, Field(description="YYYY-MM-DD to record (default today)")
        ] = None,
        format: Format = "text",
    ) -> str:
        """Record a definition the catalog lacks in this server's pending file for the
        catalog's owner: give missing (one line) or sql (one line a 待确认 placeholder). Lines
        are only ever appended. Same as `scope-lineage catalog pending add`."""
        request = dict(
            question=question, missing=missing, sql=sql, sql_name=sql_name, term=term,
            tables=tables, columns=columns, proposed=proposed, date=date,
        )
        try:
            lines = state.pending_add(**request)
        except CatalogAnswerError as error:
            raise ToolError(error.message) from None
        if format == "json":
            return json.dumps({"appended": len(lines), "lines": lines}, ensure_ascii=False, indent=2)
        return f"Appended {len(lines)} missing definition(s) -> {state.pending_path}\n"


def serve_stdio(state: CatalogState) -> None:
    build_server(state).run(transport="stdio")
