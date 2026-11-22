"""SQL text split into code and the spans that are never code: string literals and comments.

Several passes rewrite or scan rendered SQL with regular expressions -- expansion
substitutes a reference with its upstream expression, keyword repair quotes an identifier,
the feature scan harvests `<name>(` calls. A regex over the whole text cannot tell
`c.v` the reference from `'see c.v now'` the value or `/* c.v note */` the remark, so each
pass that ran over the whole text rewrote or harvested inside literals and comments too
(WP4: 2.1, 1.10, 1.13-c, 1.13-e, 1.13-m).

This module is the one definition of "a literal or a comment" those passes share:

- :data:`SQL_LITERAL_OR_COMMENT` -- a single quoted string (``''`` and backslash escapes)
  or a ``/* */`` / ``--`` comment, self-contained so it can be embedded in a larger
  alternation;
- :func:`sub_in_code` -- ``re.sub`` that leaves every literal and comment verbatim;
- :func:`blank_string_literals`, :func:`blank_comments`,
  :func:`blank_literals_and_comments` -- the scan-only forms, each span replaced by a
  space so the code around it cannot fuse into a new token.

A backslash consumes the character after it, whatever it is: `'\\\\'` is one literal holding
one backslash. Treating `\\'` as an escaped quote instead swallowed the code up to the next
literal, and the references in it vanished from the scan (1.10).
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Callable

# `(?s:...)` scopes DOTALL to the spans that may cross a line, so a pattern embedding this
# keeps its own meaning of `.`.
_LITERAL = r"(?s:'(?:''|\\.|[^'\\])*')"
_COMMENT = r"(?s:/\*.*?\*/)|--[^\n\r]*"
SQL_LITERAL_OR_COMMENT = rf"{_LITERAL}|{_COMMENT}"

_SPAN = re.compile(rf"(?P<literal>{_LITERAL})|(?P<comment>{_COMMENT})")

# Patterns are built from identifier names, so their number grows with a statement's
# columns; compiled objects are kept here for the same reason expression_refs keeps its own,
# in an LRU of the same fixed size (audit 2.2).
_COMBINED_CACHE_SIZE = 4096


@lru_cache(maxsize=_COMBINED_CACHE_SIZE)
def _combined(pattern: str) -> "re.Pattern[str]":
    return re.compile(rf"(?P<_sql_skip>{SQL_LITERAL_OR_COMMENT})|(?:{pattern})")


def sub_in_code(pattern: str, repl: str | Callable[["re.Match[str]"], str], sql: str) -> str:
    """``re.sub(pattern, repl, sql)`` applied to code only.

    One scan alternates "literal or comment" with ``pattern``, so a span is consumed whole
    before ``pattern`` can start inside it, and look-around in ``pattern`` still sees the
    characters on either side. ``repl`` is a plain replacement string (inserted as is, no
    group references) or a function of the match.
    """
    if not sql:
        return sql

    def replace(match: "re.Match[str]") -> str:
        if match.group("_sql_skip") is not None:
            return match.group(0)
        return repl(match) if callable(repl) else repl

    return _combined(pattern).sub(replace, sql)


def blank_string_literals(sql: str) -> str:
    """Replace every string literal with a space; comments are left in place."""
    return _span_blank(sql or "", literals=True, comments=False)


def blank_comments(sql: str) -> str:
    """Replace every comment with a space; string literals are left in place.

    A literal is still recognized, so a `'--'` or `'/*'` value is not taken for the start
    of a comment that would eat the rest of the line.
    """
    return _span_blank(sql or "", literals=False, comments=True)


def blank_literals_and_comments(sql: str) -> str:
    """Replace every string literal and every comment with a space: the code alone."""
    return _span_blank(sql or "", literals=True, comments=True)


def _span_blank(sql: str, *, literals: bool, comments: bool) -> str:
    def replace(match: "re.Match[str]") -> str:
        if match.group("literal") is not None:
            return " " if literals else match.group(0)
        return " " if comments else match.group(0)

    return _SPAN.sub(replace, sql)
