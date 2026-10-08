"""Where a filter sits relative to a LEFT JOIN, as a packet states it (B-V2, packet side).

A filter inside a LEFT JOIN's right side drops no target row: it decides which right
rows take part in the match. The packet marks such a filter with ``right_of`` (the LEFT
JOINs whose right side holds it) and, when its kind is structural, ``right_side_kind``:

- ``rank_first`` -- the filter keeps a ranking window's first row (``rn = 1``; the
  profile's own ``_keeps_first_row_consumer`` decides);
- ``values`` -- the filter's scope reads, down a single-input chain, an inline VALUES
  list.

A scope that also feeds the driving rows (a CTE read both as ``FROM person a`` and as
``LEFT JOIN person a1``) is never ``right_of``; nor is a right side whose rows the join's
own WHERE tests (an anti-join, ``WHERE c.k IS NULL``), where the right side does decide
which target rows survive. A filter on a CTE over a physical table is ``right_of`` but of
no structural kind, although its own ``tables`` are empty.

A partition filter is placed the same way (round 3 V2): it is ``right_of`` the LEFT JOINs
whose right side holds it, and its note says it decides which partitions the right side
reads. It never has a ``right_side_kind`` -- that exempts a filter from check 5, which
never asks for a partition filter. The checks that read these facts are not here, but
for check 5's partition filters. Every name is synthetic.
"""

from __future__ import annotations

from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.semantics.checks_context import check_rules
from scope_lineage.semantics.packet import build_packets
from scope_lineage.semantics.packet_markdown import render_packet_markdown

SCHEMA = {
    "demo_ods.order_src": ["order_id", "status_cd", "person_id", "env", "order_type", "dt"],
    "demo_ods.order_step_src": ["order_id", "step_name", "step_time", "step_role", "step_state",
                                "dt"],
    "demo_ods.person_src": ["id", "parent_id", "env", "upd"],
    "demo_dwd.order_det": ["order_id", "status_cd", "status_key", "step_name", "parent_id",
                           "parent_person", "dt"],
    "demo_dwd.person_dim": ["id", "env", "parent_person", "dt"],
    "demo_dwd.order_flat": ["order_id", "step_name", "code_key", "dt"],
}

ORDER_DET = """with code_tab as (
  select * from values ('k1','KindA','1','one'), ('k2','KindA','2','two'), ('k3','KindB','1','uno')
  as tab(code_key, code_kind, code_val, code_desc)
),
person as (
  select id, parent_id, env, row_number() over(partition by id, env order by upd desc) as rn
  from demo_ods.person_src where id <> ''
)
insert overwrite table demo_dwd.order_det partition(dt='20260101')
select o.order_id, o.status_cd, c.code_key as status_key, s.step_name, p.parent_id, p2.id as parent_person
from (select order_id, status_cd, person_id, env from demo_ods.order_src where order_type = 'X') o
left join (select * from code_tab where code_kind = 'KindA') c on o.status_cd = c.code_val
left join (select order_id, step_name from (select order_id, step_name, row_number() over
  (partition by order_id order by step_time desc) as rn from demo_ods.order_step_src
  where step_role = 'R7') x where rn = 1) s on o.order_id = s.order_id
left join (select * from person where rn = 1) p on o.person_id = p.id and o.env = p.env
left join person p2 on p.parent_id = p2.id and p.env = p2.env"""

PERSON_DIM = """with person as (
  select id, parent_id, env from (select id, parent_id, env, row_number() over(partition by id, env
  order by upd desc) as rn from demo_ods.person_src) t where t.rn = 1
)
insert overwrite table demo_dwd.person_dim partition(dt='20260101')
select a.id, a.env, a1.id as parent_person
from person a
left join person a1 on a.parent_id = a1.id and a.env = a1.env"""

ORDER_FLAT = """with step_cte as (
  select order_id, step_name, step_state from demo_ods.order_step_src
),
code_tab as (
  select * from values ('k1','KindA','1'), ('k2','KindB','1') as tab(code_key, code_kind, code_val)
)
insert overwrite table demo_dwd.order_flat partition(dt='20260101')
select o.order_id, s.step_name, c.code_key
from demo_ods.order_src o
left join (select * from step_cte where step_state = 'S9') s on o.order_id = s.order_id
left join (select * from code_tab where code_kind = 'KindA') c on o.status_cd = c.code_val"""


def _pack(sql: str, metadata=None) -> dict:
    document = to_lineage_dict(parse_scope_lineage(sql, "t", schema=SCHEMA))
    (packet,) = build_packets([(document, None)], metadata=metadata)
    return packet


def _filters(packet: dict) -> dict[str, dict]:
    found = {}
    for rule in packet["lineage"]["rules"]:
        if rule["kind"] == "filter" and not rule["partition_filter"]:
            text = rule["expression"].replace("`", "")
            found[text.split(".", 1)[-1] if "." in text.split(" ")[0] else text] = rule
    return found


def _join_id(packet: dict, right_alias: str) -> str:
    return next(rule["id"] for rule in packet["lineage"]["rules"]
                if rule["kind"] == "join" and right_alias in rule["right_aliases"])


def test_right_side_filters_are_marked_with_their_join_and_kind() -> None:
    packet = _pack(ORDER_DET)
    filters = _filters(packet)
    assert set(filters) == {"order_type = 'X'", "code_kind = 'KindA'", "step_role = 'R7'",
                            "rn = 1", "id <> ''"}
    driving = filters["order_type = 'X'"]
    assert "right_of" not in driving and "right_side_kind" not in driving
    values = filters["code_kind = 'KindA'"]
    assert values["right_of"] == [_join_id(packet, "c")]
    assert values["right_side_kind"] == "values"
    role = filters["step_role = 'R7'"]
    assert role["right_of"] == [_join_id(packet, "s")] and "right_side_kind" not in role
    ranked = [rule for rule in packet["lineage"]["rules"]
              if rule["kind"] == "filter" and rule["expression"].replace("`", "").endswith("rn = 1")]
    assert len(ranked) == 2
    assert all(rule["right_side_kind"] == "rank_first" for rule in ranked)
    person = filters["id <> ''"]
    assert person["right_of"] == [_join_id(packet, "p"), _join_id(packet, "p2")]
    assert "right_side_kind" not in person


def test_the_note_says_a_right_side_filter_drops_no_target_row() -> None:
    packet = _pack(ORDER_DET)
    rule = _filters(packet)["code_kind = 'KindA'"]
    row = next(line for line in render_packet_markdown(packet).splitlines()
               if line.startswith(f"| {rule['id']} |"))
    assert f"在 {rule['right_of'][0]} 右侧：不丢目标行，决定右侧哪些行参与匹配" in row


def test_a_cte_that_also_drives_is_never_right_of() -> None:
    packet = _pack(PERSON_DIM)
    (ranked,) = [rule for rule in packet["lineage"]["rules"] if rule["kind"] == "filter"
                 and not rule["partition_filter"]]
    assert "right_of" not in ranked and "right_side_kind" not in ranked


def test_a_filter_on_a_cte_over_a_physical_table_is_right_of_but_no_kind() -> None:
    packet = _pack(ORDER_FLAT)
    filters = _filters(packet)
    state = filters["step_state = 'S9'"]
    assert state["tables"] == []
    assert state["right_of"] == [_join_id(packet, "s")] and "right_side_kind" not in state
    assert filters["code_kind = 'KindA'"]["right_side_kind"] == "values"


def test_an_anti_join_s_right_side_filters_are_not_right_of() -> None:
    packet = _pack(ORDER_FLAT.replace(
        "on o.status_cd = c.code_val", "on o.status_cd = c.code_val where c.code_key is null"))
    filters = _filters(packet)
    assert "right_of" not in filters["code_kind = 'KindA'"]
    assert "right_side_kind" not in filters["code_kind = 'KindA'"]
    # The other join's right side is still only matched against.
    assert "right_of" in filters["step_state = 'S9'"]


_STEPS_PARTITIONED = {
    "demo_ods.order_step_src": {"partitioned": True, "partition_columns": ["dt"], "columns": []},
    "demo_ods.order_src": {"partitioned": True, "partition_columns": ["dt"], "columns": []},
}.get


def _partition_rules(packet: dict) -> list[dict]:
    return [rule for rule in packet["lineage"]["rules"] if rule["partition_filter"]]


RIGHT_PARTITION = ORDER_DET.replace("where step_role = 'R7'",
                                    "where step_role = 'R7' and dt = '20260101'")


def test_a_right_side_partition_filter_is_right_of_but_no_kind() -> None:
    """Round 3 V2: where a partition filter sits is a fact the reader of 4.2 needs too."""
    packet = _pack(RIGHT_PARTITION, _STEPS_PARTITIONED)
    (partition,) = _partition_rules(packet)
    assert partition["right_of"] == [_join_id(packet, "s")]
    assert "right_side_kind" not in partition


def test_a_driving_partition_filter_is_not_right_of() -> None:
    packet = _pack(RIGHT_PARTITION.replace("where order_type = 'X'",
                                           "where order_type = 'X' and dt = '20260101'"),
                   _STEPS_PARTITIONED)
    driving, right = _partition_rules(packet)
    assert "order_src" in " ".join(driving["tables"])
    assert "right_of" not in driving and "right_side_kind" not in driving
    assert right["right_of"] == [_join_id(packet, "s")]


def test_an_anti_join_s_right_side_partition_filter_is_not_right_of() -> None:
    sql = ORDER_FLAT.replace("from demo_ods.order_step_src",
                             "from demo_ods.order_step_src where dt = '20260101'")
    anti = sql.replace("on o.status_cd = c.code_val",
                        "on o.status_cd = c.code_val where s.step_name is null")
    (partition,) = _partition_rules(_pack(anti, _STEPS_PARTITIONED))
    assert "right_of" not in partition
    (partition,) = _partition_rules(_pack(sql, _STEPS_PARTITIONED))
    assert partition["right_of"]


def test_a_partition_filter_beside_a_kept_first_row_has_no_kind() -> None:
    packet = _pack(RIGHT_PARTITION, _STEPS_PARTITIONED)
    ranked = [rule for rule in packet["lineage"]["rules"] if rule.get("right_side_kind")]
    assert ranked and all(not rule["partition_filter"] for rule in ranked)


def test_the_note_of_a_right_side_partition_filter_says_it_picks_partitions() -> None:
    packet = _pack(RIGHT_PARTITION, _STEPS_PARTITIONED)
    (partition,) = _partition_rules(packet)
    markdown = render_packet_markdown(packet).splitlines()
    row = next(line for line in markdown if line.startswith(f"| {partition['id']} |"))
    assert f"在 {partition['right_of'][0]} 右侧：不丢目标行，决定右侧读哪些分区" in row
    assert "决定右侧哪些行参与匹配" not in row
    other = _filters(packet)["step_role = 'R7'"]
    row = next(line for line in markdown if line.startswith(f"| {other['id']} |"))
    assert "决定右侧哪些行参与匹配" in row


def test_check_5_still_asks_for_no_partition_filter() -> None:
    packet = _pack(RIGHT_PARTITION, _STEPS_PARTITIONED)
    for task in packet["tasks"]:
        task["sql"] = RIGHT_PARTITION
    document = {"rules": [], "summary": {"scope": []}}
    asked = [item["message"] for item in check_rules(document, packet)
             if item["status"] == "fail" and item["at"] == "rules"]
    assert asked and not any("dt" in message for message in asked)
