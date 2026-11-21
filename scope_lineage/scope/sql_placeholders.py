"""Placeholders an agent leaves in a query for a definition the catalog does not give.

The convention is a comment whose text starts with the marker ``待确认`` and a colon
(``:`` or ``：``), written beside a neutral predicate or value, so the query still parses::

    WHERE t.dt = '2024-01-01' AND /* 待确认：what counts as reached */ 1 = 1
    WHERE t.result_cd IN (/* 待确认：which codes mean not reached */ '0')

The comments are read from the token stream, not from the tree. sqlglot attaches a
comment to whichever node is near it -- ``/* x */ 1 = 1`` lands on the ``AND`` holding the
whole condition, ``, /* x */ 'v' AS c`` on the projection *before* it -- so the tree says
which statement a comment is in but not what it sits next to. The tokens do: every comment
lies in the gap between two tokens, a gap holds nothing but whitespace and comments (a
string or a quoted name is a token of its own, so marker text inside one is never read),
and the tokens before the gap say what the comment follows. Statements are counted the way
sqlglot's parser splits them, so the numbers agree with ``query_facts``.

A placeholder is tied to a column only by position: it sits right after ``<column> <op>``
(``=``, ``<>``, ``!=``, ``<``, ``>``, ``<=``, ``>=``) or ``<column> IN (``, where the column
is a name or ``alias.name`` standing alone on its side. Anything else -- before the
predicate, after the value, beside ``1 = 1``, after an expression -- is tied to nothing.
"""

from __future__ import annotations

import re
from typing import Optional

from sqlglot.dialects.dialect import Dialect
from sqlglot.tokens import Token, TokenType

from ._constants import DIALECT

__all__ = ["MARKER", "placeholders_by_statement"]

MARKER = "待确认"
_MARKED = re.compile(rf"^\s*{MARKER}\s*[:：]\s*(?P<text>.*?)\s*$", re.DOTALL)
_COMPARISONS = {
    TokenType.EQ, TokenType.NEQ, TokenType.LT, TokenType.GT, TokenType.LTE, TokenType.GTE,
}
# What may stand right before a column that is a whole side of a comparison.
_BOUNDARIES = {
    TokenType.WHERE, TokenType.AND, TokenType.OR, TokenType.ON, TokenType.L_PAREN,
    TokenType.NOT, TokenType.WHEN, TokenType.HAVING, TokenType.COMMA, TokenType.SELECT,
}
_NOT_NAMES = {
    TokenType.NUMBER, TokenType.STRING, TokenType.NULL, TokenType.TRUE, TokenType.FALSE,
    TokenType.END, TokenType.CASE, TokenType.STAR, TokenType.R_PAREN,
}
_WORD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def placeholders_by_statement(sql: str) -> dict[int, list[dict]]:
    """``{statement position: [{"text", "written"}]}`` in script order.

    ``written`` is ``{"alias", "column"}`` (``alias`` None for a bare name) when the
    placeholder sits right after a comparison of one column, else None.
    """
    tokens = Dialect.get_or_raise(DIALECT).tokenize(sql)
    chunks = _chunk_numbers(tokens)
    found: dict[int, list[dict]] = {}
    for index in range(len(tokens) + 1):
        before = tokens[index - 1] if index > 0 else None
        after = tokens[index] if index < len(tokens) else None
        start = before.end + 1 if before else 0
        end = after.start if after else len(sql)
        for comment in _comments(sql[start:end]):
            match = _MARKED.match(comment)
            if match is None:
                continue
            if before is not None and (before.token_type != TokenType.SEMICOLON or after is None):
                number = chunks[index - 1]
            else:
                number = chunks[index] if after is not None else 1
            found.setdefault(number, []).append({
                "text": match.group("text"),
                "written": _written(tokens, index, chunks),
            })
    return found


def _chunk_numbers(tokens: list[Token]) -> list[int]:
    """The statement position of every token, split exactly as ``Parser._parse`` splits:
    a semicolon carrying a comment becomes a statement of its own."""
    numbers = []
    current = 1
    for position, token in enumerate(tokens):
        if token.token_type == TokenType.SEMICOLON:
            if token.comments:
                current += 1
            numbers.append(current)
            if position < len(tokens) - 1:
                current += 1
        else:
            numbers.append(current)
    return numbers


def _comments(gap: str) -> list[str]:
    """The comment texts in a gap between two tokens (whitespace and comments only)."""
    found = []
    position = 0
    while position < len(gap):
        if gap.startswith("--", position):
            stop = gap.find("\n", position)
            stop = len(gap) if stop < 0 else stop
            found.append(gap[position + 2 : stop])
            position = stop
        elif gap.startswith("/*", position):
            stop = gap.find("*/", position + 2)
            stop = len(gap) if stop < 0 else stop
            found.append(gap[position + 2 : stop])
            position = stop + 2
        else:
            position += 1
    return found


def _written(tokens: list[Token], index: int, chunks: list[int]) -> Optional[dict]:
    """The column a placeholder at gap ``index`` follows as ``<column> <op>`` / ``IN (``."""
    head = index - 1
    if head >= 0 and tokens[head].token_type in _COMPARISONS:
        head -= 1
    elif (
        head >= 1
        and tokens[head].token_type == TokenType.L_PAREN
        and tokens[head - 1].token_type == TokenType.IN
    ):
        head -= 2
    else:
        return None
    if head < 0 or not _name(tokens[head]):
        return None
    column = tokens[head].text
    alias = None
    head -= 1
    if head >= 1 and tokens[head].token_type == TokenType.DOT and _name(tokens[head - 1]):
        alias = tokens[head - 1].text
        head -= 2
        if head >= 0 and tokens[head].token_type == TokenType.DOT:
            return None  # db.table.column: not a reference query_facts resolves
    if head >= 0 and chunks[head] == chunks[index - 1]:
        if tokens[head].token_type not in _BOUNDARIES:
            return None  # the column is part of an expression, not a side on its own
    return {"alias": alias, "column": column}


def _name(token: Token) -> bool:
    if token.token_type in (TokenType.VAR, TokenType.IDENTIFIER):
        return True
    return token.token_type not in _NOT_NAMES and bool(_WORD.match(token.text))
