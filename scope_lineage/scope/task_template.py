"""Parse a task's scheduling template, binding only the parameters that name tables.

A task export may carry the script as the scheduler stores it (``meta.task_sql``, with
``${name}`` parameters) beside the parameter list (``meta.task_parameters``). A run
instance (``meta.sql``) has every parameter replaced, so a value the scheduler filled in
reads exactly like a constant the author wrote. The template keeps them apart -- but a
parameter in a table name (``cat.${db}.t``) names no real table, which the parse reports
as incomplete input.

So the template is parsed as written, and only a parameter the **parser** finds in a
table id (:func:`~.parser.unbound_table_parameters` over the parsed tables, not a guess
over text positions) is bound, one at a time:

1. its value must be a plain identifier (``^[A-Za-z_][A-Za-z0-9_]*$``); a value with a
   dot, all digits, or missing is left alone;
2. ``${name}`` is replaced on the **token stream** -- outside string literals and
   comments, inside backtick-quoted names too -- so the same parameter in a string or a
   comment is never touched;
3. the script is parsed again, and the binding is kept only when every table id that held
   the parameter now appears with the value in its place, and the syntax status is no
   worse than before. Otherwise it is undone and the parameter is reported as today
   (``input_incomplete``). A reserved word as the value (``select``) is what this stops:
   the parse degrades or the table drops out of the lineage.

Parameter names are case-sensitive. A parameter used both in a table name and bare
elsewhere (not in a string) is replaced in both places: the binding works on the
parameter, not on the position. What was done is disclosed as one ``warnings[]`` entry of
type :data:`TEMPLATE_WARNING`, with the count of places each bound parameter replaced.
"""

from __future__ import annotations

import re
from typing import Mapping

import sqlglot
from sqlglot.errors import SqlglotError
from sqlglot.tokens import Token, TokenType

from ..table_identity import canonical_table_name
from ._constants import DIALECT
from .parser import unbound_table_parameters
from .task_lineage import TaskLineageResult, parse_task_lineage

__all__ = [
    "IDENTIFIER_VALUE",
    "TEMPLATE_WARNING",
    "bound_parameters",
    "parse_task_template",
    "substitute_parameters",
]

TEMPLATE_WARNING = "task_template_sql_used"
IDENTIFIER_VALUE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SYNTAX_RANK = {"strict_ok": 0, "recovered": 1}


def _parameter_group(tokens: list[Token], index: int) -> str | None:
    """The name of a ``${name}`` group written without gaps at ``index``, else None."""
    if index + 4 > len(tokens):
        return None
    dollar, brace, name, close = tokens[index : index + 4]
    if (
        dollar.token_type == TokenType.PARAMETER
        and brace.token_type == TokenType.L_BRACE
        and close.token_type == TokenType.R_BRACE
        and re.fullmatch(r"\w+", name.text)
        and dollar.end + 1 == brace.start
        and brace.end + 1 == name.start
        and name.end + 1 == close.start
    ):
        return name.text
    return None


def _spans(sql: str, name: str) -> list[tuple[int, int]]:
    """``(start, end)`` of every ``${name}`` outside strings and comments, in order."""
    try:
        tokens = sqlglot.tokenize(sql, dialect=DIALECT)
    except SqlglotError:
        return []
    slot = "${" + name + "}"
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if _parameter_group(tokens, index) == name:
            spans.append((token.start, tokens[index + 3].end + 1))
            index += 4
            continue
        if token.token_type == TokenType.IDENTIFIER:
            # A backtick-quoted name: the token's text is the inside, its span the quotes too.
            raw = sql[token.start : token.end + 1]
            spans.extend(
                (token.start + found.start(), token.start + found.end())
                for found in re.finditer(re.escape(slot), raw)
            )
        index += 1
    return spans


def substitute_parameters(sql: str, values: Mapping[str, str]) -> tuple[str, dict[str, int]]:
    """``(sql with each ${name} of values replaced, places replaced per name)``.

    Strings and comments are left as written. Names are replaced one after another, in
    the order ``values`` gives them -- the order :func:`parse_task_template` bound them.
    """
    counts: dict[str, int] = {}
    for name, value in values.items():
        spans = _spans(sql, name)
        if not spans:
            continue
        pieces, position = [], 0
        for start, end in spans:
            pieces += [sql[position:start], value]
            position = end
        pieces.append(sql[position:])
        sql = "".join(pieces)
        counts[name] = len(spans)
    return sql, counts


def _table_ids(result: TaskLineageResult) -> list[str]:
    """Every table id the statements write or read, in statement order -- the ids
    ``input_incomplete`` is reported from."""
    tables: dict[str, None] = {}
    for lineage in result.statement_lineage.values():
        if isinstance(lineage, Mapping):
            tables[str(lineage.get("target_table") or "")] = None
            tables.update(dict.fromkeys(str(table) for table in lineage.get("source_tables") or []))
    tables.pop("", None)
    return list(tables)


def _named_tables(result: TaskLineageResult) -> set[str]:
    return set(_table_ids(result))


def _table_parameters(result: TaskLineageResult) -> list[str]:
    """The parameters the parsed table ids hold, in order of first appearance."""
    names: dict[str, None] = {}
    for table in _table_ids(result):
        names.update(dict.fromkeys(unbound_table_parameters(table)))
    return list(names)


def _bound_cleanly(before: TaskLineageResult, after: TaskLineageResult, name: str, value: str) -> bool:
    """Every table that held ``${name}`` is still there under the value; syntax no worse."""
    slot = "${" + name + "}"
    held = [table for table in _named_tables(before) if slot in table]
    present = _named_tables(after)
    if not held or any(canonical_table_name(table.replace(slot, value)) not in present for table in held):
        return False
    return _SYNTAX_RANK.get(after.syntax_status, 2) <= _SYNTAX_RANK.get(before.syntax_status, 2)


def bound_parameters(warnings) -> dict[str, int] | None:
    """The ``{name: places}`` a template disclosure states; None when no template was parsed."""
    for warning in warnings or []:
        if isinstance(warning, Mapping) and warning.get("type") == TEMPLATE_WARNING:
            bound = warning.get("bound_parameters") or {}
            return {str(name): int(count) for name, count in bound.items()}
    return None


def _disclosure(bound: dict[str, int]) -> dict:
    said = ", ".join(f"${{{name}}} x{count}" for name, count in bound.items())
    return {
        "type": TEMPLATE_WARNING,
        "scope": "TASK",
        "msg": (
            "parsed the task's template SQL (meta.task_sql), not the run instance (meta.sql); "
            + (f"table-name parameters bound from meta.task_parameters: {said}" if bound
               else "no table-name parameter was bound")
        ),
        "bound_parameters": dict(bound),
    }


def parse_task_template(
    sql: str, parameters: Mapping[str, str] | None = None, **options
) -> tuple[TaskLineageResult, str]:
    """``(the task's lineage, the SQL it was parsed from)`` for a scheduling template.

    ``parameters`` maps a parameter name to its definition as the task export gives it;
    ``options`` are :func:`~.task_lineage.parse_task_lineage`'s. The returned SQL is the
    template with the bound table-name parameters replaced -- the text the lineage was
    built from.
    """
    values = dict(parameters or {})
    result = parse_task_lineage(sql, **options)
    bound: dict[str, int] = {}
    for name in _table_parameters(result):
        value = values.get(name)
        if not isinstance(value, str) or not IDENTIFIER_VALUE.match(value):
            continue
        candidate, counts = substitute_parameters(sql, {name: value})
        if not counts:
            continue
        trial = parse_task_lineage(candidate, **options)
        if _bound_cleanly(result, trial, name, value):
            sql, result, bound[name] = candidate, trial, counts[name]
    result.diagnostics["warnings"].insert(0, _disclosure(bound))
    return result, sql
