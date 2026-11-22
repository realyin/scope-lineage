"""Which inputs of a synthetic set-operation scope supply values, and which only filter rows.

UNION merges every branch's values. EXCEPT and INTERSECT output the left input's rows that
are absent from / present in the other inputs: only the left input supplies values; the
others are row-membership inputs (audit 1.1). One leaf module so the resolver, the fact
gaps and any later consumer read the same rule.
"""
from __future__ import annotations

from .scope_types import ScopeData

ROW_FILTERING_SET_OPS = frozenset({"EXCEPT", "INTERSECT"})


def value_branch_ids(scope_data: ScopeData) -> list[str]:
    """The branches whose columns are the set operation's output values."""
    branches = list(scope_data.branches or [])
    if scope_data.set_op in ROW_FILTERING_SET_OPS:
        return branches[:1]
    return branches


def row_membership_branch_ids(scope_data: ScopeData) -> list[str]:
    """The branches that decide which value rows survive but supply no values."""
    if scope_data.set_op not in ROW_FILTERING_SET_OPS:
        return []
    return list(scope_data.branches or [])[1:]
