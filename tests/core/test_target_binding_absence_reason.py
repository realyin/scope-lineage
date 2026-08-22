"""Why a statement has no target_field_binding, said once for both contract versions.

Four unrelated situations produce no binding: a CTAS or MERGE, which define their own
columns; a write to a filesystem path, which has no table to bind to; and an INSERT whose
target is simply absent from the DDL the caller supplied. Only the last is a risk -- Spark
writes an INSERT positionally, so an unbound projection can land in the wrong columns --
and the artifact said nothing that told the four apart.

The task document was worse than silent: it derived the reason at its own call site from
`metadata_requested`, so it labelled all four `target_table_not_found`, the harmful one.
The classification now happens once, where the statement kind, the target name, the
supplied metadata and the lookup result are all in scope, and both writers read it.
"""
from __future__ import annotations

from scope_lineage.metadata.target_table_metadata import (
    TargetColumnMetadata, TargetMetadataMap, TargetTableMetadata,
)
from scope_lineage.scope.scope_builder import parse_all_scope_lineage
from scope_lineage.scope.task_lineage import parse_task_lineage

SCHEMA = {"ods.a": ["id", "amt"], "mart.t": ["id", "amt"]}


def _metadata(table="mart.t") -> TargetMetadataMap:
    metadata = TargetMetadataMap()
    metadata[table] = TargetTableMetadata(
        table_name=table.split(".")[-1], full_table_name=table,
        columns=[TargetColumnMetadata(name=n, data_type="string", ordinal=i,
                                      is_partition=False, comment="")
                 for i, n in enumerate(["id", "amt"])],
        partition_columns=[], ddl="", source_file="x", validation_issues=[],
        query_time=None, ddl_update_time=None, data_source="test",
        structure_source="ddl",
    )
    return metadata


def _reason(sql: str, target_metadata=None) -> str | None:
    result = parse_all_scope_lineage(
        sql, task_name="t", schema=SCHEMA, target_metadata=target_metadata,
    )[0]
    return result.target_binding_absence


def _v2_reason_code(sql: str, target_metadata=None) -> str | None:
    task = parse_task_lineage(
        sql, task_name="t", schema=SCHEMA, target_metadata=target_metadata,
    )
    for statement in task.statements or []:
        binding = statement.get("target_field_binding") or {}
        if binding.get("status") == "absent":
            return binding.get("reason_code")
    return None


CTAS = "CREATE TABLE mart.new AS SELECT id, amt FROM ods.a"
MERGE = "MERGE INTO mart.t USING ods.a s ON mart.t.id = s.id WHEN NOT MATCHED THEN INSERT *"
DIRECTORY = "INSERT OVERWRITE DIRECTORY '/w/out' SELECT id FROM ods.a"
INSERT_MISSING = "INSERT INTO mart.absent SELECT id, amt FROM ods.a"


# --- drivers: must fail before the fix -------------------------------------------
#
# 1 and 2 are also the biting guards: with a metadata directory supplied they satisfy
# the literal condition of the "no metadata" step -- inside the binding pass
# target_metadata is always None for these kinds -- yet must not get its value.

def test_a_ctas_defines_its_own_columns_even_with_metadata_supplied():
    assert _reason(CTAS, _metadata()) == "statement_defines_its_own_columns"
    assert _v2_reason_code(CTAS, _metadata()) == "statement_defines_its_own_columns"


def test_a_merge_is_not_applicable_even_with_metadata_supplied():
    assert _reason(MERGE, _metadata()) == "binding_not_applicable_for_statement"
    assert _v2_reason_code(MERGE, _metadata()) == "binding_not_applicable_for_statement"


def test_a_path_target_is_not_a_table():
    assert _reason(DIRECTORY, _metadata()) == "target_is_not_a_table"


def test_a_table_absent_from_the_supplied_ddl_is_the_harmful_one():
    assert _reason(INSERT_MISSING, _metadata()) == "target_table_not_found"


def test_no_metadata_at_all_is_reported_as_such():
    assert _reason(INSERT_MISSING) == "metadata_not_provided"


# --- guards: must pass before AND after -------------------------------------------

def test_a_bound_statement_carries_no_reason():
    result = parse_all_scope_lineage(
        "INSERT INTO mart.t SELECT id, amt FROM ods.a",
        task_name="t", schema=SCHEMA, target_metadata=_metadata(),
    )[0]
    assert result.target_field_binding
    assert result.target_binding_absence is None


def test_the_v2_shape_is_unchanged_for_a_bound_statement():
    task = parse_task_lineage(
        "INSERT INTO mart.t SELECT id, amt FROM ods.a",
        task_name="t", schema=SCHEMA, target_metadata=_metadata(),
    )
    binding = (task.statements or [])[0].get("target_field_binding") or {}
    assert binding.get("status") == "applied"


def test_the_v1_document_carries_the_reason():
    from scope_lineage.contract.lineage import to_lineage_dict

    document = to_lineage_dict(
        parse_all_scope_lineage(CTAS, task_name="t", schema=SCHEMA,
                                target_metadata=_metadata())[0]
    )
    assert document["target_binding_absent_reason"] == "statement_defines_its_own_columns"
    assert "target_field_binding" not in document


def test_a_bound_statement_carries_no_reason_in_the_document():
    from scope_lineage.contract.lineage import to_lineage_dict

    document = to_lineage_dict(
        parse_all_scope_lineage("INSERT INTO mart.t SELECT id, amt FROM ods.a",
                                task_name="t", schema=SCHEMA,
                                target_metadata=_metadata())[0]
    )
    assert "target_binding_absent_reason" not in document
    assert document["target_field_binding"]["status"] == "applied"
