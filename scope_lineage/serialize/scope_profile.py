"""LLM-oriented profile summaries derived from scope lineage results."""

from __future__ import annotations

from typing import Any

from ..scope.scope_types import NON_PHYSICAL_SOURCE_SCOPES, ScopeColumn, ScopeData, ScopeLineageResult, SourceRef


def build_scope_profile(result: ScopeLineageResult) -> dict[str, Any]:
    """Build a compact, human/LLM-readable summary of what each scope does.

    The profile is intentionally derived from the existing scope graph instead
    of becoming a second source of lineage truth.
    """
    all_steps = [
        _scope_step(result, scope_id, scope_data)
        for scope_id, scope_data in _ordered_scopes(result)
    ]
    steps = [step for step in all_steps if not _is_parser_only_pass_through_step(step)]
    return {
        "profile_step_count": len(steps),
        "steps": steps,
    }


def _is_parser_only_pass_through_step(step: dict[str, Any]) -> bool:
    if step["scope_id"] == "ROOT":
        return False
    if step["kind"] == "union_branch":
        return True
    return set(step["operations"]) <= {"pass_through", "rename"}


def _ordered_scopes(result: ScopeLineageResult) -> list[tuple[str, ScopeData]]:
    scope_ids = set(result.scopes)
    indegree = {scope_id: 0 for scope_id in scope_ids}
    downstream = {scope_id: [] for scope_id in scope_ids}

    for edge in result.scope_graph.edges:
        if edge.from_ not in scope_ids or edge.to not in scope_ids:
            continue
        downstream[edge.from_].append(edge.to)
        indegree[edge.to] += 1

    graph_order = [node for node in result.scope_graph.nodes if node in scope_ids]
    if not graph_order:
        graph_order = list(result.scopes.keys())

    queue = [scope_id for scope_id in graph_order if indegree[scope_id] == 0]
    ordered_ids: list[str] = []
    emitted: set[str] = set()

    while queue:
        scope_id = queue.pop(0)
        if scope_id in emitted:
            continue
        emitted.add(scope_id)
        ordered_ids.append(scope_id)

        for child in downstream[scope_id]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)

    for scope_id in graph_order:
        if scope_id not in emitted:
            ordered_ids.append(scope_id)
            emitted.add(scope_id)

    return [(scope_id, result.scopes[scope_id]) for scope_id in ordered_ids]


def _scope_step(
    result: ScopeLineageResult,
    scope_id: str,
    scope_data: ScopeData,
) -> dict[str, Any]:
    operations = _operations(scope_data)
    direct_tables = _direct_source_tables(scope_data)
    physical_tables = _physical_source_tables(result, scope_id)
    return {
        "scope_id": scope_id,
        "name": _display_name(scope_id, scope_data),
        "kind": scope_data.kind,
        "role": _profile_role(scope_data),
        "operations": operations,
        "business_summary": _business_summary(scope_data, operations, direct_tables, physical_tables),
        "direct_inputs": list(scope_data.depends_on),
        "direct_source_tables": direct_tables,
        "physical_source_tables": physical_tables,
        "output_columns": len(scope_data.columns),
        "logic": {
            "joins": [_join_summary(j) for j in scope_data.joins],
            "filters": _filter_expressions(scope_data),
            "aggregations": [_column_logic(c) for c in scope_data.columns if c.transform == "AGGREGATE"],
            "window_functions": [_column_logic(c) for c in scope_data.columns if c.transform == "WINDOW"],
            "case_when": [_column_logic(c) for c in scope_data.columns if c.transform == "CONDITIONAL"],
            "key_renames": _key_renames(scope_data),
            "distinct": bool(scope_data.distinct),
            "union_branches": len(scope_data.branches or []),
            "lateral_views": _json_safe(scope_data.lateral_views),
        },
    }


def _profile_role(scope_data: ScopeData) -> str:
    if scope_data.distinct and scope_data.role == "pass_through":
        return "dedup"
    return scope_data.role or _fallback_role(scope_data)


def _display_name(scope_id: str, scope_data: ScopeData) -> str:
    if scope_id == "ROOT":
        return "ROOT"
    if scope_data.alias_in_parent:
        return scope_data.alias_in_parent
    if ":" in scope_id:
        return scope_id.split(":", 1)[1]
    return scope_id


def _fallback_role(scope_data: ScopeData) -> str:
    if scope_data.kind in ("union", "union_branch"):
        return scope_data.kind
    if any(c.transform == "WINDOW" for c in scope_data.columns):
        return "dedup"
    if any(c.transform == "AGGREGATE" for c in scope_data.columns) or scope_data.group_by:
        return "aggregate"
    if scope_data.joins:
        return "join"
    if scope_data.filters:
        return "filter"
    if scope_data.distinct:
        return "dedup"
    if scope_data.columns and all(c.transform in ("DIRECT", "CONSTANT") for c in scope_data.columns):
        return "pass_through"
    return "transform"


def _operations(scope_data: ScopeData) -> list[str]:
    operations: list[str] = []
    if scope_data.kind in ("union", "union_branch") or scope_data.set_op:
        operations.append("union")
    if scope_data.distinct:
        operations.append("distinct")
    if scope_data.lateral_views:
        operations.append("lateral_view")
    if scope_data.joins:
        operations.append("join")
    if scope_data.filters or scope_data.having:
        operations.append("filter")
    if any(c.transform == "AGGREGATE" for c in scope_data.columns) or scope_data.group_by:
        operations.append("aggregate")
    if any(c.transform == "WINDOW" for c in scope_data.columns):
        operations.append("window")
    if any(c.transform == "CONDITIONAL" for c in scope_data.columns):
        operations.append("case_when")
    if _key_renames(scope_data):
        operations.append("rename")
    if any(c.transform == "EXPRESSION" for c in scope_data.columns):
        operations.append("expression")
    if not operations:
        operations.append("pass_through")
    return operations


def _business_summary(
    scope_data: ScopeData,
    operations: list[str],
    direct_tables: list[str],
    physical_tables: list[str],
) -> str:
    parts: list[str] = []
    if direct_tables:
        shown = "、".join(direct_tables[:3])
        suffix = f" 等 {len(direct_tables)} 张物理表" if len(direct_tables) > 3 else ""
        parts.append(f"读取 {shown}{suffix}")
    elif scope_data.depends_on:
        parts.append(f"基于 {'、'.join(scope_data.depends_on[:3])}")

    if "union" in operations:
        branch_count = len(scope_data.branches or [])
        if branch_count:
            parts.append(f"合并 {branch_count} 个分支")
        else:
            parts.append("合并多路数据")
    if "join" in operations:
        parts.append(f"关联 {len(scope_data.joins)} 个上游")
    if "filter" in operations:
        parts.append("按过滤条件保留记录")
    if "aggregate" in operations:
        parts.append("聚合生成指标")
    if "window" in operations:
        parts.append("使用窗口函数排序/去重/取值")
    if "case_when" in operations:
        parts.append("通过 CASE WHEN 派生字段")
    if "lateral_view" in operations:
        parts.append("展开数组或复杂类型")
    if "distinct" in operations:
        parts.append("去重")

    indirect_tables = [table for table in physical_tables if table not in set(direct_tables)]
    if indirect_tables:
        shown = "、".join(indirect_tables[:3])
        suffix = f" 等 {len(indirect_tables)} 张物理表" if len(indirect_tables) > 3 else ""
        parts.append(f"上游可追溯至 {shown}{suffix}")

    if not parts:
        parts.append("传递并整理上游字段")
    return "；".join(parts)


def _filter_expressions(scope_data: ScopeData) -> list[str]:
    return [f.expression for f in scope_data.filters] + [
        f"HAVING {h.expression}" for h in scope_data.having
    ]


def _join_summary(join: Any) -> dict[str, str]:
    summary = {
        "type": join.join_type,
        "right": join.right_scope,
    }
    if join.condition_expression:
        summary["on"] = join.condition_expression
    return summary


def _column_logic(column: ScopeColumn) -> dict[str, Any]:
    if column.transform == "CONDITIONAL":
        branch_count = len(column.case_branches or [])
        return {
            "column": column.name,
            "summary": f"CASE expression with {branch_count} branches",
            "branch_count": branch_count,
        }

    summary: dict[str, Any] = {
        "column": column.name,
        "expression": column.expression or column.agg_function or column.transform,
    }
    if column.agg_function:
        summary["function"] = column.agg_function
    if column.window:
        summary["window"] = _json_safe(column.window)
    if column.case_branches:
        summary["case_branches"] = _json_safe(column.case_branches)
    return summary


def _key_renames(scope_data: ScopeData) -> list[dict[str, str]]:
    renames: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for column in scope_data.columns:
        if column.transform != "DIRECT" or len(column.sources) != 1:
            continue
        source = column.sources[0]
        if source.column in ("*", column.name):
            continue
        key = (source.column, column.name)
        if key not in seen:
            renames.append({"from": source.column, "to": column.name})
            seen.add(key)
    return renames


def _physical_source_tables(result: ScopeLineageResult, scope_id: str) -> list[str]:
    tables = _collect_physical_sources(result, scope_id, set())
    non_physical = NON_PHYSICAL_SOURCE_SCOPES
    return sorted(t for t in tables if t not in non_physical)


def _direct_source_tables(scope_data: ScopeData) -> list[str]:
    non_physical = NON_PHYSICAL_SOURCE_SCOPES
    return sorted(
        dep
        for dep in scope_data.depends_on
        if dep not in non_physical and not dep.startswith(("cte:", "subq:", "union:")) and "." in dep
    )


def _collect_physical_sources(
    result: ScopeLineageResult,
    scope_id: str,
    visited: set[str],
) -> set[str]:
    if scope_id in visited:
        return set()
    if scope_id not in result.scopes:
        return {scope_id}

    visited.add(scope_id)
    tables: set[str] = set()
    for dep in result.scopes[scope_id].depends_on:
        tables.update(_collect_physical_sources(result, dep, visited))

    if not tables:
        for column in result.scopes[scope_id].columns:
            for source in column.sources:
                tables.update(_collect_source_physical(result, source, visited))

    return tables


def _collect_source_physical(
    result: ScopeLineageResult,
    source: SourceRef,
    visited: set[str],
) -> set[str]:
    if source.scope not in result.scopes:
        return {source.scope}
    return _collect_physical_sources(result, source.scope, visited)


def _json_safe(value: Any) -> Any:
    if isinstance(value, SourceRef):
        return {"scope": value.scope, "column": value.column}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value
