# scope-lineage-service

Read-only servers for the `scope-lineage catalog` answer commands: an HTTP server (standard library
only) and an MCP server over stdio. They answer `search`, `context`, `query`, `check-sql` and
`pending list/add` from one built `ontology.json`, an optional directory of table-semantics documents
and an optional pending file -- the same answers, through the same functions
(`scope_lineage.cli_catalog_answers`), as the command line.

This directory is packaged on its own. The core `scope-lineage` package does not include it and gains no
dependency from it; this package depends on `scope-lineage` and on the official MCP Python SDK (`mcp`).

## Install

From a checkout of this repository (the core function module first ships in the release after 0.15.0,
so install the core from the same checkout):

```bash
pip install -e . -e service
```

## Read-only guarantee

- No endpoint or tool runs SQL. `check-sql` parses the SQL and compares it with the catalog; nothing
  connects to a database.
- The servers read only the files named when they start; no request names a path.
- The one file written is the pending file given with `--pending`, appended to the way
  `catalog pending add` appends (existing lines are never rewritten). Without `--pending` the pending
  endpoints and tools are not offered.

## HTTP

```bash
scope-lineage-service http ONTOLOGY [--semantics DIR] [--pending FILE] \
  [--host 127.0.0.1] [--port 8765] [--max-body 1048576] [--allow-host NAME]... [--quiet]
```

`GET /api` lists the endpoints with their parameters (machine-readable); `GET /health` says whether
the files load now.

| Method | Path | Parameters | Same as |
| --- | --- | --- | --- |
| GET | `/health` | none | none |
| GET | `/api` | none | none |
| GET | `/api/search` | `text` (required), `kind` (repeatable), `limit` | `catalog search --json` |
| GET | `/api/context` | `table`, `column`, `columns`, `concept` (each repeatable), `brief`, `focus` | `catalog context --json` |
| GET | `/api/query` | `kind`, `term` (both required) | `catalog query --json` |
| POST | `/api/check-sql` | body: the SQL as `text/plain`, or `application/json` `{"sql": "..."}` | `catalog check-sql --json` |
| GET | `/api/pending` | none | `catalog pending list --ontology --semantics --json` |
| POST | `/api/pending` | body (`application/json`): `question`, and `missing` or `sql`; `term`, `tables`, `columns`, `proposed`, `sql_name`, `date` | `catalog pending add` |
| GET | `/` | none | the browse page (see below) |
| GET | `/api/browse` | none | none |
| GET | `/api/list` | `kind` (required: `concepts`, `tables`, `metrics`), `domain`, `concept`, `text`, `offset`, `limit` | none |
| GET | `/api/neighbourhood` | `concept` (required), `limit` | none |
| GET | `/api/semantics` | `table` (required) | none |
| GET | `/api/questions` | `table`, `concept`, `status` (`open`, `answered`, `all`), `source` (`semantics`, `pending`), `text`, `offset`, `limit` | none |

Every answer endpoint takes `format=text` for what the command prints without `--json`. The JSON body is
byte for byte what the command prints with `--json`. The command's exit code is in the
`X-Scope-Lineage-Exit-Code` header and shapes the status:

| Exit code | Meaning | Status |
| --- | --- | --- |
| 0 | found | 200 (201 for a pending add) |
| 1 | nothing found (search, context, query) | 404, with the answer as body |
| 1 | an error or a warning (check-sql), a line that is not an entry (pending list) | 200 |
| 1 | the SQL holds no placeholder (pending add; nothing written) | 422 |
| 2 | an input the command refuses | 400 |

Errors are JSON: `{"error": {"kind": ..., "exit_code": ..., "message": ...}}`, the message being the
sentence the command prints on stderr. A started-with file that cannot be read now (a build half way
through writing it) is `503 input_unavailable`; the next request tries again.

```bash
curl -s 'http://127.0.0.1:8765/api/search?text=customer&limit=3'
curl -s 'http://127.0.0.1:8765/api/context?table=demo_dwd.dwd_party_customer_info_df&brief=true'
curl -s -X POST --data-binary @query.sql -H 'Content-Type: text/plain' http://127.0.0.1:8765/api/check-sql
```

Safety: binds `127.0.0.1` unless `--host` says otherwise (a warning is printed for any other address:
there is no authentication). A request whose `Host` or `Origin` is not this machine, the bound address or an
`--allow-host` name is refused (403), which keeps a web page elsewhere from reaching the server through DNS
rebinding. POST bodies must declare `Content-Length` and are capped by `--max-body` (413 above it, the body
is not read). `POST /api/pending` takes only `application/json`, which a browser will not send to another
origin without a preflight this server never grants. Unknown parameters and fields are refused (400), and
a connection that stops sending is dropped after 30 seconds.

## Browse page

Start the HTTP server and open `http://127.0.0.1:8765/` in a browser:

```bash
scope-lineage-service http out/ontology.json --semantics semantics/ --pending pending.jsonl
```

The page is for a person looking around a built catalog. Its labels are Chinese, in the words the command
line's text output uses; every view has its own address (`#/concept/<id>`, `#/table/<db.table>`, ...), so it
can be linked.

- **目录** -- the catalog's counts and its domains; a domain lists its concepts (kind, definition, how many
  tables, status), a page at a time. The search box uses `/api/search`.
- **概念** -- the concept's overview (`catalog query concept`), its tables a page at a time, its metrics,
  attributes and identifiers, and its **relations graph**: the concept, the concepts one relation or role away
  and every relation between them, drawn as SVG, with a table of each relation's join conditions -- the JOINs
  the corpus showed and the foreign-key columns the catalog binds.
- **指标** -- one metric as `catalog context --concept <metric>` gives it: definition, aggregation, filter,
  time window, measure columns, dimensions, constraints.
- **表** -- what the catalog says (`catalog query table` and `catalog context --table --brief`): concept,
  grain, time form and partition reading, bound columns with their code values (a column's full answer,
  `catalog context --column`, opens on request), joins, constraints, metrics; then the table-semantics document
  whole, its sections collapsible. A list of all tables is paged and filtered by name, concept or domain.
- **待确认问题** -- every open question registered: the table-semantics documents' questions and, with
  `--pending`, the pending file's items (grouped and checked as `catalog pending list` does), filterable by
  table, concept, status, source and text, each marked when the catalog does not carry it (a question on a
  table the catalog lacks; a pending item no catalog object is named by).

The browse endpoints (`/api/browse`, `/api/list`, `/api/neighbourhood`, `/api/semantics`, `/api/questions`)
are thin: each calls a browse answer of `scope_lineage.cli_catalog_answers` (`browse_index`, `browse_list`,
`neighbourhood`, `table_semantics`, `questions`). These answers have no command of their own -- the command
line keeps `query`, `context` and `render` for the same facts -- and answer JSON only (`format=text` is
refused). A list is one page (`limit` 1 to 200, default 50, with `offset` and the `total`); the graph is one
concept's neighbourhood (at most 40 neighbours by default, at most 10 join columns an edge); no endpoint
sends the whole catalog. An empty page or board is 200; a concept with no match, or a table with no
semantics document, is 404 with the answer as body.

Read-only: the page only sends GET requests and writes nothing; no SQL is run. Its files (`index.html`,
`app.css`, `app.js`, `dom.js`, `views.js`, `graph.js`) are packaged with this module and served from a fixed
table of paths -- no request path is joined to a directory, anything else is 404, and they take no
parameters. They are plain HTML, CSS and JavaScript: no build step, no third-party code, nothing loaded from
the network, so the page works offline against the local server. Catalog text is placed in the page as text
(DOM nodes, never parsed as markup), and every response carries a `Content-Security-Policy` that allows only
this server's own scripts, styles and requests (`default-src 'self'`, no inline script, no framing), with
`X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`. The Host and Origin checks apply to the
page as to every endpoint.

## MCP

```bash
scope-lineage-service mcp ONTOLOGY [--semantics DIR] [--pending FILE]
```

| Tool | Arguments | Same as |
| --- | --- | --- |
| `search_catalog` | `text`, `kinds`, `limit`, `format` | `catalog search` |
| `catalog_context` | `tables`, `columns`, `columns_of_table`, `concepts`, `brief`, `focus`, `format` | `catalog context` |
| `query_catalog` | `kind`, `term`, `format` | `catalog query` |
| `check_sql` | `sql`, `format` | `catalog check-sql` |
| `list_pending` | `format` | `catalog pending list` (with `--pending`) |
| `add_pending` | `question`, `missing` or `sql`, `sql_name`, `term`, `tables`, `columns`, `proposed`, `date`, `format` | `catalog pending add` (with `--pending`) |

Each tool returns one text item: the readable answer by default, or with `"format": "json"` exactly what
the command prints with `--json`. A nothing-found answer is an ordinary result that says so; an input the
command refuses is a tool error carrying the command's sentence. The server carries instructions that
describe the usual walk (search, context, write the SQL, check it).

An MCP client configuration (for example a `.mcp.json`):

```json
{
  "mcpServers": {
    "scope-lineage-catalog": {
      "command": "scope-lineage-service",
      "args": ["mcp", "out/ontology.json", "--semantics", "semantics/", "--pending", "pending.jsonl"]
    }
  }
}
```

## Files that change

Before each answer the ontology file and every `*.json` under the semantics directory are checked with
`stat` (size, modification time, inode) and read again only when something differs, so a new
`catalog build` or a new semantics document is answered from on the next request without a restart. The
pending file is read on every list. The servers never answer from a copy they know to be stale.

## Tests

The tests use the repository's demo ontology and table-semantics document, need no network, and start the
HTTP server on an ephemeral port of `127.0.0.1` and the MCP server in memory and as a stdio subprocess:

The browse page's pure JavaScript functions (the graph layout, the document title) are checked by running
the page's own modules with `node` when it is on `PATH` (`test_service_page_js.py`, skipped otherwise; no
JavaScript package is installed).

```bash
pip install -e ".[dev]" -e service
python -m pytest -q service/tests
python -m ruff check service
```
