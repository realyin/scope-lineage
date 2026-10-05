"""The literal rows of an inline VALUES list, for a proof that reads them (#21-c).

A JOIN onto an inline dictionary (``SELECT * FROM VALUES ('A', '1'), ('A', '2') AS
t(kind, code)``) cannot duplicate a left row when the dictionary's rows differ on the
join key -- and since the rows are literals in the SQL, that is a fact the SQL states,
not a guess. The contract keeps the VALUES text whole on the scope that carries it
(``raw_sql``); this module turns that text back into rows. It answers nothing else: the
caller decides which rows survive a pin and whether the keys differ.

A cell is the literal's text, ``None`` for ``NULL``, or :data:`NOT_LITERAL` for anything
the SQL computes (``concat('1', '')``) -- a value this module will not evaluate.
"""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

from .semantic_text import DIALECT

NOT_LITERAL = object()

_INTEGER = re.compile(r"[+-]?\d+")


def literal_rows(raw_sql: str | None, width: int) -> list[tuple] | None:
    """Each row of the VALUES list as a tuple of ``width`` cells, or None.

    None when the text is not a single VALUES list whose every row has ``width`` cells:
    a caller with no rows proves nothing, which is the safe answer.
    """
    text = str(raw_sql or "").strip()
    if not text.upper().startswith("VALUES"):
        return None
    try:
        tree = sqlglot.parse_one(f"SELECT * FROM {text}", read=DIALECT)
    except sqlglot.errors.SqlglotError:
        return None
    values = tree.find(exp.Values)
    if values is None:
        return None
    rows = []
    for row in values.expressions:
        cells = row.expressions if isinstance(row, exp.Tuple) else [row]
        if len(cells) != width:
            return None
        rows.append(tuple(_cell(cell) for cell in cells))
    return rows or None


def _cell(node: exp.Expression):
    if isinstance(node, exp.Null):
        return None
    if isinstance(node, exp.Literal):
        return str(node.this)
    if isinstance(node, exp.Neg) and isinstance(node.this, exp.Literal):
        return f"-{node.this.this}"
    return NOT_LITERAL


def comparable(value) -> object:
    """The form two cells are compared in: an integer string by its number.

    ``'1'`` and ``'01'`` differ as strings but meet as numbers once a join compares a
    string with a number, so they are treated as the same value -- the conservative
    reading for a proof of distinctness.
    """
    if isinstance(value, str) and _INTEGER.fullmatch(value.strip()):
        return int(value)
    return value


def pin_literal(expression: str | None) -> tuple[str, str] | None:
    """``(column, literal)`` for an expression that is exactly ``column = literal``."""
    try:
        node = sqlglot.parse_one(str(expression or ""), read=DIALECT)
    except sqlglot.errors.SqlglotError:
        return None
    while isinstance(node, exp.Paren):
        node = node.this
    if not isinstance(node, exp.EQ):
        return None
    for column, literal in ((node.this, node.expression), (node.expression, node.this)):
        if isinstance(column, exp.Column) and isinstance(literal, exp.Literal):
            return column.name.lower(), str(literal.this)
    return None
