"""A read-only HTTP server for the catalog answer commands, on the standard library.

Every answer body is, byte for byte, what ``scope-lineage catalog <command> ... --json``
prints for the same input on the files the server was started with (``?format=text``:
what it prints without ``--json``). The command's exit code travels in the
``X-Scope-Lineage-Exit-Code`` header and in the status:

- exit 0 -> 200; exit 1 "nothing found" (search, query, context) -> 404 with the answer
  body; for ``check-sql`` (an error or a warning) and ``pending`` list (a line that is not
  an entry) exit 1 is still 200, the findings or problems being the answer;
- exit 2, an input the command refuses -> 400 ``{"error": {"kind": "bad_input", ...}}``;
  a pending add the command declines (exit 1, nothing written) -> 422;
- a started-with file that cannot be read now -> 503 ``input_unavailable``.

Safety: binds 127.0.0.1 unless told otherwise; requests name no path, the server reads only
the files it was started with; POST bodies are capped (``max_body``) and must declare
their length; a request whose Host or Origin is not this machine (or an allowed host) is
refused, which keeps a web page elsewhere from reaching the server through DNS rebinding;
``POST /api/pending`` takes only ``application/json``, which a browser cannot send to
another origin without a preflight this server never grants. No endpoint runs SQL, and
the pending file is the only thing written -- and, with ``--answers``, the answers file.
The ask panel's model has no tool that writes the pending file: a gap is posted only when
the asker clicks the page's 「记入待确认」, with ``unless_recorded`` so an item the file
already names is reported instead of appended again.

The browse page (``GET /``) is a fixed set of files packaged with this module
(``static/``), each served at one fixed path from ``STATIC_FILES``: no request path is ever
joined to a directory. Every response carries a ``Content-Security-Policy`` that lets a
page run only this server's own scripts and styles and connect only back to it, so
catalog text placed in the page cannot load or run anything. The page calls the browse
endpoints (``/api/browse``, ``/api/list``, ``/api/neighbourhood``, ``/api/semantics``,
``/api/units``, ``/api/questions``), which answer what ``cli_catalog_answers`` answers a view at a time;
they have no command of their own and answer JSON only.

The ask endpoints (``/api/ask...``) exist only when the server was started with ``--ask``
(otherwise 404 ``not_configured``, like the pending endpoints without ``--pending``): a
question is answered by a model on this server through the catalog tools
(``ask.service``), never in the browser. Every POST must come from this page's own
origin: an ``Origin`` header, when sent, must name exactly this server's host and port,
and a ``Sec-Fetch-Site`` header, when sent, must say ``same-origin`` -- so no other site
open in the browser, not even another port on this machine, can make the server spend
money or write the pending file. The ask POSTs take ``application/json`` only.

The answers endpoints (``/api/answers...``) exist only when the server was started with
``--answers`` (otherwise 404 ``not_configured``): the page answers a table-semantics
question, or leaves a note on it, in the answers file (``answers.py``, ``state.py``); the
semantics directory is never written. The two writing endpoints are refused (403) on a
server other machines can reach -- a non-loopback ``--host``, or any ``--allow-host`` --
unless it was started with ``--answers-allow-remote``: an answer's text reaches the
context pack, the ask panel's model and MCP. Every text is kept as typed, stripped only,
and refused when blank, too long, or carrying a line break or a control character.

The platform-result endpoints (``/api/probes``, ``/api/probe-results/draft``,
``/api/observations...``) exist only when the server was started with ``--probes``
(otherwise 404 ``not_configured``, and the endpoint list does not name them): the board
shows each question's queries, a pasted result becomes a draft nothing stores, and
「确认」 stores it in the answers file under the same guards as an answer (403 on a server
others reach without ``--answers-allow-remote``, 409 when the draft is not the one shown).
A pasted text is at most ``probes.MAX_PASTE`` characters.
"""

from __future__ import annotations

import ipaddress
import json
import sys
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import parse_qs, urlsplit

from scope_lineage.cli_catalog_answers import CatalogAnswerError
from scope_lineage.render.catalog_browse import (
    BOARD_PAGE_STATUSES,
    BOARD_SOURCES,
    BOARD_STATUSES,
    DEFAULT_LIMIT,
    LIST_KINDS,
    MAX_LIMIT,
    NEIGHBOURHOOD_LIMIT,
    NEIGHBOURHOOD_MAX,
    TABLE_SORTS,
)
from scope_lineage.render.catalog_query import QUERY_KINDS
from scope_lineage.render.catalog_search import SEARCH_KINDS

from . import __version__
from . import answers as records_file
from .ask.service import AskError
from .probes import MAX_PASTE
from .state import (
    AnswerRefused,
    AnswersNotConfigured,
    AnswersUnavailable,
    CatalogState,
    PendingNotConfigured,
    ProbesNotConfigured,
)

EXIT_HEADER = "X-Scope-Lineage-Exit-Code"
DEFAULT_MAX_BODY = 1024 * 1024
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
PENDING_FIELDS = {
    "question": str, "missing": str, "sql": str, "sql_name": str, "term": str,
    "tables": list, "columns": list, "proposed": str, "date": str,
}

# The page's files: request path -> (packaged file under static/, content type). Nothing
# outside this table is served, whatever the path says.
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/dom.js": ("dom.js", "text/javascript; charset=utf-8"),
    "/views.js": ("views.js", "text/javascript; charset=utf-8"),
    "/graph.js": ("graph.js", "text/javascript; charset=utf-8"),
    "/ask.js": ("ask.js", "text/javascript; charset=utf-8"),
    "/askview.js": ("askview.js", "text/javascript; charset=utf-8"),
}
ASK_NOT_CONFIGURED = (
    "this server was started without --ask: asking calls a model through the Anthropic API, "
    "costs money and sends catalog text to the model provider; start the server with --ask "
    "to enable it"
)
ASK_FIELDS = {"question": str, "conversation": str, "model": str}
ANSWER_FIELDS = {"table", "question", "asked", "seen", "kind", "answer", "reason", "choice",
                 "to", "by", "target", "value"}
ANSWERS_REMOTE_REFUSED = (
    "this server can be reached from other machines (a non-loopback --host, or --allow-host): "
    "it takes no answers, whose text reaches the context pack, the ask panel's model and MCP; "
    "start it with --answers-allow-remote to accept them anyway"
)
EXPORT_NAME = "semantic-confirmations.json"
DEFAULT_WAIT = 20
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "connect-src 'self'; font-src 'none'; object-src 'none'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)
PAGE_PARAMS = {
    "offset": "an integer >= 0 (default 0)",
    "limit": f"an integer from 1 to {MAX_LIMIT} (default {DEFAULT_LIMIT})",
}
BROWSE_NOTE = "JSON only; no command prints it (scope_lineage.cli_catalog_answers)."

FORMAT_PARAM = {"format": "json (default: what --json prints) or text (what the command prints)"}
ENDPOINTS = [
    {
        "method": "GET", "path": "/health",
        "description": "Whether the started-with files load now, their paths and counts.",
        "params": {},
    },
    {
        "method": "GET", "path": "/api",
        "description": "This list of endpoints.",
        "params": {},
    },
    {
        "method": "GET", "path": "/api/search",
        "description": (
            "From a business word or a whole question to the catalog's own names: rank "
            "concepts, metrics, attributes, identifiers, code sets and tables "
            "(catalog search). 404 when nothing is close."
        ),
        "params": {
            "text": "required: a word, a column name or a question",
            "kind": f"repeatable: only these kinds ({', '.join(SEARCH_KINDS)})",
            "limit": "how many hits, an integer >= 1 (default 10)",
            **FORMAT_PARAM,
        },
        "cli": "catalog search ONTOLOGY TEXT [--semantics DIR] [--kind K]... [--limit N] --json",
    },
    {
        "method": "GET", "path": "/api/context",
        "description": (
            "Everything one question needs about a few tables, columns and concepts in one "
            "pack (catalog context). Name at least one table, column or concept. 404 when "
            "nothing matches."
        ),
        "params": {
            "table": "repeatable: db.table",
            "column": "repeatable: db.table.column, answered in full",
            "columns": "repeatable: comma-separated column names, looked up in every table given",
            "concept": "repeatable: a concept id, name, synonym or term",
            "brief": "true/false: the short table pack",
            "focus": "true/false: narrow watch items and rules to the requested columns",
            **FORMAT_PARAM,
        },
        "cli": (
            "catalog context ONTOLOGY [--semantics DIR] [--table T]... [--column C]... "
            "[--columns COLS]... [--concept X]... [--brief] [--focus] --json"
        ),
    },
    {
        "method": "GET", "path": "/api/query",
        "description": "Answer one exact question from the catalog (catalog query). 404 when nothing matches.",
        "params": {
            "kind": f"required: {', '.join(QUERY_KINDS)}",
            "term": "required: an id, a name, a synonym, db.table or db.table.column",
            **FORMAT_PARAM,
        },
        "cli": "catalog query ONTOLOGY KIND TERM --json",
    },
    {
        "method": "POST", "path": "/api/check-sql",
        "description": (
            "Check hand-written SELECTs against the catalog (catalog check-sql). The SQL is "
            "parsed, never run. Exit code 1 in the header when there is an error or a warning."
        ),
        "params": {
            "body": "the SQL as text/plain, or application/json {\"sql\": \"...\"}",
            **FORMAT_PARAM,
        },
        "cli": "catalog check-sql ONTOLOGY FILE --json",
    },
    {
        "method": "GET", "path": "/api/pending", "pending": True,
        "description": (
            "The missing definitions recorded in the pending file, grouped, with the "
            "catalog objects and table-semantics questions that now answer them "
            "(catalog pending list)."
        ),
        "params": dict(FORMAT_PARAM),
        "cli": "catalog pending list PENDING --ontology ONTOLOGY [--semantics DIR] --json",
    },
    {
        "method": "POST", "path": "/api/pending", "pending": True,
        "description": (
            "Append one missing definition (missing) or one line a 待确认 placeholder of "
            "the SQL given (sql) to the pending file (catalog pending add). 201 with the "
            "lines written; 422 when the SQL has no placeholder. With unless_recorded, a "
            "missing the file already names (grouped as pending list groups) appends "
            "nothing: 200 with appended 0 and the existing item as recorded."
        ),
        "params": {
            "body": (
                "application/json: question (required), and exactly one of missing or sql; "
                "with missing: term, tables[], columns[], proposed; with sql: sql_name; "
                "date YYYY-MM-DD (default today); unless_recorded true/false (default false)"
            ),
        },
        "cli": "catalog pending add PENDING --question Q (--missing M | --from-sql FILE) ...",
    },
    {
        "method": "GET", "path": "/api/ask/status", "ask": True,
        "description": "Whether asking works now (and why not), the models a question may "
                       "use (id, label, provider kind, available and why not, the default), "
                       "caps and conversation limits. Never a model's URL or key. JSON only.",
        "params": {},
    },
    {
        "method": "POST", "path": "/api/ask", "ask": True,
        "description": (
            "Ask a data question: a model on this server answers it through the catalog tools "
            "(search, context, query, check-sql; none writes), following the skill's walk. 202 "
            "with the conversation and run ids; poll /api/ask/events. Never runs SQL. Costs "
            "money and sends catalog text to the model provider. 409 while the conversation "
            "is still answering."
        ),
        "params": {
            "body": "application/json: question (required); conversation (an id from an "
                    "earlier answer: a follow-up carrying its brief); model (a model id from "
                    "/api/ask/status, default the server's default; 400 unknown, 409 unavailable)",
        },
    },
    {
        "method": "GET", "path": "/api/ask/events", "ask": True,
        "description": "A run's events after number after, waiting up to wait seconds for the "
                       "next one; done when the run has finished. JSON only.",
        "params": {
            "conversation": "required: the conversation id",
            "run": "required: the run id",
            "after": "the last event number seen (default 0)",
            "wait": f"seconds to wait for an event, 0 to 25 (default {DEFAULT_WAIT})",
        },
    },
    {
        "method": "POST", "path": "/api/ask/cancel", "ask": True,
        "description": "Stop the conversation's running question.",
        "params": {"body": "application/json: conversation (required)"},
    },
    {
        "method": "GET", "path": "/api/ask/conversation", "ask": True,
        "description": "A conversation's questions and the brief the next one carries. JSON only.",
        "params": {"conversation": "required: the conversation id"},
    },
    {
        "method": "POST", "path": "/api/answers", "answers": True,
        "description": (
            "Answer one table-semantics question, or leave a note on it, in the answers file "
            "(one record per question; a new one replaces it). 201 with the record. 409 when "
            "the question or its answer is not what the page saw (asked, seen); 403 on a "
            "server other machines reach, unless started with --answers-allow-remote."
        ),
        "params": {
            "body": (
                "application/json: table, question (its id), kind (answer, partial, deferred, "
                "redirect, invalid, not_applicable), answer (kind answer) or reason (the "
                "others), choice (yes/no; answer and partial only), to (redirect: who to ask), "
                "by (who answers), asked (the question's text as shown), seen ({disk: the "
                "document's answer {answer, answered_by, answered_on} or null, record: the "
                "page record shown or null}); a structured answer adds target (summary.row, "
                "column:<c>.meaning, column:<c>.code_values) and value, its answer is an "
                "optional note, and seen gains slot (the slot as shown)"
            ),
        },
    },
    {
        "method": "POST", "path": "/api/answers/withdraw", "answers": True,
        "description": "Delete one page record. 404 when there is none; 409 when it is not "
                       "the one the page saw.",
        "params": {"body": "application/json: table, question, seen (the record as shown)"},
    },
    {
        "method": "GET", "path": "/api/answers/export", "answers": True,
        "description": (
            "The answers in effect as a semantic-confirmations/1 file, for `scope-lineage "
            "semantic confirm`; notes and answers not matched are left out. Writes nothing. "
            "JSON only."
        ),
        "params": {},
        "cli": "scope-lineage-service answers export ANSWERS --semantics DIR --out FILE",
    },
    {
        "method": "GET", "path": "/api/probes", "probes": True,
        "description": (
            "The platform queries of a table's questions from the --probes file "
            "(question-probes/1): each item's SQL, how to read its result, where it may land, "
            "and stale when its question no longer reads as asked. JSON only."
        ),
        "params": {"table": "required: db.table", "question": "optional: a question id"},
    },
    {
        "method": "POST", "path": "/api/probe-results/draft", "probes": True,
        "description": (
            "Read one pasted platform result (the result JSON a query run hands back) for a "
            "probe: draft ({target, value, evidence}) for a query that lands, evidence (the "
            "reference {probe, partition, on, sha256}) for one that does not, or refused with "
            "the reason; and pasted_sha256. Writes nothing. A sentence answer backed by a "
            "result that lands nothing: POST /api/answers with probe_result {probe, pasted}."
        ),
        "params": {"body": "application/json: probe (its id), pasted (the result text)"},
    },
    {
        "method": "POST", "path": "/api/observations", "probes": True, "answers": True,
        "description": (
            "Confirm a drafted observation: the pasted text is read again and stored under "
            "observations in the answers file. 201 with the record; 409 when the draft is not "
            "the one shown (seen); 400 when there is no draft or the document would refuse it; "
            "403 on a server other machines reach, unless started with --answers-allow-remote."
        ),
        "params": {"body": "application/json: probe, pasted, by (who confirms), seen (the "
                           "draft as shown, with pasted_sha256)"},
    },
    {
        "method": "POST", "path": "/api/observations/withdraw", "probes": True, "answers": True,
        "description": "Delete one observation record. 404 when there is none; 409 when it is "
                       "not the one the page saw.",
        "params": {"body": "application/json: seen (the record as shown)"},
    },
    {
        "method": "GET", "path": "/",
        "description": "The browse page (HTML); its scripts and styles are served beside it.",
        "params": {},
    },
    {
        "method": "GET", "path": "/api/browse",
        "description": "The catalog's name and counts, each domain with how many concepts, "
                       "tables and metrics it holds, and the summary catalog render puts "
                       "first in index.md (use_first; its table-semantics rows only with "
                       "--semantics). " + BROWSE_NOTE,
        "params": {},
    },
    {
        "method": "GET", "path": "/api/list",
        "description": "One page of concepts, tables or metrics, filtered, with the total. "
                       "With --semantics, each table carries its row of index.md's by-table "
                       "section (by_table). An empty page is 200. " + BROWSE_NOTE,
        "params": {
            "kind": f"required: {', '.join(LIST_KINDS)}",
            "domain": "a domain id",
            "concept": "tables and metrics of this concept (id, name, synonym or term)",
            "text": "a piece of the id, name or synonym (of a table: its name), ignoring case",
            "sort": (
                f"tables only: {', '.join(TABLE_SORTS)}, with - before it for largest first "
                "(default: by name); over the whole filtered list, a table without a "
                "document last; all but table need --semantics"
            ),
            **PAGE_PARAMS,
        },
    },
    {
        "method": "GET", "path": "/api/neighbourhood",
        "description": "A concept, the concepts one relation or role away, and the relations "
                       "between them with their join conditions. 404 when no concept "
                       "matches. " + BROWSE_NOTE,
        "params": {
            "concept": "required: a concept id, name, synonym or term",
            "limit": f"at most this many neighbours, 1 to {NEIGHBOURHOOD_MAX} "
                     f"(default {NEIGHBOURHOOD_LIMIT})",
        },
    },
    {
        "method": "GET", "path": "/api/semantics",
        "description": "One table's table-semantics document, whole. 404 when it has none. "
                       + BROWSE_NOTE,
        "params": {"table": "required: db.table"},
    },
    {
        "method": "GET", "path": "/api/units",
        "description": "The unit of each of one table's measure columns, with the mark the "
                       "context pack prints when the table-semantics documents do not give "
                       "it (only with --semantics). 404 when the catalog has no such table. "
                       + BROWSE_NOTE,
        "params": {"table": "required: db.table"},
    },
    {
        "method": "GET", "path": "/api/questions",
        "description": "The registered questions: the table-semantics documents' and the "
                       "pending file's (when given), each with its concepts and whether "
                       "the catalog carries it. " + BROWSE_NOTE,
        "params": {
            "table": "db.table",
            "concept": "a concept id, name, synonym or term",
            "status": f"{', '.join(BOARD_STATUSES)} (default open)",
            "source": ", ".join(BOARD_SOURCES),
            "text": "a piece of the question, the missing definition or the table name",
            **PAGE_PARAMS,
        },
    },
]


class RequestError(Exception):
    def __init__(self, status: int, kind: str, message: str, exit_code: int | None = None):
        super().__init__(message)
        self.status, self.kind, self.message, self.exit_code = status, kind, message, exit_code


def _bad(message: str) -> RequestError:
    return RequestError(400, "bad_input", message, 2)


class _Params:
    """A query string, held to the parameters an endpoint knows."""

    def __init__(self, query: str, allowed: set[str]) -> None:
        try:
            self.values = parse_qs(query, keep_blank_values=True, strict_parsing=False,
                                   errors="strict")
        except UnicodeDecodeError as error:
            raise _bad(f"the query string is not UTF-8: {error}") from error
        unknown = sorted(set(self.values) - allowed - {"format"})
        if unknown:
            raise _bad(f"unknown parameter(s): {', '.join(unknown)}")

    def many(self, name: str) -> list[str]:
        return self.values.get(name, [])

    def one(self, name: str, required: bool = False) -> str | None:
        values = self.many(name)
        if len(values) > 1:
            raise _bad(f"{name} is given more than once")
        if not values or values[0] == "":
            if required:
                raise _bad(f"{name} is required")
            return None
        return values[0]

    def flag(self, name: str) -> bool:
        value = self.one(name)
        if value is None:
            return False
        lowered = value.lower()
        if lowered in ("1", "true", "yes"):
            return True
        if lowered in ("0", "false", "no"):
            return False
        raise _bad(f"{name} takes true or false, not {value!r}")

    def integer(self, name: str, default: int) -> int:
        value = self.one(name)
        if value is None:
            return default
        try:
            return int(value)
        except ValueError:
            raise _bad(f"{name} takes an integer, not {value!r}") from None

    def json_only(self) -> None:
        if self.format() != "json":
            raise _bad("the browse endpoints answer JSON only")

    def format(self) -> str:
        value = self.one("format") or "json"
        if value not in ("json", "text"):
            raise _bad(f"format takes json or text, not {value!r}")
        return value


def _host_of(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("["):
        return value[1:].split("]", 1)[0]
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


class CatalogHandler(BaseHTTPRequestHandler):
    server_version = f"scope-lineage-service/{__version__}"
    protocol_version = "HTTP/1.1"
    timeout = 30  # a client that stops sending does not hold a thread for ever

    # The server instance carries: state, max_body, allowed_hosts, quiet, ask.

    def log_message(self, format, *args):
        if not self.server.quiet:
            sys.stderr.write(f"{self.address_string()} - {format % args}\n")

    # ------------------------------------------------------------------ dispatch

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        if method == "GET" and self.headers.get("Content-Length", "0") != "0":
            self.close_connection = True  # a GET body is never read
        try:
            self._check_host()
            if method == "POST":
                self._check_same_origin()
            path, _, query = self.path.partition("?")
            routes = self._routes()
            if path not in routes:
                raise RequestError(404, "not_found", f"no endpoint {path}; GET /api lists them")
            handler = routes[path].get(method)
            if handler is None:
                allowed = ", ".join(sorted(routes[path]))
                raise RequestError(405, "method_not_allowed", f"{path} takes {allowed}")
            handler(query)
        except RequestError as error:
            headers = {}
            if error.status == 405:
                path = self.path.partition("?")[0]
                headers["Allow"] = ", ".join(sorted(self._routes()[path]))
            self._send_error(error, headers)
        except (PendingNotConfigured, AnswersNotConfigured, ProbesNotConfigured) as error:
            self._send_error(RequestError(404, "not_configured", error.message))
        except AnswersUnavailable as error:
            self._send_error(RequestError(503, "answers_unavailable", error.message))
        except AnswerRefused as error:
            self._send_error(RequestError(error.status, error.kind, error.message))
        except AskError as error:
            self._send_error(RequestError(error.status, error.kind, error.message))

    def _routes(self) -> dict:
        routes = {
            **{path: {"GET": self._static} for path in STATIC_FILES},
            "/health": {"GET": self._health},
            "/api": {"GET": self._endpoints},
            "/api/search": {"GET": self._search},
            "/api/context": {"GET": self._context},
            "/api/query": {"GET": self._query},
            "/api/check-sql": {"POST": self._check_sql},
            # Answered 404 not_configured when the server has no pending file.
            "/api/pending": {"GET": self._pending_list, "POST": self._pending_add},
            "/api/browse": {"GET": self._browse},
            "/api/list": {"GET": self._list},
            "/api/neighbourhood": {"GET": self._neighbourhood},
            "/api/semantics": {"GET": self._semantics},
            "/api/units": {"GET": self._units},
            "/api/questions": {"GET": self._questions},
            # Answered 404 not_configured when the server was started without --answers.
            "/api/answers": {"POST": self._answer_post},
            "/api/answers/withdraw": {"POST": self._answer_withdraw},
            "/api/answers/export": {"GET": self._answer_export},
            # Answered 404 not_configured when the server was started without --probes.
            "/api/probes": {"GET": self._probes},
            "/api/probe-results/draft": {"POST": self._probe_draft},
            "/api/observations": {"POST": self._observation_post},
            "/api/observations/withdraw": {"POST": self._observation_withdraw},
            # Answered 404 not_configured when the server was started without --ask.
            "/api/ask/status": {"GET": self._ask_status},
            "/api/ask": {"POST": self._ask},
            "/api/ask/events": {"GET": self._ask_events},
            "/api/ask/cancel": {"POST": self._ask_cancel},
            "/api/ask/conversation": {"GET": self._ask_conversation},
        }
        return routes

    def _check_host(self) -> None:
        allowed = self.server.allowed_hosts
        host = self.headers.get("Host")
        if host is not None and _host_of(host) not in allowed:
            raise RequestError(403, "forbidden_host", f"Host {host!r} is not served here")
        origin = self.headers.get("Origin")
        if origin is not None:
            netloc = urlsplit(origin).netloc
            if not netloc or _host_of(netloc) not in allowed:
                raise RequestError(403, "forbidden_origin", f"Origin {origin!r} is not served here")

    def _check_same_origin(self) -> None:
        """A POST comes from this server's own page, or from no browser page at all."""
        site = self.headers.get("Sec-Fetch-Site")
        if site is not None and site.strip().lower() not in ("same-origin", "none"):
            raise RequestError(403, "forbidden_origin",
                               f"a POST from another site (Sec-Fetch-Site: {site}) is refused")
        origin = self.headers.get("Origin")
        if origin is not None:
            host = (self.headers.get("Host") or "").strip().lower()
            if not host or urlsplit(origin.strip()).netloc.lower() != host:
                raise RequestError(403, "forbidden_origin",
                                   f"a POST from another origin ({origin!r}) is refused")

    # ------------------------------------------------------------------ endpoints

    def _endpoints(self, query: str) -> None:
        _Params(query, set())
        configured = self.server.state.pending_path is not None
        asking = self.server.ask is not None
        answering = self.server.state.answers_path is not None
        probing = self.server.state.probes is not None
        listing = [
            {key: value for key, value in item.items()
             if key not in ("pending", "ask", "answers", "probes")}
            for item in ENDPOINTS
            if (configured or not item.get("pending")) and (asking or not item.get("ask"))
            and (answering or not item.get("answers")) and (probing or not item.get("probes"))
        ]
        if answering:
            for item in listing:
                if item["path"] == "/api/questions":
                    item["params"] = {**item["params"],
                                      "status": f"{', '.join(BOARD_PAGE_STATUSES)} (default open)"}
        body = {
            "service": "scope-lineage-service", "version": __version__,
            "read_only": True, "executes_sql": False, "asks_a_model": asking,
            "exit_code_header": EXIT_HEADER, "endpoints": listing,
        }
        if answering:
            body["answers"] = self._answers_status()
        self._send_json(200, body)

    def _answers_status(self) -> dict:
        """Whether the page may answer now, and why not: the answers file's status and the
        remote switch. The page reads this to show answer boxes or read-only cards."""
        health = self.server.state.health().get("answers") or {}
        status = {"status": health.get("status"), "writable": False}
        if health.get("reason"):
            status["reason"] = self.server.state.public_text(health["reason"])
        if self.server.answers_remote_refused:
            status["refused"] = ANSWERS_REMOTE_REFUSED
        elif health.get("status") == "ok":
            status["writable"] = True
        return status

    def _health(self, query: str) -> None:
        _Params(query, set())
        health = self.server.state.health()
        if health.get("problem"):
            health["problem"] = self.server.state.public_text(health["problem"])
        for key in ("reason", "problem"):
            if (health.get("answers") or {}).get(key):
                health["answers"][key] = self.server.state.public_text(health["answers"][key])
        self._send_json(200, health)

    def _search(self, query: str) -> None:
        params = _Params(query, {"text", "kind", "limit"})
        text = params.one("text", required=True)
        kinds = params.many("kind")
        for kind in kinds:
            if kind not in SEARCH_KINDS:
                raise _bad(f"kind must be one of {', '.join(SEARCH_KINDS)}, not {kind!r}")
        limit = params.one("limit") or "10"
        try:
            number = int(limit)
        except ValueError:
            raise _bad(f"limit takes an integer, not {limit!r}") from None
        if number < 1:
            raise _bad("limit takes an integer >= 1")
        fmt = params.format()
        self._answer(lambda: self.server.state.search(text, kinds or None, number), fmt,
                     nothing_found=404)

    def _context(self, query: str) -> None:
        params = _Params(query, {"table", "column", "columns", "concept", "brief", "focus"})
        request = dict(
            tables=params.many("table"), columns=params.many("column"),
            columns_of_table=params.many("columns"), concepts=params.many("concept"),
            brief=params.flag("brief"), focus=params.flag("focus"),
        )
        fmt = params.format()
        self._answer(lambda: self.server.state.context(**request), fmt, nothing_found=404)

    def _query(self, query: str) -> None:
        params = _Params(query, {"kind", "term"})
        kind = params.one("kind", required=True)
        term = params.one("term", required=True)
        fmt = params.format()
        self._answer(lambda: self.server.state.query(kind, term), fmt, nothing_found=404)

    def _check_sql(self, query: str) -> None:
        params = _Params(query, set())
        fmt = params.format()
        body, content_type = self._read_body()
        if content_type == "application/json":
            payload = self._json_object(body)
            if set(payload) != {"sql"} or not isinstance(payload["sql"], str):
                raise _bad('a JSON body is {"sql": "..."}')
            sql = payload["sql"]
        else:
            sql = self._utf8(body)
        self._answer(lambda: self.server.state.check_sql(sql), fmt, nothing_found=200)

    def _pending_list(self, query: str) -> None:
        params = _Params(query, set())
        fmt = params.format()
        self._answer(self.server.state.pending_list, fmt, nothing_found=200)

    def _pending_add(self, query: str) -> None:
        _Params(query, set())
        body, content_type = self._read_body()
        if content_type != "application/json":
            raise RequestError(415, "unsupported_media_type",
                               "POST /api/pending takes application/json")
        payload = self._json_object(body)
        unless_recorded = payload.pop("unless_recorded", False)
        if not isinstance(unless_recorded, bool):
            raise _bad("unless_recorded takes true or false")
        unknown = sorted(set(payload) - set(PENDING_FIELDS))
        if unknown:
            raise _bad(f"unknown field(s): {', '.join(unknown)}")
        for name, value in payload.items():
            expected = PENDING_FIELDS[name]
            if value is None:
                continue
            if not isinstance(value, expected) or (
                expected is list and not all(isinstance(item, str) for item in value)
            ):
                kind = "a list of strings" if expected is list else "a string"
                raise _bad(f"{name} takes {kind}")
        if not isinstance(payload.get("question"), str):
            raise _bad("question is required")
        request = {key: value for key, value in payload.items() if value is not None}
        recorded = None
        try:
            if unless_recorded:
                lines, recorded = self.server.state.pending_add_unless_recorded(**request)
            else:
                lines = self.server.state.pending_add(**request)
        except CatalogAnswerError as error:
            status, kind = (422, "not_added") if error.exit_code == 1 else (400, "bad_input")
            raise RequestError(status, kind, error.message, error.exit_code) from None
        if recorded is not None:
            # Already in the file: nothing appended, the existing item answers instead.
            self._send_json(200, {"appended": 0, "lines": [], "recorded": recorded}, exit_code=0)
            return
        self._send_json(201, {"appended": len(lines), "lines": lines}, exit_code=0)

    # ------------------------------------------------------------------ browse page

    def _static(self, query: str) -> None:
        if query:
            raise _bad("the page's files take no parameters")
        name, content_type = STATIC_FILES[self.path.partition("?")[0]]
        self._send(200, _static_bytes(name), content_type, {})

    def _browse(self, query: str) -> None:
        _Params(query, set()).json_only()
        self._answer(self.server.state.browse_index, "json", nothing_found=404)

    def _list(self, query: str) -> None:
        params = _Params(query, {"kind", "domain", "concept", "text", "sort", "offset", "limit"})
        params.json_only()
        kind = params.one("kind", required=True)
        request = dict(
            domain=params.one("domain"), concept=params.one("concept"), text=params.one("text"),
            sort=params.one("sort"),
            offset=params.integer("offset", 0), limit=params.integer("limit", DEFAULT_LIMIT),
        )
        self._answer(lambda: self.server.state.browse_list(kind, **request), "json",
                     nothing_found=200)

    def _neighbourhood(self, query: str) -> None:
        params = _Params(query, {"concept", "limit"})
        params.json_only()
        concept = params.one("concept", required=True)
        limit = params.integer("limit", NEIGHBOURHOOD_LIMIT)
        self._answer(lambda: self.server.state.neighbourhood(concept, limit=limit), "json",
                     nothing_found=404)

    def _units(self, query: str) -> None:
        params = _Params(query, {"table"})
        params.json_only()
        table = params.one("table", required=True)
        self._answer(lambda: self.server.state.table_units(table), "json", nothing_found=404)

    def _semantics(self, query: str) -> None:
        params = _Params(query, {"table"})
        params.json_only()
        table = params.one("table", required=True)
        self._answer(lambda: self.server.state.table_semantics(table), "json",
                     nothing_found=404)

    def _questions(self, query: str) -> None:
        params = _Params(
            query, {"table", "concept", "status", "source", "text", "offset", "limit"}
        )
        params.json_only()
        request = dict(
            table=params.one("table"), concept=params.one("concept"),
            status=params.one("status") or "open", source=params.one("source"),
            text=params.one("text"), offset=params.integer("offset", 0),
            limit=params.integer("limit", DEFAULT_LIMIT),
        )
        self._answer(lambda: self._board(request), "json", nothing_found=200)

    def _board(self, request: dict):
        answer = self.server.state.questions(**request)
        if "answers" in answer.result:
            summary = answer.result["answers"]
            status = self._answers_status()
            summary["writable"] = status["writable"]
            for key in ("reason", "refused"):
                if key in status:
                    summary[key] = status[key]
            if summary.get("problem"):
                summary["problem"] = self.server.state.public_text(summary["problem"])
        return answer

    # ------------------------------------------------------------------ answers

    def _answers_writable(self) -> None:
        if self.server.state.answers_path is None:
            raise AnswersNotConfigured()
        if self.server.answers_remote_refused:
            raise RequestError(403, "forbidden_remote", ANSWERS_REMOTE_REFUSED)

    def _answer_post(self, query: str) -> None:
        _Params(query, set())
        self._answers_writable()
        probing = self.server.state.probes is not None
        payload = self._answer_payload(ANSWER_FIELDS | ({"probe_result"} if probing else set()))
        request = _answer_request(payload)
        if payload.get("probe_result") is not None:
            if request.get("target") is not None:
                raise _bad("a structured answer rests on no query result: confirm the result "
                           "as an observation")
            request["probe_result"] = _probe_paste(payload["probe_result"])
        record = self.server.state.save_answer(request)
        self._send_json(201, {"record": record})

    def _answer_withdraw(self, query: str) -> None:
        _Params(query, set())
        self._answers_writable()
        payload = self._answer_payload({"table", "question", "seen"})
        for name in ("table", "question"):
            if not isinstance(payload.get(name), str) or not payload[name].strip():
                raise _bad(f"{name} is required")
        if not isinstance(payload.get("seen"), dict):
            raise _bad("seen is the record as the page showed it")
        record = self.server.state.withdraw_answer(payload["table"], payload["question"],
                                                   payload["seen"])
        self._send_json(200, {"withdrawn": record})

    def _answer_export(self, query: str) -> None:
        _Params(query, set()).json_only()
        document = self.server.state.export_answers()
        body = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        self._send(200, body, "application/json; charset=utf-8",
                   {"Content-Disposition": f'attachment; filename="{EXPORT_NAME}"'})

    # ------------------------------------------------------------------ platform results

    def _probes(self, query: str) -> None:
        params = _Params(query, {"table", "question"})
        params.json_only()
        if self.server.state.probes is None:
            raise ProbesNotConfigured()
        table = params.one("table", required=True)
        self._send_json(200, self.server.state.probes_for(table, params.one("question")))

    def _probe_draft(self, query: str) -> None:
        _Params(query, set())
        if self.server.state.probes is None:
            raise ProbesNotConfigured()
        paste = _probe_paste(self._answer_payload({"probe", "pasted"}))
        self._send_json(200, self.server.state.probe_draft(paste["probe"], paste["pasted"]))

    def _observation_post(self, query: str) -> None:
        _Params(query, set())
        if self.server.state.probes is None:
            raise ProbesNotConfigured()
        self._answers_writable()
        payload = self._answer_payload({"probe", "pasted", "by", "seen"})
        request = _probe_paste(payload)
        if not isinstance(payload.get("seen"), dict):
            raise _bad("seen is the draft as the page showed it, with pasted_sha256")
        try:
            request["by"] = records_file.clean_text(payload.get("by"), "by", records_file.MAX_NAME)
        except records_file.TextRefused as error:
            raise _bad(str(error)) from None
        request["seen"] = payload["seen"]
        record = self.server.state.confirm_observation(request)
        self._send_json(201, {"observation": record})

    def _observation_withdraw(self, query: str) -> None:
        _Params(query, set())
        if self.server.state.probes is None:
            raise ProbesNotConfigured()
        self._answers_writable()
        payload = self._answer_payload({"seen"})
        if not isinstance(payload.get("seen"), dict):
            raise _bad("seen is the observation record as the page showed it")
        record = self.server.state.withdraw_observation(payload["seen"])
        self._send_json(200, {"withdrawn": record})

    def _answer_payload(self, fields: set) -> dict:
        body, content_type = self._read_body()
        if content_type != "application/json":
            raise RequestError(415, "unsupported_media_type",
                               f"POST {self.path.partition('?')[0]} takes application/json")
        payload = self._json_object(body)
        unknown = sorted(set(payload) - fields)
        if unknown:
            raise _bad(f"unknown field(s): {', '.join(unknown)}")
        return payload

    # ------------------------------------------------------------------ ask

    def _asking(self):
        if self.server.ask is None:
            raise RequestError(404, "not_configured", ASK_NOT_CONFIGURED)
        return self.server.ask

    def _ask_status(self, query: str) -> None:
        _Params(query, set()).json_only()
        self._send_json(200, self._asking().status())

    def _ask(self, query: str) -> None:
        _Params(query, set())
        service = self._asking()
        payload = self._json_request(ASK_FIELDS)
        if not isinstance(payload.get("question"), str):
            raise _bad("question is required")
        conversation, run = service.ask(payload["question"], payload.get("conversation"),
                                        payload.get("model"))
        self._send_json(202, {"conversation": conversation.id, "run": run.id,
                              "follow_up": bool(run.brief), "model": run.model_id})

    def _ask_events(self, query: str) -> None:
        params = _Params(query, {"conversation", "run", "after", "wait"})
        params.json_only()
        service = self._asking()
        conversation = params.one("conversation", required=True)
        run = params.one("run", required=True)
        after, wait = params.integer("after", 0), params.integer("wait", DEFAULT_WAIT)
        if after < 0 or not 0 <= wait <= 25:
            raise _bad("after takes an integer >= 0 and wait one from 0 to 25")
        self._send_json(200, service.events(conversation, run, after, wait))

    def _ask_cancel(self, query: str) -> None:
        _Params(query, set())
        service = self._asking()
        payload = self._json_request({"conversation": str})
        if not isinstance(payload.get("conversation"), str):
            raise _bad("conversation is required")
        self._send_json(200, service.cancel(payload["conversation"]))

    def _ask_conversation(self, query: str) -> None:
        params = _Params(query, {"conversation"})
        params.json_only()
        service = self._asking()
        self._send_json(200, service.conversation(params.one("conversation", required=True)))

    def _json_request(self, fields: dict) -> dict:
        """A JSON object body holding only ``fields`` (name -> type; null means absent)."""
        body, content_type = self._read_body()
        if content_type != "application/json":
            raise RequestError(415, "unsupported_media_type",
                               f"POST {self.path.partition('?')[0]} takes application/json")
        payload = self._json_object(body)
        unknown = sorted(set(payload) - set(fields))
        if unknown:
            raise _bad(f"unknown field(s): {', '.join(unknown)}")
        for name, value in payload.items():
            if value is not None and not isinstance(value, fields[name]):
                raise _bad(f"{name} takes a string")
        return {key: value for key, value in payload.items() if value is not None}

    # ------------------------------------------------------------------ helpers

    def _answer(self, produce, fmt: str, nothing_found: int) -> None:
        """Run one answer; a refusal of the started-with files is 503, of the request 400."""
        state: CatalogState = self.server.state
        try:
            state.inputs()
        except CatalogAnswerError as error:
            raise RequestError(503, "input_unavailable", error.message, error.exit_code) from None
        try:
            answer = produce()
        except CatalogAnswerError as error:
            raise RequestError(400, "bad_input", error.message, error.exit_code) from None
        status = 200 if answer.exit_code == 0 else nothing_found
        if fmt == "text":
            body, content_type = answer.text().encode("utf-8"), "text/plain; charset=utf-8"
        else:
            body = (answer.json_text() + "\n").encode("utf-8")
            content_type = "application/json; charset=utf-8"
        self._send(status, body, content_type, {EXIT_HEADER: str(answer.exit_code)})

    def _read_body(self) -> tuple[bytes, str]:
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            raise RequestError(411, "length_required", "send Content-Length, not chunked")
        length = self.headers.get("Content-Length")
        if length is None:
            raise RequestError(411, "length_required", "a POST needs Content-Length")
        try:
            size = int(length)
        except ValueError:
            raise _bad("Content-Length is not an integer") from None
        if size < 0:
            raise _bad("Content-Length is negative")
        if size > self.server.max_body:
            raise RequestError(413, "too_large",
                               f"the body is {size} bytes; this server takes at most "
                               f"{self.server.max_body}")
        body = self.rfile.read(size)
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        return body, content_type

    @staticmethod
    def _utf8(body: bytes) -> str:
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError as error:
            raise _bad(f"the body is not UTF-8: {error}") from None

    def _json_object(self, body: bytes) -> dict:
        try:
            payload = json.loads(self._utf8(body))
        except ValueError as error:
            raise _bad(f"the body is not JSON: {error}") from None
        if not isinstance(payload, dict):
            raise _bad("the body must be a JSON object")
        return payload

    def _send_json(self, status: int, payload: dict, exit_code: int | None = None) -> None:
        body = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        headers = {EXIT_HEADER: str(exit_code)} if exit_code is not None else {}
        self._send(status, body, "application/json; charset=utf-8", headers)

    def _send_error(self, error: RequestError, headers: dict | None = None) -> None:
        # A refused request may leave an unread body on the socket: never reuse it.
        self.close_connection = True
        # The core names a file by its full path; over HTTP only its name leaves.
        message = self.server.state.public_text(error.message)
        payload = {"kind": error.kind, "message": message}
        if error.exit_code is not None:
            payload = {"kind": error.kind, "exit_code": error.exit_code, "message": message}
        headers = dict(headers or {})
        if error.exit_code is not None:
            headers[EXIT_HEADER] = str(error.exit_code)
        body = (json.dumps({"error": payload}, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        self._send(error.status, body, "application/json; charset=utf-8", headers)

    def _send(self, status: int, body: bytes, content_type: str, headers: dict) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        for name, value in headers.items():
            self.send_header(name, value)
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)


@lru_cache(maxsize=None)
def _static_bytes(name: str) -> bytes:
    """A packaged page file, read once; ``name`` comes from ``STATIC_FILES`` only."""
    return (resources.files(__package__) / "static" / name).read_bytes()


def _answer_request(payload: dict) -> dict:
    """``POST /api/answers``'s body held to its fields, its texts cleaned (``_bad`` when
    one is refused)."""
    kind = payload.get("kind")
    if kind not in records_file.KINDS:
        raise _bad(f"kind must be one of {', '.join(records_file.KINDS)}")
    text_key, other = ("answer", "reason") if kind == records_file.ANSWER else ("reason", "answer")
    if payload.get(other) is not None:
        raise _bad(f"a {kind} carries {text_key}, not {other}")
    for name in ("table", "question", "asked"):
        if not isinstance(payload.get(name), str) or not payload[name].strip():
            raise _bad(f"{name} is required")
    target = payload.get("target")
    seen = payload.get("seen")
    if target is None:
        if payload.get("value") is not None:
            raise _bad("value comes with a target")
        if not isinstance(seen, dict) or set(seen) != {"disk", "record"} or not all(
            value is None or isinstance(value, dict) for value in seen.values()
        ):
            raise _bad("seen is {disk, record}: what the page showed, each an object or null")
    else:
        if kind != records_file.ANSWER:
            raise _bad("only an answer carries a target")
        if payload.get("choice") is not None:
            raise _bad("a structured answer has no choice (its value says it)")
        problem = records_file.value_problem(target, payload.get("value"))
        if problem:
            raise _bad(problem)
        if not isinstance(seen, dict) or set(seen) != {"disk", "record", "slot"} or not all(
            seen[key] is None or isinstance(seen[key], dict) for key in ("disk", "record")
        ):
            raise _bad("seen is {disk, record, slot}: what the page showed of the question and "
                       "of the answered slot")
    request = {"table": payload["table"].strip(), "question": payload["question"].strip(),
               "asked": payload["asked"], "seen": seen, "kind": kind}
    if target is not None:
        request.update(target=target, value=payload["value"])
    try:
        # a structured answer's sentence is generated; a note after it is optional
        if target is None or (payload.get(text_key) is not None and str(payload[text_key]).strip()):
            request[text_key] = records_file.clean_text(payload.get(text_key), text_key,
                                                        records_file.MAX_TEXT)
        request["by"] = records_file.clean_text(payload.get("by"), "by", records_file.MAX_NAME)
        if kind == "redirect":
            request["to"] = records_file.clean_text(payload.get("to"), "to", records_file.MAX_NAME)
        elif payload.get("to") is not None:
            raise records_file.TextRefused("only a redirect names who to ask (to)")
    except records_file.TextRefused as error:
        raise _bad(str(error)) from None
    choice = payload.get("choice")
    if choice is not None:
        if kind not in records_file.CHOICE_KINDS or choice not in records_file.CHOICES:
            raise _bad(f"choice is yes or no, on {' or '.join(records_file.CHOICE_KINDS)} only")
        request["choice"] = choice
    return request


def _probe_paste(payload) -> dict:
    """``{probe, pasted}`` of a request: a probe id and the pasted result text, at most
    ``MAX_PASTE`` characters (``_bad`` otherwise)."""
    if not isinstance(payload, dict):
        raise _bad("probe_result is {probe, pasted}")
    probe, pasted = payload.get("probe"), payload.get("pasted")
    if not isinstance(probe, str) or not probe.strip():
        raise _bad("probe is required (a probe id)")
    if not isinstance(pasted, str) or not pasted.strip():
        raise _bad("pasted is required (the result as the query run handed it back)")
    if len(pasted) > MAX_PASTE:
        raise _bad(f"pasted is {len(pasted)} characters; at most {MAX_PASTE}")
    return {"probe": probe.strip(), "pasted": pasted}


def _reachable_from_elsewhere(host: str, allow_hosts) -> bool:
    """Whether machines other than this one may reach the server: a non-loopback address,
    or another name allowed (a proxy or a tunnel in front of a loopback address)."""
    if allow_hosts:
        return True
    if host == "localhost":
        return False
    try:
        return not ipaddress.ip_address(host).is_loopback
    except ValueError:
        return True


class CatalogHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, state: CatalogState, *, max_body: int, allowed_hosts, quiet,
                 ask=None, answers_remote_refused=False):
        self.state = state
        self.ask = ask
        self.answers_remote_refused = answers_remote_refused
        self.max_body = max_body
        self.allowed_hosts = frozenset(allowed_hosts)
        self.quiet = quiet
        super().__init__(address, CatalogHandler)


def make_server(
    state: CatalogState,
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    max_body: int = DEFAULT_MAX_BODY,
    allow_hosts=(),
    quiet: bool = False,
    ask=None,
    answers_allow_remote: bool = False,
) -> CatalogHTTPServer:
    """A server bound to ``host:port`` (port 0: any free port); call ``serve_forever``.
    ``ask`` is an ``ask.service.AskService``, or None for no ask endpoints.
    ``answers_allow_remote`` lets the answers endpoints write on a server other machines
    can reach (``_reachable_from_elsewhere``)."""
    allowed = set(LOOPBACK) | {_host_of(host)} | {_host_of(item) for item in allow_hosts}
    refused = _reachable_from_elsewhere(host, allow_hosts) and not answers_allow_remote
    return CatalogHTTPServer(
        (host, port), state, max_body=max_body, allowed_hosts=allowed, quiet=quiet, ask=ask,
        answers_remote_refused=refused,
    )
