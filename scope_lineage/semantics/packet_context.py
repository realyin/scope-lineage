"""What a packet says about a task beyond its statements: its run date and its registration.

- :func:`date_literals` -- the date-shaped string literals of a task's SQL, comments
  aside, each with how many days it sits from the task's expected run date. A corpus
  exported from run instances carries ``'20250115'`` where the script had a batch-date
  parameter; the offset is the fact a writer reads that from, and the packet draws no
  conclusion from it (``'99991231'`` is a literal too). :func:`string_literals` is the
  tokenizing step, which ``packet.md`` reuses on a rule's expression.
- :func:`upstream_unmatched` -- the registered upstream tasks no table the task reads
  answers to by name. A heuristic over names: it says "does not match", not "not read".
"""

from __future__ import annotations

import re
from datetime import date

from sqlglot.dialects.dialect import Dialect
from sqlglot.errors import SqlglotError
from sqlglot.tokens import TokenType

from .sql_forms import DIALECT

_DATE_TEXT = re.compile(r"^(\d{4})-?(\d{2})-?(\d{2})$")
_DATE_START = re.compile(r"^(\d{4})-?(\d{2})-?(\d{2})(?!\d)")


def parse_date(text) -> date | None:
    """``YYYY-MM-DD`` or ``YYYYMMDD`` (a time after the date is ignored), else ``None``."""
    match = _DATE_START.match(str(text or "").strip())
    if not match:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def date_literals(sql, expect_date) -> list[dict]:
    """``[{literal, count, days_from_expect_date}]`` in order of first appearance.

    Only a string literal that is a whole valid date (``'20250115'``, ``'2025-01-15'``)
    counts; one inside a comment does not. Nothing without an expected date to measure
    from, or when the SQL does not tokenize.
    """
    expected = parse_date(expect_date)
    if expected is None or not sql:
        return []
    found: dict[str, dict] = {}
    for literal in string_literals(sql):
        text = literal[1:-1]
        day = parse_date(text) if _DATE_TEXT.match(text) else None
        if day is None:
            continue
        entry = found.setdefault(literal, {
            "literal": literal, "count": 0, "days_from_expect_date": (day - expected).days,
        })
        entry["count"] += 1
    return list(found.values())


def string_literals(sql) -> list[str]:
    """Every string literal of ``sql`` as ``'text'``, comments aside; none if it does not tokenize.

    The form ``date_literals`` keys its entries by, so a rule's expression can be matched
    against its task's literals (D-G6).
    """
    if not sql:
        return []
    try:
        tokens = Dialect.get_or_raise(DIALECT).tokenize(str(sql))
    except (SqlglotError, ValueError):
        return []
    return [f"'{token.text}'" for token in tokens if token.token_type == TokenType.STRING]


def upstream_unmatched(registered, reads) -> list[str]:
    """The registered upstream tasks whose name matches no ``db.table`` in ``reads``.

    A task matches a table it is named after: ``tbl``, ``db_tbl``, or any name ending in
    ``_db_tbl`` (a realtime sync task prefixes the table it lands).
    """
    unmatched = []
    for task in registered or []:
        name = str(task).lower()
        if not any(_named_after(name, table) for table in reads):
            unmatched.append(str(task))
    return unmatched


def _named_after(name: str, table: str) -> bool:
    db, _, tbl = table.rpartition(".")
    joined = f"{db}_{tbl}" if db else tbl
    return name in (tbl, joined) or name.endswith(f"_{joined}")
