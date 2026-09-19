"""Rules-based scope role inference.

Priority (first match wins):
  dedup        — a RANKING window whose rank column a predicate pins to a small
                 constant (the ROW_NUMBER-then-`rn = 1` pattern)
  window       — any other window scope (running aggregate, LAG/LEAD, an unfiltered
                 ranking); it adds a column and keeps every row
  aggregate    — scope has AGGREGATE column or group_by entries
  join         — scope has JOIN entries
  filter       — scope has filters, no aggregates, no joins
  label        — scope has only CONSTANT columns (pure lookup/flag)
  pass_through — all columns DIRECT, no joins/filters
  transform    — catch-all for mixed expression scopes

`window` exists because the previous rule labelled EVERY window-bearing scope `dedup`:
a CTE that only computes `SUM(total) OVER (PARTITION BY band)` was published as a
deduplicating stage, which is the one thing it does not do. The pin may be written in
this scope, or in a scope that reads it -- `WHERE s.rn = 1` and
`LEFT JOIN d ON x.k = d.k AND d.rn = 1` are the same pattern.

The pin test reads the predicate's text rather than re-parsing it, so it does not see
boolean structure: a rank pinned inside an `OR` counts as a pin. Rank columns are not
written into disjunctions in practice, and re-parsing every predicate here would make
this module a second expression analyzer.
"""
from __future__ import annotations

import re
from typing import Iterator

from .scope_types import ScopeLineageResult, ScopeData


# The window functions that number rows within a partition. `PERCENT_RANK` /
# `CUME_DIST` are deliberately absent: they return a fraction, so `= 1` on one of them
# selects the LAST row of each partition rather than deduplicating it.
_RANKING_WINDOW_FUNCTIONS = ("row_number", "rank", "dense_rank", "ntile")

# The largest constant a rank may be pinned to and still read as record selection.
# `rn <= 3` is "keep the top 3 per key"; `rn <= 5000` is a guard rail on a runaway
# partition and leaves the scope's grain unchanged.
_MAX_PINNED_RANK = 10

_RANKING_CALL_PATTERN = re.compile(
    r"\b(?:" + "|".join(_RANKING_WINDOW_FUNCTIONS) + r")\s*\(", re.IGNORECASE
)


def infer_roles(result: ScopeLineageResult) -> None:
    """Set ScopeData.role for every scope in result.scopes (in-place)."""
    for scope_id, scope_data in result.scopes.items():
        scope_data.role = _infer_role(result, scope_id, scope_data)


def _infer_role(
    result: ScopeLineageResult, scope_id: str, scope_data: "ScopeData"
) -> str:
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
        return "dedup" if _is_dedup_window(result, scope_id, scope_data) else "window"
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


def _is_dedup_window(
    result: ScopeLineageResult, scope_id: str, scope_data: "ScopeData"
) -> bool:
    """A ranking window this scope, or a scope reading it, pins to a small constant."""
    ranked = _ranking_window_columns(scope_data)
    if not ranked:
        return False
    if any(_pins_a_rank(expression, ranked) for expression, _ in _predicates(scope_data)):
        return True
    for reader in _readers(result, scope_id):
        for expression, refs in _predicates(reader):
            visible = {
                ref.column.lower() for ref in refs if ref.scope == scope_id
            } & ranked
            if visible and _pins_a_rank(expression, visible):
                return True
    return False


def _ranking_window_columns(scope_data: "ScopeData") -> set[str]:
    """The output columns this scope computes with a ranking window function."""
    return {
        column.name.lower()
        for column in scope_data.columns
        if column.transform == "WINDOW"
        and _RANKING_CALL_PATTERN.search(column.expression or "")
    }


def _readers(result: ScopeLineageResult, scope_id: str) -> Iterator["ScopeData"]:
    """The scopes that read ``scope_id`` directly."""
    for other in result.scopes.values():
        if scope_id in (other.depends_on or []):
            yield other


def _predicates(scope_data: "ScopeData") -> Iterator[tuple[str, list]]:
    """Every predicate a scope writes: WHERE, HAVING, and each JOIN's ON clause."""
    for item in [*scope_data.filters, *scope_data.having]:
        yield item.expression or "", item.columns
    for join in scope_data.joins:
        yield join.condition_expression or "", join.condition_columns


def _pins_a_rank(expression: str, names: set[str]) -> bool:
    for name in names:
        for match in _pin_pattern(name).finditer(expression or ""):
            if int(match.group("rank")) <= _MAX_PINNED_RANK:
                return True
    return False


def _pin_pattern(name: str) -> re.Pattern:
    """``[qualifier.]<name> (= | <= | <) <integer>``, backticks optional."""
    return re.compile(
        r"(?<![A-Za-z0-9_$])"
        r"(?:(?:`[^`]+`|[A-Za-z_][A-Za-z0-9_$]*)\s*\.\s*)?"
        r"`?" + re.escape(name) + r"`?\s*(?:<=|<|=)\s*"
        r"(?P<rank>[0-9]+)(?![0-9.])",
        re.IGNORECASE,
    )
