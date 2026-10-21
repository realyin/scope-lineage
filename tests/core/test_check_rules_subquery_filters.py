"""Check 5 on an ``IN (subquery)`` filter, and on one predicate the SQL repeats.

The lineage renders a filter after SQLGlot's ``qualify``, which names every projection and
every table inside the subquery after itself: the script's
``emp_no in (select follow_no from sales)`` comes back as
``emp_no IN (SELECT sales.follow_no AS follow_no FROM sales AS sales)``. Quotes and
qualifiers already compare loosely; these echo aliases did not, so quoting the script
cited nothing and quoting the lineage was "not in the task SQL" -- no quote could pass.

A predicate the script writes in several scopes (each UNION branch, say) is one lineage
filter per scope; one quote cites them all, so an uncited one is one failure that says
where it occurs, not one identical failure per scope. All names are synthetic.
"""

from __future__ import annotations

from scope_lineage.semantics.checks_context import check_rules

SCRIPT = """INSERT OVERWRITE TABLE demo_dim.dim_probe_rela_df PARTITION (dt = '${bizdate}')
WITH sales AS (SELECT follow_no FROM demo_ods.ods_probe_sales_df WHERE dt = '${bizdate}')
SELECT emp_no FROM demo_dim.dim_probe_emp_df
WHERE emp_no in (
    select follow_no from sales
)
UNION ALL
SELECT id FROM demo_ods.ods_probe_dept_df
WHERE id in (select distinct lvl2_id from lake.demo_dim.dim_probe_emp_df where dt='${bizdate}')
UNION ALL
SELECT emp_no FROM demo_dim.dim_probe_emp_df
WHERE emp_no in (
    select follow_no from sales
)
"""

SALES_FILTER = (
    "`dim_probe_emp_df`.`emp_no` IN (SELECT `sales`.`follow_no` AS `follow_no` "
    "FROM `sales` AS `sales`)"
)
DEPT_FILTER = (
    "`ods_probe_dept_df`.`id` IN (SELECT DISTINCT `dim_probe_emp_df`.`lvl2_id` AS `lvl2_id` "
    "FROM `lake`.`demo_dim`.`dim_probe_emp_df` AS `dim_probe_emp_df` "
    "WHERE `dim_probe_emp_df`.`dt` = '${bizdate}')"
)


def _packet(*filters: tuple[str, str, str]) -> dict:
    return {
        "tasks": [{"sql": SCRIPT}],
        "lineage": {
            "rules": [
                {"kind": "filter", "partition_filter": False, "expression": text,
                 "task": "dim_probe_rela", "id": rule_id, "statement_id": "stmt:001",
                 "scope": scope}
                for text, rule_id, scope in filters
            ]
        },
    }


def _document(*quoted: str) -> dict:
    rules = [
        {"id": f"r{n}", "kind": "filter", "text": "…", "sql": text, "sources": ["sql"]}
        for n, text in enumerate(quoted, 1)
    ]
    return {"rules": rules, "summary": {"scope": []}}


def _failures(document: dict, packet: dict) -> list[dict]:
    return [r for r in check_rules(document, packet) if r["status"] != "pass"]


def test_quoting_the_script_cites_a_subquery_filter_the_lineage_aliased() -> None:
    packet = _packet((SALES_FILTER, "p1", "union:main:b01"))

    assert _failures(_document("emp_no in (\n    select follow_no from sales\n)"), packet) == []


def test_quoting_the_script_cites_a_subquery_over_a_qualified_table() -> None:
    packet = _packet((DEPT_FILTER, "p2", "union:main:b02"))
    quote = (
        "id in (select distinct lvl2_id from lake.demo_dim.dim_probe_emp_df "
        "where dt='${bizdate}')"
    )

    assert _failures(_document(quote), packet) == []


def test_quoting_the_lineage_form_is_found_in_the_task_sql() -> None:
    packet = _packet((SALES_FILTER, "p1", "union:main:b01"))

    assert _failures(_document(SALES_FILTER.replace("`", "")), packet) == []


def test_a_subquery_over_another_column_still_cites_nothing() -> None:
    other = SALES_FILTER.replace("follow_no", "lead_no")
    packet = _packet((other, "p1", "union:main:b01"))

    [failure] = [
        item for item in _failures(_document("emp_no in (select follow_no from sales)"), packet)
        if item["at"] == "rules"
    ]
    assert "lead_no" in failure["message"]


def test_one_predicate_in_several_scopes_is_one_failure_naming_each() -> None:
    packet = _packet(
        (SALES_FILTER, "p1", "union:main:b01"),
        (SALES_FILTER, "p3", "union:main:b03"),
    )

    [failure] = _failures(_document(), packet)
    assert "p1（union:main:b01）" in failure["message"]
    assert "p3（union:main:b03）" in failure["message"]
    assert "2 处" in failure["message"]


def test_a_predicate_quoted_once_passes_in_every_scope() -> None:
    packet = _packet(
        (SALES_FILTER, "p1", "union:main:b01"),
        (SALES_FILTER, "p3", "union:main:b03"),
    )

    assert _failures(_document("emp_no in (select follow_no from sales)"), packet) == []
