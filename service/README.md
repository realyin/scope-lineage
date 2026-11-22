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

```bash
pip install -e ".[dev]" -e service
python -m pytest -q service/tests
python -m ruff check service
```
