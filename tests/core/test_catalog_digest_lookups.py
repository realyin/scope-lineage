"""``catalog digest --lineage``: which joined inputs a column's value is read through.

A drafter writing a code set's ``lookup.filter``, the order of a binding's ``code_sets``
and a binding's ``holds`` needs three facts the table semantics do not carry per column:
which joined inputs the value is read through and under which constant conditions, the
order a ``COALESCE`` falls back through them, and which of those reads a code column is
the join key of. The lineage already has them in its scope structure (an output source's
``input_ref_id`` and the same id on the JOIN's condition fields); the digest projects
them per column when ``--lineage`` is given, and adds nothing otherwise.

Everything here is synthetic: a generic order table, a generic code dictionary and a
generic party table, parsed with ``scope-lineage parse`` the way a corpus is.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scope_lineage.cli import main

from .catalog_demo import copy_demo, mutate
from .table_semantics_demo import CONFIRMATIONS, EXAMPLE, read_json, write_json

ORDERS = "demo_ods.ods_order_df"
DICT = "demo_dim.dim_code_dict"
PARTY = "demo_ods.ods_party_df"

T_FALLBACK = "demo_dwd.dwd_order_fallback_df"
T_FILTERED = "demo_dwd.dwd_order_filtered_df"
T_SHARED = "demo_dwd.dwd_order_shared_df"
T_VALUES = "demo_dwd.dwd_order_values_df"
T_CONFLICT = "demo_dwd.dwd_order_conflict_df"
T_PLAIN = "demo_dwd.dwd_order_plain_df"
T_CYCLE = "demo_dwd.dwd_order_cycle_df"

# The code dictionary: `dt` and `snap_day` are its partition columns. The schema says so
# for both; the lineage only says the table is partitioned, so without `--schema` only
# the `dt` name rule can recognise one of them.
SCHEMA_TABLES = {
    ORDERS: [("order_id", 0), ("c", 0), ("c2", 0), ("s", 0), ("dt", 1)],
    DICT: [
        ("code_val", 0), ("code_type", 0), ("code_desc", 0), ("dict_key", 0),
        ("kind", 0), ("lang", 0), ("dt", 1), ("snap_day", 1),
    ],
    PARTY: [("party_id", 0), ("role_type", 0), ("party_name", 0), ("dt", 1)],
    T_FALLBACK: [("order_id", 0), ("c_cd", 0), ("c_desc", 0), ("c_key", 0), ("owner_name", 0)],
    T_FILTERED: [("order_id", 0), ("s_desc", 0), ("p_name", 0), ("latest_name", 0)],
    T_SHARED: [("order_id", 0), ("x_desc", 0), ("y_desc", 0), ("z_desc", 0)],
    T_VALUES: [("order_id", 0), ("s_cd", 0), ("v_desc", 0)],
    T_CONFLICT: [("order_id", 0), ("c_cd", 0), ("f_desc", 0), ("g_desc", 0)],
    T_PLAIN: [("order_id", 0), ("p_name", 0)],
    T_CYCLE: [("order_id", 0), ("c_cd", 0), ("ab_desc", 0), ("bc_desc", 0), ("ca_desc", 0)],
}

TASKS = {
    # Tests 1-3, 9, 10. The two lookups are joined TypeB first; the COALESCE reads
    # TypeA first, and the code column must follow the COALESCE, not the JOIN order.
    "order_fallback": f"""
WITH a AS (SELECT order_id, c AS cc FROM {ORDERS} WHERE dt = '${{bizdate}}')
INSERT OVERWRITE TABLE {T_FALLBACK}
SELECT a.order_id,
       a.cc AS c_cd,
       COALESCE(d1.code_desc, d2.code_desc, a.cc) AS c_desc,
       COALESCE(d1.dict_key, a.cc) AS c_key,
       o.party_name AS owner_name
FROM a
LEFT JOIN {DICT} d2 ON a.cc = d2.code_val AND d2.code_type = 'TypeB'
LEFT JOIN {DICT} d1 ON a.cc = d1.code_val AND d1.code_type = 'TypeA'
  AND d1.dt = '20260101' /* a note on the partition */
LEFT JOIN {PARTY} o ON a.order_id = o.party_id AND o.role_type = 'Owner'
""",
    # Tests 4, 5, 7: a dictionary filtered in a joined subquery, a partition and a
    # parameterised value beside it, a main-side WHERE constant, a row-number filter.
    "order_filtered": f"""
INSERT OVERWRITE TABLE {T_FILTERED}
SELECT a.order_id, d.code_desc AS s_desc, p.party_name AS p_name, q.party_name AS latest_name
FROM {ORDERS} a
LEFT JOIN (
  SELECT code_val, code_desc FROM {DICT}
  WHERE code_type = 'TypeC' AND dt = '20260101' AND snap_day = '20260101' AND kind = '${{kind}}'
) d ON a.s = d.code_val
LEFT JOIN {PARTY} p ON a.order_id = p.party_id
LEFT JOIN (
  SELECT party_id, party_name,
         ROW_NUMBER() OVER (PARTITION BY party_id ORDER BY dt DESC) AS rn
  FROM {PARTY}
) q ON a.order_id = q.party_id AND q.rn = 1
WHERE a.c2 = 'Main'
""",
    # Tests 6, 7c: one CTE joined twice (each join keeps its own constants), a two-key
    # condition, and a constant on the joined alias written in WHERE.
    "order_shared": f"""
WITH dd AS (SELECT code_val, code_type, code_desc, kind, lang FROM {DICT})
INSERT OVERWRITE TABLE {T_SHARED}
SELECT a.order_id, x.code_desc AS x_desc, y.code_desc AS y_desc, z.code_desc AS z_desc
FROM {ORDERS} a
LEFT JOIN dd x ON a.c = x.code_val AND x.code_type = 'TypeX'
LEFT JOIN dd y ON a.c2 = y.code_val AND y.kind = 'K' AND y.lang = 'zh'
LEFT JOIN {DICT} z ON a.s = z.code_val
WHERE z.code_type = 'TypeZ'
""",
    # Test 7b: an inline VALUES dictionary, filtered in a subquery, is not a table.
    "order_values": f"""
INSERT OVERWRITE TABLE {T_VALUES}
SELECT a.order_id, a.s AS s_cd, v.code_desc AS v_desc
FROM {ORDERS} a
LEFT JOIN (
  SELECT code_val, code_desc
  FROM VALUES ('1', 'One', 'T'), ('2', 'Two', 'T') AS t(code_val, code_desc, code_type)
  WHERE code_type = 'T'
) v ON a.s = v.code_val
""",
    # Test 7d: two meaning columns fall back through the same lookups in opposite orders.
    "order_conflict": f"""
INSERT OVERWRITE TABLE {T_CONFLICT}
SELECT a.order_id, a.c AS c_cd,
       COALESCE(d1.code_desc, d2.code_desc) AS f_desc,
       COALESCE(d2.code_desc, d1.code_desc) AS g_desc
FROM {ORDERS} a
LEFT JOIN {DICT} d1 ON a.c = d1.code_val AND d1.code_type = 'TypeA'
LEFT JOIN {DICT} d2 ON a.c = d2.code_val AND d2.code_type = 'TypeB'
""",
    # Test 7d, longer: no two columns disagree, but the three orders form a cycle.
    "order_cycle": f"""
INSERT OVERWRITE TABLE {T_CYCLE}
SELECT a.order_id, a.c AS c_cd,
       COALESCE(d1.code_desc, d2.code_desc) AS ab_desc,
       COALESCE(d2.code_desc, d3.code_desc) AS bc_desc,
       COALESCE(d3.code_desc, d1.code_desc) AS ca_desc
FROM {ORDERS} a
LEFT JOIN {DICT} d1 ON a.c = d1.code_val AND d1.code_type = 'TypeA'
LEFT JOIN {DICT} d2 ON a.c = d2.code_val AND d2.code_type = 'TypeB'
LEFT JOIN {DICT} d3 ON a.c = d3.code_val AND d3.code_type = 'TypeC'
""",
    # Test 8: a join with no constant condition only supplements a field.
    "order_plain": f"""
INSERT OVERWRITE TABLE {T_PLAIN}
SELECT a.order_id, p.party_name AS p_name
FROM {ORDERS} a
LEFT JOIN {PARTY} p ON a.order_id = p.party_id
""",
}

CODE_SET_A = {
    "id": "code:type_a",
    "name": "类型甲",
    "values": [],
    "lookup": {
        "table": DICT,
        "code_column": "code_val",
        "meaning_columns": [{"column": "code_desc", "lang": "zh"}],
        "key_column": "dict_key",
        "filter": {"code_type": "TypeA"},
    },
    "status": "drafted",
    "source": "sql",
}
CODE_SET_B = {
    "id": "code:type_b",
    "name": "类型乙",
    "values": [],
    "lookup": {
        "table": DICT,
        "code_column": "code_val",
        "meaning_columns": [{"column": "code_desc", "lang": "zh"}],
        "filter": {"code_type": "TypeB"},
    },
    "status": "drafted",
    "source": "sql",
}


def _schema() -> dict:
    tables = []
    for name, columns in SCHEMA_TABLES.items():
        tables.append({
            "table_name": name,
            "table_desc": name,
            "is_partition": "1" if any(flag for _, flag in columns) else "0",
            "schema": [
                {"columnName": column, "columnType": "string", "columnComment": column,
                 "columnIndex": index, "isPartition": flag}
                for index, (column, flag) in enumerate(columns)
            ],
        })
    return {"tables": tables}


def _document(table: str) -> dict:
    """A legal table-semantics document for ``table``: the example with its columns."""
    document = copy.deepcopy(read_json(EXAMPLE))
    document["table"] = table
    columns = [column for column, _ in SCHEMA_TABLES[table]]
    document["columns"] = [
        {
            "column": column,
            "meaning": column,
            "category": "identifier" if column == "order_id" else "descriptive",
            "derivation": "直接取上游列。",
            "sources": ["sql"],
            "confidence": "high",
        }
        for column in columns
    ]
    document["summary"]["row"]["grain_columns"] = ["order_id"]
    return document


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> dict:
    root = tmp_path_factory.mktemp("lookups")
    for name, sql in TASKS.items():
        write_json(root / "tasks" / f"{name}.json", {"meta": {
            "task_id": f"task-{name}", "task_name": name, "task_type": "Spark SQL",
            "schedule_cycle": "day", "sql": sql,
        }})
    write_json(root / "schema_info.json", _schema())
    assert main([
        "parse", "--input-dir", str(root / "tasks"), "--schema", str(root / "schema_info.json"),
        "--out", str(root / "lineage"),
    ]) == 0
    docs = root / "docs"
    for table in SCHEMA_TABLES:
        if table.startswith("demo_dwd."):
            write_json(docs / f"{table}.json", _document(table))
    return {"root": root, "lineage": root / "lineage", "docs": docs,
            "schema": root / "schema_info.json"}


def _digest(corpus: dict, out: Path, *extra, docs: Path | None = None) -> dict:
    code = main([
        "catalog", "digest", str(docs or corpus["docs"]), "--out", str(out),
        *[str(arg) for arg in extra],
    ])
    assert code == 0
    return read_json(out / "digest.json")


def _columns(digest: dict, table: str) -> dict[str, dict]:
    [entry] = [entry for entry in digest["tables"] if entry["table"] == table]
    return {
        column["column"]: column
        for key, value in entry.items()
        if key.endswith("_columns") and key != "technical_columns"
        for column in value
    }


def _where(entries: list[dict]) -> list[dict]:
    return [entry["where"] for entry in entries]


@pytest.fixture(scope="module")
def digest(corpus: dict, tmp_path_factory) -> dict:
    out = tmp_path_factory.mktemp("digest")
    return _digest(corpus, out, "--lineage", corpus["lineage"])


# ------------------------------------------------------------------ 1-3 fallback order


def test_1_a_coalesce_reads_its_lookups_in_argument_order_then_falls_back(digest) -> None:
    column = _columns(digest, T_FALLBACK)["c_desc"]

    assert column["lookups"] == [
        {"table": DICT, "where": {"code_type": "TypeA"}, "reads": "code_desc",
         "rule": column["lookups"][0]["rule"]},
        {"table": DICT, "where": {"code_type": "TypeB"}, "reads": "code_desc",
         "rule": column["lookups"][1]["rule"]},
    ]
    assert column["lookups"][0]["rule"] != column["lookups"][1]["rule"]
    assert all(entry["rule"].startswith("logic:") for entry in column["lookups"])
    assert column["fallback"] == [f"{ORDERS}.c"]


def test_2_a_renamed_code_column_is_the_join_key_of_those_lookups(digest) -> None:
    column = _columns(digest, T_FALLBACK)["c_cd"]

    assert "lookups" not in column
    assert "fallback" not in column
    assert [(entry["table"], entry["where"]) for entry in column["key_of"]] == [
        (DICT, {"code_type": "TypeA"}),
        (DICT, {"code_type": "TypeB"}),
    ]
    assert "c_desc" in column["key_of"][0]["read_by"]
    assert "c_desc" in column["key_of"][1]["read_by"]
    assert "key_of_order" not in column


def test_3_the_code_column_follows_its_meaning_column_not_the_join_order(digest) -> None:
    """The JOINs are written TypeB first; the COALESCE, and so the key order, is TypeA first."""
    columns = _columns(digest, T_FALLBACK)
    lookup_rules = [entry["rule"] for entry in columns["c_desc"]["lookups"]]

    assert [entry["rule"] for entry in columns["c_cd"]["key_of"]] == lookup_rules
    assert sorted(lookup_rules) != lookup_rules  # the JOIN order would be the other one


# ------------------------------------------------------------------ 4, 5, 7 predicates


def test_4_a_dictionary_filtered_in_a_joined_subquery_is_read_with_that_filter(digest) -> None:
    column = _columns(digest, T_FILTERED)["s_desc"]

    assert [(e["table"], e["where"], e["reads"]) for e in column["lookups"]] == [
        (DICT, {"code_type": "TypeC", "snap_day": "20260101"}, "code_desc"),
    ]


def test_5_partition_parameterised_and_main_side_constants_are_not_lookups(
    corpus, tmp_path
) -> None:
    """``dt`` is judged a partition by name (the lineage marks the table partitioned);
    ``snap_day`` only by the schema; ``${kind}`` is a parameter; ``a.c2`` is the main side."""
    with_schema = _digest(
        corpus, tmp_path / "s", "--lineage", corpus["lineage"], "--schema", corpus["schema"]
    )
    columns = _columns(with_schema, T_FILTERED)

    assert _where(columns["s_desc"]["lookups"]) == [{"code_type": "TypeC"}]
    assert "lookups" not in columns["order_id"]
    assert "key_of" not in columns["order_id"]


def test_7_a_join_without_a_string_constant_is_not_a_lookup(digest) -> None:
    columns = _columns(digest, T_FILTERED)

    assert "lookups" not in columns["p_name"]  # joined by key only
    assert "lookups" not in columns["latest_name"]  # only `rn = 1`, a number
    assert "fallback" not in columns["p_name"]


# ------------------------------------------------------------------ 6, 7b, 7c, 7d


def test_6_each_join_of_one_shared_input_keeps_its_own_constants(digest) -> None:
    columns = _columns(digest, T_SHARED)

    assert _where(columns["x_desc"]["lookups"]) == [{"code_type": "TypeX"}]
    assert columns["x_desc"]["lookups"][0]["table"] == DICT
    assert columns["x_desc"]["lookups"][0]["rule"] != columns["y_desc"]["lookups"][0]["rule"]


def test_7c_two_key_conditions_and_a_where_on_the_joined_alias(digest) -> None:
    columns = _columns(digest, T_SHARED)

    assert _where(columns["y_desc"]["lookups"]) == [{"kind": "K", "lang": "zh"}]
    assert _where(columns["z_desc"]["lookups"]) == [{"code_type": "TypeZ"}]


def test_7b_an_inline_values_dictionary_is_not_published(digest) -> None:
    columns = _columns(digest, T_VALUES)

    for name in ("v_desc", "s_cd", "order_id"):
        assert not {"lookups", "fallback", "key_of"} & set(columns[name]), name


def test_7d_meaning_columns_that_disagree_leave_the_key_order_unknown(digest) -> None:
    columns = _columns(digest, T_CONFLICT)

    assert _where(columns["f_desc"]["lookups"]) == [{"code_type": "TypeA"}, {"code_type": "TypeB"}]
    assert _where(columns["g_desc"]["lookups"]) == [{"code_type": "TypeB"}, {"code_type": "TypeA"}]
    assert columns["c_cd"]["key_of_order"] == "unknown"
    assert _where(columns["c_cd"]["key_of"]) == [{"code_type": "TypeA"}, {"code_type": "TypeB"}]


def test_7d_orders_that_form_a_cycle_leave_the_key_order_unknown(digest) -> None:
    column = _columns(digest, T_CYCLE)["c_cd"]

    assert column["key_of_order"] == "unknown"
    assert _where(column["key_of"]) == [
        {"code_type": "TypeA"}, {"code_type": "TypeB"}, {"code_type": "TypeC"},
    ]


# ------------------------------------------------------------------ 8 unchanged output


def test_8_without_lineage_or_without_lookups_the_digest_is_unchanged(corpus, tmp_path) -> None:
    docs = tmp_path / "docs"
    write_json(docs / f"{T_PLAIN}.json", _document(T_PLAIN))
    write_json(docs / EXAMPLE.name, read_json(EXAMPLE))
    write_json(docs / CONFIRMATIONS.name, read_json(CONFIRMATIONS))

    _digest(corpus, tmp_path / "plain", docs=docs)
    _digest(corpus, tmp_path / "with", "--lineage", corpus["lineage"], docs=docs)

    for name in ("digest.json", "digest.md"):
        assert (tmp_path / "with" / name).read_bytes() == (tmp_path / "plain" / name).read_bytes()


def test_a_table_no_statement_writes_is_counted_and_gets_no_keys(corpus, tmp_path, capsys) -> None:
    docs = tmp_path / "docs"
    write_json(docs / f"{T_FALLBACK}.json", _document(T_FALLBACK))
    write_json(docs / EXAMPLE.name, read_json(EXAMPLE))
    write_json(docs / CONFIRMATIONS.name, read_json(CONFIRMATIONS))
    capsys.readouterr()

    digest = _digest(corpus, tmp_path / "out", "--lineage", corpus["lineage"], docs=docs)

    out = capsys.readouterr().out
    assert "1 table(s) with no writing statement in the lineage" in out
    [example] = [entry for entry in digest["tables"] if entry["table"] != T_FALLBACK]
    assert "lookups" not in str(example)
    assert "lookups" in _columns(digest, T_FALLBACK)["c_desc"]


def test_a_missing_lineage_path_exits_two(corpus, tmp_path) -> None:
    code = main([
        "catalog", "digest", str(corpus["docs"]), "--out", str(tmp_path / "out"),
        "--lineage", str(tmp_path / "nowhere"),
    ])
    assert code == 2


# ------------------------------------------------------------------ 9, 10 with a catalog


@pytest.fixture(scope="module")
def with_catalog(corpus, tmp_path_factory) -> dict:
    root = copy_demo(tmp_path_factory.mktemp("catalog"))
    mutate(root, "code_sets.yaml",
           lambda d: d["code_sets"].extend(copy.deepcopy([CODE_SET_A, CODE_SET_B])))
    out = tmp_path_factory.mktemp("digest_catalog")
    return _digest(corpus, out, "--lineage", corpus["lineage"], "--catalog", root)


def test_9_a_lookup_is_tagged_with_the_code_set_whose_table_and_filter_it_matches(
    with_catalog,
) -> None:
    columns = _columns(with_catalog, T_FALLBACK)

    assert [entry.get("code_set") for entry in columns["c_desc"]["lookups"]] == [
        "code:type_a", "code:type_b",
    ]
    assert [entry.get("code_set") for entry in columns["c_cd"]["key_of"]] == [
        "code:type_a", "code:type_b",
    ]
    owner = columns["owner_name"]["lookups"]
    assert [(e["table"], e["where"]) for e in owner] == [(PARTY, {"role_type": "Owner"})]
    assert "code_set" not in owner[0]
    # A lookup whose filter no code set has is listed, untagged.
    assert "code_set" not in _columns(with_catalog, T_SHARED)["x_desc"]["lookups"][0]


def test_10_what_a_lookup_reads_is_named_against_the_code_set(with_catalog) -> None:
    columns = _columns(with_catalog, T_FALLBACK)

    assert [entry.get("reads_as") for entry in columns["c_desc"]["lookups"]] == [
        "meaning", "meaning",
    ]
    [key] = columns["c_key"]["lookups"]
    assert (key["reads"], key["reads_as"], key["code_set"]) == ("dict_key", "key", "code:type_a")
    assert columns["c_key"]["fallback"] == [f"{ORDERS}.c"]


def test_without_a_catalog_nothing_is_tagged(digest) -> None:
    columns = _columns(digest, T_FALLBACK)

    for entry in columns["c_desc"]["lookups"] + columns["c_cd"]["key_of"]:
        assert "code_set" not in entry
        assert "reads_as" not in entry


# ------------------------------------------------------------------ markdown


def test_the_markdown_has_one_line_per_column_with_lookup_facts(with_catalog) -> None:
    from scope_lineage.catalog import render_digest_markdown

    text = render_digest_markdown(with_catalog)
    section = text.split(f"## {T_FALLBACK}")[1].split("\n## ")[0]
    lines = [line for line in section.splitlines() if line.startswith("  - ")]

    c_desc = item_line(lines, "c_desc")
    assert "reads rows of demo_dim.dim_code_dict where code_type = 'TypeA'" in c_desc
    assert c_desc.index("'TypeA'") < c_desc.index("'TypeB'")
    assert "code:type_a" in c_desc
    assert f"falls back to {ORDERS}.c" in c_desc
    c_cd = item_line(lines, "c_cd")
    assert "join key" in c_cd and "code_type = 'TypeA'" in c_cd and "c_desc" in c_cd


def item_line(lines: list[str], column: str) -> str:
    [line] = [line for line in lines if line.startswith(f"  - {column}:")]
    return line


def test_6_literals_keep_their_case(digest) -> None:
    """The lineage's display text lower-cases literals; the digest must not."""
    import json

    text = json.dumps(digest, ensure_ascii=False)
    assert "TypeA" in text and "TypeX" in text
    assert "typea" not in text and "typex" not in text
