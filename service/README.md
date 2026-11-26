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

From a checkout of this repository (the page's answers need the core's additions first shipped in 0.17.0 -- answers
overlaid on the documents and marked in the context pack and the board, and the structured answers' overlay
and slot marks; pasted platform results need `semantics.probe_results`, first shipped in 0.18.0; installing the core from the same
checkout keeps the two in step):

```bash
pip install -e . -e service
```

## Read-only guarantee

- No endpoint or tool runs SQL. `check-sql` parses the SQL and compares it with the catalog; nothing
  connects to a database.
- The servers read only the files named when they start; no request names a path.
- The files written are the pending file given with `--pending`, appended to the way
  `catalog pending add` appends (existing lines are never rewritten), and, with `http --answers FILE`, the
  answers file the browse page keeps its answers in (below), and, with `http --ask-trace DIR`, the ask
  panel's run records under DIR (below). Without `--pending` the pending endpoints and
  tools are not offered; without `--answers` the answer endpoints are not. The table-semantics directory is
  never written.
- The opt-in ask panel (`--ask`, below) keeps all of this: the model it calls gets only the catalog tools,
  never SQL execution or a file path.

## HTTP

```bash
scope-lineage-service http ONTOLOGY [--semantics DIR] [--pending FILE] [--answers FILE [--answers-allow-remote]] [--probes FILE] \
  [--host 127.0.0.1] [--port 8765] [--max-body 1048576] [--allow-host NAME]... [--quiet] \
  [--ask [--ask-model M] [--ask-effort E] [--ask-models FILE] [--ask-max-...] | --ask-dev-fake-model]
```

`GET /api` lists the endpoints with their parameters (machine-readable); `GET /health` says whether
the files load now and lists the files the server writes (`writes`: the pending file's name, and the
answers file's when this server writes one; it replaced `read_only: true`). It names the ontology file,
the table-semantics directory, the pending file and the answers file by their last path component only
(`ontology.path`, `semantics.path`, `pending.path`, `answers.path`), never the directories they live in,
so a server bound off loopback does not reveal the operator's layout.
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
| POST | `/api/pending` | body (`application/json`): `question`, and `missing` or `sql`; `term`, `tables`, `columns`, `proposed`, `sql_name`, `date`; `unless_recorded` (true/false, default false: see below) | `catalog pending add` |
| GET | `/` | none | the browse page (see below) |
| GET | `/api/browse` | none | none |
| GET | `/api/list` | `kind` (required: `concepts`, `tables`, `metrics`), `domain`, `concept`, `text`, `offset`, `limit` | none |
| GET | `/api/neighbourhood` | `concept` (required), `limit` | none |
| GET | `/api/semantics` | `table` (required) | none |
| GET | `/api/questions` | `table`, `concept`, `status` (`open`, `answered`, `all`; with `--answers` also `set_aside`), `source` (`semantics`, `pending`), `text`, `offset`, `limit` | none |
| POST | `/api/answers` | body (`application/json`): `table`, `question`, `kind`, `answer` or `reason`, `choice`, `to`, `by`, `asked`, `seen`, and for a structured answer `target`, `value` (with `--answers`; see below) | none |
| POST | `/api/answers/withdraw` | body (`application/json`): `table`, `question`, `seen` (with `--answers`) | none |
| GET | `/api/answers/export` | none (with `--answers`) | `scope-lineage-service answers export` |
| GET | `/api/probes` | `table` (required), `question` (with `--probes`; see below) | none |
| POST | `/api/probe-results/draft` | body (`application/json`): `probe`, `pasted` (with `--probes`) | none |
| POST | `/api/observations` | body (`application/json`): `probe`, `pasted`, `by`, `seen` (with `--probes` and `--answers`) | none |
| POST | `/api/observations/withdraw` | body (`application/json`): `seen` (with `--probes` and `--answers`) | none |

Every answer endpoint takes `format=text` for what the command prints without `--json`. The JSON body is
byte for byte what the command prints with `--json`. The command's exit code is in the
`X-Scope-Lineage-Exit-Code` header and shapes the status:

| Exit code | Meaning | Status |
| --- | --- | --- |
| 0 | found | 200 (201 for a pending add; 200 with `appended: 0` when `unless_recorded` found the item already there) |
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

  With `--answers` the table-semantics cards take answers and notes (next section).

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
below, posts questions and, when the reader clicks 「记入待确认」 beside a placeholder, that gap to the pending file; with
`--answers`, the questions board posts answers to the answers file.) Its files
(`index.html`, `app.css`, `app.js`, `dom.js`, `views.js`, `graph.js`, and the ask panel's `ask.js` and
`askview.js`) are packaged with this module and served from a fixed
table of paths -- no request path is joined to a directory, anything else is 404, and they take no
parameters. They are plain HTML, CSS and JavaScript: no build step, no third-party code, nothing loaded from
the network, so the page works offline against the local server. Catalog text is placed in the page as text
(DOM nodes, never parsed as markup), and every response carries a `Content-Security-Policy` that allows only
this server's own scripts, styles and requests (`default-src 'self'`, no inline script, no framing), with
`X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`. The Host and Origin checks apply to the
page as to every endpoint.

## Answering questions on the page (`--answers`)

```bash
scope-lineage-service http out/ontology.json --semantics "$RUN/docs" --answers "$RUN/question-answers.json"
```

With `--answers FILE` a person answers the table-semantics questions on the board (待确认问题) instead of
writing a confirmations file by hand. The answers go to `FILE`, never into the semantics directory; keep
`FILE` outside it (beside `$RUN/confirmations/`, say). The file is created on the first answer.

**What a person can leave on a question** -- one record per question; a new one replaces the old:

| `kind` | Page label | The question afterwards | Overlaid | Exported |
| --- | --- | --- | --- | --- |
| `answer` | 回答 (optionally 是 / 否) | answered, marked 「未写回」 | yes | yes |
| `partial` | 部分回答 (optionally 是 / 否) | open, with the part answered | no | no |
| `deferred` | 暂时确认不了 | open, with the note | no | no |
| `redirect` | 该问某某 (a name) | open, with the note | no | no |
| `invalid` | 问题有误 | set aside (已搁置) | no | no |
| `not_applicable` | 不适用 | set aside (已搁置) | no | no |

A note cannot be left on a question its document already answers (400): change the answer instead. Notes
live in the answers file only: the document format has no place for them, so they do not travel with the run
directory. The page asks for a name (回答人, kept in the browser) before sending; the date is the server's
today.

**The record file** (`question-answers/1`):

```json
{"doc_format": "question-answers/1", "answers": [
  {"table": "demo_dwd.dwd_party_customer_info_df", "question": "q1",
   "asked": "性别码值除了 F、M、U 以外，还会不会出现其他值？", "base": null,
   "kind": "answer", "answer": "不会。注册系统只允许三个值。", "choice": "no",
   "source": {"kind": "person"}, "by": "demo-reviewer", "date": "2026-11-23"}
]}
```

`asked` is the question as the person saw it; `base` what the document on disk held for it then (`null`
when open, else `{answer, answered_by, answered_on}`: the answer being changed). A note has `reason`
instead of `answer`; a `redirect` has `to`. The file is checked whenever it is read: one that cannot be read
or breaks a rule is ignored as a whole -- every answer comes from the documents alone -- and `/health`, `GET
/api` (`answers.status`, `unreadable` with the reason) and the board say so; nothing is written to it until
it is repaired or removed.

**Which records count** -- each record is held against the document on disk whenever either changes, and
the first of these that holds decides:

1. the table or the question is gone: **not matched**;
2. the question's text is not what was asked (compared after NFKC and folding whitespace, nothing fuzzier):
   **not matched**, the question was rewritten;
3. the document now holds this very answer (the same text, the same person, the same date): **written back**
   -- the record is deleted. A note on a question the document now answers is deleted the same way;
4. the document still holds `base` (an answer), or the question is open (a note): **in effect**;
5. anything else: **not matched**, the document changed under it (someone else answered, even in the same
   words; the answer went back to open; a third answer).

Only answers in effect are overlaid: the context pack, the board, `/api/semantics`, the ask panel's tools
and MCP read the question as answered, marked as not written back (`written: false`; text
`回答（页面填写，尚未写回）：…`); notes are marked `page`, and the two that set a question aside give it the
status `set_aside`. `/api/semantics` adds, beside the document, `unwritten` (the ids of the questions
answered on the page) and `page` (`{question id: note}`); the document gains no key it would not have after
`semantic confirm`. Records not matched are neither overlaid nor exported: the board lists them at the
bottom (「没对上的回答」) with the reason and what the document holds now, to delete or to answer again.

**Writing back** -- `GET /api/answers/export` (the board's 「导出确认文件」 button) or

```bash
scope-lineage-service answers export "$RUN/question-answers.json" --semantics "$RUN/docs" --out answers-confirmations.json
```

writes the answers in effect as a `semantic-confirmations/1` file (a 是 / 否 becomes `是：…` / `否：…` in the
sentence; notes and records not matched are left out). Each entry carries `asked`, the question as the
page showed it, and `replace: true` when it changes an answer the document already held, so `semantic
confirm` itself refuses a question rewritten after the export and leaves an answer the person did not
change alone (see `semantic confirm` in the table-semantics docs). The command prints each record not matched with its
reason, and each table's `document_digest`, on stderr, and exits 1 when a record did not match (the others
are still written); the board shows the same digests beside the button. Neither writes the answers file.
Then write it back as the runbook's step S12 does:

```bash
scope-lineage semantic confirm "$RUN/docs" --confirmations answers-confirmations.json --reviews "$RUN/reviews"
```

The next time the server reads the documents those answers are written back (rule 3) and their records are
deleted. Between the export and `confirm` the file is an ordinary confirmations file: check the digests if the
documents may have been rewritten meanwhile. A question rewritten in between comes back `unmatched`
(`question was rewritten`), and running the same file again reports its answers as `skipped`.

**Structured answers** -- beside 一句话, a card's answer form offers 行粒度, 列含义 and 码值: the person gives
the value itself, and the server writes the question's sentence from it. The record gains `target`, `value`
and `slot_base` (`answer` becomes an optional note after the sentence; no `choice`):

| 页签 | `target` | `value` | Sentence |
| --- | --- | --- | --- |
| 行粒度 | `summary.row` | `{"unique": "yes" \| "no", "grain_columns": ["a", "b"]}` | `是：按 (a, b) 每行唯一` / `否：按 (a, b) 不唯一` |
| 列含义 | `column:<c>.meaning` | `"<text>"` | `列 c 的含义：…` |
| 码值 | `column:<c>.code_values` | `[{"value", "meaning"}, ...]` (1--50) | `列 c 的码值：1=…；2=…` |

The column menu lists the question's own columns (`about`), or every column of the table when it names none.
The guards: grain columns are 1--8 distinct columns of the table; a code value is 1--64 characters, not
blank, given once, never on an identifier column; texts on one line as above; a row answer is refused (400)
when the document's grain is `proven` -- the lineage proved it, so say the disagreement in a sentence. Only
the table's own columns can be answered. `slot_base` is the slot on disk when the answer was given (the row's
`{unique, grain_columns, grain_source}`, the column's meaning, or `{value: meaning or null}` of the code
values given), and the judgement holds the slot too: **written back** needs the sentence on disk *and* the
slot to hold the value (the same `unique` and set of grain columns; the same meaning; each code value with
the meaning and not `unconfirmed`); **in effect** needs the question at `base` *and* the slot at `slot_base`;
a column gone is **not matched** (missing). The page sends `seen.slot`, the slot as it showed it (the
overlaid document); a different slot now is 409. Two questions may not answer one slot (the row, or the same
code value of a column): the second is refused (400) naming the first, and in a file that holds both anyway
only the first is overlaid -- the second is listed as not overlaid.

A structured answer overlays its slot and its question together: when either entry is refused, the record is
taken out whole (「叠加不上」) and the others overlaid again, until nothing is refused (a few passes at most);
a refusal is traced to its record by the entry, not by its target. The pack marks the slot -- the row
`written: false`, a column `unwritten: ["meaning", "code_values:X"]`, the text `（页面填写，尚未写回）` -- and
`/api/semantics` lists it in `unwritten_slots` beside `unwritten`. The export writes the structured entries
first -- each code value one single-object entry, never a list, which would replace the column's other codes
-- then the `question:` entry with `asked`; the structured entries carry no `asked` (`semantic confirm`
refuses it on a target that is not a question). Three things a replay does not do the way the page does:

- **The two entries are not one in a replay.** `semantic confirm --require-asked` after a rewrite leaves the
  `question:` entry unmatched, while the structured entry, addressed by column name, still applies. Read the
  unmatched list.
- **A changed code value cannot be withdrawn by a replay**: a single-object entry only merges, so an older
  entry for the same value, in a file that sorts later, says the old meaning again. When a page answer changes
  a code value's meaning on disk, the export says so (the board's 「导出前请看」, the command's `note:` lines
  on stderr): remove the old confirmation entry from `$RUN/confirmations/` before putting the new file there.
- **A code value the SQL never writes is not refused before validation.** Neither the page nor `semantic
  confirm` has the packet: a code value on a constant-only column, or an empty string no producer writes, is
  written back, and `semantic validate` fails it as 「确认与 SQL 矛盾，交回 owner」. Take it back to the owner.

Without structured records every output -- the board, `/api/semantics`, `/api/context`, the export -- is what
it was.

**Endpoints** (404 `not_configured` without `--answers`):

- `POST /api/answers` -- `{table, question, kind, answer | reason, choice?, to?, by, asked, seen}`. `asked`
  is the question's text as the page showed it and `seen` what the page showed of its state: `{disk:
  {answer, answered_by, answered_on} | null, record: <the page record shown> | null}` (the board's items
  carry `record`, `record_state` and `disk` when they have a record). 201 `{record}`. 409 when the question,
  its answer on disk or its record is not what the page saw (two people changing one record: the later is
  refused); 400 for a refused text, `choice` on another kind, a `redirect` without `to`, the same as what is
  there now, a note on a question answered on disk; 404 for an unknown table or question; 503 when the
  answers file cannot be read or written. A structured answer adds `target` and `value`, and `seen` becomes
  `{disk, record, slot}`; 400 for a value out of shape, a column the table does not have, an identifier
  column's code values, a row answer on a proven grain, or a slot another question's page answer holds; 409
  when `slot` is not the slot shown now.
- `POST /api/answers/withdraw` -- `{table, question, seen: <the record shown>}`: deletes the record (an
  answer then reads as its document says again). 200 `{withdrawn}`, 404 without a record, 409 when it changed.
- `GET /api/answers/export` -- the confirmations file (JSON only; `Content-Disposition: attachment`).
- `/api/questions` adds `answers`: `{status, writable, effective, exported, digests, unmatched: [{table,
  question, record, reason, message, now}], export_notes?, refused?, reason?, problem?}` (`now.slot` on a
  structured record; `export_notes` only when there is something to say).

**Texts and the injection path** -- an answer, a reason, a name and `to` are stored as typed, stripped of
leading and trailing whitespace only (full-width punctuation such as `：（），？` stays as written, into the
documents after `semantic confirm`), and refused when blank, longer than 1000 characters (an answer or a
reason) or 60 (a name), counted on the stripped text, or carrying a line break or a control or format
character. NFKC is used only to compare: question texts, and a new answer with the one already there.
They reach the text context pack, which is built line by line, and from there the ask panel's model
-- which holds a write tool -- and MCP clients. Answers from the page are always marked as not written back.

**Who may answer** -- the server has no authentication. On a loopback address only programs on this machine
reach it. On a non-loopback `--host`, or with any `--allow-host` (a loopback server behind a proxy or a
tunnel is reachable from elsewhere), the two writing endpoints are refused (403) and the cards are read-only,
unless the server is started with `--answers-allow-remote`, which prints a warning: any program that can
reach the port can answer under any name, and the answers' text enters the model's context and the MCP
output. The export writes nothing and is not affected.

**One writer** -- only the `http` server started with `--answers FILE` writes the file: its answers, and
the deletion of records written back (under the lock every request takes; the file is read again first and
only records still exactly as judged are deleted; a failed delete fails no request and is reported in
`/health`'s `answers.problem`). `mcp --answers FILE`, and any other server given the same file, overlay it
read-only and never write or delete. Two writers on one file are not protected against.

### Pasting platform results (`--probes`)

```bash
scope-lineage-service http out/ontology.json --semantics "$RUN/docs" --answers "$RUN/question-answers.json" \
  --probes "$RUN/probes/question-probes.json"
```

`--probes FILE` names a `question-probes/1` file (runbook S9b; read-only, read again when it changes; one
that cannot be read or is not that format stops the start with exit 2). Each table-semantics card on the
board then lists its question's queries (`probes` on the board's items: the SQL with a copy button -- the
placeholders are left for the person running it --, how to read the result, where it may land, and
`stale` when the question no longer reads as the query asked it). The server never runs a query.

- **Paste and preview.** The person running a query pastes its result as it came back: the one JSON
  object `{sql_id, status, run_on, bizdate, sql_executed, columns, rows, note}` (`elapsed_sec` may be
  there), at most 64 K characters; nothing else (no TSV or CSV) is read. For a query that lands
  (`lands`), `POST /api/probe-results/draft` returns the draft `{target, value, evidence}` and
  `pasted_sha256`, and the card shows every number, the partition and the query id. The draft is never
  stored. No draft -- `refused` with the reason -- when `sql_id` is not the probe's, `status` is not `ok`,
  `sql_executed` is not the probe's SQL with its placeholders filled in (whitespace aside), the columns are
  not exactly the query's own top-level output columns and the fixed columns of its shape (`rows, keys,
  duplicate_keys`; `value, cnt`), a count is null (an empty table), negative or not an integer, the counts
  disagree (`duplicate_keys <= keys <= rows`, no duplicates exactly when `rows == keys`, `rows` at least 1),
  a value set has more than 51 rows or a value twice, or a non-integer cell has a contact shape
  (`scope_lineage.semantics.probe_results`).
- **Confirm.** 「确认」 with the answerer's name posts `{probe, pasted, by, seen}` (`seen` is the draft shown,
  with `pasted_sha256`) to `POST /api/observations`: the server reads the pasted text again and stores the
  observation under `observations` in the answers file -- `{probe, table, question, asked, target, value,
  evidence, pasted_sha256, by, date}`, `by` the person who confirmed, one per slot (a later one replaces
  it). 201 `{observation}`; 409 when the draft is not the one shown (the text or the probes file changed);
  400 when there is no draft, the question was rewritten after the query was written, or `semantic confirm`
  would refuse the entry on the document on disk (an identifier column's values, say); 403 and 404 as for
  answers. `POST /api/observations/withdraw {seen}` deletes one (409 when it changed).
- **Not written back yet.** An observation is never overlaid on the documents: `/api/semantics` lists its
  target in `unwritten_slots` (`summary.row.observed`, `column:<c>.observed_values`, `input:<db.table>`),
  the table page marks it 「观测未写回」, and the board's `answers` gains `observations: {effective,
  records, unmatched}` with the observations listed above the export. Once the document holds the value
  (after the export is replayed) the record is deleted; a question rewritten or a column gone makes it not
  matched (not exported).
- **Export.** `/api/answers/export` and `answers export` write each observation in effect after the
  answers' entries, as an observation confirmation with `evidence` -- the reference `{probe, partition,
  on, sha256}` (the probes file's sha256). The rows of a result never leave the answers file.
- **Evidence for a sentence.** A query that lands nothing gives no draft; its pasted result previews as the
  reference `evidence`, and 「以此为依据回答」 posts a sentence answer with `probe_result: {probe, pasted}`
  (`/api/answers` takes the field only with `--probes`): the record's `source` is `{kind: "query", probe,
  partition, on, sha256}` and its exported `question:` entry carries the same `evidence`. No row is kept.

Without `--probes` the endpoint list, `/health`, the board and every other output are what they were; an
answers file without `observations` reads and writes byte for byte as before.

## Ask panel (opt-in)

The page's **问数** view takes a data question and has a model answer it -- on the server, never in the
browser -- by the skill's own walk (`skills/scope-lineage/workflows/catalog-answers.md`): search the catalog,
take one context pack, write the SQL, check it, list what the catalog lacks. The page shows each step as it
happens: the candidates the search found, the tables and columns taken into the pack, every `check-sql` round
with its findings, the final SQL, the basis given for each condition, and each `/* 待确认：… */` placeholder
with what is missing. The newest question is on top; once a question has an answer its steps fold into
one line that opens on a click. **A gap is recorded only when the asker agrees:** the model has no tool that
writes the pending file and its answer says each gap is 未记入 (not recorded); beside each placeholder the page
offers 「记入待确认」, one click records the gap (a definition typed in the box beside it is recorded as the
proposed one; it may be left empty), appending one line to the pending file through `POST /api/pending` (only
with `--pending`). The click sends `unless_recorded: true`: when the pending file already holds an item naming
the same missing thing (the grouping `catalog pending list` uses: NFKC, case folding, whitespace collapsed;
closed items included), nothing is appended and the page says 「已有人记过」 with that item's count, last date,
reply status and proposed definitions. A duplicate is reported rather than appended so one asker clicking
twice, or a second asker hitting the same gap, does not inflate the item's count; other clients of
`POST /api/pending` (without the field) append as `catalog pending add` does. **It never runs SQL** and never
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
| `--ask-trace DIR` | off | append a record of every question run to `DIR/<conversation id>.jsonl`, see below |
| `--ask-store DIR` | off | keep every conversation's full record in `DIR/<conversation id>.json`, so it survives a restart, see [Conversation memory](#conversation-memory) |
| `--ask-card-budget N` | 6000 | characters the conversation state card may take before older topics are archived (at least 500) |
| `--ask-today YYYY-MM-DD` | the server clock | the date every question is told is today (for tests and evaluation runs) |

How it runs:

- **The instructions are the walk.** The system prompt is a short preamble -- which tool stands for which
  command, and this service's limits (no SQL is run, no file can be read, answer in the asker's language,
  end with the walk's brief) -- followed by `catalog-answers.md` and the reference it cites, word for word.
  The package carries exact copies of the two skill files (`scope_lineage_service/ask/*.md`);
  `tests/test_ask_walk.py` fails when a copy differs from the skill, so the skill stays the one source.
- **The tools are the catalog answers.** `search_catalog`, `catalog_context`, `query_catalog`, `check_sql` --
  all read-only, with or without a pending file: the same functions, parameters and descriptions as the MCP
  tools. The walk's `catalog pending add` maps to no tool here; the preamble tells the model that the asker
  records a gap with the page's button and that it must not claim it recorded anything. A result is the command's text form (what it prints without `--json`), two to four times shorter than
  the JSON; the page gets a small structured summary of the same answer. Every input is checked against its
  tool's schema first, and a refused input comes back as a tool error with the command's sentence. Model
  output never becomes a path or a command.
- **The loop.** The service hosts a manual Messages API loop (official `anthropic` SDK, streamed requests,
  adaptive thinking, `tool_choice` auto): parallel tool calls run in order and their results go back in one
  message; `refusal` and `max_tokens` stop the question without running that turn's calls; `pause_turn` is
  continued. The tools and system prompt are one stable, cached prefix; the page shows the token usage of
  each question (input, cache reads and writes, output).
- **Follow-ups** carry the conversation's state card, not the transcript: every question's message starts
  with today's date and the card (see [Conversation memory](#conversation-memory)), and the model can fetch
  an earlier turn with `recall`. Conversations live in server memory under an unguessable id; without
  `--ask-store` a restart loses them, and the page says so. One question runs at a time per conversation;
  **停止** cancels it (at the next model event or tool call).
- **Safety.** Every POST must be JSON from this page's own origin (`Origin` exactly this host and port,
  `Sec-Fetch-Site: same-origin`, on top of the Host check), so no other site open in the browser can spend
  money or write the pending file; the page polls `GET /api/ask/events` (long polling, plain JSON responses
  under the same `Content-Security-Policy`). Model and catalog text are placed in the page as text only. No
  telemetry, no network call other than the model request.

| Method | Path | Parameters |
| --- | --- | --- |
| GET | `/api/ask/status` | none: whether asking works now (or why not), the default model, caps, `max_question_chars`, and `models`: each model's `id`, `label`, `provider`, `available`, `reason`, `default` (never a URL, a variable name or a key) |
| POST | `/api/ask` | `application/json`: `question` (at most 20,000 characters after trimming, enough for a pasted SQL; longer is 400 `bad_input`, and the page, which shows the limit from the status's `max_question_chars`, asks for the paste in parts before sending), `conversation` for a follow-up, `model` (an id from the status; default the server's default; a follow-up may name another); 202 with the conversation and run ids and the model, 400 for an unknown model, 409 for one that cannot answer now, while that conversation is still answering (`busy`), when it holds its 200 questions (`conversation_full`) or when its stored record has an older format (`read_only`) |
| GET | `/api/ask/events` | `conversation`, `run`, `after` (last event number seen), `wait` (0-25 s, default 20) |
| POST | `/api/ask/cancel` | `application/json`: `conversation` |
| GET | `/api/ask/conversation` | `conversation`: its runs still in memory, `turns` (every question of its record: `turn`, `question`, `status`, `topic`, `version`, `answer`, `notices`), the last `brief`, `memory` (the state card as the page shows it: current topic and SQL version, conditions, assumptions, statements, withdrawn statements, topic index, open question), `read_only` and `stored` |

### Conversation memory

A conversation is a sequence of numbered turns (the asker's Nth message is turn N). Three things carry it
from one question to the next, all kept by the service's code -- no extra model call:

- **Today's date.** Every question's message starts with `今天：YYYY-MM-DD（时区 ±HH:MM）` from the server
  clock, read again for each question (a conversation may cross midnight); `--ask-today` fixes the date. The
  walk says to resolve relative time ("上个月") against it and write the concrete dates into the SQL's
  parameter comment, and that dates in catalog examples are not "the latest".
- **The state card**, right after the date line, in the user message (never the system prompt, which stays
  byte-identical on every request so it caches). It replaces the previous question's brief:

  ~~~text
  今天：2026-11-25（时区 +08:00）
  【对话状态卡】服务维护；本轮是第 4 轮；目录版本：sha256:1a2b3c4d5e6f
  话题索引（回到旧话题、要旧版 SQL 时用 recall 按轮号或话题与版本取回）：
  - #1 客户数（当前） — 第 1–3 轮；SQL v1（第 1 轮）、v2（第 2 轮，按性别分）、v3（第 3 轮，只算有效客户）
  - #2 借据余额 — 第 4–4 轮；最终 v1（已归档，详情用 recall）
  当前话题：#1 客户数
  当前 SQL（#1 v3，第 3 轮）：
  ```sql
  SELECT …
  ```
  check-sql（服务对 #1 v3 重跑）：错误 0，警告 1，提示 2
  表：demo_dwd.dwd_party_customer_info_df — 一行是一个客户（某天的快照）
  条件：c.status_cd = 'A' — 提问者第 3 轮
  假设：期间 = 2026-01-01 ~ 2026-11-25
  提问者的说法（逐字；落在范围内的题要沿用，条件的依据写「提问者第 N 轮」）：
  - 第 3 轮「只算有效客户」— 范围：#1；表 demo_dwd.dwd_party_customer_info_df
  未决问题（上一轮问的；这轮没回答就按默认做法并说明）：…
  ~~~

  The catalog version is the first 12 hex digits of the sha256 of `ontology.json` (the file carries no build
  time); when it changes between questions the card says so. Code keeps the turn number, the topic index
  (turn range, SQL versions), the current SQL -- only the segment the answer's increment block marks
  `当前版`, versioned v1, v2, … by code; a segment left unmarked keeps the previous version and the turn is
  counted as 缺失 -- its check-sql result (run again by code), its placeholders, the asker's statements word for
  word (code copies them out of the asker's message; the model only points at the sentence -- a quote that is
  not word for word, or a correction with no statement marked, stores the whole message as a 待定说法 scoped to
  the current topic), withdrawn statements and the open question (cleared after the next question). The
  model's increment block replaces the topic's 表 / 关联 / 条件 / 假设 as a whole group when it marks a new 当前版,
  and adds name mappings and preferences. A missing or invalid block (unknown topic, SQL roles that do not
  number the answer's SQL blocks, a cited turn that does not exist) leaves every model field as it was; two
  in a row and the answer says the model may not suit multi-turn use. Not invalid: a missing topic line (the
  turn stays in the current topic), `SQL角色：无` beside a SQL block (no new version), a role note holding `；`
  (roles are split at each `段N=`), `新 #3 名称` for a new topic. A statement is a business rule, definition or
  correction the asker states (the walk gives examples); a quoted question is not kept.
- **The guard.** A statement has a scope (a topic and tables). It is checked when a question produced a new
  current SQL and stays in the statement's topic, or that SQL reads a table in scope; never for a 待定说法, a
  statement of the same turn, or a topic the asker said it does not apply to. It counts as kept when its turn
  is cited (`提问者第 N 轮`) in any 条件, 关联 or 表 line of the block, or when the current SQL contains the
  expression its 说法 line tied to it (`；SQL：<表达式>`, compared without whitespace or case). Not kept: the
  answer shown gets 「这次没有沿用你第 N 轮说的「X」，要不要加上？」 -- **once per statement**. The next card
  says 「上一轮提醒过：第 N 轮「…」是否加上」 and asks the model to read the asker's message as the reply and
  report it as `提醒答复：第 N 轮 加上` (and add the rule) or `提醒答复：第 N 轮 不加`. 「不加」 marks the
  statement 不适用 in that topic (no more prompts there); 「加上」 while the new SQL still does not keep it gives
  one more line; nothing else prompts again. A message answering a guard question is never recorded as a
  statement.
- **Budget.** Over `--ask-card-budget` characters (6,000), the least recently used topics other than the
  current one are archived to one index line each, then the current topic's SQL versions are listed by number
  and change note only; a line in the answer says what was archived. Statements are never archived: when a
  turn adds one and the statements other than 待定说法 pass their 1,500-character reserve, the answer lists them
  and asks which to drop.
- **`recall`.** A fifth tool, panel only and read-only: `recall(turn)` or `recall(topic, version)` returns
  that turn's question, the answer shown and every SQL block with its role and version. The conversation is
  bound by the service, never a parameter, so no other conversation is reachable. The preamble tells the
  model to use the card's index and `recall` for "回到第一个问题" or "第一版 SQL", and never to say a turn cannot
  be retrieved without calling it.

The page shows each answer's topic and SQL version, the lines the guard and the budget added, and (folded)
the statements and assumptions in effect after it.

**`--ask-store DIR`** keeps each conversation's full record on disk, off unless given and with no default
place. The directory is created with mode 0700; each conversation is `DIR/<conversation id>.json`, mode 0600,
rewritten whole through a temporary file and a rename after every change. Per question it holds the asker's
text, the answer shown, every SQL block with its role and version, the parsed increment block, the card after
the turn, and each tool call's name and arguments -- never a tool's result (catalog text), the system prompt or
a key. **It stores the question text, including any SQL or result data pasted into it**, so name a place
outside any repository or shared drive; delete a file to forget a conversation. The record format is
versioned (`schema: "ask-store/1"`); a file of another version is shown and recalled but never continued or
rewritten. After a restart a conversation is read back when its id is next used; a question that was running
is marked `interrupted` and never updated the card. At most 200 questions a conversation (409
`conversation_full`). Without `--ask-store` the same record lives in memory, and the card, the date, the
guard and `recall` work the same until the conversation is dropped.

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
an assembled SQL with placeholders) and an answer in the walk's format. Like a real model it has no tool that
writes the pending file; the page's 「记入待确认」 still writes when the reader clicks it. The page shows a banner and a 假模型 badge on
every answer, and every answer starts by saying it is not one.

```bash
scope-lineage-service http out/ontology.json --semantics semantics/ --pending pending.jsonl --ask-dev-fake-model
```

With `--ask-models FILE` as well, every model in the file is played by the fake (each named after its id,
none called), so the picker can be reviewed with the real file and no key.

### Recording runs (`--ask-trace DIR`)

Off unless given, and there is no default place: `--ask-trace DIR` (with `--ask`) appends one JSON line per
event of interest to `DIR/<conversation id>.jsonl` (DIR is created if missing; each file is created with mode
0600, and each line is one append, so a crash leaves whole lines). It only records: the questions, the
events, the answers and every response are the same with or without it. **It stores the asker's question
text and the answer text** (needed to score a run later), so keep DIR out of a repository or shared drive;
it never stores the catalog text the tools return, the system prompt, a key or a header. The conversation id
in the file name is the one in the page's address. Every line has `schema: "ask-trace/1"`, `kind`, `at`
(UTC), `conversation` and `run`; a failed write is logged as a warning and the question goes on.

| `kind` | When | Fields |
| --- | --- | --- |
| `turn` | each model turn | `turn`, `model_id` (the server's id), `model` (what the provider reported), `elapsed` (seconds of that request), `stop_reason`, `usage` (input, output, cache write and cache read tokens), `usage_estimated`, `request_chars` (characters of the message list sent, as JSON), `largest_tool_result_chars`, `tool_results` (tool results in that list) |
| `tool` | each tool call | `turn`, `id`, `name`, `input` (the arguments), `ok`, `result_chars` (the size of the text sent back, not the text) |
| `run` | the run finished | `model_id`, `question`, `follow_up`, `status`, `reason`, `error_kind` and `error_message` (first 300 characters of the provider's message; errors only, so a context overflow can be recognised), `answer` (the text, or null), `has_sql`, `has_brief`, `brief_missing`, `elapsed`, `turns`, `tool_calls`, `usage`, `usage_estimated`, `memory` (null without an answer: `turn`, `block` -- the increment block `ok` / `missing` / `invalid` --, `problems`, `sql_missing`, `card_chars` (the card this question carried), `card_chars_next`, `archived` (topics archived now), `guard` (the guard's lines), `statements_over`, `notices`) |

### Driving a scenario (`service/tools/ask_driver.py`)

A developer tool, not part of either package: it drives a running server's ask endpoints turn by turn the
way the page does, so an evaluator (a person, or an agent playing the asker) can run a multi-turn scenario
and read each answer as JSON. Standard library only; run it from a checkout.

```bash
scope-lineage-service http out/ontology.json --semantics semantics/ --ask --ask-trace /path/to/trace-dir
python service/tools/ask_driver.py send "a question"                        # a new conversation
python service/tools/ask_driver.py send --conversation ID "a follow-up"     # the same conversation
echo "a long question" | python service/tools/ask_driver.py send -          # the question on stdin
python service/tools/ask_driver.py show ID                                  # its runs and outcomes
```

`send` waits until the run finishes and prints `conversation`, `run`, `follow_up`, `model`, `status`,
`reason`, `detail`, `elapsed`, `answer`, `sql`, `brief`, `brief_missing`, `memory` (the answer event's topic,
SQL version, block status and added lines) and `usage`; it exits 0 when the
status is `done`, 1 for any other end, 2 when the server refused the request (its error on stderr).
`--server URL` (default `http://127.0.0.1:8765`), `--model ID` and `--timeout SECONDS` (stop waiting and
cancel the run) are optional.

## MCP

```bash
scope-lineage-service mcp ONTOLOGY [--semantics DIR] [--pending FILE] [--answers FILE]
```

With `--answers FILE` (the file an `http` server writes) the tools read the page's answers in effect,
marked as not written back; the MCP server never writes or prunes the file and has no tool to answer.

| Tool | Arguments | Same as |
| --- | --- | --- |
| `search_catalog` | `text`, `kinds`, `limit`, `format` | `catalog search` |
| `catalog_context` | `tables`, `columns`, `columns_of_table`, `concepts`, `brief`, `focus`, `format` | `catalog context` |
| `query_catalog` | `kind`, `term`, `format` | `catalog query` |
| `check_sql` | `sql`, `format` | `catalog check-sql` |
| `list_pending` | `format` | `catalog pending list` (with `--pending`) |
| `add_pending` | `question`, `missing` or `sql`, `sql_name`, `term`, `tables`, `columns`, `proposed`, `date`, `format` | `catalog pending add` (with `--pending`; its description tells the client to call it only after the asker agrees to record the gap) |

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
pending file is read on every list. The answers file has a signature of its own: when only it changes the
records are judged again without reading the ontology or the documents, and the server's own writes do not
make it read the file again. The servers never answer from a copy they know to be stale.

## Tests

The tests use the repository's demo ontology and table-semantics document, need no network, and start the
HTTP server on an ephemeral port of `127.0.0.1` and the MCP server in memory and as a stdio subprocess:

The browse page's pure JavaScript functions (the graph layout and its labels, the column filter, the table
sorts offered, the document title, the answer cards' state, `seen` and request bodies, and the ask panel's
placeholder reading, brief parsing and event view model) are checked by running the page's own modules with
`node` when it is on `PATH` (`test_service_page_js.py`, `test_service_answers_page_js.py`,
`test_ask_page_js.py`, `test_service_probe_page_js.py`, skipped otherwise; no JavaScript package is installed). The page's answers have their
own tests: the record file, every rule of the judgement and the deletes (`test_service_answers.py`) and the
endpoints, the outputs and the export through `semantic confirm` (`test_service_answers_http.py`); the
structured answers theirs (`test_service_structured_answers.py`); pasted platform results, drafts,
observations, evidence and the `--probes` guards theirs (`test_service_probe_results.py`). The run
records (`test_ask_trace.py`, including that every response is byte for byte the same without them) and the
scenario driver against the fake model (`test_ask_driver.py`) have theirs.

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
