"""The grouping keys of a GROUP BY clause, wherever sqlglot put them (audit 1.5).

``GROUP BY a, b`` keeps its items in ``group.expressions``. ``CUBE(a, b)``, ``ROLLUP(a, b)``
and ``GROUPING SETS ((a, b), (a))`` keep theirs in ``args["cube" | "rollup" |
"grouping_sets"]``, and ``GROUP BY a, b WITH CUBE`` keeps them in ``expressions`` beside an
empty ``Cube`` marker. Every reader of the grouping keys goes through here so none of them
sees only the plain part.
"""
from __future__ import annotations

from sqlglot import exp

GROUPING_PLAIN = "plain"
_ROLLED_UP_ARGS = ("grouping_sets", "cube", "rollup")


def group_by_item_expressions(group: exp.Expression) -> list[exp.Expression]:
    """Every distinct grouping key of ``group`` in clause order: plain items, then the
    columns named inside CUBE / ROLLUP / GROUPING SETS."""
    items: list[exp.Expression] = list(
        group.expressions if hasattr(group, "expressions") else [group]
    )
    for arg in _ROLLED_UP_ARGS:
        for node in group.args.get(arg) or []:
            items.extend(_rolled_up_items(node))
    seen: set[str] = set()
    unique: list[exp.Expression] = []
    for item in items:
        key = item.sql()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _rolled_up_items(node: exp.Expression) -> list[exp.Expression]:
    """The key expressions inside one CUBE / ROLLUP / GROUPING SETS node."""
    found: list[exp.Expression] = []
    for item in node.expressions if hasattr(node, "expressions") else []:
        if isinstance(item, (exp.Tuple, exp.Cube, exp.Rollup, exp.GroupingSets)):
            found.extend(_rolled_up_items(item))
        elif isinstance(item, exp.Paren):
            found.append(item.this)
        else:
            found.append(item)
    return found


def grouping_kind(group: exp.Expression | None) -> str | None:
    """``plain``, ``cube``, ``rollup``, ``grouping_sets``, ``with_cube`` or ``with_rollup``
    for a GROUP BY clause (None without one); ``mixed`` when several rolled-up forms meet.

    A non-plain grouping adds subtotal rows whose rolled-up keys are NULL, so its keys are
    not proven unique (see the profile's key confidence).
    """
    if group is None:
        return None
    kinds: list[str] = []
    for kind in _ROLLED_UP_ARGS:
        nodes = group.args.get(kind) or []
        if not nodes:
            continue
        if kind in ("cube", "rollup") and all(not node.expressions for node in nodes):
            kinds.append(f"with_{kind}")
        else:
            kinds.append(kind)
    if not kinds:
        return GROUPING_PLAIN
    return kinds[0] if len(kinds) == 1 else "mixed"
