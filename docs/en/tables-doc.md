English | [中文](../zh-CN/tables-doc.md)

# tables.json / tables.md corpus-level table cards (tables-json/1, tables-md/1)

`scope-lineage tables` walks every `lineage.json` under one corpus directory, builds one
[semantic profile](semantic-doc.md) per task, and merges the producing and consuming sides
of **the same table** into one card: who writes it, what one of its rows represents, which
columns it has, who reads it, which columns they read and how.

One task's `semantic.json` answers "what does this task do". A table card answers the
question a single task can never answer — **"what is this table"**. The upstream task has
already proved its output's grain and keys; the downstream task no longer has to guess.

## Position: a corpus-level derived view, not a business definition

- A table card is a **derived view** of the versioned contract, a sibling of
  [mapping.md](mapping-doc.md) and [semantic.json](semantic-doc.md): every line comes from
  some task's `lineage.json` and links back by task name, `statement_id` and column name.
- Every line on a card traces to a concrete statement in the corpus. Core does exactly
  three things here: **merge, count, and restate in structural words**. It does not name a
  table in business terms, judge its type (wide table / dimension / metric table), or guess
  what a column means — those absences are the design.
- Stability tiers match the semantic document: contract ids, table names and column names
  are join keys; `tables.json` key names are stable within `tables-json/1`; wording and
  layout may be adjusted, so machines should read the JSON, not the Markdown.

## Usage

```bash
# A corpus directory: lineage.json is found recursively, artifacts are written to --out
scope-lineage tables --lineage /path/to/corpus --out /path/to/tables

# Machine-readable JSON only
scope-lineage tables --lineage /path/to/corpus --out /path/to/tables --format json
```

Three artifacts:

| File | Read by | Content |
| --- | --- | --- |
| `tables.json` | machines / RAG | the main artifact, `doc_format: "tables-json/1"` |
| `tables.md` | people | index: table / producing tasks / consuming tasks / comment present / business domain / key confidence |
| `tables/<db.table>.md` | people / RAG chunked per table | one card per table, six fixed sections |

Python API (consumes semantic profiles, the same path the files are written through):

```python
from scope_lineage import build_semantic_profile, build_table_cards
from scope_lineage import render_table_card_markdown, render_table_index_markdown

profiles = [build_semantic_profile(document, diagnostics) for document, diagnostics in corpus]
cards = build_table_cards(profiles, artifact_root="/path/to/corpus")
index = render_table_index_markdown(cards)
card = render_table_card_markdown(cards["tables"][0])
```

- `--lineage` behaves exactly as it does for `render` / `describe`: one `lineage.json` or a
  tree searched recursively for it, with the sibling `diagnostics.json` paired
  automatically; documents of an unknown version are skipped and counted in directory mode.
- `--out` is required: a table card is a corpus-level artifact, so there is no "next to the
  lineage.json" place to put it.
- `--format` takes `json`, `md` or both (default `json,md`); anything else is an argument
  error (exit code 2).
- Deterministic: the same corpus produces the same bytes whatever order it was walked in.

## tables.json structure (tables-json/1)

```jsonc
{
  "doc_format": "tables-json/1",
  "corpus": {"artifact_root": "…", "task_count": 5, "lineage_digests": {"<task>": "…"}},
  "tables": [
    {
      "table": "spark_catalog.mart.customer_daily",   // normalized primary name (longest spelling)
      "aliases": ["mart.customer_daily"],             // the other spellings seen in the corpus
      "comment": null,                                 // metadata fact; absent means null
      "domain": null, "project": null, "owner": null, "layer": null,  // table-level metadata facts
      "kind": "physical",
      "produced_by": [
        {"task": "…", "statement_id": "stmt:001", "stmt_kind": "INSERT_OVERWRITE",
         "partition": {"columns": ["dt"], "mode": "static", "spec": {"dt": "'20250101'"}},
         "grain": {"basis": "group_by", "keys": ["customer_id"]},
         "candidate_keys": ["customer_id"], "key_confidence": "proven",
         "fields": [{"column": "…", "comment": null, "summary": "…", "structural_role": "measure"}],
         "refresh": {"cycle": "day", "cron": "…", "source": "task_meta"},
         "header_comments": ["…"], "lineage_digest": "…"}
      ],
      "consumed_by": [
        {"task": "…", "statement_id": "stmt:001", "role_in_task": "driving", "roles": ["driving"],
         "columns": [{"name": "customer_id", "usages": ["join_key"]}],
         "read_by_scopes": ["ROOT"]}
      ],
      "columns": [
        {"name": "customer_id", "type": "string", "comment": null,
         "produced_summary": "…", "consumer_usage_counts": {"join_key": 2, "filter": 1}}
      ],
      "coverage": {"column_comment_ratio": 0.0, "table_comment": false, "producers": 1, "consumers": 2},
      "findings": [{"kind": "never_consumed_in_corpus", "text": "…",
                    "evidence": [{"task": "…", "statement_id": "stmt:001"}]}]
    }
  ]
}
```

- Each `produced_by[]` entry comes from that task's semantic profile (`task`,
  `output_shape`, `fields`); `refresh` comes from the task JSON's `meta`
  (`schedule_cycle` / `schedule`) and stays `null` when none was supplied — a cadence is
  never guessed from a partition column or a table name.
- `consumed_by[].columns` lists only the columns a logic block **actually reads**;
  `columns[]` is the union of the produced fields and the consumed columns, so even a
  read-only table has a full column list (from its `related_metadata`).
- `consumer_usage_counts` uses `filter`, `partition_filter`, `join_key`, `group_by`,
  `window_partition`, `window_order` and `output`, published in that order; a key whose
  count is zero is not published.

### Table-name normalization

One corpus commonly records the same table at several qualification levels (`mart.t` where
it is read, `catalog.mart.t` where it is written). Cards group those by the **dotted-suffix**
rule (the same semantics as `_same_table` in `skills/scope-lineage/scripts/query.py`), take
the **most qualified spelling as the primary name**, and publish the rest under `aliases`
rather than dropping them.

### What never becomes a table

- **Session-scoped relations**: a `CREATE TEMPORARY VIEW` and friends live only inside the
  script and no other task can read them; the rule is the one the task document's
  `final_table_states` / `produced_tables` already applies;
- **`directory:` targets**: writing a directory is not writing a table, and no catalog
  declares one.

Neither becomes a card, and neither shows up in another table's `aliases`.

## The six sections of `tables/<db.table>.md`

| Section | Question it answers | Source of the facts |
| --- | --- | --- |
| 1 What this table is | table comment, business placement (domain / project / owner / layer, shown only when the metadata states it), alias spellings, producing/consuming statement counts | metadata facts + the producing statements' header comments (`SQL注释`, quoted verbatim) |
| 2 What one row represents | each producing statement's grain, logical keys, candidate keys, key confidence | structural inference (evidence is the `statement_id`) |
| 3 Columns | column / type / comment / one produced-side sentence / consumer usage counts | metadata facts + SQL facts + structural inference |
| 4 Who produces it | task, statement, write mode, partition, refresh cadence | SQL facts + task metadata |
| 5 Who consumes it | task, statement, role, which columns, how they are used | SQL facts + structural inference (the role) |
| 6 Governance leads | multiple producers, key conflicts, never read, never written | SQL facts (evidence is `<task>/<statement_id>`) |

Line tags follow [semantic.md](semantic-doc.md): `（元数据事实）`, `（SQL事实）`,
`（结构推断；证据 …）`, `（SQL注释）`. The file name replaces `/`, spaces and anything else
a file system refuses with `_`.

`findings[].kind` has exactly four values, each meaning "this is observable in the corpus"
rather than a verdict:

| kind | Meaning |
| --- | --- |
| `multiple_producers` | more than one write statement writes this table; which result a reader sees depends on scheduling order |
| `producer_key_conflict` | the producing statements disagree about the candidate key, so a person has to settle the definition |
| `never_consumed_in_corpus` | no task in the corpus reads it; it may be an external hand-off, or an unread output |
| `never_produced_in_corpus` | no task in the corpus writes it, so what one of its rows represents cannot be proved here |

## describe consuming the cards: `describe --tables`

```bash
scope-lineage tables   --lineage /path/to/corpus --out /path/to/tables
scope-lineage describe --lineage /path/to/corpus/one_task/lineage.json \
  --tables /path/to/tables/tables.json
```

With `--tables`, `semantic.json` gains three things (matched on the normalized table name),
and a fourth is **rewritten**: `output_shape` (see "Cards decide a fan-out" below):

```jsonc
{
  "task": {
    "downstream_consumers": [{"task": "…", "role_in_task": "driving", "columns": ["customer_id"]}]
  },
  "inputs": [
    {"table": "mart.customer_daily",
     "card": {"produced_by_task": "…", "grain_text": "分组聚合后的一行；逻辑键 customer_id；…",
              "candidate_keys": ["customer_id"], "key_confidence": "proven",
              "comment": null, "refresh": {"cycle": "day", "cron": "…", "source": "task_meta"}}}
  ],
  "confidence": {
    "metadata_coverage": {"table_cards": {"inputs_with_card": 1, "inputs_total": 3, "consumers": 2}}
  }
}
```

`semantic.md` gains two things: section 1's input table grows a "一行是什么（来自生产任务）"
column, and the target-table lines are followed by a "下游消费：…" line.

- When no task in the corpus writes an input table, that input's `card` is `null` and the
  table cell reads "⚠ 本语料内无生产任务" — **"no corpus was supplied" and "the corpus
  proves nobody writes it" are different answers and never render alike**.
- When there IS a producing task but that task could not decide its own grain,
  `card.grain_text` reads `生产任务 <task> 未能判定粒度（<why the upstream grain walk
  stopped>）` rather than opening with 「未知」 — "no producer" and "a producer that could
  not tell" are two different answers as well.

### Cards decide a fan-out

One statement can never prove a physical table unique by the join keys, so a JOIN onto one
could only end at `unknown` / 「物理表无主键事实」. A table card holds another task's proof,
so `describe --tables` **recomputes** `output_shape` once the cards are attached:

| Condition | Result |
| --- | --- |
| The JOIN's right side is a physical table whose card has `key_confidence: "proven"` and whose `candidate_keys` are a subset of that JOIN's right-side key columns | that risk becomes `safe`, its `reason` reads 「生产任务 `<task>` 已证明 `<keys>` 唯一（表卡）」, and it carries `basis: "table_card"` |
| The same, but the card's `key_confidence` is `candidate` | still `safe`, but the `reason` says 「表卡候选键，未证唯一」 and the statement's whole `key_confidence` is capped at `candidate` |
| The card's `key_confidence` is `proven_unexposed` or `none`, or the join keys do not cover the candidate keys | nothing is re-decided; the original verdict stands |

Once a verdict changes, `candidate_keys`, `unexposed_keys`, `key_evidence` and
`key_confidence` are recomputed with the new risk set — they were always functions of
"every JOIN on the path is `safe`". When no card re-decided anything, `output_shape` is
returned as it was, byte for byte.
- Without `--tables`, those three keys **do not appear at all**, and `semantic.json` /
  `semantic.md` are byte-identical to what they were before table cards existed. Pass
  `--tables` when you want the empty-value semantics.
- A `--tables` path that does not exist (exit code 2) or is not a `tables-json/1` document
  (exit code 1) is an error, never a silent fallback to "no cards".

## What this does not do

- It does not name a table or column in business terms, infer a table type, or guess what a
  code value means (value domains and terms belong to the glossary layer);
- It does not sample a database, so a card has no "sample values" slot;
- It does not compute a transitive closure across the corpus — a card states only "who
  writes and who reads, in this corpus"; for lineage tracing see `query.py trace` in the
  [Agent skill](agent-skill.md).
