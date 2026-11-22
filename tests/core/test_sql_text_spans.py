"""WP4: one definition of "a string literal or a comment" for every text pass.

The passes that rewrite or scan rendered SQL with regexes each carried their own idea of
a literal, or none: expansion rewrote `'see c.v now'`, keyword repair quoted a word inside
`'no using here'`, the feature scan read `/* note(x) */` as a call, and one literal regex
took `\\'` for an escaped quote and swallowed the code after `'\\'`. The splitter below is
the shared answer; these tests pin its spans.
"""

from __future__ import annotations

import pytest

from scope_lineage.scope.sql_text_spans import (
    blank_comments,
    blank_literals_and_comments,
    blank_string_literals,
    sub_in_code,
)


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("concat('a.b', x)", "concat( , x)"),
        ("concat('it''s', x)", "concat( , x)"),
        # A backslash takes the next character whatever it is: `'\\'` is one literal, and
        # the reference after it is code.
        ("concat('\\\\', a.user_id, '\\\\')", "concat( , a.user_id,  )"),
        ("concat('it\\'s', x)", "concat( , x)"),
        ("x /* 'not a literal' */ + y", "x /* 'not a literal' */ + y"),
    ],
)
def test_blank_string_literals(sql: str, expected: str) -> None:
    assert blank_string_literals(sql) == expected


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("x /* c.v */ + y", "x   + y"),
        ("x + y -- c.v\n+ z", "x + y  \n+ z"),
        ("x /* a\nb */ + y", "x   + y"),
        # A literal holding comment markers is a value, not the start of a comment.
        ("concat('--', x, '/*') + y", "concat('--', x, '/*') + y"),
    ],
)
def test_blank_comments(sql: str, expected: str) -> None:
    assert blank_comments(sql) == expected


def test_blank_literals_and_comments_leaves_code_only() -> None:
    assert blank_literals_and_comments("upper('a(') /* f(x) */ + g(y) -- h(z)") == (
        "upper( )   + g(y)  "
    )


def test_sub_in_code_leaves_literals_and_comments_verbatim() -> None:
    sql = "concat('see c.v now', c.v) /* c.v note */ + c.v -- c.v\n"

    assert sub_in_code(r"c\.v", "X", sql) == (
        "concat('see c.v now', X) /* c.v note */ + X -- c.v\n"
    )


def test_sub_in_code_lookaround_sees_the_neighbouring_characters() -> None:
    # The scan is one pass over the whole text, so `(?<![.\w])` still sees the `.`
    # in front of the second `v`.
    assert sub_in_code(r"(?<![.\w])v\b", "X", "v + t.v + 'v'") == "X + t.v + 'v'"


def test_sub_in_code_accepts_a_function_and_inserts_text_verbatim() -> None:
    assert sub_in_code(r"\bv\b", lambda _m: r"(a\1)", "v + 1") == r"(a\1) + 1"
    assert sub_in_code(r"\bv\b", r"(a\1)", "v + 1") == r"(a\1) + 1"
