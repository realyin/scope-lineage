"""Rules-based scope role inference.

Priority (first match wins):
  dedup        — scope has WINDOW column (row_number/rank pattern)
  aggregate    — scope has AGGREGATE column or group_by entries
  join         — scope has JOIN entries
  filter       — scope has filters, no aggregates, no joins
  label        — scope has only CONSTANT columns (pure lookup/flag)
  pass_through — all columns DIRECT, no joins/filters
  transform    — catch-all for mixed expression scopes
"""
from __future__ import annotations

from .scope_types import ScopeLineageResult, ScopeData


def infer_roles(result: ScopeLineageResult) -> None:
    """Set ScopeData.role for every scope in result.scopes (in-place)."""
    for scope_id, scope_data in result.scopes.items():
        scope_data.role = _infer_role(scope_data)


def _infer_role(scope_data: "ScopeData") -> str:
    # Union container scopes have no columns of their own — role comes from kind
    if scope_data.kind in ("union", "union_branch"):
        return scope_data.kind  # "union" or "union_branch"

    has_window = any(c.transform == "WINDOW" for c in scope_data.columns)
    has_aggregate = any(c.transform == "AGGREGATE" for c in scope_data.columns)
    has_join = len(scope_data.joins) > 0
    has_filter = len(scope_data.filters) > 0
    has_group_by = len(scope_data.group_by) > 0
    cols = scope_data.columns
    all_direct = all(c.transform in ("DIRECT", "CONSTANT") for c in cols) if cols else False
    all_constant = all(c.transform == "CONSTANT" for c in cols) if cols else False

    if has_window:
        return "dedup"
    if has_aggregate or has_group_by:
        return "aggregate"
    if has_join:
        return "join"
    if has_filter:
        return "filter"
    if all_constant:
        return "label"
    if all_direct and not has_join and not has_filter:
        return "pass_through"
    return "transform"
