"""Governance leads and cross-table facts a packet derives itself (D group).

- G2 ``marker_column_unused``: an input table the task reads has a logical-delete column
  (``is_deleted`` and the like, the generic naming only) that no condition and no output
  of the task reads; round 3 G1 adds a cancel flag (``is_cancel`` and the like) and a
  change-type column (``recordtype`` and the like) whose comment names at least two
  data-manipulation verbs, one a delete, in the same lead, a sentence per kind;
- G3 ``declared_key_not_used``: an input column's comment declares a composite unique
  key (``unique key ($env_$ev_id)``), and the task deduplicates or merges that table by
  part of it only -- not repeated when the MERGE already reports ``dedup_wider``;
- G4 ``header_facts.added_columns``: an ``alter table … add columns (…)`` in the script's
  header, with its date, for the target's columns;
- G5a-1 ``inputs[].producer_columns``: how a corpus task producing an input writes the
  columns this table joins, filters or windows on (its table card's summary);
- G5b ``downstream[].columns``: the columns each corpus consumer joins and filters this
  table on.

Every name is synthetic.
"""

from __future__ import annotations

from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.semantics.packet import build_packets
from scope_lineage.semantics.packet_markdown import render_packet_markdown
from scope_lineage.semantics.packet_meaning import header_facts

SCHEMA = {
    "src.ev": ["ev_id", "env", "env_ev_id", "upd", "is_deleted", "is_deleted_cnt", "recordtype",
               "v", "dt"],
    "dw.ev_out": ["ev_id", "env", "v", "flag"],
    "dim.v": ["k", "beg_d", "end_d", "name"],
    "src.v": ["k", "beg_d", "name"],
    "dw.fact": ["id", "k", "name"],
    "src.fact": ["id", "k", "d"],
    "src.ch": ["ch_id", "is_cancel", "recordtype", "op_type", "v"],
}

COMMENTS = {"env_ev_id": "unique key ($env_$ev_id)", "is_deleted": "是否删除"}


def _metadata(table: str):
    names = SCHEMA.get(table)
    if names is None:
        return None
    return {"columns": [{"name": name, "type": "string", "comment": COMMENTS.get(name, name)}
                        for name in names], "partitioned": False, "partition_columns": []}


def _pack(*sqls: str, table: str | None = None, tasks=()) -> dict:
    documents = [(to_lineage_dict(parse_scope_lineage(sql, f"t{index}", schema=SCHEMA)), None)
                 for index, sql in enumerate(sqls)]
    packets = build_packets(documents, metadata=_metadata, tasks=tasks)
    return packets[0] if table is None else next(p for p in packets if p["table"] == table)


def _leads(packet: dict, kind: str) -> list[dict]:
    return [item for item in packet["lineage"].get("findings") or [] if item["kind"] == kind]


# ------------------------------------------------------------------ G2


PLAIN = "INSERT OVERWRITE TABLE dw.ev_out SELECT e.ev_id, e.env, e.v, '' AS flag FROM src.ev e WHERE e.dt = 'x'"


def test_a_delete_marker_nobody_reads_is_a_lead() -> None:
    (lead,) = _leads(_pack(PLAIN), "marker_column_unused")
    assert lead["severity"] == "warn"
    assert (lead["task"], lead["statement_id"]) == ("t0", "stmt:001")
    assert "`src.ev.is_deleted`" in lead["text"]
    assert "is_deleted_cnt" not in lead["text"] and "recordtype" not in lead["text"]
    assert "marker_column_unused（t0 / stmt:001）" in render_packet_markdown(_pack(PLAIN))


def test_a_delete_marker_a_condition_reads_is_no_lead() -> None:
    assert _leads(_pack(PLAIN + " AND e.is_deleted = 0"), "marker_column_unused") == []


def test_a_delete_marker_an_output_reads_is_no_lead() -> None:
    sql = PLAIN.replace("'' AS flag", "CASE WHEN e.is_deleted = 1 THEN 'Y' ELSE 'N' END AS flag")
    assert _leads(_pack(sql), "marker_column_unused") == []


# ------------------------------------------------------------------ round 3 G1: cancel, change type

CH_COLUMNS = ["ch_id", "is_cancel", "recordtype", "op_type", "v"]
CH_SQL = "INSERT OVERWRITE TABLE dw.ch_out SELECT c.ch_id, c.v FROM src.ch c"
DML = "数据类型 新增(INSERT)、更新(UPSERT)，删除（DELETE）"


def _ch(sql: str = CH_SQL, **comments: str) -> dict:
    """A packet over ``src.ch`` whose column comments are ``comments`` (else the name)."""
    def metadata(table: str):
        names = {"src.ch": CH_COLUMNS, "dw.ch_out": ["ch_id", "v"]}.get(table)
        if names is None:
            return None
        return {"columns": [{"name": name, "type": "string", "comment": comments.get(name, name)}
                            for name in names], "partitioned": False, "partition_columns": []}

    schema = {"src.ch": CH_COLUMNS, "dw.ch_out": ["ch_id", "v"]}
    document = to_lineage_dict(parse_scope_lineage(sql, "t0", schema=schema))
    (packet,) = build_packets([(document, None)], metadata=metadata)
    return packet


def test_a_cancel_marker_nobody_reads_is_a_lead() -> None:
    (lead,) = _leads(_ch(is_cancel="是否作废 0：未作废 1：已作废"), "marker_column_unused")
    assert "作废标记列 `src.ch.is_cancel`" in lead["text"]
    assert "已作废的记录会照常进入" in lead["text"]
    assert lead["text"].endswith("需核实是否应过滤")


def test_a_change_type_column_listing_a_delete_is_a_lead() -> None:
    (lead,) = _leads(_ch(is_cancel="", recordtype=DML), "marker_column_unused")
    assert "疑似变更类型列 `src.ch.recordtype`" in lead["text"]
    assert "删除类记录会照常进入" in lead["text"]
    assert "is_cancel" in lead["text"]


def test_english_verbs_name_a_change_type_column_too() -> None:
    (lead,) = _leads(_ch(recordtype="I/U/D: INSERT, UPDATE, DELETE"), "marker_column_unused")
    assert "`src.ch.recordtype`" in lead["text"]


def test_a_change_type_name_without_dml_verbs_is_no_lead() -> None:
    sql = CH_SQL.replace("FROM src.ch c", "FROM src.ch c WHERE c.is_cancel = '0'")
    assert _leads(_ch(sql=sql, op_type="操作类型", recordtype=""), "marker_column_unused") == []


def test_one_dml_verb_or_none_that_deletes_is_no_change_type() -> None:
    sql = CH_SQL.replace("FROM src.ch c", "FROM src.ch c WHERE c.is_cancel = '0'")
    assert _leads(_ch(sql=sql, recordtype="删除时间"), "marker_column_unused") == []
    assert _leads(_ch(sql=sql, recordtype="Insert Timestamp, Update Time"),
                  "marker_column_unused") == []


def test_a_read_cancel_marker_is_no_lead() -> None:
    sql = CH_SQL.replace("FROM src.ch c", "FROM src.ch c WHERE c.is_cancel = '0'")
    assert _leads(_ch(sql=sql, recordtype=DML.replace("删除（DELETE）", "")),
                  "marker_column_unused") == []


def test_every_kind_of_marker_shares_one_lead_per_task() -> None:
    packet = _pack(PLAIN.replace("src.ev e", "src.ev e JOIN src.ch c ON e.ev_id = c.ch_id"))
    (lead,) = _leads(packet, "marker_column_unused")
    assert lead["text"].startswith("源表有删除标记列 `src.ev.is_deleted`，本任务没有任何条件或输出引用它："
                                   "已删除的记录会照常进入；")
    assert "作废标记列 `src.ch.is_cancel`" in lead["text"]


# ------------------------------------------------------------------ G3


def _dedup(partition: str) -> str:
    return ("INSERT OVERWRITE TABLE dw.ev_out SELECT a.ev_id, a.env, a.v, '' AS flag FROM (SELECT"
            f" ev_id, env, v, row_number() OVER (PARTITION BY {partition} ORDER BY upd DESC) rn"
            " FROM src.ev WHERE is_deleted = 0) a WHERE a.rn = 1")


def test_a_dedup_by_part_of_a_declared_key_is_a_lead() -> None:
    packet = _pack(_dedup("ev_id"))
    (lead,) = _leads(packet, "declared_key_not_used")
    (dedup,) = [rule for rule in packet["lineage"]["rules"] if rule["kind"] == "dedup"]
    assert lead["rules"] == [dedup["id"]]
    assert lead["text"] == (
        f"src.ev 的列注释声明 (env、ev_id) 唯一（作者说法），本任务在该表上按 (ev_id) 去重（{dedup['id']}），"
        "少了 env：同一 ev_id 可能对应多条源记录，需核实")


def test_a_dedup_by_the_whole_declared_key_or_its_column_is_no_lead() -> None:
    assert _leads(_pack(_dedup("env, ev_id")), "declared_key_not_used") == []
    assert _leads(_pack(_dedup("env_ev_id")), "declared_key_not_used") == []
    # A key member read inside an expression still tells its values apart.
    assert _leads(_pack(_dedup("ev_id, concat('p_', env)")), "declared_key_not_used") == []


def test_a_key_comment_without_a_template_is_no_lead() -> None:
    COMMENTS["env_ev_id"] = "上游表主键"
    try:
        assert _leads(_pack(_dedup("ev_id")), "declared_key_not_used") == []
    finally:
        COMMENTS["env_ev_id"] = "unique key ($env_$ev_id)"


def test_a_key_template_splits_into_the_tables_own_columns() -> None:
    from scope_lineage.semantics.packet_leads import _declared_members

    names = ["env", "ev_id", "env_ev_id", "v"]
    assert _declared_members("unique key ($env_$ev_id)", names) == {"env", "ev_id"}
    assert _declared_members("唯一主键（$env_ev_id）", ["env", "ev_id", "v"]) == {"env", "ev_id"}
    assert _declared_members("唯一键 ($env_$nope)", names) == set()
    assert _declared_members("说明 ($env_$ev_id)", names) == set()
    assert _declared_members("主键 ($env)", names) == set()


def _merge(using: str) -> str:
    return ("MERGE INTO dw.ev_out tgt USING (" + using + ") src ON tgt.ev_id = src.ev_id"
            " WHEN NOT MATCHED THEN INSERT *")


def test_a_merge_by_part_of_a_declared_key_is_a_lead() -> None:
    packet = _pack(_merge("SELECT ev_id, env, v, '' AS flag FROM src.ev WHERE is_deleted = 0"))
    (lead,) = _leads(packet, "declared_key_not_used")
    assert lead["statement_id"] == "stmt:001" and "rules" not in lead
    assert "按 (ev_id) 合并（stmt:001）" in lead["text"]


def test_a_merge_already_reported_dedup_wider_is_not_repeated() -> None:
    using = ("SELECT ev_id, env, v, flag FROM (SELECT ev_id, env, v, '' AS flag, row_number() OVER"
             " (PARTITION BY ev_id, v ORDER BY upd DESC) rn FROM src.ev WHERE is_deleted = 0) a"
             " WHERE a.rn = 1")
    packet = _pack(_merge(using))
    (keys,) = packet["lineage"]["keys"]
    assert keys["merge"]["coverage"] == "dedup_wider"
    assert _leads(packet, "declared_key_not_used") == []


# ------------------------------------------------------------------ G4


HEADER = ("-- 2025-01-02 someone alter table demo.t add columns (c1 string comment 'x, y',,"
          "c2 decimal(10,2), c9 int)cascade;\nINSERT OVERWRITE TABLE demo.t SELECT 1")


def test_a_header_alter_add_columns_is_recorded_for_the_targets_columns() -> None:
    facts = header_facts([], HEADER, "demo.t", ["demo.t"], ["c1", "c2", "c3"])
    assert facts["added_columns"] == [{"date": "2025-01-02", "table": "demo.t",
                                       "columns": ["c1", "c2"]}]


def test_an_alter_of_another_table_is_not_this_tables() -> None:
    facts = header_facts([], HEADER.replace("alter table demo.t", "alter table demo.other"),
                         "demo.t", ["demo.t"], ["c1", "c2"])
    assert "added_columns" not in facts


def test_an_alter_naming_the_headers_old_table_name_is_this_tables() -> None:
    sql = "-- 库表名 demo.t_old\n" + HEADER.replace("alter table demo.t", "alter table demo.t_old")
    facts = header_facts([], sql, "demo.t", ["demo.t"], ["c1"])
    assert facts["added_columns"] == [{"date": "2025-01-02", "table": "demo.t_old", "columns": ["c1"]}]


def test_the_added_columns_reach_2_1_and_4_1() -> None:
    sql = ("-- 20250102 alter table dw.ev_out add columns (flag string)\n" + PLAIN)
    packet = _pack(PLAIN, tasks=[{"name": "t0", "source_file": "t0.sql", "sql": sql}])
    (task,) = packet["tasks"]
    assert task["header_facts"]["added_columns"] == [
        {"date": "20250102", "table": "dw.ev_out", "columns": ["flag"]}]
    text = render_packet_markdown(packet)
    assert "- 头注释加列记录：20250102 加 `flag`" in text
    row = next(line for line in text.splitlines() if line.startswith("| `flag` |"))
    assert "头注释：20250102 才加入，此前写入的行该列可能为空" in row


# ------------------------------------------------------------------ G5a-1 / G5b

PRODUCER = ("INSERT OVERWRITE TABLE dim.v SELECT k, beg_d, lead(beg_d, 1, '9999') OVER"
            " (PARTITION BY k ORDER BY beg_d) AS end_d, name FROM src.v")
CONSUMER = ("INSERT OVERWRITE TABLE dw.fact SELECT f.id, f.k, d.name FROM src.fact f LEFT JOIN"
            " (SELECT * FROM dim.v WHERE beg_d <= '20260101' AND end_d > '20260101') d ON f.k = d.k")


def test_an_input_carries_how_its_producer_writes_the_columns_read_by_key() -> None:
    packet = _pack(PRODUCER, CONSUMER, table="dw.fact")
    entry = next(item for item in packet["inputs"] if item["table"] == "dim.v")
    written = {item["column"]: item for item in entry["producer_columns"]}
    assert set(written) == {"k", "beg_d", "end_d"}
    assert written["end_d"]["task"] == "t0" and written["end_d"]["statement_id"] == "stmt:001"
    assert "LEAD" in written["end_d"]["summary"]
    text = render_packet_markdown(packet)
    assert "- 生产任务怎么写这些列（表卡摘要，非本任务 SQL）：" in text
    other = next(item for item in packet["inputs"] if item["table"] == "src.fact")
    assert "producer_columns" not in other


def test_a_downstream_reader_names_the_columns_it_joins_and_filters_on() -> None:
    packet = _pack(PRODUCER, CONSUMER, table="dim.v")
    (entry,) = packet["lineage"]["downstream"]
    assert entry["columns"] == {"join_key": ["k"], "filter": ["beg_d", "end_d"]}
    text = render_packet_markdown(packet)
    assert "| 下游任务 | 写入的表 | 依据 | 读法 | 按哪些列读（关联 / 过滤） |" in text
    assert "`k`（关联）；`beg_d`、`end_d`（过滤）" in text
