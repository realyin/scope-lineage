"""A MERGE WHEN condition is a branch condition in the Core scope profile, not a row filter.

Since the MERGE ROOT records each `WHEN ... AND <condition>` as a filter (predicate_type
`merge_when`), the scope profile counted them as `filter`: `operations` listed `filter`,
`business_summary` said 「按过滤条件保留记录」 and `logic.filters` listed the conditions, so
`WHEN MATCHED AND s.op = 'D' THEN DELETE` read as "keep rows where op = 'D'".
"""

from __future__ import annotations

from scope_lineage import parse_scope_lineage, to_dict

_MERGE = """
MERGE INTO dw.cust t
USING ods.cust_delta s
ON t.cust_id = s.cust_id AND t.dt = s.dt
WHEN MATCHED AND s.op = 'D' THEN DELETE
WHEN MATCHED AND s.status <> t.status THEN UPDATE SET t.status = s.status, t.upd = s.ts
WHEN NOT MATCHED AND s.op <> 'D' THEN INSERT (cust_id, status, upd, dt)
  VALUES (s.cust_id, s.status, s.ts, s.dt)
"""
_SCHEMA = {
    "dw.cust": ["cust_id", "status", "upd", "dt"],
    "ods.cust_delta": ["cust_id", "op", "status", "ts", "dt"],
}


def _root_step(sql: str, schema: dict | None = _SCHEMA) -> dict:
    document = to_dict(parse_scope_lineage(sql, "t", schema=schema))
    [step] = [s for s in document["scope_profile"]["steps"] if s["scope_id"] == "ROOT"]
    return step


def test_merge_when_conditions_are_not_counted_as_filters():
    step = _root_step(_MERGE)

    assert "filter" not in step["operations"]
    assert "merge_when" in step["operations"]
    assert step["logic"]["filters"] == []
    assert "按过滤条件保留记录" not in step["business_summary"]


def test_merge_when_conditions_are_listed_as_branch_conditions():
    step = _root_step(_MERGE)

    assert step["logic"]["merge_when_conditions"] == [
        "`s`.`op` = 'D'",
        "`s`.`status` <> `t`.`status`",
        "`s`.`op` <> 'D'",
    ]
    assert "按 WHEN 条件选择写入分支" in step["business_summary"]


def test_merge_without_when_conditions_carries_no_branch_entry():
    step = _root_step(
        "MERGE INTO dw.cust t USING ods.cust_delta s ON t.cust_id = s.cust_id "
        "WHEN MATCHED THEN UPDATE SET t.status = s.status"
    )

    assert "merge_when" not in step["operations"]
    assert "merge_when_conditions" not in step["logic"]


def test_an_insert_where_is_still_a_filter():
    step = _root_step(
        "INSERT OVERWRITE TABLE dw.cust SELECT cust_id, status, ts AS upd, dt "
        "FROM ods.cust_delta WHERE op <> 'D'"
    )

    assert "filter" in step["operations"]
    assert step["logic"]["filters"] == ["WHERE `cust_delta`.`op` <> 'D'"]
    assert "merge_when_conditions" not in step["logic"]
