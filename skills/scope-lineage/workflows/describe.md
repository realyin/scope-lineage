### "这个任务在做什么 / 生成业务画像" — describe

```bash
scope-lineage describe --lineage <artifacts-dir>   # writes semantic.json + semantic.md next to each lineage.json
```

Produces a deterministic **semantic skeleton** of the task: target table and partition,
input tables with their column comments, output shape and grain, the stage-by-stage
processing chain, a flat rule list, and per-field semantics. `--out <dir>` mirrors the
tree elsewhere, same as `render`. When a whole corpus is available, run
`scope-lineage tables --lineage <artifacts-dir> --out <dir>` first and pass
`describe --tables <dir>/tables.json`: each input table then carries its upstream
producer's own grain and keys under `inputs[].card`, and the target table lists who reads
it under `task.downstream_consumers` — the two answers a single task cannot prove.
Run `scope-lineage glossary --lineage <artifacts-dir> --out <dir>` on the same corpus and
pass `describe --glossary <dir>/glossary.json` to fill `fields[].value_domain[]`: the
constants each column is compared against, whether the SQL proved the set closed, and the
meaning of each value when a human confirmed one in `glossary.overrides.json` or a comment
literally spells it out. **Take the "取值含义" column of a field dictionary from
`fields[].value_domain[].meaning` first** — `status: "confirmed"` is a fact, `candidate`
is a lead to write with `?`, and a value with no meaning is 待确认. Never infer a code's
meaning from its spelling. A value is stored unquoted in `value` with the author's literal
in `sql_literal` (show the literal, key an override on the unquoted form), `closed_set` is
the whole column's verdict, and a column only carries values it outputs itself or inherits
from a source it passes through unchanged — a CASE condition's constant belongs to the
column being tested. With `--tables`, a JOIN onto a physical table whose card proves the ON
clause's columns unique is re-decided `safe` (`basis: "table_card"`), and the statement's
keys and `key_confidence` are recomputed with it.

Read `semantic.md` — not lineage.json — to answer "what does this task do", "what does
field X mean", "what is one row of the output table". It is written to be read whole;
lineage.json is not. Pull `semantic.json` by path (`output_shape`, `stages`, `rules`,
`fields`, `confidence`) when you need the structured form, and fall back to
`scripts/query.py chain` for one field's full derivation.

`confidence.findings[]` carries a `severity`: `warn` is a lead somebody has to act on,
`info` is true and needs no action. A task instance covers one day, so a partition filter
naming that day is the design, not a defect — `hardcoded_date_literal`,
`partition_literal_mismatch` and `table_comment_missing` are therefore `info`, section 6
counts them in one line instead of listing them, and a profile must not turn them into
使用注意 or into questions. The day itself is published as `task.instance_dates[]` and on
section 1's 「本实例取数日」 line (worded as this instance's day, replaced on every run), and a metric's date filter reads `kind: "instance_date"`.

Every line in the skeleton carries one of three tags: `SQL事实` (verbatim from the SQL),
`元数据事实` (table/column comments and types), or `结构推断` (provable from the query
structure, with an evidence id). **`结构推断` is not a business definition.** "Groups by
`customer_id`, orders by `event_time` DESC, keeps row 1" is a structural fact; "takes the
customer's latest status" is your inference and must be labelled as such. The skeleton
deliberately contains no business entity names, no business table types (宽表/名单表/
指标表), and no "the goal of this task is…" — their absence is the design, not a gap.

#### 确认回写：让答完的问题不再被问第二遍

The open-questions list is only worth writing if the answers come back. It is now capped
at **five items** and asks only what changes a number or a meaning, so the bulk of the
"what does this code mean" work runs through a generated form instead. Step 1 is to
generate that form; steps 2-4 collect what came back:

```bash
# 1. the fill-in form: the corpus's most-used values that nobody has explained yet
scope-lineage glossary --lineage <corpus> --out <dir> \
  --template <dir>/glossary.overrides.template.md [--template-top 20]
# the owner writes the meanings into the .md and the same-named .json

# 2-4. the answered five-item list, routed back into the same two files
python3 scripts/confirmations.py apply <task-dir>/business_profile.md \
  --by <name> [--overrides <dir>/glossary.overrides.json] [--patch <dir>/metadata-patch.json]
scope-lineage glossary --lineage <corpus> --out <dir> --overrides <dir>/glossary.overrides.json
scope-lineage describe --lineage <corpus> --glossary <dir>/glossary.json \
  --metadata-patch <dir>/metadata-patch.json
```

`--template` writes two files at one path — the markdown a person fills in and the
same-named `.json` that `--overrides` reads back. It asks the columns that carry evidence
first, then ranks by how much of the corpus rests on the column, and it leaves out what
nobody can answer or nobody needs to: match patterns, day literals, bare numbers with no
enumerated context, and anything already confirmed. An entry left blank comes back as
`blank` in the run summary and is **not** written in as a confirmed empty meaning.

Each row's 候选来源 column says which evidence that value has — `comment_enum`,
`comment_mention`, `case_label`, `case_label(桶 N)`, `same_name_confirmed` or `—`. Three of
them are evidence an Agent may answer a value **from** instead of asking a person
(`comment_enum`, a 1:1 `case_label`, `same_name_confirmed`); a `comment_mention` is a
sentence that merely says the value and a `case_label(桶 N)` is the bucket N values share,
and both are leads for a human rather than answers. Follow
`references/glossary-review-prompt.md` for that pass: it writes the evidence answers into
`glossary.overrides.json` itself, each with a mandatory `basis` and
`confirmed_by: "agent:<name>"`, never overwriting a human confirmation, and turns at most
8 of what is left into an open-questions file. A confirmation signed `agent:` with no
`basis` is refused and reported under `overrides_applied.rejected`
(`reason: "missing_basis"`); a misspelled slot lands in `overrides_applied.ignored_fields`.
Check both lists every round, next to `unmatched`.

The script routes each answer by its own 回写目标 line — `术语` / `值域` into the glossary
overrides, `字段注释` / `表注释` into a `metadata-patch/1` file — and never overwrites an
entry somebody already confirmed (`--dry-run` prints both documents instead of writing
them). The next profile then reads `value_domain[].meaning.status: "confirmed"`,
`fields[].target_comment_source: "patch"` and `inputs[].comment_source: "patch"`, must
**not** ask those questions again, and lists them under appendix A (已确认项) instead — so
each round the 待确认清单 gets shorter. `parse --metadata-patch` applies the same file when a
corpus is re-parsed; both paths write the same document.

When the user wants a business profile, generate **two files** from the skeleton following
`references/semantic-profile-prompt.md`. `business_profile.md` is what the reader gets:
**three pieces plus a short appendix** — a **task semantic card** (≤ 1 page, business
language, no source tags), a **field dictionary** (every output column, with a 7-row metric
spec card per measure), an **open-questions list** (≤ 5 items a business owner can answer in
five minutes, restricted to column-position mismatches, comment-versus-derivation conflicts,
unproven keys under a fan-out risk, and misnamed fields), and appendices **A 已确认项 /
B 备查项与待填取值 / C 风险边界**, which together must stay **≤ 1/3 of the body's character
count**. `business_profile.check.md`, written next to it, is the writer's QA record — input
file verification, the source-tag evidence table, the inferred-items list, the
self-consistency pass and the 14-item self-check — a required quality gate that keeps every
item but no longer sits in the reader's document. Fill
`references/business-profile-template.md` and `references/business-profile-check-template.md`.
For a whole corpus, loop over the task directories yourself — there is no batch mode in the
CLI.
