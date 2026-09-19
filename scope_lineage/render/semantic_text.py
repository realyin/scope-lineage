"""Chinese restatements of contract expressions and structures (semantic profile, R4).

One theme only: turn an expression string or a structural tuple from the lineage
contract into one short Chinese sentence. Nothing here reads a document, decides a
role, or builds a profile -- ``semantic_profile`` does that and calls in here for the
words. The ``stages`` block reuses the same templates, and the window-intent wording
lives here while the intent *decision* (R6) stays in ``semantic_profile``.

Two rules the templates never break:

- **Structural words only.** A template may name a SQL operation (聚合 / 去重 / 窗口 /
  常量 / 合并 / 过滤 / 投影) and may echo an expression verbatim; it may never name a
  business concept. Anything the vocabulary cannot restate returns ``None`` and the
  caller keeps the raw expression instead of guessing.
- **Literals come from the raw expression.** The contract's ``display_expression`` is a
  reader-facing form that lower-cases string literals (``'HIGH'`` renders as ``'high'``),
  so callers must pass ``raw_expression`` / ``expression_sql`` / the end-to-end
  ``expression``, and the templates echo what they are given.

Identifiers are re-rendered without their backticks and a bare column is printed by its
column name alone; the qualified fact stays in the profile's ``sources[]``, so the
sentence does not have to carry it.
"""

from __future__ import annotations

import copy
import datetime
import re
from typing import Iterable, Mapping, Sequence

import sqlglot
from sqlglot import exp

from .markdown_text import normalize_inline as _normalize_inline


# The renderer may not import scope internals (architecture rule), so the dialect name
# is repeated here exactly as `scope/_constants.py` declares it.
DIALECT = "spark"

UDF_MARKER = "UDF 黑盒"

# A CASE with more branches than this is folded to a preview instead of listed in full.
CASE_BRANCH_PREVIEW_LIMIT = 6
CASE_BRANCH_PREVIEW_COUNT = 3

# The template families the glossary maps onto. Enumerated so a test can assert that no
# glossary entry points at a template that does not exist.
TEMPLATE_KINDS = frozenset(
    {
        "null_fill",
        "cast",
        "concat",
        "date",
        "text",
        "if",
        "round",
        "aggregate",
        "regex",
        "json",
        "explode",
        "numeric",
        "pattern",
    }
)

# The first-phase function vocabulary, explicit so tests can enumerate it and a reviewer
# can see the whole surface at once. A function outside it is never restated.
FUNCTION_GLOSSARY: dict[str, str] = {
    "COALESCE": "null_fill",
    "NVL": "null_fill",
    "IFNULL": "null_fill",
    "CAST": "cast",
    "CONCAT": "concat",
    "CONCAT_WS": "concat",
    "DATE_ADD": "date",
    "DATE_SUB": "date",
    "DATE_FORMAT": "date",
    "TO_DATE": "date",
    "DATEDIFF": "date",
    "DATE_TRUNC": "date",
    "UPPER": "text",
    "LOWER": "text",
    "TRIM": "text",
    "IF": "if",
    "ROUND": "round",
    "FLOOR": "round",
    "CEIL": "round",
    "SUM": "aggregate",
    "COUNT": "aggregate",
    "AVG": "aggregate",
    "MIN": "aggregate",
    "MAX": "aggregate",
    # WI-1d: the families the real corpus left unrestated most often.
    "REGEXP_REPLACE": "regex",
    "REGEXP_EXTRACT": "regex",
    "RLIKE": "regex",
    "LIKE": "pattern",
    "GET_JSON_OBJECT": "json",
    "FROM_JSON": "json",
    "JSON_TUPLE": "json",
    "EXPLODE": "explode",
    "POSEXPLODE": "explode",
    "SPLIT": "explode",
    "SUBSTRING": "text",
    "SUBSTR": "text",
    "LENGTH": "text",
    "REPLACE": "text",
    "UNIX_TIMESTAMP": "date",
    "FROM_UNIXTIME": "date",
    "CURRENT_TIMESTAMP": "date",
    "CURRENT_DATE": "date",
    "NULLIF": "null_fill",
    "NVL2": "null_fill",
    "ABS": "numeric",
    "GREATEST": "numeric",
    "LEAST": "numeric",
}

# The null-handling family is not all "fill a null in": NULLIF and NVL2 decide with a
# null rather than replace one, so they are named instead of being given the COALESCE
# sentence, which would state a substitution the SQL does not perform.
_NULL_DECIDING_FUNCTIONS = frozenset({"NULLIF", "NVL2"})

# The regex family, one verb each. A shared "正则" sentence would lose the difference
# between replacing, extracting and testing.
_REGEX_TEXT = {
    "REGEXP_REPLACE": "正则替换",
    "REGEXP_EXTRACT": "正则提取",
    "RLIKE": "正则匹配",
}

# Arithmetic has no function name to look up, so the node types stand in for one.
_ARITHMETIC_NODES = (exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Mod)

# Aggregate functions whose result is a measure rather than a picked row value; used by
# the profile's structural-role rule (R5) and kept next to the glossary it belongs to.
NUMERIC_AGGREGATE_FUNCTIONS = frozenset({"SUM", "COUNT", "AVG"})
SELECTIVE_AGGREGATE_FUNCTIONS = frozenset({"MIN", "MAX"})

# WI-1f, the structural gloss a few call shapes get in parentheses after the call. The
# call itself is never replaced -- the SQL stays readable and the gloss only says which
# of two structural readings applies -- and MIN/MAX depend on the argument's declared
# type, which the caller supplies as ``column_types``. No entry names a business idea.
_TEMPORAL_SELECTIVE_TEXT = {"MAX": "最晚时间", "MIN": "最早时间"}
_SCALAR_SELECTIVE_TEXT = {"MAX": "最大值", "MIN": "最小值"}

# The declared types that make MIN/MAX a "time", reusing the profile's own prefix rule.
_TEMPORAL_TYPE_PREFIXES = ("timestamp", "date", "datetime")

# WI-1f. One fixed sentence per join type, saying what happens to the rows the join
# cannot match. It is a property of the join type and of nothing else, so it is a
# constant rather than something derived per document; a join type outside this table
# (SEMI / ANTI / a kind the parser passed through) gets no sentence at all rather than
# an approximate one.
JOIN_NULL_SEMANTICS = {
    "LEFT_OUTER": "右侧无匹配时保留左行，右侧字段为空",
    "INNER": "无匹配的行被丢弃",
    "RIGHT_OUTER": "左侧无匹配时保留右行，左侧字段为空",
    "FULL_OUTER": "任一侧无匹配都保留，对侧字段为空",
    "CROSS": "笛卡尔积",
}

# The join types whose *right* side and *left* side may come back all-NULL. Read by the
# profile's `nullable_by_join` rule, which needs the side rather than the sentence.
NULLABLE_RIGHT_JOIN_TYPES = frozenset({"LEFT_OUTER", "FULL_OUTER"})
NULLABLE_LEFT_JOIN_TYPES = frozenset({"RIGHT_OUTER", "FULL_OUTER"})


# --------------------------------------------------------------------- parsing


def parse_expression(expression: str | None):
    """Parse one Spark expression, or return None when sqlglot cannot."""
    if not expression:
        return None
    try:
        return sqlglot.parse_one(str(expression), read=DIALECT)
    except Exception:  # noqa: BLE001 - sqlglot raises many parse error types; any of
        # them means "not restatable", which is a normal outcome here, not a failure.
        return None


# ------------------------------------------------------------------ comment kinds

# WI-2.8 D9. Two different things arrive as one `--` comment: a note the author wrote
# for the next reader, and a line of SQL the author switched off. Only the first is a
# statement about what a column means; the second is a record of what the code used to
# do, and prefixing a field's sentence with 「注释：cast(null as string) as x」 invited a
# reader to take an abandoned expression for the current definition.
COMMENT_KIND_NOTE = "note"
COMMENT_KIND_COMMENTED_OUT_SQL = "commented_out_sql"

COMMENT_KINDS = (COMMENT_KIND_NOTE, COMMENT_KIND_COMMENTED_OUT_SQL)

# The verdict needs BOTH halves, because either alone is wrong often enough to matter.
# `金额(元)` parses as a function call and is prose; `cast 过的字段` carries a SQL word
# and is prose. Only a body that parses into a SQL SHAPE *and* spells at least one ASCII
# SQL word is called commented-out code -- everything else stays a note, which is the
# conservative side: a misread note loses a field's explanation, a misread fragment only
# leaves one line of noise where it already was.
_SQL_WORDS = frozenset(
    {
        "and",
        "as",
        "avg",
        "case",
        "cast",
        "coalesce",
        "concat",
        "count",
        "distinct",
        "else",
        "end",
        "from",
        "group",
        "if",
        "ifnull",
        "insert",
        "join",
        "lateral",
        "max",
        "min",
        "null",
        "nvl",
        "on",
        "order",
        "over",
        "overwrite",
        "partition",
        "select",
        "substr",
        "substring",
        "sum",
        "then",
        "union",
        "when",
        "where",
    }
)

_ASCII_WORD_RE = re.compile(r"[a-z_][a-z0-9_]*")


def comment_kind(text: str | None) -> str:
    """``note`` unless the comment body IS SQL somebody commented out (WI-2.8 D9)."""
    body = str(text or "").strip().rstrip(";").strip()
    if not body or not _SQL_WORDS & set(_ASCII_WORD_RE.findall(body.lower())):
        return COMMENT_KIND_NOTE
    node = parse_expression(body)
    if node is None or not _is_sql_shaped(node):
        return COMMENT_KIND_NOTE
    return COMMENT_KIND_COMMENTED_OUT_SQL


def _is_sql_shaped(node: exp.Expression) -> bool:
    """A query, or a computed projection. A bare name with a word beside it is prose."""
    if isinstance(node, (exp.Select, exp.Union, exp.Insert, exp.Subquery, exp.Case)):
        return True
    if isinstance(node, exp.Alias):
        return not isinstance(node.this, (exp.Column, exp.Identifier, exp.Literal))
    return isinstance(node, exp.Func)


def is_note(text: str | None) -> bool:
    """The filter every field-level comment collector applies before publishing."""
    return comment_kind(text) == COMMENT_KIND_NOTE


def _plain(node: exp.Expression) -> exp.Expression:
    """A copy with identifier quoting and column qualifiers dropped.

    The sentence is a gloss, not an identifier: ``base.customer_name`` reads as
    ``customer_name`` here, while the qualified fact stays in the profile's
    ``sources[]`` / ``fields[]`` and the verbatim SQL stays in ``expression``.

    SQL comments are dropped for the same reason: ``/* 2026 rewrite */`` is a note to
    the next engineer, not part of what the expression computes, and sqlglot would
    otherwise re-emit it into the middle of the sentence. The comment survives in the
    profile's ``expression`` key, which is the verbatim SQL.
    """
    clone = copy.deepcopy(node)
    for item in clone.walk():
        item.comments = None
    for column in clone.find_all(exp.Column):
        for part in ("table", "db", "catalog"):
            if column.args.get(part) is not None:
                column.set(part, None)
    for identifier in clone.find_all(exp.Identifier):
        identifier.set("quoted", False)
    return clone


def expression_text(node: exp.Expression | None) -> str:
    """Render a parsed node back to SQL without quoting or column qualifiers."""
    if node is None:
        return ""
    return _plain(node).sql(dialect=DIALECT)


# sqlglot canonicalizes several surface functions onto one node type; map the canonical
# name back to the surface family the glossary is written in.
_CANONICAL_FUNCTION_ALIASES = {
    "TS_OR_DS_ADD": "DATE_ADD",
    "TS_OR_DS_TO_DATE": "TO_DATE",
    "TIME_TO_STR": "DATE_FORMAT",
    "TIMESTAMP_TRUNC": "DATE_TRUNC",
    "REGEXP_LIKE": "RLIKE",
    "JSON_EXTRACT_SCALAR": "GET_JSON_OBJECT",
    "REGEXP_SPLIT": "SPLIT",
    "STR_TO_UNIX": "UNIX_TIMESTAMP",
    "UNIX_TO_STR": "FROM_UNIXTIME",
}


def function_name(node: exp.Expression | None) -> str | None:
    """The upper-case surface name of a function-like node, or None."""
    if node is None:
        return None
    if isinstance(node, exp.Cast):
        return "CAST"
    if isinstance(node, exp.If):
        return "IF"
    if isinstance(node, exp.Anonymous):
        return str(node.this).upper()
    # LIKE / ILIKE parse to a binary predicate rather than to a function node, so the
    # glossary would never see them without being told their surface name here.
    if isinstance(node, (exp.Like, exp.ILike)):
        return "LIKE"
    if isinstance(node, exp.Func):
        name = node.sql_name().upper()
        return _CANONICAL_FUNCTION_ALIASES.get(name, name)
    return None


def has_unknown_function(expression: str | None) -> bool | None:
    """Whether the expression calls a function this renderer cannot name at all.

    WI-1g item E3. The contract's ``expression_features.has_udf`` is computed against
    ``scope/function_catalog.py``'s scalar list, which stops at 40-odd names: ``HOUR``,
    ``RANK`` and ``LAG`` are all reported as UDFs there, and a step restated as "UDF 黑盒"
    tells the reader a builtin is opaque. sqlglot already knows the Spark builtins -- it
    parses each of them into its own ``Func`` subclass and only falls back to
    ``exp.Anonymous`` for a name it does not know -- so that parse is the whitelist.

    Returns None when sqlglot cannot parse the expression at all: "cannot tell" is not
    "no UDF", and the caller keeps the contract's own verdict in that case.
    """
    node = parse_expression(expression)
    if node is None:
        return None
    return any(True for _ in node.find_all(exp.Anonymous))


def aggregate_functions(expression: str | None) -> set[str]:
    """Upper-case names of the aggregate functions appearing in an expression."""
    node = parse_expression(expression)
    if node is None:
        return set()
    found = set()
    for candidate in [node, *node.find_all(exp.AggFunc)]:
        if isinstance(candidate, exp.AggFunc):
            name = function_name(candidate)
            if name:
                found.add(name)
    return found


# --------------------------------------------------------------------- CASE


def split_case_branches(
    expression: str | None,
) -> tuple[list[dict], str | None] | None:
    """Split a CASE (or IF) expression into ``([{when, then}], else)``.

    Returns None when the expression does not parse or is not a conditional -- the
    caller then keeps the raw expression instead of inventing branches.
    """
    node = parse_expression(expression)
    if isinstance(node, exp.Case):
        branches = [
            {
                "when": expression_text(condition.this),
                "then": expression_text(condition.args.get("true")),
            }
            for condition in node.args.get("ifs") or []
        ]
        default = node.args.get("default")
        return branches, expression_text(default) if default is not None else None
    if isinstance(node, exp.If):
        branches = [
            {
                "when": expression_text(node.this),
                "then": expression_text(node.args.get("true")),
            }
        ]
        default = node.args.get("false")
        return branches, expression_text(default) if default is not None else None
    return None


def equals_one_predicate(expression: str | None, column: str) -> bool:
    """True when the predicate tests ``<column> = 1`` (either side of the equality).

    The window-intent rule (R6) turns on exactly this test, so it is answered by parsing
    rather than by matching text: ``WHERE `r`.`rn` = 1`` and ``1 = rn`` are the same
    fact, and ``rn = 10`` is not. A leading WHERE/HAVING keyword is stripped because
    ``filter_after_window`` entries quote the clause, not the bare predicate.
    """
    if not expression or not column:
        return False
    text = str(expression).strip()
    for keyword in ("WHERE ", "HAVING "):
        if text.upper().startswith(keyword):
            text = text[len(keyword):]
            break
    node = parse_expression(text)
    if node is None:
        return False
    for candidate in [node, *node.find_all(exp.EQ)]:
        if not isinstance(candidate, exp.EQ):
            continue
        sides = (candidate.this, candidate.expression)
        for named, literal in (sides, sides[::-1]):
            if (
                isinstance(named, exp.Column)
                and named.name == column
                and isinstance(literal, exp.Literal)
                and not literal.args.get("is_string")
                and str(literal.this) == "1"
            ):
                return True
    return False


VALUE_KIND_LITERAL = "literal"
VALUE_KIND_PARAMETER = "parameter"
VALUE_KIND_EXPRESSION = "expression"


def equality_conjunct(expression: str | None) -> tuple[str, str, str] | None:
    """``(column name, rendered right side, value kind)`` for ``<col> = <value>``, else None.

    WI-1f's governance findings turn on the *kind* of the right side: a date pinned to
    ``'20260814'`` is a literal, ``${bizdate}`` is a parameter (sqlglot parses it as
    one, so the distinction is read from the tree, not by looking for a dollar sign),
    and anything else -- ``date_sub(current_date(), 1)``, another column -- is an
    expression. Only the literal is ever reported.
    """
    node = parse_expression(expression)
    if not isinstance(node, exp.EQ) or not isinstance(node.this, exp.Column):
        return None
    right = node.expression
    if isinstance(right, exp.Literal):
        kind = VALUE_KIND_LITERAL
    elif isinstance(right, exp.Parameter):
        kind = VALUE_KIND_PARAMETER
    else:
        kind = VALUE_KIND_EXPRESSION
    return node.this.name, expression_text(right), kind


# ------------------------------------------------- metric definition slots (WI-2.1)

# A conjunct that bounds a value rather than pinning it. It is its own kind because a
# metric's time range is usually written this way (`dt >= a AND dt < b`) and calling it
# an "expression" would lose the one thing the reader is asking about.
VALUE_KIND_RANGE = "range"

# WI-2.9 item A. A date filter pinned to a day written out in full. One task instance
# covers one day, so this is what a scheduled statement is *supposed* to look like --
# calling it 字面量 beside 变量 read as an accusation, which is the complaint this kind
# answers. It is still a literal in every other respect; only the wording changes.
VALUE_KIND_INSTANCE_DATE = "instance_date"

# `'20260814'` / `'2026-08-14'` / `'2026/08/14'`: how a date is written when it is
# written as a constant. Nothing longer is matched, so `'2026-08-14 10:00:00'` still
# counts (prefix) while an ordinary code does not.
_DATE_LITERAL = re.compile(r"^(?:\d{8}|\d{4}[-/]\d{2}[-/]\d{2})")

# The substitution a scheduler fills in. sqlglot parses a bare `${x}` as a Parameter;
# written inside quotes it is a string literal, and the substitution is the same fact,
# so both are reported as `parameter` rather than as a hardcoded value.
_PARAMETER_MARKER = "${"


def looks_like_date_literal(value: str | None) -> bool:
    """True when a constant is *written* like a date -- a shape, never a type claim."""
    text = str(value or "").strip().strip("'\"")
    return bool(_DATE_LITERAL.match(text))


def _value_kind(node: exp.Expression | None) -> str:
    if isinstance(node, exp.Parameter):
        return VALUE_KIND_PARAMETER
    if isinstance(node, exp.Literal):
        if _PARAMETER_MARKER in str(node.this):
            return VALUE_KIND_PARAMETER
        return VALUE_KIND_LITERAL
    return VALUE_KIND_EXPRESSION


def predicate_value_kind(expression: str | None) -> str | None:
    """What one filter conjunct pins its column to: literal / parameter / expression / range.

    The same four-way reading ``equality_conjunct`` performs for the governance
    findings, widened to the comparisons a date window is written with. None means the
    conjunct did not parse, which is "cannot tell", not "expression".
    """
    node = parse_expression(expression)
    if node is None:
        return None
    if isinstance(node, (exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Between, exp.In)):
        return VALUE_KIND_RANGE
    if isinstance(node, (exp.EQ, exp.NEQ)):
        return _value_kind(node.expression)
    return VALUE_KIND_EXPRESSION


def predicate_columns(expression: str | None) -> list[str]:
    """The column names one predicate reads, in order, deduped and unqualified."""
    node = parse_expression(expression)
    if node is None:
        return []
    names: list[str] = []
    for column in node.find_all(exp.Column):
        name = column.name
        if name and name not in names:
            names.append(str(name))
    return names


def predicate_pins_a_date(expression: str | None) -> bool:
    """True when some constant in the predicate is written as a date or a variable.

    The third of the three date tests (after the declared type and the contract's own
    partition verdict), and the only one that works when no metadata was supplied.
    """
    node = parse_expression(expression)
    if node is None:
        return False
    if any(True for _ in node.find_all(exp.Parameter)):
        return True
    return any(
        looks_like_date_literal(str(item.this)) or _PARAMETER_MARKER in str(item.this)
        for item in node.find_all(exp.Literal)
    )


# WI-2.1d item 4. What the wrapper restatement puts where the aggregate stood: the call
# it wraps is already named in the card's own `aggregation` slot, so repeating it inside
# the sentence would state the same fact twice.
AGGREGATE_ELLIPSIS = "…"


def outer_aggregate_call(expression: str | None):
    """The outermost aggregate call an expression carries, or None when it carries none.

    WI-2.1d item 4. ``DATE_FORMAT(MAX(t), 'yyyy-MM-dd')`` is a ``MAX`` in a scalar coat:
    the rows it answers over are the group's, whatever the outer call does to the value
    afterwards, so reading only the *top* node left such a field with no aggregation at
    all. The walk is breadth-first so the call nearest the surface wins -- ``SUM`` of a
    ``MAX`` is summed, and the outer one is the metric's own.

    A call under a ``Window`` is never returned: a window keeps every row it reads, so it
    sets no grain, and treating ``SUM(x) OVER (...)`` as an aggregate would claim one.
    """
    node = parse_expression(expression)
    if node is None:
        return None
    return next(
        (
            item
            for item in node.bfs()
            if isinstance(item, exp.AggFunc) and item.find_ancestor(exp.Window) is None
        ),
        None,
    )


def describe_aggregate_wrapper(expression: str | None) -> str | None:
    """``"外层 F(…)"`` when a scalar call wraps the aggregate, else None (WI-2.1d item 4).

    The wrapper is a step of the metric's definition that happens inside one expression
    rather than in a later chain step, so ``post_aggregation`` would otherwise never
    mention that the number a reader sees has been reformatted or rescaled.
    """
    node = parse_expression(expression)
    if node is None:
        return None
    clone = _plain(_unwrap(node))
    call = next(
        (
            item
            for item in clone.bfs()
            if isinstance(item, exp.AggFunc) and item.find_ancestor(exp.Window) is None
        ),
        None,
    )
    if call is None or call is clone:
        return None
    call.replace(exp.var(AGGREGATE_ELLIPSIS))
    return f"外层 {clone.sql(dialect=DIALECT)}"


def aggregate_call_parts(expression: str | None) -> tuple[str | None, str | None]:
    """``(function, argument)`` of the aggregate call an expression carries, else ``(None, None)``.

    A call whose argument is a one-branch CASE answers with the *summed* value rather
    than with the whole conditional: the condition is the metric's inclusion rule and is
    published there, so repeating it inside the argument would state it twice in two
    different words.
    """
    call = outer_aggregate_call(expression)
    if call is None:
        return None, None
    name, _, argument = _aggregate_parts(call)
    if argument is None or isinstance(argument, exp.Star):
        return name, "*"
    split = split_case_branches(argument.sql(dialect=DIALECT))
    if split is not None and len(split[0]) == 1:
        return name, split[0][0]["then"]
    return name, expression_text(argument)


def aggregate_case_conditions(expression: str | None) -> list[str]:
    """The WHEN conditions of a CASE used as an aggregate call's argument."""
    call = outer_aggregate_call(expression)
    if call is None:
        return []
    _, _, argument = _aggregate_parts(call)
    if argument is None or isinstance(argument, exp.Star):
        return []
    split = split_case_branches(argument.sql(dialect=DIALECT))
    return [str(branch["when"]) for branch in (split[0] if split else []) if branch["when"]]


def coalesce_default(expression: str | None) -> str | None:
    """The fallback argument of a COALESCE / NVL / IFNULL call, wherever it sits.

    Depth is not restricted here: a COALESCE anywhere inside an expression still puts a
    value where a null would have been, and the caller decides whose expression it is
    reading.
    """
    node = parse_expression(expression)
    if node is None:
        return None
    for candidate in [node, *node.find_all(exp.Coalesce)]:
        if isinstance(candidate, exp.Coalesce):
            arguments = [candidate.this, *(candidate.expressions or [])]
            if len(arguments) > 1 and arguments[-1] is not None:
                return expression_text(arguments[-1])
    return None


def top_level_coalesce_default(expression: str | None) -> str | None:
    """The same fallback, but only when the COALESCE *is* the whole expression.

    WI-2.1d item 2. A chain step whose value is a COALESCE fills the null of the column
    that step produces. One buried inside a predicate or a branch (``CASE WHEN
    COALESCE(a, 0) <= 1 THEN ...``) fills something the step reads on the way, which is
    a different column's story and belongs to whichever field that column feeds.
    """
    node = _unwrap(parse_expression(expression))
    if not isinstance(node, exp.Coalesce):
        return None
    arguments = [node.this, *(node.expressions or [])]
    return expression_text(arguments[-1]) if len(arguments) > 1 else None


def constant_case_default(expression: str | None) -> str | None:
    """The ELSE of a *top-level* CASE / IF, when that ELSE is a scalar constant.

    WI-2.1d item 2. Two restrictions, and each answers a way the loose search was wrong.
    Top level, because a CASE nested inside another call is that call's *argument*: the
    grouping key's fallback branch is not the metric's null fill, however deep in the
    same expression it sits. And a constant ELSE, because an ELSE that is a column or an
    expression does not fill anything in -- it carries some other value through, which
    is still null when that value is.
    """
    node = _unwrap(parse_expression(expression))
    if isinstance(node, exp.Case):
        default = node.args.get("default")
    elif isinstance(node, exp.If):
        default = node.args.get("false")
    else:
        return None
    return expression_text(default) if _is_scalar_constant(default) else None


def _is_scalar_constant(node: exp.Expression | None) -> bool:
    """A literal, a NULL or a boolean -- through parentheses and a leading sign."""
    while isinstance(node, (exp.Paren, exp.Neg)):
        node = node.this
    return isinstance(node, (exp.Literal, exp.Null, exp.Boolean))


def null_fill_default(expression: str | None) -> tuple[str | None, str | None]:
    """``(default value, "COALESCE" | "CASE_ELSE")`` when one step provably fills a null.

    Only the two shapes the contract can prove: a COALESCE / NVL family call, whose last
    argument is the fallback, and a CASE with an ELSE. Anything else answers
    ``(None, None)`` rather than guessing what a value becomes when it is missing.
    """
    coalesce = coalesce_default(expression)
    if coalesce is not None:
        return coalesce, "COALESCE"
    node = parse_expression(expression)
    if node is None:
        return None, None
    for candidate in [node, *node.find_all(exp.Case)]:
        if isinstance(candidate, exp.Case) and candidate.args.get("default") is not None:
            return expression_text(candidate.args["default"]), "CASE_ELSE"
    return None, None


# The four unit words this view will ever publish, and the markers that earn them. A
# comment is matched literally -- no synonyms, no translation -- so a hint is always a
# quotation of something a person wrote, or the plain reading of a function.
UNIT_HINT_AMOUNT = "金额"
UNIT_HINT_COUNT = "笔数"
UNIT_HINT_DAYS = "天数"
UNIT_HINT_TIME = "时间"

# WI-2.1c item 1. A date difference has a unit the call itself states, and it is not the
# same word as "天数": `DATEDIFF` answers in days, `MONTHS_BETWEEN` in months and a
# difference of two `UNIX_TIMESTAMP` readings in seconds. They are separate constants
# rather than a reuse of `UNIT_HINT_DAYS`, because the hint here is the unit of a
# *measured interval*, which a reader converts, not a label copied from a comment.
UNIT_HINT_DAY = "天"
UNIT_HINT_MONTH = "月"
UNIT_HINT_SECOND = "秒"

UNIT_HINTS = (
    UNIT_HINT_AMOUNT,
    UNIT_HINT_COUNT,
    UNIT_HINT_DAYS,
    UNIT_HINT_TIME,
    UNIT_HINT_DAY,
    UNIT_HINT_MONTH,
    UNIT_HINT_SECOND,
)

_COMMENT_UNIT_MARKERS = (
    ("金额", UNIT_HINT_AMOUNT),
    ("元", UNIT_HINT_AMOUNT),
    ("笔数", UNIT_HINT_COUNT),
    ("次数", UNIT_HINT_COUNT),
    ("天", UNIT_HINT_DAYS),
    ("时间", UNIT_HINT_TIME),
)

_FUNCTION_UNIT_HINTS = {"COUNT": UNIT_HINT_COUNT}

# The two date-difference calls that name their own unit, and the aggregate wrappers a
# difference keeps its unit through: MAX / MIN / AVG / SUM of an interval is still an
# interval in the same unit, so the recursion stops being fooled by the wrapper.
_DIFFERENCE_UNIT_FUNCTIONS = {
    "DATEDIFF": UNIT_HINT_DAY,
    "MONTHS_BETWEEN": UNIT_HINT_MONTH,
}

_UNIT_TRANSPARENT_AGGREGATES = frozenset({"MAX", "MIN", "AVG", "SUM"})

_EPOCH_SECONDS_FUNCTION = "UNIX_TIMESTAMP"


def date_difference_unit(expression: str | None) -> str | None:
    """The unit of a date-difference expression, or None when it is not one.

    Only three shapes earn a word, and each states its own unit: ``DATEDIFF`` (days),
    ``MONTHS_BETWEEN`` (months) and ``UNIX_TIMESTAMP(a) - UNIX_TIMESTAMP(b)`` (seconds).
    The walk descends only through the aggregate wrappers above and through parentheses,
    so ``DATE_ADD(x, DATEDIFF(a, b))`` -- a date, not an interval -- earns nothing.
    """
    return _difference_unit(parse_expression(expression))


def _difference_unit(node: exp.Expression | None) -> str | None:
    node = _unwrap(node)
    if node is None:
        return None
    name = function_name(node)
    if name in _DIFFERENCE_UNIT_FUNCTIONS:
        return _DIFFERENCE_UNIT_FUNCTIONS[name]
    if isinstance(node, exp.AggFunc) and name in _UNIT_TRANSPARENT_AGGREGATES:
        return _difference_unit(node.this)
    if isinstance(node, exp.Sub) and all(
        function_name(_unwrap(side)) == _EPOCH_SECONDS_FUNCTION
        for side in (node.this, node.expression)
    ):
        return UNIT_HINT_SECOND
    return None

# MIN/MAX read as a time only when their argument is declared temporal, exactly as the
# aggregate gloss already decides it.
_SELECTIVE_TIME_FUNCTIONS = frozenset({"MAX", "MIN"})


def unit_hint(
    comments: Sequence[str | None],
    function: str | None,
    *,
    temporal_argument: bool = False,
    temporal_type: bool = False,
    expressions: Sequence[str | None] = (),
) -> tuple[str | None, str | None]:
    """``(hint, source)`` for a metric's unit, or ``(None, None)``.

    Sources in priority order: a comment a person wrote, the function's own reading, the
    declared type. Nothing else earns a hint -- a ``decimal`` column is not money and a
    ``bigint`` is not a count. ``expressions`` are the forms the value was written in
    (the projection and the aggregate's argument); a date difference among them states
    its unit as plainly as a function name does, so it is read at the function tier.
    """
    for comment in comments:
        for marker, hint in _COMMENT_UNIT_MARKERS:
            if comment and marker in str(comment):
                return hint, "comment"
    for expression in expressions:
        difference = date_difference_unit(expression)
        if difference:
            return difference, "function"
    name = str(function or "").upper()
    if name in _FUNCTION_UNIT_HINTS:
        return _FUNCTION_UNIT_HINTS[name], "function"
    if name in _SELECTIVE_TIME_FUNCTIONS and temporal_argument:
        return UNIT_HINT_TIME, "function"
    if temporal_type:
        return UNIT_HINT_TIME, "type"
    return None, None


# WI-2.1c item 2. The calls whose value is decided by *when the job runs* or by chance
# rather than by the data. sqlglot canonicalises the surface spellings onto these names
# -- a bare `UNIX_TIMESTAMP()` is rewritten to `UNIX_TIMESTAMP(CURRENT_TIMESTAMP())`, so
# the no-argument form is recognised by the `CURRENT_TIMESTAMP` it now carries while
# `UNIX_TIMESTAMP(col)` stays deterministic and is not listed.
NONDETERMINISTIC_FUNCTIONS = frozenset(
    {"CURRENT_TIMESTAMP", "CURRENT_DATE", "NOW", "RAND", "UUID"}
)


def nondeterministic_functions(expression: str | None) -> list[str]:
    """The run-time / random calls an expression makes, upper-cased and deduped.

    An expression sqlglot cannot parse answers with an empty list: "cannot tell" is not
    "contains one", and this feeds a finding that names fields by id.
    """
    node = parse_expression(expression)
    if node is None:
        return []
    found: list[str] = []
    for candidate in [node, *node.find_all(exp.Expression)]:
        name = function_name(candidate)
        if name in NONDETERMINISTIC_FUNCTIONS and name not in found:
            found.append(str(name))
    return found


# `yyyyMMdd` and `yyyy-MM-dd`, the only two spellings a day gap is computed from. A
# literal written any other way is reported as "不一致" without a number rather than
# being guessed at.
_GAP_DATE_FORMATS = ("%Y%m%d", "%Y-%m-%d")


def predicate_literal_days_between(left: str | None, right: str | None) -> int | None:
    """Whole days between the date literals two equality conjuncts pin, or None.

    None means the pair cannot be measured -- one side is not an equality against a
    literal, or a literal is not written as a plain day -- never that they agree.
    """
    offset = predicate_literal_day_offset(left, right)
    return None if offset is None else abs(offset)


def predicate_literal_day_offset(left: str | None, right: str | None) -> int | None:
    """Signed whole days from ``left``'s day to ``right``'s day, or None when unmeasured.

    Negative means the right-hand conjunct reads the *earlier* day, which is the shape a
    reader is actually asking about when two sides of one metric disagree: the reminder
    side takes the day before, and saying which way round it goes is a fact, not a
    complaint.
    """
    days = []
    for expression in (left, right):
        parsed = equality_conjunct(expression)
        value = _gap_date(parsed[1]) if parsed else None
        if value is None:
            return None
        days.append(value)
    return (days[1] - days[0]).days


def _gap_date(value: str | None) -> datetime.date | None:
    text = str(value or "").strip().strip("'\"")
    for pattern in _GAP_DATE_FORMATS:
        try:
            return datetime.datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


# How a join type reads in the 空值 line: the contract spells the type out, a reader
# writes it the way the SQL did. A type outside the map is printed as the contract has it.
JOIN_TYPE_LABELS = {"LEFT_OUTER": "LEFT", "RIGHT_OUTER": "RIGHT", "FULL_OUTER": "FULL"}

JOIN_SIDE_LABELS = {"right": "右侧", "left": "左侧"}


def describe_metric_subject(
    tables: Sequence[str], scope_id: str | None, argument_tables: Sequence[str] = ()
) -> str:
    """``<表>、<表> 的记录``; without a provable table, the scope that produced the rows.

    ``argument_tables`` is named separately because it answers a different question: the
    rows counted are still the driving ones, and only the value read off them came from
    somewhere else. Merging the two lists would claim a grain the statement never wrote.
    """
    named = [str(table) for table in tables if table]
    arguments = [str(table) for table in argument_tables if table]
    if not named:
        return f"{scope_id} 的输出行" if scope_id else "契约未给出统计对象"
    subject = f"{'、'.join(named)} 的记录"
    return f"{subject}，指标值取自 {'、'.join(arguments)}" if arguments else subject


def describe_nullable_argument(detail: Mapping | None) -> str | None:
    """``参数来自 LEFT JOIN 右侧（<scope>），关联不上时为空``, or None without a join."""
    if not detail:
        return None
    join_type = str(detail.get("join_type") or "")
    side = JOIN_SIDE_LABELS.get(str(detail.get("side")), "可空侧")
    label = JOIN_TYPE_LABELS.get(join_type, join_type or "OUTER")
    return f"参数来自 {label} JOIN {side}（{detail.get('scope_id')}），关联不上时为空"


def describe_metric_aggregation(
    function: str | None, argument: str | None, group_keys: Sequence[str]
) -> str:
    """``按 <keys> 汇总 <F(arg)>``; without keys the aggregation is over the whole set."""
    call = f"{function}({argument})" if function else "契约未给出聚合调用"
    keys = [str(item) for item in group_keys if item]
    head = f"按 {'、'.join(keys)} 汇总" if keys else "全表汇总"
    return f"{head} {call}"


def describe_inclusion(expression: str | None, where: str) -> str:
    """One inclusion condition, worded by where it sits rather than by what it means."""
    text = expression_text(parse_expression(expression)) or str(expression or "").strip()
    if not text:
        return "契约未给出条件原文"
    if where == "aggregate_case":
        return f"仅计 {text}"
    if where == "join_condition":
        return f"关联条件 {text}"
    return describe_filter(text)


def is_constant_label_case(expression: str | None) -> bool:
    """True when a CASE/IF returns a literal from every branch (a constant label set).

    It is the same parse the branch split already performs, asked a structural question
    instead of a wording one, so it lives beside it rather than being re-parsed by the
    profile builder.

    WI-2.1d item 3: the expression is unwrapped first, so ``CASE ... END AS band`` is
    read as the CASE it is rather than as an alias node that matches nothing, and a
    branch is constant through its sign -- ``ELSE -1`` is as fixed a label as ``ELSE 1``.
    A branch that returns a column or an expression still disqualifies the whole CASE:
    ``CASE WHEN x > 0 THEN 0 ELSE x END`` caps a number, and calling that a label set
    hides the measure it actually is.
    """
    node = _unwrap(parse_expression(expression))
    if isinstance(node, exp.Case):
        values = [condition.args.get("true") for condition in node.args.get("ifs") or []]
        values.append(node.args.get("default"))
    elif isinstance(node, exp.If):
        values = [node.args.get("true"), node.args.get("false")]
    else:
        return False
    present = [value for value in values if value is not None]
    return bool(present) and all(_is_scalar_constant(value) for value in present)


def describe_case(expression: str | None) -> str | None:
    """List the branches of a CASE as ``<条件> → <值>``, folding long ones."""
    split = split_case_branches(expression)
    if split is None:
        return None
    branches, otherwise = split
    rendered = [f"{item['when']} → {item['then']}" for item in branches]
    if len(rendered) > CASE_BRANCH_PREVIEW_LIMIT:
        preview = "；".join(rendered[:CASE_BRANCH_PREVIEW_COUNT])
        return f"{len(rendered)} 个分支，前 {CASE_BRANCH_PREVIEW_COUNT} 个：{preview}"
    if otherwise is not None:
        rendered.append(f"否则 {otherwise}")
    return "；".join(rendered)


# --------------------------------------------------------------------- functions


def _unwrap(node: exp.Expression | None) -> exp.Expression | None:
    """Drop the alias and parentheses a projection expression arrives wrapped in.

    ``(a - b) AS diff`` is the same computation as ``a - b``; the alias is the output
    column's name, which the profile already publishes, and keeping it here would make
    every aliased arithmetic expression fall outside the vocabulary.
    """
    while isinstance(node, (exp.Alias, exp.Paren)):
        node = node.this
    return node


def describe_function_expression(expression: str | None) -> str | None:
    """Restate an expression whose outermost function is in the glossary.

    An arithmetic expression has no function name to look up, so it is answered by node
    type instead -- including the ``COALESCE(a, 0) + COALESCE(b, 0)`` shape, whose
    outermost node is the operator and not the null fill.
    """
    node = _unwrap(parse_expression(expression))
    if node is None:
        return None
    if isinstance(node, _ARITHMETIC_NODES):
        return f"算术运算：{expression_text(node)}"
    name = function_name(node)
    kind = FUNCTION_GLOSSARY.get(name or "")
    if kind is None:
        return None
    renderers = {
        "null_fill": lambda node_: _describe_null_fill(node_, name or ""),
        "cast": _describe_cast,
        "concat": lambda _node: "拼接",
        "date": _describe_date,
        "text": lambda _node: f"文本规整（{name}）",
        "if": _describe_if,
        "round": lambda _node: f"取整（{name}）",
        "aggregate": _describe_aggregate_call,
        "regex": lambda _node: _REGEX_TEXT[str(name)],
        "pattern": lambda node_: f"模式匹配：{expression_text(node_)}",
        "json": lambda _node: f"JSON 解析（{name}）",
        "explode": lambda _node: f"拆分/展开（{name}）",
        "numeric": lambda _node: f"数值函数（{name}）",
    }
    return renderers[kind](node)


def _describe_null_fill(node: exp.Expression, name: str) -> str:
    """COALESCE-family fill, or the named form for the two that decide with a null."""
    if name in _NULL_DECIDING_FUNCTIONS:
        return f"空值处理（{name}）"
    arguments = _call_arguments(node)
    if not arguments:
        return "空值回填"
    return f"空值回填为 {expression_text(arguments[-1])}"


def _describe_date(node: exp.Expression) -> str:
    """The date family. ``DATEDIFF`` is named; everything else echoes its own call.

    WI-1f: ``日期运算：DATEDIFF(a, b)`` told a reader nothing they could not see, and the
    argument order of a date difference is exactly what they get wrong. sqlglot wraps
    each side in a ``TsOrDsToDate`` cast it inserted itself, so the sides are unwrapped
    back to what the SQL wrote before they are printed.
    """
    if not isinstance(node, exp.DateDiff):
        return f"日期运算：{expression_text(node)}"
    left = expression_text(_unwrap_date_cast(node.this))
    right = expression_text(_unwrap_date_cast(node.expression))
    if not left or not right:
        return f"日期运算：{expression_text(node)}"
    return f"日期差（天）：{left} − {right}"


def _unwrap_date_cast(node: exp.Expression | None) -> exp.Expression | None:
    while isinstance(node, (exp.TsOrDsToDate, exp.Paren)):
        node = node.this
    return node


def _describe_cast(node: exp.Expression) -> str:
    to = node.args.get("to")
    return f"转换为 {to.sql(dialect=DIALECT) if to is not None else '未知类型'}"


def _describe_if(node: exp.Expression) -> str:
    condition = expression_text(node.this)
    true_value = expression_text(node.args.get("true"))
    false_value = node.args.get("false")
    tail = f" 否则 {expression_text(false_value)}" if false_value is not None else ""
    return f"二值条件：{condition} 则 {true_value}{tail}"


# WI-1g item D3. A call's argument is restated once more so a nested computation stops
# being invisible: ``MAX(DATEDIFF(a, b))`` is a maximum *of a date difference*, and the
# outer gloss alone said only "最大值". Arithmetic is deliberately excluded -- "算术运算：
# a - b" repeats the call text the reader is already looking at and adds nothing.
_UNGLOSSED_ARGUMENT_NODES = (exp.Column, exp.Literal, exp.Star, exp.Null, exp.Boolean)


def nested_argument_text(argument: exp.Expression | None) -> str | None:
    """The restatement of one call argument, or None when it adds nothing.

    A bare column, a literal and an arithmetic expression are all fully visible in the
    call text itself, so they are not glossed; a glossary function inside the call is,
    because its meaning (which side of a date difference, which value fills the null) is
    exactly what the call text does not show.
    """
    if not isinstance(argument, exp.Expression):
        return None
    if isinstance(argument, _UNGLOSSED_ARGUMENT_NODES + _ARITHMETIC_NODES):
        return None
    return describe_function_expression(argument.sql(dialect=DIALECT))


def _with_nested(gloss: str, nested: str | None) -> str:
    """Merge the outer structural gloss and the argument's own restatement into one."""
    if not nested:
        return gloss
    if gloss.startswith("（") and gloss.endswith("）"):
        return f"（{gloss[1:-1]}；{nested}）"
    return f"（{nested}）"


def _call_arguments(node: exp.Expression) -> list[exp.Expression]:
    if isinstance(node, exp.Anonymous):
        return list(node.expressions or [])
    arguments = [node.this] if node.args.get("this") is not None else []
    for extra in node.args.get("expressions") or []:
        arguments.append(extra)
    return [item for item in arguments if isinstance(item, exp.Expression)]


# --------------------------------------------------------------------- aggregates


def _aggregate_parts(node: exp.Expression) -> tuple[str, str, exp.Expression | None]:
    """``(function name, "DISTINCT " or "", the single argument)`` of one aggregate call."""
    name = function_name(node) or "AGG"
    argument = node.this
    distinct = ""
    if isinstance(argument, exp.Distinct):
        argument = (argument.expressions or [None])[0]
        distinct = "DISTINCT "
    return name, distinct, argument


def _aggregate_gloss(
    name: str,
    distinct: str,
    argument: exp.Expression | None,
    column_types: Mapping[str, str] | None,
) -> str:
    """WI-1f: the parenthesised structural reading of a call, or "" when it has none.

    The call text itself is never replaced, so nothing is lost: the gloss only says
    which of two structural readings applies. MIN/MAX are a time only when the argument
    is a column the metadata declares temporal -- an undeclared column reads as the
    scalar form, because guessing from the name is exactly what R8 forbids.
    """
    if name == "COUNT":
        if argument is None or isinstance(argument, exp.Star):
            return "（行数）"
        return f"（去重计数 {expression_text(argument)}）" if distinct else ""
    if name not in _SCALAR_SELECTIVE_TEXT:
        return ""
    declared = ""
    if isinstance(argument, exp.Column) and column_types:
        declared = str(column_types.get(argument.name) or "").lower()
    if declared.startswith(_TEMPORAL_TYPE_PREFIXES):
        return f"（{_TEMPORAL_SELECTIVE_TEXT[name]}）"
    return f"（{_SCALAR_SELECTIVE_TEXT[name]}）"


def _describe_aggregate_call(
    node: exp.Expression, column_types: Mapping[str, str] | None = None
) -> str:
    """``SUM(x)`` / ``COUNT(DISTINCT x)`` / ``SUM(CASE ...)`` as one call phrase."""
    if isinstance(node, exp.Count) and isinstance(node.this, exp.Star):
        return "COUNT(*)（行数）"
    name, distinct, argument = _aggregate_parts(node)
    gloss = _with_nested(
        _aggregate_gloss(name, distinct, argument, column_types),
        nested_argument_text(argument),
    )
    if isinstance(argument, exp.Star):
        return f"{name}({distinct}*){gloss}"
    split = split_case_branches(argument.sql(dialect=DIALECT)) if argument else None
    if split is not None and len(split[0]) == 1:
        branches, otherwise = split
        tail = f"，否则计 {otherwise}" if otherwise is not None else ""
        return (
            f"{name}({distinct}{branches[0]['then']}){gloss}"
            f"，仅计 {branches[0]['when']}{tail}"
        )
    return f"{name}({distinct}{expression_text(argument)}){gloss}"


def describe_aggregate(
    expression: str | None,
    group_by_keys: Sequence[str],
    column_types: Mapping[str, str] | None = None,
) -> str:
    """``按 <keys> 聚合：<call>``; without keys the aggregation is over the whole set."""
    node = parse_expression(expression)
    call = (
        _describe_aggregate_call(node, column_types)
        if isinstance(node, exp.AggFunc)
        else expression_text(node) or str(expression or "")
    )
    if group_by_keys:
        return f"按 {'、'.join(group_by_keys)} 聚合：{call}"
    return f"全表聚合：{call}"


# --------------------------------------------------------------------- windows


def describe_window(expression: str | None) -> str | None:
    """``窗口函数 F()；按 <partition> 分组；按 <order+方向> 排序``."""
    node = parse_expression(expression)
    window = node if isinstance(node, exp.Window) else None
    if window is None and node is not None:
        window = next(iter(node.find_all(exp.Window)), None)
    if window is None:
        return None
    inner = window.this
    name = function_name(inner) or "WINDOW"
    items = _call_arguments(inner) if inner else []
    arguments = [expression_text(item) for item in items]
    call = f"{name}({', '.join(item for item in arguments if item)})"
    # WI-1g item D3: the window's own argument is restated once more, so a window over a
    # nested computation is not reduced to the bare call text.
    gloss = _with_nested("", nested_argument_text(items[0] if items else None))
    parts = [f"窗口函数 {call}{gloss}"]
    partition = [expression_text(item) for item in window.args.get("partition_by") or []]
    if partition:
        parts.append(f"按 {'、'.join(partition)} 分组")
    order = window.args.get("order")
    ordered = []
    for item in (order.expressions if order is not None else []) or []:
        direction = "DESC" if item.args.get("desc") else "ASC"
        ordered.append(f"{expression_text(item.this)} {direction}")
    if ordered:
        parts.append(f"按 {'、'.join(ordered)} 排序")
    return "；".join(parts)


# --------------------------------------------------------------------- simple shapes


def describe_constant(expression: str | None) -> str:
    return f"常量 {str(expression or '').strip()}"


# WI-1g item E4. ``generated_sources[]`` entries are ``{source_type, value, transform}``
# dicts; printing one straight into a sentence produced a Python repr. Only the two
# source types the contract emits get a word, and anything else keeps its raw value.
_GENERATED_SOURCE_LABELS = {"CONSTANT": "常量", "SYSTEM": "系统值"}


def generated_source_text(item) -> str:
    """One ``generated_sources[]`` entry as ``常量 'F_00'`` -- never a dict repr."""
    if not isinstance(item, Mapping):
        return str(item)
    value = str(item.get("value") or "").strip()
    label = _GENERATED_SOURCE_LABELS.get(str(item.get("source_type") or "").upper())
    if not label:
        return value or str(dict(item))
    return f"{label} {value}" if value else label


def describe_union(input_fields: Sequence[str]) -> str:
    fields = [str(item) for item in input_fields]
    if not fields:
        return "合并上游分支"
    return f"合并 {len(fields)} 个分支（来自 {'、'.join(fields)}）"


def describe_direct_projection(input_fields: Sequence[str]) -> str:
    fields = [str(item) for item in input_fields]
    if not fields:
        return "直接投影"
    return f"直接投影自 {'、'.join(fields)}"


def describe_distinct() -> str:
    return "对输出列去重（DISTINCT）"


def describe_lateral_view(lateral_view: dict) -> str:
    """Restate one ``scope_profile.steps[].logic.lateral_views[]`` entry verbatim."""
    expression = str(lateral_view.get("expression") or lateral_view.get("function") or "")
    outputs = [str(name) for name in lateral_view.get("output_columns") or []]
    parts = [f"展开 {expression}" if expression else "展开复杂类型"]
    if outputs:
        parts.append(f"产出列 {'、'.join(outputs)}")
    alias = lateral_view.get("alias")
    if alias:
        parts.append(f"别名 {alias}")
    return "，".join(parts)


# --------------------------------------------------------------------- stage actions


def describe_filter(expression: str | None, *, is_partition_filter: bool = False) -> str:
    """``只保留 <predicate> 的记录``, with the contract's partition verdict appended."""
    text = expression_text(parse_expression(expression)) or str(expression or "").strip()
    sentence = f"只保留 {text} 的记录" if text else "按条件过滤"
    return f"{sentence}（分区过滤）" if is_partition_filter else sentence


def describe_having(expression: str | None) -> str:
    text = expression_text(parse_expression(expression)) or str(expression or "").strip()
    return f"分组后只保留 {text} 的组" if text else "分组后按条件过滤"


def join_null_semantics(join_type: str | None) -> str | None:
    """WI-1f: what a JOIN of this type does to the rows it cannot match, or None.

    A structural fact of the join type alone, not of this statement, which is why it is
    one fixed sentence per type rather than something derived per document. The agent
    writing a business profile needs it for "what happens when the lookup misses", and
    the skeleton was the only place that could state it without guessing.
    """
    return JOIN_NULL_SEMANTICS.get(str(join_type or "").upper())


def join_key_text(pair: Mapping) -> str:
    """One key pair as a reader sees it: ``a.x = b.y``, or the column once when it is
    spelled the same on both sides.

    WI-1g item A2, and the same short form ``mapping.md``'s section 6 already uses, so a
    reader moving between the two documents reads one key the same way twice.
    """
    left, right = str(pair.get("left") or ""), str(pair.get("right") or "")
    if left and left.rpartition(".")[2] == right.rpartition(".")[2]:
        return left.rpartition(".")[2]
    return f"{left} = {right}"


def describe_join(
    join_type: str | None,
    right: str | None,
    key_pairs: Sequence[dict],
    extra_conditions: Sequence[str] = (),
) -> str:
    """``<JOIN 类型> 关联 <右侧>，键 <a = b>[，附加条件 …][，<空值语义>]``."""
    parts = [f"{join_type or 'JOIN'} 关联 {right or '未知上游'}"]
    keys = [join_key_text(pair) for pair in key_pairs]
    parts.append(f"键 {'、'.join(keys)}" if keys else "无可证明的连接键")
    extras = [str(item) for item in extra_conditions if item]
    if extras:
        parts.append(f"附加条件 {'、'.join(extras)}")
    null_semantics = join_null_semantics(join_type)
    if null_semantics:
        parts.append(null_semantics)
    return "，".join(parts)


def describe_aggregation(group_by_keys: Sequence[str], calls: Sequence[str]) -> str:
    """One summary line for a whole aggregating scope: its keys and its calls."""
    keys = [str(item) for item in group_by_keys]
    head = f"按 {'、'.join(keys)} 分组聚合" if keys else "全表聚合"
    rendered = [str(item) for item in calls if item]
    return f"{head}：{'、'.join(rendered)}" if rendered else head


def describe_aggregate_call(
    expression: str | None, column_types: Mapping[str, str] | None = None
) -> str:
    """``SUM(x)`` / ``COUNT(DISTINCT x)`` as one call phrase, qualifiers dropped.

    The stage-action form: unlike the chain-step form it does not unfold a CASE, because
    a stage line lists every call of the scope and one unfolded CASE per call would bury
    them. The WI-1f gloss is the same one, so the two forms cannot disagree.
    """
    node = parse_expression(expression)
    if not isinstance(node, exp.AggFunc):
        return expression_text(node) or str(expression or "")
    if isinstance(node, exp.Count) and isinstance(node.this, exp.Star):
        return "COUNT(*)（行数）"
    name, distinct, argument = _aggregate_parts(node)
    gloss = _with_nested(
        _aggregate_gloss(name, distinct, argument, column_types),
        nested_argument_text(argument),
    )
    if argument is None or isinstance(argument, exp.Star):
        return f"{name}({distinct}*){gloss}"
    return f"{name}({distinct}{expression_text(argument)}){gloss}"


# --------------------------------------------------------------- field summary (WI-1f)


UNKNOWN_COMMENT_TEXT = "（注释未知）"

NULLABLE_BY_JOIN_TEXT = "（关联未命中时为空）"

# WI-2.2. How an author's comment joins the summary sentence: as a labelled quotation at
# the end, never woven into the restatement. The label matters -- everything before it is
# derived from the contract, everything after it is what a person wrote, and a reader
# deciding whether to trust the line needs to see the seam.
SQL_COMMENT_PREFIX = "；注释："

# How many comments one sentence carries before it defers to `fields[].sql_comments`.
SUMMARY_COMMENT_LIMIT = 2

# The two step types that carry a value unchanged. A chain made only of these is a
# direct read however many scopes it crosses, so the summary says "直接取自 <table>.<col>"
# instead of listing eight "直接投影自 …" hops nobody reads.
PASS_THROUGH_STEP_TYPES = ("direct_projection", "union")

# How many steps and how many sources one sentence lists before it defers to the keys
# that hold them all. A summary is a sentence, not a second copy of ``derivation[]``:
# past these counts it stops mid-list, says how many there are, and names the key to
# read instead -- nothing is dropped silently, and no fact is cut in half.
SUMMARY_STEP_LIMIT = 3
SUMMARY_SOURCE_LIMIT = 3

# WI-1g item D1. UNION branches are parallel, not sequential: joining them with "再"
# ("正则替换，再正则替换，再 12 个分支") read as one pipeline that runs twice. They are
# grouped and numbered instead, and this is how many of them one sentence carries.
SUMMARY_BRANCH_LIMIT = 3


def source_note(table: str, column: str, comment: str | None, table_comment: str | None) -> str:
    """``<table>.<column>（<comment>）`` for the summary sentence -- no code spans.

    The summary is free text, so it deliberately carries no backticks: the qualified
    identifiers stay checkable in ``sources[]`` and in the markdown's own code spans,
    and a summary that quoted them would be scanned as if it were asserting catalog ids.
    A table comment is labelled as one, because printing it where a column comment goes
    would say the column means what the table means.
    """
    if comment:
        note = str(comment)
    elif table_comment:
        note = f"表：{table_comment}"
    else:
        note = "注释未知"
    return f"{table}.{column}（{note}）"


def describe_field_summary(
    *,
    target_comment: str | None,
    step_texts: Sequence[str],
    direct_notes: Sequence[str],
    source_notes: Sequence[str],
    expression: str | None,
    nullable_by_join: bool = False,
    branch_steps: Sequence[Mapping] = (),
) -> str:
    """One unlabelled sentence for one target field (WI-1f item 2, WI-1g item D1).

    ``<注释>：<加工>；来源 <来源清单>``. The processing half is the restated chain steps
    joined by "，再"; a chain that only carries the value becomes "直接取自 …", which
    already names the sources, so the tail is not repeated after it. A field with
    neither a chain nor a source falls back to its own expression, which is the most
    the contract proves about it.

    ``branch_steps`` holds the steps that happen *inside* UNION branches, one entry per
    branch (``{index, label, texts}``). They are alternatives, not stages, so they are
    numbered and separated rather than chained, and the steps above the union follow
    them as "合并后 …".
    """
    head = str(target_comment) if target_comment else UNKNOWN_COMMENT_TEXT
    sources = _bounded(source_notes, SUMMARY_SOURCE_LIMIT, "项，完整清单见 sources")
    tail = f"；来源 {sources}" if source_notes else ""
    if branch_steps:
        body = _branch_body(branch_steps, step_texts)
    elif step_texts:
        body = _bounded(
            step_texts, SUMMARY_STEP_LIMIT, "步，完整链路见 derivation", separator="，再"
        )
    elif direct_notes:
        body = f"直接取自 {_bounded(direct_notes, SUMMARY_SOURCE_LIMIT, '项，完整清单见 sources')}"
        tail = ""
    else:
        body = str(expression or "").strip() or "契约未给出加工链"
    sentence = f"{head}：{_normalize_inline(body)}{tail}"
    return f"{sentence}{NULLABLE_BY_JOIN_TEXT}" if nullable_by_join else sentence


def append_sql_comment(sentence: str, comments: Sequence[str]) -> str:
    """Append the author's own words to a restatement, verbatim and labelled.

    Nothing here interprets the text: it is normalized to one line (the summary is one
    line by contract) and otherwise copied. A comment is not evidence about the data and
    must not read as though this view derived it.
    """
    quoted = [_normalize_inline(str(item)) for item in comments if str(item).strip()]
    if not quoted:
        return sentence
    body = _bounded(quoted, SUMMARY_COMMENT_LIMIT, "条，完整清单见 sql_comments")
    return f"{sentence}{SQL_COMMENT_PREFIX}{body}"


def _branch_body(branch_steps: Sequence[Mapping], step_texts: Sequence[str]) -> str:
    """``分支 1（来自 A）：…；分支 2（来自 B）：…；合并后 …`` (WI-1g item D1)."""
    rendered = [
        f"分支 {item.get('index')}（来自 {item.get('label')}）："
        + "，再".join(str(text) for text in item.get("texts") or [])
        for item in branch_steps
    ]
    body = _bounded(
        rendered, SUMMARY_BRANCH_LIMIT, "个分支，完整链路见 derivation", separator="；"
    )
    if not step_texts:
        return body
    merged = _bounded(
        step_texts, SUMMARY_STEP_LIMIT, "步，完整链路见 derivation", separator="，再"
    )
    return f"{body}；合并后 {merged}"


def _bounded(items: Sequence[str], limit: int, overflow: str, separator: str = "、") -> str:
    """The first ``limit`` items, then how many there are in total and where to read them."""
    rendered = [str(item) for item in items]
    if len(rendered) <= limit:
        return separator.join(rendered)
    return (
        separator.join(rendered[:limit]) + f"（共 {len(rendered)} {overflow}）"
    )


# --------------------------------------------------------------------- window intent


# R6's vocabulary, as the one sentence each intent adds to the window action. The
# wording is structural on purpose: "每组保留最新一条" states what the SQL does, not
# what the row means to a business.
WINDOW_INTENT_TEXT = {
    "keep_latest_per_group": "每组保留最新一条",
    "keep_first_per_group": "每组保留第一条",
    "rank_within_group": "仅组内排名，未见 = 1 过滤",
    "pick_first_in_group": "取组内首值",
    "pick_last_in_group": "取组内末值",
    "adjacent_row_offset": "取相邻行的值",
    "running_aggregate": "组内累计聚合",
    "other": "窗口计算",
}

_DIRECTION_TEXT = {"DESC": "降序", "ASC": "升序"}

# The ranking family, shared by the intent rule (R6) and by the sentence below.
RANKING_WINDOW_FUNCTIONS = frozenset({"row_number", "rank", "dense_rank"})


def describe_window_action(
    *,
    window_function: str,
    output_field: str | None,
    partition_labels: Sequence[str],
    order_labels: Sequence[tuple[str, str | None]],
    intent: str,
    consumer_scope: str | None = None,
) -> str:
    """``按 <partition> 分组，按 <order> 降序编号（rn）；<scope> 以 rn = 1 消费，即…``."""
    ranking = window_function.lower() in RANKING_WINDOW_FUNCTIONS
    parts = [
        f"按 {'、'.join(str(item) for item in partition_labels)} 分组"
        if partition_labels
        else "全表窗口"
    ]
    verb = "编号" if ranking else f"计算 {window_function.upper()}"
    if order_labels:
        direction = _DIRECTION_TEXT.get(str(order_labels[0][1] or "ASC").upper(), "升序")
        columns = "、".join(str(column) for column, _ in order_labels)
        parts.append(f"按 {columns} {direction}{verb}")
    else:
        parts.append(verb)
    if output_field:
        parts[-1] = f"{parts[-1]}（{output_field}）"
    head = "，".join(parts)
    meaning = WINDOW_INTENT_TEXT.get(intent, WINDOW_INTENT_TEXT["other"])
    if consumer_scope and output_field:
        return f"{head}；{consumer_scope} 以 {output_field} = 1 消费，即{meaning}"
    return f"{head}；{meaning}"


# --------------------------------------------------------------------- dispatcher


def describe_step(
    step_type: str,
    expression: str | None,
    *,
    group_by_keys: Iterable[str] = (),
    input_fields: Iterable[str] = (),
    has_udf: bool = False,
    column_types: Mapping[str, str] | None = None,
) -> str | None:
    """Restate one ``field_mapping_chains[].ordered_steps[]`` entry.

    Returns None when the step's expression falls outside the vocabulary; the caller
    keeps the raw expression instead. A UDF anywhere in the step makes the step a black
    box, which is said out loud either way.
    """
    keys = list(group_by_keys)
    inputs = list(input_fields)
    builders = {
        "aggregate": lambda: describe_aggregate(expression, keys, column_types),
        "case_when": lambda: describe_case(expression),
        "window": lambda: describe_window(expression),
        "constant": lambda: describe_constant(expression),
        "union": lambda: describe_union(inputs),
        "direct_projection": lambda: describe_direct_projection(inputs),
        "expression": lambda: describe_function_expression(expression),
    }
    text = builders.get(str(step_type), lambda: None)()
    if not has_udf:
        return text
    return UDF_MARKER if text is None else f"{text}；{UDF_MARKER}"
