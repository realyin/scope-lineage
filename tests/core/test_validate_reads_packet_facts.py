"""Checks 3 and 5 read what a packet states about a column's literals and a filter's place.

- Check 3, an empty code value (B-V1): ``''`` is no text a search can find. It is a code
  only when one of the column's producers writes ``''`` (``literal_outputs``): a
  COALESCE / NVL fallback, a constant, a CASE / IF branch. A ``''`` only compared in a
  condition writes nothing, and a value of blanks is held to the same rule instead of
  matching any blank of the SQL.
- Check 3, a constant column (B-V5): when every producer of a column ends in a constant
  (``constant_only``), its codes are those constants and nothing else -- an
  ``unconfirmed`` code too, and a column that only writes NULL has no code at all.
- Check 5, a filter inside a LEFT JOIN's right side (B-V2): it drops no target row. One
  that keeps a ranking's first row or reads an inline VALUES list (``right_side_kind``)
  need not be cited; any other (``right_of`` alone) must be, as a rule and not in
  ``summary.scope``.

A packet without these keys is checked as before. Every name is synthetic.
"""

from __future__ import annotations

import copy

import pytest

from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.semantics.checks import check_code_values
from scope_lineage.semantics.checks_context import check_rules
from scope_lineage.semantics.packet import build_packets

SCHEMA = {
    "demo_ods.order_src": ["order_id", "status", "x", "flag", "status_cd", "person_id", "env",
                           "order_type"],
    "demo_ods.order_step_src": ["order_id", "step_name", "step_time", "step_role", "step_state"],
    "demo_ods.person_src": ["id", "parent_id", "env", "upd"],
    "demo_dwd.order_out": ["order_id", "status_key", "reserved_col", "cleaned", "reserved_flag",
                           "channel"],
    "demo_dwd.order_det": ["order_id", "status_cd", "status_key", "step_name", "parent_id",
                           "parent_person"],
    "demo_dwd.person_dim": ["id", "env", "parent_person"],
    "demo_dwd.order_flat": ["order_id", "step_name", "code_key"],
}


def _pack(sql: str) -> dict:
    document = to_lineage_dict(parse_scope_lineage(sql, "t", schema=SCHEMA))
    (packet,) = build_packets([(document, None)])
    for task in packet["tasks"]:
        task["sql"] = sql
    return packet


def _old(packet: dict, *keys: str) -> dict:
    """``packet`` as a build before these facts wrote it: without ``keys`` anywhere."""
    older = copy.deepcopy(packet)
    for entry in older["lineage"]["columns"]:
        for producer in entry["producers"]:
            for key in keys:
                producer.pop(key, None)
    for rule in older["lineage"]["rules"]:
        for key in keys:
            rule.pop(key, None)
    return older


# ------------------------------------------------------------------ check 3

OUT = """WITH codes AS (SELECT * FROM VALUES ('k1', '1'), ('k2', '2') AS t(code_key, code_val))
INSERT OVERWRITE TABLE demo_dwd.order_out
SELECT o.order_id, coalesce(c.code_key, '') AS status_key, '' AS reserved_col,
  CASE WHEN o.x = '' THEN NULL ELSE o.x END AS cleaned, NULL AS reserved_flag, 'web' AS channel
FROM demo_ods.order_src o LEFT JOIN codes c ON o.status = c.code_val WHERE o.flag = 0
UNION ALL
SELECT o.order_id, o.status, '', o.x, NULL, 'app'
-- , 'wap' AS channel
FROM demo_ods.order_src o"""


@pytest.fixture(scope="module")
def out() -> dict:
    return _pack(OUT)


def _code_results(packet: dict, column: str, *codes: dict) -> list[str]:
    document = {"columns": [{"column": column, "code_values": list(codes)}]}
    return [item["status"] for item in check_code_values(document, packet)]


def _code(value, **extra) -> dict:
    return {"value": value, "meaning": "…", "sources": ["sql"], **extra}


@pytest.mark.parametrize("column", ["status_key", "reserved_col"])
def test_an_empty_code_passes_on_a_column_that_writes_an_empty_string(out, column) -> None:
    assert _code_results(out, column, _code("")) == ["pass"]


def test_an_empty_code_fails_where_empty_is_only_compared(out) -> None:
    (item,) = check_code_values(
        {"columns": [{"column": "cleaned", "code_values": [_code("")]}]}, out)
    assert item["status"] == "fail"
    assert "空串不是列 cleaned 会产出的值" in item["message"]


def test_a_blank_code_is_no_longer_found_in_any_blank_of_the_sql(out) -> None:
    assert _code_results(out, "cleaned", _code(" ")) == ["fail"]
    assert _code_results(out, "status_key", _code(" ")) == ["pass"]


def test_a_wrong_code_still_fails_on_a_column_that_writes_an_empty_string(out) -> None:
    """The empty-string allowance is for '' alone, not for the column's other codes."""
    assert _code_results(out, "status_key", _code("ZQ7"), _code("k1")) == ["fail", "pass"]


def test_a_non_empty_code_is_judged_as_before(out) -> None:
    older = _old(out, "literal_outputs", "constant_only")
    for column, value in [("cleaned", "k1"), ("cleaned", "ZQ7"), ("status_key", "1")]:
        assert _code_results(out, column, _code(value)) == _code_results(older, column, _code(value))


def test_a_code_on_a_constant_null_column_fails(out) -> None:
    """0 stands alone elsewhere in the SQL (``o.flag = 0``); the column only writes NULL."""
    (item,) = check_code_values(
        {"columns": [{"column": "reserved_flag", "code_values": [_code("0")]}]}, out)
    assert item["status"] == "fail"
    assert "reserved_flag" in item["message"] and "'0'" in item["message"]


def test_a_code_outside_a_constant_column_s_constants_fails(out) -> None:
    """'wap' is in the SQL, in a branch switched off by a comment; the column writes web/app."""
    assert _code_results(out, "channel", _code("wap"), _code("web"), _code("app")) == [
        "fail", "pass", "pass"]


def test_an_unconfirmed_code_on_a_constant_column_is_checked_too(out) -> None:
    assert _code_results(out, "channel", _code("wap", unconfirmed=True)) == ["fail"]
    assert _code_results(out, "channel", _code("web", unconfirmed=True)) == ["pass"]
    assert _code_results(out, "cleaned", _code("wap", unconfirmed=True)) == []


def test_an_inline_values_column_with_a_fallback_is_not_constant(out) -> None:
    assert _code_results(out, "status_key", _code(""), _code("k1"), _code("k2")) == [
        "pass", "pass", "pass"]


def test_a_packet_without_literal_facts_checks_constants_as_before(out) -> None:
    older = _old(out, "literal_outputs", "constant_only")
    assert _code_results(older, "channel", _code("wap"), _code("wap", unconfirmed=True)) == [
        "pass"]
    assert _code_results(older, "reserved_flag", _code("0")) == ["pass"]


# ------------------------------------------------------------------ check 5

ORDER_DET = """with code_tab as (
  select * from values ('k1','KindA','1','one'), ('k2','KindA','2','two'), ('k3','KindB','1','uno')
  as tab(code_key, code_kind, code_val, code_desc)
),
person as (
  select id, parent_id, env, row_number() over(partition by id, env order by upd desc) as rn
  from demo_ods.person_src where id <> ''
)
insert overwrite table demo_dwd.order_det
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
insert overwrite table demo_dwd.person_dim
select a.id, a.env, a1.id as parent_person
from person a
left join person a1 on a.parent_id = a1.id and a.env = a1.env"""

ORDER_FLAT = """with step_cte as (
  select order_id, step_name, step_state from demo_ods.order_step_src
),
code_tab as (
  select * from values ('k1','KindA','1'), ('k2','KindB','1') as tab(code_key, code_kind, code_val)
)
insert overwrite table demo_dwd.order_flat
select o.order_id, s.step_name, c.code_key
from demo_ods.order_src o
left join (select * from step_cte where step_state = 'S9') s on o.order_id = s.order_id
left join (select * from code_tab where code_kind = 'KindA') c on o.status_cd = c.code_val"""


def _quoting(*quotes: str) -> dict:
    return {"rules": [{"id": f"r{n}", "kind": "filter", "text": "…", "sql": text, "sources": ["sql"]}
                      for n, text in enumerate(quotes, 1)],
            "summary": {"scope": []}}


def _uncited(document: dict, packet: dict) -> dict[str, str]:
    """``filter text -> message`` of every filter check 5 still asks to be cited."""
    found = {}
    for item in check_rules(document, packet):
        if item["status"] == "fail" and item["at"] == "rules":
            found[item["message"].split("（", 1)[0].removeprefix("过滤 ")] = item["message"]
    return found


def _cited(document: dict, packet: dict) -> int:
    return sum(1 for item in check_rules(document, packet)
               if item["status"] == "pass" and item["at"] == "rules")


def test_rank_first_and_values_filters_on_a_right_side_need_no_rule() -> None:
    packet = _pack(ORDER_DET)
    uncited = _uncited(_quoting("where order_type = 'X'"), packet)
    assert set(uncited) == {"person_src.id <> ''", "order_step_src.step_role = 'R7'"}
    assert _cited(_quoting("where order_type = 'X'"), packet) == 1


def test_a_right_side_filter_on_a_physical_table_must_be_a_rule_not_a_scope() -> None:
    packet = _pack(ORDER_DET)
    message = _uncited(_quoting("where order_type = 'X'"), packet)[
        "order_step_src.step_role = 'R7'"]
    join = next(rule["id"] for rule in packet["lineage"]["rules"]
                if rule["kind"] == "join" and "s" in rule["right_aliases"])
    assert f"在左关联 {join} 的右侧" in message
    assert "照抄这条过滤的原文，可以只抄这一个条件" in message
    assert "不要写进 summary.scope" in message
    assert "用 rule_refs 引用它" not in message


def test_a_driving_filter_s_message_asks_for_its_own_condition() -> None:
    packet = _pack(ORDER_DET)
    message = _uncited(_quoting(), packet)["order_src.order_type = 'X'"]
    assert "照抄这条过滤的原文，可以只抄这一个条件" in message
    assert "并在 summary.scope 里用 rule_refs 引用它" in message


def test_a_ranking_in_a_cte_that_also_drives_must_still_be_cited() -> None:
    uncited = _uncited(_quoting(), _pack(PERSON_DIM))
    (text,) = uncited
    assert text.endswith("rn = 1") and "summary.scope" in uncited[text]


def test_an_anti_join_s_right_side_filter_must_still_be_cited() -> None:
    packet = _pack(ORDER_FLAT.replace(
        "on o.status_cd = c.code_val", "on o.status_cd = c.code_val where c.code_key is null"))
    uncited = _uncited(_quoting("where c.code_key is null"), packet)
    assert "code_tab.code_kind = 'KindA'" in uncited
    assert "summary.scope" in uncited["code_tab.code_kind = 'KindA'"]


def test_a_filter_on_a_cte_over_a_physical_table_must_be_cited_its_values_neighbour_not() -> None:
    uncited = _uncited(_quoting(), _pack(ORDER_FLAT))
    assert set(uncited) == {"step_cte.step_state = 'S9'"}
    assert "右侧" in uncited["step_cte.step_state = 'S9'"]


def test_driving_filters_are_judged_as_before() -> None:
    packet = _pack(ORDER_DET)
    older = _old(packet, "right_of", "right_side_kind")
    document = _quoting("where order_type = 'X'")
    assert _cited(document, packet) == _cited(document, older) == 1


def test_a_packet_without_right_side_facts_asks_for_every_filter() -> None:
    older = _old(_pack(ORDER_DET), "right_of", "right_side_kind")
    uncited = _uncited(_quoting("where order_type = 'X'"), older)
    assert len(uncited) == 5
    assert all("summary.scope" in message for message in uncited.values())
