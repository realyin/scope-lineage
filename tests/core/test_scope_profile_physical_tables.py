"""C2.5-1: ``scope_profile`` names one set of physical tables, not two.

``direct_source_tables`` used to require a dot in the name while
``physical_source_tables`` did not, so a bare table read directly showed up only in the
transitive set and ``business_summary`` called it something the statement could only
"trace back to". A temporary view a previous statement defined is the opposite case: it
is a relation of this session, never a table in the warehouse, and neither set names it.
"""

from __future__ import annotations

from scope_lineage.contract import to_lineage_dict
from scope_lineage.contract.task_lineage import to_task_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.scope.task_lineage import parse_task_lineage

SCRIPT = """
CREATE TEMPORARY VIEW tmp_v AS SELECT id, amt FROM ods.real;
INSERT OVERWRITE TABLE mart.s SELECT id, amt FROM tmp_v;
INSERT OVERWRITE TABLE mart.s2 SELECT id FROM orders WHERE amt > (SELECT MAX(amt) FROM ods.lim);
"""


def _roots(sql: str) -> dict[str, dict]:
    document = to_task_lineage_dict(parse_task_lineage(sql, task_name="t"))
    return {
        statement_id: next(
            step for step in statement["scope_profile"]["steps"] if step["scope_id"] == "ROOT"
        )
        for statement_id, statement in document["statement_lineage"].items()
    }


def test_a_bare_table_read_directly_is_a_direct_source_table() -> None:
    root = _roots(SCRIPT)["stmt:003"]
    assert root["direct_source_tables"] == ["ods.lim", "orders"]
    assert root["physical_source_tables"] == ["ods.lim", "orders"]
    assert "上游可追溯至" not in root["business_summary"]
    assert root["business_summary"].startswith("读取 ods.lim、orders")


def test_a_temporary_view_of_the_same_script_is_no_physical_table() -> None:
    root = _roots(SCRIPT)["stmt:002"]
    assert root["direct_source_tables"] == []
    assert root["physical_source_tables"] == []
    assert root["business_summary"] == "基于 tmp_v"


def test_the_view_definition_still_reads_its_physical_table() -> None:
    """Sentinel: the statement defining the view is unchanged."""
    root = _roots(SCRIPT)["stmt:001"]
    assert root["direct_source_tables"] == ["ods.real"]
    assert root["business_summary"] == "读取 ods.real"


def test_a_name_read_before_any_view_defines_it_is_a_table() -> None:
    """Only a statement after the view's definition reads the view."""
    roots = _roots(
        "INSERT OVERWRITE TABLE mart.a SELECT id FROM tmp_v;\n"
        "CREATE TEMPORARY VIEW tmp_v AS SELECT id FROM ods.real;\n"
        "INSERT OVERWRITE TABLE mart.b SELECT id FROM tmp_v;\n"
    )
    assert roots["stmt:001"]["direct_source_tables"] == ["tmp_v"]
    assert roots["stmt:003"]["direct_source_tables"] == []


def test_a_qualified_table_through_a_cte_is_still_traced() -> None:
    """Sentinel: a CTE is a scope, the table behind it is physical, not direct."""
    result = parse_scope_lineage(
        "INSERT OVERWRITE TABLE mart.c WITH c AS (SELECT id FROM ods.a) SELECT id FROM c",
        "t",
    )
    root = next(
        step
        for step in to_lineage_dict(result)["scope_profile"]["steps"]
        if step["scope_id"] == "ROOT"
    )
    assert root["direct_source_tables"] == []
    assert root["physical_source_tables"] == ["ods.a"]
    assert "上游可追溯至 ods.a" in root["business_summary"]
