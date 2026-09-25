"""The packet facts the meaning checks (10-13) read, beside the ones checks 1-9 read.

- :func:`join_facts` -- a JOIN's right side, the names a writer may call it by, and the
  fan-out verdict the semantic profile already reached for it (``fan_out_risks``); a JOIN
  on no path the profile walked has no verdict (``None``), because nothing proves its rows
  reach the output;
- :func:`case_outputs` -- the literal values a CASE / IF column can take, and which source
  values each one gathers;
- :func:`header_facts` -- the lifecycle and data volume a script's header comment states.

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

_PASS_THROUGH = frozenset({"direct_projection", "union"})


def code_expression(field: dict):
    """The expression that last computed a field: a projection passes values on unchanged.

    A CASE written in a subquery reaches the target through ``latest.status``; the field's
    own expression is that projection, its derivation's last computing step is the CASE.
    """
    for step in reversed(field.get("derivation") or []):
        if str(step.get("step_type")) not in _PASS_THROUGH:
            return step.get("expression")
    return field.get("expression")


def case_outputs(expression) -> list[dict]:
    """``[{value, when, source_values, catch_all}]`` per literal a CASE / IF can return.

    Only for an expression that is one CASE or IF whose every output is a literal (NULL
    aside): a branch that computes its value makes the column a measure or a pass-through,
    not a code. ``source_values`` are the literals the branch conditions compare the
    source with (``x = 1``, ``x IN (1, 2)``, ``OR`` of those), ``None`` when a condition is
    anything else; ``catch_all`` marks the value the ELSE returns.
    """
    tree = _parse(expression)
    branches = _branches(tree) if tree is not None else []
    if not branches or not all(_literal(value) is not None or isinstance(value, exp.Null)
                               for _, value in branches):
        return []
    outputs: dict[str, dict] = {}
    for condition, value in branches:
        literal = _literal(value)
        if literal is None:
            continue
        entry = outputs.setdefault(
            literal, {"value": literal, "when": [], "source_values": [], "catch_all": False})
        _add_branch(entry, condition)
    return list(outputs.values())


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
    if isinstance(node, exp.Boolean):
        return "true" if node.this else "false"
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


def header_facts(header_comments, sql) -> dict:
    """``{lifecycle, volume}`` a script's header comment states, each ``None`` when silent.

    Read from the header the lineage published and from the comment lines that open the
    script, up to its first statement other than ``SET``: a header block written above a
    ``WITH`` is attached to the write itself and never reaches ``header_comments``.
    """
    lines = [str(line) for line in header_comments or []] + _leading_comments(sql)
    return {"lifecycle": _first(_LIFECYCLE, lines), "volume": _first(_VOLUME, lines)}


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
