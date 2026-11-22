"""4.5-b (defensive): a column's metadata is found whatever case either side spells it in.

``parse`` lower-cases metadata column names, so the semantic profile never met a
mixed-case ``column_details`` from this tool. A lineage.json written by hand or by an
older version can carry ``ID`` while the SQL says ``id``; the lookup used to miss it.
"""

from __future__ import annotations

from scope_lineage.render.semantic_profile import _column_detail


def test_the_lookup_ignores_case_on_both_sides() -> None:
    item = {"column_details": [{"name": "Cust_ID", "type": "bigint", "comment": "客户"}]}
    assert _column_detail(item, "cust_id")["comment"] == "客户"
    assert _column_detail(item, "CUST_ID")["type"] == "bigint"


def test_a_lower_case_name_is_found_as_before() -> None:
    """Sentinel: the case parse produces."""
    item = {"column_details": [{"name": "id", "type": "string", "comment": "标识"}]}
    assert _column_detail(item, "id")["comment"] == "标识"
    assert _column_detail(item, "other") == {}
