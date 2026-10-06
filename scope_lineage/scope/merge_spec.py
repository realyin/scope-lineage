"""A MERGE statement's ON and WHEN conditions, as the contract's ``merge_spec``.

The ON condition decides which source row meets which target row, and each WHEN clause's
own condition decides whether a met (or unmet) row is updated, inserted, deleted or left
alone. Neither is an output column, so the column lineage never carried them: task
modelling flattened both into one column list (no target/source pairing, no ON/WHEN
attribution, no literals), and a reader had to go back to the SQL to learn what a MERGE
is keyed on (D #22).

Everything here is read off the statement's own tree, which already holds the facts:
``merge.args["on"]`` and each ``when.args["condition"]``. The SQL texts are rendered the
way every other contract expression is, so they carry the author's comments exactly as
far as ``--strip-comments`` / comment redaction let them.
"""

from __future__ import annotations

from typing import Iterable

from sqlglot import exp

from ._constants import DIALECT
from .scope_resolver import _is_merge_delete_then


def build_merge_spec(
    merge_node: exp.Merge,
    *,
    target_qualifiers: Iterable[str],
    using_alias: str,
) -> dict:
    """``{on, key_pairs, other_on_conditions, whens}`` for one MERGE statement.

    ``key_pairs`` holds only top-level AND conjuncts of ON that equate one target column
    with one source column, each oriented target-then-source whichever side the author
    wrote first. Every other conjunct -- a literal pin, a function of a key, an unqualified
    column whose side the SQL does not state -- stays in ``other_on_conditions`` verbatim:
    deciding what it means is the reader's call, not something to guess here.
    """
    targets = {str(name).lower() for name in target_qualifiers if name}
    source = (using_alias or "").lower()
    on = merge_node.args.get("on")
    key_pairs: list[dict] = []
    other_on_conditions: list[str] = []
    for conjunct in _conjuncts(on):
        pair = _key_pair(conjunct, targets, source)
        if pair is None:
            other_on_conditions.append(conjunct.sql(dialect=DIALECT))
        else:
            key_pairs.append(pair)
    return {
        "on": on.sql(dialect=DIALECT) if on is not None else None,
        "key_pairs": key_pairs,
        "other_on_conditions": other_on_conditions,
        "whens": [_when_spec(index, when) for index, when in enumerate(_when_items(merge_node))],
    }


def _conjuncts(node: exp.Expression | None) -> list[exp.Expression]:
    if node is None:
        return []
    while isinstance(node, exp.Paren):
        node = node.this
    if isinstance(node, exp.And):
        return [*_conjuncts(node.left), *_conjuncts(node.right)]
    return [node]


def _bare_column(node: exp.Expression | None) -> exp.Column | None:
    while isinstance(node, exp.Paren):
        node = node.this
    return node if isinstance(node, exp.Column) else None


def _key_pair(conjunct: exp.Expression, targets: set[str], source: str) -> dict | None:
    if not isinstance(conjunct, exp.EQ):
        return None
    left, right = _bare_column(conjunct.left), _bare_column(conjunct.right)
    if left is None or right is None:
        return None
    sides = (left.table.lower(), right.table.lower())
    if sides[0] in targets and sides[1] == source:
        return {"target": left.name, "source": right.name}
    if sides[1] in targets and sides[0] == source:
        return {"target": right.name, "source": left.name}
    return None


def _when_items(merge_node: exp.Merge) -> list[exp.Expression]:
    whens = merge_node.args.get("whens")
    if whens is None:
        return []
    return list(whens.expressions) if hasattr(whens, "expressions") else [whens]


def _when_spec(index: int, when: exp.Expression) -> dict:
    matched = bool(when.args.get("matched"))
    by_source = not matched and bool(when.args.get("source"))
    clause = "matched" if matched else (
        "not_matched_by_source" if by_source else "not_matched"
    )
    condition = when.args.get("condition")
    then = when.args.get("then")
    if isinstance(then, exp.Update):
        action, star = "update", any(isinstance(item, exp.Star) for item in then.expressions)
    elif isinstance(then, exp.Insert):
        action, star = "insert", isinstance(then.this, exp.Star)
    elif _is_merge_delete_then(then):
        action, star = "delete", False
    else:
        # Not a shape Spark's grammar has; say so instead of naming an action.
        action, star = None, False
    return {
        "index": index,
        "clause": clause,
        "condition": condition.sql(dialect=DIALECT) if condition is not None else None,
        "action": action,
        "star": star,
    }
