"""The input facts a packet hands a writer: partition reads, date filters, task context.

- a partition equality written in a JOIN's ON reads one partition of the right table, as a
  WHERE would -- unless the join keeps every right row (RIGHT / FULL OUTER);
- ``full_snapshot`` is rendered with *why* it is false: not partitioned, no partition
  condition seen, several partitions read, or a name convention that is not ``full``;
- each business-date filter carries the statement it sits in and its ``shape``: an as-of
  pair (``beg <= D AND end > D``), an upper bound, a NULL check, or a window -- and only a
  window makes check 9 doubt a snapshot;
- a dynamic partition the SELECT fills with constants names them;
- a JOIN whose ON has no key pair still names the tables it touches;
- a header comment about another table of the same task is marked ``about`` and not asked
  for (check 13); an upstream producer's header (primary key, storage, partitioning) is
  carried on the input as the author's claim;
- a registered upstream task that no table the task reads matches is listed;
- the task's expected run date, and how far each date literal in its SQL sits from it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scope_lineage.semantics.checks_context import check_time

from .table_semantics_demo import (
    demo_packets,
    pack,
    packet_of,
    parse_corpus,
    write_json,
)


def _column(name: str, index: int, partition: int = 0) -> dict:
    return {"columnName": name, "columnType": "string", "columnComment": name,
            "columnIndex": index, "isPartition": partition}


def _table(name: str, columns: list[str], partitions: tuple[str, ...] = ()) -> dict:
    schema = [_column(column, index) for index, column in enumerate(columns)]
    schema += [_column(name, len(columns) + i, partition=1) for i, name in enumerate(partitions)]
    return {"table_name": name, "table_desc": name, "is_partition": 1 if partitions else 0,
            "schema": schema}


SCHEMA = {"tables": [
    _table("demo_ods.ods_ticket_df",
           ["ticket_no", "cust_no", "code", "alt_code", "open_date", "close_date"], ("dt",)),
    _table("demo_ods.ods_rate_df", ["cust_no", "rate"], ("dt",)),
    _table("demo_dim.dim_code_dc", ["code", "code_name", "eff_beg_date", "eff_end_date"]),
    _table("demo_dwd.dwd_ticket_df", ["ticket_no", "code_name", "rate"], ("dt",)),
    _table("demo_dwd.dwd_ticket_new_di", ["ticket_no", "code_name"], ("dt",)),
    _table("demo_dwd.dwd_ticket_src_df", ["ticket_no"], ("dt", "src")),
    _table("demo_dwd.dwd_rate_hist_df", ["cust_no", "rate"], ("dt",)),
    _table("demo_dwd.dwd_ticket_code_df", ["ticket_no", "code_name"]),
    _table("demo_tmp.tmp_x", ["x_key", "x_name"]),
    _table("demo_dim.dim_x", ["x_key", "x_name"]),
    _table("demo_dwd.dwd_x_use_df", ["x_key", "x_name", "tmp_name"]),
    _table("demo_dwd.dwd_ticket_snap_df", ["ticket_no"], ("dt",)),
]}

TASKS = {
    # An as-of pair, an upper bound and a NULL check on a snapshot; a RIGHT JOIN's ON
    # partition condition; registered upstreams, one matched only by its prefixed name.
    "dwd_ticket_daily": ({
        "upstream_tasks": ["ods_ticket_df", "x_rt_demo_ods_ods_rate_df", "ods_never_read_df"],
    }, """-- 库表名 demo_dwd.dwd_ticket_old_df
-- 生命周期 30天
INSERT OVERWRITE TABLE demo_dwd.dwd_ticket_df PARTITION (dt = '${bizdate}')
SELECT t.ticket_no, d.code_name, r.rate
FROM demo_ods.ods_ticket_df t
LEFT JOIN (SELECT code, code_name FROM demo_dim.dim_code_dc
           WHERE eff_beg_date <= '${bizdate}' AND eff_end_date > '${bizdate}') d
       ON t.code = d.code
RIGHT JOIN demo_ods.ods_rate_df r ON t.cust_no = r.cust_no AND r.dt = '${bizdate}'
WHERE t.dt = '${bizdate}' AND substr(t.open_date, 1, 10) <= '${bizdate}'
  AND t.close_date IS NOT NULL"""),
    # Windows: a lower bound, and an as-of pair whose two constants differ.
    "dwd_ticket_new_daily": ({}, """INSERT OVERWRITE TABLE demo_dwd.dwd_ticket_new_di PARTITION (dt = '${bizdate}')
SELECT t.ticket_no, d.code_name
FROM demo_ods.ods_ticket_df t
LEFT JOIN (SELECT code, code_name FROM demo_dim.dim_code_dc
           WHERE eff_beg_date <= '${bizdate}' AND eff_end_date > '${yesterday}') d
       ON t.code = d.code
WHERE t.dt = '${bizdate}' AND substr(t.open_date, 1, 10) >= '${bizdate}'"""),
    "dwd_ticket_src_daily": ({}, """INSERT OVERWRITE TABLE demo_dwd.dwd_ticket_src_df PARTITION (dt, src)
SELECT t.ticket_no, '${bizdate}' AS dt, 'a' AS src FROM demo_ods.ods_ticket_df t
WHERE t.dt = '${bizdate}'
UNION ALL
SELECT r.cust_no, '${bizdate}', 'b' FROM demo_ods.ods_rate_df r WHERE r.dt = '${bizdate}'"""),
    "dwd_rate_hist_daily": ({}, """INSERT OVERWRITE TABLE demo_dwd.dwd_rate_hist_df PARTITION (dt)
SELECT cust_no, rate, dt FROM demo_ods.ods_rate_df WHERE dt >= '${bizdate}'"""),
    "dwd_ticket_code_daily": ({}, """INSERT OVERWRITE TABLE demo_dwd.dwd_ticket_code_df
SELECT t.ticket_no, d.code_name FROM demo_ods.ods_ticket_df t
LEFT JOIN demo_dim.dim_code_dc d ON IF(COALESCE(t.code, '') = '', t.alt_code, t.code) = d.code
WHERE t.dt = '${bizdate}'"""),
    # One task, two tables: the header describes the second.
    "dim_x_dc": ({"upstream_tasks": ["ods_rate_df", "ods_ticket_df"]}, """-- 库表名 demo_dim.dim_x
-- 主键 x_key
-- 存储设计 拉链表
-- 数据规模 100
INSERT OVERWRITE TABLE demo_tmp.tmp_x
SELECT cust_no AS x_key, rate AS x_name FROM demo_ods.ods_rate_df WHERE dt = '${bizdate}';
INSERT OVERWRITE TABLE demo_dim.dim_x
SELECT t.ticket_no AS x_key, x.x_name FROM demo_ods.ods_ticket_df t
JOIN demo_tmp.tmp_x x ON t.cust_no = x.x_key WHERE t.dt = '${bizdate}'"""),
    "dwd_x_use_daily": ({}, """INSERT OVERWRITE TABLE demo_dwd.dwd_x_use_df
SELECT d.x_key, d.x_name, t.x_name AS tmp_name FROM demo_dim.dim_x d
LEFT JOIN demo_tmp.tmp_x t ON d.x_key = t.x_key"""),
    # A run-instance SQL: literals where a parameter was, one more in each kind of comment.
    "dwd_ticket_snap_daily": ({"expect_date": "2025-01-16"}, """-- 补数 '20250101'
INSERT OVERWRITE TABLE demo_dwd.dwd_ticket_snap_df PARTITION (dt = '20250115')
SELECT t.ticket_no FROM demo_ods.ods_ticket_df t
WHERE t.dt = '20250115' AND t.close_date < '99991231' /* '20240101' */"""),
}


@pytest.fixture(scope="module")
def packets(tmp_path_factory) -> Path:
    work = tmp_path_factory.mktemp("inputs")
    corpus = work / "corpus"
    for name, (meta, sql) in TASKS.items():
        write_json(corpus / "tasks" / f"{name}.json", {"meta": {
            "task_name": name, "schedule_cycle": "day", "sql": sql, **meta,
        }})
    write_json(corpus / "schema_info.json", SCHEMA)
    lineage = parse_corpus(corpus, work / "lineage")
    assert pack(corpus, lineage, work / "packets") == 0
    return work / "packets"


@pytest.fixture(scope="module")
def demo(tmp_path_factory) -> Path:
    return demo_packets(tmp_path_factory.mktemp("demo"))


def _markdown(packets: Path, table: str) -> str:
    return (packets / table / "packet.md").read_text(encoding="utf-8")


def _input(packet: dict, table: str) -> dict:
    return next(item for item in packet["inputs"] if item["table"] == table)


def _joins(packet: dict, right: str) -> list[dict]:
    return [r for r in packet["lineage"]["rules"] if r["kind"] == "join" and r["right"] == right]


def _snapshot_doc() -> dict:
    return {"summary": {"refresh": {"time": "snapshot", "how_to_read": ""}, "watch": []}}


# ------------------------------------------------------------------ #18 ON partitions


def test_a_partition_equality_in_a_left_joins_on_reads_one_partition(demo: Path) -> None:
    packet = packet_of(demo, "demo_dwd.dwd_lending_borrower_df")
    credit = _input(packet, "demo_ods.ods_credit_limit_df")
    assert (credit["partition_read"], credit["partition_filters"], credit["full_snapshot"]) == (
        "equality", ["`cr`.`dt` = '${bizdate}'"], True,
    )
    (join,) = _joins(packet, "demo_ods.ods_credit_limit_df")
    assert join["partition_reads"] == [{
        "table": "demo_ods.ods_credit_limit_df", "expression": "`cr`.`dt` = '${bizdate}'",
        "basis": "metadata",
    }]
    assert not any(key.startswith("_") for key in join)


def test_the_markdown_marks_a_joins_partition_read_on_the_right_table(demo: Path) -> None:
    text = _markdown(demo, "demo_dwd.dwd_lending_borrower_df")
    assert "| 是（右表 `` `cr`.`dt` = '${bizdate}' ``） |" in text


def test_a_right_joins_on_condition_does_not_read_a_partition(packets: Path) -> None:
    packet = packet_of(packets, "demo_dwd.dwd_ticket_df")
    rate = _input(packet, "demo_ods.ods_rate_df")
    assert (rate["partition_read"], rate["partition_filters"]) == ("none", [])
    (join,) = _joins(packet, "demo_ods.ods_rate_df")
    assert "partition_reads" not in join


def test_a_join_without_partition_conditions_carries_no_partition_reads(demo: Path) -> None:
    packet = packet_of(demo)
    assert all("partition_reads" not in rule for rule in packet["lineage"]["rules"])


@pytest.mark.parametrize(("entry", "said"), [
    ({"partitioned": True, "partition_columns": ["dt"], "partition_read": "equality",
      "name_convention": "full", "full_snapshot": True}, "是"),
    ({"partitioned": False, "partition_columns": [], "partition_read": "none",
      "name_convention": "full", "full_snapshot": False}, "不适用（非分区表）"),
    ({"partitioned": True, "partition_columns": ["dt"], "partition_read": "none",
      "name_convention": "full", "full_snapshot": False}, "未证明（未见分区条件）"),
    ({"partitioned": True, "partition_columns": ["dt"], "partition_read": "range",
      "name_convention": "full", "full_snapshot": False}, "否（读多个分区 / 范围）"),
    ({"partitioned": True, "partition_columns": ["dt"], "partition_read": "equality",
      "name_convention": "incremental", "full_snapshot": False},
     "未证明（表名约定 incremental）"),
])
def test_full_snapshot_says_why_it_is_not_proven(entry: dict, said: str) -> None:
    from scope_lineage.semantics.packet_markdown import full_snapshot_text

    assert full_snapshot_text(entry) == said


def test_the_markdown_inputs_say_why_a_table_is_no_full_snapshot(packets: Path) -> None:
    text = _markdown(packets, "demo_dwd.dwd_ticket_df")
    assert "全量快照：未证明（未见分区条件）" in text
    assert "全量快照：不适用（非分区表）" in text
    assert "全量快照：是" in text


# ------------------------------------------------------------------ A #11 date shapes


def _shapes(packet: dict, table: str) -> list[tuple]:
    return sorted((f["column"], f["shape"], f["statement_id"])
                  for f in _input(packet, table)["date_filters"])


def test_each_date_filter_carries_its_statement_and_shape(packets: Path) -> None:
    packet = packet_of(packets, "demo_dwd.dwd_ticket_df")
    assert _shapes(packet, "demo_dim.dim_code_dc") == [
        ("eff_beg_date", "as_of", "stmt:001"), ("eff_end_date", "as_of", "stmt:001"),
    ]
    assert _shapes(packet, "demo_ods.ods_ticket_df") == [
        ("close_date", "null_check", "stmt:001"), ("open_date", "upper_bound", "stmt:001"),
    ]


def test_a_lower_bound_and_an_unpaired_bound_are_windows(packets: Path) -> None:
    packet = packet_of(packets, "demo_dwd.dwd_ticket_new_di")
    assert _shapes(packet, "demo_dim.dim_code_dc") == [
        ("eff_beg_date", "upper_bound", "stmt:001"), ("eff_end_date", "window", "stmt:001"),
    ]
    assert _shapes(packet, "demo_ods.ods_ticket_df") == [("open_date", "window", "stmt:001")]


def test_check_9_doubts_a_snapshot_only_over_a_window(packets: Path) -> None:
    (quiet,) = check_time(_snapshot_doc(), packet_of(packets, "demo_dwd.dwd_ticket_df"))
    assert quiet["status"] == "pass"
    (loud,) = check_time(_snapshot_doc(), packet_of(packets, "demo_dwd.dwd_ticket_new_di"))
    assert loud["status"] == "warn"
    assert "eff_end_date" in loud["message"] and "open_date" in loud["message"]
    assert "eff_beg_date" not in loud["message"]


def test_a_date_filter_without_a_shape_still_counts_as_a_window() -> None:
    packet = {"inputs": [{"table": "demo_ods.t", "full_snapshot": False, "date_filters": [
        {"column": "d", "expression": "d <= '1'"}]}]}
    (result,) = check_time(_snapshot_doc(), packet)
    assert result["status"] == "warn"


def test_the_markdown_names_each_date_filters_shape(packets: Path) -> None:
    text = _markdown(packets, "demo_dwd.dwd_ticket_df")
    assert "有效期取数（拉链）" in text and "只有上界" in text and "非空判断" in text


# ------------------------------------------------------------------ #27a / #27b


def test_a_dynamic_partition_the_select_fills_with_constants_names_them(packets: Path) -> None:
    (partition,) = packet_of(packets, "demo_dwd.dwd_ticket_src_df")["lineage"]["partition"]
    assert partition["mode"] == "dynamic"
    assert partition["select_values"] == {"dt": ["'${bizdate}'"], "src": ["'a'", "'b'"]}
    text = _markdown(packets, "demo_dwd.dwd_ticket_src_df")
    assert "dynamic（SELECT 写常量：dt = `'${bizdate}'`；src ∈ `'a'`、`'b'`）" in text


def test_a_dynamic_partition_read_from_a_column_has_no_select_values(packets: Path) -> None:
    (partition,) = packet_of(packets, "demo_dwd.dwd_rate_hist_df")["lineage"]["partition"]
    assert partition["mode"] == "dynamic"
    assert "select_values" not in partition


def test_a_join_with_no_key_pair_names_the_tables_its_on_touches(packets: Path) -> None:
    packet = packet_of(packets, "demo_dwd.dwd_ticket_code_df")
    (join,) = _joins(packet, "demo_dim.dim_code_dc")
    assert join["tables"] == ["demo_dim.dim_code_dc", "demo_ods.ods_ticket_df"]
