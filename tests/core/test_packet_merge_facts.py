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

Round 3:

- M2: a column only some UNION branches may blank out is said with those branches, and a
  column a branch fills with a literal on a miss (``update_filled_on_miss``) on its own
  line;
- M3: ``partition[].merge_columns`` says per partition column whether the UPDATE leaves
  it (``keeps``), writes it (``writes``) or is absent (``none``), whether it is a merge
  key, and the value a matched condition pins it to -- then no old partition is
  rewritten;
- M4a: two USING rows of one merge key are followed by what the statement's own WHEN
  clauses do (no matched sentence for an INSERT-only MERGE);
- M4b: a USING side read from a table whose writer keys its batch on more columns.

Every name is synthetic.
"""

from __future__ import annotations

from scope_lineage import parse_task_lineage
from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.contract.task_lineage import to_task_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.semantics.packet import build_packets
from scope_lineage.semantics.packet_markdown import (
    _coverage,
    _update_facts,
    render_packet_markdown,
)

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
        "分支之间没有去重：同一合并键可能在不同分支各出一行，目标里没有的合并键会按 USING 行数重复插入；"
        "与合并键比较：unknown（工具无法比较）")


def test_an_undecided_using_side_is_not_called_one_without_dedup() -> None:
    merge = {"using_grain": {"basis": "unknown"}, "coverage": "unknown"}
    assert _coverage(merge).startswith("USING 粒度未判定（unknown）；")
    merge = {"using_grain": {"basis": "driving_table_rows"}, "coverage": "no_dedup"}
    assert _coverage(merge).startswith("USING 无去重（driving_table_rows）；")


# ------------------------------------------------------------------ round 3 M2: per branch

UNION_UPDATE = (
    "MERGE INTO dw.m tgt USING (SELECT a.k, a.env, a.v, coalesce(l.note, '') AS note,"
    " 'p1' AS src_tag, a.dt FROM ods.s a LEFT JOIN ods.lk l ON a.k = l.k"
    " UNION ALL SELECT b.k, b.env, b.v, l2.note AS note, 'p2' AS src_tag, b.dt"
    " FROM ods.s b LEFT JOIN ods.lk l2 ON b.k = l2.k) src ON tgt.k = src.k"
    " WHEN MATCHED THEN UPDATE SET tgt.note = src.note WHEN NOT MATCHED THEN INSERT *"
)


def test_a_column_only_one_branch_may_blank_out_is_said_per_branch() -> None:
    packet = _pack(UNION_UPDATE)
    (keys,) = packet["lineage"]["keys"]
    assert keys["merge"]["update_nullable_by_join_branches"] == {"note": [2]}
    assert _lines(packet, "- MERGE matched UPDATE 可能写入空值") == [
        "- MERGE matched UPDATE 可能写入空值（t / stmt:001）：`note` 只在 USING 的 UNION 分支 2 来自"
        " LEFT JOIN：这些分支的行本次关联未命中时，会把已有值覆盖成 NULL"]


def test_a_column_a_branch_fills_on_a_miss_is_said_with_its_value() -> None:
    assert _lines(_pack(UNION_UPDATE), "- MERGE matched UPDATE 关联未命中时写回填值") == [
        "- MERGE matched UPDATE 关联未命中时写回填值（t / stmt:001）：`note`（分支 1 写 `''`）："
        "本次关联未命中时会把已有值覆盖成该值"]


def test_whole_and_per_branch_columns_share_one_line() -> None:
    merge = {"update_nullable_by_join": ["a"],
             "update_nullable_by_join_branches": {"b": [3], "c": [1, 2], "d": [3]},
             "update_filled_on_miss": [{"column": "e", "value": "0"},
                                       {"column": "f", "value": "''", "branches": [1, 2]},
                                       {"column": "f", "value": "'x'", "branches": [3]}]}
    blank, filled = _update_facts(merge, "（t / s）")
    assert blank == (
        "- MERGE matched UPDATE 可能写入空值（t / s）：`a` 来自 LEFT JOIN，本次关联未命中时会把已有值"
        "覆盖成 NULL；`b`、`d` 只在 USING 的 UNION 分支 3 来自 LEFT JOIN：这些分支的行本次关联未命中时，"
        "会把已有值覆盖成 NULL；`c` 只在 USING 的 UNION 分支 1、2 来自 LEFT JOIN：这些分支的行本次关联"
        "未命中时，会把已有值覆盖成 NULL")
    assert filled == (
        "- MERGE matched UPDATE 关联未命中时写回填值（t / s）：`e`（写 `0`）、`f`（分支 1、2 写 `''`；"
        "分支 3 写 `'x'`）：本次关联未命中时会把已有值覆盖成该值")


# ------------------------------------------------------------------ round 3 M3: partitions


def _partition(sql: str) -> tuple[dict, str]:
    packet = _pack(sql)
    (partition,) = packet["lineage"]["partition"]
    (line,) = _lines(packet, "- 分区写入")
    return partition, line


USING = "USING (SELECT k, env, v, note, 'p1' AS src_tag, dt FROM ods.s) src"


def test_an_update_that_leaves_a_pinned_partition_column_says_old_partitions_stay() -> None:
    partition, line = _partition(
        f"MERGE INTO dw.m tgt {USING} ON tgt.k = src.k"
        " WHEN MATCHED AND tgt.dt = '20260101' THEN UPDATE SET tgt.v = src.v"
        " WHEN NOT MATCHED THEN INSERT *")
    assert partition["merge_columns"] == {
        "src_tag": {"update": "keeps", "key": False},
        "dt": {"update": "keeps", "key": False, "pinned": "'20260101'"},
    }
    assert line.startswith("- 分区写入（t / stmt:001）：`src_tag`、`dt`，MERGE 无 PARTITION 子句："
                           "按写入行的分区列值落分区")
    assert ("`dt`：matched UPDATE 不改 dt：被更新的已有行留在原分区；matched 条件限定 target.dt = "
            "`'20260101'`：只有 dt = `'20260101'` 的已有行会被更新，同一合并键落在其他分区的已有行"
            "既不更新、也不会再插入（本次 USING 行被丢弃），旧分区不被本语句改写") in line
    assert ("`src_tag`：matched UPDATE 不改 src_tag：被更新的已有行留在原分区，本语句会改写旧分区里的行"
            ) in line
    assert "UPDATE 不改该列时行留在原分区" not in line
    assert "INSERT 写常量：src_tag = `'p1'`" in line


def test_an_update_that_writes_a_partition_column_moves_the_row() -> None:
    partition, line = _partition(
        f"MERGE INTO dw.m tgt {USING} ON tgt.k = src.k"
        " WHEN MATCHED THEN UPDATE SET tgt.v = src.v, tgt.dt = src.dt"
        " WHEN NOT MATCHED THEN INSERT *")
    assert partition["merge_columns"]["dt"] == {"update": "writes", "key": False}
    assert ("`dt`：matched UPDATE 也写 dt：已有行的 dt 与本次写入值不同时，行换到新值对应的分区"
            ) in line


def test_a_written_and_pinned_partition_column_moves_only_rows_of_that_value() -> None:
    partition, line = _partition(
        f"MERGE INTO dw.m tgt {USING} ON tgt.k = src.k"
        " WHEN MATCHED AND tgt.dt = '20260101' THEN UPDATE SET tgt.v = src.v, tgt.dt = src.dt"
        " WHEN NOT MATCHED THEN INSERT *")
    assert partition["merge_columns"]["dt"] == {"update": "writes", "key": False,
                                                "pinned": "'20260101'"}
    assert ("`dt`：matched UPDATE 也写 dt，但 matched 条件限定 target.dt = `'20260101'`：只有 dt = "
            "`'20260101'` 的已有行会被更新，其中 USING 的 dt 不同的行换到新值的分区；其他分区的同键行"
            "既不更新、也不会再插入（本次 USING 行被丢弃），旧分区不被本语句改写") in line


def test_an_insert_only_merge_leaves_existing_rows_alone() -> None:
    partition, line = _partition(f"MERGE INTO dw.m tgt {USING} ON tgt.k = src.k"
                                 " WHEN NOT MATCHED THEN INSERT *")
    assert partition["merge_columns"]["dt"] == {"update": "none", "key": False}
    assert "`dt`：只插入新行，已有行不动" in line


def test_a_partition_column_in_the_merge_key_keeps_its_value() -> None:
    partition, line = _partition(
        f"MERGE INTO dw.m tgt {USING} ON tgt.k = src.k AND tgt.dt = src.dt"
        " WHEN MATCHED THEN UPDATE SET tgt.v = src.v WHEN NOT MATCHED THEN INSERT *")
    assert partition["merge_columns"]["dt"]["key"] is True
    assert "`dt`：合并键列，matched 行上 ON 保证 dt 不变，行留在原分区" in line


def test_an_insert_overwrite_has_no_merge_columns() -> None:
    (partition,) = _pack(
        "INSERT OVERWRITE TABLE dw.t_out PARTITION (dt) SELECT k, v, dt FROM ods.s"
    )["lineage"]["partition"]
    assert "merge_columns" not in partition


# ------------------------------------------------------------------ round 3 M4a: consequences

BOTH = [{"clause": "matched", "action": "update"}, {"clause": "not_matched", "action": "insert"}]
MATCHED = "matched 分支会遇到多个 USING 行匹配同一目标行（通常报错终止，引擎行为，推断）"
INSERTED = "目标里没有的合并键会按 USING 行数重复插入"


def test_no_dedup_says_what_both_branches_do_with_two_rows_of_a_key() -> None:
    said = _coverage({"using_grain": {"basis": "driving_table_rows"}, "coverage": "no_dedup",
                      "whens": BOTH})
    assert said.endswith(f"no_dedup（USING 侧没有去重，同一合并键可能有多行：{MATCHED}，{INSERTED}）")


def test_an_update_only_merge_says_the_matched_consequence_only() -> None:
    said = _coverage({"using_grain": {"basis": "driving_table_rows"}, "coverage": "no_dedup",
                      "whens": BOTH[:1]})
    assert MATCHED in said and INSERTED not in said


def test_an_insert_only_merge_never_says_matched() -> None:
    said = _coverage({"using_grain": {"basis": "window_partition"}, "coverage": "dedup_wider",
                      "dedup_keys": [{"column": "k"}, {"column": "env"}], "extra_keys": ["env"],
                      "whens": BOTH[1:]})
    assert "matched" not in said
    assert said.endswith(f"dedup_wider（去重键多出 `env`：同一合并键在 USING 侧可能多行，{INSERTED}）")


def test_a_covered_or_undecided_merge_says_no_consequence() -> None:
    for coverage in ("covered", "unknown"):
        said = _coverage({"using_grain": {"basis": "window_partition"}, "coverage": coverage,
                          "whens": BOTH})
        assert MATCHED not in said and INSERTED not in said


# ------------------------------------------------------------------ round 3 M4b: writer keys


def test_a_using_side_read_from_a_table_its_writer_keys_wider_is_said() -> None:
    schema = {"ods.feed": ["k", "env", "d", "v", "ts"], "dw.ver": ["k", "env", "d", "v"]}
    sql = (
        "INSERT INTO dw.ver SELECT k, env, d, v FROM (SELECT k, env, d, v, row_number() OVER ("
        "PARTITION BY k, env, d ORDER BY ts DESC) rn FROM ods.feed) a WHERE a.rn = 1;\n"
        "MERGE INTO dw.ver t USING (SELECT * FROM dw.ver) s ON t.k = s.k AND t.d = s.d "
        "WHEN MATCHED THEN UPDATE SET t.v = s.v"
    )
    document = to_task_lineage_dict(parse_task_lineage(sql, "task", schema=schema))
    (packet,) = build_packets([(document, None)])
    (line,) = _lines(packet, "- MERGE USING 与写入方的键")
    assert line == (
        "- MERGE USING 与写入方的键（task / stmt:002）：USING 读 `dw.ver` 的行；写 dw.ver 的 stmt:001"
        " 本批写入键是 `k`、`env`、`d`（推断为行的区分键），比合并键多出 `env`：同一合并键在 USING 侧"
        f"可能多行，{MATCHED}")
