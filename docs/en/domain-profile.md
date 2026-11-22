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
