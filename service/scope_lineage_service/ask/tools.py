"""The tools the model is offered: the catalog answers the walk uses, nothing else -- all
read-only (the model has no tool that writes the pending file; the asker records a gap with
the page's button).

Each tool calls one ``CatalogState`` answer -- the function the HTTP endpoint and the MCP
tool of the same name call -- with the parameters that endpoint accepts. The descriptions
are the MCP tools' own words (``service/tests/test_ask_tools.py`` holds them to
``mcp_server.py``), so the two ways a model reaches the catalog say the same thing.

A tool's result for the model is the command's text form (what it prints without
``--json``): on catalog samples it is two to four times shorter than the JSON and is
the form the walk is written against. The page gets a small structured summary of the
same answer (``data``) instead, so it can show candidates, the tables and columns taken
into the pack and each check's findings without parsing text.

Every input is checked against its tool's schema before anything runs: an unknown tool,
an unknown or mistyped argument, or SQL longer than the server's body limit is a tool
error (``is_error``), and so is an input the command itself refuses, with the command's
sentence. Model output never names a path: the paths are the ones the server started
with.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from scope_lineage.cli_catalog_answers import CatalogAnswer, CatalogAnswerError
from scope_lineage.render.catalog_query import QUERY_KINDS
from scope_lineage.render.catalog_search import SEARCH_KINDS

from ..state import CatalogState

DEFAULT_MAX_RESULT_CHARS = 200_000
SUMMARY_ITEMS = 50

_STRINGS = {"type": "array", "items": {"type": "string"}}


def _schema(properties: dict, required: tuple[str, ...] = ()) -> dict:
    return {
        "type": "object", "properties": properties, "required": list(required),
        "additionalProperties": False,
    }


# The MCP tools' descriptions (docstrings and Field descriptions), word for word.
SEARCH = {
    "name": "search_catalog",
    "description": (
        "Find the catalog's own names for the asker's words: rank concepts, metrics, "
        "attributes, identifiers, code sets and tables against the text (also matching what "
        "each table's semantics document says it is) and return the best few to choose from. "
        "Use it first, before naming any table or column. Same as `scope-lineage catalog search`."
    ),
    "input_schema": _schema({
        "text": {"type": "string",
                 "description": "A business word, a column name or a whole question"},
        "kinds": {"type": "array", "items": {"type": "string", "enum": list(SEARCH_KINDS)},
                  "description": "Only these kinds of catalog object; every kind when omitted"},
        "limit": {"type": "integer", "minimum": 1,
                  "description": "How many hits to return (default 10)"},
    }, ("text",)),
}
CONTEXT = {
    "name": "catalog_context",
    "description": (
        "Everything one question needs about a few tables, columns and concepts in one "
        "answer: keys, time columns, join targets, constraints and metrics from the catalog; "
        "how to read each table, what it is not for, what to watch and its open questions from "
        "the table-semantics documents. Name at least one table, column or concept. Same as "
        "`scope-lineage catalog context`."
    ),
    "input_schema": _schema({
        "tables": {**_STRINGS, "description": (
            "Tables to pack, as db.table: catalog facts, how to read it, one line a column")},
        "columns": {**_STRINGS, "description": (
            "Columns to answer in full, as db.table.column: binding, code values, derivation, notes")},
        "columns_of_table": {**_STRINGS, "description": (
            "Column names looked up in every table given in tables (each item may be "
            "comma-separated; table.col pins one table), answered in full like columns")},
        "concepts": {**_STRINGS, "description": (
            "Concepts by id, name, synonym or term: their tables, constraints, metrics")},
        "brief": {"type": "boolean", "description": (
            "A short table pack: columns by name only, cited rules without their SQL")},
        "focus": {"type": "boolean", "description": (
            "Keep only the watch items, open questions and rules that concern the requested "
            "columns (needs columns or columns_of_table)")},
    }),
}
QUERY = {
    "name": "query_catalog",
    "description": (
        "Answer one exact lookup from the catalog: a concept, a table, a column, an "
        "identifier, an attribute, or a concept's one-hop neighbours. An answer with no match "
        "says so. Same as `scope-lineage catalog query`."
    ),
    "input_schema": _schema({
        "kind": {"type": "string", "enum": list(QUERY_KINDS), "description": "What the term names"},
        "term": {"type": "string", "description": (
            "An id, a name, a synonym or a term; db.table for a table; db.table.column for a column")},
    }, ("kind", "term")),
}
CHECK_SQL = {
    "name": "check_sql",
    "description": (
        "Check hand-written SQL against the catalog before showing it: tables the catalog "
        "does not know, columns a table does not have, joins the catalog does not record, "
        "partition filters left out, sums inflated by a one-to-many join, code values outside a "
        "code set, and 待确认 placeholders. The SQL is parsed, never run. Same as "
        "`scope-lineage catalog check-sql`."
    ),
    "input_schema": _schema({
        "sql": {"type": "string", "description": "One or more SELECT statements, as text"},
    }, ("sql",)),
}
@dataclass
class ToolOutcome:
    """One tool call's result: ``text`` goes to the model, ``data`` to the page."""

    ok: bool
    text: str
    data: dict = field(default_factory=dict)
    exit_code: int | None = None


def check_input(schema: dict, args) -> str | None:
    """Why ``args`` does not fit ``schema`` (the subset of JSON Schema used above), or None."""
    if not isinstance(args, dict):
        return "the input must be a JSON object"
    properties = schema["properties"]
    unknown = sorted(set(args) - set(properties))
    if unknown:
        return f"unknown argument(s): {', '.join(unknown)}"
    for name in schema["required"]:
        if name not in args:
            return f"{name} is required"
    for name, value in args.items():
        problem = _check_value(name, properties[name], value)
        if problem:
            return problem
    return None


def _check_value(name: str, spec: dict, value) -> str | None:
    kind = spec["type"]
    if kind == "string":
        if not isinstance(value, str):
            return f"{name} takes a string"
        if "enum" in spec and value not in spec["enum"]:
            return f"{name} must be one of {', '.join(spec['enum'])}, not {value!r}"
    elif kind == "boolean":
        if not isinstance(value, bool):
            return f"{name} takes true or false"
    elif kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return f"{name} takes an integer"
        if value < spec.get("minimum", value):
            return f"{name} takes an integer >= {spec['minimum']}"
    elif kind == "array":
        if not isinstance(value, list):
            return f"{name} takes a list"
        for item in value:
            problem = _check_value(f"each item of {name}", spec["items"], item)
            if problem:
                return problem
    return None


class ToolBox:
    """The tools over one ``CatalogState``: all read-only. There is no ``add_pending``: a gap
    is recorded only when the asker agrees, by the page's button (``POST /api/pending``), never
    by the model. ``pending`` says whether the server has a pending file the page can write."""

    def __init__(
        self, state: CatalogState, *, max_sql: int, max_result_chars: int = DEFAULT_MAX_RESULT_CHARS
    ) -> None:
        self.state = state
        self.max_sql = max_sql
        self.max_result_chars = max_result_chars
        self.pending = state.pending_path is not None
        offered = [SEARCH, CONTEXT, QUERY, CHECK_SQL]
        self._tools = {tool["name"]: tool for tool in offered}

    def definitions(self) -> list[dict]:
        """The tool list, in one fixed order (it is part of the cached prompt prefix)."""
        return [dict(tool) for tool in self._tools.values()]

    def call(self, name: str, args) -> ToolOutcome:
        tool = self._tools.get(name)
        if tool is None:
            return ToolOutcome(False, f"no tool named {name!r}")
        problem = check_input(tool["input_schema"], args)
        if problem is None and name == "check_sql" and \
                len(args.get("sql") or "") > self.max_sql:
            problem = f"sql is longer than this server takes ({self.max_sql} characters)"
        if problem:
            return ToolOutcome(False, f"{name}: {problem}")
        try:
            return getattr(self, "_" + name)(**args)
        except CatalogAnswerError as error:
            return ToolOutcome(False, error.message, exit_code=error.exit_code)

    # ------------------------------------------------------------------ tools

    def _search_catalog(self, text: str, kinds=None, limit: int = 10) -> ToolOutcome:
        answer = self.state.search(text, kinds or None, limit)
        hits = [
            {key: hit.get(key) for key in ("kind", "id", "name", "where")}
            for hit in answer.result["hits"][:SUMMARY_ITEMS]
        ]
        return self._outcome(answer, {"text": text, "kinds": kinds or [], "hits": hits})

    def _catalog_context(self, tables=(), columns=(), columns_of_table=(), concepts=(),
                         brief: bool = False, focus: bool = False) -> ToolOutcome:
        answer = self.state.context(
            tables=list(tables), columns=list(columns), columns_of_table=list(columns_of_table),
            concepts=list(concepts), brief=brief, focus=focus,
        )
        pack = answer.result
        data = {
            "tables": [item["table"] for item in pack["tables"]][:SUMMARY_ITEMS],
            "columns": [f"{item['table']}.{item['column']}" for item in pack["columns"]][:SUMMARY_ITEMS],
            "concepts": [item.get("id") for item in pack["concepts"]][:SUMMARY_ITEMS],
            "missing": [f"{item.get('kind')} {item.get('term')}" for item in pack["missing"]][:SUMMARY_ITEMS],
            "brief": brief, "focus": focus,
        }
        return self._outcome(answer, data)

    def _query_catalog(self, kind: str, term: str) -> ToolOutcome:
        answer = self.state.query(kind, term)
        matches = [
            match.get("id") or match.get("table") or match.get("column") or match.get("name")
            for match in answer.result["matches"][:SUMMARY_ITEMS]
        ]
        return self._outcome(answer, {"kind": kind, "term": term, "matches": matches})

    def _check_sql(self, sql: str) -> ToolOutcome:
        answer = self.state.check_sql(sql)
        result = answer.result
        counts = {"error": 0, "warning": 0, "info": 0}
        for finding in result["findings"]:
            counts[finding["severity"]] = counts.get(finding["severity"], 0) + 1
        data = {
            "sql": sql,
            "errors": counts["error"], "warnings": counts["warning"], "infos": counts["info"],
            "findings": [
                {key: finding.get(key) for key in ("severity", "rule", "table", "column", "message")}
                for finding in result["findings"][:SUMMARY_ITEMS]
            ],
            "placeholders": placeholders_of(result),
        }
        return self._outcome(answer, data)

    def _outcome(self, answer: CatalogAnswer, data: dict) -> ToolOutcome:
        text = answer.text()
        if len(text) > self.max_result_chars:
            text = (text[: self.max_result_chars]
                    + f"\n（输出过长，只给出前 {self.max_result_chars} 个字符；用 brief、focus 或更少的表、列重跑）\n")
        data["chars"] = len(text)
        return ToolOutcome(True, text, data, answer.exit_code)


def placeholders_of(check_result: dict) -> list[dict]:
    """The 待确认 placeholders a ``check_sql`` answer found, with their table and column."""
    return [
        {key: item.get(key) for key in ("statement", "text", "written", "table", "column")}
        for item in check_result.get("placeholders", [])[:SUMMARY_ITEMS]
    ]
