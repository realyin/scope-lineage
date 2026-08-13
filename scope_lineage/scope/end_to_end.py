"""End-to-end physical lineage summaries for ROOT columns."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from .scope_types import (
    AMBIGUOUS_SCOPE_ID,
    CONSTANT_SCOPE_ID,
    SYSTEM_SCOPE_ID,
    ScopeColumn,
    ScopeLineageResult,
    ScopeOutputField,
)


_TRANSFORM_PRIORITY: dict[str, int] = {
    "CONSTANT": 0,
    "DIRECT": 1,
    "EXPAND_ALL": 2,
    "UNION": 3,
    "EXPRESSION": 4,
    "CONDITIONAL": 5,
    "WINDOW": 6,
    "AGGREGATE": 7,
}


@dataclass
class _TraceResult:
    sources: list[tuple[str, str, str]] = field(default_factory=list)
    incomplete_reasons: list[str] = field(default_factory=list)
    ambiguities: list[dict[str, Any]] = field(default_factory=list)


def build_end_to_end_lineage(result: ScopeLineageResult) -> list[dict[str, Any]]:
    """Return ROOT columns with physical source columns traced through scopes."""
    root = result.scopes.get("ROOT")
    if root is None:
        return []

    items = []
    for output_ordinal, column in enumerate(root.columns):
        output = (
            root.outputs[output_ordinal]
            if output_ordinal < len(root.outputs)
            else None
        )
        trace = _lineage_for_column(
            result,
            "ROOT",
            column.name,
            column.transform,
            column_override=column,
            output_override=output,
        )
        item = {
            "column": column.name,
            "transform": column.transform,
            "expression": column.expression,
            "trace_complete": not trace["trace_incomplete_reasons"],
            "physical_sources": trace["physical_sources"],
            "generated_sources": trace["generated_sources"],
            "source_kind": trace["source_kind"],
            "output_ordinal": output_ordinal,
        }
        if column.merge_branch is not None:
            item["merge_branch"] = column.merge_branch
        if column.merge_when_index is not None:
            item["merge_when_index"] = column.merge_when_index
        if column.parsed_name is not None:
            item["parsed_column"] = column.parsed_name
        if column.target_column_ordinal is not None:
            item["target_column_ordinal"] = column.target_column_ordinal
        if column.target_field_resolution is not None:
            item["target_field_resolution"] = column.target_field_resolution
        if column.target_field_corrected is not None:
            item["target_field_corrected"] = column.target_field_corrected
        if column.target_metadata_table is not None:
            item["target_metadata_table"] = column.target_metadata_table
        if trace.get("rowset_sources"):
            item["rowset_sources"] = trace["rowset_sources"]
        if trace["trace_incomplete_reasons"]:
            item["trace_incomplete_reasons"] = trace["trace_incomplete_reasons"]
        if trace.get("ambiguities"):
            item["ambiguities"] = trace["ambiguities"]
        items.append(item)
    return items


def _lineage_for_column(
    result: ScopeLineageResult,
    scope_id: str,
    column_name: str,
    transform: str,
    *,
    column_override: ScopeColumn | None = None,
    output_override: ScopeOutputField | None = None,
) -> dict[str, Any]:
    found = _trace_column(
        result,
        scope_id,
        column_name,
        "DIRECT",
        set(),
        column_override=column_override,
        output_override=output_override,
    )
    physical_sources, generated_sources = _source_dicts(found.sources)
    traced_lineage = {
        "physical_sources": physical_sources,
        "generated_sources": generated_sources,
        "rowset_sources": [],
        "source_kind": _source_kind(physical_sources, generated_sources),
        "trace_incomplete_reasons": _unique_reasons(found.incomplete_reasons),
        "ambiguities": _unique_ambiguities(found.ambiguities),
    }
    if not traced_lineage["trace_incomplete_reasons"]:
        scope = result.scopes.get(scope_id)
        column = column_override or (
            _find_column(scope.columns, column_name) if scope else None
        )
        output = output_override or (
            _find_output(scope.outputs, column_name) if scope else None
        )
        if column is not None and _has_internal_struct_member_access(result, column):
            expression_transform = _dominant_physical_transform(
                physical_sources, transform
            )
            expression_lineage = _lineage_from_output_expression_resolution(
                output, expression_transform
            )
            if (
                expression_lineage is not None
                and _physical_source_key_set(expression_lineage["physical_sources"])
                < _physical_source_key_set(physical_sources)
            ):
                return expression_lineage
        return traced_lineage
    if traced_lineage["ambiguities"]:
        # Expression resolution contains only proven physical facts; it cannot replace the
        # ambiguity evidence collected from SourceRef candidates.
        return traced_lineage

    scope = result.scopes.get(scope_id)
    output = output_override or (
        _find_output(scope.outputs, column_name) if scope else None
    )
    if transform != "EXPAND_ALL" and not _is_star_column_name(column_name):
        expression_lineage = _lineage_from_output_expression_resolution(output, transform)
        if expression_lineage is not None:
            return expression_lineage
    return traced_lineage


def _lineage_from_output_expression_resolution(
    output: ScopeOutputField | None,
    transform: str,
) -> dict[str, Any] | None:
    if output is None:
        return None
    resolution = output.expression_resolution or {}
    if resolution.get("status") != "resolved":
        return None
    if resolution.get("missing_reasons"):
        return None

    physical_sources = _physical_sources_from_expression_resolution(resolution, transform)
    generated_sources = [
        dict(item)
        for item in resolution.get("generated_sources") or []
        if isinstance(item, dict)
    ]
    rowset_sources = [
        dict(item)
        for item in resolution.get("rowset_sources") or []
        if isinstance(item, dict)
    ]
    source_kind = str(
        resolution.get("source_kind")
        or _source_kind(physical_sources, generated_sources, rowset_sources)
    )
    if source_kind == "rowset" and not rowset_sources:
        rowset_sources = [
            {
                "source_type": "rowset",
                "scope": "ROOT",
                "field": output.name,
                "expression": str(output.expanded_expression or output.expression or ""),
            }
        ]
    if source_kind not in {"physical", "generated", "mixed", "rowset"}:
        return None
    if not physical_sources and not generated_sources and not rowset_sources:
        return None
    return {
        "physical_sources": physical_sources,
        "generated_sources": generated_sources,
        "rowset_sources": rowset_sources,
        "source_kind": source_kind,
        "trace_incomplete_reasons": [],
    }


def _physical_sources_from_expression_resolution(
    resolution: dict[str, Any],
    transform: str,
) -> list[dict[str, str]]:
    physical_sources: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in resolution.get("physical_source_fields") or []:
        if not isinstance(item, dict):
            continue
        table = str(item.get("table") or "")
        column = str(item.get("field") or item.get("column") or "")
        if not table or not column:
            continue
        key = (table, column, transform)
        if key in seen:
            continue
        seen.add(key)
        physical_sources.append({"table": table, "column": column, "transform": transform})
    return physical_sources


def _has_internal_struct_member_access(
    result: ScopeLineageResult,
    column: ScopeColumn,
) -> bool:
    expression = column.expression or ""
    for source in column.sources:
        if source.scope not in result.scopes or not source.column:
            continue
        field = re.escape(source.column)
        if re.search(rf"`[^`]+`\.`{field}`\.`[^`]+`", expression):
            return True
        if re.search(
            rf"(?<![.`\w])[A-Za-z_][A-Za-z0-9_]*\.{field}\."
            rf"[A-Za-z_][A-Za-z0-9_]*(?![`.\w])",
            expression,
        ):
            return True
    return False


def _physical_source_key_set(
    sources: list[dict[str, str]],
) -> set[tuple[str, str]]:
    return {
        (str(item.get("table") or ""), str(item.get("column") or ""))
        for item in sources
        if item.get("table") and item.get("column")
    }


def _dominant_physical_transform(
    sources: list[dict[str, str]],
    fallback: str,
) -> str:
    dominant = fallback
    for item in sources:
        dominant = _dominant_transform(dominant, str(item.get("transform") or ""))
    return dominant


def _trace_column(
    result: ScopeLineageResult,
    scope_id: str,
    column_name: str,
    incoming_transform: str,
    visited: set[tuple[str, str]],
    *,
    column_override: ScopeColumn | None = None,
    output_override: ScopeOutputField | None = None,
) -> _TraceResult:
    key = (scope_id, column_name)
    if key in visited:
        return _TraceResult(incomplete_reasons=["cycle_detected"])
    if scope_id not in result.scopes:
        reasons = _terminal_incomplete_reasons(scope_id, column_name, incoming_transform)
        return _TraceResult(
            sources=[(scope_id, column_name, incoming_transform)],
            incomplete_reasons=reasons,
        )

    visited = visited | {key}
    scope = result.scopes[scope_id]
    column = column_override or _find_column(scope.columns, column_name)
    if column is None:
        return _TraceResult(incomplete_reasons=["missing_scope_column"])
    output = output_override or _find_output(scope.outputs, column_name)

    dominant = _dominant_transform(incoming_transform, column.transform)
    if not column.sources:
        return _TraceResult(incomplete_reasons=_output_terminal_incomplete_reasons(output))

    traced = _TraceResult(incomplete_reasons=_column_incomplete_reasons(column))
    for source in column.sources:
        if source.scope == AMBIGUOUS_SCOPE_ID and source.candidates:
            traced.ambiguities.append(
                _trace_ambiguity(
                    result,
                    scope_id,
                    source.column or column_name,
                    source.candidates,
                    dominant,
                    visited,
                )
            )
            traced.incomplete_reasons.append("ambiguous_unqualified")
            continue
        if (
            source.column == "*"
            and source.scope in result.scopes
            and dominant in {"AGGREGATE", "WINDOW"}
        ):
            source_trace = _trace_scope_rowset(result, source.scope, dominant, visited)
        else:
            source_column = _source_column_for_trace(result, source.scope, source.column, column_name)
            source_trace = _trace_column(
                result, source.scope, source_column, dominant, visited
            )
        traced.sources.extend(source_trace.sources)
        traced.incomplete_reasons.extend(source_trace.incomplete_reasons)
        traced.ambiguities.extend(source_trace.ambiguities)
    if not traced.sources:
        traced.incomplete_reasons.extend(_output_terminal_incomplete_reasons(output))
    return traced


def _trace_ambiguity(
    result: ScopeLineageResult,
    scope_id: str,
    column_name: str,
    candidates: list[dict],
    transform: str,
    visited: set[tuple[str, str]],
) -> dict[str, Any]:
    traced_candidates: list[dict[str, Any]] = []
    for candidate in sorted(
        (
            item
            for item in candidates
            if isinstance(item, dict) and item.get("scope") and item.get("column")
        ),
        key=lambda item: (
            str(item["scope"]),
            str(item["column"]),
            str(item.get("binding_scope_id") or ""),
            str(item.get("input_ref_id") or ""),
            str(item.get("qualifier") or ""),
        ),
    ):
        candidate_scope = str(candidate["scope"])
        candidate_column = str(candidate["column"])
        candidate_trace = _trace_column(
            result,
            candidate_scope,
            candidate_column,
            transform,
            set(visited),
        )
        physical_sources, generated_sources = _source_dicts(candidate_trace.sources)
        reasons = _unique_reasons(candidate_trace.incomplete_reasons)
        item = {
            "scope": candidate_scope,
            "column": candidate_column,
            **(
                {"qualifier": candidate["qualifier"]}
                if candidate.get("qualifier")
                else {}
            ),
            **(
                {"binding_scope_id": candidate["binding_scope_id"]}
                if candidate.get("binding_scope_id")
                else {}
            ),
            **(
                {"input_ref_id": candidate["input_ref_id"]}
                if candidate.get("input_ref_id")
                else {}
            ),
            "trace_complete": not reasons and not candidate_trace.ambiguities,
            "physical_sources": physical_sources,
            "generated_sources": generated_sources,
            "trace_incomplete_reasons": reasons,
        }
        nested = _unique_ambiguities(candidate_trace.ambiguities)
        if nested:
            item["ambiguities"] = nested
        traced_candidates.append(item)
    return {
        "scope": scope_id,
        "column": column_name,
        "candidate_count": len(traced_candidates),
        "candidates": traced_candidates,
    }


def _trace_scope_rowset(
    result: ScopeLineageResult,
    scope_id: str,
    transform: str,
    visited: set[tuple[str, str]],
) -> _TraceResult:
    key = (scope_id, "*")
    if key in visited:
        return _TraceResult(incomplete_reasons=["cycle_detected"])
    if scope_id not in result.scopes:
        return _TraceResult(
            sources=[(scope_id, "*", transform)],
            incomplete_reasons=_terminal_incomplete_reasons(scope_id, "*", transform),
        )

    scope = result.scopes[scope_id]
    visited = visited | {key}
    traced = _TraceResult()
    input_ids = [edge.source_id for edge in scope.input_edges if edge.source_id]
    if not input_ids:
        input_ids = list(scope.depends_on)
    for input_id in input_ids:
        if input_id in result.scopes:
            source_trace = _trace_scope_rowset(result, input_id, transform, visited)
        else:
            source_trace = _TraceResult(
                sources=[(input_id, "*", transform)],
                incomplete_reasons=_terminal_incomplete_reasons(input_id, "*", transform),
            )
        traced.sources.extend(source_trace.sources)
        traced.incomplete_reasons.extend(source_trace.incomplete_reasons)
    return traced


def _source_column_for_trace(
    result: ScopeLineageResult,
    source_scope: str,
    source_column: str,
    current_column: str,
) -> str:
    if source_column != "*":
        return source_column
    if source_scope in result.scopes:
        return current_column
    return "*"


def _column_incomplete_reasons(column: ScopeColumn) -> list[str]:
    if column.transform == "EXPAND_ALL" or _is_star_column_name(column.name):
        return ["star_not_expanded"]
    return []


def _terminal_incomplete_reasons(scope_id: str, column_name: str, transform: str) -> list[str]:
    reasons: list[str] = []
    if scope_id == "UNKNOWN":
        reasons.append("unknown_source")
    if scope_id == AMBIGUOUS_SCOPE_ID:
        # Reachable, but not uniquely determined. `trace_complete` has to mean both, or a
        # consumer reading only that flag cannot tell a proven source from a coin flip
        # (LINEAGE-002). The candidates travel on the SourceRef.
        reasons.append("ambiguous_unqualified")
    if _is_star_column_name(column_name) and transform not in {"AGGREGATE", "WINDOW"}:
        reasons.append("star_not_expanded")
    return reasons


def _output_terminal_incomplete_reasons(output: ScopeOutputField | None) -> list[str]:
    if output is None or output.transform in {"CONSTANT"}:
        return []
    resolution = output.expression_resolution or {}
    status = resolution.get("status")
    if status not in {"partially_resolved", "unresolved"}:
        return []
    reasons = [
        str(reason)
        for reason in resolution.get("missing_reasons") or []
        if reason
    ]
    return reasons or ["output_expression_unresolved"]


def _source_kind(
    physical_sources: list[dict[str, str]],
    generated_sources: list[dict[str, str]],
    rowset_sources: list[dict[str, str]] | None = None,
) -> str:
    kinds = sum(
        bool(items)
        for items in (
            physical_sources,
            generated_sources,
            rowset_sources or [],
        )
    )
    if kinds > 1:
        return "mixed"
    if physical_sources:
        return "physical"
    if generated_sources:
        return "generated"
    if rowset_sources:
        return "rowset"
    return "unresolved"


def _source_dicts(
    sources: list[tuple[str, str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    physical: dict[tuple[str, str, str], dict[str, str]] = {}
    generated: dict[tuple[str, str, str], dict[str, str]] = {}
    for table, column, transform in sources:
        if table in {CONSTANT_SCOPE_ID, SYSTEM_SCOPE_ID}:
            generated[(table, column, transform)] = {
                "source_type": table,
                "value": column,
                "transform": table,
            }
        elif table not in {"UNKNOWN", AMBIGUOUS_SCOPE_ID}:
            physical[(table, column, transform)] = {
                "table": table,
                "column": column,
                "transform": transform,
            }
    return list(physical.values()), list(generated.values())


def _is_star_column_name(column_name: str) -> bool:
    return column_name == "*" or column_name.endswith(".*")


def _unique_reasons(reasons: list[str]) -> list[str]:
    seen = set()
    unique = []
    for reason in reasons:
        if reason in seen:
            continue
        seen.add(reason)
        unique.append(reason)
    return unique


def _unique_ambiguities(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in items:
        candidates = item.get("candidates") or []
        key = (
            str(item.get("scope") or ""),
            str(item.get("column") or ""),
            tuple(
                (
                    str(candidate.get("scope") or ""),
                    str(candidate.get("column") or ""),
                    str(candidate.get("binding_scope_id") or ""),
                    str(candidate.get("input_ref_id") or ""),
                    str(candidate.get("qualifier") or ""),
                )
                for candidate in candidates
                if isinstance(candidate, dict)
            ),
        )
        unique[key] = item
    return [unique[key] for key in sorted(unique)]


def _find_column(columns: list[ScopeColumn], column_name: str) -> ScopeColumn | None:
    wildcard = None
    for column in columns:
        if column.name == column_name:
            return column
        if column.name == "*":
            wildcard = column
    return wildcard


def _find_output(outputs: list[ScopeOutputField], column_name: str) -> ScopeOutputField | None:
    wildcard = None
    for output in outputs:
        if output.name == column_name:
            return output
        if output.name == "*":
            wildcard = output
    return wildcard


def _dominant_transform(left: str, right: str) -> str:
    if _TRANSFORM_PRIORITY.get(left, 0) >= _TRANSFORM_PRIORITY.get(right, 0):
        return left
    return right
