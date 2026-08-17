"""A table a script creates is knowable to the statements that follow it.

Each write statement is modelled independently, so a table built by statement N was
invisible to statement N+1: its columns could not expand, and it turned up in
``metadata_coverage.missing_tables`` as a table nobody can ever supply — it does not
exist outside the script. The statement that produced it already proves its columns.
"""

from __future__ import annotations

from scope_lineage.scope.scope_builder import parse_all_scope_lineage
from scope_lineage.scope.task_lineage import parse_task_lineage


SCHEMA = {
    "ods.source": ["id", "code"],
    "mart.target": ["id", "code"],
}

SCRIPT = """
CREATE TABLE staging_tmp AS SELECT id, code FROM ods.source;
MERGE INTO mart.target target
USING (SELECT id, code FROM staging_tmp) source
ON target.id = source.id
WHEN MATCHED THEN UPDATE SET target.code = source.code
"""


def test_v1_resolves_a_later_statement_against_a_script_created_table() -> None:
    results = parse_all_scope_lineage(SCRIPT, "script_local_table", schema=SCHEMA)

    assert [result.stmt_kind for result in results] == ["CTAS", "MERGE"]
    merge = results[1]
    assert merge.parse_status == "ok"
    assert [column.name for column in merge.scopes["subq:source"].columns] == [
        "id",
        "code",
    ]
    assert merge.diagnostics.lineage_fact_gaps == []


def test_v2_does_not_report_a_script_created_table_as_missing_metadata() -> None:
    result = parse_task_lineage(SCRIPT, task_name="script_local_table", schema=SCHEMA)

    assert [item["model_status"] for item in result.statements] == [
        "modeled",
        "modeled",
    ]
    assert result.analysis_status == {"status": "complete", "blocking_reasons": []}
    assert result.diagnostics["lineage_fact_gaps"] == []

    coverage = result.diagnostics["metadata_coverage"]
    assert "staging_tmp" not in coverage["missing_tables"]

    # The script-local table is the statement's real input, so it is named as one. What
    # links it back to ods.source is the table-state graph, not a collapsed source list.
    assert result.statements[1]["effect"]["rowset_effect"]["membership_sources"] == [
        {"table": "mart.target", "column": "id"},
        {"table": "staging_tmp", "column": "id"},
    ]
    assert [
        (node["table"], node["producer_statement_id"], node["columns_known"])
        for node in result.table_state_graph["nodes"]
        if node["table"] == "staging_tmp"
    ] == [("staging_tmp", "stmt:001", True)]


def test_supplied_metadata_wins_over_a_script_local_definition() -> None:
    """A script-local CREATE must not redefine a real warehouse table.

    Same name, different columns: trusting the script would silently replace the
    authoritative schema with whatever this one job happened to build.
    """
    results = parse_all_scope_lineage(
        """
        CREATE TABLE mart.target AS SELECT id FROM ods.source;
        INSERT INTO mart.audit SELECT id, code FROM mart.target
        """,
        "script_shadows_real_table",
        schema={**SCHEMA, "mart.audit": ["id", "code"]},
    )

    insert = results[1]
    assert [
        (source.scope, source.column)
        for column in insert.scopes["ROOT"].columns
        for source in column.sources
    ] == [("mart.target", "id"), ("mart.target", "code")]


def test_the_most_recent_definition_of_a_script_local_table_wins() -> None:
    results = parse_all_scope_lineage(
        """
        CREATE TABLE staging_tmp AS SELECT id FROM ods.source;
        CREATE TABLE staging_tmp AS SELECT id, code FROM ods.source;
        INSERT INTO mart.target SELECT * FROM staging_tmp
        """,
        "script_local_table_redefined",
        schema=SCHEMA,
    )

    assert [column.name for column in results[2].scopes["ROOT"].columns] == [
        "id",
        "code",
    ]
