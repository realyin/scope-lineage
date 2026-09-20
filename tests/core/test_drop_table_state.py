"""`DROP TABLE` / `DROP VIEW` is a modelled table-state event, not a capability gap.

The recreate pattern ``DROP TABLE IF EXISTS t; CREATE TABLE t AS SELECT ...`` is the
single most common shape behind ``blocking_reasons: ["unsupported_data_change"]`` on a
real corpus, and the CTAS half of it was always modelled. The DROP downgraded the whole
task because ``_unsupported_statement_changes_data`` answered "yes" for every ``exp.Drop``
(DROP-001). Dropping a relation is a state this document can state exactly: the relation
is gone, and whatever a later statement does to the name starts from nothing.
"""

from __future__ import annotations

from scope_lineage.scope.task_lineage import parse_task_lineage


SCHEMA = {"ods.source": ["id", "value"], "mart.target": ["id", "value"]}


def _nodes(result, table: str) -> list[dict]:
    return [
        node
        for node in result.table_state_graph["nodes"]
        if node["table"] == table
    ]


def _edges(result, table: str) -> list[dict]:
    states = {node["state_id"] for node in _nodes(result, table)}
    return [
        edge
        for edge in result.table_state_graph["edges"]
        if edge["to"] in states or edge["from"] in states
    ]


def _warning_types(result) -> list[str]:
    return [warning["type"] for warning in result.diagnostics["warnings"]]


def test_drop_then_ctas_is_a_complete_analysis() -> None:
    result = parse_task_lineage(
        "DROP TABLE IF EXISTS mart.target;\n"
        "CREATE TABLE mart.target AS SELECT id, value FROM ods.source",
        task_name="drop_recreate",
        schema=SCHEMA,
    )

    assert result.analysis_status == {"status": "complete", "blocking_reasons": []}
    assert [item["model_status"] for item in result.statements] == [
        "modeled",
        "modeled",
    ]


def test_the_recreated_tables_final_state_is_the_ctas_state() -> None:
    result = parse_task_lineage(
        "DROP TABLE IF EXISTS mart.target;\n"
        "CREATE TABLE mart.target AS SELECT id, value FROM ods.source",
        task_name="drop_recreate",
        schema=SCHEMA,
    )

    final = result.final_table_states["mart.target"]
    node = result.table_state_graph["nodes_by_id"][final]
    assert node["producer_statement_id"] == "stmt:002"
    assert not node.get("known_dropped")
    assert {
        row["column"]
        for row in result.end_to_end_lineage
        if row["table"] == "mart.target"
    } == {"id", "value"}


def test_the_history_keeps_the_drop_ahead_of_the_create() -> None:
    result = parse_task_lineage(
        "DROP TABLE IF EXISTS mart.target;\n"
        "CREATE TABLE mart.target AS SELECT id, value FROM ods.source",
        task_name="drop_recreate",
        schema=SCHEMA,
    )

    nodes = _nodes(result, "mart.target")
    dropped = [node for node in nodes if node.get("known_dropped")]
    assert [node["producer_statement_id"] for node in dropped] == ["stmt:001"]
    assert dropped[0]["ordinal"] < max(node["ordinal"] for node in nodes)
    assert {
        (edge["statement_id"], edge["effect"])
        for edge in _edges(result, "mart.target")
    } == {("stmt:001", "DROP")}


def test_a_drop_with_nothing_after_it_leaves_the_table_dropped() -> None:
    result = parse_task_lineage(
        "DROP TABLE mart.target",
        task_name="drop_only",
        schema=SCHEMA,
    )

    assert result.analysis_status == {"status": "complete", "blocking_reasons": []}
    final = result.final_table_states["mart.target"]
    assert result.table_state_graph["nodes_by_id"][final]["known_dropped"] is True
    assert result.table_state_graph["nodes_by_id"][final]["known_empty"] is True
    # A relation that no longer exists has no columns to trace.
    assert not [
        row for row in result.end_to_end_lineage if row["table"] == "mart.target"
    ]


def test_a_drop_of_a_table_the_task_never_touches_again_is_still_modeled() -> None:
    result = parse_task_lineage(
        "DROP TABLE IF EXISTS mart.scratch;\n"
        "INSERT INTO mart.target SELECT id, value FROM ods.source",
        task_name="drop_scratch",
        schema={**SCHEMA, "mart.scratch": ["id"]},
    )

    assert result.analysis_status["status"] == "complete"
    final = result.final_table_states["mart.scratch"]
    assert result.table_state_graph["nodes_by_id"][final]["known_dropped"] is True


def test_an_insert_after_a_drop_composes_the_way_truncate_then_insert_does() -> None:
    result = parse_task_lineage(
        "DROP TABLE IF EXISTS mart.target;\n"
        "INSERT INTO mart.target SELECT id, value FROM ods.source",
        task_name="drop_then_insert",
        schema=SCHEMA,
    )

    assert result.analysis_status["status"] == "complete"
    final = result.final_table_states["mart.target"]
    node = result.table_state_graph["nodes_by_id"][final]
    assert node["producer_statement_id"] == "stmt:002"
    assert not node.get("known_dropped")
    # The dropped state carried no values, so the append inherits nothing from before it.
    sources = {
        source["source_kind"]
        for row in result.end_to_end_lineage
        if row["table"] == "mart.target"
        for source in row["value_sources"]
    }
    assert sources == {"physical_field"}


def test_drop_view_is_modeled_like_drop_table() -> None:
    result = parse_task_lineage(
        "DROP VIEW mart.target_view",
        task_name="drop_view",
        schema={"mart.target_view": ["id"]},
    )

    assert result.analysis_status["status"] == "complete"
    assert result.statements[0]["model_status"] == "modeled"
    assert result.statements[0]["stmt_kind"] == "DROP"
    final = result.final_table_states["mart.target_view"]
    assert result.table_state_graph["nodes_by_id"][final]["known_dropped"] is True


def test_the_statement_entry_carries_the_drop_kind_and_its_effect() -> None:
    result = parse_task_lineage(
        "DROP TABLE IF EXISTS mart.target",
        task_name="drop_only",
        schema=SCHEMA,
    )

    (statement,) = result.statements
    assert statement["stmt_kind"] == "DROP"
    assert statement["category"] == "relation_mutation"
    assert statement["model_status"] == "modeled"
    assert statement["target_table"] == "mart.target"
    assert statement["effect"]["rowset_effect"]["operation"] == "DROP_RELATION"


def test_a_modeled_drop_raises_no_unsupported_warning() -> None:
    result = parse_task_lineage(
        "DROP TABLE IF EXISTS mart.target;\n"
        "CREATE TABLE mart.target AS SELECT id, value FROM ods.source",
        task_name="drop_recreate",
        schema=SCHEMA,
    )

    assert "unsupported_statement" not in _warning_types(result)


def test_drop_database_is_still_an_unsupported_data_change() -> None:
    result = parse_task_lineage(
        "DROP DATABASE mart",
        task_name="drop_database",
        schema=SCHEMA,
    )

    assert result.analysis_status == {
        "status": "partial",
        "blocking_reasons": ["unsupported_data_change"],
    }
    assert result.statements[0]["model_status"] == "unsupported"
    assert _warning_types(result) == ["unsupported_statement"]


def test_drop_function_and_alter_stay_unsupported() -> None:
    for sql in ("DROP FUNCTION mart.udf_one", "ALTER TABLE mart.target ADD COLUMNS (x INT)"):
        result = parse_task_lineage(sql, task_name="still_unsupported", schema=SCHEMA)
        assert result.analysis_status["blocking_reasons"] == [
            "unsupported_data_change"
        ], sql
