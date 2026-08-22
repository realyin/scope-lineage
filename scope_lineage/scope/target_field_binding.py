"""Bind ROOT projections to authoritative INSERT target columns by position."""

from __future__ import annotations

from collections.abc import Mapping

from ..metadata.target_table_metadata import (
    TargetTableMetadata,
    lookup_target_table_metadata,
)
from .scope_types import DiagnosticWarning, ScopeLineageResult


_DIRECTORY_TARGET_PREFIX = "directory:"


def _absence_reason(result, *, target_metadata) -> str | None:
    """Why this statement will have no target_field_binding, or None if it will have one.

    Computed here because this is the only place holding all four facts at once: the
    statement kind, the target's name, whatever metadata the caller supplied, and the
    lookup result. The task document used to re-derive it at its own call site from
    `metadata_requested` alone, which is why it reported every CTAS, MERGE and path write
    as `target_table_not_found` -- the one value that means the binding *should* have
    happened (TARGETBIND-001).

    The order is load-bearing, and each step is earlier than the test it would otherwise
    fail:

    * A path target exits at a different early return depending on whether metadata was
      supplied, so it has to be recognised before either of them.
    * CTAS and MERGE never reach the pass with metadata in hand -- `_build_ctas_scope`
      does not take it, and `_build_merge_scope` uses it only to expand a `*` branch --
      so keying them on "no metadata" would label all of them `metadata_not_provided`.

    Deliberately not distinguished: after the MERGE star fix, a MERGE whose caller
    supplied the DDL takes its column *names* from that DDL, in target order, while one
    without it falls back to the source's names. Both land on
    `binding_not_applicable_for_statement`. Splitting them needs to know whether the star
    expansion had a column list, and that fact was already dropped one frame upstream --
    `_build_merge_scope` hands on the column list, not the metadata.
    """
    if str(result.target_table or "").startswith(_DIRECTORY_TARGET_PREFIX):
        return "target_is_not_a_table"
    if result.stmt_kind == "CTAS":
        return "statement_defines_its_own_columns"
    if result.stmt_kind == "MERGE":
        return "binding_not_applicable_for_statement"
    if target_metadata is None:
        return "metadata_not_provided"
    if lookup_target_table_metadata(target_metadata, result.target_table) is None:
        return "target_table_not_found"
    return None


def apply_target_field_binding(
    result: ScopeLineageResult,
    *,
    target_metadata: Mapping[str, TargetTableMetadata] | None,
    explicit_target_columns: list[str] | None = None,
    insert_by_name: bool = False,
) -> None:
    """Apply optional target names after star expansion and before ROOT de-duplication."""
    result.target_binding_absence = _absence_reason(
        result, target_metadata=target_metadata
    )
    if target_metadata is None:
        return
    root = result.scopes.get("ROOT")
    if root is None:
        return

    metadata = lookup_target_table_metadata(target_metadata, result.target_table)
    # A directory is commonly a partial, table-by-table enrichment set. Absence means the
    # caller supplied no target DDL for THIS table, so preserve the exact no-metadata
    # behaviour. Only metadata that exists but cannot be applied is a fallback worth warning
    # about; otherwise a 17-table bundle turns hundreds of unrelated tasks YELLOW.
    if metadata is None:
        return
    if insert_by_name:
        _record_noop(
            result,
            metadata,
            status="not_applied",
            issues=["insert_by_name_uses_projection_names"],
        )
        return

    method = (
        "insert_column_list"
        if explicit_target_columns
        else "schema_position"
        if metadata.structure_source == "schema"
        else "ddl_position"
    )
    target_columns: list[tuple[str, int]]
    if explicit_target_columns:
        target_columns = _explicit_target_columns(
            explicit_target_columns,
            metadata,
        )
    else:
        if not metadata.usable:
            _record_fallback(
                result,
                metadata,
                [f"target_metadata_invalid:{issue}" for issue in metadata.validation_issues],
                projection_count=len(root.columns),
            )
            return
        static_partitions = {
            name
            for name, value in result.target_partition_spec.items()
            if value is not None
        }
        undeclared_partitions = [
            name
            for name in result.target_partition_columns
            if name not in metadata.partition_columns
        ]
        if undeclared_partitions:
            _record_fallback(
                result,
                metadata,
                [
                    f"insert_partition_not_in_target_metadata:{name}"
                    for name in undeclared_partitions
                ],
                projection_count=len(root.columns),
            )
            return
        target_columns = [
            (column.name, column.ordinal)
            for column in metadata.columns
            if column.name not in static_partitions
        ]

    if len(root.columns) != len(target_columns):
        _record_fallback(
            result,
            metadata,
            [
                "projection_target_count_mismatch:"
                f"{len(root.columns)}!={len(target_columns)}"
            ],
            projection_count=len(root.columns),
            target_column_count=len(target_columns),
        )
        return
    target_names = [name for name, _ordinal in target_columns]
    if len(target_names) != len(set(target_names)):
        _record_fallback(
            result,
            metadata,
            ["target_column_names_not_unique"],
            projection_count=len(root.columns),
            target_column_count=len(target_columns),
        )
        return

    metadata_table = metadata.table_name if metadata is not None else result.target_table
    source_file = metadata.source_file if metadata is not None else None
    corrected_count = 0
    for column, (target_name, target_ordinal) in zip(root.columns, target_columns):
        parsed_name = column.name
        corrected = parsed_name != target_name
        corrected_count += int(corrected)
        column.name = target_name
        column.parsed_name = parsed_name
        column.target_column_ordinal = target_ordinal
        column.target_field_resolution = method
        column.target_field_corrected = corrected
        column.target_metadata_table = metadata_table

    result.target_field_binding = {
        "status": "applied",
        "method": method,
        "metadata_table": metadata_table,
        **({"metadata_source_file": source_file} if source_file else {}),
        "projection_count": len(root.columns),
        "target_column_count": len(target_columns),
        "corrected_column_count": corrected_count,
        "static_partition_columns": [
            name
            for name, value in result.target_partition_spec.items()
            if value is not None
        ],
        "dynamic_partition_columns": [
            name
            for name, value in result.target_partition_spec.items()
            if value is None
        ],
        "issues": [],
    }


def _explicit_target_columns(
    columns: list[str],
    metadata: TargetTableMetadata | None,
) -> list[tuple[str, int]]:
    metadata_ordinals = {
        column.name: column.ordinal
        for column in metadata.columns
    } if metadata is not None else {}
    return [
        (name, metadata_ordinals.get(name, index))
        for index, name in enumerate(columns)
    ]


def _record_noop(
    result: ScopeLineageResult,
    metadata: TargetTableMetadata | None,
    *,
    status: str,
    issues: list[str],
) -> None:
    root = result.scopes.get("ROOT")
    result.target_field_binding = {
        "status": status,
        "method": "sql_projection",
        **(
            {
                "metadata_table": metadata.table_name,
                "metadata_source_file": metadata.source_file,
            }
            if metadata is not None
            else {}
        ),
        "projection_count": len(root.columns) if root else 0,
        "target_column_count": 0,
        "corrected_column_count": 0,
        "static_partition_columns": [],
        "dynamic_partition_columns": [],
        "issues": issues,
    }


def _record_fallback(
    result: ScopeLineageResult,
    metadata: TargetTableMetadata | None,
    issues: list[str],
    *,
    projection_count: int,
    target_column_count: int = 0,
) -> None:
    result.target_field_binding = {
        "status": "fallback",
        "method": "sql_projection",
        **(
            {
                "metadata_table": metadata.table_name,
                "metadata_source_file": metadata.source_file,
            }
            if metadata is not None
            else {}
        ),
        "projection_count": projection_count,
        "target_column_count": target_column_count,
        "corrected_column_count": 0,
        "static_partition_columns": [
            name
            for name, value in result.target_partition_spec.items()
            if value is not None
        ],
        "dynamic_partition_columns": [
            name
            for name, value in result.target_partition_spec.items()
            if value is None
        ],
        "issues": issues,
    }
    result.diagnostics.warnings.append(
        DiagnosticWarning(
            type="target_field_binding_fallback",
            scope="ROOT",
            msg=(
                "Optional target DDL/Schema metadata was not applied; kept SQL projection names. "
                f"Reasons: {', '.join(issues)}"
            ),
        )
    )
