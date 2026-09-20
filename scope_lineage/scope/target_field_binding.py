"""Bind ROOT projections to authoritative INSERT target columns by position."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..metadata.target_table_metadata import (
    TargetTableMetadata,
    lookup_target_table_metadata,
)
from .scope_types import DiagnosticWarning, ScopeLineageResult


_DIRECTORY_TARGET_PREFIX = "directory:"

# The kinds whose write is positional, which is the only thing this pass can bind. CTAS and
# MERGE never get here (they publish `not_applicable` above); anything else arriving is a
# statement whose write semantics the contract does not model, and guessing a position for
# it would be worse than saying so.
_POSITIONAL_WRITE_KINDS = frozenset({"INSERT", "INSERT_OVERWRITE"})

# Why a statement has no binding to make. A closed set, published inside the block as
# `reason` -- "no binding" is then a stated fact rather than a missing key (Q4).
NOT_APPLICABLE_REASONS = (
    "ctas_defines_columns",
    "merge_target",
    "directory_target",
    "no_write_target",
)

# Why a binding that was attempted kept the SQL projection names instead. Published as
# `fallback_reason`; `other` is the honest overflow, and `issues[]` keeps the particulars
# (which column, which counts) in every case.
FALLBACK_REASONS = (
    "no_target_metadata",
    "projection_target_count_mismatch",
    "target_column_names_not_unique",
    "star_projection_unexpanded",
    "insert_column_list_unknown_column",
    "unsupported_statement_kind",
    "other",
)

# The token each issue shape derives, first match wins. Reading it off `issues[]` rather
# than recording it at the call site keeps one vocabulary: an issue nobody mapped becomes
# `other` instead of silently becoming nothing. `star_projection_unexpanded` is the one
# exception -- it is not a shape of its own, it is a count mismatch whose cause is upstream,
# so its call site passes it in.
_FALLBACK_REASON_BY_ISSUE = (
    ("target_metadata_invalid:", "no_target_metadata"),
    ("insert_column_list_unknown_column:", "insert_column_list_unknown_column"),
    ("unsupported_statement_kind:", "unsupported_statement_kind"),
    ("projection_target_count_mismatch:", "projection_target_count_mismatch"),
    ("target_column_names_not_unique", "target_column_names_not_unique"),
)


def _not_applicable_reason(result) -> str | None:
    """Why this statement has no target-column binding to make, or None if it has one.

    Computed here because this is the only place holding the statement kind and the target's
    name at once. The four are not failures and never were: a CTAS defines the columns it
    writes, a MERGE resolves its target columns outside this mechanism, a directory write has
    no table to bind to, and a statement with no write target has nothing to bind at all.

    The order is load-bearing, and each step is earlier than the test it would otherwise
    fail:

    * A path target is recognised before any statement kind, because it exits whatever kind
      it was written as.
    * CTAS and MERGE never reach the pass with metadata in hand -- `_build_ctas_scope` does
      not take it, and `_build_merge_scope` uses it only to expand a `*` branch -- so keying
      them on "no metadata" would report them as a metadata gap (TARGETBIND-001).

    Deliberately not distinguished: after the MERGE star fix, a MERGE whose caller supplied
    the DDL takes its column *names* from that DDL, in target order, while one without it
    falls back to the source's names. Both are `merge_target`. Splitting them needs to know
    whether the star expansion had a column list, and that fact was already dropped one frame
    upstream -- `_build_merge_scope` hands on the column list, not the metadata.
    """
    if not str(result.target_table or "").strip():
        return "no_write_target"
    if str(result.target_table).startswith(_DIRECTORY_TARGET_PREFIX):
        return "directory_target"
    if result.stmt_kind == "CTAS":
        return "ctas_defines_columns"
    if result.stmt_kind == "MERGE":
        return "merge_target"
    return None


def _absence_reason(result, *, target_metadata) -> str | None:
    """Why a binding that *should* have happened did not, or None when it did.

    Only the two metadata gaps remain here: the caller supplied no target metadata at all, or
    supplied a directory this target is missing from. Both mean an unbound projection that
    Spark will nonetheless write positionally, which is the one absence worth a reader's
    attention -- the kinds with no binding to make say so in the block itself.
    """
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
    not_applicable = _not_applicable_reason(result)
    if not_applicable is not None:
        result.target_binding_absence = None
        result.target_field_binding = {
            "status": "not_applicable",
            "reason": not_applicable,
        }
        return
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
    # about; otherwise a partial metadata directory demotes unrelated tasks.
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
    if result.stmt_kind not in _POSITIONAL_WRITE_KINDS:
        _record_fallback(
            result,
            metadata,
            [f"unsupported_statement_kind:{result.stmt_kind}"],
            projection_count=len(root.columns),
        )
        return

    method = (
        "insert_column_list"
        if explicit_target_columns
        else "schema_position"
        if metadata.structure_source == "schema"
        else "ddl_position"
    )
    target_columns = _bindable_target_columns(
        result, metadata, explicit_target_columns=explicit_target_columns
    )
    if target_columns is None:
        return
    if not _counts_and_names_agree(result, metadata, target_columns):
        return
    _record_applied(result, metadata, target_columns, method=method)


def _record_applied(
    result: ScopeLineageResult,
    metadata: TargetTableMetadata,
    target_columns: list[tuple[str, int]],
    *,
    method: str,
) -> None:
    """Write the authoritative names onto the ROOT projection and publish the record."""
    metadata_table = metadata.table_name
    source_file = metadata.source_file
    corrected_count = 0
    for column, (target_name, target_ordinal) in zip(
        result.scopes["ROOT"].columns, target_columns
    ):
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
        "projection_count": len(result.scopes["ROOT"].columns),
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


def _bindable_target_columns(
    result: ScopeLineageResult,
    metadata: TargetTableMetadata,
    *,
    explicit_target_columns: list[str] | None,
) -> list[tuple[str, int]] | None:
    """The authoritative columns to bind against, or None having recorded the fallback."""
    root = result.scopes["ROOT"]
    if explicit_target_columns:
        unknown = _columns_the_metadata_lacks(explicit_target_columns, metadata)
        if unknown:
            # Binding to a list the target does not declare would claim an authority this
            # metadata does not have: either the DDL is stale or the statement names a column
            # that is not there, and neither is decided here.
            _record_fallback(
                result,
                metadata,
                [f"insert_column_list_unknown_column:{name}" for name in unknown],
                projection_count=len(root.columns),
            )
            return None
        return _explicit_target_columns(explicit_target_columns, metadata)
    if not metadata.usable:
        _record_fallback(
            result,
            metadata,
            [f"target_metadata_invalid:{issue}" for issue in metadata.validation_issues],
            projection_count=len(root.columns),
        )
        return None
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
        return None
    static_partitions = {
        name for name, value in result.target_partition_spec.items() if value is not None
    }
    return [
        (column.name, column.ordinal)
        for column in metadata.columns
        if column.name not in static_partitions
    ]


def _counts_and_names_agree(
    result: ScopeLineageResult,
    metadata: TargetTableMetadata,
    target_columns: list[tuple[str, int]],
) -> bool:
    """Whether the projection can be zipped onto the target, recording why it cannot."""
    root = result.scopes["ROOT"]
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
            # Arithmetically the same mismatch, a different thing to go and fix: the gap is
            # the source schema nobody supplied, not the target DDL.
            reason=(
                "star_projection_unexpanded" if _has_unexpanded_star(root) else None
            ),
        )
        return False
    target_names = [name for name, _ordinal in target_columns]
    if len(target_names) != len(set(target_names)):
        _record_fallback(
            result,
            metadata,
            ["target_column_names_not_unique"],
            projection_count=len(root.columns),
            target_column_count=len(target_columns),
        )
        return False
    return True


def _columns_the_metadata_lacks(
    columns: list[str],
    metadata: TargetTableMetadata,
) -> list[str]:
    """INSERT-column-list names the target metadata does not declare, in written order.

    Metadata that could not be parsed declares nothing, so it cannot contradict anything
    either: an unusable entry keeps the established behaviour of binding to the list as
    written rather than reporting every column of it as unknown.
    """
    if not metadata.usable:
        return []
    declared = {column.name for column in metadata.columns}
    declared.update(metadata.partition_columns)
    return [name for name in columns if name not in declared]


def _has_unexpanded_star(root) -> bool:
    """Whether the ROOT projection still carries a `*` nobody could expand."""
    return any(
        column.name == "*" or str(column.name).endswith(".*") for column in root.columns
    )


def _fallback_reason(issues: Sequence[str]) -> str:
    """The one token that names why the binding fell back, derived from its own issues."""
    for issue in issues:
        for prefix, token in _FALLBACK_REASON_BY_ISSUE:
            if issue.startswith(prefix):
                return token
    return "other"


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
    reason: str | None = None,
) -> None:
    result.target_field_binding = {
        "status": "fallback",
        "method": "sql_projection",
        # One token from a closed set, beside the issues rather than instead of them: a run
        # summary can count it, and a reader gets "why" without parsing free text (Q4).
        "fallback_reason": reason or _fallback_reason(issues),
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
