"""Markdown text escaping for the contract-derived documents.

One theme: make a rendered contract value survive one markdown line. A code span that a
backtick inside SQL cannot break, a table cell that a pipe cannot break, and the newline
normalization both of them rest on. Nothing here reads a contract document or decides
what to say -- ``mapping_markdown`` and ``semantic_markdown`` do that and call in here
for the escaping, so both documents escape identically by construction rather than by
two copies that agree today.
"""

from __future__ import annotations

import re


def normalize_inline(text: str) -> str:
    """One fact per line: real newlines inside rendered values become literal ``\\n``."""
    return str(text).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")


def expr_span(expression: str) -> str:
    """Code span that survives backticks inside SQL (`` `t`.`c` ``) and newlines."""
    text = normalize_inline(str(expression))
    longest_run = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest_run + 1)
    if longest_run:
        return f"{fence} {text} {fence}"
    return f"{fence}{text}{fence}"


def cell(text: str) -> str:
    """Table-cell text. GFM honours the pipe escape inside code spans too, so an
    expression rendered into a cell keeps its literal pipes."""
    return normalize_inline(str(text)).replace("|", "\\|")


def sql_alias_note(alias) -> str:
    """The one spelling of "written into this column by DDL position, under that name".

    Three documents print it -- semantic.md's field dictionary, glossary.md and the
    overrides template -- and a reader holding two of them must not have to work out
    that two different sentences are saying the same thing. Empty for no alias.
    """
    text = str(alias or "")
    return f"（SQL 别名 {expr_span(text)}，按 DDL 位置写入）" if text else ""
