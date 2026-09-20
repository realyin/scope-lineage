# Changelog

## Unreleased
- A comment written back through `--metadata-patch` is redacted like every other comment.
  The patch is applied after `parse_task_lineage` has already masked the SQL author's
  comments and the ones loaded from `--schema` / `--target-ddl-metadata`, so a reviewed
  answer was the one comment reaching the artifact verbatim -- and a reviewed file is
  precisely where somebody writes a colleague's address down. The masking now happens
  where the patch is read, so every surface it writes to agrees: `column_details[]`,
  `declared_columns[]`, the `field_usage` copy, and `table_metadata.table_name_cn` /
  `table_desc`. `parse --no-redact-comments` publishes them verbatim with the rest; the
  patch's keys are untouched either way, so `unmatched` is unchanged.
- `parse --input-dir` is repeatable. A second directory used to replace the first
  silently, so a corpus spread across two trees was parsed by half and reported success.
  Every directory is now walked, in the order given, with `--include-glob` /
  `--exclude-glob` applied to each; a file named by more than one of them (a parent and
  its own subdirectory, or one tree spelled two ways) is parsed once, under the first
  directory that named it. Each file's relative parent -- and its
  `task_dependencies[].source_file` -- is taken against its own `--input-dir`.
- `parse --expansion-limit N` raises the expression-expansion substitution guard, and the
  gap that guard produces now names the number it stopped at. A task that hits the guard
  ends `partial` with an `expression_expansion_bounded` / `capacity_guard` gap, which used
  to say only which guard had fired: the reader could not tell what the limit was, nor
  that anything could be done about it. `needed_fact` now reads "the max_substitutions
  guard stopped at N, raise it with `parse --expansion-limit N`" and
  `evidence_summary.expansion_limit` carries `{guard, limit, raised_by}`. The flag
  defaults to today's constant, so an artifact produced without it is unchanged, and the
  limit applies to one call only (`parse_task_lineage(expansion_limit=...)`). The run's
  summary gains `capacity_guard=N`, the number of tasks that hit it, when any did.
- The `parse` summary says why its partial tasks are partial. Beside `partial_tasks=N` it
  now prints `partial_reasons=lineage_fact_gap:2,unsupported_statement:1`, counted from
  each task's own `analysis_status.blocking_reasons` -- one count per task per reason,
  commonest first, ties broken by name. Omitted when no task came back partial.
- The incremental fact cache stores a **projection** of each task's semantic profile
  instead of the whole thing (`corpus-cache/2`, P2). A profile is mostly the reader-facing
  half of the view -- `stages`, `confidence`, every field's step-by-step `derivation` --
  and no corpus-level merge reads any of it. Each builder now publishes the keys its merge
  does read as a `PROFILE_FIELDS_READ` list beside the code that reads them
  (`render/glossary.py`, `render/table_cards.py`, `render/ontology.py`), and `glossary`,
  `tables` and `ontology` hand their merge exactly what they cached, reused or recomputed
  alike. The artifacts are byte-identical to before, which is what the guard test proves:
  it builds each merge over the golden corpora from the full profiles and from the
  projected ones and compares. The list is part of the options digest, so editing one
  invalidates every index written under the old one; the stored facts additionally carry a
  `payload_version`, and a cache file or index of another version is recomputed rather than
  read.

## 0.3.0
- **Breaking** (derived artifacts only; the lineage contracts 1.0 / 2.0 are unchanged):
  `ontology.json` `overrides_applied.unmatched[]` entries are objects `{"key", "reason"}`
  instead of bare strings; a table card's `coverage.column_comment_ratio` is measured
  over every column the card lists (declared and used) instead of the used subset; and
  the scope `role` vocabulary gains `window`, with `dedup` narrowed to a ranking window
  whose rank column is pinned to a small constant. See the READMEs' migration section.
- Incremental corpus derivations: `--incremental` / `--no-cache` on `describe`, `tables`,
  `glossary` and `ontology` (A5). All four walk the whole corpus and re-derive every task
  on every run, however little changed since the last one -- and the expensive half of
  that work, the semantic profile built *per document*, depends on nothing but that
  document and its `diagnostics.json`. `--incremental` fingerprints exactly those bytes
  (sha256) into `<out>/.scope-lineage-corpus-index.json` and caches what each task
  contributed under `<out>/.cache/<task>.json` (`corpus-index/1`, `corpus-cache/1`), so a
  later run re-derives only the tasks whose digests moved, loads the rest from the cache,
  and drops the ones that left the corpus. What is deliberately *not* cached is the
  corpus-level merge: it always runs over every task, reused and recomputed alike, which
  is why an incremental run publishes the same bytes as a full one -- the guard test runs
  a command in full, changes one task, runs it incrementally, and compares against a fresh
  full run. Everything outside the corpus lands in one `options_sha256` and invalidates
  the whole index when it moves: the *content* of an overrides file, the `glossary.json` /
  `tables.json` read back, the format and template flags, the package version. An index or
  fact file written by another subcommand is ignored on its `command` / `doc_format`.
  `describe` has no corpus-level merge, so an unchanged task is skipped whole -- its own
  `semantic.json` / `semantic.md` are part of its fingerprint, and a deleted or edited
  output is described again; with `--metadata-patch` nothing is skipped, because
  `patch_unmatched` only means "matched nothing in the whole corpus" when every task was
  actually described. Both flags are off by default: a run that asks for nothing reads and
  writes no index, no cache, and prints no extra counter. The summary line of an
  incremental run gains `reused=N, recomputed=M, removed=K`. `ontology` also stops
  building its in-memory value dictionary from a second set of profiles: the CLI builds it
  from the cached ones instead, byte for byte the dictionary the builder built for itself.
- A table card can show what a column's values look like, from a file somebody exported
  (A6). `scope-lineage tables --samples <file-or-dir>` reads a `table,column,value[,count]`
  CSV, a directory of such CSVs, or a `samples/1` JSON, and hangs the values on the card:
  `columns[].samples[]`, `coverage.columns_sampled`, and a 样例值 column in section 3 of
  `tables/<db.table>.md`, rendered `` `'US'`、`'JP'` `` the way every other supplied value
  is. The ontology carries them across as `entities[].attributes[].samples[]`. Core still
  never connects to a database: this is a side input, exactly like `--schema` and
  `--metadata-patch`, and the doc says so where it used to say a card has no sample-value
  slot. Each column publishes at most `--samples-top` distinct values (default 5), ordered
  by `count` where the file gave counts and by file order where it did not. Every value is
  trimmed, passed through the contact-shape redaction SQL comments already get
  (`<email>` / `<phone>` / `<id>`) and cut at 64 characters with `…` -- a samples file is
  the most PII-prone input the tool ever reads, so the masking is unconditional and there
  is no flag that disables it. Table and column names are matched the way the cards
  normalize them (last two dotted segments, case ignored), so `spark_catalog.MART.t` in
  the export is the `mart.t` on the card; a key nothing answers to is published in
  `samples_applied.unmatched[]` and printed as `samples_unmatched=N` with the keys, rather
  than dropped, because a typo in a hand-made export is what its author cannot see. A
  malformed file exits 2 with one sentence. Without `--samples` every artifact is
  byte-identical to what it was before: the three keys and the markdown column appear only
  when a file was supplied. The contact-shape redaction itself moved from
  `scope.sql_comments` to the new package-root `scope_lineage.redaction` (re-exported under
  its old name, so every caller and import keeps working): the samples loader lives in
  `scope_lineage.metadata`, which by the repository's dependency direction may not import
  `scope`, and a masking rule over free text was never a SQL rule.
- `scope-lineage ontology --export linkml,shacl` writes the candidate out for an RDF
  toolchain (A4). The slot correspondence with LinkML and SHACL was already specified in
  the ontology guide and already shaped `ontology.json`; it had no exporter behind it, so
  loading a corpus into a graph meant writing one. `--export` (repeatable, or one comma
  list; nothing by default, independent of `--format`) now writes
  `<out>/ontology.linkml.yaml` -- a class per entity, a slot per attribute with its range
  mapped from the SQL type, an `identifier` for a single-column proven key and
  `unique_keys` for every other, a relation as a slot on the source class, an enum for a
  closed value set -- and `<out>/ontology.shacl.ttl`, one `sh:NodeShape` per entity with
  an `sh:property` per assertion. No tier is lost on the way out: every derived element
  carries `annotations.tier` or `sl:tier`, and an entity or attribute carries `proven`
  because the corpus read its name rather than inferring it. Two things are deliberately
  not stretched to fit and say so in the file: SHACL core has no composite uniqueness
  constraint, so `unique_per` and candidate keys are published as annotation blocks whose
  `rdfs:comment` states the limitation, and a value set the SQL never proved closed gets
  an annotation rather than an enum. The base IRI is a placeholder. Both formats are
  emitted by a small deterministic writer in `scope_lineage/render/ontology_export.py`,
  so the distribution gains **no new runtime dependency**, and
  `tests/core/fixtures/ontology/` pins one golden per format.
- A JOIN upstream of the grouping no longer costs the statement its key (B12).
  `key_confidence` dropped to `none` as soon as any grain-path fan-out risk was not
  `safe`, whatever the grain's basis -- which reads the risk against the wrong question
  for a proven basis. A GROUP BY (equally a DISTINCT, or a ranking window filtered to
  `= 1`) makes its grouping set unique *in the output* however many rows a JOIN handed
  it: the duplication inflates the aggregated values, which the metric-path risks
  already report, and adds no row to the output. The same reasoning B10 already applied
  to `single_row` now covers every proven basis: only a risk in a scope **strictly
  downstream of the grain-deciding scope** -- ROOT, or an intermediate scope between
  ROOT and the grouping, as `grain.via_scopes` orders them -- can duplicate what the
  grouping made unique. `driving_table_rows` and `unknown` are unchanged: no operation
  of theirs makes anything unique, so a fan-out anywhere on the path still costs them
  the key. The decision is published rather than silent: a non-`safe` risk ignored on
  these grounds adds 「`<scope>` 的关联放大发生在分组之前，不影响输出键唯一性」 to
  `output_shape.key_evidence[]`, and the risk itself is published exactly as before.
  Metric-path card levels still cap the result. semantic.md renders the note under the
  key line of section 2 as 「- 说明：<scope> 的关联放大发生在分组之前，不影响输出键唯一性」
  -- the reader meets 「键：目标表列 …」 and 「JOIN …：⚠ 有放大风险」 three lines apart, and
  without the sentence the second reads as a refutation of the first. The sentence itself
  lives in `semantic_text` so the builder and the renderer cannot spell it differently,
  and only that note renders there: `key_evidence` also carries notes about keys that
  never reached the target. The profile prompt says the note belongs in 使用注意 only
  where the reader would otherwise mistrust the key, and then as an explanation -- it is
  never a warning. Two golden cases gain their proven key (and with it two
  `candidate_key` field roles), and the table-card / ontology corpus follows:
  `mart.channel_summary` now carries a proven key set and its `unique_per` constraint.
- One ontology constraint per claim, not per producer statement. `unique_per` is read off
  each producer in turn, so a table two tasks write with the same key set published that
  constraint twice -- identical but for its single `evidence[]` entry, and counted twice
  in 「共 N 条约束」. Constraints sharing a (target entity, target column, kind, columns,
  values) are now merged into one, keeping the strongest `tier` among them and the union
  of their evidence in corpus order: the same merge `identity.candidate_keys` already
  performed on the very same producer facts. Two key sets are still two claims. The
  golden corpus drops from 7 constraints to 6.
- An `ontology.overrides.json` key is checked against the entity's columns before it is
  published (H1). `_apply_key_overrides` verified the entity id and nothing else, so a
  mistyped column arrived as a `confirmed` candidate key -- a typo published at the one
  tier the corpus can never produce and a reviewer can never doubt. Every column named by
  a key override (including its `scope_columns`) must now be an attribute of that entity,
  declared or used, and a relation override's columns must be on the two entities.
  `overrides_applied.unmatched` entries grew from bare strings to `{"key", "reason"}`,
  where `reason` is `unknown_entity: X` / `unknown_column: X` / `missing_columns` /
  `unknown_relation` / `unparsable_key` -- the reviewer is told which half of the string
  was wrong instead of being handed the string back.
- A confirmation can say "unique within one `dt`", and why it is believed (H2). A snapshot
  table is unique per partition and duplicated across them, which the overrides format had
  no way to express: the honest answer was "not unique", which is true and useless. A key
  override may now carry `scope_columns`, published on the confirmed candidate key and
  rendered 「在 `dt` 内唯一」. A key or relation override may carry free-text `basis` and
  `note`, published beside `confirmed_by` / `date` (`basis` as `confirmed_basis`, because
  `basis` on a cardinality is a machine token), and the card prints the three of them on
  the confirmed line. A field this release does not understand is listed in
  `overrides_applied.ignored_fields[]` instead of being dropped without a word.
- The column comments that name a key are read as evidence (H3). The catalog had already
  answered part of the identity question, in prose, and the ontology walked past it.
  A comment holding 主键 / 唯一键 / 唯一编号 / 主键id / primary key / unique
  (case-insensitive, `KEY_HINT_PHRASES`) now publishes
  `entities[].identity.declared_hints[]` and appears in section 7 of the card. Where a hint
  agrees with a candidate key, the key moves from `hypothesis` to `implied` -- a comment
  and a JOIN are two independent sources pointing at one column. Where the candidate keys
  are all hypotheses and none of them holds the hinted column, the disagreement is a
  `key_hint_conflict` finding rather than a silent choice between the two.
- Two competing identity hypotheses are a finding, not a list (H4). One entity carrying
  `[id]` and `[id, dt]`, or two disjoint key sets, published both side by side with nothing
  saying that at most one of them is the identity, and `findings` stayed empty. A strict
  subset or a disjoint pair of `hypothesis` candidate keys now produces
  `competing_candidate_keys`, carrying both key sets with their evidence, in 待人工判定 and
  in section 11 of the card.
- `ontology.json` gains `open_items[]`, and `ontology.md` a 「待人工判定清单（N 条）」 (H5).
  The open questions lived one card at a time, so a second review round could not tell what
  the first one bought. There is now one entry per hypothesis key, hypothesis relation and
  finding -- a relation once, not once per side -- each with a content-derived `open:` id
  that survives into the next round, the entity it concerns, its tier and the write-back
  key its answer is filed under, ranked findings first, then relations by task count, then
  keys. The index headline reads 「待人工判定 N 条（已确认 M 条）」 and section 11 of each
  card cites the list id. `overrides_applied` and the golden fixtures move with them.
- The ontology review prompt gets an evidence-first pass, and the skill follows it (H6).
  An Agent reviewer may now close a hypothesis itself from three named kinds of corpus
  evidence -- a producing task's proven grain, a column comment naming the key, two tasks
  joining on the same key set -- each recorded with its `basis`; everything else stays in
  the open list unchanged, and at most 8 items per round are turned into questions for a
  person. Evidence-based confirmations are uncapped. The prompt says where the task
  profiles are (`semantic.md` beside `lineage.json`) and to run `describe` first when they
  are absent. `SKILL.md` and `docs/{zh-CN,en}/ontology-doc.md` follow in parity.
- The scheduler's upstream and downstream task lists reach `task_meta` (B4). A task JSON
  registers what runs before and after this task in `meta.upstream_tasks` /
  `meta.downstream_tasks`, and contract 2.0 dropped both on the floor: `TASK_META_FIELDS`
  copies single values, and a list stringified into `"[{'task_id': ...}]"` would have been
  worse than nothing. They are now published as arrays of task names -- deduplicated, the
  exporter's order kept, a record entry read by its `task_name` and falling back to its
  `task_id` -- and an empty list publishes no key at all, because `[]` is what an exporter
  writes for "nothing registered". `owner_email` stays excluded. `describe` copies them
  with the rest of `task_meta` into `task.meta`, semantic.md's 任务元信息 line appends
  「上游任务 N 个」「下游任务 N 个」 (counts, not names), and the profile prompt now names
  both downstream sources apart: `task.meta.downstream_tasks` is scheduling registration
  and `task.downstream_consumers` is what the corpus proves. One golden case gains the two
  keys.
- Positional writing has a home in the profile's risk table (B5). 附录 C of
  `business-profile-template.md` gains a fixed row 「写入方式 | target_binding | 按位置 /
  按名 | 按位置写入时 DDL 列序变更会整体错位」, and the prompt says the `target_binding`
  finding is reported there -- and in 使用注意 only when the same statement also carries
  `alias_position_mismatch`. Templates and prompt only; no code.
- How an input is read is carried by the wording of its sentence (B7). The profile's
  「数据从哪来、到哪去」 rule now fixes it: 「直接读取」 where `inputs[].read_by_scopes`
  holds ROOT and 「经 <scope> 读取」 otherwise. The distinction 直接读物理表 vs
  上游可追溯 therefore lives in the sentence the reader reads, and self-check item 9
  checks that wording instead of asking for a slot nothing filled. Prompt and check
  template only; no code.
- A filter value's meaning can come from its own column's comment (B6).
  `meaning_candidates` only matched a comment that *contains* the value, and a value
  shorter than two characters never matched at all -- so `WHERE eff_status = '1'` against a
  column commented `0-未生效，1-生效` reached the fill-in form with no clue in it, although
  the answer was written next to the column. A column comment written as a code table is
  now read as one: the shapes `0-未生效，1-生效`, `0:未生效;1:生效`, `0=未生效,1=生效`,
  `Y 是 N 否` and `1 生效 0 未生效` (separators `，,;；|/、` and a space; a code joined to
  its meaning by `-`, `:`, `=`, `：` or a space), in every observation context (`filter_eq`,
  `filter_in`, `case_condition`, `case_then`, `constant_projection`, `union_constant`) and
  only off the observed column's own comment, source or target. The candidate's `text` is
  the half that belongs to this value, its `source` is `column_comment`, and the template
  shows it in the 注释线索 column. A space-joined pair needs a second pair to count as a
  table, so `队列编码，99 表示无效` stays one sentence. A candidate is still not a
  confirmation: `glossary --template` asks about the value exactly as before.
- Three findings stop warning about the shop's own house style (B11). On a wide corpus
  `target_binding` warned on nearly every statement (positional INSERT being the norm),
  every `metadata_conflicts` warning read 「元数据来源冲突，处理方式 kept_authoritative」
  (a fact about the metadata load, not about the task), and `nondeterministic_function`
  warned about audit columns such as `insert_time = current_timestamp()` -- a section the
  reader learns to skip. `severity` is now decided per finding rather than looked up from
  its kind: `target_binding` is `info` unless the same statement also has
  `alias_position_mismatch`; a `metadata_conflicts` resolved as `kept_authoritative` is
  `info` and every other resolution stays `warn`; `nondeterministic_function` is `info`
  when every affected field is an audit column (a constant projection whose expression is
  only the run-time call, so the value enters no filter, join, group or metric), with the
  reason published in the text as 「仅用于审计列 …」. Every text is unchanged otherwise, and
  the findings stay in `semantic.json`. Only `severity` moves in the goldens.
- Comments loaded from metadata are masked like SQL comments (E1). `redact` covered the
  SQL comments and `task_meta.description`, while the column and table comments read from
  `--schema` / `--target-ddl-metadata` -- free text a person wrote, published in the same
  artifacts -- went out verbatim. They now go through the same masking where
  `related_metadata` is assembled: `column_details[].comment`, `declared_columns[].comment`,
  `table_metadata.table_desc` / `table_name_cn`, and the copy of the same text the scope
  field usage carries (`scopes[].inputs[].used_columns[].comment`, `source_metadata`).
  `--no-redact-comments` turns both kinds off together, and the other `table_metadata` keys
  (domain, project, owner, layer, source file) are left alone -- rewriting an identifier
  corrupts a fact rather than protecting anybody.
- A SQL keyword in front of a parenthesis is no longer read as a function call (C2
  follow-up). `expression_features.functions` was collected by a regex over the
  expression's text -- `\b(name)\s*\(` -- which cannot tell `upper(a)` from `kind IN
  ('a', 'b')` or `NOT (a AND b)`, so `in` and `not` were published as functions, the
  catalog could not place them, and an ordinary `SUM(CASE WHEN k IN (...) THEN ... END)`
  came back `has_udf: true`. The scanner now skips the 38 SQL keywords that may precede a
  parenthesis (`cast` / `case` / `if` / `over` were the four it already skipped) and strips
  string literals before scanning, so a quoted value can no longer look like a call. Names
  that are both a keyword and a Spark function -- `filter`, `exists`, `transform`, `left`,
  `right`, `any`, `some` -- are still collected. Over the whole corpus only
  `expression_features.functions` (a keyword leaving the list) and `has_udf` (true to
  false, 60 of them) move; no golden fixture changes.
- A scope that only computes window functions is no longer called a `dedup` (C1). The role
  inferrer labelled every window-bearing scope `dedup`, so a CTE whose whole job is
  `SUM(total) OVER (PARTITION BY band)` was published as a deduplicating stage in
  `scopes.<id>.role`, in `scope_profile.steps[].role`, in the stage's `pattern_signature`
  and in the 「角色」 of mapping.md section 6 and semantic.md section 3. `dedup` now needs
  both halves of the pattern it was named after: a **ranking** window (`ROW_NUMBER` /
  `RANK` / `DENSE_RANK` / `NTILE`) whose output column an `=` / `<=` / `<` predicate pins
  to a small constant (<= 10), written either in that scope or in the scope that reads it
  -- a WHERE, a HAVING, or a JOIN ON clause (`LEFT JOIN d ON x.k = d.k AND d.rn = 1` is
  the same dedup, written in ON). Every other window scope gets the new role `window`. The
  grain walk, `output_shape` and the window intents (R6) are unchanged: they never read
  `role`. Two corpus scopes move, both correctly (`SUM(...) OVER` and a `LAG`).
- The function catalog knows the Spark builtins, so `expression_features.has_udf` means UDF
  (C2). The catalog was a hand-written list of ~40 names, so `HOUR`, `LAG`, `RANK`,
  `EXPLODE` and `GET_JSON_OBJECT` were all reported as UDF black boxes -- one 52-field task
  carried 148 such marks and not one of them was a UDF. It is now derived from sqlglot's
  own Spark / Spark2 / Hive function registries plus every `exp.Func` class's `sql_names()`
  (~700 names), with a curated list of the Hive/Spark builtins sqlglot registers under no
  name of their own (`percentile_approx`, `json_tuple`, `from_json`, `bround`, `pmod`,
  `hash`, `crc32`, `format_number`, `reflect`, `java_method`, `stack`, `now`, …). Names
  compare case-insensitively. A name nobody can place is still `has_udf: true`, and
  `expression_type` still reads `udf_expression` for it. Only `has_udf` moves, always from
  true to false; the render side's own builtin whitelist already hid most of these from
  semantic.md, so no 「UDF 黑盒」 line changes in the golden corpus.
- The driving table is walked on its own instead of being read off the grain. R3's grain
  walk stops at a `LATERAL VIEW`, a `UNION` or an unprovable FROM item, and the `driving`
  role and the summary sentence were read off that same stop -- so a statement whose FROM
  item was a subquery chain that exploded an event log twice published *every* input as
  `enrich` and opened with 「ROOT 直接读取 <dimension>」, pointing a profile writer at a
  lookup table. `task.driving_tables[]` now publishes the physical table every output row
  comes from, each `{table, via_scopes[], lateral_view_scopes[]}`: from ROOT down the FROM
  item only (a JOIN's right side is never one; a RIGHT JOIN swaps sides, a FULL JOIN takes
  both, a UNION takes all branches), unstopped by a LATERAL VIEW, because an explode
  multiplies the driving table's rows rather than replacing the driving table. Row *count*
  stays undecidable there; row *source* was never in doubt. `structural_summary` opens with
  「行来源 <表>（经 <scope> → <scope> 两次 LATERAL VIEW 展开）；补充 <其余表>」, `inputs[]` takes
  its `driving` from that path (a RIGHT JOIN's left side falls back to `enrich`), and a new
  role `filter_partner` names the other side of an INNER / SEMI / ANTI JOIN on the path --
  it adds columns *and* drops the driving rows it cannot match, which `enrich` denied. An
  aggregated or deduplicated shape and a MERGE publish `driving_tables: []`: there the rows
  are counted by a key set, not by a table. Contract version unchanged.
- An undecided grain offers a candidate instead of only a refusal. Where the walk ends
  `unknown` because the driving path explodes, and the grain one layer *below* the
  expansion is itself decided, `output_shape.grain.candidate` publishes the row shape that
  follows -- `{keys[], row_source, basis: "candidate", confidence: "hypothesis", reason,
  evidence[]}`, the pre-expansion keys plus each exploded column, with `row_source` naming
  the table when the pre-expansion basis is `driving_table_rows` and no keys exist to list.
  `grain.basis` stays `unknown` and `candidate_keys` / `key_confidence` are untouched: this
  is a shape the structure suggests, not one it proves. `semantic.md` reads 「未能判定…；
  候选：一行 = `<表>` 的一行 × `<展开列>`（<原因>）[推断]」, and the profile prompt and template
  tell the writer to copy that line with its `[推断]` rather than invent a grain, which is
  what the corpus measurement caught them doing. Nothing is offered for a decided grain, for
  several driving tables (a UNION's rows are a sum, not a product) or for an upstream grain
  that is itself `unknown`.
- A column an equality filter pins to one value is a constant inside its scope, and no
  longer counts as part of a unique key set. A scope whose WHERE carries a top-level AND
  conjunct `col = <scalar literal | ${…}>` -- or which passes that column through
  unchanged from a scope on the driving path that does -- is unique by the rest of its
  GROUP BY list, so `SELECT k, dt … WHERE dt = '20260815' GROUP BY k, dt` joined on `k`
  alone is `safe` rather than a fan-out `risk` -- by some margin the commonest wrong
  verdict the old reading produced. `<>`, `IN (a, b)`, `BETWEEN`, `LIKE`, a comparison
  with another column and an equality nested in an OR all still leave the column free, and
  so does a key that merely reads the pinned column inside an expression. The dropped
  columns are published as `fan_out_risks[].pinned_keys[]` (`{scope_id, column, value}`)
  and named in the reason; emptying the key set makes the right side a single row, which
  is `safe` too. `output_shape.grain.keys[]` *keeps* the pinned key, marked
  `pinned: {"value": "'20260815'"}` so the reader still sees the day the row covers, while
  `candidate_keys` / `key_confidence` read past it -- a constant is neither a key nor, when
  it is not written to the target, a `proven_unexposed` finding.
- An aggregate over an empty grouping set is one row, not an undecided grain.
  `SELECT COUNT(1) … FROM t` with no GROUP BY now publishes `grain.basis = "single_row"`
  with `grain.keys: []` and `key_confidence: "proven"` (an empty key set is trivially
  unique) instead of `group_by` / `none`, and `semantic.md` writes 「一行 = 全表汇总」 on the
  grain line with 「输出只有一行，无需键即可唯一标识」 on the key line; a table card's
  「一行代表什么」 reads 「整张输出一行（全表汇总）」. A UNION ALL of several such aggregates is
  not one row and keeps its `unknown` grain. Contract version unchanged.
- The script's header comment block reaches the artifacts. A task script usually opens with
  the lines that say what the job does, written above a `SET` preamble -- so sqlglot
  attached them to a statement nothing models, and `statement_comments` came back empty
  while `sql_comment_counts.header` read 0. The comments on every statement before the
  first modelled write are now published on that write's `statement_comments` (in source
  order, ahead of its own header block, a repeat published once) and, for the task
  document, once more as a new top-level `script_comments[]` -- always present, `[]` when
  the script opens with no such block. A comment written *between* two writes is not moved:
  it stays on the write it was written above. Redaction and `--strip-comments` behave
  exactly as they do for every other comment.
- An entity's attributes cover the whole declared table, not only the columns the corpus
  read. `related_metadata.input_tables[<table>]` and `output_tables[<table>]` gain
  `declared_columns[]` -- every column the metadata declares, in DDL order, each
  `{name, type, comment, used}` -- beside the unchanged used-subset `column_details[]`;
  the key is absent, never empty, when no metadata described the table. A table card's
  `columns[]` is now that union, each column carrying `used_in_corpus`, with
  `coverage.columns_used` / `coverage.columns_declared` (the second `null` when nothing
  declared the table); section 1 adds 「本语料用到 n/N 个字段」 and section 3 moves a tail of
  more than 20 untouched columns below the used ones. An ontology entity therefore has one
  attribute per declared column, an untouched one carrying the empty `observed_roles` the
  document always promised plus `used_in_corpus: false`, and both `ontology.md`'s entity
  table and section 7 of each card show 「属性 N（语料用到 n）」. `column_comment_ratio` is
  now over the card's whole column list, so a card showing 88 rows can no longer claim the
  coverage of the 4 the corpus happened to read; contract version unchanged.
- The task profile is two files. `business_profile.md` keeps the three body sections and a
  reader's appendix of exactly three tables (`附录 A 已确认项`, `附录 B 备查项与待填取值`,
  `附录 C 风险边界`), capped at one third of the body; the writer's own record -- input-file
  check, source-label table, inferred-item counts, self-consistency check and the 14-item
  self-check, numbering unchanged -- moves to `business_profile.check.md` from the new
  `business-profile-check-template.md`. On a real profile the appendix went from 101% of
  the body to 30%. `confirmations.py apply` is unaffected.
- The instance date is worded as the instance's, not the SQL's. Section 1's line now reads
  「本实例取数日：20260814（每次运行按实例日期替换，不是 SQL 固定日期）」, and the profile
  prompt and template say the same and forbid 「都按这一天取」 -- a reader took the old
  「取数日 20260814」 as the statement's fixed day.
- A positionally bound projection no longer borrows another column's logic block. When an
  INSERT has no column list, `target_field_binding` renames every ROOT output to the DDL
  column at that position and keeps the alias in `parsed_name`; `_populate_scope_outputs`
  then looked the alias up in an index keyed by the *bound* names, so under a real
  alias/position mismatch a DIRECT projection could carry the CASE block of a different
  position and a CASE output could carry two. Binding always runs before the blocks are
  built, so the fallback matched nothing but a different column -- removed.
- The alias the SQL wrote is now shown beside a positionally bound column. `semantic.json`
  `fields[]` gains `sql_alias` (positional binding, alias differs, name not generated);
  the field dictionary and field sections of `semantic.md`, the `glossary.md` column
  headings and the fill-in form append `（SQL 别名 `x`，按 DDL 位置写入）`, so a reader
  can tell which of a mismatched task's rows describes the expression they wrote.
- A numeric branch of a mixed CASE is a computation default, not a code. `CASE WHEN gap > 0
  THEN 0 ELSE gap END` caps a number; the glossary no longer files `0` as a candidate value
  of that column (a string branch of such a CASE is still recorded, with no closed set),
  and the `in_set` hypotheses the ontology derived from them are gone with it.
- `glossary --template-top 0` means no cap: the form asks about every askable value,
  including columns with a single one.

- The ontology lands where people read it. `ontology --out <dir>` now writes
  `<dir>/tables/<db.table>.md` -- the same card `tables` writes, under the same filename
  rule, with five sections appended (`ontology-md/1`): 身份 (candidate keys, multiplicity
  and partition columns side by side, each with a Chinese tier and its evidence ids),
  关系 (one table for outgoing and one for incoming edges, with the basis token
  translated into a sentence), 约束, 属性同义, and 待人工判定, which collects the
  table's findings *and* every `hypothesis` assertion about it and prints the write-back
  key each answer is filed under. A reader with a question about a table opens one file.
  `ontology.md` opens with a Mermaid `erDiagram` -- entities as boxes carrying their
  candidate-key columns, cardinality claims as ER symbols, `?` on an edge nobody proved
  and `!` on one two tasks disagree about -- followed by the entity, relation, constraint
  and open-item tables. Warehouse names are flattened into Mermaid identifiers, and two
  that flatten to one name keep two boxes rather than silently merging. Past 60 entities
  the diagram keeps the best-connected 60 and says how many it left out.
- A fifth tier, `confirmed`, and the round trip that produces it. `ontology --overrides
  ontology.overrides.json` merges the answers a person gave to the hypotheses the
  document asked about: a relation's cardinality, or a table's identity key -- including
  a key the corpus never guessed. A confirmed assertion carries `tier: "confirmed"`,
  `basis: "human_confirmation"` and who confirmed it when; `confirmed` is the one tier
  the corpus can never reach on its own. An override matching nothing is reported in the
  new `overrides_applied.unmatched` rather than dropped, because a typo in a reviewed
  file is exactly what its reviewer cannot see. The skill's new
  `references/ontology-review-prompt.md` is the other half: how to turn the 待人工判定
  items into a question list a business owner answers in five minutes, and the two
  write-back key forms (`关系:` / `键:`) the answers are filed under.
- `test_ontology_properties.py` states what no single rule case can: every entity,
  relation endpoint, constraint target and synonym counterpart -- table *and* column --
  appears in some `lineage.json`; every assertion carries a known tier and non-empty
  evidence whose task, statement and logic block dereference; the document is a function
  of the corpus, not of the order its files were walked in; and every table/column
  reference in a card's ontology sections resolves. The golden now pins the ER-bearing
  `ontology.md` and three merged cards beside `ontology.json`.
- The distribution boundary line in both READMEs now reads "parser + versioned contracts
  + contract-derived artifacts (including the corpus-level derivations: glossary /
  tables / ontology)". The corpus artifacts merge facts across tasks, which the old
  wording ("contract-derived renderers") did not cover, and every merged assertion still
  carries its source and its evidence.
- `scope-lineage ontology` turns a corpus into an **ontology candidate**
  (`ontology-json/1`). The table cards say what each table is; the ontology says how the
  tables relate, and it says it with the honesty the rest of the layer is built on: every
  assertion carries one of four tiers (`proven` written in the SQL, `implied` provable
  from what the SQL does, `hypothesis` assumed by an author and never proven, `conflict`
  two tasks disagreeing) plus the task, statement and logic block it was read from.
  Entities carry candidate keys (what a producer proved and what a consumer assumed, side
  by side and never merged into a "primary key"), multiplicity evidence, partition
  columns, attributes with their observed roles and synonyms. Relations come from JOIN key
  pairs -- grouped by table pair so a key pair written over a UNION does not become a
  dozen invented keys, and a CTE side pierced to its physical table with the path
  recorded -- and from UNION branch alignment. Cardinality reads a dedup before a JOIN as
  proof that the table under it holds many rows per key, a direct JOIN onto a physical
  table as the author's assumption, and another task's proven write key as the one fact a
  single statement can never reach. Constraints publish not-null (as a hypothesis, with
  the note that the task discarded the NULLs), value sets (`complete` only for a closed
  `IN` list or an exhaustive CASE), partitions and unique-per-key. `--tables` /
  `--glossary` reuse documents you already built; without them both are built in memory
  over the same corpus, byte for byte the same. No business name, no class hierarchy, no
  OWL/SHACL file: `build_ontology` and `render_ontology_index_markdown` join the public
  API, and the [guide](docs/en/ontology-doc.md) has the slots.
- A fan-out under a metric's own aggregation is no longer invisible. Once a metric anchors
  to its aggregating scope, the grain path starts there and follows driving inputs only --
  so a lookup that scope joins in, and every JOIN inside it, was judged by nobody although
  duplicating those rows inflates every number the anchor aggregates.
  `fan_out_risks[].path` gains `anchor` for exactly that subtree, judged by the same
  three-state verdict, listed in `semantic.md` under 影响指标取值的关联 beside the
  argument path, and (like the argument path) never allowed to cost the statement its
  keys: it changes a value, not a row's identity.
- `metadata_coverage.glossary` gains `enumerable_total` / `enumerable_confirmed`, and the
  A2 coverage ratio is taken over them. `values_total` counts every constant a column was
  compared against, which is the right denominator for "how much did we observe" and the
  wrong one for "how much is still unexplained": a batch date, a row limit and a `= 0`
  guard are not business vocabulary and no owner will ever confirm them, so a real corpus
  read as permanent failure. An enumerable code is a physical column's literal, seen in a
  `filter_eq` / `filter_in` / `case_then` / `union_constant` / `constant_projection`
  context, not shaped like a date, and -- when it is a bare number -- written as an `IN`
  member, a CASE label or a projected constant rather than only pinned by `=`.
- A confirmed code now reaches the line it is written on. A warehouse keeps most of its
  business codes in `WHERE queue_code IN ('01','07')`, in a join's extra condition and in
  a CASE's condition, while `fields[].value_domain` hangs off an output column -- so a
  corpus could confirm seventeen codes and the task's document would explain four fields.
  `describe --glossary` now also fills `rules[].value_meanings[]`: every code a rule pins
  a column to, attributed exactly as the dictionary attributes it (a table name only where
  one rule field carries it, a scope-level reference otherwise, and a scope-level
  reference only against entries this very task observed), `meaning` null while nobody has
  answered. `semantic.md` gains a 取值含义 column in the rule table, and a restated filter
  or join ends in `（取值：'01'＝人工队列）`. A human-confirmed term travels too:
  `inputs[].used_columns[].term_meaning` beside the column's own comment, and
  `fields[].term_meaning` only where the field has no target comment -- with its own
  `- 术语：` line, because a term is not a comment and never fills that slot.
  `metadata_coverage.glossary` now counts both halves and their deduped union
  (`values_total` / `rule_values_total` / `field_values_total`), and
  `confirmations.rule_values_confirmed` counts the rule layer apart from the field layer.
- A constant the SQL projects into one column is no longer published as a value of a
  column that merely reads it. A metric's chain legitimately contains the UNION branch
  step that writes `'contract' AS data_source` -- it is how the `SUM(CASE WHEN
  data_source = ...)` gets its flag -- and attributing every `constant` step to the
  chain's target column published those codes as values of a `decimal` amount. Each
  constant step is filed under its own `output_field`, promoted to the target column only
  while every downstream step carries it through unchanged (`DIRECT` / `UNION`). The
  describe-side declared-type guard (`'Y'` is not a value of a `decimal(15,2)`) now also
  runs where the dictionary is collected, so a corpus cannot publish the wrong fact in
  the first place.
- `glossary --template` asks about code columns instead of switches. The old ranking put
  closed sets first and then counted observations, which filled a real corpus's first
  page with `Y` / `N`, `1` / `0` and scope-level columns. The form now takes physical
  columns only, drops switches, bare numbers and date-shaped literals, skips any column
  left with fewer than two values, and ranks what is left by column -- distinct values,
  task counts, whether an `IN` list or a `CASE` puts the column in enumerated position,
  and whether its comment reads like a code column's (a ranking clue, never a meaning).
  The markdown says how much it stepped over: `排除了 N 个开关/数字/日期型取值与 M 个
  scope 级列`. `--out` stays required, and the refusal now names the reason.
- One unreadable `lineage.json` no longer ends a whole corpus run. `describe`, `render`,
  `glossary` and `tables` share one input walk, and a truncated or half-written document
  used to raise out of `main` -- hiding every other task in the tree behind the one input
  the reader cannot fix. A directory now skips that file, names it on stderr and counts it
  as `skipped_unreadable=N` in the run summary; a file the user named by name is one error
  line and exit code 2. The same guard covers each document's sibling `diagnostics.json`,
  and `--metadata-patch` reports a `tables` / `columns` section written as a list instead
  of raising an `AttributeError`.
- A value domain no longer travels between two tables that share a column name. The output
  route of `fields[].value_domain` was indexed by the bare column name, so every CASE label
  any task ever wrote into a `status` was published as a value of every other task's
  `status`. It is keyed by target table (normalized by the dotted-suffix rule) and column
  now; a CASE inside a CTE, which names no table, still speaks to the column it produces in
  its own statement.
- A fan-out on a metric's **argument** path no longer costs a statement its keys. It
  duplicates the rows a `SUM` reads -- a wrong value -- without duplicating a row of the
  output, so `candidate_keys` / `key_confidence` are decided from the `path: "grain"` risks
  alone. The argument risk is still published; a `GROUP BY` whose own path is clean now
  reads `proven` instead of `none`.
- A projection the author did not alias is no longer reported as an alias/DDL column
  mismatch. `SELECT a, 0, current_date()` bound positionally leaves sqlglot's `_col_N`
  placeholder in `parsed_column`, and comparing that string to the DDL name accused every
  statement writing a constant of putting data in the wrong columns. The contract's
  `name_is_generated` decides where it is published, the placeholder shape where it is not.
- `describe --glossary` validates the document it was given: a missing or unreadable file
  exits 2, one that does not declare `doc_format: "glossary-json/1"` exits 1. Handing it
  `glossary.overrides.json` -- the neighbouring line in every runbook -- used to be accepted
  silently and produce a profile with no value domains, which reads like a corpus that
  observed nothing.
- Table-name suffix merging stops at the bare name. `ods.t` and `dwd.t` are two tables, and
  one script that wrote an unqualified `t` used to merge every `<db>.t` in the corpus into a
  single card -- publishing one table's producer as another's. A bare name now joins a card
  only when exactly one qualified table matches it; when several do it gets its own card
  carrying the new `ambiguous_bare_name` finding.
- `related_metadata.output_tables[].metadata_complete` answers about the columns rather than
  about the lookup. A target description that knows the table but agrees with none of the
  written column names leaves `column_details[]` empty, and empty was published as
  `metadata_complete: true`. It is `false` now, `metadata_source` still names which side
  answered, and the additive `metadata_note: "no_output_column_matched"` separates "the DDL
  was read and matched nothing" from "nobody supplied metadata".
- Comment redaction stops masking 15- and 18-digit serial numbers as ID numbers. Length was
  never the shape: an ID number carries a six-digit region code that does not start with a
  zero followed by a real birth date, and a run whose middle digits are not a legal date is
  left as the author wrote it.
- `describe --tables` decides a JOIN's fan-out in one place. The table-card proof used to be
  applied after the profile was finished, so there were two implementations of "is this JOIN
  safe" and everything the build derives from the shape -- a field's `candidate_key` role,
  the `inferred_items` counts -- still saw the answer from before the card.
  `build_semantic_profile(..., table_cards=...)` is now the only path, and
  `apply_table_cards` folds in the narrative only.
- Stop calling a task instance's own date a governance problem. `confidence.findings[]`
  now carries a `severity`: `warn` for the leads somebody has to act on, `info` for the
  facts that need no action -- `hardcoded_date_literal`, `partition_literal_mismatch` and
  `table_comment_missing`. Section 6 lists only the `warn` ones and counts the rest in a
  single 「信息项：N」 line, so the one lead that matters is no longer buried among five
  that need nothing. A metric's date filter pinned to a day-shaped literal reads
  `kind: "instance_date"` and renders as 「实例日期 20260814」, the two sides of a metric
  disagreeing now state which way round they go (「另一侧取前 1 日」) instead of being
  scored as a defect, and section 1 publishes the days themselves as
  `task.instance_dates[]` and a 取数日 line.
- `scope-lineage glossary --template <path.md>` writes the 取值含义 fill-in form the
  profile's open-questions list used to ask one code at a time: the markdown a person
  fills in plus the same-named `.json` that `--overrides` reads straight back. It ranks
  proven closed sets first, then by how much of the corpus rests on the value, and leaves
  out match patterns, day literals, bare numbers with no enumerated context and anything
  already confirmed; `--template-top` (default 20) caps how many values it asks about. An
  overrides key whose meaning is still an empty string is now counted under
  `overrides_applied.blank` and skipped, rather than written in as a confirmed empty
  meaning.
- Profile prompt: the open-questions list drops from 15 items to **5**, and asks only what
  can change a number or a meaning -- column-position mismatches, a comment that contradicts
  the derivation chain, an unproven key under a fan-out risk (asked once for all of them),
  and misnamed fields. Whether a hardcoded date is substituted by the scheduler, what a code
  means, and whether a key is unique in business terms are no longer asked at all; the
  overflow candidates and every value still missing a meaning go to a new appendix A2b that
  points at `glossary.overrides.template.md`.
- Stop the value dictionary from lending a column somebody else's values. A target column's
  `value_domain` now holds only what that column itself outputs -- a CASE's THEN / ELSE
  labels, a UNION or plain constant projection -- plus the `=` / `IN` observations of a
  source column the value reaches it from unchanged at *every* step (the field's own
  transform and that source's, both `DIRECT` / `UNION`). A CASE **condition**'s constant
  belongs to the column being tested, so `WHEN flag = 'N' THEN amount` no longer publishes
  `'N'` as a value of the amount column, and a numeric or temporal target column admits
  same-typed literals only. `closed_set` became the **column's** verdict rather than each
  value's, so one field can no longer read "this value is proven closed, that one is not"
  out of a single exhaustive CASE; it is `true` only where that column's own last-step CASE
  is exhaustive or a pass-through source carries a closed `IN` list. Values are stored in
  one spelling -- `value` with the SQL quotes stripped, the author's literal beside it in
  the new `sql_literal`, which is what the markdown and the overrides examples show, while
  an overrides key may still be written either way.
- Let a table card decide a fan-out. One statement can never prove a physical table unique
  by its join keys, so a JOIN onto one stopped at `unknown` even where the same document's
  `inputs[].card` already carried another task's proof that the table is written one row
  per exactly those columns. `describe --tables` now re-decides such a risk from the card
  (`status: "safe"`, a reason naming the producing task, and `basis: "table_card"`) and
  recomputes `candidate_keys`, `unexposed_keys`, `key_evidence` and `key_confidence` with
  it; a card offering only candidate keys says so in the reason and caps the whole claim at
  `candidate`. Without `--tables` nothing changes, byte for byte. An input card whose
  producer could not decide its own grain now says so by name instead of opening with
  「未知」, which read as a missing value beside 「本语料内无生产任务」.
- Keep commented-out SQL out of a field's meaning. A `--` comment whose body parses into a
  SQL shape and carries an ASCII SQL word (`cast(null as string) as x`) records what the
  code used to do, not what the column means, so it no longer reaches
  `fields[].sql_comments` or the `；注释：` tail of the field's sentence; the verbatim text
  stays in the contract's own `comments`. Anything the test cannot prove is SQL stays a
  note.
- Profile prompt: the semantic card's length cap scales with the number of input tables
  (`600 + 40 × max(0, inputs − 3)`, capped at 900) so the mandatory coverage and the word
  limit stop contradicting each other on a multi-input task; warning counts are stated to
  be the union of `statement_diagnostics[].warnings` and the top-level list, because an
  empty top-level array is not "no warnings"; and the `- 证据：` line of an open question is
  exempted from the "no structural words in the body" rule, since it is a pointer for the
  reviewer rather than a sentence for the business owner.
- Close the loop on the open-questions list: an answer now comes back as a fact instead of
  being asked again. New `metadata-patch/1` file -- `{"tables": {"db.t": {…}}, "columns":
  {"db.t.col": {"comment": …}}}`, the same vocabulary rich JSON metadata uses -- carries the
  comments a human confirmed, without writing to anybody's catalog. `parse --metadata-patch`
  (repeatable) applies it to each statement document on its way to disk and
  `describe --metadata-patch` applies it in memory to a `lineage.json` already written, so an
  answer lands without re-parsing a corpus; both go through one function, so the two paths
  produce a byte-identical `semantic.json`, `lineage_digest` included, and the artifact on
  disk is never rewritten by a derived view. Every patched entry says so -- `comment_source:
  "patch"` on a column (in `related_metadata` and in the `field_usage` mirror),
  `table_metadata.patch_applied: true` on a table -- and a key that matches no table or column
  is reported as `unmatched`, never dropped. The semantic view sources every comment it
  publishes (`fields[].target_comment_source`, `inputs[].comment_source`, each absent when
  there is no comment to source) and counts what has been answered in
  `confidence.confirmations` (`values_confirmed` / `terms_confirmed` / `columns_patched` /
  `tables_patched`, always present) and `confidence.metadata_coverage.patch`. The skill gains
  `scripts/confirmations.py apply <business_profile.md> --by <name>`, which reads the answers
  the business owner wrote on each item's new `- 答案：` line and routes them by the item's own
  回写目标 line -- `术语` / `值域` into `glossary.overrides.json`, `字段注释` / `表注释` into
  `metadata-patch.json` -- merging without ever overwriting an entry somebody already
  confirmed, skipping and counting unanswered items, and writing nothing under `--dry-run`.
  The profile prompt must no longer generate a `Q` for an item the skeleton already shows as
  confirmed; those move to appendix A2a, and the field dictionary's confidence column reads
  `事实（已确认）`.
- Say what a table *is*, not only what columns it has. Rich JSON metadata carries table-level
  facts -- a readable/Chinese name, a description, the business domain and its path, the
  project and its code, the owner, the storage layer, the physical type and whether the table
  is partitioned -- and the loader dropped every one of them, so `related_metadata` never
  published a table-level fact and table cards had no table comment to show. They now travel end to end: one vocabulary-neutral
  normalizer reads them from a rich JSON document, a rich JSON directory, the aggregate
  `{"tables": […]}` shape, the `{"db.table": {…}}` shorthand and the target table's own
  DDL/Schema export (`TargetTableMetadata.table_detail`), into `SchemaMap.table_details` and on
  into `related_metadata.input_tables[*].table_metadata` / `output_tables[*].table_metadata`
  (an open, additive object -- see `lineage.json` §12.2). `--schema-fallback` fills facts the
  authoritative source lacks *per fact*, never overriding one it has. The semantic view reads
  the comment as `table_name_cn` → `table_desc` → `comment` → `table_comment`, `inputs[]` gains
  `domain` / `project` / `owner` / `layer` (always present, `null` when the metadata is silent),
  `task` gains `target_table_domain` / `target_table_project` / `target_table_owner`, section 1
  names the target's business placement, and a field summary's source note can finally fall back
  to the table's comment. Table cards gain the same four facts, a real `coverage.table_comment`,
  a 业务域 column in `tables.md` and a 业务归属 line in each card's section 1. Privacy is part of
  the rule, not an aside: any value containing `@` is refused wherever it appears (the export's
  `tbl_pic` contact address among them), and timestamps and quality rates are not table facts.
- Answer "what does `'PAID'` mean" with evidence instead of a guess. New
  `scope-lineage glossary --lineage <corpus> --out <dir>` aggregates a corpus into
  `glossary.json` (`glossary-json/1`) and `glossary.md`: `terms[]` merges column comments
  across tables by column name, keeping two different readings of one name side by side as
  a `conflict` rather than deciding for the authors; `values[]` collects every constant the
  SQL compares a column against -- `filter_eq` / `filter_neq` / `filter_in` / `filter_rlike`,
  a CASE's `case_condition` and `case_then`, `union_constant` / `constant_projection`
  projections and a JOIN's `join_condition` -- with the tasks and evidence ids behind each;
  `parameters[]` keeps `${bizdate}` and `date_sub(current_date(), 1)` out of the value list,
  because a substitution is not a value. `closed_set` is claimed only for an `IN` list or a
  CASE whose THEN and ELSE are all constants, and only when the corpus's claims agree -- an
  observed set is a floor, not a ceiling. A regex pattern stays whole rather than being split
  on `|`, and a value is attributed to a physical table only when exactly one of the rule's
  fields carries that name, otherwise it is published as a `logical` scope-level reference.
  `meaning` has exactly two sources: a reviewed `--overrides` file (`{column: …}` and
  `{column='VALUE': …}`, qualified or bare, with unmatched keys reported under
  `overrides_applied.unmatched` rather than dropped) and `meaning_candidates`, which are
  comments that *literally* contain the value (never a value shorter than two characters).
  `describe` consumes it: `fields[].value_domain[]` carries `{value, kind, seen_in,
  closed_set, meaning}`, `semantic.md` section 5 gains a `- 取值：` line, and
  `confidence.metadata_coverage.glossary` counts `{values_total, confirmed, candidate}`.
  Without `--glossary` the value domain still appears, holding only what that one statement
  proves with every meaning `null`; only a *confirmed* meaning is ever appended to a field's
  one-sentence summary. Public API: `build_glossary`, `render_glossary_markdown`. Documented
  in `docs/{zh-CN,en}/glossary-doc.md`.
- Publish what a *corpus* knows about a table, which no single task can say. New
  `scope-lineage tables --lineage <corpus> --out <dir>` builds one semantic profile per
  task and merges the producing and consuming sides of the same table into
  `tables.json` (`tables-json/1`), a `tables.md` index, and one `tables/<db.table>.md`
  card per table: what the table is, what one row represents (the producing statement's
  own grain, keys and key confidence), its columns (the union of written fields and read
  columns, with per-usage consumer counts), who writes it with what partition and
  cadence, who reads it and how, and four governance findings -- `multiple_producers`,
  `producer_key_conflict`, `never_consumed_in_corpus`, `never_produced_in_corpus`. Names
  differing only in catalog qualification are one table (the dotted-suffix rule the query
  helper uses), with the most qualified spelling as the primary name and the rest under
  `aliases`; session-scoped relations and `directory:` writes never become a table.
  `describe --tables <tables.json>` then lets a task profile cite the corpus:
  `inputs[].card` carries the upstream task's grain sentence, candidate keys, key
  confidence and cadence, `task.downstream_consumers` names who reads the target table,
  and `confidence.metadata_coverage.table_cards` counts how much of the input side a card
  could answer. Without `--tables` those three keys do not appear and `semantic.json` /
  `semantic.md` are byte-identical to before. Public API:
  `build_table_cards`, `render_table_index_markdown`, `render_table_card_markdown`,
  `apply_table_cards`, `table_card_filename`. Documented in
  `docs/{zh-CN,en}/tables-doc.md`.
- Carry the SQL author's own words into the contract. The statement document gains
  `statement_comments[]` (the header block, always present so an empty list can mean "this
  statement has none"), and `scopes[].outputs[].comments[]` /
  `scopes[].logic_blocks[].comments[]` appear where the author wrote one. Quoted strings
  and backticked identifiers are not scanned, so `WHERE note = '-- not a comment'` stays
  data. Task metadata is carried too: a task JSON's `meta` becomes the 2.0 top-level
  `task_meta` under neutral key names, every value a string or `null`, unknown keys
  ignored -- and **`owner_email` excluded by name**, since a person's contact address
  explains nothing about the data and artifacts travel between systems. `parse
  --strip-comments` drops the comments entirely, including the inline copies inside
  rendered expressions, for the cases where a comment must not leave the machine; the
  public `parse_task_lineage(..., task_meta=, strip_comments=)` exposes both.
  `describe` consumes all of it: `task.header_comments` and `task.meta`,
  `fields[].sql_comments` collected along the derivation chain,
  `rules[].sql_comments` and `stages[].actions[].sql_comments`, a
  `metric_spec.refresh` finally filled from the task's schedule instead of published as
  `null`, and `confidence.metadata_coverage.sql_comment_counts`. In `semantic.md` a
  comment is quoted with its own `SQL注释` label -- section 1 as a blockquote under the
  task-metadata line, section 3 at the end of an action line, section 4 as its own column,
  section 5 as a `- 注释：` line -- and never inside a code span, because a code span in
  that document means verbatim SQL. Documented in `docs/{zh-CN,en}/lineage-json.md` §18,
  `task-lineage-v2.md`, `input-formats.md` and `semantic-doc.md`. Since a comment is
  where a person writes down how to reach another person, contact details inside one are
  **masked by default**: an email becomes `<email>`, a mainland-China or international
  phone number `<phone>`, an 18- or 15-digit ID number `<id>`, in the collected
  `comments` keys, in the inline copy inside a rendered `raw_expression`, and in
  `task_meta.description` -- the rest of the sentence is kept, and the SQL expression
  itself is never rewritten. No key is added for it. It is shape matching, so it is
  neither exhaustive nor certain; `parse --no-redact-comments` publishes the text
  verbatim, and `--strip-comments` remains the complete switch.
- Close six determinable gaps an Agent hit while writing a business profile from the
  skeleton. `metric_spec.unit.hint` now reads a date difference's own unit -- `DATEDIFF`
  is `天`, `MONTHS_BETWEEN` is `月`, `UNIX_TIMESTAMP(a) - UNIX_TIMESTAMP(b)` is `秒` --
  recursively through a MAX / MIN / AVG / SUM wrapper. A new `nondeterministic_function`
  finding names the fields and rules whose value follows `CURRENT_TIMESTAMP` /
  `CURRENT_DATE` / `NOW()` / a bare `UNIX_TIMESTAMP()` / `RAND` / `UUID` instead of the
  data date, so a backfill of an old day does not reproduce it; the metrics among them
  carry `metric_spec.time_dependent` and say so on the card's 时间范围 line. A column
  pinned to two different literals across the grain and argument paths marks both
  `time_range[]` entries `mismatch`, the markdown states the gap in days when both are
  written as plain days, and the `partition_literal_mismatch` finding's `evidence[]` now
  points at the affected metrics' mapping chains. R7's `driving` role reaches below ROOT:
  a physical table that is a non-ROOT scope's own FROM item is driving when that scope
  sits on ROOT's driving path or supplies ROOT's GROUP BY keys, so a table every grouping
  key comes from is no longer labelled `enrich`. `fan_out_risks[]` gains a `path` and now
  also judges the JOINs on a metric's argument path -- they leave the row count alone and
  inflate the number instead -- which `semantic.md` section 2 lists under its own
  「影响指标取值的关联」 heading. Section 6 points at the `warnings.md` that
  `scope-lineage render` writes, since `describe` does not write one. Documented in
  `docs/{zh-CN,en}/semantic-doc.md`.
- Give every metric field a definition card. `fields[].metric_spec` publishes the seven
  slots a reader asks a number for -- what is counted (`subject`), over which dates
  (`time_range[]`), under which conditions (`inclusion[]`), aggregated how
  (`aggregation`, with each GROUP BY key's target column), in what unit (`unit`), what a
  missing value becomes (`null_handling`), and how often it refreshes (`refresh`, always
  `null` until the contract carries task metadata) -- plus `post_aggregation[]` and the
  evidence ids each slot was read from. It appears on `measure` / `event_time` fields and
  on any field whose chain crosses an aggregate step. Every slot is read along the
  *aggregation path*: the aggregating scope and the scopes its FROM item descends into, so
  a filter sitting on a bypass JOIN's right side narrows that lookup and never the metric,
  and a slot the path cannot prove is published empty or `null` rather than filled with a
  plausible sentence. `semantic.md` section 5 renders the card as a fixed seven-line block
  under each metric field's one-sentence meaning, and the full field list gains a `口径`
  column compressing the call and the time range. Documented in
  `docs/{zh-CN,en}/semantic-doc.md`.
- Add `scope-lineage describe`: a deterministic task-semantic skeleton derived from the
  contract, written as `semantic.json` (`semantic-json/1`) and its rendering `semantic.md`
  (`semantic-md/1`) beside each `lineage.json`, the same input handling as `render`
  (one file or a tree, `--out` mirroring, sibling `diagnostics.json`, statement and task
  documents), plus `--format json,md` and `--sections` (the seven fixed sections, with
  `fields_table` keeping section 5's table without the per-field subsections). It answers
  "what does this task do, what does one output row represent, what does each field mean":
  output shape and grain with per-JOIN fan-out risk, the stage-by-stage processing chain,
  a recursive grain walk that pierces window, projection and JOIN layers down to the scope
  that sets the row count (`grain.basis` adds `distinct`, `grain.via_scopes` records the
  whole path, `grain.keys[]` holds one *logical* key per GROUP BY / PARTITION BY item with
  the physical columns it pierces to, `candidate_keys[]` names the **target columns** those
  keys are written to, and `output_shape.key_confidence` says whether the key set is
  `proven`, `proven_unexposed` (proven keys the target never receives, so its columns
  cannot identify a row), a `candidate`, or nothing the structure proves),
  a flat rule list, and per-field semantics carrying the target column's own comment. Every
  line is tagged `SQL事实` / `元数据事实` / `结构推断` with an evidence id back into the
  contract; business entity naming, business table types, and column-name guessing stay out
  of Core by design (an Agent generates the business profile from
  `skills/scope-lineage/references/semantic-profile-prompt.md`). Documented in
  `docs/{zh-CN,en}/semantic-doc.md`.
- Make the semantic skeleton say what the SQL wrote, not what it pierces to. A GROUP BY
  item and a JOIN key are now named logically: an aggregate reads "按 segment 分组聚合"
  rather than naming the four physical columns one key fans out to across a UNION, and a
  join states its key once (`rules[].key_pairs[]` is the scope-level short form
  mapping.md's section 6 already uses, with the pierced cross product beside it under the
  new `physical_key_pairs[]`); the physical fact stays in `actions[].fields[]`, and the
  fan-out proof still compares physical key sets. Adds the `derive` action for the plain
  expression derivations (`a - b AS delta`) that are not logic blocks and were therefore
  invisible in `stages[]`, the governance finding `alias_position_mismatch` (a positional
  write whose SQL aliases disagree with the DDL columns at those positions — Core counted
  them, nothing said so), `derivation[].branch` for the steps that happen inside a UNION
  branch, and a `fields[].summary` that groups those branches as the alternatives they are
  instead of chaining them with "再". Restatements now recurse into a call's argument
  (`MAX(DATEDIFF(a, b))` reads as a maximum *of a date difference*), builtins that
  `scope/function_catalog.py` does not list (`HOUR`, `RANK`, `LAG`, …) are no longer
  reported as "UDF 黑盒" — sqlglot's own grammar is the whitelist — and `generated_sources`
  render as `常量 'F_00'` instead of a Python repr. `confidence.inferred_items` is now
  counted by path pattern. In `semantic.md`, folded stage groups carry every member's
  topological number, a scope's derivations fold past eight, same-shaped rule families
  (identical once numeric literals become `N`) fold into one templated row, runs of
  value-carrying derivation steps fold into one line, and a source-boundary line that
  repeats the stage's own inputs or the previous stage's is dropped. `semantic.json` still
  folds nothing.
- Export `build_semantic_profile` and `render_semantic_markdown` from the public API, next
  to the mapping renderers.
- Carry the target table's own column comments and types into `lineage.json`. When
  `--schema` does not know the target, `related_metadata.output_tables[*].column_details[]`
  now falls back to the DDL/Schema export supplied through `--target-ddl-metadata`
  (restricted, as on the schema path, to the columns the statement actually writes), and
  the entry reports `metadata_complete: true` instead of describing a fully supplied run
  as metadata-free. Table-level `full_table_name`/`source_file`/`structure_source` travel
  in `table_metadata`. The additive key `metadata_source` (`schema` | `target_ddl`, absent
  when neither side described the table) names which input answered, so a null comment and
  an authoritative empty one are no longer the same document. `--schema` stays
  authoritative when it knows the target: the two descriptions are never interleaved.

## 0.2.6
- List, under the mapping.md section 2 table, the predicates applied to each source
  table: the contract's AND-split WHERE conjuncts and the non-key part of JOIN ON,
  regrouped by physical table, each line naming where it occurred
  (`WHERE @ <scope>` / `JOIN ON @ <scope>`; the same predicate repeated across scopes,
  as in every branch of a UNION, is one line listing up to three occurrences or
  `等 N 处`). A predicate on an intermediate result's
  column is attributed to a table only through a DIRECT single-source pass-through
  (annotated `经 <scope>.<column> 直传`); window, aggregate, UNION and expression
  columns are never guessed and are listed separately, subquery-internal references
  stay with the subquery's own WHERE, cross-table predicates appear under every table
  they touch, and HAVING stays in section 6. Renderer only — `lineage.json` is unchanged.

## 0.2.5
- Stop reading `COUNT(*)` as "uses every column". Source-free row-count/row-position
  expressions (`COUNT(*)`, `COUNT(1)`, `ROW_NUMBER()`…) now emit source refs marked
  `rowset: true` — a row-set dependency that reads no columns — instead of star refs
  indistinguishable from the unexpandable-`SELECT *` fallback. A task reading a handful
  of fields from a wide table no longer reports every column as used, end-to-end lineage publishes
  `rowset_sources` instead of fabricated `column='*'` physical reads (matching the
  expression-resolution layer it used to contradict, `mixed` when combined with real
  columns), and literal aggregates such as `SUM(1)`/`MAX('x')` fall through to their
  established generated classification instead of gaining row-set stars.
- Split mapping.md section 2 into honest columns: `表列数（元数据）` (the table's full
  schema width, from the new additive `related_metadata` key `table_column_count`) and
  `使用列数` (the used subset — previously the only number shown, under a header that
  claimed to be the table width). Tables referenced only through row-set dependencies
  keep their metadata entry with zero used columns.
- Report the exact difference count in the differential comparison harness: the
  tree walk was capped at 40 and a run silently presented an 88-difference change as
  "41 differences", dropping whole categories from the report.
- Add a `trace` subcommand to the bundled lineage query helper: join tasks by table
  name across an artifact corpus and walk N hops upstream and/or downstream, each edge
  citing the task and artifact that proves it. First run writes an incremental routing
  index at the corpus root (refreshed by file fingerprint; a disposable cache — the
  artifacts stay the single source of truth). Hive-style and catalog-qualified names
  for the same table are joined by dotted-suffix equivalence at every hop, `chain` and
  `impact` gain the same under-qualified fallback, and cycles (MERGE self-references,
  mutually fed tables) are reported once per direction.

## 0.2.4
- Add a pre-parse metadata coverage gate: `scope-lineage parse --metadata-preflight`
  reports every referenced table missing from the supplied schema (with the tasks
  referencing it), writes a deterministic `metadata_gaps.json` manifest into `--out`,
  produces no lineage artifacts, and returns non-zero when gaps exist — so chaining
  `preflight && parse` stops for a decision before parsing with incomplete metadata.
  A normal batch parse that finds gaps writes the same manifest next to its artifacts
  and prints a pointer. Coverage aggregates the per-task
  `diagnostics.metadata_coverage` fact; nothing derives it a second way. Motivated by
  two investigations in a row where an incomplete schema produced AMBIGUOUS
  attributions that were first mistaken for parser or SQL defects.
- Cover unbound anonymous projections in field mapping chains. `end_to_end_lineage`
  emits an entry for every output the statement writes, but the chain layer skipped
  outputs whose name is not a reliable target column (a generated `_col_N`, a purely
  numeric alias), so mapping.md showed a section-4 row with no section-5 steps. Chains
  now cover exactly the population end-to-end covers, with `final_output_fields` left
  empty rather than fabricating a target column; section-5 titles render such fields as
  `（匿名投影，未绑定目标列）` / `（未绑定目标列）` instead of composing a physical
  field id the target table never declared. A new additive contract key
  `name_is_generated: true` (on end-to-end entries and chains, present only when true)
  says the published name is a parser-generated placeholder — a fact that previously
  never left the parser, so consumers could not tell `_col_6` from a real column of
  that name. Documents containing such outputs renumber later `mc:NNN` ids.
- Add contract invariant validation: `validate_contract_invariants` checks that
  independently derived layers of one document agree with each other — chain-layer vs
  end-to-end trace completeness, physical sources vs `source_tables` containment,
  sentinel-value semantics (every rule measured over the full corpus, and the sweep
  demonstrably reports the pre-fix AMBIGUOUS defect and nothing else). A new
  `scope-lineage validate --lineage <file|dir>` command audits existing artifacts with
  schema + cross-reference + invariant checks in one pass, and an architecture test
  keeps the whole example/golden corpus at zero violations so the next cross-layer
  contradiction fails a test the day it is introduced.
- Mark field mapping chains rooted in an `AMBIGUOUS` ref as `trace_status: "incomplete"`
  (with an `ambiguous_unqualified:<column>` missing reason), matching the end-to-end layer
  that already reported `trace_complete: false` for the same field. Previously a chain whose
  expression expansion resolved through sqlglot's guessed qualification claimed completeness
  for a field whose root attribution was never proven — the two layers of one document
  contradicted each other. mapping.md now also explains the sentinel instead of rendering it
  like a table: the section 6 input list labels it `AMBIGUOUS（⚠ 裸列多源歧义）`, and the
  section 7 diagram styles the node amber with a matching legend entry.
- Annotate joins that read the statement's own target table with
  `join_relation_detail.target_self_reference`. When both the target partition and the
  reference's partition predicate are literal dates the day offset is stated and proven
  (`partition_offset_days`, a negative offset being the classic carry-forward shape);
  otherwise the reference stays `offset_proven: false` rather than guessed. mapping.md
  section 6 renders the annotation under the join.
- Add a `lineage_digest` key to the mapping.md front matter: a 16-hex content digest of the
  source lineage document. Same input still renders byte-identically; a consumer recomputes
  the digest (`lineage_document_digest`) to confirm which `lineage.json` a document came from.
- Use Chinese list punctuation consistently in scope profile summaries (`、` between table
  names, spaced `等 N 张物理表`), matching the rest of the rendered documents.

## 0.2.3
- Split join equality keys at every hop of a chained self-join. The left side of each hop now
  matches any alias already joined ahead of it, not only the first FROM alias, so multi-level
  hierarchy joins keep per-hop key pairs instead of degrading to unsplit verbatim conditions.
  Joins whose keys genuinely cannot be split (expression-level conditions, `ON TRUE`) now emit
  a `join_keys_not_split` warning instead of leaving the gap silent.
- State the grain on every mapping.md transformation step as `粒度=changed/preserved/unknown`.
  A provably preserved grain and an unknown one were both rendered as no label; the three
  contract values now stay distinguishable, within the existing step-line grammar.
- Count parse warnings per type in mapping.md section 9 instead of one undifferentiated
  "advisory" total, and mark section 8 as declared scheduler dependencies — with a fixed note
  pointing at sections 2/4 for actual lineage consumption and one task per line.
- Keep the scope-graph mermaid diagram readable in dark themes by pinning explicit text colors
  with the light node fills, and add a legend line. Render partition specs as JSON instead of a
  Python dict repr, merge the section 6 input line when all inputs are physical tables, and
  label the binding summary count as corrected columns.
- Keep lineage uncertainty consistent across diagnostics, mapping chains, statement-level
  end-to-end lineage, and task-level end-to-end lineage. A root-impact fact gap now marks only
  the target fields it can actually affect, rather than leaving statement views complete or
  making every field in the task incomplete.
- Complete several evidence-backed expression-resolution paths involving repeated aliases,
  lateral-view outputs, window arithmetic, and consumers revisited after a late expansion. When
  an expansion is declined by the capacity guard, diagnostics now report that precise bounded
  condition instead of a generic unresolved alias.
- Treat a parenthesized wildcard projection such as `DISTINCT(*)` as the same column set as
  `DISTINCT *`. It now expands through physical schemas, subqueries, and UNION branches instead
  of becoming a source-free expression or an unexpanded downstream wildcard.
- Distinguish unsupported statements from unsupported data changes in task analysis blockers.
  Read-only SELECT/UNION statements remain partial but report `unsupported_statement`; mutating
  DDL and unsupported row changes continue to report `unsupported_data_change`.
- Add repeatable `--include-glob` and `--exclude-glob` filters for directory parsing. The default
  remains fail-visible recursive JSON discovery, while callers with mixed export directories can
  declare the task-file boundary explicitly.
- Make the bundled lineage query helper read task diagnostic summaries accurately, stream the
  fields needed by `summary`, process corpus files one at a time, and bound chain expression
  previews by default. `--expanded` retains access to the full expression evidence.

## 0.2.2
- Reject task identifiers that could escape the requested output directory, normalize output
  collision checks, and keep task dependency source labels free of machine-local paths.
- Publish each task's `lineage.json` and `diagnostics.json` as one directory generation. A failed
  or interrupted replacement now leaves the previous complete pair available instead of exposing
  files from different parses.
- Validate cross-references inside every embedded statement document, including statement identity,
  index, scope graph, and column-source references, before writing either task artifact.
- Add privacy gates for repository text, commit messages, pull-request and release descriptions,
  and built distributions. Releases now start from a reviewed draft, require the private terms
  list, and publish only after the tag, archive, and public text checks succeed.
- Clarify the updated path, validation, and paired-write behavior in both documentation trees.

## 0.2.1
- `scope-lineage --version` reports the installed package version. Agent integrations
  (and any script) can now probe the version deterministically instead of inferring it
  from flag behavior.
- The repository ships an agent-neutral skill under `skills/scope-lineage/` -- metadata
  wiring rules, artifact reading paths, honesty rules, and a targeted extraction script
  (`query.py summary/chain/impact`) -- with a Claude Code plugin shell and native-install
  routes for Codex and other Agent Skills hosts. Delivered via git, deliberately NOT via
  this package: `skills/` and `.claude-plugin/` are excluded from the distribution and
  the boundary test enforces it. See the README's "AI agent integration" section.
- Docs caught up with 0.2.0 across the Chinese guides: contract selection is reframed as
  statement-level vs task-level reading, the contract references introduce themselves as
  the embedded statement shapes, and stale `write_lineage` / per-write output-directory
  examples are gone.

## 0.2.0
- **Breaking**: the task contract (2.0) is now the only output mode, and the standalone
  contract-1.0 artifact is removed in the same release -- the planned deprecation window
  collapsed when the sole downstream consumer confirmed its own retirement.
  `write_lineage` is gone from the API; the CLI accepts `--contract-version 2.0` only
  (the flag stays one release so a `1.0` request fails with a clear choices error). The
  statement-document SHAPE is not retired: every `statement_lineage` entry keeps it,
  `lineage.schema.json` / `diagnostics.schema.json` remain as its schemas, the converters
  (`to_lineage_dict` / `to_lineage_json` / `to_dict` / `to_json`) stay public, and the
  golden statement corpus now validates every embedded entry against that schema.
- **Breaking**: removed four facade exports with no remaining consumer
  (`build_end_to_end_lineage`, `build_scope_profile`, `materialize_schema`,
  `table_details_for_table`) after the downstream consumer's retirement was confirmed.
  Their implementations stay internal to the packages that own them.
- `render` / `render_mapping_markdown` accept contract-2.0 task documents and render one
  mapping section per statement, in `statement_sequence` order; a single statement
  document still renders as before. Unknown schema versions are rejected.
- **Breaking**: removed the v1-era result types `Column`, `ColumnRef`, `JoinKey`,
  `LineageResult`, and `Unresolved` from the public API. Nothing inside the package, the test
  suite, or the approved consumer surface referenced them; they predate `ScopeLineageResult`
  and had no producer. Consumers of the current parser entry points are unaffected.
- Fixed the internal-resolution pass rewriting settled outputs: a completed expansion
  (resolved, physical fields present) is no longer mistaken for a damaged one, so the
  fine-grained `scope_output_trace` provenance chain can never be collapsed by an extra
  resolution round. Golden artifacts are byte-identical.
- Internal restructuring, no artifact changes: the `_shared.py` grab-bag split into ten
  themed modules; the fact pipeline expressed as four named phases with convergence loops
  and a wiring guard test; a package dependency-direction architecture test now runs in CI;
  the `expression_resolution` payload is typed (`fact_protocols.py`) with a non-blocking
  pyright job. Deep imports of `scope_lineage.scope._shared`, `scope.types`, or
  `scope.sqlglot_config` (now `scope_lineage.sqlglot_config`) no longer resolve -- the
  supported surface remains the package facade.
- The task contract no longer strips column types and comments while handing its schema to
  per-statement parsing. `SchemaMap` carries them on an attribute, and a `dict()` copy kept
  the keys while silently dropping it, so every nested statement in a v2 artifact reported
  null type/comment for columns the v1 artifact of the same statement documented fully.
- **Contract:** v1 documents now carry the script-position join key to v2: an optional
  top-level `statement_id` (`stmt:NNN`, matching v2's `statement_sequence[].statement_id`
  for the same statement) and `statement_index`. `task_id` cannot serve as the key -- v1
  suffixes it by write ordinal, v2 by script position, so the same `demo#1` names different
  statements in the two contracts and matches silently. Absent when parsing starts from a
  caller-supplied tree, where the script position is unknown.
- `parse_scope_lineage` (the single-statement entry) no longer applies its
  "first write only" boundary silently. Writes beyond the first are recorded in
  `skipped_statements` with `category: additional_write_statement` (plus their
  `target_table`), an `additional_write_statements_not_modeled` warning names the targets,
  and the script's non-write statements are recorded the same way the plural entry always
  did. Previously a two-write script came back as the first write's document with nothing
  recorded -- undeclared data loss on a public API symbol.
- **Behavior change (CI exit codes):** an unexpanded `SELECT *` on ROOT is now a
  root-impact `projection_wildcard_unexpanded` fact gap in the statement document -- the
  same gap type the task level always emitted for the same condition. Pipelines gating on
  `--fail-on-root-gap` or `--quality-policy strict` that previously passed such artifacts
  now fail them; that is what those flags are for. The permissive default still exits zero.
- Self-joins keep their two sides apart in `join_relation_detail`: `left_alias` and
  `right_alias` no longer collapse onto the later alias, and equality conjuncts whose two
  refs resolve to the same table become `join_key_pairs` oriented by qualifier instead of
  falling into `condition_filters` as an apparent tautology.
- `write_task_lineage` now validates every nested v1 document in `statement_lineage`
  against the v1 schema before publishing; the v2 schema types them as bare objects, so
  the envelope validation never looked inside.
- A `directory:` target in a v2 task raises a `directory_targets_present` task-level
  warning: the entry lands in `final_table_states` like a table, and v1 already documents
  the exclusion rule on `target_table` while v2 said nothing.
- A trailing comment (`INSERT ...; -- done`) is recorded as `stmt_kind: COMMENT` instead
  of `SEMICOLON`, in both contracts; the category stays `empty_statement`.
- Docs: designated `statement_id` as the only cross-contract statement key; marked
  `metadata_coverage`/`analysis_status` guidance as contract-2.0-only (v1 diagnostics
  never carried those keys); stated that top-level v2 `end_to_end_lineage` is a
  final-state merged view not equivalent to v1's per-statement arrays (the nested
  documents are the equivalent surface); documented the `directory:` phantom-table
  exclusion in v2; and stated the consequence of writing both contracts into one
  directory (same file names, silent overwrite).

## 0.1.16
- MERGE assignment values now resolve in the scope their WHEN branch can actually see. Spark
  picks the name-resolution scope from the clause -- a MATCHED action sees target and source
  both, `WHEN NOT MATCHED` only the source, `WHEN NOT MATCHED BY SOURCE` only the target --
  while Core resolved every branch against the USING relation and took the branch label from
  the THEN action's type rather than from the clause. With two branch kinds those dimensions
  coincide; Spark has three. A `WHEN NOT MATCHED BY SOURCE` update published an edge to the
  *source* table, marked `trace_complete`, for a branch in which Spark cannot see the source at
  all. The same missing candidate set produced two further wrong answers under plain MATCHED,
  with no BY SOURCE anywhere: an unqualified name both relations expose was silently
  attributed to the source, though this project already publishes a rule against picking an
  arbitrary source, and a name only the *target* exposes was attributed to the source as well,
  so a column the source does not have appeared as its output with no diagnostic -- and writing
  the same statement with a subquery `USING` gave a different answer again. Unqualified names
  now go through the resolver the rest of the product uses, so ambiguity lands in the existing
  `ambiguous_unqualified` / `AMBIGUOUS` + candidates representation, an unknowable side in
  `unresolved_unqualified_no_schema`, and a source-qualified reference under BY SOURCE in
  `dangling_column_ref_dropped`. No new vocabulary was introduced. WHEN conditions get the same
  branch discipline.
- **Contract:** Spark has three WHEN clause kinds and the `merge_branch` enum names two. Rather
  than publish one of the two for a clause that is neither -- `not_matched` means "absent from
  the target, inserted from the source", the opposite of what a BY SOURCE clause writes --
  `merge_branch` is now omitted there and a new optional `merge_branch_qualifier` carries the
  kind, on every surface that already published `merge_branch`. A consumer keying on
  `merge_branch` drops such a write rather than misplacing it: missing beats wrong, but it is a
  silent omission, so a `merge_branch_not_representable` warning states why the label is
  absent, and `merge_when_index` is still emitted. Two surfaces published `merge_branch`
  without declaring it in the schema; both are declared now.
- `SELECT * EXCEPT (...)` no longer publishes the columns it excludes. The excluded column used
  to appear as a proven output field on every surface -- including `related_metadata`'s entry
  for the *target* table, where it invented a column the target does not have -- with no
  diagnostic. The exclusion is applied in one pass over the resolved scopes rather than at each
  expansion site, because a star is materialized in more than one place and which one runs
  depends on how the query was written rather than on what it means. Relatedly, a passthrough
  SELECT over a UNION is no longer unwrapped when its star carries an EXCEPT: such a star is
  not a passthrough, it drops columns, and unwrapping lost the exclusion the same way the
  surrounding code already warns other clauses are lost. Because this changes the projection
  count, positional target-DDL binding moves in both directions, and both are corrections:
  where the counts now match, binding applies where it previously bailed out; where they no
  longer match, the statement falls back instead of authoritatively binding a column the
  projection never produced. Spark's grammar allows exactly one star modifier; `REPLACE`,
  `RENAME` and `ILIKE` belong to other engines and are reported through
  `star_modifier_not_supported` rather than modelled, and `star_except_column_not_found` marks
  an exclusion naming a column the star does not produce.
- A deployment can declare the partition overwrite mode its clusters run with, via
  `--partition-overwrite-mode static|dynamic` (contract 2.0 only). `INSERT OVERWRITE TABLE t
  PARTITION(dt)` -- a partition spec with no value -- deletes either the whole table or only
  the partitions the write produces, and `spark.sql.sources.partitionOverwriteMode` decides
  which; the SQL cannot see it. Scripts rarely `SET` it, so v2 fell back to Spark's documented
  default of `static`. For a deployment whose clusters run `dynamic` that answer is not
  conservative but backwards: every daily overwrite of a partitioned table was reported as
  wiping the table's history, dropping the "came from this table's own prior state" edges such
  an overwrite in fact preserves. A `SET` inside the script still wins. **Contract:**
  `partition_overwrite_mode_source: "assumed_default"` used to imply "static was used"; it now
  means only "the script did not set it", and a new `partition_overwrite_mode_declared` carries
  the value actually applied, its *absence* meaning Spark's default. Consumers that only filter
  on the enum are unaffected. Separately, the rolling `SET` tracker no longer treats an
  unrecognised value as `static`, which had quietly converted the neighbouring Hive key's
  `nonstrict` into a real answer.
- The empty statement a `;;` leaves behind is recorded. sqlglot models the two empty shapes
  differently -- a bare `;` after a comment parses to a semicolon node, `;;` yields nothing --
  and v1 recorded the first while dropping the second. Statement indices count every position,
  so dropping the record left holes that no published field explained, in exactly the field the
  documentation points readers to for "what was ignored". The two shapes keep separate kinds,
  matching what the task document has published for both all along. Note that
  `skipped_statements` is a conditional key: a script with no skipped statements gains the key,
  while one that already had an entry gains an array element, so a consumer that counts entries
  sees a different number with no schema change to signal it.
- A MERGE `INSERT *` branch expands over the target's columns, not the source's, matching how
  Spark resolves a star action.
- A statement with no target binding says why, once, in both documents, so an absent binding is
  distinguishable from a binding that was never attempted.
- The session setting for quoted regex column selections is honoured: with it disabled, a
  backtick-quoted pattern is the literal column name it is in Spark, not an expansion over the
  columns it would have matched. The overwrite documentation was corrected in the same change.

- New `scope-lineage render` subcommand and `render_mapping_markdown` public API: render one
  statement's `lineage.json` (+ sibling `diagnostics.json`) into a `mapping.md` field-mapping
  document readable by people and parseable by machines. The document is a derived view of the
  contract, never a second source of truth: a flat front matter block, fixed line grammars
  (versioned as `mapping-md/1`) whose expressions always sit last on the line inside code
  spans -- so SQL literals containing separators cannot break parsing -- and contract ids
  (`mapping_chain_id`, `logic_block_id`, scope ids) as join keys back into `lineage.json`.
  Uncertainty stays explicit: incomplete traces, un-split self-join conditions, and a missing
  diagnostics file are all marked instead of being rendered as facts. Directory mode skips
  contract-2.0 documents with a count instead of failing. The `parse` subcommand still writes
  exactly the two contract files. Four golden cases were added alongside the existing baseline
  (directory target, self join, a non-empty lineage fact gap, separator-heavy literals); the
  rendered `mapping.md` for every case is byte-locked the same way the JSON contracts are.
  Parse-process warnings do not enter `mapping.md`: a statement that has any renders a sibling
  `warnings.md` (grouped by type, each type carrying a one-line gloss), and the mapping
  document keeps a counted pointer plus only the facts that change how much a reader may trust
  the lineage. The relations overview answers "how do the source TABLES relate": join keys
  are pierced to physical fields and aggregated per table pair with short key names and an
  occurrence count, identical patterns repeated across scopes merge into one counted row, and
  CTE-to-CTE joins whose pierced keys add nothing (both sides reading the same table used to
  render as repeated self-pair rows with `t.c = t.c` keys) stay out of the overview entirely
  -- the scope-level detail below remains the complete list, where pierced pairs appear only
  when informative and the verbatim ON survives only where the key/filter split is
  incomplete. The constant-source column of the mapping table appears only when some field is
  actually constant-fed. The overview consumes `target_binding_absent_reason`: a statement
  without a binding states the actual reason in Chinese, and only `target_table_not_found`
  -- the one absence that risks positionally misplaced columns -- carries the warning
  marker. The four golden cases added with the renderer are regenerated against the current
  contract output.

## 0.1.15
- A UNION branch projecting a row-count aggregate or a bare window function no longer reports a
  root-impact lineage gap for an expression nothing was missing from. The branch mappings are
  built one pass before expression resolutions are normalized, and it is normalization that
  synthesizes `rowset_sources` for a resolution already classified `rowset`; the mapping copied
  three empty source lists and the gap detector re-derived `unresolved` from them. `COUNT(1)`
  and a bare `OVER ()` in a union branch therefore failed the strict quality gate, which was the
  largest single source of root-impact gaps a run could report. A windowed function that
  references a column was never affected -- it picks that column up as a physical source. No
  contract change: `rowset_sources` is an existing field.
- A generator over a literal -- `LATERAL VIEW EXPLODE(ARRAY(...))`,
  `INLINE(ARRAY(STRUCT(...)))` -- now records the constant it reads. Its argument has no column
  references, so the output columns were minted with an empty source list, making the column a
  dead end that reported itself as fully traced: `end_to_end_lineage` rendered
  `source_kind: "unresolved"` while `trace_complete` stayed true, the one pair a consumer must
  never have to tell apart, while `field_mapping_chains` already answered `generated` for the
  same field. The VALUES / table-valued-function path already routed a source-free leaf
  correctly; this is its missing twin. Fixing it in the resolver rather than while rendering the
  trace also clears the dead end out of the scope document, which the chains and the MERGE
  condition path read directly. A column that branches on the generator's value now reports
  `mixed` rather than `physical` -- it genuinely depends on the literal array, so the previous
  answer was an omission.
- A quoted regex column selection that was expanded no longer keeps a warning saying the column
  does not exist. Column-reference resolution runs first and cannot know the name is a pattern,
  so it warns -- `column_not_found` bare, `column_not_in_table_schema` qualified -- and the
  expansion pass then replaces the pattern with the columns it matched. The retraction is gated
  on the match having happened, not on the name looking like a regex: that predicate is only a
  metacharacter test, so it is equally true of a genuinely missing column called `amount$usd`,
  of a pattern matching nothing, and of a pattern in a WHERE clause that is never expanded.
  Suppressing on it would trade a false alarm for a false silence.
- A `CREATE TABLE ... <query>` that omits the optional `AS` is now parsed when its query begins
  with `WITH`. Spark allows the omission and the parser accepts it before `SELECT` but not
  before a CTE, where the statement degraded to an opaque command and contributed no lineage at
  all. The repair works on the token stream, per statement: a text-level match cannot see
  comments, and a commented-out `create table` line above a live `WITH ... AS (` is a common
  shape whose rewrite would swallow the *following* statement's CTE while still parsing. Each
  statement is judged alone -- it must currently be a command and must become a create carrying
  a query -- and the rewrite is disclosed as `ctas_as_inserted_for_parse` rather than left
  silent. `syntax_status` is deliberately unchanged: it is script-scoped, and downgrading it
  would degrade every other statement in the same script.
- A statement the tool ignores by design is no longer called unsupported. The category function
  already separated a config statement and an empty one from the kinds genuinely not modelled,
  and the task document acted on that split; the statement document imported the same function
  and never used it, so config and empty statements were the largest source of warnings in a run
  while the name asserted something false about both. Dropping the warning alone would have
  traded a misleading signal for no signal -- this document's skip record carried no SQL, and
  `skipped_statements` is written to `lineage.json` only -- so the record now carries
  `normalized_sql`, matching the task document's. Warnings for row mutations and genuinely
  unmodelled kinds are unchanged, and the records themselves are untouched.
- Documented what `target_table` holds when the write goes to a path. `INSERT OVERWRITE
  DIRECTORY` is modelled like any other write but its destination is a filesystem path, reported
  as `directory:<path>`; the contract doc described the field as a table name only, so a consumer
  registering warehouse tables from it had nothing telling it to skip these. No behaviour change
  -- the regression tests the shape never had are added, including that it emits no diagnostic of
  its own, since the result is correct and the target is self-describing.

## 0.1.14
- Narrowed the `source_state_columns_unknown` gap to the one shape it exists for. It was keyed
  on `state.columns_known`, which is false for *any* missing reason, so relations whose columns
  were named in the producing projection and listed column by column in the document were
  reported as undescribed. It now asks whether the relation's own projection stayed a wildcard
  -- the case where its single row is keyed on `*` and no named column can ever be found in it,
  which is what leaves a consumer with nothing to fold. `COUNT(*)` is excluded: its star is the
  row, not an unknown column list.
- Added `fold_session_scoped(document)` to the public API: one implementation of resolving hops
  through relations that do not outlive the session, so consumers do not each write their own.
  It returns a copy, drops the rows and `final_table_states` entries for those relations, and
  where a hop cannot be resolved it keeps the original source and says why via
  `value_sources_folded` / `fold_incomplete_reasons` rather than returning a shorter answer. The
  four unresolvable cases are all real: a read of a state that was later replaced, a relation
  whose own columns were never resolved, a column with no sources, and a cycle. Constants
  survive the fold -- they name no relation to resolve.
- `value_sources[]` entries that read a session-scoped relation now carry `session_scoped: true`.
  The same fact was already on the producing statement, but the edges a consumer acts on are
  here, so acting on it meant collecting relation names from `statement_sequence` and
  intersecting them against every source. This is a new optional key beside `source_kind`, not a
  value of it: a filter that does not know the key keeps exactly the behaviour it had. Because
  Core marks the relation it resolved, the edge is marked even where a consumer matching by name
  could not -- a global temporary view is declared bare and read qualified.
- A `CREATE GLOBAL TEMPORARY VIEW` is recorded as `global_temp.<name>`, the name it can be read
  by. Spark puts these views in the `global_temp` database and the declared bare name does not
  resolve, so recording the bare name meant the statement reading it matched nothing: the read
  looked like an ordinary physical table, a consumer excluding session-scoped relations kept it,
  and metadata was reported missing for a table that does not exist. This is the identity half
  of the judgement whose persistence half was fixed alongside temporary tables.
- Incompleteness now crosses a script-local hop. A column read out of a relation whose own
  columns were never resolved -- a temporary relation built from an unexpanded `SELECT *`, which
  has a single row keyed on `*` -- reported `trace_complete: true`, resting on a relation nobody
  could describe. Such columns now report `false` with a `source_state_columns_unknown` reason
  and a matching `lineage_fact_gaps` entry. Incompleteness already propagated from the previous
  state of the table being written; this is the same question asked of the relations being read.
  **This moves rows out of "complete"**: consumers gating on `trace_complete` will see fewer
  complete rows, and the ones they lose were making a claim the document could not support. No
  row moves the other way.
- `value_sources[]` entries now carry `source_state` when the source table was written by a
  statement in the same script, naming which state of it the read saw. A table can hold more
  than one state in a script, so a source that named only the table left two reads of a
  redefined relation indistinguishable, and a consumer resolving that hop by name folded both
  to whichever definition was recorded last. `end_to_end_lineage` is a final-state view, so an
  intermediate state has no row and cannot have one without changing what the field means --
  naming the state is what makes that detectable instead of wrong: the consumer looks for the
  state, finds no row, and keeps the original edge. Absent for a table the script never wrote,
  where there is no second candidate.
- A relation re-created during a script now gets a new `state_id` instead of reusing the first
  one. A CTAS is deliberately given no previous state -- it replaces the relation, so its value
  sources must carry no prior-state passthrough -- but the state's ordinal was derived from that
  same "previous", so every CTAS was numbered 1. A script that redefined a temporary view
  produced two `table_state_graph` nodes both called `state:v:001` with different producing
  statements, and every `edges` / `final_table_states` / `input_states` reference to that id
  became ambiguous rather than invalid, which is why no check caught it. The ordinal now counts
  the states a table has had; inheritance is unchanged. Validation now rejects a duplicate node
  id outright.
- `CREATE TEMPORARY TABLE ... AS SELECT` is now marked `is_session_scoped_relation` like the
  other session-scoped forms. sqlglot reports it with the same `TemporaryProperty` but
  `kind=TABLE`, and the predicate required `kind=VIEW`, so it was silently missed -- the
  "which keyword produced it" mistake the predicate's own comment warns against. The
  judgement is now the property alone.

## 0.1.13
- Added a `session_scoped_relations_present` warning naming every relation in a script that
  only lives for the session. `is_session_scoped_relation` alone was not enough in the task
  document: the flag sits on `statement_sequence[]` while the entry that misleads is in
  `final_table_states`, and `analysis_status` stays `complete`, so a consumer who does not
  know to cross-reference the two reads a confident artifact naming tables that were never
  written to storage.

## 0.1.12
- Kept a statement's lineage when one of its columns is named after a SQL keyword. Spark
  accepts `not`, `like`, `out` and `using` as column names when quoted, and authors routinely
  leave them unquoted; the parser stopped at the first one and the whole projection list was
  discarded, costing a statement the sources for nearly every column it writes. The
  repair carries no reserved-word list -- the parser names the token it stopped on, that token
  is quoted, and the statement is parsed again, with the rewrite kept only if it makes the
  statement parse. Rewrites are reported as an `identifiers_quoted_for_parse` warning rather
  than applied silently. Clause keywords are never quoted: a malformed statement may parse
  once its `WHERE` is quoted, yielding an AST in which WHERE is a column name, and staying
  `recovered` is the honest answer for SQL that is simply broken. Verification shows fewer
  statements degrade to `recovered`, and none lose a traced column.
- Added `is_session_scoped_relation`, marking relations that never reach storage -- `TEMP VIEW`,
  `GLOBAL TEMP VIEW` and `CACHE [LAZY] TABLE`. `CREATE TABLE db.r AS SELECT` and
  `CREATE OR REPLACE TEMP VIEW r AS SELECT` previously produced byte-identical lineage: the AST
  holds the distinction and Core dropped it, so `final_table_states` gained an entry for every
  temp view and consumers reconciling it against the catalogue reported tables that do not
  exist. One predicate covers every spelling, decided on AST facts rather
  than naming patterns; a non-temporary `CREATE VIEW` is registered in the catalogue and
  outlives the session, so it is not marked. Purely additive: `source_kind` and `source_type`
  keep their value distributions, and `is_cached_relation` keeps its meaning as the
  CACHE-shaped subset of this field.
- Stopped a statement sqlglot can parse but not print from taking the caller down with it. An
  identifier its tokenizer claims as a keyword — for example a keyword-colliding column inside
  `CAST` — parses into a Cast whose target type is None, and the Spark generator
  dereferences it. `parse_scope_lineage` had no error boundary, so the AttributeError escaped
  the public API; the batch entry point has had one since 0.1.0, which is why only the
  single-statement path was affected. Guarding the boundary rather than each of the 55 render
  sites: rendering is not the only thing that can fail on a repaired tree — `output_name`
  derives its answer by rendering too — and a statement that cannot be printed still has usable
  lineage. `ValueError` and `NoSupportedWriteStatementError` still reach the caller unchanged:
  this package raises those deliberately to mean "refuse to emit lineage rather than emit
  something wrong". The degradation itself is unchanged — that statement is still `recovered` —
  and the verification outputs are byte-identical

## 0.1.11 - 2026-08-20

- Named the columns a window grouped or ordered by, in a new optional
  `window_context_sources` beside the existing sources. `transform` cannot carry this: it
  records the strongest expression kind on a source's path, and `_trace_column` passes that down
  every branch, so a partition key and the value the window computes arrive labelled `WINDOW`
  alike. Nothing was wrong with the lineage — `value_sources` was complete — but a wide window
  was filed as a P0 "the lineage was smeared across the whole table" against a right answer.
  The keys sit in their own array the way
  `row_membership_sources` and `value_condition_sources` have since 0.1.0, and `value_sources` is
  unchanged to the edge: it stays the complete dependency set change-impact analysis needs. A
  column that both orders a window and feeds the computed value appears in both, which is why
  subtracting one from the other is not the recipe for "what computes this" — when a column has
  both roles, subtraction answers "nothing". Optional, omitted when empty, declared in both
  documents' schemas; verification confirms the
  `value_sources` edges are unchanged and the context entries are additive

- Stopped reporting a `duplicate_table_in_union` for a table a branch only reads inside a filter
  subquery. The warning exists to catch a copy-pasted UNION branch whose source was never changed,
  and it read that off `depends_on` -- everything the scope reaches. Once a filter subquery's
  physical tables were restored to `depends_on`, the anti-join shape (`SELECT ... FROM a` UNION
  `SELECT ... FROM b WHERE NOT EXISTS (SELECT 1 FROM a ...)`) started warning on every occurrence,
  which is deliberate SQL and extremely common: the old rule produced false warnings and demoted
  statements that had nothing wrong with them. `ScopeInputEdge` already carries the fact the
  detector wants -- "a direct input edge from a FROM/JOIN source into a scope" -- so it now reads
  `input_edges`, counting each branch once because one branch can hold several edges to the same
  table. A table the branch pulls in by JOIN still counts; a branch whose FROM is a derived table
  over the shared table is still missed, as it was before, and widening that reach is a separate
  change (DUP-UNION-001)

- Limited an unreadable metadata file to that file, on the two paths where 0.1.6's rule had never
  actually taken effect. Source schema had the per-file guard but caught only `MetadataFileError`,
  while the JSON reader let a raw `JSONDecodeError` out — so the commonest kind of bad file walked
  straight past it. Target DDL metadata raised on the first unreadable file and abandoned the rest
  of the directory, the rule having never been applied there at all. Worse, a file-level rejection
  is recorded with no table name, and the serializer kept only conflicts whose table was among the
  referenced ones — so every one of them was recorded and then dropped, leaving an artifact that
  said nothing at all about the file it could not read. Unreadable files are now isolated while
  healthy tables still load, with each rejected file and its reason in `metadata_conflicts`.
  A load that produced no table still raises, and still names every file it
  refused

- Stopped deciding which warehouse layers require a cross-task trace. Core stamped
  `expression_resolution.cross_task_trace_required` from a vocabulary written into it -- `app`,
  `app_*`, `dm*`, `ads*`, matched against the database segment alone. Warehouse layer naming is a
  deployment convention, which this project's own conventions place downstream, and a deployment
  naming its upper layers anything else got the flag on nothing at all with no way to find out.
  Core still publishes what the judgement rests on: `physical_source_fields`, the physical columns
  an expression resolved to. **The field was never declared in the JSON Schema and appears in no
  document, but it did reach the artifact and it did have a consumer** -- so its removal is a
  behaviour change even though it breaks no contract. Verification confirms every other signal is
  unchanged. A consumer that wants it back computes it
  from `physical_source_fields` with its own layer policy

- Dropped seven re-exports from `scope_builder` that existed only so a consuming repository could
  import Core internals through it. They were never in `PUBLIC_CORE_API`, so this changes no
  contract -- but anyone who had reached for `scope_lineage.scope.scope_builder._populate_lineage_fact_gaps`
  and friends will now get an ImportError instead of a symbol Core was free to move anyway. The
  functions themselves are unchanged, in the modules that define them. The consumer that needed
  them stopped: the tests that were reaching through now live here, where the behaviour does

## 0.1.10 - 2026-08-19

- Published `Diagnostics` and `DiagnosticWarning` on the public facade. A consumer already
  receives both through `ScopeLineageResult.diagnostics`, which is itself published, and their
  siblings `ScopeColumn`, `ScopeData`, `ScopeOutputField` and `SourceRef` were public — these two
  alone were not, so anyone naming the type they had just been handed had to import it from
  `scope_lineage.scope.scope_types`, a path Core is free to move. Reaching a type through a
  private module in order to describe a published one is a hole in the facade, not a use of it

- Documented that `value_sources[]` lists participation paths rather than a set of columns. The
  dedup key is `(table, column, transform)` and includes the transform deliberately, so one
  physical column appears once per way it participates — a derived column can carry duplicate
  entries that dedupe to the same physical columns as a sibling field. Read as a column set, that
  looks like the lineage was smeared across the whole table. The document now gives the dedupe recipe
  and warns off the filter that suggests itself — keeping only `DIRECT`/`EXPRESSION`/
  `CONDITIONAL` empties the lineage of every aggregate and window metric, because their value
  arguments carry `AGGREGATE` and `WINDOW` too

## 0.1.9 - 2026-08-19

- Stopped reporting a table qualified by its own name as an unexpanded alias. `qualify` names
  an unaliased table after itself, so `FROM ods.pay` yields references written `pay.uid` while
  the physical id stays `ods.pay`; the exemption for "the alias *is* the physical source"
  compared the two directly and never matched. A fully resolved direct physical source was
  therefore reported as `expanded_expression_contains_unexpanded_alias`, demoting the output to
  partially_resolved and the statement to `partial`. It needed the same table read both in the
  enclosing `FROM` and inside a projection subquery to surface, which is why it hid: the `FROM`
  registers the binding and the subquery puts that same qualifier into the expression text,
  which the textual check cannot tell apart. A genuine local alias is still reported — `s` in
  `FROM ods.source s` is neither the id nor its table name. An affected statement goes from several gaps and
  `partial` to none and `complete`, with its physical sources unchanged

- Recovered the physical sources of a scalar subquery used as a projection. Column references
  inside a nested query are skipped when the enclosing expression is resolved, and rightly so:
  they belong to the subquery's sources, and resolving them outward binds them to whatever the
  outer scope exposes under the same alias. But nothing picked them up afterwards — a scalar
  subquery is not a FROM-clause source, so it never became an input of the outer scope, and the
  projection fell through to the constant fallback with the whole `(SELECT …)` recorded as a
  CONSTANT value and its tables nowhere in the lineage. In the plain shape this was silent: no
  gap, `analysis_status` complete. They now resolve against the subquery's own scope, which
  sqlglot already builds, and a correlated reference still binds outward because alias lookup
  walks parent scopes. Across the statements that use the shape, physical source edges come
  back and affected subqueries stop being reported as constants

- Stopped a dynamic-partition `INSERT OVERWRITE` from claiming the target's previous values
  survived it. The write effect was chosen from `target_partition_mode != "none"`, so
  `PARTITION(dt='20260101')` and `PARTITION(dt)` were treated alike and both carried the
  target's previous `value_sources` forward. Only the first deserves that: a valued spec
  replaces the partitions it names and the rest of the table stands, while a bare
  `PARTITION(dt)` depends on `spark.sql.sources.partitionOverwriteMode`, whose default is
  STATIC — every existing partition is dropped before the new data lands. Every column of such
  a target therefore came back with a `prior_table_state` edge from a state the overwrite had
  destroyed, which is what a consumer folding state-evolution edges reads as "this column was
  left alone". The setting is now read from the script when present and applies to the
  statements after it. A dynamic-partition overwrite now agrees with the unpartitioned one it
  has always resembled: a column the write does not supply gets no row rather than a false
  one. Affected statements lose those edges; gap counts, statuses and syntax results are
  unchanged

- Documented that a window field's sources carry three different roles under one
  `transform: "WINDOW"`: the aggregate's value argument, the `PARTITION BY` keys and the
  `ORDER BY` keys. A window partitioned by many columns therefore lists all of them as
  sources, which reads as "the whole table was smeared onto one field" if the roles are not
  separated — a reading that has already produced a false pollution report. The roles are on
  the column that *defines* the window (`columns[].window.partition_by` / `order_by`), not on
  the downstream field, and `end_to_end_lineage` flattens the chain without a back-pointer,
  so both documents now say where to look and how to tell a value source from grouping
  context. No behaviour change

## 0.1.8 - 2026-08-19

- Normalized schema column names the way table names already were. sqlglot's `qualify`
  lower-cases unquoted identifiers, so every column reference the resolver sees is
  lower-case; `normalize_table_name` lower-cases for exactly that reason and says so in its
  docstring, but column names were passed through verbatim. A metadata export that spells
  its columns in upper case therefore matched nothing. Nothing failed loudly: `SELECT *`
  expansion copies schema names into a scope's column list, so an inner scope advertised
  `V1` while the outer scope asked for `v1`, source chains broke to `scope:"UNKNOWN"`, and
  explicitly referenced columns were re-added as case-variant duplicates — while
  `metadata_coverage` still reported every table covered, because coverage only checks table
  names. A multi-branch MERGE went from many lineage fact gaps and `partial` to none
  and `complete`; the same schema differing only in case is now the same lineage

- Stopped a MERGE's USING alias from being captured by an inner table of the same name.
  `USING (SELECT record_id AS biz_no, 'prod' AS etl_source FROM ods.src t1) t1` resolved
  every `t1.<col>` against the subquery's *internal* sources, where the inner table won — so
  a renamed projection was published as `ods.src.biz_no`, a column that table does not have,
  and the literal became `ods.src.etl_source`, a physical field. With `trace_complete` true
  and no warning: a confident wrong answer, and precisely what this project's README
  criticises other tools for. A column the subquery passes straight through still binds
  directly to the table, which is the lexical source an earlier fix preserves; only a
  derived column is redirected. The fabricated columns in an affected statement go to none

- Gave `syntax_errors[]` an order that holds across processes. sqlglot builds one message
  per entry of `Expression.required_args`, which is a `set`, and CPython randomises string
  hashing per process — so a statement missing two required keywords wrote the same entries
  in an order that changed between runs. `syntax_errors` is a required field of
  `lineage.json`, and this project treats byte-for-byte determinism as a contract invariant,
  so anyone diffing artifacts across runs saw a phantom change. Sorted by position first, so
  errors genuinely ordered by where they occur keep that order and the description only
  breaks ties

## 0.1.7 - 2026-08-19

- Said where the reader looks when a source table's columns were never supplied. The fact
  was already in `metadata_coverage`, but `analysis_status` said `partial` for
  `lineage_fact_gap` and the document carried many records — every one of those
  words meaning "the parser could not handle this SQL". `blocking_reasons` now names
  `metadata_incomplete` ahead of `lineage_fact_gap`, and a warning lists the source tables
  that were missing. Sources only: a target without a schema entry is an ordinary shape and
  is never why a source-side reference failed

- Resolved `col.field` on a struct column written without a table alias. `alias.col.field`
  carries three parts and was handled; the two-part form had its first part looked up as a
  table alias, found nothing, and reported the column as an unbound alias. Whether the alias
  is there is not the author's choice alone — qualify adds it when it knows the column set
  and cannot when the input is a `SELECT *` — so the same SQL resolved or did not depending
  on how deep it sat. A name more than one input exposes stays unresolved

- Modelled a PIVOT's output columns. `PIVOT (max(amt) FOR k IN ('A', 'B'))` turns the values
  of `k` into columns named A and B whose values come from the aggregate, and neither the
  names nor that lineage existed: a `SELECT *` over a pivoted relation saw the pivoted
  subquery's own columns instead, so every downstream reference to a pivoted name was a gap —
  many in an affected statement. The pivot's alias now becomes an input edge when it has one, and a
  star over a pivoted source expands to the IN list. A non-literal IN list still reports a
  gap rather than guessing names

- Stopped qualifying every statement twice. `qualify` mutates the tree it is given and
  returns that same object, so the `qualified is src_expr` comparison that guarded the "did
  qualify fail?" branch was true either way, and the branch re-ran qualify on every
  statement to learn what the first call already knew. `_qualify_ast` now reports success
  directly. Cost only — no output changes, both baselines untouched

- Stopped reading an unexpanded `a.*` as a regex pattern. A qualified star cannot always be
  expanded when its projection is first read — a CTE backed by a UNION only gets its columns
  in a later pass — so it is parked as a placeholder for the fixpoint expansion to finish.
  Spark's regex column selection, added in 0.1.6, then matched that placeholder as a pattern,
  and `a.*` is a valid one: a 63-column star collapsed into the single column whose name
  began with "a", and the placeholder was gone before the pass that would have expanded it
  properly ever ran. The affected statements go from many gaps to none

- Let a bare column bind through a regex column selection. Spark's `` `(rk)?+.+` `` names
  the columns a source exposes by pattern, and the match runs after column resolution — but
  a scope projecting one was read as already materialized, with a single concrete column
  literally called `(rk)?+.+`. Every other name was then judged absent from it, so a bare
  reference with two inputs lost the only input that could supply it. A pattern means "not
  yet knowable", which the resolver already models and already keeps in play. Affected
  tasks either improve or remain unchanged

- Marked the fact gaps that a repaired parse produces, with a new optional
  `derived_from_recovered_syntax` on each. When sqlglot cannot place a token it drops the
  rest, and a statement that said `FROM` becomes one with no source at all — so the gaps
  that follow describe the truncation, not the query. They sat in the same list as gaps
  about genuinely missing metadata, and counting the two together turned one syntax problem
  into many apparent capability gaps. `syntax_status` already said the
  parse was repaired; the marker means a consumer no longer has to correlate two documents
  to know which gaps to exclude. Statement lineage needed its own answer, since a truncation
  is invisible once the tree is rendered back out

- Backquoted reserved-word column names in a table's DDL before parsing it. sqlglot's Spark
  dialect does not terminate on `CREATE TABLE db.t (a DOUBLE, not DOUBLE)` across the supported
  SQLGlot versions, so a table whose export happened to
  name a column `not` did not make a task's answer worse, it made the task never finish, and
  no caller could put a timeout around it. Other tables were being rejected outright by
  the milder version of the same problem, losing their columns wholesale. Quoting is an
  equivalent rewrite, and nearly every DDL it touches yields facts identical to before

## 0.1.6 - 2026-08-18

- Roughly halved lineage resolution time on wide statements by remembering answers that
  depend only on their inputs: compiled patterns built from identifier names, the field
  references of an expression, and whether an expression reaches into a struct. A large
  task that previously timed out and returned `partial` now completes with no gaps
- Expanded Spark's quoted regex column selection. `` `(dt)?+.+` `` selects every column
  whose name matches the pattern — its possessive quantifier making it the idiom for "every
  column except dt" — and reading it as a literal name produced a column no table has, which
  took every downstream reference to that scope down with it
- Resolved a reference to a LATERAL VIEW's output column when the qualifier is the column
  rather than the view's alias, so `arr.field` binds to the view that exposes `arr`. Two
  views exposing the same name stay a gap rather than being resolved by writing order
- Modelled Spark's `CACHE [LAZY] TABLE ... AS SELECT` as the relation-from-a-SELECT it is.
  It was skipped as an unsupported statement, so the relation it builds was read back as an
  external table nobody has metadata for and every reference to it became a gap — many from a
  single missed relation. It reports `stmt_kind: "CTAS"` with a new optional `is_cached_relation`
  flag, since the relation lives only for the session
- Made a table's DDL authoritative over its exported column array rather than validating one
  against the other. A partition column declared only in `PARTITIONED BY` is an ordinary
  export shape, not a contradiction, and rejecting it discarded usable metadata
- Limited an unusable metadata file to the table it describes. The loader raised, so a
  malformed file left every table without columns; rejected tables are now
  reported through `metadata_conflicts` and only a load that produced no table at all raises

## 0.1.4 - 2026-08-17

- Declared a MERGE's target relation as a ROOT input carrying its alias, so `target.x` can
  be mapped back to the relation it names, while holding it out of `alias_source_bindings`
  so the correlated reference a MERGE action preserves is not read as a failed expansion

## 0.1.3 - 2026-08-17

- Stopped re-parsing each statement from generated SQL during task-level modelling. sqlglot
  does not round-trip a WITH carried by an individual UNION branch, so the clauses merged,
  same-named CTEs shadowed each other, and the whole statement degraded to an unqualified
  parse; the AST parsed from the original script is now used directly
- Report `normalized_sql_not_equivalent` when the rendered statement loses a CTE to
  shadowing, so a consumer is not handed SQL that looks runnable and is not
- Stopped reading `COUNT(*)`'s dependency on the whole row as an unexpanded projection
  wildcard; only a source that is actually an unexpanded `SELECT *` reports one now
- Declared the USING relation as an input of a MERGE's ROOT scope. That scope is synthetic,
  so the pass that walks SQLGlot scopes never reached it and the scope reported no inputs at
  all, leaving `source` unbindable for expressions that resolve a qualifier by alias
- Expanded physical-table references in expressions that also reference a query block; the
  alias-expansion helper skipped physical sources entirely, so the alias stayed in the text
  and its field never reached the physical source list
- Report `column_not_in_table_schema` when a qualifier names a table whose schema proves
  the column does not exist; the qualified path previously took a qualifier as proof and
  published the reference as a physical field
- Resolve statements against tables the same script creates, so a `CREATE ... AS SELECT`
  feeding a later statement no longer leaves that statement's columns unexpandable and no
  longer reports the script-local table as missing warehouse metadata
- Finish expression expansion when substitution reintroduces a qualifier belonging to the
  consuming scope, recovering the physical field behind a LATERAL VIEW over a query block
- Fixed MERGE lineage corruption when the statement is preceded by a CTE: qualify
  reorders the column traversal, so pairing pre- and post-qualify columns by position
  pasted a MERGE action's target references onto unrelated CTE projections and
  neighbouring UPDATE assignments. Correlated target references are now protected across
  qualify by identity, and an unrestorable reference fails the statement instead of
  publishing a positional guess
- Resolved MERGE `row_membership_sources` through the built USING scope, so a CTE- or
  subquery-backed USING reports its physical root fields instead of the query block's
  name, a UNION reports every branch instead of the literal `UNKNOWN`, and a condition
  the USING relation does not expose reports a new `merge_condition_source_unresolved`
  fact gap instead of a fabricated column

## 0.1.2 - 2026-08-16

- Documentation and packaging only; no library changes

## 0.1.1 - 2026-08-15

- Added opt-in task-level `schema_version: "2.0"` output with ordered statements and
  table-state transitions for write and mutation operations
- Made rich JSON table schema metadata authoritative over CSV fallbacks, preserving column order,
  DDL, and other structured metadata while reporting conflicts
- Added installation, CLI usage, input-format, schema-precedence, and release documentation

## 0.1.0 - 2026-08-14

Initial public release preparation:

- Added opt-in task-level `schema_version: "2.0"` contracts that preserve statement order and
  model table-state transitions across INSERT, overwrite, CTAS, MERGE, DELETE, UPDATE, and
  TRUNCATE, including partition-scoped replacement/reset behavior
- Separated final-field value provenance, value-condition provenance, and row-membership
  provenance so DELETE predicates are not misrepresented as field value sources
- Added schema fallback merging with conflict reporting, metadata coverage diagnostics, target
  binding reason codes, compact JSON output, and configurable CLI quality gates
- Added a SQLGlot compatibility CI matrix for the oldest, previous, and latest supported releases
- Adapted MERGE scope handling for SQLGlot 30.17 and constrained the verified range to
  `sqlglot>=30,<30.18`; MERGE now uses an explicit USING scope instead of SQLGlot's removed
  root Subquery wrapper
- Fixed MERGE action scalar-subquery lineage so nested predicates are not emitted as target
  assignments, correlated target references remain physical self-sources, and scalar outputs bind
  through their own scopes instead of the USING scope
- Resolve CTE references lexically when collecting physical inputs, preserving an unqualified
  physical table that shares a name with a CTE in a different query block
- Versioned `lineage.json` and `diagnostics.json` 1.0 contracts with mandatory validation
- Pure Core writer API for emitting only Lineage and Diagnostics artifacts
- `scope-lineage parse` CLI for SQL files, exported task JSON, and recursive task directories;
  it still emits only Core artifacts
- Explicit `--catalog-prefixes` / `SCOPE_LINEAGE_CATALOG_PREFIXES` normalization policy; full
  catalog-qualified table identities are preserved by default
- Explicit `PUBLIC_CORE_API` facade for downstream Python consumers
- Wheel and source-distribution manifests contain only Lineage Core
- CI verifies Python 3.9–3.12, archive contents, and a repository-external installation
- Scope-aware column lineage parser for Spark/Hive SQL
- schema metadata loading for `SELECT *` expansion
- target DDL/Schema metadata loading for positional INSERT binding
- production-shaped synthetic examples for task wrappers, task dependencies, complex Spark SQL,
  Schema CSV/JSON, and target-table DDL metadata
- public documentation centered on AI-ready SQL task knowledge bases
- field-level documentation for every major Lineage and Diagnostics object, including scope values,
  logic blocks, mapping chains, end-to-end trace semantics, fact gaps, and safe AI consumption
