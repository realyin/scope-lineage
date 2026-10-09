"""What a packet transcribes from the semantic profile, and how ``packet.md`` shows it.

The profile already settled every fact below; the packet used to drop or garble it:

- two MERGE branches writing one column with the same content are one producer
  (``branches`` lists them); branches that write different values stay apart (#19);
- a derivation step the vocabulary cannot word shows its expression, never ``None`` (#20);
- a DIRECT column whose chain computes says what the chain computes (``computed_by``);
- a positional write's SQL alias, the alias / duplicate-alias / empty-string findings,
  a CASE nobody reads, a field's lookup keys and the SQL comments on a value are carried;
- a MERGE's merge key, WHEN conditions and dedup-versus-merge-key comparison are in 4.3;
- a join without a verdict is never "not on the output path": it sits inside the right
  side of joins that have one, below an aggregate, or is simply undecided;
- comment markers are listed without meaning, and ``[db.table.col]`` references are
  checked against the run.

Every name is synthetic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.semantics.packet import build_packets
from scope_lineage.semantics.packet_markdown import render_packet_markdown

from .table_semantics_demo import demo_packets, packet_of

SCHEMA = {
    "ods.a": ["k", "x", "n"],
    "ods.log": ["k", "v", "s"],
    "ods.shop": ["s", "name"],
    "dw.t_out": ["k", "v"],
    "ods.o": ["order_id", "amount", "note", "env", "dt"],
    "dw.m": ["order_id", "amount", "note", "env", "dt"],
}


def _document(sql: str, task: str = "t", schema=None, **kwargs) -> dict:
    return to_lineage_dict(parse_scope_lineage(sql, task, schema=schema or SCHEMA, **kwargs))


def _pack(*sqls: str, schema=None, metadata=None, table: str | None = None, **kwargs) -> dict:
    documents = [
        (_document(sql, f"t{index}", schema, **kwargs), None) for index, sql in enumerate(sqls)
    ]
    packets = build_packets(documents, metadata=metadata)
    if table is None:
        return packets[0]
    return next(packet for packet in packets if packet["table"] == table)


def _producers(packet: dict, column: str) -> list[dict]:
    return next(c for c in packet["lineage"]["columns"] if c["column"] == column)["producers"]


def _rules(packet: dict, kind: str) -> list[dict]:
    return [rule for rule in packet["lineage"]["rules"] if rule["kind"] == kind]


# ------------------------------------------------------------------ #19 MERGE branches

MERGE = """MERGE INTO dw.m target USING ods.o source
ON target.order_id = source.order_id
WHEN MATCHED AND target.dt = '2025-01-01' THEN UPDATE SET target.order_id = source.order_id,
  target.amount = source.amount, target.note = coalesce(target.note, source.note)
WHEN NOT MATCHED THEN INSERT *"""


def test_two_merge_branches_writing_the_same_value_are_one_producer() -> None:
    packet = _pack(MERGE)
    for column in ("order_id", "amount"):
        (producer,) = _producers(packet, column)
        assert producer["branches"] == [
            f"dw.m.{column}（merge:matched 分支 0）", f"dw.m.{column}（merge:not_matched 分支 1）",
        ]
        assert producer["expression"] == f"`source`.`{column}`"
    text = render_packet_markdown(packet)
    assert "t0 / stmt:001（2 支：merge:matched 分支 0、merge:not_matched 分支 1）" in text


def test_merge_branches_writing_different_values_stay_apart() -> None:
    producers = _producers(_pack(MERGE), "note")
    assert len(producers) == 2
    assert all("branches" not in producer for producer in producers)


def test_a_producer_written_once_carries_no_branches() -> None:
    (producer,) = _producers(_pack(MERGE), "env")
    assert "branches" not in producer


def _lineage_row(text: str, column: str) -> list[str]:
    """The column's rows in 4.1 (other sections have rows starting with a column name too)."""
    section = text.split("### 4.1 ", 1)[1].split("\n### ", 1)[0]
    return [line for line in section.splitlines() if line.startswith(f"| `{column}` |")]


def test_a_column_only_the_not_matched_insert_writes_says_so_in_4_1() -> None:
    """B-T3b: a single-branch producer of a two-branch MERGE says which branch writes it."""
    text = render_packet_markdown(_pack(MERGE))
    (row,) = _lineage_row(text, "env")
    assert "t0 / stmt:001（仅 not_matched INSERT 写入；matched UPDATE 不改，见 4.3）" in row


def test_a_column_both_merge_branches_write_keeps_its_branches_and_no_insert_only_note() -> None:
    text = render_packet_markdown(_pack(MERGE))
    for column in ("order_id", "amount"):
        (row,) = _lineage_row(text, column)
        assert "（2 支：merge:matched 分支 0、merge:not_matched 分支 1）" in row
        assert "仅 not_matched" not in row


# ------------------------------------------------------------------ #22 MERGE in 4.3


# No target column read in an assignment: the profile then names the USING side.
MERGE_PLAIN = MERGE.replace("coalesce(target.note, source.note)", "source.note")


def test_a_merges_key_when_conditions_and_dedup_comparison_are_in_4_3() -> None:
    packet = _pack(MERGE_PLAIN)
    (keys,) = packet["lineage"]["keys"]
    merge = keys["merge"]
    assert merge["merge_keys"] == [{"target": "order_id", "source": "order_id"}]
    assert merge["coverage"] == "no_dedup"
    text = render_packet_markdown(packet)
    assert "- MERGE 合并键（t0 / stmt:001）：target.order_id = source.order_id" in text
    assert ("- MERGE WHEN（t0 / stmt:001）：matched AND `` `target`.`dt` = '2025-01-01' `` → UPDATE；"
            "not matched → INSERT *；matched 但条件不满足的行既不更新也不插入") in text
    assert "- MERGE 去重与合并键（t0 / stmt:001）：USING 无去重（driving_table_rows）" in text


def test_a_dedup_wider_than_the_merge_key_is_named() -> None:
    packet = _pack("""MERGE INTO dw.m target USING (SELECT * FROM (
  SELECT o.order_id, o.amount, o.env, o.dt,
         row_number() over(partition by o.order_id, o.env order by o.dt desc) rn
  FROM ods.o o) a WHERE rn = 1) source
ON target.order_id = source.order_id
WHEN MATCHED THEN UPDATE SET target.amount = source.amount
WHEN NOT MATCHED THEN INSERT (order_id, amount, env, dt)
  VALUES (source.order_id, source.amount, source.env, source.dt)""")
    (keys,) = packet["lineage"]["keys"]
    assert keys["merge"]["coverage"] == "dedup_wider"
    assert keys["merge"]["extra_keys"] == ["env"]
    text = render_packet_markdown(packet)
    assert "与合并键比较：dedup_wider（去重键多出 `env`" in text


def test_a_statement_that_is_no_merge_carries_no_merge_block() -> None:
    packet = _pack("INSERT OVERWRITE TABLE dw.t_out SELECT a.k, a.x AS v FROM ods.a a")
    assert all("merge" not in keys for keys in packet["lineage"]["keys"])


# ------------------------------------------------------------------ #20 / #21-d steps


def test_a_step_the_vocabulary_cannot_word_shows_its_expression() -> None:
    packet = _pack(
        "INSERT OVERWRITE TABLE dw.t_out SELECT t.k, md5(concat_ws('-', t.x, t.n)) AS v FROM ods.a t"
    )
    (producer,) = _producers(packet, "v")
    assert "None" not in producer["steps"]
    assert any(step.startswith("表达式 MD5(") for step in producer["steps"])


def test_a_direct_column_over_an_aggregate_says_what_its_chain_computes() -> None:
    packet = _pack(
        "INSERT OVERWRITE TABLE dw.t_out SELECT t.k, t.s AS v "
        "FROM (SELECT k, sum(n) s FROM ods.a GROUP BY k) t"
    )
    (producer,) = _producers(packet, "v")
    assert producer["transform"] == "DIRECT"
    assert producer["computed_by"] == ["aggregate(SUM)"]
    assert "| DIRECT（末层）；链上：aggregate(SUM) |" in render_packet_markdown(packet)
    (plain,) = _producers(packet, "k")
    assert "computed_by" not in plain


# ------------------------------------------------------------------ #25 alias, findings

PAID_SCHEMA = {"ods.o": ["order_id", "amount"], "dw.t_paid": ["order_id", "paid_amt"]}


def _target_metadata():
    from scope_lineage.metadata.target_table_metadata import (
        TargetColumnMetadata,
        TargetMetadataMap,
        TargetTableMetadata,
    )

    item = TargetTableMetadata(
        table_name="dw.t_paid",
        full_table_name="spark_catalog.dw.t_paid",
        columns=[
            TargetColumnMetadata(name="order_id", data_type="string", ordinal=0),
            TargetColumnMetadata(name="paid_amt", data_type="decimal(18,2)", ordinal=1),
        ],
        partition_columns=[],
        ddl=None,
        source_file="synthetic-target-metadata.json",
        structure_source="schema",
    )
    return TargetMetadataMap({item.table_name: item})


def test_a_positional_writes_sql_alias_and_finding_reach_the_packet() -> None:
    packet = _pack(
        "INSERT OVERWRITE TABLE dw.t_paid SELECT a.order_id, a.amount AS total_amt FROM ods.o a",
        schema=PAID_SCHEMA, target_metadata=_target_metadata(),
    )
    (producer,) = _producers(packet, "paid_amt")
    assert producer["sql_alias"] == "total_amt"
    (plain,) = _producers(packet, "order_id")
    assert "sql_alias" not in plain
    (finding,) = packet["lineage"]["findings"]
    assert (finding["kind"], finding["task"], finding["statement_id"]) == (
        "alias_position_mismatch", "t0", "stmt:001",
    )
    text = render_packet_markdown(packet)
    assert "| `paid_amt`（SQL 别名 `total_amt`，按位置写入） |" in text
    assert "目标 paid_amt ← 别名 total_amt" in text


ALIAS_SCHEMA = {"ods.buyer": ["k", "app_code"], "ods.region": ["k", "region_name"],
                "dw.t_out": ["k", "v"]}


def test_one_alias_for_two_sources_is_a_packet_finding() -> None:
    packet = _pack(
        "INSERT OVERWRITE TABLE dw.t_out SELECT b.k, b.region_name AS v FROM ods.buyer b "
        "LEFT JOIN ods.region b ON b.k = b.k",
        schema=ALIAS_SCHEMA,
    )
    (finding,) = packet["lineage"]["findings"]
    assert finding["kind"] == "duplicate_alias"
    assert "别名 b" in render_packet_markdown(packet)


def test_one_alias_in_two_scopes_is_no_finding_and_no_key() -> None:
    packet = _pack(
        "INSERT OVERWRITE TABLE dw.t_out SELECT b.k, b.v FROM ("
        " SELECT b.k, b.region_name AS v FROM ods.region b) b",
        schema=ALIAS_SCHEMA,
    )
    assert "findings" not in packet["lineage"]


TYPED_SCHEMA = {"tables": [{"table_name": "ods.x", "schema": [
    {"columnName": "k", "columnType": "bigint", "columnIndex": 0},
    {"columnName": "s", "columnType": "string", "columnIndex": 1},
]}]}


def test_an_empty_string_test_on_a_bigint_is_a_finding_on_its_rule(tmp_path: Path) -> None:
    from scope_lineage.metadata.schema_metadata import load_schema

    path = tmp_path / "schema.json"
    path.write_text(json.dumps(TYPED_SCHEMA), encoding="utf-8")
    packet = _pack(
        "INSERT OVERWRITE TABLE dw.t_out SELECT if(x.k = '', NULL, x.k) AS k, x.s AS v "
        "FROM ods.x x WHERE x.s <> ''",
        schema=load_schema(str(path)),
    )
    (finding,) = packet["lineage"]["findings"]
    assert finding["kind"] == "empty_string_on_non_string"
    (case,) = _rules(packet, "case")
    assert finding["rules"] == [case["id"]]
    row = next(line for line in render_packet_markdown(packet).splitlines()
               if line.startswith(f"| {case['id']} |"))
    assert "类型不匹配" in row and "取决于引擎" in row


# ------------------------------------------------------------------ #21-e consumed


def test_a_case_nobody_reads_is_marked_unconsumed() -> None:
    packet = _pack(
        "INSERT OVERWRITE TABLE dw.t_out SELECT a.k, a.x AS v FROM ("
        " SELECT k, x, if(x IS NULL, '', x) AS c FROM ods.a) a"
    )
    (case,) = _rules(packet, "case")
    assert case["consumed"] is False
    row = next(line for line in render_packet_markdown(packet).splitlines()
               if line.startswith(f"| {case['id']} |"))
    assert "未被消费" in row


def test_a_case_that_is_read_carries_no_consumed_key() -> None:
    packet = _pack(
        "INSERT OVERWRITE TABLE dw.t_out SELECT a.k, if(a.x IS NULL, '', a.x) AS v FROM ods.a a"
    )
    (case,) = _rules(packet, "case")
    assert "consumed" not in case


# ------------------------------------------------------------------ lookup keys, comments

LOOKUP_SCHEMA = {"src.t_a": ["id", "status"], "dw.t_out": ["id", "status_label"]}
TWO_HOPS = """WITH mapping AS (
  SELECT * FROM VALUES ('S', '0', 'M0'), ('S', '1', 'M1') AS t(mtype, src, dst)),
dict AS (SELECT * FROM VALUES ('M0', 'Zero'), ('M1', 'One') AS t(code, label))
INSERT OVERWRITE TABLE dw.t_out
SELECT a.id, coalesce(c.label, '') AS status_label FROM src.t_a a
LEFT JOIN (SELECT * FROM mapping WHERE mtype = 'S') b ON a.status = b.src
LEFT JOIN dict c ON b.dst = c.code"""


def test_a_field_read_through_a_lookup_carries_its_lookup_keys() -> None:
    packet = _pack(TWO_HOPS, schema=LOOKUP_SCHEMA)
    (producer,) = _producers(packet, "status_label")
    assert producer["lookup_keys"] == ["src.t_a.status"]
    assert "查码键（决定读哪一行，不是取值来源）：`src.t_a.status`" in render_packet_markdown(packet)
    (plain,) = _producers(packet, "id")
    assert "lookup_keys" not in plain


def test_the_sql_comments_on_a_value_and_a_rule_are_carried() -> None:
    packet = _pack(
        "INSERT OVERWRITE TABLE dw.t_out SELECT a.k /* 单号 */, a.x AS v FROM ods.a a "
        "WHERE a.n > 0 /* 只要正数 */"
    )
    (producer,) = _producers(packet, "k")
    assert producer["sql_comments"] == ["单号"]
    assert "/*" not in str(producer["expression"])
    (rule,) = _rules(packet, "filter")
    assert rule["sql_comments"] == ["只要正数"]
    text = render_packet_markdown(packet)
    assert "注释：单号" in text and "注释：只要正数" in text
    (plain,) = _producers(packet, "v")
    assert "sql_comments" not in plain


# ------------------------------------------------------------------ #21-a' undecided joins


def _join_cells(packet: dict) -> dict[str, str]:
    text = render_packet_markdown(packet)
    assert "不在输出路径上" not in text
    rows = {}
    for rule in _rules(packet, "join"):
        line = next(line for line in text.splitlines() if line.startswith(f"| {rule['id']} |"))
        rows[rule["id"]] = line.split(" | ")[6]
    return rows


def test_a_join_inside_another_joins_right_side_says_so() -> None:
    packet = _pack(
        "INSERT OVERWRITE TABLE dw.t_out SELECT a.k, d.v FROM ods.a a LEFT JOIN ("
        " SELECT x.k, y.name AS v FROM ods.log x LEFT JOIN ods.shop y ON x.s = y.s) d"
        " ON a.k = d.k"
    )
    inner, outer = _rules(packet, "join")
    assert inner["fan_out"] is None and inner["inside"] == [outer["id"]]
    assert "inside" not in outer and "below_aggregate" not in outer
    assert _join_cells(packet)[inner["id"]] == (
        f"在 {outer['id']} 右侧内部；行数影响已计入这些关联的判定"
    )


def test_a_table_joined_twice_names_both_outer_joins() -> None:
    packet = _pack(
        "WITH c AS (SELECT x.k, y.name AS v FROM ods.log x LEFT JOIN ods.shop y ON x.s = y.s) "
        "INSERT OVERWRITE TABLE dw.t_out SELECT a.k, concat(c1.v, c2.v) AS v FROM ods.a a "
        "LEFT JOIN c c1 ON a.k = c1.k LEFT JOIN c c2 ON a.x = c2.k"
    )
    inner, first, second = _rules(packet, "join")
    assert inner["inside"] == [first["id"], second["id"]]
    assert _join_cells(packet)[inner["id"]].startswith(f"在 {first['id']}、{second['id']} 右侧内部")


def test_a_join_below_an_aggregate_whose_outer_join_has_no_verdict() -> None:
    packet = _pack(
        "INSERT OVERWRITE TABLE dw.t_out SELECT t.k, max(t.v) AS v FROM ("
        " SELECT a.k, d.v FROM ods.a a LEFT JOIN ("
        "  SELECT x.k, y.name AS v FROM ods.log x LEFT JOIN ods.shop y ON x.s = y.s) d"
        "  ON a.k = d.k) t GROUP BY t.k"
    )
    inner, outer = _rules(packet, "join")
    assert inner["fan_out"] is not None and outer["fan_out"] is None
    assert outer["below_aggregate"] == "ROOT" and "inside" not in outer
    assert "below_aggregate" not in inner
    assert _join_cells(packet)[outer["id"]] == (
        "位于聚合 `ROOT` 之下：不复制输出行，可能放大聚合值；工具未判定"
    )


def test_an_undecided_join_with_nothing_to_say_is_undecided() -> None:
    from scope_lineage.semantics.packet_markdown import _fan_out

    rule = {"kind": "join", "fan_out": None, "scope": "subq:z"}
    assert _fan_out(rule) == "工具未判定（`subq:z`）"


# ------------------------------------------------------------------ #26 comments


def _metadata(table: str):
    tables = {
        "dw.t_out": {"columns": [
            {"name": "k", "type": "string",
             "comment": '订单号【updt:0】【Sec:D】【STD:Enum:"0:否","1:是"】【码表，1：女】'},
            {"name": "v", "type": "string",
             "comment": "买家号 [demo_dim.buyer_master.buyer_id]，另见 [ods.a.k]、"
                        "[ods.meta_only.c] 与 [buyer_master.buyer_id]，格式 [yyyy-MM-dd]"},
        ]},
        "ods.a": {"columns": [{"name": "k", "type": "string", "comment": "键【updt:1】"}]},
        "ods.meta_only": {"columns": [{"name": "c", "type": "string", "comment": "c"}]},
    }
    return tables.get(table)


COMMENTED = (
    "INSERT OVERWRITE TABLE dw.t_out SELECT a.k, a.x AS v FROM ods.a a",
    "INSERT OVERWRITE TABLE demo_dim.buyer_master_dc SELECT a.k, a.x FROM ods.a a",
)
COMMENT_SCHEMA = {**SCHEMA, "demo_dim.buyer_master_dc": ["buyer_id", "name"]}


@pytest.fixture(scope="module")
def commented() -> dict:
    return _pack(*COMMENTED, schema=COMMENT_SCHEMA, metadata=_metadata, table="dw.t_out")


def _target_column(packet: dict, name: str) -> dict:
    return next(column for column in packet["target"]["columns"] if column["name"] == name)


def test_comment_markers_are_listed_without_meaning(commented: dict) -> None:
    column = _target_column(commented, "k")
    assert column["comment_markers"] == [
        {"key": "updt", "value": "0"}, {"key": "Sec", "value": "D"},
        {"key": "STD", "value": 'Enum:"0:否","1:是"'},
    ]
    assert column["comment"].endswith("【码表，1：女】")
    assert commented["comment_marker_keys"] == {
        "Sec": {"count": 1, "example": "dw.t_out.k"},
        "STD": {"count": 1, "example": "dw.t_out.k"},
        "updt": {"count": 2, "example": "dw.t_out.k"},
    }
    assert "comment_markers" not in _target_column(commented, "v")
    text = render_packet_markdown(commented)
    assert "注释标记（工具不解释含义）：STD×1、Sec×1、updt×2" in text


def test_bracketed_table_references_are_checked_against_the_run(commented: dict) -> None:
    refs = _target_column(commented, "v")["comment_refs"]
    assert refs == [
        {"ref": "demo_dim.buyer_master.buyer_id", "status": "unknown",
         "near": ["demo_dim.buyer_master_dc"]},
        {"ref": "ods.a.k", "status": "in_run"},
        {"ref": "ods.meta_only.c", "status": "metadata_only"},
        {"ref": "buyer_master.buyer_id", "status": "unknown",
         "near": ["demo_dim.buyer_master_dc"]},
    ]
    assert "comment_refs" not in _target_column(commented, "k")
    text = render_packet_markdown(commented)
    assert ("引用 `demo_dim.buyer_master.buyer_id`：本运行无此表；名字相近："
            "`demo_dim.buyer_master_dc`（未证实同一张表）") in text


# ------------------------------------------------------------------ empty means absent

# The demo corpus has no shape for these; `sql_comments` and `computed_by` it does have
# (a commented projection, a DIRECT column over a function), so they are left out here.
NEW_KEYS = ("branches", "sql_alias", "lookup_keys",
            "comment_markers", "comment_marker_keys", "comment_refs", "findings",
            "inside", "below_aggregate", "consumed", "merge")


def _keys_of(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(_keys_of(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(set(), *(_keys_of(item) for item in value))
    return set()


def test_the_demo_packets_carry_none_of_the_new_keys(tmp_path: Path) -> None:
    packets = demo_packets(tmp_path)
    for path in sorted(packets.iterdir()):
        found = _keys_of(packet_of(packets, path.name)) & set(NEW_KEYS)
        assert found == set(), path.name


def test_an_only_run_resolves_a_reference_the_way_a_full_run_does(tmp_path: Path) -> None:
    """With ``--only`` a schema directory is read for the packet's tables; a reference to
    another table is read on demand, so the packet does not change."""
    from .table_semantics_demo import run, write_json

    def table(name: str, columns: dict[str, str]) -> dict:
        return {"table_name": name, "table_desc": name, "schema": [
            {"columnName": column, "columnType": "string", "columnComment": comment,
             "columnIndex": index}
            for index, (column, comment) in enumerate(columns.items())]}

    corpus = tmp_path / "corpus"
    write_json(corpus / "tasks" / "t_out.json", {"meta": {
        "task_name": "t_out",
        "sql": "INSERT OVERWRITE TABLE dw.t_out SELECT a.k, a.x AS v FROM ods.src_main a"}})
    write_json(corpus / "schema" / "dw.t_out.json",
               table("dw.t_out", {"k": "键 [ods.side_ref.c]", "v": "值"}))
    write_json(corpus / "schema" / "ods.src_main.json", table("ods.src_main", {"k": "键", "x": "值"}))
    write_json(corpus / "schema" / "ods.side_ref.json", table("ods.side_ref", {"c": "c"}))
    lineage = tmp_path / "lineage"
    assert run("parse", "--input-dir", corpus / "tasks", "--schema", corpus / "schema",
               "--out", lineage) == 0
    full, only = tmp_path / "full", tmp_path / "only"
    args = ["semantic", "packet", "--lineage", lineage, "--tasks", corpus / "tasks",
            "--schema", corpus / "schema"]
    assert run(*args, "--out", full) == 0
    assert run(*args, "--out", only, "--only", "dw.t_out") == 0
    packet = packet_of(only, "dw.t_out")
    assert packet == packet_of(full, "dw.t_out")
    assert _target_column(packet, "k")["comment_refs"] == [
        {"ref": "ods.side_ref.c", "status": "metadata_only"},
    ]


def test_a_database_name_read_as_a_table_name_suggests_nothing() -> None:
    from scope_lineage.semantics.packet_comments import References

    refs = References(["demo_dim.dim_buyer_master_dc", "demo_dwt.dwt_dim_buyer_x"], lambda _: None)
    assert refs.refs("[dim.dim_buyer_master]") == [
        {"ref": "dim.dim_buyer_master", "status": "unknown",
         "near": ["demo_dim.dim_buyer_master_dc"]},
    ]


def test_lookup_keys_are_written_the_way_sources_are() -> None:
    from scope_lineage.semantics.packet_facts import column_producer

    field = {"column": "c", "transform": "DIRECT", "sources": [],
             "lookup_keys": ["spark_catalog.src.t_a.status", "src.t_a.status"]}
    assert column_producer("t", {"statement_id": "stmt:001"}, field)["lookup_keys"] == [
        "src.t_a.status",
    ]
