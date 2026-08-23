[中文](../zh-CN/task-lineage-v2.md) | English

# Task Lineage 2.0: task-level table state and row-set lineage

schema_version 2.0 is the task-level contract, and since 0.2.0 it is the only output. It preserves
the statement order of the script and, in one pair of lineage.json / diagnostics.json, describes
field value sources, the dependencies of row existence, and final table state; the complete
statement document of each write statement (the former 1.0 shape) is embedded in
`statement_lineage`. If you are unsure which layer to read, start with
[choosing the layer by scenario](contract-selection.md): field lineage and transformation-step
analysis only need the statement documents; the task-level fields target "what did the task do"
questions such as audits, incident forensics, and final table state.

## Usage

~~~bash
scope-lineage parse \
  --task-file task.json \
  --schema rich-table-metadata \
  --schema-fallback schema_info.csv \
  --target-ddl-metadata rich-table-metadata \
  --quality-policy strict \
  --compact-json \
  --out ./output
~~~

Python API:

~~~python
from scope_lineage import parse_task_lineage, write_task_lineage

result = parse_task_lineage(sql, task_name="daily_publish", schema=schema)
write_task_lineage(result, "./output/daily_publish")
~~~

## Top-level structure

| Field | Meaning |
| --- | --- |
| artifact_kind | Fixed at task_lineage. |
| analysis_status | complete or partial, kept separate from the syntax/graph parse_status. |
| statement_sequence[] | Every recognizable statement, in script order. |
| table_state_graph | The logical state nodes of each table before and after each statement, and the transition edges. |
| final_table_states | The state each modified table is in when the script ends. |
| statement_lineage | Statement-level evidence for INSERT/CTAS/MERGE, reusing the Core statement-document scope facts. |
| end_to_end_lineage | Final-state oriented, keeping value sources and row-existence sources separately. |

**The top-level `end_to_end_lineage` is a view merged by "final state × column"; it is not
equivalent to the per-statement array of the statement documents.** A MERGE's branch attribution
(`matched`/`not_matched`) is folded away in the merge; when one table is written twice the
statement documents give two rows (one per write) while this gives only the final-state row. That
is by design — the top level is final-state oriented — but it means "reading v2 equals reading v1"
holds only for the nested documents inside `statement_lineage.<statement_id>`: for branch
attribution and per-write granularity, read the nested documents, not the top-level array.

Every statement has a stable statement_id, a zero-based statement_index, stmt_kind, category, and
model_status. SET and empty semicolons stay in the sequence but are marked ignored, so they are
never miscounted as failed data changes.

Statements that produce a session-scoped relation additionally carry
`is_session_scoped_relation: true` — the relations created by `TEMP VIEW`, `GLOBAL TEMP VIEW`, and
`CACHE [LAZY] TABLE` live only for the session. `final_table_states` creates an entry for **every**
relation the script produces, including these; you must exclude them using that field before
reconciling against a catalog, or you will conclude the warehouse gained tables that do not exist.
Field lineage itself is unaffected: the two hops `mart.t.v ← tmp_v.v` and `tmp_v.v ← ods.real.v`
are each preserved as facts, and whether to fold them into one hop is the consumer's decision.
Whenever such a relation appears in a script, `diagnostics.warnings[]` carries one
`session_scoped_relations_present` entry listing every relation name — the marker sits on
`statement_sequence[]` while the misleading entries sit in `final_table_states`, so without a
cross-check you would miss it; hence the extra script-level reminder.

`INSERT OVERWRITE DIRECTORY` is another kind of "phantom table": the target is a file path rather
than a table, and the entry in `final_table_states` looks like `directory:/warehouse/export/daily`,
with a `directory:` prefix. It must likewise be excluded before catalog reconciliation; when such a
write appears in a script, `diagnostics.warnings[]` carries one `directory_targets_present` entry
listing every such target (the same convention as excluding them from `target_table` in the
statement documents).

## Two kinds of lineage that must not be conflated

- value_sources[]: where the field's value itself comes from;
- row_membership_sources[]: which fields decide whether the target row exists;
- value_condition_sources[]: which conditions decide whether an UPDATE/MERGE branch changes a field's value.

DELETE does not disguise WHERE fields as value sources of target fields. The field values of
surviving rows pass through from the target table's previous state, while the predicate fields enter
row_membership_sources, affecting the existence of the rows all target fields live in.
A MERGE's ON and WHEN conditions likewise enter row-membership/value-condition sources; only the
real UPDATE/INSERT expressions enter value_sources.

row_membership_sources[].table is always a physical table, never a query block. A target alias in a
MERGE condition resolves to the target table, while a USING alias is traced along the resolved USING
scope all the way to the physical root fields: when USING is a CTE or subquery, the physical table
behind it is recorded rather than the CTE name, and when USING is a UNION, the physical root fields
of every branch are preserved. When the trace cannot be completed, no name is filled in; a
merge_condition_source_unresolved fact gap is recorded instead (see the next section).

## value_sources[].source_kind: three kinds of source, and how to fold prior-state edges

Every `value_sources[]` entry carries `source_kind`, with only three possible values:

| source_kind | Meaning | Typical case |
| --- | --- | --- |
| `physical_field` | The value comes from a column of some physical table | The vast majority of lineage |
| `generated` | The value is produced by a constant or an expression referencing no input column | `'rcs' AS send_type` |
| `prior_table_state` | The value passes through from **the target table's own previous state** | Partitions not covered by `INSERT OVERWRITE ... PARTITION`, fields not assigned by `UPDATE`, rows surviving a `DELETE` |

### Why prior-state edges exist, and when to fold them

`prior_table_state` records "this field was not rewritten this time; it carries over from the
previous state". It adds nothing to **tracing the final physical source**, but it is necessary for
**explaining what one write actually changed** — so Core records it faithfully and the consumer
chooses by purpose.

They can form a substantial share of a task's `value_sources` edges. A consumer that only cares
"which physical tables does the field ultimately come from" (for example, comparing against a
platform that emits physical sources only) should fold them away:

```python
physical_only = [
    source
    for source in item["value_sources"]
    if source["source_kind"] != "prior_table_state"
]
```

### Do not filter by "same table name"

A seemingly equivalent approach is to drop rows where `source_table == target_table`. **That
criterion is wrong.**

By contract, a `prior_table_state` edge points to the target table's own previous state, so filtering
by `source_kind` is precise. But the converse does occur: rows on the same table that are **not**
prior-state edges exist, where the task reads its own table as a genuine input
(`INSERT INTO t SELECT ... FROM t`). That is **real lineage**, and filtering by table-name equality
would delete it along with the rest.

**The criterion is the kind of source, not whether the table names match.**

## value_sources[].transform: not every `WINDOW` source is a value source

`source_kind` answers "what kind of place does the value come from"; `transform` answers "what
transformation did it go through". They must be read together — counting only
`source_kind == "physical_field"` also counts a window's **grouping context** as a value dependency.

The sources of a window field mix three roles, but `transform` is uniformly `WINDOW`:

| Role | In `SUM(amt) OVER (PARTITION BY id ORDER BY dt)` | Decides the value? |
| --- | --- | --- |
| Value argument | `amt` | Yes |
| Partition key | `id` | No, it only decides which group it falls into |
| Order key | `dt` | No, it only decides the order within the group |

All three columns appear as `physical_field` + `transform: "WINDOW"`.

### Why this is the easiest place to get it wrong

`end_to_end_lineage` is a **flattened** view: it expands the whole scope chain down to physical
leaves and keeps only `{table, column, transform}`, **preserving neither which hop it was nor a way
back**. So a window partitioned by many columns puts all of them into some downstream field's
`value_sources`, which looks like "the sources were spread across an entire table".

The scope view in `lineage.json` does not create that illusion — there, each hop usually has only
one or two direct sources, and the context columns hang off the column that defines the window.

### How to take value sources only

The role information is on the `lineage.json` side: `scopes[].columns[].window` gives
`partition_by[]` and `order_by[]`, and only the column whose `transform` is `WINDOW` has it. The
method is to walk up `sources[]` to the column carrying `window` and remove its `partition_by` /
`order_by` from the sources.

Windows such as `row_number()` and `rank()` have no value argument, and an empty result after
removal is correct: their value is decided entirely by partitioning and ordering. The real value
source of such a field is in the expression outside the window, appearing as `DIRECT` /
`EXPRESSION` rather than `WINDOW`.

**To judge whether a column is a value source, look at its `transform` and at whether it appears in
the corresponding window's `partition_by` / `order_by` — do not just count the entries in
`value_sources`.**

## value_sources[] is a list of "participation paths", not a set of "dependency columns"

The same physical column can appear **several times** in one field's `value_sources`, each time
with a different `transform`. The dedup key is `(table, column, transform)`, and `transform` is
deliberately included: each record is one **way of participating**, not the same fact recorded
repeatedly.

A derived column can contain repeated participation paths:

```
valid_to ← window path from source fields
valid_to ← aggregate path from the same source fields
```

This is not inflation: the same columns arrive via **two paths** — one through a window-derived
column (`transform=WINDOW`), and one through an aggregate reading that window's output
(`transform=AGGREGATE`). A conditional value path may appear alongside them.

For "which physical columns does this field depend on", deduplicate by `(table, column)`:

```python
columns = {
    (source["table"], source["column"])
    for source in item["value_sources"]
    if source["source_kind"] == "physical_field"
}
```

For "where does the value come from" — that is a different question; see the previous section, and
do not filter by a `transform` allowlist alone.

### One filter that will wipe out your lineage

Someone will think "keeping only `DIRECT`/`EXPRESSION`/`CONDITIONAL` gives the value sources".
**That rule is wrong**:

| Field expression | Real physical source | After filtering by that rule |
| --- | --- | --- |
| `SUM(amt)` | `amt` | **empty** |
| `COUNT(DISTINCT amt)` | `amt` | **empty** |
| `SUM(amt) OVER (PARTITION BY id ORDER BY dt)` | `amt`, `id`, `dt` | **empty** |

The **value arguments themselves** of aggregate and window metrics carry `AGGREGATE` / `WINDOW`, so
filtering them out means filtering out the real sources. Most metric columns in a warehouse have
this shape. The rule looks like it works on windows such as `row_number()` that have **no value
argument**; that is a coincidence and does not generalize.

## value_sources[].source_state: which state this hop read

One table can have several states within one script (written twice, or a temporary relation
redefined by `CREATE OR REPLACE`). When a source records only the table name, those reads cannot be
told apart.

When a source table has been written within this script, the source additionally carries
`source_state`, whose value is a `table_state_graph.nodes[].state_id`:

```json
{"source_kind": "physical_field", "table": "v", "column": "id",
 "transform": "DIRECT", "source_state": "state:v:001"}
```

A table never written by this script does not carry the field — it is simply the state from before
the script started, with no second candidate to confuse it with.

The relation produced by `CREATE GLOBAL TEMPORARY VIEW gv` is recorded as **`global_temp.gv`**, not
`gv` — Spark puts such views in the `global_temp` database, the bare name used at declaration is not
resolvable, and any statement reading it must write `global_temp.gv`. Only by aligning the produced
name with the read name can this hop be recognized as a session-scoped relation; otherwise it looks
like an ordinary physical table.

### The edge carries the marker directly

The edge that reads a session-scoped relation carries `session_scoped: true` itself:

```json
{"source_kind": "physical_field", "table": "tmp_v", "column": "amt",
 "transform": "DIRECT", "source_state": "state:tmp_v:001", "session_scoped": true}
```

**No correlation back to `statement_sequence` is needed.** Taking only stored sources is a single
filter:

```python
[s for s in item["value_sources"]
 if s.get("source_kind") == "physical_field" and not s.get("session_scoped")]
```

This is **not a value of `source_kind`** — `source_kind` keeps its original meaning, existing code
filtering by `source_kind == "physical_field"` behaves exactly as before, it just still includes
these edges.

The marker is decided by the tool from the relation it actually resolved, so **an inconsistent
spelling cannot make it slip through**: a global temporary view is declared with a bare name and
read with a `global_temp.`-qualified name, so comparing by name would miss it; the marker on the
edge would not.

### If you only want to exclude, not fold

Reconciling against a catalog usually only requires removing these relations from the table list,
without touching field lineage:

```bash
jq -r '
  ([.statement_sequence[] | select(.is_session_scoped_relation==true) | .target_table]) as $scoped
  | .final_table_states | keys | map(select(. as $t | $scoped | index($t) | not))
' lineage.json
```

`["mart.daily", "tmp_v"]` → `["mart.daily"]`.

**But do not treat this as a way to filter field lineage.** Deleting only the session-scoped
sources without substituting anything leaves those columns pointing at no upstream table at all —
that hop is their only path. For clean field lineage, use `fold_session_scoped`.

### Two anti-patterns

**Do not judge by name or suffix.** **Real tables** named like `tmp_*` or `*_20260101` do exist, and
filtering by name kills them; conversely, temporary views often carry no recognizable prefix at all.
A global temporary view is worse still: declared with a bare name and read with a `global_temp.`
qualified name, so a name comparison must miss it. The only criterion is `session_scoped` /
`is_session_scoped_relation`.

**Do not use "did the source count change" to judge whether the tool handled this.** The marker is
additive and deletes no edges, so the source count of the default artifact **does not change by
design**. What you verify is the result after folding: whether `value_sources_folded` is `true`, and
whether every stored column still has sources afterwards.

### If you want a "clean" artifact: use fold_session_scoped

You do not have to write the folding yourself. Core exports an implementation:

```python
from scope_lineage import fold_session_scoped

folded = fold_session_scoped(document)     # the input is not modified
```

It resolves `final_table.v ← temp_view.v ← real_table.v` into `final_table.v ← real_table.v`, and
also removes the rows of those temporary relations themselves along with their entries in
`final_table_states`.

**What cannot be folded is not quietly dropped.** Such a row keeps its original edges and reports:

| Field | Meaning |
| --- | --- |
| `value_sources_folded` | `true` = every hop in this row folded successfully; `false` = some hop could not be folded |
| `fold_incomplete_reasons` | Why folding stopped, present only when `false` |

There are four reasons, each corresponding to a situation that really occurs:

- `source_state_not_in_document` — the read happened **before** that relation was redefined.
  `end_to_end_lineage` is a final-state view, and that state has no row; substituting the surviving
  definition would **point at the wrong origin**.
- `source_column_not_in_document` — the relation's own column was not resolved (usually an
  unexpanded `SELECT *` with only a single `*` row).
- `source_column_has_no_sources` — the column has no sources at all in the document.
- `fold_depth_exceeded` — the relations form a cycle.

**Empty sources after folding ≠ this column has no lineage**, which is why this implementation never
returns empty — when it cannot fold, it keeps the original edge and says so. That is exactly what
hand-written folding gets wrong most often.

### A known boundary: table-creation syntax that cannot be parsed

Forms **without `AS SELECT`**, such as
`CREATE TEMPORARY VIEW tv (...) USING csv OPTIONS (...)`, cannot be structured by the parser; the
statement degrades to `stmt_kind: COMMAND` / `model_status: unsupported`, and it is therefore
**not** marked as a session-scoped relation.

The tool does not guess about it: the criterion comes only from AST facts, and here there is no
usable AST. Regexing a relation name out of unparsed text is the same class of move as guessing a
table by its `tmp_` prefix, and this tool does not do that.

The practical impact is limited, but know where the boundary is:

- it does **not** register a phantom table — `tv` does not appear in `final_table_states`;
- the script is marked `analysis_status: partial`, with `unsupported_data_change` among the blocking reasons, accompanied by the two warnings `unsupported_statement` and `metadata_incomplete`;
- **but** a field that read `tv` still has `trace_complete` = `true` — that hop's source is a relation the tool could not model. **In a script containing `unsupported` statements, per-row `trace_complete` must not be trusted on its own**; check `analysis_status` first.

### Check this before folding

`end_to_end_lineage` is a **final-state view** (the state of each table when the script ends), so
**rows for intermediate states are not in the document**. Before folding a hop, confirm that
`source_state` can be found in `end_to_end_lineage[].target_state`:

```python
available = {item["target_state"] for item in doc["end_to_end_lineage"]}
foldable = source.get("source_state") in available   # sources without source_state need no folding
```

**If it is not found, keep the original edge; do not substitute.** Not found means this read hit an
intermediate state, while the row for that table in the document describes a different state —
substituting by table name would give you "the last definition", which is a false claim about where
that column came from.

Example:

```sql
create or replace temp view v as select id from ods.a;
insert overwrite table mart.x select id from v;      -- reads state:v:001
create or replace temp view v as select id from ods.b;
insert overwrite table mart.y select id from v;      -- reads state:v:002
```

`mart.x.id`'s source is `state:v:001`, while the document has only the `state:v:002` row for `v`.
Folding by name would conclude `mart.x.id ← ods.b.id` — it actually comes from `ods.a`. With
`source_state` present, this case **can be detected**, and the consumer knows this hop cannot be
folded within this document.

What the tool gives here is the fact of "which state was read"; it does not promise every state is
retrievable from the document.

## State transition semantics

| Statement | rowset operation | Field value semantics |
| --- | --- | --- |
| INSERT INTO | APPEND | Old-state values coexist with the newly appended projection values. |
| INSERT OVERWRITE | REPLACE | On a whole-table overwrite, the new state's values come from this projection. |
| INSERT OVERWRITE PARTITION (a partition spec with values, or a DYNAMIC session) | REPLACE_PARTITION | Overwritten partitions come from this projection; unaffected partitions keep their old-state sources. |
| INSERT OVERWRITE PARTITION (a fully dynamic spec with the session not set to DYNAMIC) | REPLACE | **Whole-table replacement.** Spark's `spark.sql.sources.partitionOverwriteMode` defaults to `static`, so a `PARTITION(dt)` first deletes the whole table's directory and then writes. See "The overwrite radius depends on the session setting" below. |
| CTAS | REPLACE | Creates a new state with no old-target branch. |
| DELETE | DELETE_MATCHED_ROWS | Surviving rows are PASSTHROUGH_SURVIVING_ROWS; without a WHERE it is DELETE_ALL_ROWS. |
| TRUNCATE | RESET_ALL_ROWS | The row set is known to be empty, the field set is preserved, but the fields' value_sources are empty. |
| TRUNCATE PARTITION | RESET_PARTITION | Unaffected partitions and their existing field sources are preserved. |
| UPDATE | PRESERVE_ROWS | Assigned fields are a conditional update; the others pass through. |
| MERGE | MERGE | The old state plus the resolved update/delete/insert branches together form the new state. |

### The overwrite radius depends on the session setting

How much data `INSERT OVERWRITE` deletes is decided by
`spark.sql.sources.partitionOverwriteMode`, and **Spark's default value is `static`**:

| Partition spec | Session setting | Deletion radius |
| --- | --- | --- |
| `PARTITION(dt='2026-01-01')` | any | Only `dt=2026-01-01` |
| `PARTITION(dt)` (fully dynamic) | `static` (**default**) | **The whole table directory** |
| `PARTITION(dt)` (fully dynamic) | `dynamic` | Only the partitions actually written this run |
| `PARTITION(dt, region='mx')` (mixed) | `static` | Everything under the static prefix `region=mx` |

A `SET` inside the script is read and takes effect in statement order. **When the script does not
set it, Spark's default `static` is assumed** — that is an assumption, not an observed fact: a real
cluster may set `dynamic` in `spark-defaults.conf`.

#### When the cluster default differs from Spark's official default

Spark's official default is `static`, and this tool infers accordingly. **If your cluster is
configured as `dynamic`** (the effective value can be confirmed on the Environment page of the Spark
Web UI), pass:

~~~bash
scope-lineage parse --contract-version 2.0 --partition-overwrite-mode dynamic ...
~~~

The consequence of not passing it is **material**: every
`INSERT OVERWRITE ... PARTITION(col)` that gives no partition value (the everyday way partitioned
tables are written) has its effect judged in the opposite direction, and `end_to_end_lineage` will
be missing a large number of "from the table's own historical state" source edges — for a partition
table overwritten daily, the tool would conclude that each overwrite wiped the history.

**A `SET` inside the script always wins over this flag**: the script is the more specific statement.
The flag **requires `--contract-version 2.0`**, which is the only contract; an explicit 1.0 request
is rejected outright rather than silently ignored.

**A knob you set is a knob you must maintain.** If the cluster configuration changes and this flag
is forgotten, the output is a confidently wrong answer;
`partition_overwrite_mode_declared` records the value declared at the time and is the only forensic
lead.

#### Two things not to get wrong

**`hive.exec.dynamic.partition.mode` is unrelated to this setting.** That one is a **compile-time**
admission check on the shape of the partition spec (`strict` requires at least one static partition
column, and errors otherwise); it **does not affect the deletion radius**. Reading `nonstrict` as
`dynamic` is wrong.

**Hive serde tables are unaffected by this setting.** From Spark's own documentation: *"this config
doesn't affect Hive serde tables, as they are always overwritten with dynamic mode."* This tool only
sees the SQL and cannot tell whether the target table takes the datasource or the Hive serde write
path, so for a bare dynamic overwrite of a Hive serde table, the model's `REPLACE` is
**conservative (larger)** than the actual deletion radius.

#### How to tell from the artifact whether this conclusion was a guess

`effect.rowset_effect` has an optional field `partition_overwrite_mode_source`:

| Value | Meaning |
| --- | --- |
| **field absent** | This conclusion does not depend on the setting (static partition values, a mixed spec, CTAS, MERGE, a whole-table overwrite of a non-partitioned table, …) |
| `observed` | The `SET` appeared in the script |
| `assumed_default` | **The script did not set it.** The value actually used is on the next row, `partition_overwrite_mode_declared`; only when that field is **absent** was Spark's default `static` inferred — and in that case, if the cluster is actually configured as `dynamic`, this entry's `REPLACE` is conservative and the target table's own historical state does in fact survive |
| `partition_overwrite_mode_declared`<br>(a separate field) | The cluster value the deployment declared with `--partition-overwrite-mode` (`static`/`dynamic`). **Present only when `partition_overwrite_mode_source` is `assumed_default`** — a script that `SET` it itself is `observed` and no longer needs this. It carries a value rather than a boolean: for writes with no `PARTITION` clause, the two declarations produce identical output everywhere else, and only this field can say what was declared at the time |

**`observed` is not the same as "certain".** It only means that `SET` was seen in the script. As
noted above, the setting has no effect on Hive serde tables, and this tool cannot tell the write
path from the SQL — so even `observed` rests on an unobservable premise.

**Two shapes are marked**: a fully dynamic partition spec (`PARTITION(dt)`), and **no `PARTITION`
clause at all while the target table is partitioned** — the latter is likewise a dynamic partition
insert in Spark. Judging the latter requires `--target-ddl-metadata` to supply that table's
partition columns; without it the judgment cannot be made and the field does not appear.

**`end_to_end_lineage` does not carry this marker** (deliberately, to avoid repeating it per row).
To get from a lineage row back to it, correlate three hops: `target_state` →
`table_state_graph.nodes[].producer_statement_id` → `statement_sequence[].effect.rowset_effect`.



For example, TRUNCATE; INSERT forms two intermediate states: the post-TRUNCATE state has
known_empty=true, and the following INSERT produces the new final state. So a consumer must not
assert that the table is empty at the end of the task merely because TRUNCATE appears in the script.

An empty state is not "no lineage" either. After a whole-table DELETE/TRUNCATE there are still
target-table states and field entries; the empty value_sources then mean there are no surviving
field values, while known_empty and the state transition edges explain why the row set is empty.

## Metadata and fact gaps

When the target schema of a DELETE/UPDATE is missing, the tool still outputs table-level state
transitions but does not guess the full field set; it records a
schema_missing_for_state_passthrough fact gap and sets analysis_status=partial.
A `*` in a projection that cannot be expanded against a schema keeps a wildcard source, records
projection_wildcard_unexpanded, and sets the corresponding final field's trace_complete to false.

Incompleteness **propagates across one hop inside the script**. Reading an in-script relation whose
own columns were not resolved (for example, one built from an unexpanded `SELECT *` with only a
single `*` row) makes the read field record source_state_columns_unknown, with `trace_complete`
false. Such fields previously claimed `trace_complete: true` — a claim built on a relation nobody
could describe; meanwhile a consumer folding that hop would find no row for the column, get an empty
result that reads like "this column has no lineage", and the `true` next to it would not contradict
that. The gap is recorded under the same name in `lineage_fact_gaps`, and `needed_fact` lists which
states are involved.

Incompleteness of the target table's **prior** state already propagated; this is the same question
asked on the other edge: the relation being **read**.

When a MERGE condition field cannot be traced to a physical root field,
merge_condition_source_unresolved is recorded, with the fields statement_id, source_alias, column,
root_impact=true, and needed_fact. Triggering cases include a condition referencing a column the
USING relation does not output, and a condition using a qualifier that is neither the target alias
nor the USING alias. This gap has root_impact=true, so it sets analysis_status=partial and makes the
strict gate return non-zero.

diagnostics.json.metadata_coverage records referenced tables, covered tables, missing tables, the
number of schema sources, and metadata conflicts.
--schema-fallback only fills in tables missing from --schema; when definitions of the same table
disagree, the authoritative source is kept and the conflict is reported.

## Quality gates

--quality-policy permissive|balanced|strict controls the CLI exit code; it changes no fact in the
artifact.

- permissive: keeps the parse-failure exit behavior;
- balanced: also returns non-zero for unmodeled data changes;
- strict: additionally rejects recovered syntax, root-impact fact gaps, and target-binding fallback.

You can also use --fail-on-root-gap, --fail-on-unsupported-mutation, and
--fail-on-binding-fallback separately. --allow-partial does not override an explicit quality gate.

## Compatibility and consumption

1. One output directory belongs to one task. Re-parsing that task replaces the whole owned directory generation, so `lineage.json` and `diagnostics.json` always come from the same run. Derived `mapping.md` / `warnings.md` files are removed and must be rendered again; an unknown file makes replacement fail instead of being deleted;
2. consumers check schema_version first and must reject an unknown major version;
3. v2 makes the whole task one artifact, so you can no longer assume one directory represents one write statement;
4. --compact-json only removes formatting whitespace; it does not change JSON semantics;
5. each parse generation contains only lineage.json and diagnostics.json;
6. **to correlate the same statement across contracts, use `statement_id` (and the same-basis `statement_index`), not `task_id`.**
   The v1 `task_id` suffix is numbered by write ordinal and v2's by script position, so the same
   `demo#1` points at different statements in the two artifacts, and the mismatch is silent. The v1
   top level, v2's `statement_sequence[]`, the `statement_lineage` keys, and the nested documents'
   top level now all carry the same `stmt:NNN`, which is the only correlation key the contract
   specifies.
