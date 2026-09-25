"""One comparison space for a quoted rule, a lineage filter and the task SQL (check 5).

A document's ``rules[].sql`` quotes the task script as written; the lineage renders every
predicate through SQLGlot, so ``nvl(x, 0)`` comes back as ``COALESCE(x, 0)``,
``substr`` as ``SUBSTRING``, ``x is not null`` as ``NOT x IS NULL`` -- and a column that a
derived table computes can come back as the expression behind it
(``DATE_FORMAT(time_inst, 'yyyyMMdd')`` for a subquery's ``dt``). A loose text match
cannot relate the two, so check 5 compares *forms*:

- a fragment's forms are its loose text (:func:`normalize_sql`) and, when SQLGlot parses
  it, the text SQLGlot renders for it in the lineage's dialect;
- the task SQL's forms are its loose text, its rendered text, and one *unit* per WHERE,
  HAVING and ON predicate and per conjunct of each: the unit rendered as written and with
  every column a derived table or CTE computes replaced by the expression behind it.

A rule's SQL is found in the task SQL when any of its forms occurs in the script (loose or
rendered) or equals a unit; a lineage filter is cited when one of its forms meets a form
of a quoted rule -- the rule's own, or those of the units it equals.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from .names import normalize_sql, strip_leading_keyword

# The dialect the lineage parses and renders every task in (scope_lineage.scope.parser).
DIALECT = "spark"
_PARSE_ERRORS = (SqlglotError, ValueError, RecursionError)
_JOIN_HOST = "SELECT 1 FROM __fragment "
_RESOLVE_DEPTH = 4


@dataclass(frozen=True)
class TaskSql:
    raw: str
    rendered: str
    units: tuple[frozenset, ...]

    def contains(self, forms: frozenset) -> bool:
        """Whether a quoted fragment is in the scripts, loosely, rendered, or as a unit."""
        if any(form in self.raw or form in self.rendered for form in forms):
            return True
        return any(forms & unit for unit in self.units)

    def expand(self, forms: frozenset) -> frozenset:
        """A quoted fragment's forms plus those of every unit it equals."""
        return forms.union(*(unit for unit in self.units if forms & unit))


def overlaps(left: frozenset, right: frozenset) -> bool:
    return any(a == b or a in b or b in a for a in left for b in right)


@lru_cache(maxsize=4096)
def fragment_forms(fragment: str) -> frozenset:
    """The loose text of a fragment, and what SQLGlot renders for it when it parses."""
    forms = {normalize_sql(fragment)} | {normalize_sql(text) for text in _rendered(fragment)}
    return frozenset(form for form in forms if form)


def _rendered(fragment: str) -> list[str]:
    body = strip_leading_keyword(fragment)
    if not body.strip():
        return []
    try:
        tree = sqlglot.parse_one(body, read=DIALECT)
        return [tree.sql(dialect=DIALECT)] if tree is not None else []
    except _PARSE_ERRORS:
        pass
    try:
        joins = sqlglot.parse_one(_JOIN_HOST + body, read=DIALECT).args.get("joins") or []
    except _PARSE_ERRORS:
        return []
    rendered = [join.sql(dialect=DIALECT) for join in joins]
    return rendered + [
        join.args["on"].sql(dialect=DIALECT) for join in joins if join.args.get("on")
    ]


@lru_cache(maxsize=64)
def task_sql(scripts: tuple) -> TaskSql:
    """The comparison forms of the task scripts a packet carries."""
    trees = [tree for script in scripts for tree in _statements(script)]
    return TaskSql(
        raw=normalize_sql("\n".join(scripts)),
        rendered=normalize_sql("\n".join(tree.sql(dialect=DIALECT) for tree in trees)),
        units=tuple(unit for tree in trees for unit in _units(tree)),
    )


def _statements(script: str) -> list:
    """Every statement SQLGlot parses; a script that fails whole is tried piece by piece."""
    try:
        return [tree for tree in sqlglot.parse(script, read=DIALECT) if tree is not None]
    except _PARSE_ERRORS:
        pass
    trees = []
    for piece in script.split(";"):
        try:
            tree = sqlglot.parse_one(piece, read=DIALECT) if piece.strip() else None
        except _PARSE_ERRORS:
            continue
        if tree is not None:
            trees.append(tree)
    return trees


def _units(tree) -> list[frozenset]:
    ctes = {cte.alias_or_name.lower(): cte.this for cte in tree.find_all(exp.CTE)}
    units = []
    for node in tree.find_all(exp.Where, exp.Having, exp.Join):
        condition = node.args.get("on") if isinstance(node, exp.Join) else node.this
        if condition is None:
            continue
        select = node.find_ancestor(exp.Select)
        parts = [condition, *_conjuncts(condition)] if isinstance(condition, exp.And) else [
            condition
        ]
        units += [_unit_forms(part, select, ctes) for part in parts]
    return units


def _conjuncts(condition) -> list:
    if isinstance(condition, exp.And):
        return _conjuncts(condition.this) + _conjuncts(condition.expression)
    return [condition]


def _unit_forms(part, select, ctes: dict) -> frozenset:
    written = part.sql(dialect=DIALECT)
    resolved = _resolve(part.copy(), select, ctes, _RESOLVE_DEPTH).sql(dialect=DIALECT)
    return frozenset(form for form in (normalize_sql(written), normalize_sql(resolved)) if form)


# ------------------------------------------------------------------ derived columns


def _resolve(node, select, ctes: dict, depth: int):
    """``node`` with each column a derived source computes replaced by its expression."""
    if select is None or depth <= 0:
        return node
    sources = _derived_sources(select, ctes)
    if not sources:
        return node

    def replace(column):
        if not isinstance(column, exp.Column):
            return column
        found = _computed(column, sources)
        if found is None:
            return column
        inner, expression = found
        return _resolve(expression.copy(), inner, ctes, depth - 1)

    return node.transform(replace, copy=False)


def _derived_sources(select, ctes: dict) -> dict:
    """``alias -> query`` for each subquery and CTE the SELECT reads."""
    from_ = select.args.get("from_") or select.args.get("from")
    items = ([from_.this] if from_ is not None else []) + [
        join.this for join in select.args.get("joins") or []
    ]
    sources = {}
    for item in items:
        if isinstance(item, exp.Subquery) and item.alias_or_name:
            sources[item.alias_or_name.lower()] = item.this
        elif isinstance(item, exp.Table) and item.name.lower() in ctes:
            sources[(item.alias_or_name or item.name).lower()] = ctes[item.name.lower()]
    return sources


def _computed(column, sources: dict):
    """``(inner select, expression)`` behind a column a derived source computes, or None."""
    name = column.name.lower()
    candidates = [sources.get(column.table.lower())] if column.table else list(sources.values())
    found = []
    for query in candidates:
        if query is None:
            continue
        for projection in getattr(query, "selects", []):
            if _computes(projection, name):
                found.append((_first_select(query), projection.this))
    return found[0] if len(found) == 1 else None


def _computes(projection, name: str) -> bool:
    """An aliased projection named ``name`` that is more than the same-named column."""
    if not isinstance(projection, exp.Alias) or projection.alias.lower() != name:
        return False
    inner = projection.this
    return not (isinstance(inner, exp.Column) and inner.name.lower() == name)


def _first_select(query):
    return query if isinstance(query, exp.Select) else query.find(exp.Select)
