[中文](../zh-CN/glossary-doc.md) | English

# glossary.json / glossary.md term and value dictionary (glossary-json/1)

`scope-lineage glossary` scans a **whole corpus** (a tree of `lineage.json` files) and
aggregates it into one dictionary organised by column name: which comments each name
carries, which constants the SQL compares it against, and which value sets the SQL has
proven closed. It answers the question one task cannot: `describe` can only say "this
field filters on `pay_status = 'PAID'`", while the dictionary can say "`pay_status`
appears in 9 tables, its comments say these three things, and the corpus has seen 4
distinct values in total".

## What it is: a corpus-level derived view, not a business glossary

- The dictionary has exactly **two** sources of content: the comments the contract
  carries (column, table and SQL comments) and the constants the contract carries. Core
  never guesses a meaning from a value's spelling, never translates, never paraphrases.
- `meaning` is filled only by a human (`glossary.overrides.json`), and is then marked
  `source: "override"`; `meaning_candidates` means "some comment's text **literally
  contains** this value", which is a lead, not a conclusion.
- **An observed value set is a floor, not a ceiling.** Only two things produce a
  `closed_set`: an `IN` list, and a CASE with an ELSE whose every THEN and ELSE is a
  constant. Everything else is `null` -- "the corpus has only seen 3 values" is not
  "this column only has 3 values".
- It is the early delivery of the phase-two ontology's (`ontology-json/1`)
  `value_domains` + `synonyms` slice, with aligned slots: the same (column, value,
  evidence, task count, completeness) five-tuple its `in_set` constraint carries.

## Usage

```bash
# one corpus -> one dictionary
scope-lineage glossary --lineage /path/to/corpus --out /path/to/dict

# with the meanings a human has confirmed
scope-lineage glossary --lineage /path/to/corpus --out /path/to/dict \
  --overrides /path/to/glossary.overrides.json

# JSON only
scope-lineage glossary --lineage /path/to/corpus --out /path/to/dict --format json

# hand the dictionary to describe, and field semantics carry value meanings
scope-lineage describe --lineage /path/to/task --glossary /path/to/dict/glossary.json
```

Python API (consumes contract document dicts, the same path the files take):

```python
from scope_lineage import build_glossary, render_glossary_markdown

glossary = build_glossary(lineage_documents, artifact_root="corpus", overrides=overrides)
markdown = render_glossary_markdown(glossary)
```

- `--lineage` is exactly what `render` / `describe` / `tables` accept: one `lineage.json`
  or a directory tree searched recursively for them; both contract shapes are accepted
  (statement documents `1.0` and task documents `2.0`); other versions are skipped and
  counted in directory mode, and are a hard error (exit 1) for a single named file.
- `--out` is required and receives `glossary.json` and `glossary.md`; `--format` takes
  `json`, `md`, or both.
- A `--overrides` path that does not exist, is not valid JSON, or is not a JSON object
  exits 2 -- silently ignoring a file a human has reviewed is worse than failing.
- `corpus.artifact_root` records the `--lineage` value **verbatim**. Pass a relative path
  when you want reproducible bytes.

## glossary.json structure (glossary-json/1)

```jsonc
{
  "doc_format": "glossary-json/1",
  "corpus": {"artifact_root": "…", "task_count": 12, "statement_count": 17,
             "lineage_digests": {"<task_id>": "8c292a40a47f1439"}},
  "terms": [
    {"column": "pay_status",
     "comments": [{"text": "Payment status", "tables": ["ods.app_order", "ods.web_order"], "count": 2}],
     "tables_total": 3, "tables_without_comment": ["ods.pos_order"], "conflict": false,
     "meaning": null}
  ],
  "values": [
    {"column_ref": "ods.app_order.pay_status", "column": "pay_status",
     "value": "'PAID'", "kind": "literal",
     "observations": [{"task": "order_daily", "statement_id": "stmt:001",
                       "context": "filter_eq", "evidence": "rule:003",
                       "expression": "pay_status = 'PAID'"}],
     "task_count": 2,
     "closed_set": {"values": ["'PAID'", "'REFUND'"], "basis": "in_list"},
     "meaning_candidates": [{"text": "Payment status; PAID means settled", "source": "column_comment",
                             "evidence": "column:ods.app_order.pay_status"}],
     "meaning": {"text": "Settled", "source": "override",
                 "confirmed_by": "owner", "date": "2026-09-18"}},
    {"column_ref": "cte:latest_dim.rn", "logical": true, "column": "rn",
     "value": "1", "kind": "literal",
     "observations": [{"task": "…", "statement_id": "stmt:001",
                       "context": "join_condition", "evidence": "rule:002",
                       "expression": "rn = 1"}],
     "task_count": 1, "closed_set": null, "meaning_candidates": [], "meaning": null}
  ],
  "parameters": [{"column_ref": "ods.app_order.dt", "expression": "dt = '${bizdate}'",
                  "kind": "parameterized", "task_count": 6}],
  "overrides_applied": {"terms": 1, "values": 2, "unmatched": ["pay_status='GONE'"]}
}
```

| Key | Content |
| --- | --- |
| `corpus` | What was scanned: `artifact_root` verbatim, the task count, the write-statement count, and each task's contract digest (the same digest function mapping.md / semantic.md use, so you can confirm the dictionary and a profile came from one snapshot) |
| `terms[]` | Comments merged across tables by **column name**; one entry per name, sorted by name |
| `values[]` | One entry per (column reference, value, `kind`); sorted by (column name, column reference, value, `kind`) |
| `parameters[]` | Columns pinned by a `${…}` variable or a function call: they pin the column, but they are not its values |
| `overrides_applied` | How many human confirmations took effect, and which keys matched nothing in the corpus |

### Terms (terms[])

| Key | Meaning |
| --- | --- |
| `comments[]` | One entry per distinct comment text, `tables[]` being the tables that wrote it (deduped, sorted by name) and `count` their number; ordered by (table count descending, text) |
| `tables_total` | How many tables in the corpus hold this column (inputs and targets both count; two catalog spellings of one table count once) |
| `tables_without_comment[]` | Tables that hold the column but wrote no column comment -- the "still undocumented" list |
| `conflict` | `true` when one column name has 2 or more different comment texts; the dictionary **keeps both side by side** rather than deciding for the authors |
| `meaning` | The human-confirmed column meaning; `null` until somebody confirms one |

### Value observations (values[])

`column_ref` is a physical column `<db.table>.<column>` where it can be; **when the
contract cannot pierce to one**, it is `<scope_id>.<column>` with `logical: true` -- a CTE
id is not a table name, and writing it where a table goes would invent one. The
attribution rule: a physical table is claimed only when **exactly one** of the rule's
`fields[]` carries that column name, otherwise the entry falls back to the scope level
(with two joined tables both holding `status`, either choice is a guess).

The `context` vocabulary (`observations[].context`):

| Value | Where it comes from |
| --- | --- |
| `filter_eq` / `filter_neq` | A WHERE / HAVING conjunct `col = constant` / `col <> constant` |
| `filter_in` | `col IN (…)`, one entry per list item, all sharing one `closed_set` |
| `filter_rlike` | `col LIKE 'pattern'` / `col RLIKE 'pattern'` -- **the whole pattern is one observation**, never split on `|`: splitting would invent two values the SQL never compares against. Its `kind` is `pattern`, not `literal` |
| `case_condition` | `col = constant` inside a CASE branch's WHEN condition |
| `case_then` | A CASE's THEN / ELSE constants, attributed to the column that CASE **produces** |
| `union_constant` | A constant projected inside one UNION branch, attributed to the target column |
| `constant_projection` | A constant projection outside any UNION branch, attributed to the target column |
| `join_condition` | A JOIN's extra condition (`ON … AND d.rn = 1`) |

Other rules:

- The `kind` vocabulary has four entries: `literal`, `pattern`, `parameterized`,
  `function`. Only the first two reach `values[]`; a `${…}` variable (`parameterized`) or
  a function call (`function`) is not a value of the column and goes to `parameters[]`; a
  column-to-column comparison (`a.x = b.y`) has no constant on either side and reaches
  neither list.
- `pattern` (WI-2.4b) is the match shape on the right of a `LIKE` / `RLIKE`:
  `col LIKE '%UNIT_OUT_%'` names the **shape** this column's values have, not a value it
  ever holds. It is still an observation about the column, so it stays in `values[]`, but
  its `closed_set` is always `null` and it takes no part in any closed-set decision --
  listing it beside the enumerated values would say something the SQL never said.
  `LIKE '${prefix}%'` stays `parameterized`: being a substitution is the bigger fact
  about it.
- `NULL` is not published as a value (it is an absence, not a code), but it does count
  towards a CASE's exhaustiveness: `ELSE NULL` closes the branch set just the same.
- `closed_set` is published only when the corpus's closure claims for that column
  **agree**: two tasks with different `IN` lists give `null`, because contradictory
  evidence is not a closed set.
- `meaning_candidates[]` is a **literal match only**: the value with its quotes stripped
  must occur in the comment text (case-insensitively). Candidate comments come from three
  places: that column's comment (`column_comment`), that table's comment
  (`table_comment`), and the SQL comment written on that condition or field
  (`sql_comment`). **A value shorter than 2 characters never matches** -- `0` occurs in
  almost any sentence, and one wrong candidate costs more than ten missed ones.

### Parameterised values (parameters[])

`{column_ref, expression, kind, task_count}`, where `kind` is `parameterized` (a `${…}`
variable, including one written inside quotes as `'${bizdate}'`) or `function` (a call
such as `date_sub(current_date(), 1)`). `expression` is the predicate with qualifiers and
backticks removed.

## overrides: how a human answer gets written back

```json
{
  "terms": {
    "pay_status": {"meaning": "支付状态", "confirmed_by": "owner", "date": "2026-09-18"}
  },
  "values": {
    "ods.app_order.pay_status='PAID'": {"meaning": "已支付", "confirmed_by": "owner", "date": "2026-09-18"},
    "pay_status='REFUND'": {"meaning": "已退款"}
  }
}
```

| Rule | Detail |
| --- | --- |
| Two key forms | Qualified (`ods.app_order.pay_status='PAID'`) matches that one column; bare (`pay_status='PAID'`) matches **every** same-named column in the corpus |
| Table matching | The same rule the dictionary uses internally: suffix matching, so `ods.t` and `catalog.ods.t` are one table |
| Value matching | Compared with quotes stripped, so `'PAID'` and `PAID` are the same value |
| Merge precedence | An override always beats a candidate: on a match `meaning.source` is `override`, and `meaning_candidates` is kept as it was |
| Keys that match nothing | Go to `overrides_applied.unmatched` (sorted) and are **never dropped silently** -- a typo in a file a human reviewed is exactly what the reviewer cannot see |

## describe consumption: fields[].value_domain

`describe` always publishes `fields[].value_domain`, **including without `--glossary`** --
it then holds only what this one statement proves, with every `meaning` `null` (one
statement cannot know what a value means). Passing `--glossary` swaps in the corpus-level
observations along with the meanings a human confirmed.

```jsonc
"value_domain": [
  {"value": "'PAID'", "kind": "literal", "seen_in": ["rule:003", "mc:004"],
   "closed_set": true, "meaning": {"text": "已支付", "status": "confirmed"}},
  {"value": "'REFUND'", "kind": "literal", "seen_in": ["rule:003"],
   "closed_set": true, "meaning": {"text": "Payment status; REFUND means refunded", "status": "candidate"}},
  {"value": "'%UNIT_OUT_%'", "kind": "pattern", "seen_in": ["rule:007"],
   "closed_set": null, "meaning": null}
]
```

| Rule | Detail |
| --- | --- |
| When it appears | Only when non-empty; a field with no observed value carries no such key |
| One entry per value | Deduplicated by (`value`, `kind`): a value several observations prove (two CASE branches, two branch scopes) is written once, and the evidence is merged into `seen_in` (deduplicated, order preserved). A field's domain is a **set** of values; how often each was seen belongs in `seen_in` |
| Entry order | The order the values were **first observed**; never re-sorted |
| `kind` | `literal` (an enumerated value) or `pattern` (a `LIKE` / `RLIKE` match shape). A `pattern` always has `closed_set: null`, takes no part in the closed-set decision, and never reaches the `summary` suffix |
| Matching by source column | A field inherits its source physical column's values only when its last transform is `DIRECT` / `UNION` (the value reaches the target unchanged) -- `CASE WHEN pay_status = 'PAID' THEN 'Y' ELSE 'N' END` reads `pay_status`, but `'PAID'` is emphatically not a value of `paid_flag` |
| Matching by target column name | The `case_then` / `union_constant` / `constant_projection` observations match by **column name**, which is how a CASE's enum reaches the same-named target field |
| `closed_set` | `true` means this value belongs to a set the SQL proved closed; `null` means **not proven closed**, never "proven open" |
| `meaning.status` | `confirmed` (human) or `candidate` (a literal comment hit) |
| `summary` suffix | Only a **confirmed** meaning is appended to the sentence (`；取值：'PAID'（已支付）`, at most 3): a candidate is "some comment happens to contain this value", and putting it into the line a reader stops at would read as a definition |
| `confidence.metadata_coverage.glossary` | `{values_total, confirmed, candidate}`; absent when the statement has no value observation at all |

Section 5 of `semantic.md` gains one `- 取值：` line per field subsection: a confirmed
meaning is written plainly, a candidate is prefixed `? `, and neither gives 「待确认」.
When every **enumerated** value in the column is closed, the line adds
「（该列取值已被 SQL 证明封闭）」. The trailing `SQL事实` tag vouches for the values only --
a meaning is not a SQL fact, so its three-state marker is written inside the value.

WI-2.4b adds two bounds to that line:

- at most 12 enumerated values; past that it writes
  「等 N 个，完整见 semantic.json value_domain」 -- the line is a summary, `semantic.json`
  is the record;
- a `pattern` is never listed beside the enumerated values. It trails the line under its
  own 「匹配模式：…」 label and carries no 「待确认」 marker, because a match shape is not a
  code waiting for somebody to define it.

## The sections of glossary.md

One section per column name (`## <column name>`), holding in order: the term lines (the
merged comments, a `⚠` conflict note, the tables missing a comment, the column meaning),
the value table (value / column reference / kind / task count / context / closed set /
meaning), and the parameterised-value lines. A column name with neither a comment nor a
single constant comparison is named once, in the trailing "other columns" section.

Same input, same bytes: the document carries no timestamp, every list and table is sorted
on a stable key, and the order the corpus was read in does not change the result.

## What it does not do

- It does not name fields in business terms, does not guess what a code means, and does
  not present an observed value set as a complete enumeration;
- it does not connect to a database to sample values;
- it does not decide a comment conflict for the authors -- both readings stand side by
  side, for a human to answer.
