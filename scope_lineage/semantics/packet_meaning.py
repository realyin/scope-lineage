"""The packet facts the meaning checks (10-13) read, beside the ones checks 1-9 read.

- :func:`join_facts` -- a JOIN's right side, the names a writer may call it by, and the
  fan-out verdict the semantic profile already reached for it (``fan_out_risks``); a JOIN
  on no path the profile walked has no verdict (``None``), because nothing proves its rows
  reach the output;
- :func:`case_outputs` -- the literal values a CASE / IF column can take, and which source
  values each one gathers;
- :func:`literal_outputs` -- the literals a column's SQL writes out (``''``, a constant,
  a literal NULL), and whether it writes nothing else;
- :func:`header_facts` -- the lifecycle and data volume a script's header comment states,
  and which table of the task the header describes when it is another one;
- :func:`producer_header` -- what an input's producing task says of the table in its
  header: primary key, storage, partitioning, lifecycle, volume (the author's claim).

Nothing here judges a document; the checks do.
"""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from .names import bare_table
from .sql_forms import DIALECT

_PARSE_ERRORS = (SqlglotError, ValueError, RecursionError)
_CONDITIONAL = re.compile(r"\b(case|if)\b", re.IGNORECASE)

# ------------------------------------------------------------------ joins


def join_facts(statement: dict, rule: dict) -> dict:
    """``{right, right_aliases, right_tables, fan_out}`` for one profile JOIN rule."""
    right = str(rule.get("right_input") or "")
    inputs = {bare_table(item.get("table")) for item in statement.get("inputs") or []}
    physical = bare_table(right) in inputs
    risks = (statement.get("output_shape") or {}).get("fan_out_risks") or []
    risk = next((r for r in risks if r.get("logic_block_id") == rule.get("evidence")), None)
    return {
        "right": bare_table(right) if physical else right,
        "right_aliases": _aliases(rule, right, physical),
        "right_tables": [bare_table(right)] if physical else _scope_tables(statement, right),
        "fan_out": {key: risk.get(key) for key in ("status", "reason", "path")} if risk else None,
    }


def _aliases(rule: dict, right: str, physical: bool) -> list[str]:
    names = [
        str(pair.get("right")).rsplit(".", 1)[0]
        for pair in rule.get("key_pairs") or []
        if "." in str(pair.get("right") or "")
    ]
    if not physical and ":" in right:
        names.append(right.split(":", 1)[1])
    return list(dict.fromkeys(name for name in names if name))


def _scope_tables(statement: dict, scope: str) -> list[str]:
    for stage in statement.get("stages") or []:
        if stage.get("scope_id") == scope:
            return sorted({bare_table(t) for t in stage.get("upstream_physical_tables") or []})
    return []


# ------------------------------------------------------------------ CASE outputs

PASS_THROUGH_STEPS = frozenset({"direct_projection", "union"})


def code_expression(field: dict):
    """The expression that last computed a field: a projection passes values on unchanged.

    A CASE written in a subquery reaches the target through ``latest.status``; the field's
    own expression is that projection, its derivation's last computing step is the CASE.
    """
    for step in reversed(field.get("derivation") or []):
        if str(step.get("step_type")) not in PASS_THROUGH_STEPS:
            return step.get("expression")
    return field.get("expression")


def case_outputs(expression) -> list[dict]:
    """``[{value, when, source_values, catch_all}]`` per literal a CASE / IF can return.

    Only for an expression that is one CASE or IF whose every branch returns a string or
    number literal (NULL and ``''`` aside, which say "no value"): a branch that computes
    its value makes the column a measure or a pass-through, and a TRUE / FALSE flag is a
    boolean, not a code. ``source_values`` are the literals the branch conditions compare
    the source with (``x = 1``, ``x IN (1, 2)``, ``OR`` of those), ``None`` when a
    condition is anything else; ``catch_all`` marks the value the ELSE returns.

    An ELSE that computes its value (``… ELSE x END``) is read the way the glossary reads
    the same CASE (WI-C): the string branches are still values somebody chose and are
    listed -- as an open set, the ELSE supplies the rest -- while a number branch is a
    computation default (``WHEN g > 0 THEN 0 ELSE g``), not a code, and is dropped. Each
    output then carries ``else``: ``source`` when the ELSE passes on a column the branches
    compare (as is, CAST, or COALESCE with a literal), ``computed`` for anything else.
    """
    tree = _parse(expression)
    branches = _branches(tree) if tree is not None else []
    if not branches or not all(_constant(value) for condition, value in branches
                               if condition is not None):
        return []
    otherwise = next((value for condition, value in branches if condition is None), None)
    computed = otherwise is not None and not _constant(otherwise)
    kind = _else_kind(otherwise, [c for c, _ in branches if c is not None]) if computed else None
    outputs: dict[str, dict] = {}
    for condition, value in branches:
        literal = _literal(value)
        if not literal or (computed and _is_number(value)):
            continue
        entry = outputs.setdefault(
            literal, {"value": literal, "when": [], "source_values": [], "catch_all": False})
        _add_branch(entry, condition)
        if kind:
            entry["else"] = kind
    return list(outputs.values())


def _constant(node) -> bool:
    return _literal(node) is not None or isinstance(node, exp.Null)


def _is_number(node) -> bool:
    """A number literal, sign included; ``'0'`` is a string and is not."""
    while isinstance(node, (exp.Paren, exp.Neg)):
        node = node.this
    return isinstance(node, exp.Literal) and not node.args.get("is_string")


def _else_kind(otherwise, conditions: list) -> str:
    """``source`` when a computed ELSE hands on a column the branch conditions compare."""
    node = otherwise
    while True:
        if isinstance(node, (exp.Paren, exp.Cast)):  # TryCast is a Cast
            node = node.this
        elif isinstance(node, exp.Coalesce) and all(
                _constant(item) for item in node.expressions):
            node = node.this
        else:
            break
    if not isinstance(node, exp.Column):
        return "computed"
    compared = [column for condition in conditions for column in _compared_columns(condition)]
    return "source" if any(_same_column(node, column) for column in compared) else "computed"


def _compared_columns(condition) -> list:
    """The columns a branch condition compares with a literal (``=`` or ``IN``)."""
    found = []
    for node in condition.find_all(exp.EQ, exp.In):
        if isinstance(node, exp.In):
            sides = [node.this] if all(_literal(i) is not None for i in node.expressions) else []
        else:
            pair = (node.this, node.expression)
            sides = [a for a, b in (pair, pair[::-1]) if _literal(b) is not None]
        found += [side for side in sides if isinstance(side, exp.Column)]
    return found


def _same_column(left, right) -> bool:
    if left.name.lower() != right.name.lower():
        return False
    tables = (left.table.lower(), right.table.lower())
    return tables[0] == tables[1] or not all(tables)


def _parse(expression):
    if not expression or not _CONDITIONAL.search(str(expression)):
        return None
    try:
        return sqlglot.parse_one(str(expression), read=DIALECT)
    except _PARSE_ERRORS:
        return None


def _branches(tree) -> list[tuple]:
    """``[(condition or None for ELSE, output)]`` of a top-level CASE or IF."""
    node = tree.unalias() if isinstance(tree, exp.Alias) else tree
    if isinstance(node, exp.If):
        pairs = [(node.this, node.args.get("true")), (None, node.args.get("false"))]
    elif isinstance(node, exp.Case):
        subject = node.this
        pairs = [
            (exp.EQ(this=subject.copy(), expression=branch.this) if subject else branch.this,
             branch.args.get("true"))
            for branch in node.args.get("ifs") or []
        ] + [(None, node.args.get("default"))]
    else:
        return []
    return [(condition, value) for condition, value in pairs if value is not None]


def _add_branch(entry: dict, condition) -> None:
    if condition is None:
        entry["when"].append("ELSE")
        entry["catch_all"] = True
        return
    entry["when"].append(condition.sql(dialect=DIALECT))
    values = _compared_values(condition)
    if values is None or entry["source_values"] is None:
        entry["source_values"] = None
    else:
        entry["source_values"] += [v for v in values if v not in entry["source_values"]]


def _compared_values(condition) -> list[str] | None:
    if isinstance(condition, exp.Paren):
        return _compared_values(condition.this)
    if isinstance(condition, exp.Or):
        left, right = _compared_values(condition.this), _compared_values(condition.expression)
        return None if left is None or right is None else left + right
    if isinstance(condition, exp.EQ):
        found = [_literal(side) for side in (condition.this, condition.expression)]
        literals = [value for value in found if value is not None]
        return literals if len(literals) == 1 else None
    if isinstance(condition, exp.In) and condition.expressions:
        values = [_literal(item) for item in condition.expressions]
        return None if None in values else values
    return None


def _literal(node) -> str | None:
    if isinstance(node, exp.Paren):
        return _literal(node.this)
    if isinstance(node, exp.Neg):
        inner = _literal(node.this)
        return None if inner is None else f"-{inner}"
    if isinstance(node, exp.Literal):
        return str(node.this)
    return None


# ------------------------------------------------------------------ literal outputs

# A scope the contract names for one branch of a UNION (`union:main:b01`): the last step of
# that branch's part of a field's derivation.
_BRANCH_SCOPE = re.compile(r"^union:.+:b\d+$")


def literal_outputs(field: dict) -> tuple[list[str], bool]:
    """``(literals, constant_only)``: what a field's SQL writes as literals (B-V1 / V5).

    A field's derivation lists each UNION branch's steps in turn, a branch's ending at
    its ``union:…:bNN`` scope, then the steps above the union. The step that decides
    what a branch writes is its last computing one; when a step above the union computes,
    that step decides for all. Its literals are written out when only pass-throughs
    follow (:data:`PASS_THROUGH_STEPS`): a constant (``''``, ``'web'``, ``NULL``), the
    fallback a COALESCE / NVL ends in, the literal outputs of a CASE / IF. Literals in a
    condition are no output, and a NULL a LEFT JOIN brings is ``nullable_by_join``'s.

    ``constant_only`` is true when every branch's deciding step is a constant: the
    literals are then all the column holds. An inline VALUES column (one constant step
    standing for a list) is no single literal.
    """
    segments, current = [], []
    for step in field.get("derivation") or []:
        current.append(step)
        if _BRANCH_SCOPE.match(str(step.get("scope_id") or "")):
            segments.append(current)
            current = []
    above = _deciding_step(current)
    deciding = [above] if above is not None or not segments else [
        _deciding_step(segment) for segment in segments]
    literals: list[str] = []
    constant_only = bool(deciding)
    for step in deciding:
        found, constant = _step_literals(step) if step is not None else ([], False)
        literals += [value for value in found if value not in literals]
        constant_only = constant_only and constant
    return literals, constant_only and bool(literals)


def _deciding_step(steps: list[dict]) -> dict | None:
    return next((step for step in reversed(steps)
                 if str(step.get("step_type")) not in PASS_THROUGH_STEPS), None)


def _step_literals(step: dict) -> tuple[list[str], bool]:
    """``(literals the step writes, whether it writes nothing else)``."""
    text = str(step.get("expression") or "").strip()
    if not text or (str(step.get("step_type")) == "constant" and text.startswith("(")):
        return [], False
    try:
        node = sqlglot.parse_one(text, read=DIALECT)
    except _PARSE_ERRORS:
        return [], False
    node = _bare(node)
    single = _literal_sql(node)
    if single is not None:
        return [single], True
    if isinstance(node, exp.Coalesce):
        last = _literal_sql(_bare(([node.this] + list(node.expressions))[-1]))
        return ([last] if last is not None else []), False
    outputs = [_literal_sql(_bare(value)) for _condition, value in _branches(node)]
    return [value for value in outputs if value is not None], False


def _bare(node):
    while isinstance(node, (exp.Paren, exp.Alias)) or (
            isinstance(node, exp.Cast) and _literal_sql(node.this) is not None):
        node = node.this
    return node


def _literal_sql(node) -> str | None:
    """A literal in SQL spelling (``'x'``, ``''``, ``0``, ``-1``, ``NULL``), else None."""
    if isinstance(node, exp.Null):
        return "NULL"
    if isinstance(node, exp.Neg) and isinstance(node.this, exp.Literal) and not node.this.is_string:
        return node.sql(dialect=DIALECT)
    if isinstance(node, exp.Literal):
        return node.sql(dialect=DIALECT)
    return None


# ------------------------------------------------------------------ header


_LIFECYCLE = re.compile(
    r"(?:生命周期|保留(?:期|时间|天数|周期)?|保存(?:期|时间|天数)|lifecycle)\s*[:：=]?\s*"
    r"(\d+\s*(?:天|日|个月|月|年|days?)?|永久|永远)",
    re.IGNORECASE,
)
_VOLUME = re.compile(
    r"(?:数据规模|数据量|数据条数|数据行数|记录数)\s*[:：=]?\s*约?\s*"
    r"(\d[\d.,]*\s*(?:万|亿|千|百万|千万|[wWkKmM])?\s*(?:条|行)?)"
)
_WRITE = re.compile(r"^\s*(?!set\b)[a-z(]", re.IGNORECASE)


def header_facts(header_comments, sql, table: str = "", written=()) -> dict:
    """``{lifecycle, volume}`` a script's header comment states, each ``None`` when silent.

    Read from the header the lineage published and from the comment lines that open the
    script, up to its first statement other than ``SET``: a header block written above a
    ``WITH`` is attached to the write itself and never reaches ``header_comments``.

    A task writing several tables has one header; when it names (``库表名 x``) another
    table the task writes (``written``), the facts are about that table and ``about``
    names it. A header naming a table the task does not write (an old name) is kept as
    this table's.
    """
    lines = [str(line) for line in header_comments or []] + _leading_comments(sql)
    facts = {"lifecycle": _first(_LIFECYCLE, lines), "volume": _first(_VOLUME, lines)}
    about = header_about(lines, table, written)
    if about:
        facts["about"] = about
    return facts


_NAMED = re.compile(r"^[\s\-/*]*(?:库表名|表名)\s*[:：=]?\s*([A-Za-z0-9_.`]+)")
_PRODUCER_FACTS = (
    ("primary_key", re.compile(r"^[\s\-/*]*主键\s*[:：=]?\s*(.+?)\s*(?:\*/)?\s*$")),
    ("storage", re.compile(r"^[\s\-/*]*存储设计\s*[:：=]?\s*(.+?)\s*(?:\*/)?\s*$")),
    ("partition_design", re.compile(r"^[\s\-/*]*分区设计\s*[:：=]?\s*(.+?)\s*(?:\*/)?\s*$")),
)


def header_about(lines: list[str], table: str, written) -> str | None:
    """The other table of the task a header names, or ``None`` when it is about ``table``."""
    named = next((m.group(1) for m in map(_NAMED.match, lines) if m), None)
    if not named or not table:
        return None
    named = bare_table(named)
    for other in written:
        same = other == named or ("." not in named and other.rsplit(".", 1)[-1] == named)
        if same:
            return None if other == table else other
    return None


def producer_header(task: str, sql, table: str, written) -> dict | None:
    """``{task, primary_key?, storage?, partition_design?, lifecycle?, volume?}`` or None.

    What the producing task's own header says -- the author's claim, not a SQL fact.
    Nothing when the header describes another table the task writes, or says none of it.
    """
    lines = _leading_comments(sql)
    if header_about(lines, table, written):
        return None
    stated = {key: next((m.group(1) for m in map(pattern.match, lines) if m), None)
              for key, pattern in _PRODUCER_FACTS}
    stated["lifecycle"], stated["volume"] = _first(_LIFECYCLE, lines), _first(_VOLUME, lines)
    stated = {key: value for key, value in stated.items() if value}
    return {"task": task, **stated} if stated else None


def _leading_comments(sql) -> list[str]:
    lines, in_block = [], False
    for line in str(sql or "").splitlines():
        text = line.strip()
        if in_block or text.startswith("/*"):
            in_block = "*/" not in text
            lines.append(text)
        elif text.startswith("--"):
            lines.append(text.lstrip("-"))
        elif text and _WRITE.match(text):
            break
    return lines


def _first(pattern, lines: list[str]) -> str | None:
    for line in lines:
        match = pattern.search(line)
        if match:
            return re.sub(r"\s+", "", match.group(1))
    return None
