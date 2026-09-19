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

# also write a fill-in 取值含义 form (.md for a person, the same-named .json as --overrides)
scope-lineage glossary --lineage /path/to/corpus --out /path/to/dict \
  --template /path/to/dict/glossary.overrides.template.md --template-top 20

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
     "value": "PAID", "sql_literal": "'PAID'", "kind": "literal",
     "observations": [{"task": "order_daily", "statement_id": "stmt:001",
                       "context": "filter_eq", "evidence": "rule:003",
                       "expression": "pay_status = 'PAID'"}],
     "task_count": 2,
     "closed_set": {"values": ["PAID", "REFUND"], "basis": "in_list"},
     "meaning_candidates": [{"text": "Payment status; PAID means settled", "source": "column_comment",
                             "evidence": "column:ods.app_order.pay_status"}],
     "meaning": {"text": "Settled", "source": "override",
                 "confirmed_by": "owner", "date": "2026-09-18"}},
    {"column_ref": "cte:latest_dim.rn", "logical": true, "column": "rn",
     "value": "1", "sql_literal": "1", "kind": "literal",
     "observations": [{"task": "…", "statement_id": "stmt:001",
                       "context": "join_condition", "evidence": "rule:002",
                       "expression": "rn = 1"}],
     "task_count": 1, "closed_set": null, "meaning_candidates": [], "meaning": null}
  ],
  "parameters": [{"column_ref": "ods.app_order.dt", "expression": "dt = '${bizdate}'",
                  "kind": "parameterized", "task_count": 6}],
  "overrides_applied": {"terms": 1, "values": 2, "blank": 0,
                        "unmatched": ["pay_status='GONE'"]}
}
```

| Key | Content |
| --- | --- |
| `corpus` | What was scanned: `artifact_root` verbatim, the task count, the write-statement count, and each task's contract digest (the same digest function mapping.md / semantic.md use, so you can confirm the dictionary and a profile came from one snapshot) |
| `terms[]` | Comments merged across tables by **column name**; one entry per name, sorted by name |
| `values[]` | One entry per (column reference, value, `kind`); sorted by (column name, column reference, value, `kind`). `value` is the normalized, unquoted form and `sql_literal` is the literal the author wrote |
| `parameters[]` | Columns pinned by a `${…}` variable or a function call: they pin the column, but they are not its values |
| `overrides_applied` | How many human confirmations took effect (`terms` / `values`), how many keys are still blank (`blank`), and which keys matched nothing in the corpus (`unmatched`) |

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
| `union_constant` | A constant projected inside one UNION branch, attributed to **the column that branch projects it as** (see below) |
| `constant_projection` | A constant projection outside any UNION branch, attributed the same way: to the output column of the step that produces it |
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
- A value is stored **with its SQL quotes stripped**: `value` is `PAID`, the author's
  `'PAID'` stays in `sql_literal`, and the predicate as written stays in
  `observations[].expression`. Numbers are unchanged (`0` is `0`). One value the corpus
  spells `'0'` here and `0` there therefore merges into one entry, whose `sql_literal` is
  the first spelling in sorted order. The markdown and the overrides keys follow the same
  rule: **display `sql_literal`, key on `value`**.
- **A projected constant belongs to the column that step projects it as** (WI-2.10 A).
  Every `constant` step of a field chain (`field_mapping_chains[].ordered_steps[]`)
  carries an `output_field` -- `union:xxx:b01.data_source`, or `<target table>.<column>`
  at the root -- and the observation is filed there. Following that output column
  downstream, **while every step on the way is a pass-through (`DIRECT` / `UNION`)** the
  constant still is what the target column holds, so it is published as
  `<target table>.<column>`; as soon as one step **consumes** it (an aggregate, an
  arithmetic step, a CASE reading it) the observation stays on the scope-level column
  that produced it, flagged `logical: true`.
  The counter-example came from a real corpus: the chain of
  `x = SUM(CASE WHEN data_source = 'contract' THEN amt END)` legitimately contains the
  step `'contract' AS data_source`, so attributing every constant step to the chain's
  **target** published `contract` / `inner` as values of a `decimal` amount column. They
  are values of `data_source`.
- **The declared-type guard** (WI-2.10 A): a quoted literal only reaches a physical
  column declared numeric or temporal when the text inside the quotes is itself of that
  type -- `'Y'` is not a value any `decimal(15,2)` column ever held. A column whose type
  the metadata does not give admits everything: this layer does not guess. The same rule
  runs on the describe side (`value_domain`) and where the dictionary is collected.
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
| Value matching | Quotes are stripped on both sides, so `'PAID'` and `PAID` are the same value; **prefer the unquoted `pay_status=PAID`**, which is what `values[].value` holds |
| Merge precedence | An override always beats a candidate: on a match `meaning.source` is `override`, and `meaning_candidates` is kept as it was |
| Keys that match nothing | Go to `overrides_applied.unmatched` (sorted) and are **never dropped silently** -- a typo in a file a human reviewed is exactly what the reviewer cannot see |

## The fill-in form: `glossary --template`

Once the profile's open-questions list was capped at **five items** (WI-2.9), "what does
this code mean" stopped being asked one question at a time -- it was never really a
question, it is a **form**. `--template` generates that form:

```bash
scope-lineage glossary --lineage corpus --out dict \
  --template dict/glossary.overrides.template.md --template-top 20
# the owner writes the meanings into the .md and the same-named .json, then
scope-lineage glossary --lineage corpus --out dict --overrides dict/glossary.overrides.template.json
```

One `--template` path writes two files: the `.md` is what a person fills in (one section
per column, one row per value) and the same-named `.json` is what `--overrides` reads
straight back (`doc_format: "glossary-overrides-template/1"`, `values` keyed on
`<table.column>=<unquoted value>`, an empty `meaning`, and today's `date`). Both files ask
about the same values.

`--template` still needs `--out`: the form is **a ranking of the dictionary**, not a
replacement for it. Without `--out` the command stops with exit code 2 and prints that
reason.

**Which values reach the form** (nothing else is asked, WI-2.10 B):

| Rule | Detail |
| --- | --- |
| `kind = literal` only | A `pattern` is a `LIKE` / `RLIKE` match shape rather than a value, and nobody can give a shape a business meaning |
| Physical columns only | A `logical: true` reference, or any `column_ref` containing `:`, is a scope id, and as an overrides key it would match nothing |
| No switches | `Y` / `N` / `yes` / `no` / `true` / `false` (case-insensitively) answer "yes or no", which the reader already knows |
| No bare numbers | `rn = 1` and `flag = 0` are positions and switches -- **excluded even inside a proven closed set**, because `IN (0, 1, 2)` only pins a position to a set |
| No date-shaped literals | `'20260814'` is an instance date, not a code (see `instance_date` in the semantic doc) |
| No column left with fewer than two values | One value is not a code system, and the answer describes no set |
| Nothing already confirmed | A value whose `meaning` already carries text is not asked twice |

**Order and size**: the first version ranked closed sets first and then by observation
count, and a real corpus spent its whole first page on `Y` / `N`, `1` / `0` and
scope-level columns -- the exclusions above are that finding. Ranking now runs over
**columns**, scored

```
distinct values × 2 + Σ task_count + 3×(has filter_in) + 2×(has case_then) + 2×(comment clue)
```

where a comment clue is one of `编码` / `代码` / `类型` / `状态` / `标记` / `code` / `type` /
`status` / `flag` in the column's corpus comment. It is a **ranking signal only** and never
becomes a value's meaning -- "this column is probably worth asking about" and "I know what
this value means" are different claims. Ties break on the column name, values inside a
column order by task count, observation count and spelling, so two runs over one corpus
produce identical bytes. `--template-top` still caps the number of **values** (default 20);
the cut may land inside a column, and every column before it is whole.

**What it did not ask about is in the header**: `generated.excluded_values` and
`generated.excluded_scope_columns`, rendered in the markdown as one line,
`> 排除了 N 个开关/数字/日期型取值与 M 个 scope 级列。` A form that asks about three columns
has to let a reader tell "the corpus held nothing else" from "everything else was skipped".

**A blank entry is not an answer**: the form ships entirely blank and comes back half
filled, which is normal. When `--overrides` reads a key whose `meaning` is an empty
string it **skips it and counts it under `overrides_applied.blank`** rather than writing
it in as a confirmed empty meaning -- "nobody has said" and "somebody said nothing" are
different claims.

## The write-back loop: how an answer reaches the dictionary and the metadata

Every item of a profile's third piece (the open-questions list) carries a 回写目标 line, and
that line is what routes it. Once the business owner has answered:

```bash
# 1. 业务方在 business_profile.md 的每条待确认项里填 `- 答案：…`
# 2. 把答案分流成两份回写文件（--dry-run 只打印）
python3 skills/scope-lineage/scripts/confirmations.py apply <画像>/business_profile.md \
  --by owner --overrides dict/glossary.overrides.json --patch dict/metadata-patch.json

# 3. 重跑字典与画像，已确认项就不再是问题
scope-lineage glossary --lineage corpus --out dict --overrides dict/glossary.overrides.json
scope-lineage describe --lineage corpus --glossary dict/glossary.json \
  --metadata-patch dict/metadata-patch.json
```

| Write-back target | Which file | Written as |
| --- | --- | --- |
| `术语:<term>` | `glossary.overrides.json` | `terms["<term>"] = {meaning, confirmed_by, date}` |
| `值域:<column>=<value>` | `glossary.overrides.json` | `values["<column>=<value>"] = {meaning, confirmed_by, date}` |
| `字段注释:<table.column>` | `metadata-patch.json` | `columns["<table.column>"] = {comment, confirmed_by, date}` |
| `表注释:<table>` | `metadata-patch.json` | `tables["<table>"] = {table_name_cn, confirmed_by, date}` |

The script's rules:

- **Merge, never overwrite**: a key the target file already holds is kept and counted under
  `kept_existing` — two reviewers can each answer a round without either erasing the other;
- **An unanswered item is skipped and counted**: `- 答案：（待填）`, an empty answer, or no
  answer line at all counts as `unanswered` — a question nobody answered is not a blank answer;
- **A write-back target that is not one of the four is skipped and counted** (`no_target`):
  the template's four-way line left as written is not an answer, and guessing one of the four
  would file the answer under the wrong key;
- `--by` is recorded as each entry's `confirmed_by`, `date` defaults to today and `--date` overrides it;
- **No empty file is created** when nothing was written — an empty file reads as "every
  confirmation was cleared".

In the next round the skeleton already carries those answers as facts, and the prompt requires
that **no `Q` be generated for them** again:

| Skeleton key | Filled by | Meaning |
| --- | --- | --- |
| `fields[].value_domain[].meaning.status = "confirmed"` | `glossary --overrides` | This value's meaning is confirmed |
| `fields[].target_comment_source = "patch"` | `describe --metadata-patch` | The target field's comment came from a write-back |
| `inputs[].comment_source = "patch"` | Likewise | The input table's readable name came from a write-back |
| `confidence.confirmations` | Both | `{values_confirmed, terms_confirmed, columns_patched, tables_patched}`, the four counts of confirmed items |

The patch file's own format, its matching rules and `parse --metadata-patch` are documented in
[Core input formats](input-formats.md).

## describe consumption: fields[].value_domain

`describe` always publishes `fields[].value_domain`, **including without `--glossary`** --
it then holds only what this one statement proves, with every `meaning` `null` (one
statement cannot know what a value means). Passing `--glossary` swaps in the corpus-level
observations along with the meanings a human confirmed.

A `--glossary` path that does not exist or is not valid JSON (exit code 2), or that does
not declare `doc_format: "glossary-json/1"` (exit code 1), is an error -- the same rule
`--tables` follows. Both are JSON objects, so handing `--glossary` the
`glossary.overrides.json` by mistake used to be accepted silently, and the result was a
document with no value domains at all, which reads exactly like a corpus that observed
nothing.

```jsonc
"value_domain": [
  {"value": "PAID", "sql_literal": "'PAID'", "kind": "literal",
   "seen_in": ["rule:003", "mc:004"], "closed_set": true, "meaning": {"text": "已支付", "status": "confirmed"}},
  {"value": "REFUND", "sql_literal": "'REFUND'", "kind": "literal",
   "seen_in": ["rule:003"], "closed_set": true, "meaning": {"text": "Payment status; REFUND means refunded", "status": "candidate"}},
  {"value": "%UNIT_OUT_%", "sql_literal": "'%UNIT_OUT_%'", "kind": "pattern",
   "seen_in": ["rule:007"], "closed_set": null, "meaning": null}
]
```

| Rule | Detail |
| --- | --- |
| When it appears | Only when non-empty; a field with no observed value carries no such key |
| One entry per value | Deduplicated by (`value`, `kind`): a value several observations prove (two CASE branches, two branch scopes) is written once, and the evidence is merged into `seen_in` (deduplicated, order preserved). A field's domain is a **set** of values; how often each was seen belongs in `seen_in` |
| Entry order | The order the values were **first observed**; never re-sorted |
| `kind` | `literal` (an enumerated value) or `pattern` (a `LIKE` / `RLIKE` match shape). A `pattern` always has `closed_set: null`, takes no part in the closed-set decision, and never reaches the `summary` suffix |
| Matching by source column | A field inherits its source physical column's values only when **every step of the chain** is `DIRECT` / `UNION` (the field's own `transform` and that source's `sources[].transform`; one non-pass-through step anywhere breaks it), and only the observations that pin the column with `=` / `IN` or match its shape with `LIKE` / `RLIKE` travel. `CASE WHEN pay_status = 'PAID' THEN 'Y' ELSE 'N' END` reads `pay_status`, but `'PAID'` is emphatically not a value of `paid_flag` |
| Matching by target table + column name | The `case_then` / `union_constant` / `constant_projection` observations match by **target table (normalized by dotted suffix) and column name**, which is how a CASE's enum reaches the same-named target field. Matching by column name alone published every label any task ever wrote into a `status` as a value of every other `status`, and `mart.orders.status` says nothing about `mart.tickets.status`. An observation that stayed on a scope and never reached a named target column (a CASE inside a CTE) belongs to no table and keeps speaking to the same-named field of its own statement only |
| Type guard | A target column declared numeric (`decimal` / `int` / `bigint` / `double` …) or temporal (`date` / `timestamp`) admits same-typed literals only: a quoted `'Y'` never lands on an amount column, while a quoted `'0'` / `'2026-01-01'` still counts |
| `closed_set` | `true` means this value belongs to a set the SQL proved closed; `null` means **not proven closed**, never "proven open". The verdict is the **column's**: every value of one field is either all `true` or all `null`. Two proofs make it `true` -- the column's own last-step CASE is exhaustive (an ELSE, and every branch a constant), or a pass-through source column carries a closed `IN` list |
| `sql_literal` | The literal the author wrote. The `- 取值：` line of `semantic.md` shows it, while `value_domain[].value` and the overrides keys use the unquoted form |
| `meaning.status` | `confirmed` (human) or `candidate` (a literal comment hit) |
| `summary` suffix | Only a **confirmed** meaning is appended to the sentence (`；取值：'PAID'（已支付）`, at most 3): a candidate is "some comment happens to contain this value", and putting it into the line a reader stops at would read as a definition |
| `confidence.metadata_coverage.glossary` | `{values_total, confirmed, candidate, rule_values_total, rule_values_confirmed, field_values_total, field_values_confirmed, enumerable_total, enumerable_confirmed}`; absent when the statement has no value observation at all. `values_total` is the deduped **union of field values and rule-referenced values**, keyed by `(column name, value, kind)` — a code pinned by a `WHERE` and carried unchanged into the output column of the same name is **one** question to answer, not two; `confirmed` / `candidate` count over the same union. `enumerable_total` narrows that union to the **codes somebody can be asked to name**, and it is the denominator the A2 coverage ratio is taken over (`enumerable_confirmed / enumerable_total`): a physical column's literal, observed in a `filter_eq` / `filter_in` / `case_then` / `union_constant` / `constant_projection` context, not shaped like a date, and — for a bare number — written as an `IN` member, a CASE label or a projected constant rather than only pinned by `=`. A batch date and a `= 0` guard are observed values that no owner will ever confirm, and counting them made A2 read as permanent failure |

Section 5 of `semantic.md` gains one `- 取值：` line per field subsection: a confirmed
meaning is written plainly, a candidate is prefixed `? `, and neither gives 「待确认」.
When every **enumerated** value in the column is closed, the line adds
「（该列取值已被 SQL 证明封闭）」 -- and because `closed_set` is the column's verdict, one
column can no longer hold some closed values beside some unproven ones.
The trailing `SQL事实` tag vouches for the values only --
a meaning is not a SQL fact, so its three-state marker is written inside the value.

WI-2.4b adds two bounds to that line:

- at most 12 enumerated values; past that it writes
  「等 N 个，完整见 semantic.json value_domain」 -- the line is a summary, `semantic.json`
  is the record;
- a `pattern` is never listed beside the enumerated values. It trails the line under its
  own 「匹配模式：…」 label and carries no 「待确认」 marker, because a match shape is not a
  code waiting for somebody to define it.

### The rule and term layers: `rules[].value_meanings` and `term_meaning` (WI-2.12)

A warehouse keeps most of its business codes off the output columns: in
`WHERE queue_code IN ('01','07')`, in a join's extra condition, in a CASE **condition**.
A `value_domain` hangs off an output column, so a corpus could confirm all seventeen codes
and a task's document would still explain four fields — the answer never reached the line
the code is written on. With `--glossary`:

| Where it lands | What it carries |
| --- | --- |
| `rules[].value_meanings[]` | Every code this rule pins a column to, as `{column_ref, value, sql_literal, meaning}`. Only the constants of `=` / `IN` / `<>` and of a CASE **condition**; a `LIKE` / `RLIKE` shape is not a business code and a join key compares two columns. Deduped by `(column_ref, value)`, in the order the rule writes them, `meaning` null while nobody has answered — what is missing is the answer, not the question |
| How it is attributed | Exactly as the collecting side attributes it: a physical table name only when exactly one of the rule's `fields[]` carries the name (reusing the `values[]` by-column index and the dotted-suffix normalisation), a scope-level reference otherwise. A scope-level reference **only matches entries this very task observed**: `cte.flag` in another task is another CTE that happens to share a spelling |
| `inputs[].used_columns[].term_meaning` | The dictionary's **human-confirmed** meaning for that column NAME from `terms[]`, `{text, status}`, published beside the column's own `comment` |
| `fields[].term_meaning` | The same `{text, status}`, but only where the field's `target_comment` is **empty**: a term is not a comment, and filling that slot would publish a comment the metadata does not have |
| `confidence.confirmations.rule_values_confirmed` | How many codes the rule layer has answered, counted apart from the field layer's `values_confirmed` |

Three matching changes in `semantic.md`: a restated filter / join in section 3 ends in
「（取值：'01'＝人工队列）」 (only the answered ones, 「等 N 个，见规则表」 past three);
section 4's rule table gains a 「取值含义」 column after 「条件」 (absent as a whole when
nothing was answered); and a field subsection in section 5 gains a
`- 术语：…（人工确认）` line after `- 目标注释：`, with a matching 「术语」 column in the
「完整字段清单」.

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
