# scope-lineage-service

Read-only servers for the `scope-lineage catalog` answer commands: an HTTP server (standard library
only) and an MCP server over stdio. They answer `search`, `context`, `query`, `check-sql` and
`pending list/add` from one built `ontology.json`, an optional directory of table-semantics documents
and an optional pending file -- the same answers, through the same functions
(`scope_lineage.cli_catalog_answers`), as the command line.

This directory is packaged on its own. The core `scope-lineage` package does not include it and gains no
dependency from it; this package depends on `scope-lineage` and on the official MCP Python SDK (`mcp`), and
its optional `[ask]` extra on the official Anthropic SDK (`anthropic`) for the opt-in ask panel, and its
optional `[ask-openai]` extra on the official OpenAI SDK (`openai`) for ask-panel models behind
OpenAI-compatible endpoints.

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
- The opt-in ask panel (`--ask`, below) keeps all of this: the model it calls gets only the catalog tools,
  never SQL execution or a file path.

## HTTP

```bash
scope-lineage-service http ONTOLOGY [--semantics DIR] [--pending FILE] \
  [--host 127.0.0.1] [--port 8765] [--max-body 1048576] [--allow-host NAME]... [--quiet] \
  [--ask [--ask-model M] [--ask-effort E] [--ask-models FILE] [--ask-max-...] | --ask-dev-fake-model]
```

`GET /api` lists the endpoints with their parameters (machine-readable); `GET /health` says whether
the files load now. It names the ontology file, the table-semantics directory and the pending file by
their last path component only (`ontology.path`, `semantics.path`, `pending.path`), never the
directories they live in, so a server bound off loopback does not reveal the operator's layout.
The same holds for error text: an input that breaks after start (removed, invalid, unreadable) is
reported in `/health`'s `problem` and in every error body with those paths cut to their names; the
command line keeps full paths.

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
origin without a preflight this server never grants. Every POST is also refused (403) when its `Origin`
header names another origin than this host and port exactly (another port on this machine included) or its
`Sec-Fetch-Site` header says anything but `same-origin`; clients that send neither, such as `curl`, are
unaffected. Unknown parameters and fields are refused (400), and
a connection that stops sending is dropped after 30 seconds.

## Browse page

Start the HTTP server and open `http://127.0.0.1:8765/` in a browser:

```bash
scope-lineage-service http out/ontology.json --semantics semantics/ --pending pending.jsonl
```

The page is for a person looking around a built catalog. Its labels are Chinese, in the words the command
line's text output uses; every view has its own address (`#/concept/<id>`, `#/table/<db.table>`, ...), so it
can be linked.

- **目录** -- the catalog's counts, then 「用之前先看」: the same two sentences and the same summary rows,
  with the same numbers, that `catalog render` puts first in `index.md` (computed by the same core function,
  `catalog_pages.use_first_rows`; the two rows counted from the table-semantics documents appear only when
  the server was started with `--semantics`, as they appear in `index.md` only with `--docs`); then its
  domains; a domain lists its concepts (kind, definition, how many tables, status), a page at a time. The
  search box uses `/api/search`.
- **概念** -- the concept's overview (`catalog query concept`), its tables a page at a time, its metrics,
  attributes and identifiers, and its **relations graph**: the concept, the concepts one relation or role away
  and every relation between them, drawn as SVG, with a table of each relation's join conditions -- the JOINs
  the corpus showed and the foreign-key columns the catalog binds. The relations between one pair of concepts
  share one line and one label (a line of text per relation). A relation is labelled with its name; a
  participation (derived from an event's `participants`, whose name is the participant's `role_name`, an
  identifier) is labelled 「参与者」, with how many roles when the event has several participants of the same
  concept, and each role name is in the line's tooltip and in the table below. Every neighbour is placed (the
  ring widens until no two boxes touch; a wide drawing scrolls). Labels are drawn while the graph has at most
  24 concepts, each placed outward from its line's middle until it meets no concept and no other label, with
  a dotted leader when it had to move away; a label line longer than 18 characters, or a label of more than
  4 relations, is shortened and its tooltip and the table carry it whole. With more than 24 concepts the
  lines carry no labels and the page says so.
- **指标** -- one metric as `catalog context --concept <metric>` gives it: definition, aggregation, filter,
  time window, measure columns, dimensions, constraints.
- **表** -- what the catalog says (`catalog query table` and `catalog context --table --brief`): concept,
  grain, time form and partition reading, bound columns (a column's full answer, `catalog context --column`,
  opens on request), joins, constraints, metrics; then the table-semantics document whole, its sections
  collapsible. A table of more than 12 columns gets a filter box (column name, the attribute or identifier it
  points to, code values, derivation, unit) and a choice of binding kind. Code values and derivation (口径) are
  shown on a line under the columns that have them, not in columns of mostly empty cells; a measure column's
  unit is shown under its target in the words the context pack prints, marked 「材料未给」 when the server was
  given table-semantics documents that do not give it (`/api/units`).
- **表（清单）** -- all tables, paged and filtered by name, concept or domain. With `--semantics`, each row also
  carries the columns of `index.md`'s 「按表看」 (key evidence and what the document says, with lineage
  evidence; measure columns; of which the unit has no support in the material; unmapped columns; watch items
  and how many contradict the material), with the same definitions and cells, `—` where the table has no
  document, and the coverage note when the documents do not cover every table. The list is in table-name order;
  the reader may sort it by the name backwards or by one of those numbers (either way), and the server sorts
  the whole filtered list before cutting the page, a table without a document last. There is no score, no
  combined ranking and no default order other than the name.
- **待确认问题** -- every open question registered: the table-semantics documents' questions and, with
  `--pending`, the pending file's items (grouped and checked as `catalog pending list` does), filterable by
  table, concept, status, source and text, each marked when the catalog does not carry it (a question on a
  table the catalog lacks; a pending item no catalog object is named by).

The browse endpoints (`/api/browse`, `/api/list`, `/api/neighbourhood`, `/api/semantics`, `/api/units`,
`/api/questions`) are thin: each calls a browse answer of `scope_lineage.cli_catalog_answers` (`browse_index`,
`browse_list`, `neighbourhood`, `table_semantics`, `table_units`, `questions`). These answers have no command
of their own -- the command line keeps `query`, `context` and `render` for the same facts -- and answer JSON
only (`format=text` is refused).

- `/api/browse` adds `use_first`: `{heading, notes, rows: [{name, value}]}`.
- `/api/list` takes `sort` (tables only): `table`, `measures`, `unit_unsupported`, `unmapped`, `watch` or
  `watch_conflicts`, with `-` before it for largest first; every value but `table`/`-table` needs
  `--semantics`; anything else is 400 like an unknown parameter. Its `query` adds `sort`; with `--semantics`
  a table answer adds `by_table` (`columns: [{key, label}]`, `covered`, `tables`, `note`) and each table row
  `by_table` (the numbers -- `null` where the table has no document -- `covered`, and `cells`, the texts
  `index.md` prints).
- `/api/units?table=` (new): `{table, in_catalog, checked, columns: [{column, ref, unit?, material_unit?,
  text}]}` for the table's measure columns and columns bound to an attribute with a unit; `text` is what the
  context pack's `单位：` line says. 404 when the catalog has no such table.

The whole-catalog counts behind these (the catalog view, the summary rows, the by-table rows) are computed
once for the loaded documents and kept until the files change, so a page of a large catalog is answered
without recounting it. A list is one page (`limit` 1 to 200, default 50, with `offset` and the `total`); the graph is one
concept's neighbourhood (at most 40 neighbours by default, at most 10 join columns an edge); no endpoint
sends the whole catalog. An empty page or board is 200; a concept with no match, or a table with no
semantics document, is 404 with the answer as body.

Read-only: the browse views only send GET requests and write nothing; no SQL is run. (The ask panel,
below, posts questions and, when the reader submits one, a 待确认 definition to the pending file.) Its files
(`index.html`, `app.css`, `app.js`, `dom.js`, `views.js`, `graph.js`, and the ask panel's `ask.js` and
`askview.js`) are packaged with this module and served from a fixed
table of paths -- no request path is joined to a directory, anything else is 404, and they take no
parameters. They are plain HTML, CSS and JavaScript: no build step, no third-party code, nothing loaded from
the network, so the page works offline against the local server. Catalog text is placed in the page as text
(DOM nodes, never parsed as markup), and every response carries a `Content-Security-Policy` that allows only
this server's own scripts, styles and requests (`default-src 'self'`, no inline script, no framing), with
`X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`. The Host and Origin checks apply to the
page as to every endpoint.

## Ask panel (opt-in)

The page's **问数** view takes a data question and has a model answer it -- on the server, never in the
browser -- by the skill's own walk (`skills/scope-lineage/workflows/catalog-answers.md`): search the catalog,
take one context pack, write the SQL, check it, record what the catalog lacks. The page shows each step as it
happens: the candidates the search found, the tables and columns taken into the pack, every `check-sql` round
with its findings, the final SQL, the basis given for each condition, and each `/* 待确认：… */` placeholder
with what is missing. Beside a placeholder the reader can type the definition; submitting it appends one line
to the pending file through `POST /api/pending` (only with `--pending`). **It never runs SQL** and never
changes the catalog.

**It costs money and sends catalog text to the model provider.** Every question calls the model through the
Anthropic API (or, with `--ask-models`, the endpoint of the model the asker picked); the question, the catalog text the tools return (search hits, context packs, check findings)
and the SQL the model drafts are sent with it. So it is off unless the server is started with `--ask`;
without it the ask endpoints answer `404 not_configured` and the page says how to enable it.

```bash
pip install -e . -e "service[ask]"          # the anthropic SDK is an optional extra of this package only
export ANTHROPIC_API_KEY=...                 # or ANTHROPIC_AUTH_TOKEN, or `ant auth login`
scope-lineage-service http out/ontology.json --semantics semantics/ --pending pending.jsonl --ask
# then open http://127.0.0.1:8765/#/ask
```

If a question ends at once with `TypeError: process() takes no keyword arguments`, the environment has an
old `brotli` package that the SDK's HTTP library cannot use to read a compressed reply (seen with
`brotli` 1.0.9 from a system-wide Python distribution): `pip install "brotli>=1.1"` in the same
environment and restart the server.

Credentials are resolved by the SDK from the server's environment: there is no key option, no key is logged,
and nothing about it reaches the browser. If the SDK is missing or too old, or no credential is found, the
start message and the panel say why asking is unavailable; the rest of the page keeps working. `--ask` is
refused on an address other than loopback (it spends money and the server has no authentication).

| Option | Default | Meaning |
| --- | --- | --- |
| `--ask` | off | enable the panel and its endpoints |
| `--ask-model` | `claude-opus-5-5` | the model |
| `--ask-effort` | `high` | `output_config.effort` (`low` ... `max`); the walk is a long multi-step tool task, and this model's own default is `medium` |
| `--ask-no-fallback` | fallback on | without it, a request the model's safety classifiers decline is retried server-side on the API's recommended fallback model (`fallbacks: "default"`) |
| `--ask-models FILE` | none | several models the asker picks from per question, see below; replaces the three options above |
| `--ask-max-turns` | 30 | model requests per question |
| `--ask-max-tool-calls` | 40 | tool calls per question (calls past it are refused as tool errors and the model is told to answer; a second refused turn stops) |
| `--ask-max-output-tokens` | 128000 | output tokens per question (each request asks for at most 64000 and never more than is left) |
| `--ask-max-seconds` | 900 | wall time per question |
| `--ask-max-conversations` | 20 | conversations kept in memory (the least recently used idle one goes first) |
| `--ask-idle-minutes` | 60 | an idle conversation is dropped after this |
| `--ask-dev-fake-model` | off | **development aid**, see below |

How it runs:

- **The instructions are the walk.** The system prompt is a short preamble -- which tool stands for which
  command, and this service's limits (no SQL is run, no file can be read, answer in the asker's language,
  end with the walk's brief) -- followed by `catalog-answers.md` and the reference it cites, word for word.
  The package carries exact copies of the two skill files (`scope_lineage_service/ask/*.md`);
  `tests/test_ask_walk.py` fails when a copy differs from the skill, so the skill stays the one source.
- **The tools are the catalog answers.** `search_catalog`, `catalog_context`, `query_catalog`, `check_sql`, and
  `add_pending` when the server has a pending file: the same functions, parameters and descriptions as the MCP
  tools. A result is the command's text form (what it prints without `--json`), two to four times shorter than
  the JSON; the page gets a small structured summary of the same answer. Every input is checked against its
  tool's schema first, and a refused input comes back as a tool error with the command's sentence. Model
  output never becomes a path or a command.
- **The loop.** The service hosts a manual Messages API loop (official `anthropic` SDK, streamed requests,
  adaptive thinking, `tool_choice` auto): parallel tool calls run in order and their results go back in one
  message; `refusal` and `max_tokens` stop the question without running that turn's calls; `pause_turn` is
  continued. The tools and system prompt are one stable, cached prefix; the page shows the token usage of
  each question (input, cache reads and writes, output).
- **Follow-ups** carry the previous question's brief, not the transcript, as the walk's multi-turn section
  says. Conversations live in server memory only, under an unguessable id: a restart loses them, and the page
  says so. One question runs at a time per conversation; **停止** cancels it (at the next model event or tool
  call).
- **Safety.** Every POST must be JSON from this page's own origin (`Origin` exactly this host and port,
  `Sec-Fetch-Site: same-origin`, on top of the Host check), so no other site open in the browser can spend
  money or write the pending file; the page polls `GET /api/ask/events` (long polling, plain JSON responses
  under the same `Content-Security-Policy`). Model and catalog text are placed in the page as text only. No
  telemetry, no network call other than the model request.

| Method | Path | Parameters |
| --- | --- | --- |
| GET | `/api/ask/status` | none: whether asking works now (or why not), the default model, caps, and `models`: each model's `id`, `label`, `provider`, `available`, `reason`, `default` (never a URL, a variable name or a key) |
| POST | `/api/ask` | `application/json`: `question`, `conversation` for a follow-up, `model` (an id from the status; default the server's default; a follow-up may name another); 202 with the conversation and run ids and the model, 400 for an unknown model, 409 for one that cannot answer now or while that conversation is still answering |
| GET | `/api/ask/events` | `conversation`, `run`, `after` (last event number seen), `wait` (0-25 s, default 20) |
| POST | `/api/ask/cancel` | `application/json`: `conversation` |
| GET | `/api/ask/conversation` | `conversation`: its questions and the brief the next one carries |

### Several models (`--ask-models`)

One model is often not enough: a team may want the official API beside a privately hosted model, or a
cheaper model for easy questions. `--ask-models FILE` lists them; the panel then shows a picker, the asker
chooses the model for each question (a follow-up may switch), the browser remembers the last choice, and
each answer is labelled with the model that gave it.

```json
{
  "models": [
    {"id": "opus", "label": "Claude Opus 5.5", "provider": "anthropic",
     "model": "claude-opus-5-5", "effort": "high", "default": true},
    {"id": "gateway", "label": "Claude via the internal gateway", "provider": "anthropic",
     "model": "claude-opus-5-5", "base_url": "https://gateway.example.internal",
     "api_key_env": "GATEWAY_KEY", "fallback": false},
    {"id": "private", "label": "Private model", "provider": "openai-compatible",
     "model": "example-model", "base_url": "https://models.example.internal/v1",
     "api_key_env": "PRIVATE_MODELS_KEY", "max_tokens": 8192}
  ]
}
```

```bash
pip install -e . -e "service[ask,ask-openai]"
export PRIVATE_MODELS_KEY=...     # the file names the variable; the value never goes in the file
scope-lineage-service http out/ontology.json --semantics semantics/ --ask --ask-models models.json
```

| Field | For | Meaning |
| --- | --- | --- |
| `id` | all | required; 1-40 lower-case letters, digits, `.`, `_`, `-`; what the page sends and remembers |
| `label` | all | what the page shows (default: the id) |
| `provider` | all | `anthropic` or `openai-compatible` |
| `model` | all | the provider's model id |
| `base_url` | all | required for `openai-compatible` (the URL before `/chat/completions`); for `anthropic`, a gateway that speaks the Messages API (default: the official endpoint) |
| `api_key_env` | all | the NAME of the environment variable holding the key. `anthropic` without it: the SDK's own credential (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, a login profile) for the official endpoint, but with a `base_url` a placeholder key and never the ambient credential, so a forgotten `api_key_env` cannot send the official key to a private host. `openai-compatible` without it: no key (a placeholder; `OPENAI_API_KEY` is never picked up) |
| `effort` | all | `anthropic`: `output_config.effort`, default `high`, `null` sends none. `openai-compatible`: sent as `reasoning_effort` when set |
| `max_tokens` | all | the model's output limit per request: no request asks for more (`openai-compatible` default 8192, since private models often allow little) |
| `default` | all | at most one; without it the first model. An unavailable default gives way to the first available model |
| `allow_insecure_http` | all | allow plain `http://` to a host other than this machine (see below) |
| `fallback`, `prompt_cache`, `eager_input_streaming`, `adaptive_thinking` | `anthropic` | each `true` by default (today's request); set `false` for a gateway that rejects the refusal-fallback beta, the cache marks (top-level and on the system prompt), streamed tool input or adaptive thinking |
| `stream_usage` | `openai-compatible` | send `stream_options.include_usage` (default `true`; an endpoint that rejects it is asked again without it, once, automatically) |
| `max_tokens_field` | `openai-compatible` | `max_tokens` (default) or `max_completion_tokens` |

**Checked at start.** An unknown field, a bad value, two defaults, a duplicate id, or anything that looks
like a secret (a field named like a key or token, a value shaped like a key, credentials or a key in the
`base_url`) stops the server with a sentence naming the problem. A `base_url` must be `http(s)://` with a
host; **plain `http://` to a host other than this machine is refused** unless that model sets
`allow_insecure_http: true` -- the question and catalog text cross that link. `--ask` itself still binds
loopback only. A model whose SDK or key is missing is listed as unavailable with the reason (the page shows
it disabled) and the server starts as long as one model can answer; with none, the panel is unavailable as
before. The start message lists each model with its endpoint and the variable its key comes from; the page
and the status endpoint get only id, label, provider kind, availability and the reason.

**What is sent where.** A question and everything that follows it (the walk as system prompt, the tool
definitions, the catalog text the tools return, the SQL drafted) go to the endpoint of the model that
answers it, and nowhere else. The caps (turns, tool calls, output tokens, seconds) apply to every model.
The `openai` SDK also sends `OPENAI_ORG_ID` and `OPENAI_PROJECT_ID` as request headers when they are set in
the server's environment, whichever endpoint the model names: unset them if that endpoint should not see them.

**What differs per provider.** `anthropic` models get the full request described above. On the
`openai-compatible` path the service translates at the model seam (system prompt, messages, tools and tool
results into Chat Completions form; text, tool calls, finish reason and usage back): there is **no prompt
caching, no refusal fallback and no adaptive thinking**; `length` reads as a cut-off answer and
`content_filter` as a refusal; tool arguments that are not a JSON object are asked for again, as on the
Anthropic path; an endpoint that reports no usage gets counts estimated from text lengths, marked as
estimates on the page, so the output cap still holds. **How well a weaker model follows the walk is not
verified**: the walk was written for and tried with Claude, and a model that skips steps or ignores the
brief format gives worse answers -- compare on your own questions before relying on one.

### Reviewing the page without a key

`--ask-dev-fake-model` is a development aid, off by default: no model is called and nothing leaves the
machine. It answers through the same loop and endpoints with a fixed sequence of real tool calls against the
loaded catalog (a search, then the best table's column list beside a metric search, a context pack, a check of
an assembled SQL with placeholders) and an answer in the walk's format. It never calls `add_pending`; the
page's fill-in still writes when the reader submits a definition. The page shows a banner and a 假模型 badge on
every answer, and every answer starts by saying it is not one.

```bash
scope-lineage-service http out/ontology.json --semantics semantics/ --pending pending.jsonl --ask-dev-fake-model
```

With `--ask-models FILE` as well, every model in the file is played by the fake (each named after its id,
none called), so the picker can be reviewed with the real file and no key.

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
`stat` (size, modification time, inode; the directory is walked with `os.scandir`, a few milliseconds for
thousands of documents) and read again only when something differs, so a new
`catalog build` or a new semantics document is answered from on the next request without a restart. The
pending file is read on every list. The servers never answer from a copy they know to be stale.

## Tests

The tests use the repository's demo ontology and table-semantics document, need no network, and start the
HTTP server on an ephemeral port of `127.0.0.1` and the MCP server in memory and as a stdio subprocess:

The browse page's pure JavaScript functions (the graph layout and its labels, the column filter, the table
sorts offered, the document title, and the ask panel's placeholder reading, brief parsing and event view
model) are checked by running the page's own modules with `node` when it is on `PATH`
(`test_service_page_js.py`, `test_ask_page_js.py`, skipped otherwise; no
JavaScript package is installed).

The ask panel's tests never call a model or need the SDK: the loop runs against a scripted model behind
its one seam (`test_ask_loop.py`), the endpoints against the development fake (`test_ask_http.py`), and the
SDK calls against a stand-in module of the documented shape (`test_ask_model.py`) -- which checks the
request the service builds, not the real API. The models file has its own tests (`test_ask_models.py`). When
the SDKs are installed, two more run them for real against stand-in servers on `127.0.0.1` (standard library
only): `test_ask_openai_model.py` (a streamed chat-completions server: split and interleaved tool-call
deltas, invalid arguments, missing usage, refused `stream_options`, HTTP 401/403/404/429/400/500, a refused
connection, cancel mid-stream, and a whole question through the loop) and `test_ask_anthropic_gateway.py` (a
Messages API gateway receiving the default request and the one with every feature switched off). None of
them reaches a real endpoint.

```bash
pip install -e ".[dev]" -e service
python -m pytest -q service/tests
python -m ruff check service
```
