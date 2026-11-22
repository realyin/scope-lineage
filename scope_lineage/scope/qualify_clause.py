"""AST facts about a QUALIFY clause (D5: QUALIFY is supported natively, not rewritten).

QUALIFY filters the rows a SELECT returns after its window functions are computed. The
windows it tests are usually written inside the clause itself
(``QUALIFY ROW_NUMBER() OVER (PARTITION BY k ORDER BY t DESC) = 1``); one written on an
output alias (``QUALIFY rn = 1``) arrives here in the same form, because ``qualify``
expands the alias into the window expression. Both are read from the AST, never the text.
"""
from __future__ import annotations

from sqlglot import exp

# The window functions that number rows within a partition (the role inferrer's list).
_RANKING_FUNCTIONS = (exp.RowNumber, exp.Rank, exp.DenseRank, exp.Ntile)


def qualify_condition(select: exp.Expression) -> exp.Expression | None:
    """The boolean expression of a SELECT's QUALIFY clause, or None."""
    if not isinstance(select, exp.Select):
        return None
    clause = select.args.get("qualify")
    if clause is None:
        return None
    return clause.this if isinstance(clause, exp.Qualify) else clause


def own_windows(node: exp.Expression) -> list[exp.Window]:
    """The window functions ``node`` computes itself, not those of a nested subquery."""
    owner = node if isinstance(node, exp.Select) else node.find_ancestor(exp.Select)
    return [
        window
        for window in node.find_all(exp.Window)
        if window.find_ancestor(exp.Select) is owner
    ]


def pinned_rank(predicate: exp.Expression) -> int | None:
    """``N`` when ``predicate`` is ``<ranking window> (= | <= | <) N`` (either side)."""
    if not isinstance(predicate, (exp.EQ, exp.LTE, exp.LT, exp.GTE, exp.GT)):
        return None
    left, right = predicate.this, predicate.expression
    if _is_ranking_window(left) and isinstance(predicate, (exp.EQ, exp.LTE, exp.LT)):
        return _integer(right)
    if _is_ranking_window(right) and isinstance(predicate, (exp.EQ, exp.GTE, exp.GT)):
        return _integer(left)
    return None


def _is_ranking_window(node: exp.Expression) -> bool:
    return isinstance(node, exp.Window) and isinstance(node.this, _RANKING_FUNCTIONS)


def _integer(node: exp.Expression) -> int | None:
    if isinstance(node, exp.Literal) and not node.is_string and str(node.this).isdigit():
        return int(str(node.this))
    return None
