"""A MERGE's USING alias names the subquery, not something inside it.

`USING (SELECT ...) t1` exposes the subquery's output columns under `t1`. Resolution looked
`t1` up in the subquery's *internal* source map, so when an inner table happened to carry the
same alias, that table won — and every `t1.<col>` was published as a column of the physical
table instead of an output of the subquery (MERGE-ALIAS-001).

The result is not a gap. It is a confident wrong answer: `record_id AS biz_no` became
`ods.src.biz_no`, a column that table does not have, and the literal `'prod' AS etl_source`
became `ods.src.etl_source` — reported as a physical field with trace_complete true and no
warning. Reporting a literal as a column it does not have is the first thing this project's
README criticises other tools for.

Renaming either alias made the same statement resolve correctly, which is what isolates the
cause.
"""

from __future__ import annotations

import pytest

from scope_lineage.scope.task_lineage import parse_task_lineage

SCHEMA = {"ods.src": ["record_id", "dt"], "mart.tgt": ["biz_no", "etl_source", "dt"]}


def _merge_sql(using_alias: str, inner_alias: str) -> str:
    return (
        "MERGE INTO mart.tgt t\n"
        f"USING (SELECT record_id AS biz_no, 'prod' AS etl_source, dt FROM ods.src {inner_alias}) {using_alias}\n"
        f"ON t.biz_no = {using_alias}.biz_no\n"
        "WHEN NOT MATCHED THEN INSERT (biz_no, etl_source, dt) "
        f"VALUES ({using_alias}.biz_no, {using_alias}.etl_source, {using_alias}.dt)"
    )


def _final_sources(sql: str) -> dict[str, list[tuple]]:
    result = parse_task_lineage(sql, task_name="t", schema=SCHEMA)
    out: dict[str, list[tuple]] = {}
    for item in result.end_to_end_lineage:
        if item.get("table") != "mart.tgt":
            continue
        out[str(item.get("column"))] = [
            (source.get("source_kind"), source.get("table"), source.get("column"))
            for source in item.get("value_sources") or []
            if source.get("source_kind") != "prior_table_state"
        ]
    return out


@pytest.mark.parametrize("using_alias,inner_alias", [
    ("t1", "t1"),  # the shadowing shape
    ("s", "t1"),   # already correct — must stay correct
    ("t1", "a"),
])
def test_a_renamed_projection_keeps_its_real_source(using_alias, inner_alias):
    sources = _final_sources(_merge_sql(using_alias, inner_alias))

    assert sources["biz_no"] == [("physical_field", "ods.src", "record_id")]


@pytest.mark.parametrize("using_alias,inner_alias", [("t1", "t1"), ("s", "t1")])
def test_a_literal_stays_generated_and_never_becomes_a_column(using_alias, inner_alias):
    sources = _final_sources(_merge_sql(using_alias, inner_alias))

    kinds = {kind for kind, _table, _column in sources["etl_source"]}
    assert kinds == {"generated"}
    assert not [c for _k, _t, c in sources["etl_source"] if c == "etl_source"]


def test_a_passthrough_column_is_unaffected():
    sources = _final_sources(_merge_sql("t1", "t1"))

    assert sources["dt"] == [("physical_field", "ods.src", "dt")]


def test_shadowing_and_non_shadowing_agree():
    """The alias a user happens to choose must not change the lineage."""
    assert _final_sources(_merge_sql("t1", "t1")) == _final_sources(_merge_sql("s", "t1"))


def test_a_reference_to_an_inner_alias_still_reaches_the_inner_table():
    """The inner-source lookup exists for a reason; only the USING alias takes priority."""
    sql = (
        "MERGE INTO mart.tgt t\n"
        "USING (SELECT inner_t.record_id AS biz_no, 'prod' AS etl_source, inner_t.dt "
        "FROM ods.src inner_t) s\n"
        "ON t.biz_no = s.biz_no\n"
        "WHEN NOT MATCHED THEN INSERT (biz_no, dt) VALUES (s.biz_no, s.dt)"
    )

    sources = _final_sources(sql)

    assert sources["biz_no"] == [("physical_field", "ods.src", "record_id")]
