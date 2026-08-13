"""Domain-neutral regression matrix for the public SQL Lineage Core."""

from __future__ import annotations

import pytest

from scope_lineage import parse_scope_lineage, to_lineage_dict


SCHEMA = {
    "ods.orders": ["customer_id", "amount"],
    "ods.left_source": ["id", "amount", "dimension_id", "enabled"],
    "ods.right_source": ["id", "amount"],
    "dim.lookup": ["id", "name"],
    "ods.source": ["id", "name", "amount", "refund", "enabled"],
}


@pytest.mark.parametrize(
    ("case_id", "sql", "statement_kind", "sources", "scope_kinds"),
    [
        (
            "cte_window",
            """
            INSERT OVERWRITE TABLE mart.customer_summary PARTITION (dt='2026-08-10')
            WITH base AS (
              SELECT customer_id, amount FROM ods.orders WHERE amount > 0
            ), aggregated AS (
              SELECT customer_id, SUM(amount) AS total_amount, COUNT(*) AS order_count
              FROM base GROUP BY customer_id
            )
            SELECT customer_id, total_amount, order_count,
                   ROW_NUMBER() OVER (ORDER BY total_amount DESC) AS row_number
            FROM aggregated
            """,
            "INSERT_OVERWRITE",
            ["ods.orders"],
            {"cte", "root"},
        ),
        (
            "union_all",
            """
            INSERT INTO mart.combined
            SELECT id, amount FROM ods.left_source
            UNION ALL
            SELECT id, amount FROM ods.right_source
            """,
            "INSERT",
            ["ods.left_source", "ods.right_source"],
            {"union", "union_branch", "root"},
        ),
        (
            "join_filter",
            """
            INSERT INTO mart.enriched
            SELECT source.id, lookup.name
            FROM ods.left_source source
            LEFT JOIN dim.lookup lookup ON source.dimension_id = lookup.id
            WHERE source.enabled = 1
            """,
            "INSERT",
            ["dim.lookup", "ods.left_source"],
            {"root"},
        ),
        (
            "create_table_as_select",
            "CREATE TABLE mart.snapshot AS SELECT id, name FROM ods.source",
            "CTAS",
            ["ods.source"],
            {"root"},
        ),
        (
            "merge",
            """
            MERGE INTO mart.target target
            USING ods.source source ON target.id = source.id
            WHEN MATCHED THEN UPDATE SET target.name = source.name
            WHEN NOT MATCHED THEN INSERT (id, name) VALUES (source.id, source.name)
            """,
            "MERGE",
            ["ods.source"],
            {"subquery", "root"},
        ),
        (
            "subquery",
            """
            INSERT INTO mart.filtered
            SELECT nested.id
            FROM (SELECT id FROM ods.source WHERE enabled = 1) nested
            """,
            "INSERT",
            ["ods.source"],
            {"subquery", "root"},
        ),
    ],
)
def test_public_core_statement_and_scope_matrix(
    case_id: str,
    sql: str,
    statement_kind: str,
    sources: list[str],
    scope_kinds: set[str],
) -> None:
    document = to_lineage_dict(
        parse_scope_lineage(sql, case_id, schema=SCHEMA)
    )

    assert document["parse_status"] == "ok"
    assert document["syntax_status"] == "strict_ok"
    assert document["stmt_kind"] == statement_kind
    assert document["source_tables"] == sources
    assert {scope["kind"] for scope in document["scopes"].values()} == scope_kinds
    assert document["end_to_end_lineage"]


def test_public_core_preserves_aggregation_window_and_static_partition_facts() -> None:
    document = to_lineage_dict(
        parse_scope_lineage(
            """
            INSERT OVERWRITE TABLE mart.customer_summary PARTITION (dt='2026-08-10')
            WITH aggregated AS (
              SELECT customer_id, SUM(amount) AS total_amount
              FROM ods.orders GROUP BY customer_id
            )
            SELECT customer_id, total_amount,
                   ROW_NUMBER() OVER (ORDER BY total_amount DESC) AS row_number
            FROM aggregated
            """,
            "aggregation_window_partition",
            schema=SCHEMA,
        )
    )

    by_column = {item["column"]: item for item in document["end_to_end_lineage"]}
    assert document["target_partition_mode"] == "static"
    assert document["target_partition_spec"] == {"dt": "2026-08-10"}
    assert by_column["total_amount"]["physical_sources"] == [
        {"table": "ods.orders", "column": "amount", "transform": "AGGREGATE"}
    ]
    assert by_column["row_number"]["transform"] == "WINDOW"


def test_public_core_preserves_conditional_expression_sources() -> None:
    document = to_lineage_dict(
        parse_scope_lineage(
            """
            INSERT INTO mart.amounts
            SELECT id,
                   CASE WHEN amount > 0
                        THEN CAST(amount AS DECIMAL(18, 2))
                        ELSE COALESCE(refund, 0)
                   END AS net_amount
            FROM ods.source
            """,
            "conditional_expression",
            schema=SCHEMA,
        )
    )

    net_amount = next(
        item for item in document["end_to_end_lineage"]
        if item["column"] == "net_amount"
    )
    assert net_amount["transform"] == "CONDITIONAL"
    assert {
        (source["table"], source["column"])
        for source in net_amount["physical_sources"]
    } == {("ods.source", "amount"), ("ods.source", "refund")}
