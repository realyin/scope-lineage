"""One comparison space for a quoted rule, a lineage filter and the task SQL (check 5).

A document's ``rules[].sql`` quotes the task script as written; the lineage renders every
predicate through SQLGlot, so ``nvl(x, 0)`` comes back as ``COALESCE(x, 0)``,
``substr`` as ``SUBSTRING``, ``x is not null`` as ``NOT x IS NULL`` -- and a column that a
derived table computes can come back as the expression behind it
(``DATE_FORMAT(time_inst, 'yyyyMMdd')`` for a subquery's ``dt``). A loose text match
cannot relate the two, so check 5 compares *forms*:

- a fragment's forms are its loose text (:func:`normalize_sql`) and, when SQLGlot parses
  it, the text SQLGlot renders for it in the lineage's dialect -- once as is and once
  without the echo aliases ``qualify`` adds inside a subquery (``follow_no AS follow_no``,
  ``sales AS sales``), so the script's ``x IN (SELECT follow_no FROM sales)`` and the
  lineage's qualified rendering of it meet;
- the task SQL's forms are its loose text, its rendered text, and one *unit* per WHERE,
  HAVING and ON predicate and per conjunct of each: the unit rendered as written and with
  every column a derived table or CTE computes replaced by the expression behind it.

A rule's SQL is found in the task SQL when any of its forms occurs in the script (loose or
rendered) or equals a unit; a lineage filter is cited when one of its forms *equals* a
form of a quoted rule (:func:`quote_forms`) -- the rule's own, one of its conjuncts', or
those of the units either equals. Containment is not citing: the same predicate text in a
CASE branch or a MERGE condition cites no WHERE filter.
"""

from __future__ import annotations

import re
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


@lru_cache(maxsize=4096)
def quote_forms(quote: str) -> frozenset:
    """The forms a quoted rule cites a filter by: its own and each of its conjuncts'.

    A quote is parsed without its comments and split at every top-level AND; a quote that
    copies a whole statement (SELECT, INSERT … SELECT) also gives the conjuncts of every
    WHERE, HAVING and ON inside it, nested subqueries included; a quote SQLGlot cannot
    parse whole is tried again without a dangling leading or trailing AND / OR, and
    failing that cut at each top-level `` and `` (a ``BETWEEN x AND y`` and anything in
    parentheses or quotes kept whole) and each piece tried on its own. A filter is cited
    only by a form *equal* to one of its own: a CASE branch or a MERGE condition that
    merely contains the filter's text cites nothing.
    """
    forms: set = set()
    for piece in quote_pieces(quote):
        forms |= fragment_forms(piece)
    return frozenset(forms)


@lru_cache(maxsize=4096)
def quote_pieces(quote: str) -> tuple[str, ...]:
    """The quote itself and every conjunct :func:`quote_forms` takes from it."""
    return (quote, *_quote_conjuncts(quote))


def _quote_conjuncts(quote: str) -> list[str]:
    body = strip_leading_keyword(quote)
    if not body.strip():
        return []
    try:
        tree = sqlglot.parse_one(body, read=DIALECT)
    except _PARSE_ERRORS:
        tree = None
    if tree is None:
        stripped = _strip_dangling(body)
        if stripped != body.strip():
            return [stripped, *_quote_conjuncts(stripped)] if stripped else []
        try:
            joins = sqlglot.parse_one(_JOIN_HOST + body, read=DIALECT).args.get("joins") or []
        except _PARSE_ERRORS:
            joins = []
        conditions = [join.args["on"] for join in joins if join.args.get("on")]
        if not conditions:
            pieces = split_top_level_and(body)
            return [] if len(pieces) < 2 else [
                part for piece in pieces for part in _quote_conjuncts(piece)] + pieces
    else:
        # A quote that copies a whole statement holds its WHERE / HAVING / ON predicates
        # (nested ones too) as written; a bare predicate holds none, and a CASE branch in
        # a select list or a MERGE ``WHEN`` condition is no WHERE, so neither adds a form.
        conditions = [tree, *(condition for _node, condition in _conditions(tree))]
    return [node.sql(dialect=DIALECT, comments=False)
            for condition in conditions for node in [condition, *_quoted_conjuncts(condition)]]


def _quoted_conjuncts(condition) -> list:
    """A quote's conjuncts, parentheses around a conjunction or a conjunct looked through.

    ``((a = 1) AND (b = 2))`` quotes ``a = 1`` and ``b = 2``; the parentheses group, they
    do not make a different predicate.
    """
    while isinstance(condition, exp.Paren):
        condition = condition.this
    if isinstance(condition, exp.And):
        return _quoted_conjuncts(condition.this) + _quoted_conjuncts(condition.expression)
    return [condition]


def _conditions(tree) -> list[tuple]:
    """Each WHERE, HAVING and JOIN node in a tree with the condition it holds."""
    found = []
    for node in tree.find_all(exp.Where, exp.Having, exp.Join):
        condition = node.args.get("on") if isinstance(node, exp.Join) else node.this
        if condition is not None:
            found.append((node, condition))
    return found


_DANGLING = re.compile(r"^(?:\s*\b(?:and|or)\b)+|(?:\b(?:and|or)\b\s*)+$", re.IGNORECASE)
# The tokens the fallback split walks: a string, a parenthesis, a word, anything else.
_SPLIT_TOKEN = re.compile(r"""'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|[()]|\w+|\s+|.""")


def _strip_dangling(body: str) -> str:
    """``x = 1 AND`` -> ``x = 1``: a quote cut mid-conjunction, without its loose end."""
    return _DANGLING.sub("", body.strip()).strip()


def split_top_level_and(body: str) -> list[str]:
    """``body`` cut at each top-level ``AND`` -- the fallback for a quote SQLGlot rejects.

    Top level is outside parentheses (a depth counter, so nesting is followed) and outside
    string literals; the ``AND`` that closes a ``BETWEEN x AND y`` at the same depth is
    part of that predicate, not a cut.
    """
    pieces, current, depth, between = [], [], 0, set()
    for token in _SPLIT_TOKEN.findall(body):
        word = token.lower()
        if token == "(":
            depth += 1
        elif token == ")":
            depth = max(depth - 1, 0)
        elif word == "between":
            between.add(depth)
        elif word == "and" and depth == 0 and 0 not in between:
            pieces.append("".join(current).strip())
            current = []
            continue
        elif word == "and" and depth in between:
            between.discard(depth)
        current.append(token)
    pieces.append("".join(current).strip())
    return [piece for piece in pieces if piece]


@lru_cache(maxsize=4096)
def fragment_forms(fragment: str) -> frozenset:
    """The loose text of a fragment, and what SQLGlot renders for it when it parses."""
    forms = {normalize_sql(fragment)} | {normalize_sql(text) for text in _rendered(fragment)}
    return frozenset(form for form in forms if form)


@lru_cache(maxsize=4096)
def qualifiers(fragment: str) -> dict[str, frozenset]:
    """``column -> the qualifiers it is written with`` in a fragment, lower case.

    The loose form (:func:`normalize_sql`) drops qualifiers so ``rn = 1`` and
    ```latest`.`rn` = 1`` meet; this keeps what it dropped, so check 5 can tell
    ``a.is_deleted = 0`` from ``b.is_deleted = 0``. An unqualified column is absent. A
    fragment SQLGlot cannot parse is read by a pattern outside its string literals.
    """
    body = _strip_dangling(strip_leading_keyword(fragment))
    found: dict[str, set] = {}
    try:
        tree = sqlglot.parse_one(body, read=DIALECT) if body else None
        pairs = [(column.name, column.table) for column in tree.find_all(exp.Column)] if tree else []
    except _PARSE_ERRORS:
        text = _STRING_OR_COMMENT.sub(" ", body.replace("`", ""))
        pairs = [(name, table) for table, name in _QUALIFIED_NAME.findall(text)]
    for name, table in pairs:
        if table:
            found.setdefault(name.lower(), set()).add(table.lower())
    return {name: frozenset(tables) for name, tables in found.items()}


_STRING_OR_COMMENT = re.compile(r"""'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|--[^\n]*""")
_QUALIFIED_NAME = re.compile(r"(?:[A-Za-z_]\w*\.)?([A-Za-z_]\w*)\.([A-Za-z_$][\w$]*)")


def _rendered(fragment: str) -> list[str]:
    body = strip_leading_keyword(fragment)
    if not body.strip():
        return []
    try:
        tree = sqlglot.parse_one(body, read=DIALECT)
        if tree is None:
            return []
        return [tree.sql(dialect=DIALECT), _without_echo_aliases(tree).sql(dialect=DIALECT)]
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


def _without_echo_aliases(tree):
    """A copy without aliases that only repeat a name: ``col AS col``, ``tbl AS tbl``.

    ``qualify`` writes them on every projection and table of a subquery; they change no
    meaning, and a script never needs to spell them. An alias that renames stays.
    """
    def drop(node):
        if (isinstance(node, exp.Alias) and isinstance(node.this, exp.Column)
                and node.this.name.lower() == node.alias.lower()):
            return node.this
        if (isinstance(node, exp.TableAlias) and not node.columns
                and isinstance(node.parent, exp.Table)
                and node.parent.name.lower() == node.name.lower()):
            return None
        return node

    return tree.copy().transform(drop)


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
    for node, condition in _conditions(tree):
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


def statement_starts(sql: str | None) -> list[int | None]:
    """W6: the offset each statement of a script starts at, by its ``statement_index``.

    Counted as SQLGlot splits a script -- the lineage's statement numbers come from that
    split: a statement ends at each ``;``, a ``;`` carrying a comment is a statement of its
    own, and an empty statement (``;;``) keeps its place with no offset. A script the
    tokenizer cannot read gives ``[]``.
    """
    try:
        tokens = sqlglot.Dialect.get_or_raise(DIALECT).tokenize(str(sql or ""))
    except _PARSE_ERRORS:
        return []
    chunks: list[list] = [[]]
    for index, token in enumerate(tokens):
        if token.token_type == sqlglot.TokenType.SEMICOLON:
            if token.comments:
                chunks.append([token])
            if index < len(tokens) - 1:
                chunks.append([])
        else:
            chunks[-1].append(token)
    return [chunk[0].start if chunk else None for chunk in chunks]
