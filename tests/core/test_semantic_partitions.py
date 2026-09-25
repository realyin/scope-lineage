"""Partition reads in a packet: the metadata's flag first, a guarded name rule second.

The lineage marks a WHERE clause a partition filter only when *every* column it names is
called dt/ds/pt/..., so ``dt = x AND status = 0`` marks neither conjunct, and a partition
column with any other name is never marked. The packet judges each conjunct alone: the
metadata's ``isPartition`` / ``PARTITIONED BY`` decides; failing that, a comparison with
a constant on a dt/ds/pt/p_date column of a table the metadata marks partitioned; with
neither, the lineage's flag stands.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scope_lineage.metadata.schema_metadata import (
    load_schema,
    load_schema_sources,
    partition_columns_for_table,
)
from scope_lineage.semantics.checks_context import check_time

from .table_semantics_demo import pack, packet_of, parse_corpus, write_json

TARGET = "demo_dwd.dwd_member_order_df"
MEMBER_ONLY = "demo_dwd.dwd_member_df"


def _column(name: str, index: int, kind: str = "string", partition: int | None = None) -> dict:
    column = {"columnName": name, "columnType": kind, "columnComment": name, "columnIndex": index}
    if partition is not None:
        column["isPartition"] = partition
    return column


def _table(name: str, columns: list[dict], partitioned: str | None = None) -> dict:
    table = {"table_name": name, "table_desc": name, "schema": columns}
    if partitioned is not None:
        table["is_partition"] = partitioned
    return table


SCHEMA = {"tables": [
    # The partition column has a name no rule would guess: only the metadata says it.
    _table("demo_ods.ods_member_snap_df", [
        _column("member_no", 0), _column("status", 1, "int"),
        _column("snap_day", 2, partition=1),
    ], partitioned="1"),
    # Marked partitioned, no column flagged: the dt name rule may be used.
    _table("demo_ods.ods_order_flow_df", [
        _column("order_no", 0), _column("member_no", 1), _column("order_status", 2),
        _column("dt", 3),
    ], partitioned="1"),
    # Nothing stated at all: the lineage's own flag stands.
    _table("demo_ods.ods_rate_plain_df", [
        _column("member_no", 0), _column("rate_type", 1), _column("dt", 2),
    ]),
    _table(TARGET, [
        _column("member_no", 0), _column("order_no", 1), _column("rate_type", 2),
        _column("dt", 3, partition=1),
    ], partitioned="1"),
    _table(MEMBER_ONLY, [
        _column("member_no", 0), _column("dt", 1, partition=1),
    ], partitioned="1"),
]}

JOINED_SQL = """INSERT OVERWRITE TABLE demo_dwd.dwd_member_order_df PARTITION (dt = '${bizdate}')
SELECT m.member_no, o.order_no, r.rate_type
FROM (SELECT member_no FROM demo_ods.ods_member_snap_df
      WHERE snap_day = '${bizdate}' AND status = 1) m
JOIN (SELECT member_no, order_no FROM demo_ods.ods_order_flow_df
      WHERE dt = '${bizdate}' AND order_status = 'PAID') o ON m.member_no = o.member_no
LEFT JOIN (SELECT member_no, rate_type FROM demo_ods.ods_rate_plain_df
      WHERE dt = '${bizdate}' AND rate_type = 'A') r ON m.member_no = r.member_no"""

MEMBER_SQL = """INSERT OVERWRITE TABLE demo_dwd.dwd_member_df PARTITION (dt = '${bizdate}')
SELECT member_no FROM demo_ods.ods_member_snap_df
WHERE snap_day = '${bizdate}' AND status = 1"""


@pytest.fixture(scope="module")
def packets(tmp_path_factory) -> Path:
    work = tmp_path_factory.mktemp("partitions")
    corpus = work / "corpus"
    for name, sql in (("dwd_member_order_daily", JOINED_SQL), ("dwd_member_daily", MEMBER_SQL)):
        write_json(corpus / "tasks" / f"{name}.json", {"meta": {
            "task_name": name, "schedule_cycle": "day", "sql": sql,
        }})
    write_json(corpus / "schema_info.json", SCHEMA)
    lineage = parse_corpus(corpus, work / "lineage")
    assert pack(corpus, lineage, work / "packets") == 0
    return work / "packets"


def _filters(packet: dict, table: str) -> dict[str, dict]:
    return {
        rule["expression"].replace("`", ""): rule
        for rule in packet["lineage"]["rules"]
        if rule["kind"] == "filter" and table in rule["tables"]
    }


def _input(packet: dict, table: str) -> dict:
    return next(item for item in packet["inputs"] if item["table"] == table)


def test_a_partition_column_only_the_metadata_names_is_read_as_a_partition(packets: Path) -> None:
    packet = packet_of(packets, TARGET)
    rules = _filters(packet, "demo_ods.ods_member_snap_df")
    snap = rules["ods_member_snap_df.snap_day = '${bizdate}'"]
    assert (snap["partition_filter"], snap["partition_basis"]) == (True, "metadata")
    status = rules["ods_member_snap_df.status = 1"]
    assert (status["partition_filter"], status["partition_basis"]) == (False, "metadata")
    member = _input(packet, "demo_ods.ods_member_snap_df")
    assert (member["partition_read"], member["full_snapshot"], member["date_filters"]) == (
        "equality", True, [],
    )
    assert [c["name"] for c in member["columns"] if c["partition"]] == ["snap_day"]


def test_a_dt_equality_on_a_table_marked_partitioned_is_a_partition_read(packets: Path) -> None:
    packet = packet_of(packets, TARGET)
    dt = _filters(packet, "demo_ods.ods_order_flow_df")["ods_order_flow_df.dt = '${bizdate}'"]
    assert (dt["partition_filter"], dt["partition_basis"]) == (True, "partition_name")
    orders = _input(packet, "demo_ods.ods_order_flow_df")
    assert (orders["partition_read"], orders["full_snapshot"], orders["date_filters"]) == (
        "equality", True, [],
    )


def test_with_no_partition_fact_the_lineage_flag_stands(packets: Path) -> None:
    packet = packet_of(packets, TARGET)
    dt = _filters(packet, "demo_ods.ods_rate_plain_df")["ods_rate_plain_df.dt = '${bizdate}'"]
    assert (dt["partition_filter"], dt["partition_basis"]) == (False, "lineage")
    rates = _input(packet, "demo_ods.ods_rate_plain_df")
    assert rates["partition_read"] == "none"
    assert [item["column"] for item in rates["date_filters"]] == ["dt"]


def test_incremental_over_a_metadata_partitioned_snapshot_fails_check_9(packets: Path) -> None:
    packet = packet_of(packets, MEMBER_ONLY)
    document = {"summary": {"refresh": {"time": "incremental"}}}
    (result,) = check_time(document, packet)
    assert result["status"] == "fail"
    document["summary"]["refresh"]["time"] = "snapshot"
    assert check_time(document, packet)[0]["status"] == "pass"


# ------------------------------------------------------------------ the loader


def test_the_loader_keeps_the_partition_flag_of_every_format(tmp_path: Path) -> None:
    directory = tmp_path / "per_table"
    for table in SCHEMA["tables"]:
        write_json(directory / f"{table['table_name']}_metadata.json", table)
    csv = tmp_path / "schema.csv"
    csv.write_text(
        "table_name,column_name,type,is_partition\n"
        "demo_ods.ods_csv_df,member_no,string,0\ndemo_ods.ods_csv_df,ds,string,1\n",
        encoding="utf-8",
    )
    schema = load_schema(directory)
    assert partition_columns_for_table(schema, "demo_ods.ods_member_snap_df") == ["snap_day"]
    assert partition_columns_for_table(schema, "spark_catalog.demo_dwd.dwd_member_df") == ["dt"]
    assert partition_columns_for_table(schema, "demo_ods.ods_order_flow_df") is None
    assert partition_columns_for_table(load_schema(csv), "demo_ods.ods_csv_df") == ["ds"]
    merged = load_schema_sources([directory, csv])
    assert partition_columns_for_table(merged, "demo_ods.ods_csv_df") == ["ds"]
    assert partition_columns_for_table(merged, "demo_ods.ods_member_snap_df") == ["snap_day"]


def test_only_tables_narrows_a_metadata_directory_to_the_files_naming_them(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "per_table"
    for table in SCHEMA["tables"]:
        write_json(directory / f"{table['table_name']}_metadata.json", table)
    whole = load_schema(directory)
    narrow = load_schema_sources(
        [directory], only_tables={"spark_catalog.demo_ods.ods_member_snap_df"}
    )
    table = "demo_ods.ods_member_snap_df"
    assert sorted(narrow) == [table]
    assert narrow.column_details[table] == whole.column_details[table]
    assert partition_columns_for_table(narrow, table) == ["snap_day"]
    assert dict(load_schema(directory, only_tables=set())) == {}


def test_the_partition_flag_does_not_reach_the_published_column_details(tmp_path: Path) -> None:
    schema = load_schema(write_json(tmp_path / "s.json", SCHEMA))
    details = schema.column_details["demo_ods.ods_member_snap_df"]
    assert all(set(detail) == {"name", "type", "comment"} for detail in details)
