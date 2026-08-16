"""Task-level value and row-membership lineage across ordered statements."""

from __future__ import annotations

import json

from scope_lineage import (
    TargetColumnMetadata,
    TargetMetadataMap,
    TargetTableMetadata,
    load_schema_sources,
    to_task_lineage_dict,
    validate_cross_references,
    validate_diagnostics_document,
    validate_lineage_document,
    write_task_lineage,
)
from scope_lineage.scope.task_lineage import parse_task_lineage


SCHEMA = {
    "mart.orders": ["id", "customer_id", "amount", "status"],
    "ods.orders": ["id", "customer_id", "amount", "status"],
    "ods.blocked_customers": ["customer_id"],
}


def _final_field(result, column: str) -> dict:
    return next(
        item
        for item in result.end_to_end_lineage
        if item["table"] == "mart.orders" and item["column"] == column
    )


def test_truncate_then_insert_uses_the_later_write_as_final_state() -> None:
    result = parse_task_lineage(
        """
        TRUNCATE TABLE mart.orders;
        INSERT INTO mart.orders
        SELECT id, customer_id, amount, status FROM ods.orders;
        """,
        task_name="truncate_then_insert",
        schema=SCHEMA,
    )

    assert [item["stmt_kind"] for item in result.statements] == [
        "TRUNCATETABLE",
        "INSERT",
    ]
    truncate, insert = result.statements
    assert truncate["effect"]["rowset_effect"]["operation"] == "RESET_ALL_ROWS"
    assert truncate["effect"]["column_effect"]["schema_preserved"] is True
    assert result.final_table_states["mart.orders"] == insert["output_state"]
    assert result.table_state_graph["nodes_by_id"][truncate["output_state"]][
        "known_empty"
    ] is True
    assert result.table_state_graph["nodes_by_id"][insert["output_state"]][
        "known_empty"
    ] is False
    assert _final_field(result, "amount")["value_sources"] == [
        {
            "source_kind": "physical_field",
            "table": "ods.orders",
            "column": "amount",
            "transform": "DIRECT",
        }
    ]


def test_empty_statement_slots_are_preserved_in_order() -> None:
    result = parse_task_lineage(
        "SET spark.sql.ansi.enabled=false; ; "
        "INSERT INTO mart.orders "
        "SELECT id, customer_id, amount, status FROM ods.orders",
        task_name="empty_slot",
        schema=SCHEMA,
    )

    assert [item["statement_id"] for item in result.statements] == [
        "stmt:001",
        "stmt:002",
        "stmt:003",
    ]
    assert result.statements[1] == {
        "statement_id": "stmt:002",
        "statement_index": 1,
        "stmt_kind": "EMPTY",
        "category": "empty_statement",
        "model_status": "ignored",
        "normalized_sql": "",
    }


def test_delete_preserves_values_but_adds_row_membership_dependencies() -> None:
    result = parse_task_lineage(
        """
        DELETE FROM mart.orders
        WHERE customer_id IN (
          SELECT customer_id FROM ods.blocked_customers
        )
        """,
        task_name="delete_membership",
        schema=SCHEMA,
    )

    statement = result.statements[0]
    assert statement["model_status"] == "modeled"
    assert statement["effect"]["rowset_effect"]["operation"] == "DELETE_MATCHED_ROWS"
    assert statement["effect"]["column_effect"] == {
        "value_mode": "PASSTHROUGH_SURVIVING_ROWS",
        "value_changed_columns": [],
        "row_membership_affected_columns": ["*"],
    }
    amount = _final_field(result, "amount")
    assert amount["value_sources"] == [
        {
            "source_kind": "prior_table_state",
            "state_id": "state:mart.orders:000",
            "table": "mart.orders",
            "column": "amount",
        }
    ]
    assert amount["row_membership_sources"] == [
        {"table": "mart.orders", "column": "customer_id"},
        {"table": "ods.blocked_customers", "column": "customer_id"},
    ]


def test_delete_without_predicate_keeps_schema_but_has_no_surviving_values() -> None:
    result = parse_task_lineage(
        "DELETE FROM mart.orders",
        task_name="delete_all",
        schema=SCHEMA,
    )

    statement = result.statements[0]
    final_state = result.table_state_graph["nodes_by_id"][
        statement["output_state"]
    ]
    assert statement["effect"]["rowset_effect"]["operation"] == (
        "DELETE_ALL_ROWS"
    )
    assert statement["effect"]["column_effect"]["value_mode"] == (
        "NO_SURVIVING_ROWS"
    )
    assert final_state["known_empty"] is True
    assert _final_field(result, "amount")["value_sources"] == []


def test_insert_into_combines_prior_state_and_appended_value_sources() -> None:
    result = parse_task_lineage(
        """
        INSERT INTO mart.orders
        SELECT id, customer_id, amount, status FROM ods.orders
        """,
        task_name="append",
        schema=SCHEMA,
    )

    amount = _final_field(result, "amount")
    assert [item["source_kind"] for item in amount["value_sources"]] == [
        "prior_table_state",
        "physical_field",
    ]


def test_insert_overwrite_replaces_prior_value_sources() -> None:
    result = parse_task_lineage(
        """
        INSERT OVERWRITE TABLE mart.orders
        SELECT id, customer_id, amount, status FROM ods.orders
        """,
        task_name="replace",
        schema=SCHEMA,
    )

    assert _final_field(result, "amount")["value_sources"] == [
        {
            "source_kind": "physical_field",
            "table": "ods.orders",
            "column": "amount",
            "transform": "DIRECT",
        }
    ]


def test_partition_overwrite_preserves_unaffected_partition_sources() -> None:
    schema = {
        **SCHEMA,
        "mart.partitioned_orders": ["id", "amount", "dt"],
        "ods.partitioned_orders": ["id", "amount"],
    }
    result = parse_task_lineage(
        """
        INSERT OVERWRITE TABLE mart.partitioned_orders
        PARTITION (dt='2026-08-14')
        SELECT id, amount FROM ods.partitioned_orders
        """,
        task_name="partition_overwrite",
        schema=schema,
    )

    statement = result.statements[0]
    assert statement["effect"]["rowset_effect"]["operation"] == (
        "REPLACE_PARTITION"
    )
    amount = next(
        item
        for item in result.end_to_end_lineage
        if item["table"] == "mart.partitioned_orders"
        and item["column"] == "amount"
    )
    assert [source["source_kind"] for source in amount["value_sources"]] == [
        "prior_table_state",
        "physical_field",
    ]


def test_partition_truncate_preserves_unaffected_rows_and_value_sources() -> None:
    schema = {
        **SCHEMA,
        "mart.partitioned_orders": ["id", "amount", "dt"],
    }
    result = parse_task_lineage(
        """
        TRUNCATE TABLE mart.partitioned_orders
        PARTITION (dt='2026-08-14')
        """,
        task_name="partition_truncate",
        schema=schema,
    )

    statement = result.statements[0]
    final_state = result.table_state_graph["nodes_by_id"][
        statement["output_state"]
    ]
    assert statement["effect"]["rowset_effect"]["operation"] == (
        "RESET_PARTITION"
    )
    assert final_state["known_empty"] is False
    amount = next(
        item
        for item in result.end_to_end_lineage
        if item["table"] == "mart.partitioned_orders"
        and item["column"] == "amount"
    )
    assert amount["value_sources"][0]["source_kind"] == "prior_table_state"
    assert amount["row_membership_sources"] == [
        {"table": "mart.partitioned_orders", "column": "dt"}
    ]


def test_ctas_creates_state_without_a_prior_target_branch() -> None:
    result = parse_task_lineage(
        """
        CREATE TABLE mart.orders AS
        SELECT id, customer_id, amount, status FROM ods.orders
        """,
        task_name="ctas",
        schema=SCHEMA,
    )

    statement = result.statements[0]
    assert statement["stmt_kind"] == "CTAS"
    assert statement["input_states"] == []
    assert statement["effect"]["rowset_effect"]["operation"] == "REPLACE"
    assert all(
        source["source_kind"] != "prior_table_state"
        for source in _final_field(result, "amount")["value_sources"]
    )


def test_merge_combines_prior_state_with_modeled_branch_values() -> None:
    result = parse_task_lineage(
        """
        MERGE INTO mart.orders target
        USING ods.orders source
        ON target.id = source.id
        WHEN MATCHED THEN UPDATE SET target.amount = source.amount
        WHEN NOT MATCHED THEN
          INSERT (id, customer_id, amount, status)
          VALUES (source.id, source.customer_id, source.amount, source.status)
        """,
        task_name="merge",
        schema=SCHEMA,
    )

    statement = result.statements[0]
    assert statement["stmt_kind"] == "MERGE"
    assert statement["effect"]["rowset_effect"]["operation"] == "MERGE"
    amount_sources = _final_field(result, "amount")["value_sources"]
    assert any(
        source["source_kind"] == "prior_table_state"
        for source in amount_sources
    )
    assert any(
        source.get("table") == "ods.orders"
        for source in amount_sources
    )
    assert _final_field(result, "amount")["row_membership_sources"] == [
        {"table": "mart.orders", "column": "id"},
        {"table": "ods.orders", "column": "id"},
    ]


def test_merge_delete_condition_is_row_membership_not_value_provenance() -> None:
    result = parse_task_lineage(
        """
        MERGE INTO mart.orders target
        USING ods.orders source
        ON target.id = source.id
        WHEN MATCHED AND source.status = 'deleted' THEN DELETE
        WHEN MATCHED THEN UPDATE SET target.amount = source.amount
        """,
        task_name="merge_delete",
        schema=SCHEMA,
    )

    amount = _final_field(result, "amount")
    assert amount["row_membership_sources"] == [
        {"table": "mart.orders", "column": "id"},
        {"table": "ods.orders", "column": "id"},
        {"table": "ods.orders", "column": "status"},
    ]
    assert all(
        source.get("column") != "status"
        for source in amount["value_sources"]
    )
    assert amount["value_condition_sources"] == amount[
        "row_membership_sources"
    ]


def test_update_changes_selected_values_and_keeps_row_membership() -> None:
    result = parse_task_lineage(
        """
        UPDATE mart.orders
        SET amount = amount * 2
        WHERE status = 'open'
        """,
        task_name="update",
        schema=SCHEMA,
    )

    statement = result.statements[0]
    assert statement["effect"]["rowset_effect"]["operation"] == "PRESERVE_ROWS"
    assert statement["effect"]["column_effect"]["value_changed_columns"] == [
        "amount"
    ]
    assert statement["effect"]["condition_sources"] == [
        {"table": "mart.orders", "column": "status"}
    ]
    amount = _final_field(result, "amount")
    assert amount["row_membership_sources"] == []
    assert amount["value_condition_sources"] == [
        {"table": "mart.orders", "column": "status"}
    ]


def test_delete_without_schema_keeps_table_state_and_reports_fact_gap() -> None:
    result = parse_task_lineage(
        "DELETE FROM mart.orders WHERE expired = true",
        task_name="delete_without_schema",
    )

    assert result.final_table_states["mart.orders"]
    assert result.end_to_end_lineage == []
    assert result.analysis_status["status"] == "partial"
    assert result.diagnostics["lineage_fact_gaps"][0]["gap_type"] == (
        "schema_missing_for_state_passthrough"
    )


def test_projection_fact_gaps_roll_up_to_task_analysis_with_statement_id() -> None:
    result = parse_task_lineage(
        "INSERT INTO mart.orders SELECT id FROM ods.first a "
        "JOIN ods.second b ON a.id = b.id",
        task_name="projection_gap",
        schema={"ods.first": ["id"], "ods.second": ["id"]},
    )

    assert result.analysis_status == {
        "status": "partial",
        "blocking_reasons": ["lineage_fact_gap"],
    }
    assert result.diagnostics["lineage_fact_gaps"][0]["statement_id"] == (
        "stmt:001"
    )
    assert result.diagnostics["lineage_fact_gaps"][0]["root_impact"] is True


def test_unexpanded_projection_wildcard_is_an_explicit_incomplete_fact() -> None:
    result = parse_task_lineage(
        "INSERT OVERWRITE TABLE mart.orders SELECT * FROM ods.unknown",
        task_name="wildcard_gap",
        schema={"mart.orders": ["id", "amount"]},
    )

    assert result.analysis_status["status"] == "partial"
    gap = result.diagnostics["lineage_fact_gaps"][0]
    assert gap["gap_type"] == "projection_wildcard_unexpanded"
    assert gap["root_impact"] is True
    wildcard = _final_field(result, "*")
    assert wildcard["trace_complete"] is False
    assert wildcard["missing_reasons"] == ["projection_wildcard_unexpanded"]


def test_task_writer_emits_and_validates_only_the_v2_contract_pair(
    tmp_path,
) -> None:
    result = parse_task_lineage(
        """
        DELETE FROM mart.orders WHERE status = 'closed';
        INSERT INTO mart.orders
        SELECT id, customer_id, amount, status FROM ods.orders;
        """,
        task_name="task_contract",
        schema=SCHEMA,
    )

    output = write_task_lineage(result, tmp_path)
    assert {path.name for path in output.iterdir()} == {
        "lineage.json",
        "diagnostics.json",
    }
    lineage = json.loads((output / "lineage.json").read_text(encoding="utf-8"))
    diagnostics = json.loads(
        (output / "diagnostics.json").read_text(encoding="utf-8")
    )
    assert lineage["schema_version"] == "2.0"
    assert diagnostics["schema_version"] == "2.0"
    assert lineage["final_table_states"]["mart.orders"] == (
        lineage["statement_sequence"][-1]["output_state"]
    )
    validate_lineage_document(lineage)
    validate_diagnostics_document(diagnostics)


def test_task_cross_reference_validation_covers_final_field_state_refs() -> None:
    result = parse_task_lineage(
        "INSERT INTO mart.orders SELECT id, customer_id, amount, status "
        "FROM ods.orders",
        task_name="cross_refs",
        schema=SCHEMA,
    )
    document = to_task_lineage_dict(result)
    document["end_to_end_lineage"][0]["target_state"] = "state:missing:999"
    document["end_to_end_lineage"][0]["value_sources"][0] = {
        "source_kind": "prior_table_state",
        "state_id": "state:missing:000",
    }

    errors = validate_cross_references(document)
    assert any("target_state='state:missing:999'" in item for item in errors)
    assert any("state_id='state:missing:000'" in item for item in errors)


def test_compact_task_writer_preserves_json_semantics_and_reduces_bytes(
    tmp_path,
) -> None:
    result = parse_task_lineage(
        "DELETE FROM mart.orders WHERE status = 'closed'",
        task_name="compact",
        schema=SCHEMA,
    )
    pretty = write_task_lineage(result, tmp_path / "pretty")
    compact = write_task_lineage(result, tmp_path / "compact", compact=True)

    for name in ("lineage.json", "diagnostics.json"):
        assert json.loads((pretty / name).read_text(encoding="utf-8")) == json.loads(
            (compact / name).read_text(encoding="utf-8")
        )
        assert (compact / name).stat().st_size < (pretty / name).stat().st_size


def test_task_diagnostics_report_merged_metadata_coverage(tmp_path) -> None:
    primary = tmp_path / "primary.json"
    primary.write_text(
        '{"ods.unrelated": ["id"], "mart.orders": ["id"]}',
        encoding="utf-8",
    )
    fallback = tmp_path / "fallback.csv"
    fallback.write_text(
        "table_name,column_name\n"
        "mart.orders,other_id\n"
        "ods.orders,id\n"
        "ods.unrelated,other_id\n",
        encoding="utf-8",
    )
    schema = load_schema_sources([primary, fallback])

    result = parse_task_lineage(
        "INSERT OVERWRITE TABLE mart.orders SELECT id FROM ods.orders",
        task_name="coverage",
        schema=schema,
    )

    coverage = result.diagnostics["metadata_coverage"]
    assert coverage["referenced_table_count"] == 2
    assert coverage["covered_table_count"] == 2
    assert coverage["missing_table_count"] == 0
    assert coverage["schema_source_count"] == 2
    assert coverage["metadata_conflicts"] == [{
        "table": "mart.orders",
        "authoritative_columns": ["id"],
        "fallback_columns": ["other_id"],
        "fallback_source_index": 1,
        "resolution": "kept_authoritative",
    }]


def test_v2_target_binding_observation_distinguishes_absent_and_fallback() -> None:
    absent = parse_task_lineage(
        "INSERT INTO mart.orders SELECT id FROM ods.orders",
        task_name="absent",
        schema=SCHEMA,
        target_metadata=TargetMetadataMap(),
    )
    assert absent.statements[0]["target_field_binding"] == {
        "status": "absent",
        "reason_code": "target_table_not_found",
    }

    metadata = TargetMetadataMap({
        "mart.orders": TargetTableMetadata(
            table_name="mart.orders",
            full_table_name="mart.orders",
            columns=[
                TargetColumnMetadata("id", ordinal=0),
                TargetColumnMetadata("amount", ordinal=1),
            ],
            partition_columns=[],
            ddl="CREATE TABLE mart.orders (id BIGINT, amount BIGINT)",
            source_file="synthetic.json",
        )
    })
    fallback = parse_task_lineage(
        "INSERT INTO mart.orders SELECT id FROM ods.orders",
        task_name="fallback",
        schema=SCHEMA,
        target_metadata=metadata,
    )
    observation = fallback.statements[0]["target_field_binding"]
    assert observation["status"] == "fallback"
    assert observation["reason_code"] == "column_count_mismatch"


def test_v2_writer_canonicalizes_warning_order(tmp_path) -> None:
    result = parse_task_lineage(
        "DELETE FROM mart.orders WHERE status = 'closed'",
        task_name="warning_order",
        schema=SCHEMA,
    )
    result.diagnostics["warnings"] = [
        {"statement_id": "stmt:002", "type": "z", "scope": "TASK", "msg": "z"},
        {"statement_id": "stmt:001", "type": "a", "scope": "TASK", "msg": "a"},
    ]

    output = write_task_lineage(result, tmp_path)
    diagnostics = json.loads(
        (output / "diagnostics.json").read_text(encoding="utf-8")
    )
    assert [item["statement_id"] for item in diagnostics["warnings"]] == [
        "stmt:001",
        "stmt:002",
    ]


MERGE_CTE_SCHEMA = {
    "ods.events": ["id", "event_type", "account_id"],
    "dim.accounts": ["account_id", "account_key"],
    "mart.event_target": ["id", "event_type", "account_key"],
}

MERGE_CTE_SQL = """
WITH staged AS (
  SELECT e.id, e.event_type, a.account_key
  FROM ods.events e
  LEFT JOIN dim.accounts a ON e.account_id = a.account_id
)
MERGE INTO mart.event_target target
USING (SELECT id, event_type, account_key FROM staged) source
ON target.id = source.id
WHEN MATCHED THEN UPDATE SET
  target.id = source.id,
  target.event_type = source.event_type,
  target.account_key = source.account_key
WHEN NOT MATCHED THEN INSERT *
"""


def _rowset_effect(result, index: int = 0) -> dict:
    return result.statements[index]["effect"]["rowset_effect"]


def test_merge_condition_sources_trace_through_a_cte_to_physical_fields() -> None:
    """A CTE is a query block, never a row-membership source.

    ``row_membership_sources`` asserts that a physical field decided whether a target
    row exists, so a CTE name there is a claim the warehouse cannot answer — and it
    then travels on into metadata coverage as a table nobody can supply.
    """
    result = parse_task_lineage(
        MERGE_CTE_SQL,
        task_name="merge_cte_condition_sources",
        schema=MERGE_CTE_SCHEMA,
    )

    assert _rowset_effect(result)["membership_sources"] == [
        {"table": "mart.event_target", "column": "id"},
        {"table": "ods.events", "column": "id"},
    ]
    assert result.analysis_status == {"status": "complete", "blocking_reasons": []}
    assert result.diagnostics["lineage_fact_gaps"] == []

    coverage = result.diagnostics["metadata_coverage"]
    assert "staged" not in coverage["missing_tables"]
    assert "staged" not in coverage["covered_tables"]


def test_merge_condition_sources_keep_every_branch_of_a_union_using() -> None:
    """Two candidate roots are two facts, not a reason to publish ``UNKNOWN``."""
    result = parse_task_lineage(
        """
        MERGE INTO mart.event_target target
        USING (
          SELECT id FROM ods.events
          UNION ALL
          SELECT account_id AS id FROM dim.accounts
        ) source
        ON target.id = source.id
        WHEN MATCHED THEN UPDATE SET target.event_type = source.id
        """,
        task_name="merge_union_condition_sources",
        schema=MERGE_CTE_SCHEMA,
    )

    assert _rowset_effect(result)["membership_sources"] == [
        {"table": "mart.event_target", "column": "id"},
        {"table": "ods.events", "column": "id"},
        {"table": "dim.accounts", "column": "account_id"},
    ]
    assert result.analysis_status["status"] == "complete"


def test_an_untraceable_merge_condition_is_a_fact_gap_not_a_guessed_table() -> None:
    result = parse_task_lineage(
        """
        MERGE INTO mart.event_target target
        USING (SELECT id FROM ods.events) source
        ON target.id = source.missing_col
        WHEN MATCHED THEN UPDATE SET target.event_type = source.id
        """,
        task_name="merge_untraceable_condition",
        schema=MERGE_CTE_SCHEMA,
    )

    # The unresolvable side is absent rather than invented.
    assert _rowset_effect(result)["membership_sources"] == [
        {"table": "mart.event_target", "column": "id"},
    ]
    assert result.diagnostics["lineage_fact_gaps"] == [
        {
            "gap_type": "merge_condition_source_unresolved",
            "statement_id": "stmt:001",
            "source_alias": "source",
            "column": "missing_col",
            "root_impact": True,
            "needed_fact": "MERGE condition source scope and physical field",
        }
    ]
    assert result.analysis_status == {
        "status": "partial",
        "blocking_reasons": ["lineage_fact_gap"],
    }
