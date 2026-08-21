"""INSERT OVERWRITE DIRECTORY writes a path, and target_table says so.

The write is modelled like any other -- sources, scopes and end-to-end rows are
produced normally -- but the destination is a filesystem path, not a table. It is
reported as ``directory:<path>`` so a consumer registering warehouse tables can tell
the two apart from the field itself, without a second lookup.

No diagnostic is emitted: the lineage is complete and the target is self-describing.
Warning here would be the same mistake target_field_binding avoids when a table has no
DDL -- turning a correct, fully-traced result yellow.
"""
from __future__ import annotations

from scope_lineage.scope.end_to_end import build_end_to_end_lineage
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {"db.src": ["id", "amount"]}


def test_directory_target_is_reported_with_its_prefix():
    result = parse_scope_lineage(
        "INSERT OVERWRITE DIRECTORY '/warehouse/export/daily' "
        "SELECT id, amount FROM db.src",
        task_name="t",
        schema=SCHEMA,
    )
    assert result.target_table == "directory:/warehouse/export/daily"
    assert result.stmt_kind == "INSERT_OVERWRITE"


def test_directory_write_still_produces_lineage():
    result = parse_scope_lineage(
        "INSERT OVERWRITE DIRECTORY '/warehouse/export/daily' "
        "SELECT id, amount FROM db.src",
        task_name="t",
        schema=SCHEMA,
    )
    assert result.source_tables == ["db.src"]
    rows = build_end_to_end_lineage(result)
    assert [row["column"] for row in rows] == ["id", "amount"]
    assert all(row["trace_complete"] for row in rows), rows


def test_directory_write_emits_no_diagnostic_of_its_own():
    result = parse_scope_lineage(
        "INSERT OVERWRITE DIRECTORY '/warehouse/export/daily' "
        "SELECT id, amount FROM db.src",
        task_name="t",
        schema=SCHEMA,
    )
    assert result.diagnostics.lineage_fact_gaps == []
    assert [w.type for w in result.diagnostics.warnings] == []
