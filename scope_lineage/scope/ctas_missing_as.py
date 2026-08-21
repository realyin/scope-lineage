"""Insert the `AS` that Spark lets a CTAS omit but sqlglot only accepts before SELECT.

Spark's grammar is ``CREATE TABLE … [AS] query``. sqlglot honours the omission when the
query starts with ``SELECT``, but not when it starts with ``WITH``: there it gives up and
returns a ``Command``, and the statement contributes no lineage at all.

The repair runs on the **token stream, per statement**, and that is the whole point of the
module. A text-level match cannot see comments, and in real scripts a commented-out
``create table`` line sitting directly above a live ``WITH … AS (`` is a far more common
text shape than the defect itself. Rewriting there turns the *following* statement into
``INSERT OVERWRITE TABLE u AS with`` -- same node type, same target table, CTE and
projection silently discarded. sqlglot's tokenizer strips comments and string literals, so
scanning tokens sees neither trap.

Acceptance is per statement and asks the parser, not a pattern: the span must currently be
a ``Command`` and must become a ``Create`` carrying a query. Anything unforeseen simply
falls back to today's behaviour.
"""
from __future__ import annotations

from functools import lru_cache

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.tokens import TokenType

DIALECT = "spark"

# Only these may stand between CREATE and the TABLE/VIEW keyword. Anything else means this
# is not a shape we understand, and we would rather do nothing than guess.
_CREATE_MODIFIERS = frozenset({
    TokenType.OR,
    TokenType.REPLACE,
    TokenType.TEMPORARY,
})
# EXTERNAL and GLOBAL have no dedicated token type -- they arrive as VAR. Allowing them by
# text keeps the gate as narrow as the named types; allowing VAR itself would let any
# identifier through and defeat the point of the whitelist.
_CREATE_MODIFIER_WORDS = frozenset({"EXTERNAL", "GLOBAL"})
_CREATE_TARGETS = frozenset({TokenType.TABLE, TokenType.VIEW})
_OPEN_PARENS = frozenset({TokenType.L_PAREN})
_CLOSE_PARENS = frozenset({TokenType.R_PAREN})


@lru_cache(maxsize=64)
def repair_ctas_missing_as(sql: str) -> tuple[str, tuple[str, ...]]:
    """Return (repaired_sql, tuple of repaired target descriptions).

    The second element is for disclosure: a rewritten statement must not be presented as
    if the author wrote it that way, the same reason `repair_keyword_identifiers` reports
    what it quoted.
    """
    try:
        tokens = sqlglot.tokenize(sql, dialect=DIALECT)
    except SqlglotError:
        return sql, ()

    edits: list[tuple[int, str]] = []
    for span in _statement_spans(tokens):
        offset = _insertion_offset(span)
        if offset is None:
            continue
        start, end = span[0].start, span[-1].end + 1
        statement_sql = sql[start:end]
        repaired = _accepted_repair(statement_sql, offset - start)
        if repaired is None:
            continue
        edits.append((offset, repaired))
    if not edits:
        return sql, ()

    out = []
    cursor = 0
    for offset, _ in edits:
        out.append(sql[cursor:offset])
        out.append("AS ")
        cursor = offset
    out.append(sql[cursor:])
    return "".join(out), tuple(name for _, name in edits)


def _statement_spans(tokens) -> list[list]:
    spans: list[list] = []
    current: list = []
    for token in tokens:
        if token.token_type == TokenType.SEMICOLON:
            if current:
                spans.append(current)
            current = []
            continue
        current.append(token)
    if current:
        spans.append(current)
    return spans


def _insertion_offset(span) -> int | None:
    """Character offset of the WITH that should have been preceded by AS, or None."""
    if not span or span[0].token_type != TokenType.CREATE:
        return None
    index = 1
    while index < len(span) and (
        span[index].token_type in _CREATE_MODIFIERS
        or (
            span[index].token_type == TokenType.VAR
            and span[index].text.upper() in _CREATE_MODIFIER_WORDS
        )
    ):
        index += 1
    if index >= len(span) or span[index].token_type not in _CREATE_TARGETS:
        return None

    depth = 0
    for token in span[index + 1:]:
        if token.token_type in _OPEN_PARENS:
            depth += 1
        elif token.token_type in _CLOSE_PARENS:
            depth -= 1
        elif depth == 0:
            if token.token_type == TokenType.ALIAS:
                # The author wrote the AS after all -- whatever fails here, it is not this.
                return None
            if token.token_type == TokenType.WITH:
                return token.start
    return None


def _accepted_repair(statement_sql: str, relative_offset: int) -> str | None:
    """Return a label for the repair if the parser confirms it, else None."""
    if not isinstance(_parsed(statement_sql), exp.Command):
        return None
    candidate = (
        statement_sql[:relative_offset] + "AS " + statement_sql[relative_offset:]
    )
    tree = _parsed(candidate)
    if not isinstance(tree, exp.Create) or tree.expression is None:
        return None
    target = tree.this
    name = target.sql(dialect=DIALECT) if target is not None else "?"
    return name.split("(")[0].strip()


def _parsed(statement_sql: str):
    try:
        return sqlglot.parse_one(statement_sql, dialect=DIALECT)
    except SqlglotError:
        return None
