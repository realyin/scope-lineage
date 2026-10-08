English | [中文](../zh-CN/table-semantics.md)

# Table semantics (`table-semantics/1`): packet, validate, confirm, render

Table semantics answers, for one target table and in words a business reader uses: what
the table is, what one row is, how it is refreshed and how to read a day or a range, which
records it keeps, where its data comes from and who uses it, what each column means and
how it is computed, which code values a column holds, and what to watch out for.

The document is written by a model and held to the facts by machine. Core does the
deterministic work and never calls a model:

- `scope-lineage semantic packet` gathers every fact a writer needs about one table into a
  **material packet** — the table's metadata, each producing task with its SQL, the input
  tables, and the lineage facts the semantic profile already derives;
- `scope-lineage semantic validate` checks a written `table-semantics/1` document against
  its JSON Schema and against the packet (thirteen cross checks), and lists per item what to
  rewrite;
- `scope-lineage semantic confirm` writes a person's answers back into the documents;
- `scope-lineage semantic render` renders the documents as one page per table and an
  index, linked both ways with the ontology catalog's concept pages;
- `scope-lineage semantic status` reads a run directory back, reports each table's stage
  and batches the tables the next step still needs; `scope-lineage semantic fixed` records
  that a revision finished.

Writing the document (the prompt, the rewrite loop) belongs to the agent skill: the prompt
is `skills/scope-lineage/references/table-semantics-prompt.md`, and the skill's `SKILL.md`
gives the order of the steps.

A hand-written example document for a demo table lives in
[`examples/table-semantics/`](../../examples/table-semantics/), beside a confirmations file
for it; both are synthetic, like the demo corpus they describe.

## Where it sits

| Step | Who | Command | Output |
| --- | --- | --- | --- |
| 1. packet | machine | `semantic packet` | `<out>/<db.table>/packet.md` and `packet.json` |
| 2. write | model, through the agent skill | — | one `table-semantics/1` JSON per table |
| 3. validate | machine | `semantic validate` | a text summary, or a `--json` report whose failure list is the rewrite prompt |
| 4. render | machine | `semantic render` | one page per table, `<db.table>.md`, and `index.md` |
| 5. confirm | a person answers, the machine applies | `semantic confirm` | the documents with `confirmed` marks |
| throughout | machine | `semantic status` | each table's stage and flags; `--next` batches the next step |

## Five minutes on the demo

Every input is synthetic and ships with the repository:

```bash
scope-lineage parse --input-dir examples/catalog-demo-corpus/tasks \
  --schema examples/catalog-demo-corpus/schema_info.json --out out/lineage
scope-lineage semantic packet --lineage out/lineage \
  --tasks examples/catalog-demo-corpus/tasks \
  --schema examples/catalog-demo-corpus/schema_info.json --out out/packets
scope-lineage semantic validate examples/table-semantics --packets out/packets
scope-lineage semantic confirm examples/table-semantics \
  --confirmations examples/table-semantics/confirmations.json --out out/confirmed
scope-lineage semantic validate out/confirmed --packets out/packets --json > out/validation.json
scope-lineage catalog build examples/catalog-demo --out out/catalog
scope-lineage semantic render out/confirmed --out out/pages/semantics \
  --validation out/validation.json --ontology out/catalog/ontology.json
scope-lineage catalog render out/catalog/ontology.json --out out/pages \
  --semantics out/pages/semantics
```

`validate` prints one line per document (`demo_dwd.dwd_party_customer_info_df: 52/52
checks passed (100.0%)`) and a total. The example's `packet_digest` pins the packet as the
installed SQLGlot renders it; with another SQLGlot version the digest check may report the
example as stale while every other check still passes.

## `semantic packet`

### Inputs

| Option | Required | What it is |
| --- | --- | --- |
| `--lineage` | yes | one `lineage.json`, or a tree of them — the same walk `describe` uses, with each document's `diagnostics.json` |
| `--tasks` | yes | the task JSON directory the lineage was parsed from; read with `parse`'s own task reader, for each task's SQL |
| `--schema` / `--schema-fallback` | no | schema metadata, the same options and loaders as `parse`; without them the columns and comments come from the lineage |
| `--tables` | no | a `tables.json` from `scope-lineage tables`; without it the table cards are built from `--lineage` first |
| `--only` | no | one or more target tables (`db.table`; a catalog prefix is ignored); an unknown name exits 1 |
| `--glossary` | no | a `glossary.json` from `scope-lineage glossary`; every target and input column then lists the value meanings the dictionary confirms (`confirmed_values`), see "Confirmed facts" |
| `--metadata-patch` | no | a reviewed `metadata-patch/1` file, repeatable; laid over the lineage and `--schema` comments in memory, each patched comment marked `comment_source: "patch"`; a file that cannot be read exits 2 |
| `--out` | yes | the output directory: one `<db.table>/` per target table |

A packet is written for every table a task finally writes (session views and temporary
tables are not target tables). A task whose JSON is missing from `--tasks` is packed
without SQL; the summary line counts them as `tasks_without_sql`.

With `--only` the corpus is not profiled as a whole. A document that writes or reads a
table names it, so only the lineage documents whose bytes contain a requested table's name
are parsed: with `--tables`, just the ones that write it; without, those plus the
producers of its input tables, from which the cards are built. The packet is the same as a
full run's; the summary line's task count says how many documents were read.

### What a packet holds

`packet.json` (`table-semantics-packet/1`) and `packet.md` hold the same facts; the
validator reads the JSON, a model reads the markdown.

| `packet.md` section | `packet.json` key | Content |
| --- | --- | --- |
| 1. 目标表 | `target` | table comment, layer, domain, where the metadata came from (`schema` / `lineage` / `fields`), every column in table order with type, comment and whether it is a partition column |
| 2. 生产任务 | `tasks[]` | per producing task: id, schedule, cycle, description, declared upstream and downstream tasks, the script's header comments, the statements that write this table, and the SQL |
| 3. 输入表 | `inputs[]` | per input table: comment, layer, roles in this table's statements, the tasks that produce it, every column with how it is used, and the time facts below |
| 4. 血缘事实 | `lineage` | `columns[]` (per target column: each producing statement's transform, physical source columns, expression and derivation steps), `rules[]` (filters, joins, dedups, windows, unions and CASE branches, numbered `p1…`), `keys[]` (shape, grain basis, candidate keys, `key_confidence`, `proven`), `partition[]`, `upstream_tables`, `upstream_tasks`, `downstream[]` (consumer task, the tables it writes, whether lineage or task registration says so) |
| 5. 目标列顺序 | — | the column order the document must follow |

The lineage facts are the semantic profile's (`describe`'s builder), read with the table
cards so downstream consumers and joins another task proved unique are known. The profile
is an input here, not a deliverable.

The layout of `packet.md` changes the markdown only, never `packet.json`, so `packet_digest`
does not move and no written document goes stale over it:

- The 4.2 rules table has a 位置 column after 类型: `stmt:00N / <scope>` (the task name first
  when the packet has several tasks). Rows with the same expression are told apart by it --
  which statement, which subquery.
- Section 3's 分区读取 and 日期列上的过滤 list each condition once, followed by the rules it
  comes from, e.g. `（p2、p5）`.
- Section 3's 分区读取, when a condition fixes some partition column and not another, goes on
  with 「；未限定的分区列：`src`（注释：…）」, quoting the comment as written and drawing no
  conclusion -- whether reading every value multiplies rows depends on the data. A read with
  no partition condition at all says nothing more; 全量快照 already covers it.
- Section 3's 本表用到 cell of an input column read in (most often through `select *`) but
  used by no output, condition or key says 「读入未用（select * 等）」.
- A 4.1 步骤 cell whose step chain is longer than 300 characters first says 「计算步骤：…（略去
  N 个直接投影 / 合并步骤；完整步骤见同目录 packet.json 该列 producers[].steps）」: the chain
  without its two pass-through kinds, direct projections and merges, each step text once
  (with 「M 个重复步骤」 noted). Only when those computing steps are still longer than 300
  characters, or there are none, does it say 「末层：<last step>（共 N 步；…）」, cutting a last
  step that is itself too long. So every row is bounded; the author's comments and the
  「头注释：… 才加入」 note stay.
- When 4.1 or 4.2 holds a one-argument `FROM_UNIXTIME` / `UNIX_TIMESTAMP`, a line under the
  section heading says its format is the default `'yyyy-MM-dd HH:mm:ss'`. SQLGlot leaves out a
  format argument equal to the default, so a call whose SQL wrote that format keeps one
  argument in the lineage; the meaning is the same.
- 4.2's 说明 gives, right after the rule's text, how far each date literal of the task in the
  rule's expression sits from the expected run date, e.g. 「日期字面量 '20250115'（期望日期
  −1 天）」 -- the same reading as 2.x's `date_literals`: an offset, never which literal is the
  batch date.

Each input carries the facts check 9 needs: `partition_read` (`equality` for a single
partition; `multi_equality` when every partition filter is an equality or an `IN` list of
literals and they come to more than one value, i.e. several fixed partitions; `range`
otherwise; `none` when unfiltered) with the `partition_filters` behind
it, `date_filters` (non-partition filters on a date- or time-like column), and
`name_convention` (`full` for a `_df` / `_da` style name, `incremental` for `_di` / `_hi`,
`unknown` otherwise) — a naming convention, published so a reader sees what the check
assumed. `full_snapshot` is `equality` read of a `full` name; when it is false, `packet.md`
says why: `不适用（非分区表）` (not partitioned), `未证明（未见分区条件）` (no partition
condition seen), `否（读 N 个固定分区 …）` (several fixed partitions; for a `full` name it adds
that each partition is a snapshot holding one row per record), `否（读多个分区 / 范围）`
(several partitions or a range) or `未证明（表名约定 …）` (the name convention is not `full`).

A partition condition written in a JOIN's ON (`LEFT JOIN t c ON a.k = c.k AND c.dt = '…'`)
reads partitions as a WHERE does when it compares a column of the right side, qualified by
its alias, with a constant; the right side is one physical table; the column is a
partition column (decided as in the table below); and the join does not keep every right
row (a RIGHT or FULL OUTER join's ON never removes a right row, so it does not count).
Such a join rule carries `partition_reads: [{table, expression, basis}]` (only when there
is one), and `packet.md`'s rules table shows 是（右表 …） in its 分区过滤 column.

Each `date_filters` entry carries the `statement_id` it sits in and its `shape`: `X <= C`
(or `<`) paired with `Y > C` (or `>=`) on another column, same statement, same constant,
is `as_of` (a zipper table read as of one day); an upper bound alone is `upper_bound`;
`IS [NOT] NULL` is `null_check`; anything else (`=`, `>=`, `>`, BETWEEN, a shape not
recognised) is `window`. Only a `window` selects rows by business date.

Whether a filter reads partitions is decided per conjunct, because the lineage's own flag
is a name rule over a whole `WHERE` clause (`dt = x AND status = 0` marks neither half).
Each filter rule carries `partition_filter` and the `partition_basis` it rests on:

| `partition_basis` | When |
| --- | --- |
| `metadata` | every column of the filter has a partition fact in the schema metadata (`isPartition` on the column, or the DDL's `PARTITIONED BY`); a column flagged there is a partition column whatever its name |
| `partition_name` | the metadata marks the table partitioned (`is_partition`) without naming the column, and the filter compares a `dt` / `ds` / `pt` / `p_date` column with a constant or a `${...}` parameter |
| `lineage` | neither: the lineage's flag stands |

The same facts mark `partition` on the target's and the inputs' columns.

Every rule row is made first and numbered once; every note naming a `pN` comes after, and
no note adds or drops a rule. A window that does not dedup (a ranking never filtered to
`= 1`, a LEAD) is a row too, `kind` `window`, its 说明 the profile's own words (「仅组内排名，
未见 = 1 过滤」). A filter inside a LEFT JOIN's right side (the right scope and every scope
it reads), a partition filter included, carries `right_of: [p…]`, those joins: it drops no
target row, it decides which right rows take part in the match -- a partition filter, which
partitions the right side reads. A scope that also feeds the driving rows (a
CTE read as `FROM c a` and as `LEFT JOIN c a1`) does not count; nor does the right side of a
join whose own scope's WHERE filters on it (an anti-join's `WHERE r.k IS NULL`), where the
right side decides which target rows survive. `right_side_kind`, on a non-partition filter
only, names two structural kinds:
`rank_first` (the filter keeps a ranking's `= 1`, decided by the profile's R6) and `values`
(the filter's scope reads an inline VALUES list down a single-input chain); whether the
rule's `tables` are empty is not asked. The 说明 column joins its parts in one order: the
rule's text → date offsets → where it sits (`right_of`, 「在 pN 右侧：不丢目标行，决定右侧哪些行
参与匹配」, for a partition filter 「……决定右侧读哪些分区」) → notes → 相邻的注释掉的 SQL（不生效） → 未被消费 → findings.

Three more facts serve the meaning checks (10–13). Each join rule carries `right` (the
right side: a `db.table`, or the profile's scope id such as `subq:p`), `right_aliases`
(the aliases the ON clause and the scope give it), `right_tables` (the physical tables
behind it) and `fan_out`, the profile's verdict on whether the right side is unique on the
join keys (`{status, reason, path}`, `status` one of `safe` / `risk` / `unknown`; `null`
for a join on no path the profile walked); `packet.md` shows it in the rules table's
行数放大 column. A verdict off the grain path (`path` `argument` / `anchor`) carries
`verdict_aggregate`, the aggregating scope it sits under, and the cell reads 「status（位于聚合 X
之下：不复制输出行，可能让聚合值重复计入）：reason」; a `risk` / `unknown` verdict whose right side
holds a ranking nobody filters lists those `window` rows in `unfiltered_ranking: [p…]`
(「右侧的 pN 算了排名但没有 = 1 过滤，未去重」). A join whose `fan_out` is `null` is never written as off the output path:
when it sits inside the right side of joins that have a verdict (in the right scope or any
scope it reads), `inside: [p…]` lists every such join (「在 pN 右侧内部；行数影响已计入这些关联的判定」);
failing that, when it sits below an aggregating scope, `below_aggregate: <scope>` names it
(「不复制输出行，可能放大聚合值；工具未判定」); otherwise it reads 「工具未判定」. Each column producer carries `case_outputs`: for a column whose last
computing step is one CASE or IF with only string or number outputs (NULL and `''` aside), one entry per
value with the branch conditions (`when`), the source values those conditions compare with
(`source_values`, `null` when a condition is not an equality or `IN` list) and whether
the ELSE returns it (`catch_all`). When the branches return literals but the ELSE
computes its value (`CASE WHEN s = '1' THEN 'X' ELSE s END`), the CASE is read the way the
glossary reads it: string branches are listed (an open set, the ELSE supplies the rest)
and number branches, computation defaults rather than codes, are dropped; each entry then
carries `else`, `source` when the ELSE is a column the branch conditions compare (as is,
`CAST`, or `COALESCE` with a literal) and `computed` for anything else (a date stamped
on new rows, say). A CASE with a
computing branch still has no `case_outputs`. Each task carries `header_facts`, the lifecycle
(`生命周期` / `保留` / `lifecycle` followed by a number of days or `永久`) and data volume
(`数据规模` / `数据量` followed by a number) its header comment states, read from the
published header and from the comment lines that open the script; `packet.md` prints them
as 头注释. A task writing several tables has one header: when its 库表名 / 表名 line names
**another** table the same task writes, `header_facts` gains `about: <that table>` and
check 13 no longer asks this table's document for those facts; a header naming a table
the task does not write (an old name, say) stays with this table. An
`alter table … add columns (…)` in the header naming this table, or the table of the
header's 库表名 line, is recorded as `header_facts.added_columns: [{date?, table, columns}]`
(only columns the target has; `date` the date stamp before the ALTER on its line or on the
line above); `packet.md` prints 头注释加列记录 under 2.x, and 4.1 says on each such column
「头注释：… 才加入，此前写入的行该列可能为空」.

The remaining facts are for the writer only; no check reads them, and each appears only
when it has content:

| Where | Key | Content |
| --- | --- | --- |
| `tasks[]` | `expect_date` | the expected run date from the task metadata |
| `tasks[]` | `date_literals` | every whole-date string literal (`'YYYYMMDD'` / `'YYYY-MM-DD'`) in the SQL outside comments: `{literal, count, days_from_expect_date}`. A corpus exported from run instances carries the batch-date parameter as a literal; the offset is given, no conclusion that it is a parameter is drawn |
| `tasks[]` | `upstream_unmatched` | the registered upstream tasks whose name matches no table the task reads over all its statements; a task named `tbl`, `db_tbl` or ending in `_db_tbl` matches. A name heuristic: it says "does not match", not "not read" |
| `inputs[]` | `producer_header` | what the SQL header of each corpus task producing the input states: primary key, storage design, partition design, lifecycle, volume, as `[{task, primary_key?, storage?, partition_design?, lifecycle?, volume?}]`. The author's claim, not a SQL fact; absent for an input the target writes itself and when the header describes another table of that task |
| `lineage.partition[]` | `select_values` | for a dynamic partition column (`PARTITION (dt)`) the SELECT fills with constants only (`'${bizdate}' AS dt`, one per UNION branch), those constants as `{column: [literal…]}`. A MERGE has no PARTITION clause: `columns` are the target table's partition columns from the metadata, `mode` is `merge_row_values` (each written row lands in the partition its values name), and the constants are read from the not matched (INSERT) branch only |
| `lineage.partition[]` | `merge_columns` | with `merge_row_values` only: `{partition column: {update, key, pinned?}}`. `update` is `none` (no UPDATE clause), `keeps` (the column is in `insert_only_columns`, or missing from an UPDATE-only MERGE's `update_columns`: an updated row stays in its partition) or `writes` (the UPDATE writes it too: a row whose value changes moves to another partition); `key` says it is a merge key's target column (ON keeps it equal on a matched row); `pinned` is the value every matched WHEN condition pins it to (the profile's `matched_target_pins`): only that partition's rows are updated, and a same-key row elsewhere is neither updated nor inserted again. The 4.3 「分区写入」 line of `packet.md` says these per column, and says for a pinned one that no old partition is rewritten |
| `inputs[]` | `producer_columns` | how each corpus task producing the input writes the columns this table joins, filters or windows on: its table card's `produced_by[].fields` summaries, `[{task, statement_id, column, summary}]`; another task's SQL, summarised, never this task's. Absent for an input the target writes itself |
| `lineage.downstream[]` | `columns` | the columns of this table the downstream task joins and filters on (its table card's `consumed_by[].columns`): `{join_key: [...], filter: [...]}`; `packet.md`'s 4.4 gains a column 按哪些列读（关联 / 过滤） |
| `lineage.columns[].producers[]` | `literal_outputs` | the values the column's SQL writes as literals (SQL spelling: `''`, `'web'`, `0`, `NULL`): when only pass-throughs follow the last computing step of the chain, a constant, the last argument of a COALESCE / NVL, the literal outputs of a CASE / IF; each UNION branch by its own last computing step. A literal only in a condition is none, and a NULL a missed LEFT JOIN brings is `nullable_by_join`'s. `constant_only: true` says every branch ends in a constant, so these are all the column holds |

A join rule whose `tables` would be empty (the ON's only equality has several columns on a
side, `IF(COALESCE(a.x, '') = '', a.y, a.x) = d.k`, which the lineage does not pair as a
key) falls back to the tables its ON conditions touch plus the right side. A transitional
fallback: once the lineage pairs such an equality, it no longer fires.

The packet also copies these facts of the semantic profile, each likewise only when it has
content:

| Where | Key | Content |
| --- | --- | --- |
| `lineage.columns[].producers[]` | `branches` | MERGE branches of one statement writing one column with the same content (the expressions differing only in quotes, whitespace or case) are one producer; this lists the profile's names of the branches folded, and `packet.md` writes 「（2 支：merge:matched 分支 0、…）」. Branches writing different values stay one row each |
| `lineage.columns[].producers[]` | `computed_by` | for a column whose last step is `DIRECT`, the kinds of computation its chain makes besides passing values on, in order and without repeats (an aggregate names its functions, `aggregate(SUM)`); `packet.md`'s 加工 reads 「DIRECT（末层）；链上：…」 |
| `lineage.columns[].producers[]` | `sql_alias` | in a positional write (by DDL or metadata column order) whose SQL alias differs from the target column, the alias the SQL wrote; `packet.md` writes 「`col`（SQL 别名 `x`，按位置写入）」 |
| `lineage.columns[].producers[]` | `lookup_keys` | for a value read off a constant row set (an inline VALUES list, a constant column …), the physical join keys that choose its row; not a source of the value |
| `lineage.columns[].producers[]`, `lineage.rules[]` | `sql_comments` | the SQL comments the author wrote on the expression (the expression itself carries none) |
| `lineage.rules[]` | `commented_out_sql` | SQL switched off beside the condition (a filter somebody removed, say), kept apart from the notes; `packet.md`'s 说明 says 「相邻的注释掉的 SQL（不生效）：…」 |
| `lineage.columns[].producers[]` | `steps` | a step the profile's vocabulary cannot word (a UDF, `MD5(…)`) reads 「表达式 …」 instead of `None` |
| `lineage.rules[]` | `consumed` | only `false`: a CASE / IF whose output provably nobody reads; `packet.md`'s 说明 says 「未被消费」 |
| `lineage.keys[]` | `grain_columns` | the target column each grain key lands on, the profile's `grain_key_columns`: `[{logical, column?, via, pinned?}]`, `via` being `exposed` (passed through to a target column), `derived` (through a single-source expression), `merge_on` (through a MERGE's ON equality) or `unexposed` (not written to the target). `grain_keys` are the logical keys' names in the scope that decides the grain; this key is present only when some key does not land on a target column of its own name, so its absence means every grain key is its target column. The 4.3 cell 「粒度键（目标列）」 of `packet.md` names the target columns from it, marking a derived key, one tied by ON and one not written |
| `lineage.keys[]` | `merge` | a MERGE statement's profile `output_shape.merge`: the merge key `merge_keys`, other ON conditions, each WHEN clause, the USING side's grain, and how its dedup compares with the merge key, `coverage` (`covered` / `dedup_wider` / `no_dedup` / `unknown`, with `extra_keys` for `dedup_wider`); `joins_after_dedup` as rule ids (each of `union_branches[]` too); besides, `matched_target_pins`, `using_writer_keys`, `table_key`, `insert_only_columns`, `update_columns`, `update_nullable_by_join`, `update_nullable_by_join_branches`, `update_filled_on_miss` and `union_branches` (see [semantic-doc.md](semantic-doc.md)). `packet.md` adds under 4.3: the merge key, the WHEN clauses (a row failing a clause's condition is neither updated nor inserted), the dedup against the merge key (branch by branch for a UNION USING side; an undecided grain reads 「USING 粒度未判定」, never "no dedup"; where one merge key may have several USING rows -- `no_dedup`, `dedup_wider`, between UNION branches -- what the statement's own WHEN clauses then do: a matched UPDATE / DELETE meets several USING rows for one target row, a not matched INSERT inserts a missing key more than once; no engine is named), a line for a USING side read from a table whose writer keys its batch on columns the merge key lacks (`using_writer_keys`), the inferred table key (not proven; an UPDATE-only MERGE 「本语句不决定目标表的行粒度」), the columns a matched UPDATE leaves alone, changes or may overwrite with NULL (with the UNION branches when only some branches may), and the columns a miss overwrites with a filled-in literal (`update_filled_on_miss`, with branches and value). `proven` is always `false` on a MERGE row: the profile proves the written batch, not the table |
| `lineage` | `findings` | the profile's governance findings `alias_position_mismatch`, `duplicate_alias`, `empty_string_on_non_string`, `numeric_compare_on_string`, `literal_outside_comment_codes` and `window_partition_narrower` (hung on its window's `window` row by logic block), then two the packet finds itself: `marker_column_unused` (an input has a marker column that no condition and no output of the task reads; generic names only: a logical-delete flag in the `is_deleted` style, a cancel flag in the `is_cancel` / `is_void` / `is_invalid` style, and a change-type column in the `record_type` / `op_type` / `change_type` style -- the last only when its comment names at least two data-manipulation verbs (INSERT, UPSERT, UPDATE, DELETE, 新增, 插入, 更新, 修改, 删除), one of them a delete, which keeps out a business "operation type"; one lead per task, a sentence per kind) and `declared_key_not_used` (an input column's comment declares a unique key as a `$` template of the table's columns, and the task deduplicates or merges that table by part of it; not said again for a statement whose MERGE already reports `dedup_wider`). Each `{kind, severity, task, statement_id, text, rules?}`, `rules` naming the rules it is about; `packet.md` lists them after 4.3, and in the 说明 of each rule named |
| `target.columns[]`, `inputs[].columns[]` | `comment_markers` | the full-width markers of the comment (`【key:value】`, the key starting with an ASCII letter), split out as `[{key, value?}]`. Their meaning is the data owner's and the tool gives none; the comment is unchanged |
| top level | `comment_marker_keys` | how often each marker key occurs, with one example column; `packet.md` lists them in its opening lines, saying a marker is no business fact until its meaning is recorded |
| `target.columns[]`, `inputs[].columns[]` | `comment_refs` | the comment's `[db.table.col]` / `[db.table]` / `[table.col]` references as `{ref, status, near?}`, `status` being `in_run` (a corpus task reads or writes the table, by the table cards), `metadata_only` (only the metadata knows it) or `unknown`; an `unknown` one may list in `near` the run's tables whose names, past their first layer prefix, extend one another -- a lead, not proven the same table |

With `--only`, a `--schema` directory is read for the packet's tables only; another table a
comment references is read on demand, so the references read as they do in a full run.

### Confirmed facts

What the owner has already answered, a writer should neither guess again nor ask again.
Two kinds of answer reach the packet when their option is given:

- **Confirmed comments** (`--metadata-patch`). The patch is applied to every lineage
  document first — the same function `describe --metadata-patch` uses, the lineage on disk
  is never rewritten — and then laid over the `--schema` metadata: in a packet the metadata
  wins over the lineage, so patching the lineage alone would let the very comment the patch
  corrects win. A table's patched facts are merged into its metadata, a column's comment
  is replaced by name (ignoring case); a table `--schema` does not know keeps the
  (already patched) lineage comments. Where the comment the packet shows is the patch's
  answer, that table (`target`, `inputs[]`) or column carries `"comment_source": "patch"`,
  right behind `comment`; a patch that gave only a description while the comment is still
  the metadata's table name marks nothing. The summary line reports `patch_unmatched` as
  `describe` does, naming each patch key no table or column answered to; with `--only`
  only the documents read count.
- **Confirmed value meanings** (`--glossary`). Every dictionary `values[]` entry whose
  `meaning` is filled (written by `glossary --overrides`) lands on the target and input
  columns its `column_ref` names — the table by dotted suffix, so a catalog prefix does not
  matter, the column by name, ignoring case — as
  `"confirmed_values": [{"value", "meaning"}]` (who confirmed it, and when, stays in the
  dictionary), in dictionary order, the first entry of a value winning; `logical: true`
  entries (a scope's columns) and entries without a `meaning` are skipped.

`packet.md` appends 「（已确认，元数据补丁）」 to a patched comment, gives a column table
an extra 已确认码值 column (`0=否；1=是`) when one of its columns has confirmed values, and
opens with a line telling the writer to use them as written, with `sources` `confirmed`,
never `unconfirmed`, never as a question. Checks 3 and 12 read the same facts. Both keys
appear only when there is something to say: without the two options a packet, its
`packet_digest` included, is byte for byte what it was.

### Owners and emails

A packet is handed to a model, so it never carries a person: every owner key
(`owner`, `owner_email`, `target_table_owner`, …) is dropped wherever it appears, every
comment is masked the way `parse` masks comments by default (email, phone, ID number), the
SQL's comments are masked the same way, and a last pass masks any email address left
anywhere in the packet, SQL included. `confirmed_values[]` carries the value and its
meaning only, never the dictionary's confirmer.

### The digest

`packet_digest` is sixteen hex digits over every fact in the packet. The same inputs give
the same digest; any change to the metadata, the SQL or a lineage fact changes it. A
document copies the digest of the packet it was written from, and check 8 compares it with
the current packet.

## The `table-semantics/1` format

One JSON document per target table. The schema is shipped as
`scope_lineage/schemas/table-semantics.schema.json` and rejects unknown keys.

```json
{
  "doc_format": "table-semantics/1",
  "table": "demo_dwd.dwd_party_customer_info_df",
  "packet_digest": "ec811d2e60ec6088",
  "generator": {"prompt": "table-semantics-prompt@0", "model": "hand-written example"},
  "summary": {"what": "...", "row": {}, "refresh": {}, "scope": [], "upstream": [],
              "downstream": [], "good_for": [], "not_for": [], "watch": [], "questions": []},
  "columns": [],
  "steps": ["..."],
  "rules": [],
  "task": {"name": "dwd_party_customer_info_daily", "purpose": "...", "outputs": ["demo_dwd.dwd_party_customer_info_df"]},
  "concept": {"concept": "concept:customer", "representation_kind": "core"}
}
```

| Key | Content |
| --- | --- |
| `table` | `db.table`, no catalog prefix |
| `packet_digest` | copied from the packet |
| `generator` | the prompt (and optionally the model) that wrote it |
| `summary` | the one-page summary, all ten keys required (arrays may be empty) |
| `columns[]` | every target column, in table order |
| `steps[]` | the processing in one to seven sentences |
| `rules[]` | filters, joins, dedups, derivations and unions: business wording plus the SQL quoted as written |
| `task` or `tasks[]` | the producing task(s): `name`, `purpose`, `outputs`, optionally `cycle`, `upstream_tasks`, `downstream_tasks` — exactly one of the two keys |
| `concept` | optional link to the ontology catalog: `concept:<id>` and the table's representation kind |
| `confirmed[]` | written by `semantic confirm`: every applied confirmation (`target`, `by`, `date`) |

### Sources and confidence

Every item that states something carries `sources`, drawn from `comment`, `sql`,
`sql_comment`, `metadata`, `task`, `inferred` and `confirmed`; it may carry `confidence`
(`high` / `medium` / `low`) and a `watch` sentence for a conflict or a risk. The sourced
items are `summary.row`, `summary.refresh`, each `summary.scope[]` and `summary.upstream[]`,
each column, each code value and each rule. A packet's `confirmed_values` and its comments
marked `comment_source: "patch"` are facts the owner confirmed; an item written from them
is sourced `confirmed`.

### The one-page summary

| Key | Content |
| --- | --- |
| `what` | one sentence: what the table is |
| `row` | what one row is: `text`, `grain_columns`, `grain_source` (`declared` / `inferred` / `proven`), `unique` (`yes` / `no` / `unknown`), `note` for the risk when it is not unique |
| `refresh` | `cycle`, `time` (`snapshot` / `incremental` / `zipper` / `unknown`) and `how_to_read`: how to take one day and how to take a range |
| `scope[]` | which records the table keeps, in business words, citing rules through `rule_refs` |
| `upstream[]` | each input table's `role` (`main` / `enrich` / `filter` / `dedup` / `union_branch` / `lookup` / `other`) and what it `provides` |
| `downstream[]` | consuming `task` and optionally the `table` it writes |
| `good_for[]` / `not_for[]` | typical uses and their limits |
| `watch[]` | conflicts, risks, deprecations and coverage gaps, each with a `kind` and optional `refs` such as `column:x` or `rule:r2` |
| `questions[]` | at most five open questions for the owner: `id` (`q1`…), `text`, `about`, `status` (`open` / `answered`), and once answered `answer`, `answered_by`, `answered_on` |

### Columns and rules

A column holds `column`, `meaning` (the business name), `category` (`identifier`,
`foreign_identifier`, `descriptive`, `state`, `measure`, `time`, `technical`),
`derivation` (in business words; `branches[]` when branches differ), `source_columns`
(`db.table.column` references the derivation reads), `code_values[]` (`value`, `meaning`,
`sources`, and `unconfirmed: true` for a guess), optionally `unit`, `null_meaning` and
`watch`, plus `sources` and `confidence`.

A rule holds `id` (`r1`…), `kind` (`filter`, `join`, `dedup`, `derive`, `union`, `other`),
`text`, `sql` (the SQL fragment as written in the script) and `sources`.

### What the schema leaves to the checks

The schema checks shape only. Two counts a model often gets wrong are deliberately left to
check 7 so they land in the rewrite list instead of failing the whole document: an empty
`sources`, and more than five questions.

## `semantic validate`

```bash
scope-lineage semantic validate <documents> --packets <packet dir> [--only <db.table> ...] [--json]
```

Every `*.json` under `<documents>` is read; the toolchain's own other documents
(`semantic-confirmations/1`, packets, reports) are skipped, anything else is checked. A
document that fails the schema is reported with its errors and not cross-checked. A valid
document is checked against `<packet dir>/<table>/packet.json`.

`--only` checks only the documents of these tables (`db.table`, a catalog prefix is ignored), spelt as `semantic packet`'s and `semantic status`'s `--only`; the report and its summary line count the chosen tables only. A file that is not readable JSON or names no `table` is passed over without an error, so writers working in parallel each check their own tables without tripping over another's half-written file. A named table with no document prints `--only: no document for …` on standard error and exits 1. Do not redirect an `--only` run into `validation.json`: it would overwrite the full report.

`--only` takes every word after it. Write the directory before it, or end the tables with `--`
(`--only <db.table> ... -- <documents>`). When the directory comes last anyway, the last word
after `--only` is taken back as the directory if it holds a `/` or names an existing directory
and at least one table stays before it; any other last word is a usage error (exit 2) that
says where to put the directory. `semantic status`, `semantic fixed` and `catalog digest`
read `--only` and their directory the same way.

The thirteen cross checks:

| # | Check | Fails when | Warns when |
| --- | --- | --- | --- |
| 1 | `coverage` | a target column is missing, a column is extra or repeated, or the order differs from the table's | — |
| 2 | `source_columns` | a source column is neither in that column's lineage nor in any input table (the column's lineage is its producers' sources plus their `lookup_keys`: for a value read off a constant row set such as an inline dictionary, the physical keys deciding which row is read) | it is only in an input table's metadata, not in the column's lineage |
| 3 | `code_values` | a code value not marked `unconfirmed` appears neither in the related comments nor in the SQL, and the dictionary does not confirm it on the column or a source column it reads (`confirmed_values`). The value must stand alone, not inside a longer word or number; only in a comment (the column's, a source column's, the SQL header's) may a value ending in a digit run straight into letters (the `2` of `1普通2VIP回访`). An empty value (`""`, or blanks) is no text to find: it passes only when a producer of the column writes `''` (`literal_outputs`: a COALESCE / NVL fallback, a constant, a CASE / IF branch), not when `''` is only compared in a condition. A column every producer of which is `constant_only` holds its constants and nothing else: each of its code values, `unconfirmed` too, must be one of them, and a column that only writes NULL has none. A packet without `literal_outputs` has no such column | — |
| 4 | `grain` | a grain column is not a target column, or `grain_source: proven` has no proven key in the packet | the claimed grain columns differ from the proven key |
| 5 | `rules` | a non-partition filter is not cited by any `rules[].sql`, a quoted `sql` is not found in the task SQL (normalized), or a `rule_refs` entry names no rule. A quote cites a filter when it, or one of its AND conjuncts (comments dropped), equals the filter in some form; a longer quote that merely contains the filter's text (a CASE branch, a MERGE condition) cites nothing. A filter with `right_of` and a `right_side_kind` of `rank_first` or `values` need not be cited; one with `right_of` alone must be, by a rule, and the message says to keep it out of `summary.scope`. The fix quotes that one condition, not the whole WHERE | the packet has no SQL to check a quote against |
| 6 | `neighbours` | an upstream table is not a lineage input, or a downstream task (or the table it is said to write) is not known | the downstream task is known but the tables it writes are not |
| 7 | `sources` | a sourced item has an empty `sources`, or there are more than five questions | — |
| 8 | `digest` | `packet_digest` differs from the packet's (stale), or there is no packet for the table | — |
| 9 | `time` | `refresh.time` is `incremental` while every input is a full snapshot read by one partition and no filter touches a business date | `refresh.time` is `snapshot` while the write filters on a business date (only date filters shaped `window` count) |
| 10 | `fan_out` | the right side of a join whose `fan_out.status` is not `safe` and whose `fan_out.path` is `grain` (or absent) is named — by table (`db.table` or bare) or alias — neither in `summary.row.note` nor in a `summary.watch` item of kind `risk` (one item per right side, however many times it is joined) | a sentence of the note or a watch calls such a LEFT join harmless to the row count (无影响, 不影响行数, 不会放大 …); one warning per place. A phrase right after a negation is no such claim (不保证不放大, 不一定不放大, 未必不影响行数); a sentence that names no such join but says 左关联 is read as meaning every unproven LEFT join, unless it names a join proven unique (`safe`) and the clause holding the phrase has none of 都, 均, 全部, 所有, 一律, 任何, 皆. Nor is a phrase made under a condition with its failing case said: a condition word before the phrase in the sentence (若, 如果, 假如, 倘若, 假设, 只要, 只有, 一旦, 除非, 当 / 在 … 时) and the rows multiplying after it (会 / 可能 + 放大, 膨胀, 重复, or 关联出多行 / 多条); or a next sentence opening with 若 / 如果 / 一旦 … 不成立 / 不唯一 / 不满足 that says the rows multiply; or a condition word before the phrase and a next sentence opening with 否则, 不然 or 反之 that says so. A failing case naming a join the sentence has not named up to the phrase still warns, and a trailing reservation alone (「注释推出，SQL 未证明」) is no failing case. A join off the grain path (below an aggregate) is held to neither |
| 11 | `derived_codes` | a literal a column's CASE / IF returns (`case_outputs`) is missing from its `code_values` (one failure per value; NULL, `''` and TRUE / FALSE are not codes; an entry with `else: computed` is information only and is not asked for) | a code value whose meaning is success-like (成功 / 正常 / 通过 / 有效) comes from a branch that gathers several source values or the ELSE, and neither the column's `watch` nor a `summary.watch` with `refs` `column:<name>` says so |
| 12 | `documented_meaning` | a code value marked `unconfirmed`, or whose meaning starts with 待确认 once parenthetical asides are dropped (`待确认（猜测：…）` does, `已实名（是否含补录待确认）` does not), is explained by the column's comment or a source column's comment (`0-申请 1-成功` pairs, or a `正常、锁定、删除` list whose label the SQL quotes), or the dictionary confirms it on the column or a source column (`confirmed_values`; the fix: write the dictionary's meaning, sourced `confirmed`); a state whose documented or confirmed meaning is itself 待确认 may say so | a qualifier (`增值税`, `税`, `手续费`, `罚息`, `冲正`, `测试`) in the main input's comment or a source column's comment, absent from the target's comments, is missing from `summary.what` (main input) or from every affected column's meaning / derivation (one warning per term) |
| 13 | `header_facts` | — | the SQL header states a lifecycle (`header_facts.lifecycle`) or a data volume (`header_facts.volume`) that neither `summary.refresh.how_to_read` nor a watch mentions; not checked when the header describes another table of the task (`header_facts.about`) |

Check 9 exists because a daily full snapshot described as incremental leads a reader to
add partitions together and count every row once per day.

Checks 1–9 hold a document's form to the packet: every column covered, every source
cited, every quote found. Checks 10–13 hold what it means, because a page can pass all of
the first nine and still mislead: a join that repeats rows left unsaid, a derived code
value left out, a value the comment already explains left as a question, a qualifier
such as 增值税 or 测试 dropped, a ten-day lifecycle not passed on. They read the packet
facts described under "What a packet holds" (`fan_out`, `case_outputs`, `header_facts`)
and the comments; a packet built before those facts existed has none, and those checks
then find nothing to look at. The qualifier list is `QUALIFIER_TERMS` in
`scope_lineage/semantics/checks_documented.py`; a term inside a longer one found in the
same comment (税 in 增值税) is reported once, as the longer term.

The normalization for check 5 lower-cases, drops identifier quotes, table qualifiers,
whitespace and a leading `WHERE` / `AND` / `ON`, so the lineage's `` `latest`.`rn` = 1 ``,
a quoted `WHERE rn = 1` and the script's `latest.rn=1` compare equal.

The lineage renders every predicate through SQLGlot, while `rules[].sql` quotes the script
as written, so check 5 compares both in one space. A fragment counts in two forms: its
loose text, and — when SQLGlot parses it in the lineage's dialect — the text SQLGlot renders
for it. The task SQL counts as its loose text, its rendered text, and one unit per `WHERE`,
`HAVING` and `ON` predicate and per conjunct of each, rendered as written and with every
column a subquery or CTE computes replaced by the expression behind it. A quote is found
when any of its forms occurs in the script or equals a unit; a filter is cited when one of
its forms meets a form of a quote or of a unit the quote equals. So the script's
`nvl(x, 0) = 1`, `substr(n, 1, 2) = 'AB'` and `x is not null` cite the lineage's
`COALESCE(x, 0) = 1`, `SUBSTRING(n, 1, 2) = 'AB'` and `NOT x IS NULL`, and a quoted
`a.dt = '${bizdate}'` cites `DATE_FORMAT(time_inst, 'yyyyMMdd') = '${bizdate}'` when the
subquery `a` computes `dt` that way. A fragment or script SQLGlot cannot parse keeps the
loose text match.

### Report

A table's pass rate is the share of checked items that did not fail; a warning is listed
but does not count against it. The text summary prints each table's line and then its
failures, one per line, in the form a rewrite prompt can take as it stands:

```text
demo_dwd.dwd_party_customer_info_df: 46/51 checks passed (90.2%), 5 fail, 1 warn
  FAIL [1 coverage] columns: 缺少目标表的列 verified_customer_no（表内第 2 列）；补上这一列
  WARN [2 source_columns] columns[0].source_columns[1]: ...
  FAIL [9 time] summary.refresh.time: 写了 incremental，但上游 demo_ods.ods_core_customer_df 都按单一分区取全量快照，...
Validated 1 document(s): 0 clean, 1 with failures, 0 with warnings only, 0 with schema errors
```

`--json` prints the same as a `table-semantics-validation/1` document:

```json
{
  "doc_format": "table-semantics-validation/1",
  "tables": [
    {
      "table": "demo_dwd.dwd_party_customer_info_df",
      "file": "demo_dwd.dwd_party_customer_info_df.json",
      "schema_errors": [],
      "counts": {"pass": 45, "warn": 1, "fail": 5},
      "pass_rate": 0.902,
      "checks": {"coverage": {"pass": 5, "warn": 0, "fail": 1}},
      "failures": [
        {"check": "coverage", "status": "fail", "at": "columns", "message": "..."}
      ]
    }
  ],
  "summary": {"documents": 1, "clean": 0, "tables_with_failures": 1,
              "tables_with_warnings_only": 0, "tables_with_schema_errors": 0, "pass_rate": 0.902}
}
```

### Exit codes

| Code | When |
| --- | --- |
| 0 | every document is schema-valid (cross-check failures are reported, not fatal) |
| 1 | at least one document has a schema error, or the directory holds no JSON |
| 2 | the documents directory or `--packets` does not exist |

## Independent review and revision

`semantic validate` guarantees form: every column is written, sources are in the lineage, rules quote the SQL, time semantics match the partitions, row-multiplying joins are named. It cannot guarantee meaning — when a derived column is NULL, whether a page shows target codes or source codes, whether a backfilled 0 means "zero" or "no value", whether the reading notes contradict the usage notes. A real acceptance run found pages that passed every check and were still wrong on exactly these points.

So two steps follow writing, both in the agent skill:

1. **Independent review** (`skills/scope-lineage/references/table-semantics-review-prompt.md`): a separate model call reads only the packet, the document and the confirmed facts, works through a sixteen-item checklist and lists factual errors by severity as "document says / material shows / change to". The reviewer may read sibling tables' packets to check what the document says about them. Item 16 treats the packet's row-multiplication and grain verdicts as the tool's judgement, not fact: where the SQL contradicts one, the SQL wins, and the review lists each such case in a closing section of its own; a join marked 「在 pN 右侧内部」 is checked through pN's verdict, and a document that calls a 「工具未判定」 join harmless must quote the SQL that shows it. Items 13 and 5 name what is most often written as fact: whether a source record is updated in place, what a downstream known only by its task name does with the table, whether the partition day is the business day, and whether an `= ''` clean-up on a numeric or date column takes effect. After a packet rebuild and a full rewrite, the first review is also given the old review, kept as `reviews/<db.table>.prior.md`, and judges each old finding: still applicable under the new packet or not, and avoided or made again by the new document (the prompt's 「材料包重建后的重写：带上旧审读」 section).
2. **Revision** (`skills/scope-lineage/references/table-semantics-fix-prompt.md`): verify each finding, apply it (a tool verdict the review shows the SQL overrules is rewritten per the SQL, naming the packet's verdict and quoting the SQL, and a check-10 warning that sentence draws is kept rather than worded around), re-read the whole page to remove contradictions, keep inference apart from fact, run `semantic validate` again, and as the last step record that the revision finished with `semantic fixed` (below).

Two lessons: the review must be a separate call — a writer re-checking its own page does not find its blind spots; and a revision easily fixes one sentence while leaving the old claim elsewhere on the page, so the whole-page re-read is not optional. When a second review is wanted, it follows the review prompt's 「修订后再审读」 section: its inputs are the packet (possibly rebuilt), the revised document and the previous review, and it checks only whether each previous finding was fixed, the four areas of page consistency / inference vs fact / confirmed facts / sibling tables, and any facts new or changed in a rebuilt packet; the severity rules do not change, and the review still opens with front matter (`reviewed_doc_digest` is the revised document's digest as `scope-lineage semantic digest` prints it, `reviewed_packet_digest` the packet read this round). Never give the acceptance questions to the writing, review or revision calls.

## `semantic status`: batch runs that resume

With a few dozen tables, writing, review and revision are handed to the model in batches (each
table and step is its own model call; a batch is how many run at once), and
a run can be interrupted halfway. `semantic status` reads a run directory back and says where
each table stands and which tables the next step still needs. It only reads files and calls
the validator in-process; it never calls a model and never changes a file.

### The run directory

```text
<run>/packets/<db.table>/packet.json   semantic packet --out <run>/packets
<run>/docs/<db.table>.json             the table-semantics/1 documents the model writes and fixes
<run>/reviews/<db.table>.md            the independent review, opening with front matter
<run>/reviews/<db.table>.prior.md      the old review kept across a rewrite; status does not read it
<run>/pages/<db.table>.md              semantic render <run>/docs --out <run>/pages
```

Each directory can be moved with `--packets`, `--docs`, `--reviews` and `--pages` (for
example to put the pages at `<pages>/semantics` under the `catalog render` output). The
tables are those that appear in any of the packets, documents or reviews; with `--only` they
are exactly those tables, and a table with nothing in the run is `no_packet`. The
toolchain's other documents in the documents directory (confirmations, validation reports,
status reports, batch files) are skipped, as `validate` skips them.

### Stages

Every table is at one of seven stages, each requiring the one before:

| Stage | Condition |
| --- | --- |
| `no_packet` | no `packet.json` |
| `packet` | a packet, no document |
| `drafted` | a document flagged `invalid` or `packet_stale` |
| `valid` | the document meets its schema and fails no cross check (warnings allowed), and no review applies to it |
| `reviewed` | a review with high or medium findings the document still has to answer: a review of this very document (`reviewed_doc_digest` is the document's digest), or a revision without a fix record (`fix_unconfirmed`); or a review without front matter |
| `fixed` | a review of this very document with no high or medium finding; or a fix record (`fixed_doc_digest`, written by `semantic fixed`) for this very document |
| `rendered` | `fixed`, and the page is not older than the document (by modification time) |

The document digest is the first sixteen hex digits of SHA-256 over the document's canonical
JSON (sorted keys, no whitespace, UTF-8) — the same algorithm as `packet_digest`
(`scope_lineage/semantics/digests.py`), so re-indenting or reordering keys keeps it and
changing any value changes it. `scope-lineage semantic digest <doc.json>` prints it, and so
does each table's `doc_digest` in the status report.

### Flags

| Flag | Condition | Effect |
| --- | --- | --- |
| `packet_stale` | the document's `packet_digest` is not the current packet's | stage `drafted`; rewrite from the new packet |
| `invalid` | a schema error, an unreadable file, or a failed cross check other than check 8 (`digest`) | stage `drafted`; rewrite from the failure list |
| `review_packet_stale` | the review names the packet it read (`reviewed_packet_digest`), and it is not the packet the document is written against | back to `valid`; review again |
| `review_stale` | the document changed after the review and no fix record ties the change to it: the review asked for no high or medium change, or it names no packet (a review written before `table-semantics-review@5`) | back to `valid`; review again |
| `fix_unconfirmed` | the review read the current packet and has high or medium findings; the document changed after it, but has no fix record for this version: the revision was interrupted, or the document changed again after the record | stage `reviewed`; `--next fix` dispatches it again |
| `review_unparsed` | the review file has no complete front matter | stage `reviewed`, and no step dispatches it again; add the front matter or delete the review to review again |
| `render_stale` | `fixed`, and the page is older than the document | stage `fixed`; render again |
| `doc_misfiled` | a document file is named for another table than the `table` it holds (both tables are flagged), or two files hold this table | none -- a warning at any stage. The table the file is named for looks unwritten (`packet`), and of two files the first by path is read; put each document back as `docs/<db.table>.json` with that `table` |

### How a review is judged

A valid document with a review is judged by these rules in order; the first that holds
decides. `d` is the document's digest, `dp` its `packet_digest` (by now the packet's own —
otherwise the table is `drafted packet_stale`):

1. the review read `d` (`reviewed_doc_digest`): `reviewed` with high or medium findings,
   else `fixed`;
2. the review names a packet (`reviewed_packet_digest`) other than `dp`:
   `valid review_packet_stale`;
3. the fix record (`fixed_doc_digest`) is `d`: `fixed`, whatever the review found —
   low findings a revision took up included;
4. the review names no packet: `valid review_stale`. Without the key a revision and a
   rewrite from another packet look the same, so such a review is never handed to a fix;
5. high or medium findings: `reviewed fix_unconfirmed`;
6. low findings only: `valid review_stale`.

A revised document that fails validation is `drafted` before any of this. The fix record
only says the reviser declared the revision done and the document was valid then; whether
each finding was fixed correctly is the next review's call.

Boundary: when a re-review leaves only low findings — a low finding it calls half-fixed included —
rule 1 makes the table `fixed` and `--next` never hands it out again, which is the "low findings
are not fixed" convention. To close them anyway, dispatch one more revision and finish it with
`semantic fixed` as usual (the re-review carries `reviewed_packet_digest`, so the record is
written) and the table stays `fixed`; editing the document without the record sends it back to
`valid review_stale` under rule 6, and it is reviewed again.

### `semantic fixed`: the fix record

```bash
scope-lineage semantic fixed <run> --only <db.table> ... [--packets <dir>] [--docs <dir>] [--reviews <dir>]
```

The last step of a revision. For each table it judges the run as `status` does, and writes
`fixed_doc_digest: <document digest>` into the review's front matter (replacing an earlier
record; nothing else in the file changes) only when all of these hold: the table has a
packet, a document that is neither `invalid` nor `packet_stale`, and a review with complete
front matter; the review names the packet it read and that is the document's
`packet_digest`; and the document is not the version the review read. Otherwise it writes
nothing for that table and says why on standard error. A new review overwrites the file
and drops the record with it. The model never writes the record by hand.

| Exit code | Condition |
| --- | --- |
| 0 | every table's record was written |
| 1 | at least one table was refused (the others were still written) |
| 2 | the run directory does not exist, or no `--only` |

### The review's front matter

A review is markdown a model writes, and it must open with a block like this
(`semantic digest` gives the digest):

```yaml
---
reviewed_doc_digest: 2a9b25086e81590f
reviewed_packet_digest: ec811d2e60ec6088
high: 1
medium: 2
low: 0
---
```

`reviewed_doc_digest` and the three counts are required; the digest must not be empty and
the counts are non-negative whole numbers. Anything less is treated as no front matter
(`review_unparsed`). `reviewed_packet_digest` is the `packet_digest` of the packet the
reviewer read, copied from `packet.md`; `table-semantics-review@5` and later always write it, and a
review without it still parses but is judged by rule 4 above. `fixed_doc_digest` is added
by `semantic fixed` only; a value that is not sixteen lower-case hex digits counts as no
record. The parser needs no YAML library: one `key: value` per line.

### Output

```bash
scope-lineage semantic status <run> [--only <db.table> ...] [--json [<path>|-]]
scope-lineage semantic status <run> --next {draft,review,fix,render} [--batch-size 5] [--out <path>]
scope-lineage semantic fixed <run> --only <db.table> ...
scope-lineage semantic digest <doc.json> ...
```

By default it prints one line of stage counts, then one line per table (its stage and flags), then one line per flag naming its tables:

```text
Status of 3 table(s): no_packet 0, packet 1, drafted 1, valid 1, reviewed 0, fixed 0, rendered 0
  demo_dwd.dwd_lending_borrower_df     packet
  demo_dwd.dwd_lending_loan_df         drafted packet_stale
  demo_dwd.dwd_party_customer_info_df  valid
  packet_stale: demo_dwd.dwd_lending_loan_df
```

`--json` writes the `table-semantics-status/2` report (`-`, or no path, for standard output):

```json
{
  "doc_format": "table-semantics-status/2",
  "directories": {"packets": "run/packets", "docs": "run/docs", "reviews": "run/reviews", "pages": "run/pages"},
  "tables": [
    {
      "table": "demo_dwd.dwd_party_customer_info_df",
      "stage": "valid",
      "flags": [],
      "packet_digest": "ec811d2e60ec6088",
      "doc_digest": "2a9b25086e81590f",
      "doc_packet_digest": "ec811d2e60ec6088",
      "schema_errors": 0,
      "failures": 0,
      "review": null
    }
  ],
  "summary": {
    "tables": 1,
    "stages": {"no_packet": 0, "packet": 0, "drafted": 0, "valid": 1, "reviewed": 0, "fixed": 0, "rendered": 0},
    "flags": {"packet_stale": [], "invalid": [], "review_packet_stale": [], "review_stale": [], "fix_unconfirmed": [], "review_unparsed": [], "render_stale": [], "doc_misfiled": []}
  }
}
```

`review` is the parsed front matter (`reviewed_doc_digest`, `reviewed_packet_digest`,
`fixed_doc_digest`, `high`, `medium`, `low`; the two optional keys are `null` when absent),
or `null` with no review or one that does not parse; `failures` counts the failed cross checks
other than check 8.

### `--next`: batches and resuming

`--next <step>` lists the tables that step still needs, sorted by name, `--batch-size` to a
batch, as `table-semantics-next/1` (on standard output without `--out`):

```json
{"doc_format": "table-semantics-next/1", "step": "review", "batches": [["demo_dwd.dwd_party_customer_info_df"]]}
```

| Step | Tables selected |
| --- | --- |
| `draft` | `packet` and `drafted`: no document yet, a stale one, or one that fails validation |
| `review` | `valid`, including those flagged `review_packet_stale` or `review_stale` |
| `fix` | `reviewed` with front matter: the review has high or medium findings and the document has not changed, or changed without a fix record (`fix_unconfirmed`) |
| `render` | `fixed`, including those flagged `render_stale` |

A table that is past a step never comes back for it, so after an interruption, running
`status --next` again resumes where the run stopped. A `no_packet` table is in no batch;
build its packet first. `render` is one deterministic command and is batched only to keep
the orchestration uniform; rendering the whole documents directory at once is fine too. A
table still `drafted` after two `draft` rounds has a failure left to the owner (the rewrite
rule: stop forcing a spot that failed two rounds running); the orchestrator should take it
out of the round and tell the user rather than dispatch it forever.

### Exit codes

| Exit code | Condition |
| --- | --- |
| 0 | reported (stale or failing tables still exit 0) |
| 2 | the run directory does not exist, or `--json -` and `--next` without `--out` both want standard output |

## `semantic confirm`

```bash
scope-lineage semantic confirm <documents> --confirmations <file> [--out <dir>]
```

The confirmations file is a `semantic-confirmations/1` document (schema:
`scope_lineage/schemas/semantic-confirmations.schema.json`). Each entry names one table,
one target, the answer (`value`), who gave it (`by`) and when (`date`, `YYYY-MM-DD`):

```json
{
  "doc_format": "semantic-confirmations/1",
  "confirmations": [
    {
      "table": "demo_dwd.dwd_party_customer_info_df",
      "target": "question:q1",
      "value": "不会。注册系统只允许 F、M、U 三个值。",
      "by": "demo-reviewer",
      "date": "2026-09-26"
    }
  ]
}
```

| Target | `value` | Effect |
| --- | --- | --- |
| `question:<id>` | the answer text | `status: answered`, `answer`, `answered_by`, `answered_on` |
| `column:<c>.meaning` | the meaning text | replaces `meaning`; the column's `sources` gains `confirmed` |
| `column:<c>.code_values` | a list of `{value, meaning}`, or one such object | a list replaces the code values, one object is merged into them; each confirmed value gains `confirmed` and `unconfirmed: false` |
| `summary.row` | an object of row fields, or the row text | merged into `summary.row`; its `sources` gains `confirmed` |

Every applied confirmation is logged under `confirmed[]`, and applying the same file twice
changes nothing the second time. A confirmation whose table, question or column does not
exist, whose value has the wrong shape, or whose value would make the document fail the
schema is **not applied and not dropped**: the summary line counts it as `unmatched` and
names it with the reason. Without `--out` the changed documents are rewritten in place;
with `--out` every document is written there and the originals are left alone. A malformed
confirmations file exits 2.

## `semantic render`

```bash
scope-lineage semantic render <documents> --out <dir> \
  [--validation <report.json>] [--ontology <ontology.json>]
```

Renders every legal `table-semantics/1` document under `<documents>` as one page,
`<dir>/<db.table>.md`, and writes `<dir>/index.md`. The toolchain's other documents
(confirmations, packets, reports) are passed over; a document that does not fit the schema
is reported on stderr and not rendered, and the exit code is 1.

| Option | Required | Meaning |
| --- | --- | --- |
| `<documents>` | yes | The directory of `table-semantics/1` documents |
| `--out` | yes | The output directory |
| `--validation` | no | A `table-semantics-validation/1` report written by `semantic validate --json`: the page marks the failed items and ends with a 校验 section, the index shows the pass rate |
| `--ontology` | no | An `ontology.json` written by `catalog build`: each table's domain and concept come from the catalog, the concept linked to `../concepts/<slug>.md` |

### The table page

The page follows the order of a hand-made sample page:

| Part | Content |
| --- | --- |
| Title line | The table name; under it the domain (with `--ontology` the domain of the table's concept, else the database name), 「本表是 <concept> 的 <representation kind>表」, and how many items on the page are confirmed; with a report, the pass rate too |
| 一页纸 | What the table is, what a row is (grain columns, where the grain comes from, whether it is unique), refresh and how to read, which records it keeps (citing its rules), where the data comes from (each upstream table and its role), who uses it, good for / not for, what to watch (each with its kind), open questions (an answered one with its answer, who answered and when) |
| 字段 | Five groups: identifiers (标识与关联), states and codes (状态与码值 — every column with code values is here, with an extra 码值 column), amounts (金额 — the unit after the meaning) and time (时间), each a 字段 / 含义 / 口径 / 来源 table; descriptive and technical columns (描述与技术列) as one line. A 口径 spells out each branch (`线上：…；线下：…`), then the general wording, then when the column is empty |
| 加工过程 | The producing task (its cycle and purpose), then the steps |
| 规则（原文） | Each rule's id and kind, its business wording and its SQL |
| 来源说明 | What the source words and the marks mean; the prompt the page was written with and the packet digest it was written against |
| 校验 | Only with `--validation`: the pass rate, and each failed item and warning with its check, its place and how to fix it |

The marks on a page:

| Mark | Meaning |
| --- | --- |
| ✓ | The item's `sources` include `confirmed` (written by `semantic confirm`), or the question was answered; shown beside what it confirms (a column's meaning, a code value, a rule, …) |
| ⚠ | The item carries a `watch`, whose text follows; a column or rule named only by the summary's watch list (`column:<name>`, `rule:<id>`) shows 「⚠（见要注意）」 |
| ✗n | The report's n-th failed item falls on this item (numbered in report order); a failure about the whole table (a missing column, an uncited filter, a stale digest) is listed in the 校验 section only |
| `值（含义待确认）` | A code value marked `unconfirmed: true` (or whose meaning starts with 待确认) |
| （中置信）（低置信） | The item's `confidence` is not `high` |

### The index

`index.md` lists every table by domain, then by concept: the table (linked to its page),
what it is (`summary.what`), the validation pass rate (— without a report, 未校验 when the
report does not cover the table) and the number of open questions (still `open`); the
by-concept tables add the representation kind. With `--ontology` the domain is that of the
concept the table represents and each concept heading links to its concept page; without
it the database name stands in for the domain and the concept is the document's own
`concept`, shown as its id without a link. Tables that represent no concept are listed last
under 未关联概念. No company's table-name convention is used for grouping.

### Links to and from the concept pages

The catalog decides which concept a table belongs to: a table the catalog lists as a
representation takes the catalog's concept and representation kind; only a table the
catalog does not list falls back to the document's own `concept`. A table page links to
`../concepts/<slug>.md`, the concept page `catalog render` writes, so `--out` belongs in a
subdirectory of the `catalog render` output, such as `<pages>/semantics`. The other
direction is `catalog render --semantics <pages>/semantics`; see the
[ontology catalog](ontology-catalog.md). Linking both ways, run `catalog build`, then
`semantic render --ontology`, then `catalog render --semantics`: `semantic render` reads the built
`ontology.json`, and `catalog render` needs the `--semantics` directory to exist already (exit 2
when it does not). Both flags are optional; without them both
outputs are byte-for-byte what they were before this feature.

### Exit codes

| Code | When |
| --- | --- |
| 0 | Every document was rendered |
| 1 | A document does not fit the schema (the rest are still rendered), no document could be rendered, or `--validation` / `--ontology` declares the wrong `doc_format` |
| 2 | The document directory, `--validation` or `--ontology` does not exist or cannot be read |

## Relation to the ontology catalog and to `describe`

The two layers answer different questions. Table semantics is about one table, one
column, one piece of SQL; the [ontology catalog](ontology-catalog.md) is about business
concepts that span many tables. Table semantics is raw material for the catalog: its
`concept` key names the concept this table represents (`concept:<id>`) and the kind of
representation (the catalog's representation `kind`, such as `core`), so a table page and a
concept page can link to each other (`semantic render --ontology` and
`catalog render --semantics`), and a cross-table problem the catalog finds (a column
that actually holds another identifier) comes back to the table's document as a `watch`.

The [task-semantic description](semantic-doc.md) (`describe`, the semantic card) is no
longer the deliverable for a reader: its builder is the source of the packet's lineage
facts, and the table-semantics document written from that packet is what a reader gets.
