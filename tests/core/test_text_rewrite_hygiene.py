"""WP4: text rewrites touch code only, never a string literal or a comment.

Expansion, the qualify-fallback substitution, keyword repair and the display rewrite each
ran a regex over the whole rendered SQL. A literal is data and a comment is a remark, so a
rewrite inside either changes a value the contract publishes (`'see c.v now'` became
`'see (amt * 2) now'`, `'no using here'` became ``'no `using` here'``) or garbles the
author's note. And one literal regex took the `\\'` that ends `'\\\\'` for an escaped
quote, swallowing the code up to the next literal: the reference in between was never
expanded.

Each test below is one measured reproduction (audit verify-A §2.1, verify-B §1.10,
§1.13-c/d/e); each sentinel pins the neighbouring behaviour the fix must keep. The struct
path expansion and the operator scan at the end are WP4's two follow-ups (WP13).
"""

from __future__ import annotations

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.scope.expression_text import _parenthesize_replacement_expression
from scope_lineage.scope.keyword_identifiers import repair_keyword_identifiers
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.scope.scope_facts import _expression_features

SCHEMA = {
    "ods.x": ["amt", "k", "fee"],
    "s.a": ["x", "user_id", "using"],
    "s.log": ["x", "arr"],
    "s.users": ["profile"],
}

# `'\\'` in SQL: a literal holding one backslash.
BACKSLASH = "'\\\\'"


def _root_outputs(sql: str) -> dict[str, dict]:
    document = to_lineage_dict(parse_scope_lineage(sql, "hygiene", schema=SCHEMA))
    return {output["name"]: output for output in document["scopes"]["ROOT"]["outputs"]}


def _physical(output: dict) -> set[str]:
    resolution = output.get("expression_resolution") or {}
    return {
        f"{field['table']}.{field['field']}"
        for field in resolution.get("physical_source_fields") or []
    }


# ------------------------------------------------- expansion (2.1, 1.10)


def test_expansion_leaves_a_string_literal_unchanged() -> None:
    output = _root_outputs(
        "INSERT OVERWRITE TABLE m.t "
        "WITH c AS (SELECT c1.amt * 2 AS v FROM ods.x c1) "
        "SELECT CONCAT('see c.v now', c.v) AS s FROM c"
    )["s"]

    assert output["expanded_expression"] == "CONCAT('see c.v now', (`ods.x`.`amt` * 2))"


def test_expansion_leaves_a_comment_unchanged() -> None:
    output = _root_outputs(
        "INSERT OVERWRITE TABLE m.t "
        "WITH c AS (SELECT c1.amt * 2 AS v FROM ods.x c1) "
        "SELECT c.v /* c.v note */ + 1 AS s FROM c"
    )["s"]

    assert output["expanded_expression"] == "(`ods.x`.`amt` * 2) /* c.v note */ + 1"


def test_a_backslash_literal_does_not_hide_the_reference_after_it() -> None:
    output = _root_outputs(
        "INSERT OVERWRITE TABLE m.t "
        "WITH c AS (SELECT c1.amt * 2 AS v, c1.k FROM ods.x c1) "
        f"SELECT CONCAT({BACKSLASH}, c.v, '-', c.k) AS s FROM c"
    )["s"]

    assert output["expanded_expression"] == (
        f"CONCAT({BACKSLASH}, (`ods.x`.`amt` * 2), '-', `ods.x`.`k`)"
    )
    assert {"ods.x.amt", "ods.x.k"} <= _physical(output)


def test_a_backslash_literal_keeps_the_call_around_a_physical_column() -> None:
    output = _root_outputs(
        "INSERT OVERWRITE TABLE m.t "
        f"SELECT CONCAT({BACKSLASH}, a.user_id, {BACKSLASH}) AS k FROM s.a a"
    )["k"]

    assert output["expanded_expression"] == (
        f"CONCAT({BACKSLASH}, `s.a`.`user_id`, {BACKSLASH})"
    )


def test_a_backslash_literal_does_not_leave_a_local_alias_behind() -> None:
    output = _root_outputs(
        "INSERT OVERWRITE TABLE m.t "
        f"WITH c AS (SELECT CONCAT({BACKSLASH}, a.user_id, {BACKSLASH}, a.x) AS k FROM s.a a) "
        "SELECT CONCAT(c.k, 'z') AS kz FROM c"
    )["kz"]

    assert "`a`." not in output["expanded_expression"]
    assert "CONCAT(" in output["expanded_expression"]


def test_sentinel_expansion_still_substitutes_code_references() -> None:
    output = _root_outputs(
        "INSERT OVERWRITE TABLE m.t "
        "WITH c AS (SELECT c1.amt * 2 AS v FROM ods.x c1) "
        "SELECT c.v * 10 AS r, CONCAT('-', c.v) AS s FROM c"
    )

    assert output["r"]["expanded_expression"] == "(`ods.x`.`amt` * 2) * 10"
    assert output["s"]["expanded_expression"] == "CONCAT('-', (`ods.x`.`amt` * 2))"


# ------------------------------------------- operator precedence (1.9)

# A substituted expression is wrapped in parentheses unless it already is one
# parenthesised unit. Looking only at the first and last character took
# `(x + 1) + COALESCE(y, 0)` for such a unit, and `c.v * 10` became
# `(x + 1) + COALESCE(y, 0) * 10` -- a different value, published as resolved.


@pytest.mark.parametrize(
    ("replacement", "expected"),
    [
        ("(a + 1) + COALESCE(b, 0)", "((a + 1) + COALESCE(b, 0))"),
        ("(a + b) + (c + d)", "((a + b) + (c + d))"),
        ("(a) * (b)", "((a) * (b))"),
        # sentinels: one parenthesised unit is left as it is
        ("(a + 1)", "(a + 1)"),
        ("((a + 1) + (b))", "((a + 1) + (b))"),
        ("(CONCAT(')', a))", "(CONCAT(')', a))"),
        ("`s`.`x`", "`s`.`x`"),
        ("a + 1", "(a + 1)"),
    ],
)
def test_parenthesize_wraps_unless_one_unit(replacement: str, expected: str) -> None:
    assert _parenthesize_replacement_expression(replacement) == expected


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        (
            "WITH c AS (SELECT (a.x + 1) + COALESCE(a.user_id, 0) AS v FROM s.a a) "
            "SELECT c.v * 10 AS r FROM c",
            "((`s.a`.`x` + 1) + COALESCE(`s.a`.`user_id`, 0)) * 10",
        ),
        (
            "SELECT q.v * 10 AS r FROM (SELECT (a.x + 1) - (a.user_id + 2) AS v FROM s.a a) q",
            "((`s.a`.`x` + 1) - (`s.a`.`user_id` + 2)) * 10",
        ),
    ],
)
def test_expansion_keeps_operator_precedence(sql: str, expected: str) -> None:
    output = _root_outputs(f"INSERT OVERWRITE TABLE m.t {sql}")["r"]

    assert output["expanded_expression"] == expected


# ------------------------------- the qualify-fallback substitution (1.13-e)

# qualify refuses a LATERAL VIEW alias equal to the table alias (common in Hive code), so
# the unqualified substitution is the path that expands `status` here.
FALLBACK_SQL = (
    "INSERT OVERWRITE TABLE m.t "
    "SELECT CASE WHEN status = 0 THEN 'pending status here' ELSE 'other' END AS st, e "
    "FROM (SELECT l.x + 1 AS status, l.arr FROM s.log l) t "
    "LATERAL VIEW EXPLODE(t.arr) t AS e"
)


def test_the_unqualified_fallback_leaves_a_string_literal_unchanged() -> None:
    output = _root_outputs(FALLBACK_SQL)["st"]

    assert output["expanded_expression"] == (
        "CASE WHEN (`s.log`.`x` + 1) = 0 THEN 'pending status here' ELSE 'other' END"
    )


# ------------------------------------------------------ keyword repair (1.13-c)


def test_keyword_repair_leaves_a_string_literal_unchanged() -> None:
    repaired, quoted = repair_keyword_identifiers(
        "INSERT OVERWRITE TABLE m.t "
        "SELECT using, IF(a.x = 1, 'no using here', 'ok') AS s FROM s.a a"
    )

    assert quoted == ("using",)
    assert "'no using here'" in repaired
    assert "SELECT `using`," in repaired


def test_keyword_repair_leaves_a_comment_unchanged() -> None:
    repaired, quoted = repair_keyword_identifiers(
        "INSERT OVERWRITE TABLE m.t\n"
        "SELECT using -- using is a column here\n"
        "FROM s.a a"
    )

    assert quoted == ("using",)
    assert "-- using is a column here" in repaired


def test_keyword_repair_end_to_end_keeps_the_literal_value() -> None:
    output = _root_outputs(
        "INSERT OVERWRITE TABLE m.t "
        "SELECT using, IF(a.x = 1, 'no using here', 'ok') AS s FROM s.a a"
    )["s"]

    assert "'no using here'" in output["expression"]
    assert "'no using here'" in output["expanded_expression"]


# ------------------------------------------------------- display rewrite (1.13-d)


def test_display_keeps_a_struct_segment_named_like_the_alias() -> None:
    document = to_lineage_dict(
        parse_scope_lineage(
            "INSERT OVERWRITE TABLE m.t SELECT u.profile.u.name AS n FROM s.users u",
            "hygiene",
            schema=SCHEMA,
        )
    )
    output = document["scopes"]["ROOT"]["outputs"][0]

    assert output["display_expression"] == "`profile`.`u`.`name`"


def test_sentinel_display_still_drops_a_single_source_qualifier() -> None:
    document = to_lineage_dict(
        parse_scope_lineage(
            "INSERT OVERWRITE TABLE m.t SELECT CONCAT('u.k', a.user_id) AS n FROM s.a a",
            "hygiene",
            schema=SCHEMA,
        )
    )
    output = document["scopes"]["ROOT"]["outputs"][0]

    assert output["display_expression"] == "CONCAT('u.k', `user_id`)"


# ---------------------------------- expansion of a struct path naming the alias (1.13-d)


def test_expansion_keeps_a_struct_segment_named_like_the_alias() -> None:
    # The display rewrite got its preceding-character guard in WP4; the expansion did not,
    # so the `u`.`name` inside the STRUCT path was read as the alias `u`'s column `name`
    # and rewritten to `s.users`.`name`, which also published a physical field that does
    # not exist.
    output = _root_outputs(
        "INSERT OVERWRITE TABLE m.t SELECT u.profile.u.name AS n FROM s.users u"
    )["n"]

    assert output["expanded_expression"] == "`s.users`.`profile`.`u`.`name`"
    assert _physical(output) == {"s.users.profile"}


def test_physical_expansion_leaves_a_string_literal_unchanged() -> None:
    # The physical-field rewrite (a column read straight from a table alias) is a separate
    # text replacement from the upstream-expression one WP4 fixed; it rewrote literals too.
    output = _root_outputs(
        "INSERT OVERWRITE TABLE m.t SELECT CONCAT('see a.x and `a`.`x`', a.x) AS n FROM s.a a"
    )["n"]

    assert output["expanded_expression"] == "CONCAT('see a.x and `a`.`x`', `s.a`.`x`)"


def test_sentinel_expansion_of_a_plain_struct_path() -> None:
    output = _root_outputs("INSERT OVERWRITE TABLE m.t SELECT u.profile.name AS n FROM s.users u")["n"]

    assert output["expanded_expression"] == "`s.users`.`profile`.`name`"
    assert _physical(output) == {"s.users.profile"}


# ------------------------------------------- expression_features.operators (WP4 follow-up)


def test_operators_ignore_a_comment_and_a_literal() -> None:
    features = _expression_features(
        "expression", "CONCAT(`a`.`x`, '-') /* rate * 100 / n */", []
    )

    assert features["operators"] == []


def test_sentinel_operators_still_list_code_operators() -> None:
    features = _expression_features("expression", "`a`.`x` * 2 - `a`.`y` / 3 /* x */", [])

    assert features["operators"] == ["-", "*", "/"]
