"""Regression coverage for member access on aggregate STRUCT results."""

from scope_lineage import parse_scope_lineage, to_dict


def _root_output(sql: str, field_name: str) -> tuple[dict, dict]:
    lineage = to_dict(parse_scope_lineage(sql, "aggregate_struct_member"))
    output = next(
        item for item in lineage["scopes"]["ROOT"]["outputs"]
        if item["name"] == field_name
    )
    trace = next(
        item for item in lineage["end_to_end_lineage"]
        if item["column"] == field_name
    )
    return output, trace


def test_max_named_struct_member_keeps_selection_and_value_dependencies():
    output, trace = _root_output(
        """
        INSERT OVERWRITE TABLE mart.t
        WITH last_layer AS (
          SELECT MAX(NAMED_STRUCT(
            'update_time', source.update_time,
            'layer_name', source.layer_name
          )) AS last_name
          FROM ods.layer source
        )
        SELECT last_layer.last_name.layer_name AS layer_name
        FROM last_layer
        """,
        "layer_name",
    )

    expanded = output["expanded_expression"].upper()
    assert "MAX(" in expanded
    assert "STRUCT(" in expanded
    assert expanded.endswith(".`LAYER_NAME`")
    assert output["expression_resolution"]["status"] == "resolved"
    assert output["expression_resolution"]["physical_source_fields"] == [
        {"table": "ods.layer", "field": "update_time"},
        {"table": "ods.layer", "field": "layer_name"},
    ]
    assert trace["physical_sources"] == [
        {"table": "ods.layer", "column": "update_time", "transform": "AGGREGATE"},
        {"table": "ods.layer", "column": "layer_name", "transform": "AGGREGATE"},
    ]


def test_min_struct_member_keeps_aggregate_wrapper():
    output, _ = _root_output(
        """
        INSERT OVERWRITE TABLE mart.t
        WITH last_layer AS (
          SELECT MIN(STRUCT(
            source.update_time AS update_time,
            source.layer_name AS layer_name
          )) AS first_name
          FROM ods.layer source
        )
        SELECT last_layer.first_name.layer_name AS layer_name
        FROM last_layer
        """,
        "layer_name",
    )

    expanded = output["expanded_expression"].upper()
    assert "MIN(" in expanded
    assert "STRUCT(" in expanded
    assert expanded.endswith(".`LAYER_NAME`")
    assert output["expression_resolution"]["physical_source_fields"] == [
        {"table": "ods.layer", "field": "update_time"},
        {"table": "ods.layer", "field": "layer_name"},
    ]


def test_non_aggregate_struct_member_still_resolves_to_selected_leaf_only():
    output, trace = _root_output(
        """
        INSERT OVERWRITE TABLE mart.t
        WITH layer_details AS (
          SELECT NAMED_STRUCT(
            'update_time', source.update_time,
            'layer_name', source.layer_name
          ) AS details
          FROM ods.layer source
        )
        SELECT layer_details.details.layer_name AS layer_name
        FROM layer_details
        """,
        "layer_name",
    )

    assert output["expanded_expression"] == "`ods.layer`.`layer_name`"
    assert output["expression_resolution"]["physical_source_fields"] == [
        {"table": "ods.layer", "field": "layer_name"},
    ]
    assert trace["physical_sources"] == [
        {"table": "ods.layer", "column": "layer_name", "transform": "EXPRESSION"},
    ]
