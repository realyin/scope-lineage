"""What a packet says about a MERGE statement in section 4.3.

- A-M6: a MERGE has no PARTITION clause, so the contract names no partition column; the
  packet takes the target table's partition columns from the metadata, as
  ``mode: merge_row_values``, and the constants an INSERT writes into them -- from the
  ``not_matched`` branch only;
- A-M1 (README 第六节): ``proven`` is false on every MERGE row -- what the profile proves
  is the written batch, not the table;
- A-M1 / M2 / M3: the merge block's ``table_key``, the UPDATE facts and the UNION
  branches are rendered, a branch's JOINs after its dedup as rule numbers;
- A-M3: a USING side whose grain is not decided is not called "without dedup".

Every name is synthetic.
"""

from __future__ import annotations

from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.semantics.packet import build_packets
from scope_lineage.semantics.packet_markdown import _coverage, render_packet_markdown

SCHEMA = {
    "dw.m": ["k", "env", "v", "note", "src_tag", "dt"],
    "ods.s": ["k", "sk", "env", "v", "ts", "dt"],
    "ods.lk": ["k", "note"],
    "dw.t_out": ["k", "v", "dt"],
}


def _metadata(table: str):
    names = SCHEMA.get(table)
    if names is None:
        return None
    partitions = {"dw.m": ["src_tag", "dt"], "dw.t_out": ["dt"]}.get(table, [])
    return {"columns": [{"name": name, "type": "string"} for name in names],
            "partitioned": bool(partitions), "partition_columns": partitions}


def _pack(sql: str) -> dict:
    document = to_lineage_dict(parse_scope_lineage(sql, "t", schema=SCHEMA))
    (packet,) = build_packets([(document, None)], metadata=_metadata)
    return packet


def _lines(packet: dict, prefix: str) -> list[str]:
    return [line for line in render_packet_markdown(packet).splitlines() if line.startswith(prefix)]


DEDUP_MERGE = (
    "MERGE INTO dw.m tgt USING (SELECT k, env, v, note, 'p1' AS src_tag, dt FROM (SELECT k, env,"
    " v, '' AS note, dt, row_number() OVER (PARTITION BY k ORDER BY ts DESC) rn FROM ods.s) a"
    " WHERE a.rn = 1) src ON tgt.k = src.k"
    " WHEN MATCHED THEN UPDATE SET tgt.v = src.v, tgt.src_tag = 'p9'"
    " WHEN NOT MATCHED THEN INSERT *"
)


# ------------------------------------------------------------------ A-M6 partitions


def test_a_merge_writes_the_targets_partition_columns_row_by_row() -> None:
    (partition,) = _pack(DEDUP_MERGE)["lineage"]["partition"]
    assert partition["columns"] == ["src_tag", "dt"]
    assert partition["mode"] == "merge_row_values"
    # The INSERT writes the USING side's constant; the UPDATE's own constant is no
    # partition an inserted row lands in.
    assert partition["select_values"] == {"src_tag": ["'p1'"]}
    (line,) = _lines(_pack(DEDUP_MERGE), "- 分区写入")
    assert "MERGE 无 PARTITION 子句：按写入行的分区列值落分区" in line
    assert "INSERT 写常量：src_tag = `'p1'`" in line


def test_an_update_only_merge_names_its_partitions_and_no_constant() -> None:
    (partition,) = _pack(
        "MERGE INTO dw.m tgt USING (SELECT k, v FROM ods.s) src ON tgt.k = src.k"
        " WHEN MATCHED THEN UPDATE SET tgt.v = src.v, tgt.src_tag = 'p9'"
    )["lineage"]["partition"]
    assert (partition["columns"], partition["mode"]) == (["src_tag", "dt"], "merge_row_values")
    assert "select_values" not in partition


def test_an_insert_overwrites_partition_clause_is_kept() -> None:
    (partition,) = _pack(
        "INSERT OVERWRITE TABLE dw.t_out PARTITION (dt) SELECT k, v, dt FROM ods.s"
    )["lineage"]["partition"]
    assert (partition["columns"], partition["mode"]) == (["dt"], "dynamic")


def test_a_merge_into_an_unpartitioned_table_names_no_partition() -> None:
    document = to_lineage_dict(parse_scope_lineage(DEDUP_MERGE, "t", schema=SCHEMA))
    (packet,) = build_packets([(document, None)])
    (partition,) = packet["lineage"]["partition"]
    assert (partition["columns"], partition["mode"]) == ([], None)


# ------------------------------------------------------------------ A-M1 proven


def test_a_merge_row_is_never_proven_but_its_confidence_stays() -> None:
    (keys,) = _pack(DEDUP_MERGE)["lineage"]["keys"]
    assert keys["key_confidence"] == "proven"
    assert keys["proven"] is False


def test_an_insert_row_keeps_proven() -> None:
    (keys,) = _pack(
        "INSERT OVERWRITE TABLE dw.t_out PARTITION (dt) SELECT k, max(v) AS v, dt FROM ods.s"
        " GROUP BY k, dt"
    )["lineage"]["keys"]
    assert keys["proven"] is (keys["key_confidence"] == "proven")
    assert keys["proven"] is True


# ------------------------------------------------------------------ 4.3 lines


def test_the_table_key_a_merge_suggests_is_said_to_be_inferred() -> None:
    (line,) = _lines(_pack(DEDUP_MERGE), "- MERGE 后目标表的")
    assert line == "- MERGE 后目标表的候选键（t / stmt:001）：`k`（按 ON 合并键与 USING 去重键推断，未证明）"


def test_an_update_only_merge_does_not_decide_the_grain_and_lists_what_it_changes() -> None:
    packet = _pack(
        "MERGE INTO dw.m tgt USING (SELECT k, v, env FROM ods.s) src ON tgt.k = src.k"
        " WHEN MATCHED THEN UPDATE SET tgt.v = src.v, tgt.env = src.env"
    )
    assert _lines(packet, "- MERGE 后目标表的") == [
        "- MERGE 后目标表的键（t / stmt:001）：只更新已有行、不新增行，本语句不决定目标表的行粒度"]
    assert _lines(packet, "- MERGE matched UPDATE 只改") == [
        "- MERGE matched UPDATE 只改（t / stmt:001）：`v`、`env`，其余列保持原值"]


def test_what_an_update_leaves_alone_and_may_blank_out_is_said() -> None:
    packet = _pack(
        "MERGE INTO dw.m tgt USING (SELECT s.k, s.env, s.v, l.note, 'p1' AS src_tag, s.dt"
        " FROM ods.s s LEFT JOIN ods.lk l ON s.k = l.k) src ON tgt.k = src.k"
        " WHEN MATCHED THEN UPDATE SET tgt.v = src.v, tgt.note = src.note,"
        " tgt.env = coalesce(src.env, tgt.env), tgt.src_tag = src.src_tag"
        " WHEN NOT MATCHED THEN INSERT *"
    )
    assert _lines(packet, "- MERGE matched UPDATE 不改的列") == [
        "- MERGE matched UPDATE 不改的列（t / stmt:001）：`dt`（只在首次 INSERT 时写入，之后不随更新变化）"]
    assert _lines(packet, "- MERGE matched UPDATE 可能写入空值") == [
        "- MERGE matched UPDATE 可能写入空值（t / stmt:001）：`note` 来自 LEFT JOIN，"
        "本次关联未命中时会把已有值覆盖成 NULL"]


def test_union_branches_are_listed_with_their_joins_as_rule_numbers() -> None:
    packet = _pack(
        "MERGE INTO dw.m tgt USING (SELECT a.k, a.env, a.v, l.note, 'p1' AS src_tag, a.dt FROM"
        " (SELECT k, env, v, dt, row_number() OVER (PARTITION BY k ORDER BY ts DESC) rn"
        " FROM ods.s) a LEFT JOIN ods.lk l ON a.k = l.k WHERE a.rn = 1"
        " UNION ALL SELECT k, env, v, '' note, 'p2' AS src_tag, dt FROM ods.s) src"
        " ON tgt.k = src.k WHEN NOT MATCHED THEN INSERT *"
    )
    (keys,) = packet["lineage"]["keys"]
    first, second = keys["merge"]["union_branches"]
    (join,) = [rule for rule in packet["lineage"]["rules"] if rule["kind"] == "join"]
    assert first["joins_after_dedup"] == [join["id"]]
    assert "joins_after_dedup" not in second
    (line,) = _lines(packet, "- MERGE 去重与合并键")
    assert line == (
        "- MERGE 去重与合并键（t / stmt:001）：USING 是 UNION，逐分支：分支 1 按 `k` 去重（unknown；"
        f"去重之后还有未证明唯一的关联 {join['id']}）；分支 2 无去重（driving_table_rows）；"
        "分支之间没有去重：同一合并键可能在不同分支各出一行；与合并键比较：unknown（工具无法比较）")


def test_an_undecided_using_side_is_not_called_one_without_dedup() -> None:
    merge = {"using_grain": {"basis": "unknown"}, "coverage": "unknown"}
    assert _coverage(merge).startswith("USING 粒度未判定（unknown）；")
    merge = {"using_grain": {"basis": "driving_table_rows"}, "coverage": "no_dedup"}
    assert _coverage(merge).startswith("USING 无去重（driving_table_rows）；")
