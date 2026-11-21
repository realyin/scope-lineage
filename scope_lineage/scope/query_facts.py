"""What a hand-written query reads, joins, filters, aggregates and compares, as plain data.

``catalog check-sql`` compares a query an agent wrote against the catalog. The catalog side
lives in ``render`` and the parser here, and neither may import the other, so this module
hands the query over as dicts: one per statement holding a query, one entry per SELECT scope
in it. The query inside ``INSERT ... SELECT`` and ``CREATE TABLE ... AS SELECT`` is checked
too (with a ``WITH`` written before the ``INSERT``); the table written is not a read.
Statements with no query at all are skipped.

It parses with the same text repairs, dialect and strict-then-lenient check as the lineage
parser (``scope_builder``), qualifies with the same ``_qualify_ast`` and walks sqlglot's
scopes; it adds no grammar of its own. Each column reference carries the physical columns it
reaches (``targets``): through a table alias directly, through a CTE or subquery projection
that is a bare column, through ``*`` / ``alias.*`` of a scope with one source, and through
the same position of every UNION branch. Anything else -- an expression, an aggregate, a
UDTF output -- reaches nothing, and a reader must treat an empty ``targets`` as "cannot
tell", not as "no table". A bare column in a scope with more than one source is not
attributed to any of them (``ambiguous``): without a schema, picking one would be a guess.
"""

from __future__ import annotations

from typing import Optional

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope, walk_in_scope

from ._constants import DIALECT, PARSE_OPTS, _ORIGINALLY_UNQUALIFIED_META
from .parser import _qualified_table
from .scope_builder import _normalize_directory_insert_sql, _qualify_ast, _syntax_status
from .ctas_missing_as import repair_ctas_missing_as
from .keyword_identifiers import repair_keyword_identifiers

__all__ = ["QueryFactsError", "query_facts"]

_AMBIGUOUS = "ambiguous"
_MAX_DEPTH = 32
_CLAUSES = (
    (exp.Where, "where"),
    (exp.Join, "join"),
    (exp.Group, "group"),
    (exp.Having, "having"),
    (exp.Order, "order"),
)


class QueryFactsError(ValueError):
    """The text does not parse, or holds no query statement to check."""


def query_facts(sql: str) -> list[dict]:
    """One dict per query statement of ``sql``, numbered by script position from 1.

    Raises ``QueryFactsError`` when strict parsing fails (the lenient parse would check a
    repaired query, not the one written) or when no statement is a query.
    """
    status, errors = _syntax_status(sql)
    if status != "strict_ok":
        raise QueryFactsError(_parse_error_text(errors))
    normalized, _ = repair_keyword_identifiers(repair_ctas_missing_as(_normalize_directory_insert_sql(sql))[0])
    trees = sqlglot.parse(normalized, dialect=DIALECT, **PARSE_OPTS)
    statements = []
    skipped = []
    for position, tree in enumerate(trees, 1):
        query = _query_of(tree)
        if query is not None:
            statements.append(_statement(position, query))
        elif tree is not None and not isinstance(tree, exp.Semicolon):
            skipped.append(position)
    if not statements:
        raise QueryFactsError("没有可检查的查询语句（检查 SELECT，以及 INSERT / CTAS 里的查询）")
    for statement in statements:
        statement["skipped_statements"] = skipped
    return statements


_EXCERPT = 40


def _parse_error_text(errors: list[dict]) -> str:
    """Where strict parsing broke: line, column, the parser's words and the text around it."""
    if not errors:
        return "SQL 无法解析"
    first = errors[0]
    description = str(first.get("description") or "unknown error").splitlines()[0]
    where = ""
    if first.get("line") is not None and first.get("col") is not None:
        where = f"第 {first['line']} 行第 {first['col']} 列附近："
    excerpt = ""
    if first.get("highlight") is not None:
        flat = {key: str(first.get(key) or "").replace("\r", " ").replace("\n", " ")
                for key in ("start_context", "highlight", "end_context")}
        before = flat["start_context"][-_EXCERPT:]
        after = (flat["highlight"] + flat["end_context"])[:_EXCERPT]
        excerpt = f"；出错处（【此处】标在出错的位置）：…{before}【此处】{after}…"
    more = f"（另有 {len(errors) - 1} 条解析错误）" if len(errors) > 1 else ""
    return f"SQL 无法解析：{where}{description}{excerpt}{more}"


def _query_of(tree) -> Optional[exp.Expression]:
    """The query a statement runs: itself, or the SELECT an INSERT or a CTAS writes."""
    if isinstance(tree, exp.Query):
        return tree
    if isinstance(tree, (exp.Insert, exp.Create)) and isinstance(tree.expression, exp.Query):
        query = tree.expression.copy()
        leading = tree.args.get("with_")
        if leading is not None and query.args.get("with_") is None:
            query.set("with_", leading.copy())
        return query
    return None


def _statement(position: int, tree: exp.Expression) -> dict:
    qualified, _ = _qualify_ast(tree.copy())
    try:
        scopes = list(traverse_scope(qualified))
    except Exception as error:  # noqa: BLE001 - sqlglot raises its own types for trees it cannot scope
        raise QueryFactsError(f"第 {position} 条语句无法划分作用域：{error}") from error
    ids = {id(scope): f"q{number}" for number, scope in enumerate(scopes, 1)}
    facts = [_scope(scope, ids) for scope in scopes if isinstance(scope.expression, exp.Select)]
    reads = [
        {"read": f"{entry['id']}:{alias}", "scope": entry["id"], "alias": alias,
         "table": source["table"]}
        for entry in facts
        for alias, source in entry["sources"].items()
        if "table" in source
    ]
    return {"statement": position, "scopes": facts, "reads": reads}


# ------------------------------------------------------------------- scope


def _scope(scope: Scope, ids: dict) -> dict:
    select = scope.expression
    sources: dict = {}
    for alias, (_node, source) in scope.selected_sources.items():
        if isinstance(source, exp.Table):
            sources[alias] = {"table": _table_name(source)}
        elif isinstance(source, Scope):
            sources[alias] = {"scope": ids.get(id(source))}
        else:
            sources[alias] = {}
    refs = {id(column): _ref(scope, column, ids) for column in scope.columns}
    refs = {key: ref for key, ref in refs.items() if ref is not None}
    return {
        "id": ids[id(scope)],
        "kind": scope.scope_type.name.lower(),
        "name": _cte_name(scope),
        "sources": sources,
        "refs": list(refs.values()),
        "joins": _joins(select, refs),
        "aggregates": _aggregates(select, refs),
        "group_by": [
            refs[id(c)] for c in (select.args.get("group") or exp.Group()).find_all(exp.Column)
            if id(c) in refs
        ],
        "comparisons": _comparisons(select, refs),
    }


def _cte_name(scope: Scope) -> Optional[str]:
    parent = scope.expression.parent
    return parent.alias if scope.is_cte and isinstance(parent, exp.CTE) else None


def _table_name(table: exp.Table) -> str:
    return _qualified_table(table).lower()


def _ref(scope: Scope, column: exp.Column, ids: dict) -> Optional[dict]:
    if isinstance(column.this, exp.Star):
        return None
    owner = _owner(scope, column)
    if owner is None:
        return None
    clause = _clause(column, scope.expression)
    if owner == _AMBIGUOUS:
        return {"alias": None, "column": column.name, "clause": clause, "targets": [],
                "ambiguous": True}
    owner_scope, alias = owner
    return {
        "alias": alias,
        "column": column.name,
        "clause": clause,
        "targets": _resolve(owner_scope, alias, column.name, ids, 0),
        "ambiguous": False,
    }


def _owner(scope: Scope, column: exp.Column):
    """``(scope, alias)`` the column is read from, ``_AMBIGUOUS``, or None (a struct field,
    a name no enclosing scope defines)."""
    if column.args.get("db") is not None or column.args.get("catalog") is not None:
        return None
    selected = scope.selected_sources
    name = column.table
    if not name:
        return (scope, next(iter(selected))) if len(selected) == 1 else _AMBIGUOUS
    if column.meta.get(_ORIGINALLY_UNQUALIFIED_META) and len(selected) > 1:
        # qualify picked a source for a bare name; without a schema that is a guess
        return _AMBIGUOUS
    current: Optional[Scope] = scope
    while current is not None:
        if name in current.selected_sources:
            return current, name
        current = current.parent
    return None


def _clause(column: exp.Column, select: exp.Expression) -> str:
    node = column.parent
    while node is not None and node is not select:
        for kind, label in _CLAUSES:
            if isinstance(node, kind):
                return label
        node = node.parent
    return "select"


# ------------------------------------------------------------- resolution


def _resolve(scope: Scope, alias: str, name: str, ids: dict, depth: int) -> list[dict]:
    """The physical columns ``alias.name`` reaches from ``scope``."""
    entry = scope.selected_sources.get(alias)
    if entry is None or depth > _MAX_DEPTH:
        return []
    source = entry[1]
    if isinstance(source, exp.Table):
        return [{"table": _table_name(source), "column": name, "read": f"{ids[id(scope)]}:{alias}"}]
    if isinstance(source, Scope):
        return _resolve_output(source, name, ids, depth + 1)
    return []


def _resolve_output(scope: Scope, name: str, ids: dict, depth: int) -> list[dict]:
    expression = scope.expression
    folded = name.casefold()
    if isinstance(expression, exp.SetOperation):
        leaves = _leaf_scopes(scope)
        if not leaves or not isinstance(leaves[0].expression, exp.Select):
            return []
        names = [p.alias_or_name.casefold() for p in leaves[0].expression.selects]
        if folded not in names:
            return []
        position = names.index(folded)
        found = []
        for leaf in leaves:
            selects = leaf.expression.selects if isinstance(leaf.expression, exp.Select) else []
            if position < len(selects):
                found += _resolve_projection(leaf, selects[position], ids, depth)
        return found
    if not isinstance(expression, exp.Select):
        return []
    for projection in expression.selects:
        if not isinstance(projection, exp.Star) and projection.alias_or_name.casefold() == folded:
            return _resolve_projection(scope, projection, ids, depth)
    for projection in expression.selects:
        if isinstance(projection, exp.Star) and len(scope.selected_sources) == 1:
            return _resolve(scope, next(iter(scope.selected_sources)), name, ids, depth)
        if isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star):
            return _resolve(scope, projection.table, name, ids, depth)
    return []


def _resolve_projection(scope: Scope, projection: exp.Expression, ids: dict, depth: int) -> list:
    inner = projection.this if isinstance(projection, exp.Alias) else projection
    if not isinstance(inner, exp.Column) or isinstance(inner.this, exp.Star):
        return []
    owner = _owner(scope, inner)
    if owner is None or owner == _AMBIGUOUS:
        return []
    owner_scope, alias = owner
    return _resolve(owner_scope, alias, inner.name, ids, depth)


def _leaf_scopes(scope: Scope) -> list[Scope]:
    if not scope.union_scopes:
        return [scope]
    return [leaf for child in scope.union_scopes for leaf in _leaf_scopes(child)]


# ------------------------------------------------- joins, aggregates, values


def _conjuncts(condition: Optional[exp.Expression]):
    if condition is None:
        return
    if isinstance(condition, exp.Paren):
        yield from _conjuncts(condition.this)
    elif isinstance(condition, exp.And):
        yield from _conjuncts(condition.left)
        yield from _conjuncts(condition.right)
    else:
        yield condition


def _equal_pairs(condition, refs: dict, *, distinct_aliases: bool) -> list[dict]:
    pairs = []
    for item in _conjuncts(condition):
        if not isinstance(item, exp.EQ):
            continue
        left, right = item.this, item.expression
        if not (isinstance(left, exp.Column) and isinstance(right, exp.Column)):
            continue
        a, b = refs.get(id(left)), refs.get(id(right))
        if not a or not b or a["ambiguous"] or b["ambiguous"]:
            continue
        if distinct_aliases and a["alias"] == b["alias"]:
            continue
        pairs.append({"left": a, "right": b})
    return pairs


def _joins(select: exp.Select, refs: dict) -> list[dict]:
    joins = []
    for join in select.args.get("joins") or []:
        kind = " ".join(part for part in (join.side, join.kind) if part).upper() or "INNER"
        joins.append({
            "alias": join.this.alias_or_name,
            "kind": kind,
            "in": "on",
            "pairs": _equal_pairs(join.args.get("on"), refs, distinct_aliases=False),
        })
    where = select.args.get("where")
    pairs = _equal_pairs(where.this if where else None, refs, distinct_aliases=True)
    if pairs:
        joins.append({"alias": None, "kind": "WHERE", "in": "where", "pairs": pairs})
    return joins


def _aggregates(select: exp.Select, refs: dict) -> list[dict]:
    found = []
    for node in walk_in_scope(select):
        if not isinstance(node, (exp.Sum, exp.Count)) or isinstance(node.parent, exp.Window):
            continue
        found.append({
            "function": "SUM" if isinstance(node, exp.Sum) else "COUNT",
            "distinct": isinstance(node.this, exp.Distinct),
            "columns": [refs[id(c)] for c in node.find_all(exp.Column) if id(c) in refs],
        })
    return found


def _literal(node: exp.Expression) -> Optional[str]:
    if isinstance(node, exp.Literal):
        return str(node.this)
    if isinstance(node, exp.Neg) and isinstance(node.this, exp.Literal) and not node.this.is_string:
        return f"-{node.this.this}"
    return None


def _comparisons(select: exp.Select, refs: dict) -> list[dict]:
    found = []
    for node in walk_in_scope(select):
        if isinstance(node, exp.EQ):
            for column, other in ((node.this, node.expression), (node.expression, node.this)):
                value = _literal(other)
                if isinstance(column, exp.Column) and id(column) in refs and value is not None:
                    found.append({"ref": refs[id(column)], "op": "=", "values": [value]})
        elif isinstance(node, exp.In) and not node.args.get("query"):
            column = node.this
            values = [_literal(item) for item in node.expressions]
            if isinstance(column, exp.Column) and id(column) in refs and values and None not in values:
                found.append({"ref": refs[id(column)], "op": "in", "values": values})
    return found
