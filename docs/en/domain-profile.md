English | [中文](../zh-CN/domain-profile.md)

# Domain profile (`domain-profile/1`)

Scope Lineage is domain-neutral: the package ships generic defaults only. The words one
business uses for its qualifiers, its events, its measures and its lifecycle states, and the
table-name suffixes one warehouse uses to mark a full snapshot or an increment, reach it as
data -- one JSON file the caller passes with `--domain-profile`, or names in the
`SCOPE_LINEAGE_DOMAIN_PROFILE` environment variable (see below). A package-wide architecture
test (`tests/architecture/test_domain_neutral_literals.py`) keeps public lending and finance
words, and table-name suffixes such as `df` / `di`, out of the package's string literals (the
one exemption is listed in that test with its reason: it trims a storage tail off a comment
and never decides a role or a kind).

## Who reads it

| Command | Section it reads | Without a profile |
| --- | --- | --- |
| `semantic packet` | `table_name_convention` | every input's `name_convention` is `unknown` and none is a `full_snapshot`, so check 9's `incremental`-over-full-snapshots failure cannot fire |
| `semantic validate` | `qualifier_terms` | check 12 looks for the generic qualifiers 增值税, 税, 手续费, 测试 |
| `ontology` | `concept_words`, `table_name_convention` | the concept layer votes and ranks with its generic word lists, and no table-name suffix says which copy a table is: no member is a `snapshot` by its suffix, the `increment_with_event_time` kind vote never appears, and a table with no comment is named by its whole short name (`ods.gadget_df` → `gadget_df`); table families (`families[]` and the grouping of open items) fold only `_tmp` / `_bak` / `_new` / `_old` and numbered steps, so `ods.gadget_di` and `ods.gadget_df` are two families |

Each command reads only its own section and ignores the others, so one file serves a whole
run. A file that cannot be read, a wrong `doc_format`, an unknown key or a value of the wrong
shape exits 2 with the field named.

## Through the environment

When `--domain-profile` is not given, all three commands read the
`SCOPE_LINEAGE_DOMAIN_PROFILE` environment variable (only when it is non-empty), so one run
sets it once and every command reads the same file. When both are given the flag wins. A
command that reads a profile says on stderr which file it used and whether it came from the
flag or the environment, so a setting left over in the environment cannot change the output
unnoticed. A file named by the variable that cannot be read or is malformed exits 2 as well,
with `SCOPE_LINEAGE_DOMAIN_PROFILE` named in the message.

The runbook (`skills/scope-lineage-ontology`) writes the path into the run directory's
`env.sh` with `init_run.py --domain-profile <file>`, and `runlib.sh` exports it as this
variable, so the runbook's `semantic packet`, `semantic validate` and `ontology` all read the
same profile.

## Format

```json
{
  "doc_format": "domain-profile/1",
  "qualifier_terms": ["运费", "优惠券"],
  "table_name_convention": {
    "full": ["df", "da", "full", "snapshot", "hf", "mf", "wf", "all"],
    "incremental": ["di", "hi", "inc", "incr", "delta", "mi", "wi"]
  },
  "concept_words": {
    "event": ["下单", "发货", "退货"],
    "entity": ["商品", "门店"],
    "summary": ["周报"],
    "measure_suffixes": ["运费", "销量"],
    "filter_words": ["已发货", "未发货", "已签收"]
  }
}
```

This is `examples/domain-profile/domain-profile.json`, a synthetic retail example.

| Key | Shape | Meaning |
| --- | --- | --- |
| `doc_format` | `"domain-profile/1"` | required |
| `qualifier_terms` | list of strings | qualifiers added to check 12's generic ones. A Chinese term counts where it stands as a word (see check 12 in [Table semantics](table-semantics.md)); a latin term matches as a whole word, case-insensitively |
| `table_name_convention` | object with `full` and / or `incremental`, each a list of suffixes | a table whose last name segment ends in `_<suffix>` is `full` (each partition holds a full copy) or `incremental`. A suffix is letters and digits, written without its `_`, matched case-insensitively; `full` is tried first. The packet labels each input's `name_convention` by it; the concept layer (`ontology`) reads a member's role by it (a `full` table with no columns outside the key is the primary copy, an `incremental` one a snapshot copy), casts the `increment_with_event_time` vote for an incremental table, keeps incremental tables out of a dimension concept, drops these suffixes when it names a table that has no comment, and table families (`families[]` and the grouping of open items) fold a table's copies by it (the union of `full` and `incremental`) |
| `concept_words` | object with any of `event`, `entity`, `summary`, `measure_suffixes`, `filter_words`, each a list of strings | words added to the concept layer's generic lists: the first three are word votes for a concept's kind (Chinese as a substring, latin as a whole word), `measure_suffixes` and `filter_words` mark a name candidate as naming a measure or a slice of the concept rather than the concept (see `junk_reason` in [Key-fold candidates](ontology-doc.md)) |

Every key but `doc_format` is optional, every list adds to the built-in generic list rather
than replacing it, and an empty profile changes nothing.

## Drafting a profile from the corpus

A domain profile need not be written from memory: a warehouse's conventions are already in its corpus -- the table-name
suffixes, how tables are read, the column and table comments. Drafting a profile takes five steps:

1. the tool counts the evidence in the corpus (`domain-profile evidence`);
2. a model reads the evidence and writes a draft profile with one reason per entry (the writing prompt is
   `skills/scope-lineage-ontology/references/domain-profile-prompt.md`);
3. the tool checks the draft (`domain-profile check`);
4. a person decides every pending entry; the answers go into `confirmed.json` and the accepted entries into the draft;
5. the tool checks the draft again together with the answers, and the profile is enabled.

The tool reports observations only and draws no conclusion for you; whatever the evidence cannot settle is left to a person.
In the runbook this is step S2a (`skills/scope-lineage-ontology/references/steps/S2a.md`).

```bash
# 1. Count the evidence: reads the parsed corpus and the metadata only, calls no model
scope-lineage domain-profile evidence \
  --lineage out/artifacts --schema table_metadata/ \
  --out profile/

# 2. Draft: give the writing prompt and profile/evidence.md to a model; it writes
#    profile/domain-profile.draft.json and profile/domain-profile.reasons.md

# 3. Check the draft
scope-lineage domain-profile check \
  --profile profile/domain-profile.draft.json \
  --reasons profile/domain-profile.reasons.md \
  --evidence profile/evidence.json

# 4. A person decides every pending entry: answers in profile/confirmed.json, accepted entries added to the draft

# 5. Check again with the answers; once it passes, copy the draft to the real file
scope-lineage domain-profile check \
  --profile profile/domain-profile.draft.json \
  --reasons profile/domain-profile.reasons.md \
  --evidence profile/evidence.json \
  --confirmed profile/confirmed.json
cp profile/domain-profile.draft.json profile/domain-profile.json
```

### `domain-profile evidence`

| Option | Meaning |
| --- | --- |
| `--lineage` | The `parse` output directory (or one `lineage.json`), as `semantic packet --lineage` takes it. Required |
| `--schema` | Metadata, as `parse --schema` takes it. Required: without it a partition column with an unusual name goes unseen and the read counts are quietly wrong |
| `--schema-fallback` | As for `semantic packet`; repeatable |
| `--metadata-patch` | As for `semantic packet`; repeatable. A run that patched its comments passes the same patch, so the evidence reads the comments the packets read |
| `--out` | Output directory for `evidence.json` (`domain-profile-evidence/1`, complete, for `check`) and `evidence.md` (for the model) |

Only the tables the corpus reads or writes (the corpus tables) are counted; no domain profile is read, and the output carries no
business word of the package's. On success stdout gets one summary line:

```
Evidence for 12 corpus table(s), 12 found in metadata (100%): 4 suffix(es) -- 1 incremental, 0 pending, 3 without suggestion; qualifier material 16 entries, concept material 25 entries (truncated 0)
```

Exit 0 means the evidence was written, 2 a usage error or an unreadable input. When fewer than 80% of the corpus tables are
found in the metadata the evidence is still written, but no suffix gets a suggestion, and `notes` and the top of `evidence.md`
say why.

**Table-name suffixes**: the part of each corpus table's last name segment (lower-cased, backticks dropped) after its last `_`,
letters and digits only (a name without `_` has none). Per suffix the evidence counts how each downstream statement reads the
partitions of those tables, one statement reading one table being one read:

| Read | Meaning |
| --- | --- |
| `equality` | One partition |
| `multi_equality` | A few fixed partitions (two points in time compared, say) |
| `range` | A range of partitions |
| `unconditioned` | The table is partitioned, but this read has no partition condition |
| `unpartitioned` | The table has no partitions |

Each read comes with up to three typical shapes, everything but operators, SQL keywords and function names masked (a
partition column as 「分区列」, any other column as 「列」, a constant as 「常量」), so a person can see where the reading is coarse:
`substr(分区列, 常量, 常量) = 常量` takes a month yet counts as `equality`. The write side is observation only: how many
statements write these tables, how many of them filter their upstream by a business-date window, and how many write static
or dynamic partitions.

The partitioned reads are `equality` + `multi_equality` + `range`; `multi_equality` is in the denominator and in neither
numerator. The thresholds are written into `evidence.json` as `suffix_rules`:

| Observation | Condition |
| --- | --- |
| `range_reads` | At least 3 tables read with a partition condition, at least 5 such reads, at least 90% of them `range` |
| `single_partition_reads` | The same thresholds, at least 90% `equality` |
| `mixed` | Over the thresholds, neither at 90% |
| `too_few` | Under the thresholds |

| Suggestion | Condition |
| --- | --- |
| `incremental` | `range_reads`: reading a full snapshot by range would count rows twice, so this inference holds |
| pending (leaning full) | `single_partition_reads`; the corpus writes these tables at least once, never through a business-date window; `unconditioned` reads are at most 10% of all reads of the partitioned tables |
| pending (no lean) | `single_partition_reads`, but one of those conditions fails (named) |
| none | `mixed` or `too_few` |

Reads alone cannot tell "each partition is a full copy" from "each day takes that day's increment" (an increment passed on
through the partition looks in SQL exactly like a full-snapshot chain), so **the tool never suggests `full`**. Suffixes under
the thresholds with no partitioned read at all (mostly plain words in table names) fold into one line of `evidence.md`;
suffixes written and never read are listed apart in `write_only_suffixes`.

**Material**: the qualifier material is the comments of the columns the corpus uses (values, conditions, JOIN keys, GROUP BY)
and of the corpus tables, each de-duplicated, listed by count with one source, numeric columns first; the concept material is
the table comments, the comments of the writing statements' key columns (GROUP BY, JOIN keys), and the table-name words (the
runs of letters and digits in the full name, cut as the concept layer's vote cuts them). A comment comes from `--schema` (and
the fallbacks and patches) first and from what the parse carried into the lineage otherwise; `from` says which. `builtin`
lists the qualifiers and concept words the package already has. `evidence.md` lists at most 1200 entries of qualifier material
(numeric columns' comments first, then by frequency) and at most 400 of concept material (by
frequency), and says how many more are in evidence.json.

### Draft and reasons

Following the writing prompt, the model writes `domain-profile.draft.json` (`domain-profile/1`) and
`domain-profile.reasons.md` (two sections, 「已写入」 written and 「待确认」 pending). Every entry of the draft has one line in
the written section, its key written as the full path; `check` pairs them by key path and value, with a full-width or a
half-width colon:

```
- `table_name_convention.incremental` `inc`: every partitioned read is a range (12/12). Evidence: suffix inc
- `qualifier_terms` `运费`: several amount columns' comments state the freight basis. Evidence: comment of shop.order_inc.freight_amt
```

A suffix the evidence marks pending or leaves without a suggestion, and a word the model is unsure of, go in the pending
section and stay out of the draft. The model must not write `confirmed.json`, nor claim in a reason that a person confirmed
anything.

### Confirmation (`confirmed.json`)

A person reads the pending section and decides each entry. For a suffix the most direct test is to take one of its tables and
compare the row counts of two neighbouring partitions: close, and growing slowly over time, means each partition is a full
copy (`full`); far apart, each partition holding one day's worth, means each partition is an increment (`incremental`); when
it cannot be told, leave it out. The orchestrator (or the person) writes the answers as `domain-profile-confirmations/1`; the
accepted entries go into the draft and their reason lines move to the written section:

```json
{
  "doc_format": "domain-profile-confirmations/1",
  "confirmed_by": "<姓名>",
  "confirmed_at": "2026-11-22",
  "entries": [
    {"key": "table_name_convention.full", "value": "<后缀>", "decision": "accept"},
    {"key": "qualifier_terms", "value": "<词>", "decision": "reject", "note": "只是一列的说明"}
  ]
}
```

### `domain-profile check`

| Option | Meaning |
| --- | --- |
| `--profile` | The profile to check. Required |
| `--reasons` | The reasons file. Required unless `--format-only` |
| `--evidence` | `evidence.json`. Required unless `--format-only` |
| `--confirmed` | A person's answers; their accepted suffix classifications pass |
| `--lineage` | Optional: checks whether the evidence is stale |
| `--format-only` | Format only, for a hand-edited profile; then only `--profile` is needed |

The format is checked by the same reader every command's `--domain-profile` goes through, and only its first error is
reported. Whether a word is grounded is decided by the rule its downstream command matches it with, so a word that passes is
one the downstream command can use:

| Draft entry | Grounded when |
| --- | --- |
| a `table_name_convention.incremental` suffix | the evidence suggests `incremental`, or `confirmed.json` accepts this entry |
| a `table_name_convention.full` suffix | `confirmed.json` accepts this entry |
| a `qualifier_terms` word | it hits at least one comment of the qualifier material under check 12's word rule |
| `concept_words.event` / `entity` / `summary` | it hits at least one **table-name word or table comment** under the concept vote's rule (Chinese as a substring, latin as a whole word in any case). Key-column comments do not count: the concept layer votes on a member's table name and table comment only |
| `concept_words.measure_suffixes` | some **table or key-column comment** ends with it (name candidates come from those two) |
| `concept_words.filter_words` | some **table or key-column comment** contains it |

Errors (any one exits 1; grounding errors are all listed): a bad format; an entry without ground; a draft entry without a line
in the written section; a malformed `confirmed.json`, or an entry it accepts that is not in the draft; an entry it rejects
that is in the draft. An `accept` only passes a suffix classification; an accepted word still needs its material (the
downstream command could not match it).

Hints (the exit code is unaffected): a suffix the evidence suggests `incremental` that the draft leaves out; a word whose hits
are exactly those of the built-in words; a repeated entry; a tool version other than the evidence's; with `--lineage`, a
lineage digest other than the evidence's (every `lineage.json` under it hashed with sha256 in relative-path order, the digests
concatenated and hashed once more; the metadata is left out, because `--schema` is often the whole warehouse).

| Exit | Meaning |
| --- | --- |
| 0 | No error; there may be hints |
| 1 | Errors. A draft that is not valid JSON is 1 too: it is a writing mistake, and the draft is rewritten |
| 2 | A usage error, or a file that cannot be read |

When step 3 fails, the `check` output goes back to the model with the evidence for a rewrite, at most twice; after that a
person takes over. When step 5 fails, the answers and the draft disagree, and the orchestrator or the person fixes them.

### When to draft again

- The corpus changed, or another warehouse's tables were added;
- the metadata (comments, partitions) changed, or a new patch was applied;
- a tool upgrade changed the built-in words or how reads are classified (`check` hints at it);
- a downstream output shows a plain convention problem (a family of tables never read as full snapshots, say).

One run uses one profile from start to end: when the profile changes, the packets are rebuilt from scratch
(`packet_digest` changes) and `ontology` runs again.

## Turning the old defaults back on

Before this change the package carried two table-name suffix conventions and a few lending and
payment words as defaults. A downstream project that relied on them keeps the old behaviour by
writing them into its own profile:

- the packet's suffixes were `_df` / `_da` / `_full` / `_snapshot` as full and `_di` / `_hi` /
  `_inc` / `_incr` / `_delta` as incremental;
- the concept layer's were `_df` / `_hf` / `_mf` / `_wf` / `_all` as full and `_di` / `_hi` /
  `_mi` / `_wi` as incremental; the suffixes table families used to fold are this same set.

Both now read the one `table_name_convention`, and the example above holds the union of the
two. The union makes each layer recognise a few more suffixes than it used to: to keep one
layer's old reading word for word, write only that layer's old lists. Its own qualifiers go
into `qualifier_terms`, and its own event words, measure suffixes and lifecycle filter words
into `concept_words`. Packets built with and without the convention differ in
`name_convention` and `full_snapshot`, so their `packet_digest` differs too: rebuild the
packets of a run with the same profile every time. The same holds for the concept layer:
without the convention member roles, kind votes and the names of comment-less tables change,
so run `ontology` over one corpus with the same profile every time.
