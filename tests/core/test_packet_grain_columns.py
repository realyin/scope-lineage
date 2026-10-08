"""The 4.3 grain cell names target columns, not the logical keys of a scope (round 3 M1).

``grain.keys[]`` are logical keys -- a column of the scope that decides the grain -- while
the 候选键 cell beside them names target columns. The packet carries
``lineage.keys[].grain_columns`` (the profile's ``grain_key_columns``) when a key's target
column is not the key's own name, and the cell renders it:

- ``exposed``: the target column;
- ``derived``: the target column, 「派生自 <logical key>」;
- ``merge_on``: the target column a MERGE's ON equality ties the key to;
- ``unexposed``: the logical key, 「未写入目标表」.

When every key lands on a column of its own name the key is absent and the packet is
byte-for-byte what it was. Every name is synthetic, and target and source names differ
on purpose: equal names would hide the difference.
"""

from __future__ import annotations

from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.semantics.packet import build_packets
from scope_lineage.semantics.packet_markdown import render_packet_markdown

SCHEMA = {
    "ods.ev": ["k", "env", "v", "ts"],
    "dw.out": ["out_key", "out_env", "v"],
    "dw.same": ["k", "env", "v"],
    "dw.m": ["tk", "v"],
}

DEDUP = (
    "(SELECT k, env, v FROM (SELECT k, env, v, row_number() OVER (PARTITION BY k, env"
    " ORDER BY ts DESC) rn FROM ods.ev) a WHERE a.rn = 1)"
)


def _pack(sql: str) -> dict:
    document = to_lineage_dict(parse_scope_lineage(sql, "t", schema=SCHEMA))
    (packet,) = build_packets([(document, None)])
    return packet


def _row(packet: dict) -> str:
    return next(line for line in render_packet_markdown(packet).splitlines()
                if line.startswith("| t / stmt:001 |"))


def test_a_renamed_and_a_derived_key_name_their_target_columns() -> None:
    packet = _pack(
        f"INSERT OVERWRITE TABLE dw.out SELECT x.k AS out_key, concat('p_', x.env) AS out_env,"
        f" x.v FROM {DEDUP} x"
    )
    (keys,) = packet["lineage"]["keys"]
    assert keys["grain_keys"] == ["k", "env"]
    assert [(item.get("column"), item["via"]) for item in keys["grain_columns"]] == [
        ("out_key", "exposed"), ("out_env", "derived")]
    row = _row(packet)
    logical = keys["grain_columns"][1]["logical"]
    assert f"| `out_key`、`out_env`（派生自 {logical}） |" in row


def test_a_merge_key_names_the_target_column_of_its_on_equality() -> None:
    packet = _pack(
        "MERGE INTO dw.m tgt USING (SELECT a.k AS src_k, a.v FROM (SELECT k, v, row_number()"
        " OVER (PARTITION BY k ORDER BY ts DESC) rn FROM ods.ev) a WHERE a.rn = 1) src"
        " ON tgt.tk = src.src_k WHEN MATCHED THEN UPDATE SET tgt.v = src.v"
    )
    (keys,) = packet["lineage"]["keys"]
    (entry,) = keys["grain_columns"]
    assert (entry["column"], entry["via"]) == ("tk", "merge_on")
    assert f"| `tk`（经 ON 等值，USING 侧 {entry['logical']}） |" in _row(packet)


def test_a_key_the_write_leaves_out_says_so_and_names_no_column() -> None:
    packet = _pack(
        f"INSERT OVERWRITE TABLE dw.out SELECT x.k AS out_key, 'c' AS out_env, x.v FROM {DEDUP} x"
    )
    (keys,) = packet["lineage"]["keys"]
    unexposed = keys["grain_columns"][1]
    assert unexposed["via"] == "unexposed" and "column" not in unexposed
    assert f"`out_key`、{unexposed['logical']}（未写入目标表）" in _row(packet)


def test_keys_written_under_their_own_names_add_nothing() -> None:
    packet = _pack(f"INSERT OVERWRITE TABLE dw.same SELECT x.k, x.env, x.v FROM {DEDUP} x")
    (keys,) = packet["lineage"]["keys"]
    assert keys["grain_keys"] == ["k", "env"]
    assert "grain_columns" not in keys
    assert "| `k`、`env` |" in _row(packet)


def test_the_grain_header_says_target_columns() -> None:
    packet = _pack(f"INSERT OVERWRITE TABLE dw.same SELECT x.k, x.env, x.v FROM {DEDUP} x")
    assert "| 任务 / 语句 | 形态 | 粒度依据 | 粒度键（目标列） | 候选键 | 键置信 | 已证明 |" in (
        render_packet_markdown(packet).splitlines())
