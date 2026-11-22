"""Quote a name with a run parameter spliced into it, so the name parses as one identifier.

A scheduler parameter may fill a whole name part (``${db}.t``) or sit inside one
(``db.src_${region}``, ``db.${p}_src``). sqlglot parses the first shape as a ``Parameter``
part. The second it tokenizes as the word ``src_`` followed by a parameter, which its
grammar cannot place: the strict parse fails, and the lenient parse drops the parameter
and the tokens after it up to the next clause it recognises -- the table becomes
``db.src_`` (reported as missing metadata) and a JOIN that follows disappears.

The repair runs on the **token stream**, so a ``${...}`` inside a string literal or a
comment is never touched (the tokenizer strips both). A spliced name is a run of tokens
with no gap between them, made of word pieces and ``${name}`` groups, holding at least one
of each kind -- or at least two parameters -- and it must be in a name position: part of
a dotted name, or right after ``FROM`` / ``JOIN`` / ``TABLE`` / ``INTO`` / ``VIEW``.
Elsewhere the same shape can be a value (``dt = ${bizdate}01``). Each run is wrapped in backticks, the way an
author would write it: ``db.`src_${region}``` parses to a table ``src_${region}``, whose id
keeps the parameter, so the existing unbound-parameter reporting
(:func:`scope_lineage.scope.parser.unbound_table_parameters`) applies to it unchanged.

A rewrite is kept only when it changes something; the caller discloses the quoted names,
for the same reason the keyword repair discloses what it quoted.
"""

from __future__ import annotations

import re
from functools import lru_cache

import sqlglot
from sqlglot.errors import SqlglotError
from sqlglot.tokens import Token, TokenType

from ._constants import DIALECT

__all__ = ["quote_spliced_parameters"]

_WORD = re.compile(r"^\w+$")
_PARAMETER_NAME = re.compile(r"^\w+$")
# What a bare (undotted) relation name follows.
_RELATION_KEYWORDS = frozenset({
    TokenType.FROM, TokenType.JOIN, TokenType.TABLE, TokenType.INTO, TokenType.VIEW,
})


def _parameter_at(tokens: list[Token], index: int) -> int:
    """The index past a ``${name}`` group written without gaps starting at ``index``, else -1."""
    if index + 4 > len(tokens):
        return -1
    dollar, brace, name, close = tokens[index : index + 4]
    if (
        dollar.token_type == TokenType.PARAMETER
        and brace.token_type == TokenType.L_BRACE
        and close.token_type == TokenType.R_BRACE
        and _PARAMETER_NAME.match(name.text)
        and dollar.end + 1 == brace.start
        and brace.end + 1 == name.start
        and name.end + 1 == close.start
    ):
        return index + 4
    return -1


def _word(token: Token) -> bool:
    """A bare word piece: a name or keyword as written, never a string or quoted name."""
    return token.token_type not in (TokenType.STRING, TokenType.IDENTIFIER) and bool(
        _WORD.match(token.text)
    )


def _piece_end(tokens: list[Token], index: int) -> tuple[int, bool]:
    """``(index past the piece, is_parameter)`` for the piece at ``index``; ``-1`` for none."""
    end = _parameter_at(tokens, index)
    if end >= 0:
        return end, True
    if _word(tokens[index]):
        return index + 1, False
    return -1, False


def _names_a_relation(tokens: list[Token], start: int, end: int) -> bool:
    """Whether the run is part of a dotted name or stands right after a table keyword.

    Anywhere else a spliced run may be a value (``dt = ${bizdate}01``) or a projection
    sqlglot already reads as ``c_ AS ${x}``; quoting it there would turn a value into a
    column, so those are left to the parser as before.
    """
    before = tokens[start - 1] if start > 0 else None
    after = tokens[end] if end < len(tokens) else None
    if before is not None and before.token_type == TokenType.DOT and before.end + 1 == tokens[start].start:
        return True
    if after is not None and after.token_type == TokenType.DOT and tokens[end - 1].end + 1 == after.start:
        return True
    return before is not None and before.token_type in _RELATION_KEYWORDS


def _spliced_runs(tokens: list[Token]) -> list[tuple[int, int]]:
    """``(start char, end char)`` of every spliced name, in order."""
    runs = []
    index = 0
    while index < len(tokens):
        end, is_parameter = _piece_end(tokens, index)
        if end < 0:
            index += 1
            continue
        parameters, words, start = int(is_parameter), int(not is_parameter), index
        while end < len(tokens) and tokens[end - 1].end + 1 == tokens[end].start:
            following, is_parameter = _piece_end(tokens, end)
            if following < 0:
                break
            parameters += is_parameter
            words += not is_parameter
            end = following
        if parameters and (words or parameters > 1) and _names_a_relation(tokens, start, end):
            runs.append((tokens[start].start, tokens[end - 1].end + 1))
        index = end
    return runs


@lru_cache(maxsize=64)
def quote_spliced_parameters(sql: str) -> tuple[str, tuple[str, ...]]:
    """Return ``(sql with spliced names quoted, the names quoted)``; unchanged when none."""
    try:
        tokens = sqlglot.tokenize(sql, dialect=DIALECT)
    except SqlglotError:
        return sql, ()
    runs = _spliced_runs(tokens)
    if not runs:
        return sql, ()
    pieces, names, position = [], [], 0
    for start, end in runs:
        name = sql[start:end]
        pieces.append(sql[position:start])
        pieces.append(f"`{name}`")
        names.append(name)
        position = end
    pieces.append(sql[position:])
    return "".join(pieces), tuple(dict.fromkeys(names))
