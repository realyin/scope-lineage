English | [中文](../zh-CN/domain-profile.md)

# Domain profile (`domain-profile/1`)

Scope Lineage is domain-neutral: the package ships generic defaults only. The words one
business uses for its qualifiers, its events, its measures and its lifecycle states, and the
table-name suffixes one warehouse uses to mark a full snapshot or an increment, reach it as
data -- one JSON file the caller passes with `--domain-profile`. A package-wide architecture
test (`tests/architecture/test_domain_neutral_literals.py`) keeps public lending and finance
words out of the package's string literals.

## Who reads it

| Command | Section it reads | Without a profile |
| --- | --- | --- |
| `semantic packet` | `table_name_convention` | every input's `name_convention` is `unknown` and none is a `full_snapshot`, so check 9's `incremental`-over-full-snapshots failure cannot fire |
| `semantic validate` | `qualifier_terms` | check 12 looks for the generic qualifiers 增值税, 税, 手续费, 测试 |
| `ontology` | `concept_words` | the concept layer votes and ranks with its generic word lists |

Each command reads only its own section and ignores the others, so one file serves a whole
run. A file that cannot be read, a wrong `doc_format`, an unknown key or a value of the wrong
shape exits 2 with the field named.

## Format

```json
{
  "doc_format": "domain-profile/1",
  "qualifier_terms": ["运费", "优惠券"],
  "table_name_convention": {
    "full": ["df", "da", "full", "snapshot"],
    "incremental": ["di", "hi", "inc", "incr", "delta"]
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
| `table_name_convention` | object with `full` and / or `incremental`, each a list of suffixes | a table whose last name segment ends in `_<suffix>` is `full` (each partition holds a full copy) or `incremental`. A suffix is letters and digits, written without its `_`, matched case-insensitively; `full` is tried first |
| `concept_words` | object with any of `event`, `entity`, `summary`, `measure_suffixes`, `filter_words`, each a list of strings | words added to the concept layer's generic lists: the first three are word votes for a concept's kind (Chinese as a substring, latin as a whole word), `measure_suffixes` and `filter_words` mark a name candidate as naming a measure or a slice of the concept rather than the concept (see `junk_reason` in [Key-fold candidates](ontology-doc.md)) |

Every key but `doc_format` is optional, every list adds to the built-in generic list rather
than replacing it, and an empty profile changes nothing.

## Turning the old defaults back on

Before this change the package carried a table-name suffix convention and a few lending and
payment words as defaults. A downstream project that relied on them keeps the old behaviour by
writing them into its own profile: the suffixes (`_df` / `_da` / `_full` / `_snapshot` as full,
`_di` / `_hi` / `_inc` / `_incr` / `_delta` as incremental) are exactly the
`table_name_convention` of the example above; its own qualifiers go into `qualifier_terms`,
and its own event words, measure suffixes and lifecycle filter words into `concept_words`.
Packets built with and without the convention differ in `name_convention` and `full_snapshot`,
so their `packet_digest` differs too: rebuild the packets of a run with the same profile every
time.
