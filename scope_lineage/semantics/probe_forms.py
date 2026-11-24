"""What a probe query's expressions compute, read from its qualified syntax tree.

``semantic probes check`` (:mod:`.probes`) holds a query whose result may land in an
observation slot to fixed output columns (C9), and a fixed name proves nothing by
itself: ``COUNT(DISTINCT k) AS rows`` must fail. So each output expression is classified
by its form, never by its name:

- ``rows`` -- ``COUNT(*)`` / ``COUNT(1)`` over the rows of one table (a derived table
  that only filters or projects them counts as those rows), or ``SUM(n)`` over a
  subquery grouped by the keys where ``n`` is that subquery's ``COUNT(*)``;
- ``keys`` -- ``COUNT(DISTINCT k, ...)`` over the rows of one table, or ``COUNT(*)``
  over a subquery grouped by ``k, ...`` (one row per key);
- ``duplicate_keys`` -- over a subquery grouped by the keys with ``n = COUNT(*)``:
  ``SUM(CASE WHEN n > 1 THEN 1 ELSE 0 END)``, ``SUM(IF(n > 1, 1, 0))``,
  ``COUNT(CASE WHEN n > 1 THEN 1 END)``, ``COUNT_IF(n > 1)``,
  ``COUNT(*) FILTER (WHERE n > 1)`` (``n >= 2``, ``1 < n`` and ``2 <= n`` read the same);
  or ``COUNT(*)`` over a subquery grouped by the keys ``HAVING COUNT(*) > 1``.

A column of a one-row derived table (``SELECT a.rows ... FROM (SELECT COUNT(*) AS rows
...) a CROSS JOIN (...) b``) and a scalar subquery are read through to the expression
that computes them. ``COUNT(*) - COUNT(DISTINCT k)`` counts surplus rows, not keys with
more than one row, and is no form of ``duplicate_keys``. The filters of the parts are not
compared: that the three counts read the same partitions is the query writer's to keep.

The tree must have been through sqlglot's ``qualify``, so every column names its source.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlglot import exp
from sqlglot.optimizer.scope import Scope

from .names import bare_table


@dataclass(frozen=True)
class Form:
    """What one expression counts: ``kind`` over ``table``, by ``keys`` (column names)."""

    kind: str
    table: str
    keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Rows:
    table: str


@dataclass(frozen=True)
class _Grouped:
    table: str
    keys: tuple[str, ...]
    having_duplicates: bool
    scope: Scope


def projection(select: exp.Expression, name: str) -> exp.Expression | None:
    """The projection of ``select`` whose output name is ``name``, without its alias."""
    if not isinstance(select, exp.Select):
        return None
    for item in select.expressions:
        if item.alias_or_name.lower() == name.lower():
            return item.unalias()
    return None


def output_names(select: exp.Select) -> list[str]:
    return [item.alias_or_name.lower() for item in select.expressions]


def base_column(column: exp.Column, scope: Scope) -> tuple[str, str] | None:
    """``(db.table, column)`` a column reads, through derived tables that pass it on."""
    source = scope.sources.get(column.table)
    if isinstance(source, exp.Table):
        return table_name(source), column.name.lower()
    if isinstance(source, Scope):
        inner = projection(source.expression, column.name)
        if isinstance(inner, exp.Column):
            return base_column(inner, source)
    return None


def table_name(table: exp.Table) -> str:
    return bare_table(".".join(part for part in (table.db, table.name) if part))


def single_row(scope: Scope) -> bool:
    """Whether the select of ``scope`` returns one row whatever the data."""
    select = scope.expression
    if not isinstance(select, exp.Select):
        return False
    if select.args.get("group") or select.args.get("distinct"):
        return False
    if not scope.sources:
        return True
    if any(_aggregate(item.unalias()) for item in select.expressions):
        return True
    return all(isinstance(source, Scope) and single_row(source)
               for source in scope.sources.values())


def _aggregate(node: exp.Expression) -> bool:
    """An aggregate function in ``node`` outside any window and any subquery."""
    for found in node.find_all(exp.AggFunc):
        parent = found.parent
        inside = False
        while parent is not None and parent is not node.parent:
            if isinstance(parent, (exp.Window, exp.Subquery, exp.Select)):
                inside = True
                break
            parent = parent.parent
        if not inside:
            return True
    return False


def classify(node: exp.Expression, scope: Scope) -> Form | None:
    """The form of one output expression of ``scope``'s select, or None for any other."""
    if isinstance(node, exp.Paren):
        return classify(node.this, scope)
    if isinstance(node, exp.Column):
        source = scope.sources.get(node.table)
        if isinstance(source, Scope) and single_row(source):
            inner = projection(source.expression, node.name)
            return classify(inner, source) if inner is not None else None
        return None
    if isinstance(node, exp.Subquery):
        inner_scope = _subquery_scope(scope, node)
        if inner_scope is None or not isinstance(inner_scope.expression, exp.Select):
            return None
        items = inner_scope.expression.expressions
        if len(items) != 1 or not single_row(inner_scope):
            return None
        return classify(items[0].unalias(), inner_scope)
    relation = _relation(scope)
    if relation is None:
        return None
    if isinstance(node, exp.Count):
        return _count(node, relation, scope)
    if isinstance(node, exp.Filter) and isinstance(node.this, exp.Count):
        where = node.expression
        condition = where.this if isinstance(where, exp.Where) else where
        if _counts_rows(node.this) and _duplicates(condition, relation, scope):
            return Form("duplicate_keys", relation.table, relation.keys)
        return None
    if isinstance(node, exp.CountIf):
        if _duplicates(node.this, relation, scope):
            return Form("duplicate_keys", relation.table, relation.keys)
        return None
    if isinstance(node, exp.Sum):
        return _sum(node.this, relation, scope)
    return None


def _count(node: exp.Count, relation, scope: Scope) -> Form | None:
    argument = node.this
    if _counts_rows(node):
        if isinstance(relation, _Rows):
            return Form("rows", relation.table)
        kind = "duplicate_keys" if relation.having_duplicates else "keys"
        return Form(kind, relation.table, relation.keys)
    if isinstance(argument, exp.Distinct) and isinstance(relation, _Rows):
        keys = []
        for column in argument.expressions:
            if not isinstance(column, exp.Column):
                return None
            base = base_column(column, scope)
            if base is None or base[0] != relation.table:
                return None
            keys.append(base[1])
        return Form("keys", relation.table, tuple(sorted(keys)))
    if isinstance(argument, (exp.Case, exp.If)) and _one_when(argument, relation, scope, None):
        return Form("duplicate_keys", relation.table, relation.keys)
    return None


def _sum(argument, relation, scope: Scope) -> Form | None:
    if not isinstance(relation, _Grouped) or relation.having_duplicates:
        return None
    if isinstance(argument, exp.Column):
        source = scope.sources.get(argument.table)
        if source is relation.scope and _counts_rows(projection(source.expression, argument.name)):
            return Form("rows", relation.table)
        return None
    if isinstance(argument, (exp.Case, exp.If)) and _one_when(argument, relation, scope, 0):
        return Form("duplicate_keys", relation.table, relation.keys)
    return None


def _one_when(node, relation, scope: Scope, otherwise) -> bool:
    """``CASE WHEN <n > 1> THEN 1 [ELSE otherwise] END`` or ``IF(<n > 1>, 1, otherwise)``."""
    if not isinstance(relation, _Grouped) or relation.having_duplicates:
        return False
    if isinstance(node, exp.If):
        condition, then, default = node.this, node.args.get("true"), node.args.get("false")
    else:
        ifs = node.args.get("ifs") or []
        if len(ifs) != 1 or node.this is not None:
            return False
        condition, then = ifs[0].this, ifs[0].args.get("true")
        default = node.args.get("default")
    if not _literal(then, 1):
        return False
    if otherwise is None:
        if default is not None and not isinstance(default, exp.Null):
            return False
    elif not _literal(default, otherwise):
        return False
    return _duplicates(condition, relation, scope)


def _duplicates(condition, relation, scope: Scope) -> bool:
    """``n > 1`` (or ``n >= 2``, ``1 < n``, ``2 <= n``) on the grouped subquery's count."""
    if not isinstance(relation, _Grouped) or relation.having_duplicates:
        return False
    count = _more_than_one(condition)
    if not isinstance(count, exp.Column):
        return False
    source = scope.sources.get(count.table)
    return source is relation.scope and _counts_rows(projection(source.expression, count.name))


def _more_than_one(condition) -> exp.Expression | None:
    """The side of ``condition`` that must be over 1, or None when it says anything else."""
    if isinstance(condition, exp.Paren):
        return _more_than_one(condition.this)
    if isinstance(condition, exp.GT) and _literal(condition.expression, 1):
        return condition.this
    if isinstance(condition, exp.GTE) and _literal(condition.expression, 2):
        return condition.this
    if isinstance(condition, exp.LT) and _literal(condition.this, 1):
        return condition.expression
    if isinstance(condition, exp.LTE) and _literal(condition.this, 2):
        return condition.expression
    return None


def _counts_rows(node) -> bool:
    """``COUNT(*)`` or ``COUNT(<a non-null literal>)``."""
    if not isinstance(node, exp.Count):
        return False
    argument = node.this
    return isinstance(argument, exp.Star) or (
        isinstance(argument, exp.Literal) and not isinstance(argument, exp.Null))


def _literal(node, value: int) -> bool:
    return isinstance(node, exp.Literal) and not node.is_string and node.this == str(value)


def _relation(scope: Scope):
    """What the select of ``scope`` reads: the rows of one table, or one row per key of a
    subquery grouped over them; None for a join or anything else."""
    if len(scope.sources) != 1 or not isinstance(scope.expression, exp.Select):
        return None
    if scope.expression.args.get("joins"):
        return None
    (source,) = scope.sources.values()
    if isinstance(source, exp.Table):
        return _Rows(table_name(source))
    if not isinstance(source, Scope) or not isinstance(source.expression, exp.Select):
        return None
    select = source.expression
    inner = _relation(source)
    if not isinstance(inner, _Rows):
        return None
    group = select.args.get("group")
    if group is None:
        plain = not select.args.get("distinct") and not any(
            _aggregate(item.unalias()) for item in select.expressions)
        return inner if plain else None
    keys = []
    for key in group.expressions:
        base = base_column(key, source) if isinstance(key, exp.Column) else None
        if base is None or base[0] != inner.table:
            return None
        keys.append(base[1])
    having = select.args.get("having")
    if having is not None:
        condition = having.this if isinstance(having, exp.Having) else having
        if not _counts_rows(_more_than_one(condition)):
            return None
    return _Grouped(inner.table, tuple(sorted(keys)), having is not None, source)


def _subquery_scope(scope: Scope, node: exp.Subquery) -> Scope | None:
    for inner in scope.subquery_scopes:
        if inner.expression is node.this:
            return inner
    return None
