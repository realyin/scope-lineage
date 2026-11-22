"""Split Hive's FROM-first multi-table insert into one INSERT per target (audit 1.2).

``FROM src INSERT OVERWRITE TABLE t1 SELECT a INSERT INTO t2 SELECT b WHERE ...`` reads
``src`` once and writes every target. sqlglot does not parse it: the lenient parse keeps
only ``SELECT * FROM src`` and every target is lost. Each branch is an ordinary
``INSERT ... SELECT`` once the shared FROM clause is put back after its projection, so the
statement is rewritten into that form before anything parses it.

The rewrite works on sqlglot's own tokens, never on a regex over raw text, so a ``FROM``
or ``INSERT`` inside a string or a comment is never mistaken for a clause. It keeps the
script's line count: the shared FROM clause's lines become blank lines and its copies are
single-line, so a syntax error or comment later in the script keeps its line number.

A branch that writes a table the shared FROM also reads is not split: Hive reads the source
once, while sequential INSERTs would read the first branch's output, and the table state
graph would chain them. Such a statement is returned with ``split=False`` for the caller to
report (``multi_table_insert_unsupported``).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.dialects.dialect import Dialect
from sqlglot.tokens import Token, TokenType

from ._constants import DIALECT

def _token_types(*names: str) -> frozenset:
    """The named token types this sqlglot version defines."""
    return frozenset(getattr(TokenType, name) for name in names if hasattr(TokenType, name))


# Clauses that end a branch's projection list and must follow the re-inserted FROM.
_AFTER_FROM = _token_types(
    "WHERE", "GROUP_BY", "HAVING", "ORDER_BY", "SORT_BY", "CLUSTER_BY", "DISTRIBUTE_BY",
    "LIMIT", "WINDOW", "QUALIFY",
)
# Tokens that end the target name in `INSERT [OVERWRITE|INTO] [TABLE] <name> ...`.
_AFTER_TARGET = _token_types("PARTITION_BY", "PARTITION", "SELECT", "L_PAREN")
_TARGET_INTRO = frozenset({TokenType.OVERWRITE, TokenType.INTO, TokenType.TABLE})


@dataclass
class MultiTableInsert:
    """One FROM-first statement found in a script."""
    statement_index: int  # position in the rewritten script (what the parser numbers)
    targets: list[str] = field(default_factory=list)
    split: bool = False
    reason: str | None = None


def split_multi_table_inserts(sql: str) -> tuple[str, list[MultiTableInsert]]:
    """``(sql with each splittable FROM-first statement rewritten, every one found)``.

    A script with no FROM-first statement, or one the tokenizer cannot read, comes back
    unchanged with an empty list.
    """
    try:
        tokens = Dialect.get_or_raise(DIALECT).tokenize(sql)
    except Exception:  # noqa: BLE001 - an untokenizable script is left to the parser, which reports it
        return sql, []
    found: list[MultiTableInsert] = []
    pieces: list[str] = []
    cursor = 0
    extra_statements = 0
    for index, statement in enumerate(_statements(tokens)):
        branches = _top_level_inserts(statement)
        if not branches or statement[0].token_type != TokenType.FROM:
            continue
        record = MultiTableInsert(statement_index=index + extra_statements)
        found.append(record)
        rewritten = _rewrite(sql, statement, branches, record)
        if rewritten is None:
            continue
        start, end = statement[0].start, statement[-1].end + 1
        pieces.append(sql[cursor:start])
        pieces.append(rewritten)
        cursor = end
        extra_statements += len(branches) - 1
    if not pieces:
        return sql, found
    pieces.append(sql[cursor:])
    return "".join(pieces), found


def _statements(tokens: list[Token]) -> list[list[Token]]:
    """The script's statements as token lists, split on top-level semicolons."""
    statements: list[list[Token]] = []
    current: list[Token] = []
    for token in tokens:
        if token.token_type == TokenType.SEMICOLON:
            statements.append(current)
            current = []
        else:
            current.append(token)
    if current:
        statements.append(current)
    return statements


def _top_level_inserts(statement: list[Token]) -> list[int]:
    """Indexes of the INSERT tokens outside any parenthesis."""
    depth = 0
    found: list[int] = []
    for position, token in enumerate(statement):
        if token.token_type == TokenType.L_PAREN:
            depth += 1
        elif token.token_type == TokenType.R_PAREN:
            depth -= 1
        elif token.token_type == TokenType.INSERT and depth == 0:
            found.append(position)
    return found


def _raw(sql: str, tokens: list[Token]) -> str:
    """The tokens' source text on one line, comments dropped."""
    return " ".join(sql[token.start:token.end + 1] for token in tokens)


def _rewrite(
    sql: str, statement: list[Token], branches: list[int], record: MultiTableInsert
) -> str | None:
    """The split text for one statement, or None (with ``record.reason``) when it cannot be."""
    from_clause = _raw(sql, statement[:branches[0]])
    bounds = [*branches, len(statement)]
    split: list[str] = []
    for start, end in zip(bounds, bounds[1:]):
        branch = statement[start:end]
        record.targets.append(_target_name(sql, branch))
        text = _branch_with_from(sql, branch, from_clause)
        if text is None:
            record.reason = "branch_without_select"
            return None
        split.append(text)
    if not _all_parse_as_inserts(split):
        record.reason = "split_does_not_parse"
        return None
    if set(record.targets) & _tables_read(from_clause):
        record.reason = "target_read_by_shared_from"
        return None
    record.split = True
    # The shared FROM clause's lines stay as blank lines, and each branch keeps the text
    # that followed it (line breaks, comments) after its new `;`: no line moves.
    text = "\n" * sql.count("\n", statement[0].start, statement[branches[0]].start)
    for position, branch_text in enumerate(split):
        text += branch_text
        if position + 1 < len(split):
            gap_start = statement[bounds[position + 1] - 1].end + 1
            text += ";" + sql[gap_start:statement[bounds[position + 1]].start]
    return text


def _target_name(sql: str, branch: list[Token]) -> str:
    position = 1
    while position < len(branch) and branch[position].token_type in _TARGET_INTRO:
        position += 1
    name: list[Token] = []
    while position < len(branch) and branch[position].token_type not in _AFTER_TARGET:
        name.append(branch[position])
        position += 1
    return "".join(sql[token.start:token.end + 1] for token in name).replace("`", "").lower()


def _branch_with_from(sql: str, branch: list[Token], from_clause: str) -> str | None:
    """``INSERT ... SELECT <projection> <from_clause> <rest>`` for one branch."""
    depth = 0
    select_at = None
    for position, token in enumerate(branch):
        if token.token_type == TokenType.L_PAREN:
            depth += 1
        elif token.token_type == TokenType.R_PAREN:
            depth -= 1
        elif depth == 0 and token.token_type == TokenType.SELECT and select_at is None:
            select_at = position
        elif depth == 0 and select_at is not None and token.token_type in _AFTER_FROM:
            # Spliced right after the projection's last token, never after the text that
            # follows it: a trailing `-- comment` there would swallow the clause.
            cut = branch[position - 1].end + 1
            return f"{sql[branch[0].start:cut]} {from_clause}{sql[cut:branch[-1].end + 1]}"
    if select_at is None:
        return None
    return f"{sql[branch[0].start:branch[-1].end + 1]} {from_clause}"


def _all_parse_as_inserts(statements: list[str]) -> bool:
    for text in statements:
        try:
            tree = sqlglot.parse_one(text, read=DIALECT)
        except Exception:  # noqa: BLE001 - any parse failure means the split is not safe to use
            return False
        if not isinstance(tree, exp.Insert):
            return False
    return True


def _tables_read(from_clause: str) -> set[str]:
    try:
        tree = sqlglot.parse_one(f"SELECT 1 {from_clause}", read=DIALECT)
    except Exception:  # noqa: BLE001 - unreadable FROM: nothing proven read, the INSERT parse already passed
        return set()
    return {
        ".".join(part for part in (table.db, table.name) if part).lower()
        for table in tree.find_all(exp.Table)
    }
