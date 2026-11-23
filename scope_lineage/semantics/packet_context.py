"""What a packet says about a task beyond its statements: its run date and its registration.

- :func:`date_literals` -- the date-shaped string literals of a task's SQL, comments
  aside, each with how many days it sits from the task's expected run date. A corpus
  exported from run instances carries ``'20250115'`` where the script had a batch-date
  parameter; the offset is the fact a writer reads that from, and the packet draws no
  conclusion from it (``'99991231'`` is a literal too). :func:`string_literals` is the
  tokenizing step, which ``packet.md`` reuses on a rule's expression.
- :func:`scheduling_parameters` -- for a task read from its scheduling template, each
  parameter its SQL still holds with the definition the task export gives, verbatim, and
  the table-name parameters ``parse`` bound. What a definition means is the scheduler's;
  the packet does not read it.
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


_SLOT = re.compile(r"\$\{(\w+)\}")


def parameter_counts(sql) -> dict[str, int]:
    """``{name: occurrences}`` of every ``${name}`` in ``sql`` outside comments -- in the code,
    in a string literal, in a quoted name -- in order of first appearance."""
    if not sql:
        return {}
    try:
        tokens = Dialect.get_or_raise(DIALECT).tokenize(str(sql))
    except (SqlglotError, ValueError):
        return {}
    counts: dict[str, int] = {}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        group = tokens[index : index + 4]
        if (len(group) == 4 and token.token_type == TokenType.PARAMETER
                and group[1].token_type == TokenType.L_BRACE
                and group[3].token_type == TokenType.R_BRACE
                and re.fullmatch(r"\w+", group[2].text)):
            counts[group[2].text] = counts.get(group[2].text, 0) + 1
            index += 4
            continue
        if token.token_type in (TokenType.STRING, TokenType.IDENTIFIER):
            for name in _SLOT.findall(token.text):
                counts[name] = counts.get(name, 0) + 1
        index += 1
    return counts


def scheduling_parameters(sql, given: dict | None) -> dict | None:
    """``{in_sql, bound}`` of a task parsed from its scheduling template, else None.

    ``given`` is the task record's ``{definitions, descriptions, bound}``. ``in_sql`` is
    each parameter the SQL still holds outside comments, with its definition as the task
    export gives it (None when the list has none), its count and the user's description;
    ``bound`` is each table-name parameter ``parse`` replaced, with how many places. A
    parameter left only in a comment is in neither. None when both are empty.
    """
    if not given:
        return None
    definitions = given.get("definitions") or {}
    descriptions = given.get("descriptions") or {}

    def entry(name: str, count: int) -> dict:
        return {"name": name, "definition": definitions.get(name), "count": count,
                **({"description": descriptions[name]} if descriptions.get(name) else {})}

    in_sql = [entry(name, count) for name, count in parameter_counts(sql).items()]
    bound = [entry(name, int(count)) for name, count in (given.get("bound") or {}).items()]
    return {"in_sql": in_sql, "bound": bound} if in_sql or bound else None


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
