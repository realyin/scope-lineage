"""Windows, joins under aggregates and partition reads, as a packet shows them.

- C-P4: a window that is no dedup (a ranking never filtered to ``= 1``, a LEAD) is a rule
  row of its own, ``kind: window``, worded by the profile; a JOIN whose verdict is not
  ``safe`` and whose right side holds an unfiltered ranking names it
  (``unfiltered_ranking``), in its 行数放大 cell;
- A-M4 (README 裁决 2): the ``window_partition_narrower`` lead names that window row;
- C-P3: a verdict on a JOIN off the grain path (under an aggregate) says so
  (``verdict_aggregate``) instead of reading like a row-copying risk;
- C-P7: two or more fixed partitions read by equalities / a literal IN list are
  ``multi_equality``, not a range;
- README 裁决 12: rules are numbered once, after every row is out; every ``pN`` a packet
  refers to exists, and the numbers run from p1 without a gap.

Every name is synthetic.
"""

from __future__ import annotations

import re

import pytest

from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.contract.task_lineage import to_task_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.scope.task_lineage import parse_task_lineage
from scope_lineage.semantics.packet import build_packets
from scope_lineage.semantics.packet_markdown import render_packet_markdown

SCHEMA = {
    "ods.orders": ["id", "b_val", "dt"],
    "ods.pay": ["id", "seq", "amt"],
    "ods.pay_ext": ["id", "seq", "kind"],
    "ods.ref": ["k", "v", "t"],
    "dw.t_m": ["id", "amt", "v", "dt"],
    "dw.t_g": ["id", "amt", "dt"],
    "dw.ver": ["k", "env", "d", "e"],
    "ods.v": ["k", "env", "d", "ts"],
}

# A ranking window computed on a LEFT JOIN's right side and never filtered to `= 1`.
UNFILTERED = """INSERT OVERWRITE TABLE dw.t_m PARTITION (dt = '20260101')
SELECT o.id, 0 AS amt, r.v
FROM (SELECT id FROM ods.orders WHERE dt = '20260101') o
LEFT JOIN (SELECT k, v, row_number() OVER (PARTITION BY k ORDER BY t DESC) AS rn FROM ods.ref) r
  ON o.id = r.k"""

# The same ranking kept to `= 1` one level up: a dedup, not a window row.
FILTERED = """INSERT OVERWRITE TABLE dw.t_m PARTITION (dt = '20260101')
SELECT o.id, 0 AS amt, r.v
FROM (SELECT id FROM ods.orders WHERE dt = '20260101') o
LEFT JOIN (SELECT x.k, x.v FROM (SELECT k, v, row_number() OVER (PARTITION BY k ORDER BY t DESC) AS rn
  FROM ods.ref) x WHERE x.rn = 1) r ON o.id = r.k"""

# A join inside a SUM's argument, below the outer aggregate (C group's t_g).
UNDER_AGGREGATE = """INSERT OVERWRITE TABLE dw.t_g PARTITION (dt = '20260101')
SELECT o.id, coalesce(s.amt, 0) AS amt
FROM (SELECT id FROM ods.orders WHERE dt = '20260101') o
LEFT JOIN (
  SELECT a.id, sum(amt) AS amt
  FROM (SELECT id FROM ods.orders WHERE dt = '20260101') a
  LEFT JOIN (
    SELECT p.id, sum(CASE WHEN e.kind = 'X' THEN p.amt ELSE 0 END) AS amt
    FROM ods.pay p LEFT JOIN ods.pay_ext e ON p.id = e.id AND p.seq = e.seq
    GROUP BY p.id
  ) b ON a.id = b.id
  GROUP BY a.id
) s ON o.id = s.id"""

# M4: one statement writes (k, env, d) once each, the next chains d by k alone.
WRITER = (
    "MERGE INTO dw.ver tgt USING (SELECT k, env, d, NULL AS e FROM (SELECT k, env, d,"
    " row_number() OVER (PARTITION BY k, env, d ORDER BY ts DESC) rn FROM ods.v) a"
    " WHERE a.rn = 1) src ON tgt.k = src.k AND tgt.d = src.d WHEN NOT MATCHED THEN INSERT *;\n"
)
CHAIN = (
    "MERGE INTO dw.ver tgt USING (SELECT a.*, lead(d, 1, '9999') OVER"
    " (PARTITION BY k ORDER BY d) AS nd FROM (SELECT * FROM dw.ver) a) src"
    " ON tgt.k = src.k AND tgt.d = src.d AND tgt.env = src.env"
    " WHEN MATCHED THEN UPDATE SET tgt.e = src.nd;\n"
)


def _pack(sql: str) -> dict:
    (packet,) = build_packets([(to_lineage_dict(parse_scope_lineage(sql, "t0", schema=SCHEMA)), None)])
    return packet


def _pack_task(script: str) -> dict:
    document = to_task_lineage_dict(parse_task_lineage(script, "v", schema=SCHEMA))
    (packet,) = build_packets([(document, None)])
    return packet


def _rules(packet: dict, kind: str) -> list[dict]:
    return [rule for rule in packet["lineage"]["rules"] if rule["kind"] == kind]


def _row(packet: dict, rule_id: str) -> list[str]:
    line = next(line for line in render_packet_markdown(packet).splitlines()
                if line.startswith(f"| {rule_id} |"))
    return line.split(" | ")


# ------------------------------------------------------------------ C-P4 window rows


def test_a_ranking_never_filtered_to_one_is_a_window_row_its_join_names() -> None:
    packet = _pack(UNFILTERED)
    (window,) = _rules(packet, "window")
    assert "未见 = 1 过滤" in window["text"]
    (join,) = _rules(packet, "join")
    assert join["fan_out"]["status"] != "safe"
    assert join["unfiltered_ranking"] == [window["id"]]
    assert _row(packet, join["id"])[5].endswith(
        f"右侧的 {window['id']} 算了排名但没有 = 1 过滤，未去重")


def test_a_ranking_kept_to_one_is_a_dedup_and_no_window_row() -> None:
    packet = _pack(FILTERED)
    assert _rules(packet, "window") == []
    assert len(_rules(packet, "dedup")) == 1
    assert all("unfiltered_ranking" not in rule for rule in _rules(packet, "join"))


def test_a_lead_window_is_a_row_no_join_names_and_the_narrower_lead_hangs_on_it() -> None:
    packet = _pack_task(WRITER + CHAIN)
    (window,) = _rules(packet, "window")
    assert window["statement_id"] == "stmt:002" and "LEAD" in window["text"]
    assert all("unfiltered_ranking" not in rule for rule in _rules(packet, "join"))
    (finding,) = [item for item in packet["lineage"]["findings"]
                  if item["kind"] == "window_partition_narrower"]
    assert finding["rules"] == [window["id"]]
    assert finding["text"] in _row(packet, window["id"])[6]


# ------------------------------------------------------------------ C-P3 verdict paths


def test_a_verdict_under_an_aggregate_says_where_it_sits() -> None:
    packet = _pack(UNDER_AGGREGATE)
    (inner,) = [rule for rule in _rules(packet, "join")
                if (rule.get("fan_out") or {}).get("path") not in (None, "grain")]
    assert inner["verdict_aggregate"] == "subq:b"
    assert "below_aggregate" not in inner
    cell = _row(packet, inner["id"])[5]
    status = inner["fan_out"]["status"]
    assert cell.startswith(f"{status}（位于聚合 `subq:b` 之下：不复制输出行，可能让聚合值重复计入）：")


def test_a_grain_path_verdict_reads_as_before() -> None:
    packet = _pack(UNFILTERED)
    (join,) = _rules(packet, "join")
    assert join["fan_out"]["path"] == "grain" and "verdict_aggregate" not in join
    verdict = join["fan_out"]
    assert _row(packet, join["id"])[5].startswith(f"{verdict['status']}：{verdict['reason']}")


def test_a_verdict_off_the_grain_path_without_an_aggregate_scope_says_the_path() -> None:
    from scope_lineage.semantics.packet_markdown import _fan_out

    rule = {"kind": "join", "fan_out": {"status": "risk", "reason": "r", "path": "argument"}}
    assert _fan_out(rule) == "risk（在聚合参数路径上：不复制输出行，可能让聚合值重复计入）：r"


# ------------------------------------------------------------------ README 裁决 12 numbering


_REFERS = ("inside", "unfiltered_ranking", "right_of")


def _referenced(packet: dict) -> list[str]:
    lineage = packet["lineage"]
    found = [ref for rule in lineage["rules"] for key in _REFERS for ref in rule.get(key) or []]
    found += [ref for item in lineage.get("findings") or [] for ref in item.get("rules") or []]
    for key in lineage["keys"]:
        merge = key.get("merge") or {}
        found += merge.get("joins_after_dedup") or []
        for branch in merge.get("union_branches") or []:
            found += branch.get("joins_after_dedup") or []
    return found


@pytest.mark.parametrize("build", [
    lambda: _pack(UNFILTERED), lambda: _pack(UNDER_AGGREGATE),
    lambda: _pack_task(WRITER + CHAIN),
])
def test_every_rule_a_packet_names_exists_and_numbers_run_from_p1(build) -> None:
    packet = build()
    ids = [rule["id"] for rule in packet["lineage"]["rules"]]
    assert ids == [f"p{index}" for index in range(1, len(ids) + 1)]
    referenced = _referenced(packet)
    assert referenced and set(referenced) <= set(ids)
    text = render_packet_markdown(packet)
    assert set(re.findall(r"\bp\d+\b", text)) <= set(ids)


# ------------------------------------------------------------------ C-P7 partition reads


@pytest.mark.parametrize(("filters", "read"), [
    (["`o`.`dt` IN ('20250101', '20260101')"], "multi_equality"),
    (["`o`.`dt` = '20250101'", "`o`.`dt` IN ('20250101', '20260101')"], "multi_equality"),
    (["`o`.`dt` IN ('20260101')"], "equality"),
    (["`o`.`dt` = '20260101'"], "equality"),
    (["`o`.`dt` >= '20260101'"], "range"),
    (["`o`.`dt` = '20260101'", "`o`.`dt` >= '20250101'"], "range"),
    (["`o`.`dt` IN (SELECT d FROM x)"], "range"),
    ([], "none"),
])
def test_fixed_partitions_read_by_equality_are_multi_equality(filters, read) -> None:
    from scope_lineage.semantics.packet_facts import _partition_read

    assert _partition_read(filters) == read


def test_two_fixed_partitions_of_a_full_table_say_each_is_a_snapshot() -> None:
    from scope_lineage.semantics.packet_markdown import full_snapshot_text

    entry = {"partitioned": True, "partition_columns": ["dt"], "partition_read": "multi_equality",
             "partition_filters": ["`o`.`dt` IN ('20250101', '20260101')"],
             "name_convention": "full", "full_snapshot": False}
    assert full_snapshot_text(entry) == (
        "否（读 2 个固定分区 '20250101'、'20260101'；表名约定 full：每个分区是一份快照，"
        "同一记录在每份里各一行）")
    entry["name_convention"] = "incremental"
    assert full_snapshot_text(entry) == "否（读 2 个固定分区 '20250101'、'20260101'）"


def test_an_in_list_of_partitions_in_a_packet_is_multi_equality() -> None:
    metadata = {"ods.orders": {"columns": [{"name": c} for c in ("id", "b_val", "dt")],
                               "partitioned": True, "partition_columns": ["dt"]}}
    sql = UNFILTERED.replace("WHERE dt = '20260101'", "WHERE dt IN ('20250101', '20260101')")
    document = to_lineage_dict(parse_scope_lineage(sql, "t0", schema=SCHEMA))
    (packet,) = build_packets([(document, None)], metadata=metadata.get)
    orders = next(entry for entry in packet["inputs"] if entry["table"] == "ods.orders")
    assert orders["partition_read"] == "multi_equality"
    assert orders["full_snapshot"] is False
