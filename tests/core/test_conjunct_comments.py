"""A comment beside one conjunct of a WHERE belongs to that conjunct, not to its siblings.

The contract splits a WHERE / HAVING into ``conjuncts[]``; the profile publishes one rule
per conjunct. The comments used to be the whole block's list, handed to every rule, so a
note written beside ``typ = '1'`` read as the explanation of ``dt = '…'`` too. Two layers
carry the fix:

- **contract** -- each conjunct publishes ``comments``: the comments inside its own
  expression, led by any comment sqlglot attached to the ``And`` node that joined it on.
  sqlglot attaches a comment written on its own line *above* ``and b = 2`` to that
  ``And``, and splitting on AND used to drop it, so no conjunct's text carried it;
- **profile** -- a rule takes its conjunct's ``comments``; only what the block carries
  beyond every conjunct's own (a comment attached to the ``WHERE`` / ``HAVING`` itself)
  is said of the whole condition and goes to every rule.

A comment at the end of a line attaches to the last node before it, so it goes to the
last predicate on that line (sqlglot's attachment, kept as it is). Every fixture is
synthetic.
"""

from __future__ import annotations

import pytest

from scope_lineage import build_semantic_profile
from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {
    "ods.src": ["k", "v", "w", "typ", "x", "y", "z", "dt"],
    "dw.t_out": ["k", "v", "dt"],
}


def _contract(sql: str) -> dict:
    return to_lineage_dict(parse_scope_lineage(sql, "conjunct_comments", schema=SCHEMA))


def _conjuncts(document: dict, logic_type: str = "filter") -> list[dict]:
    return [
        conjunct
        for scope in document["scopes"].values()
        for block in scope.get("logic_blocks") or []
        if block.get("logic_type") == logic_type
        for conjunct in (block.get("filter_predicate_detail") or {}).get("conjuncts") or []
    ]


def _rule_comments(document: dict, kind: str = "filter") -> list[list[str]]:
    profile = build_semantic_profile(document)
    return [
        rule.get("sql_comments") or []
        for rule in profile["rules"]
        if rule["kind"] == kind
    ]


def _where(body: str) -> str:
    return f"INSERT OVERWRITE TABLE dw.t_out SELECT a.k, a.v, a.dt FROM ods.src a WHERE {body}"


# --- the contract ------------------------------------------------------------------------

SHAPES = [
    pytest.param(
        "a.x = 1 -- n\n and a.y = 2",
        [["n"], []],
        id="line-end comment goes to the predicate it ends",
    ),
    pytest.param(
        "a.x = 1\n -- n\n and a.y = 2",
        [[], ["n"]],
        id="own-line comment above an and goes to the predicate below",
    ),
    pytest.param(
        "a.x = 1\n -- ny\n and a.y = 2\n -- nz\n and a.z = 3",
        [[], ["ny"], ["nz"]],
        id="two own-line comments each go to the predicate below",
    ),
    pytest.param(
        "a.x = 1 and -- n\n a.y = 2",
        [[], ["n"]],
        id="comment after the and goes to the predicate it introduces",
    ),
    pytest.param(
        "a.x = 1\n -- n\n and (a.y = 2 or a.z = 3)",
        [[], ["n"]],
        id="a parenthesised OR is one predicate",
    ),
]


@pytest.mark.parametrize(("body", "expected"), SHAPES)
def test_each_conjunct_publishes_its_own_comments(body: str, expected: list[list[str]]):
    conjuncts = _conjuncts(_contract(_where(body)))
    assert [conjunct.get("comments", []) for conjunct in conjuncts] == expected


def test_a_conjunct_without_comments_has_no_comments_key():
    conjuncts = _conjuncts(_contract(_where("a.x = 1 and a.y = 2")))
    assert conjuncts and all("comments" not in conjunct for conjunct in conjuncts)


def test_a_comment_on_the_where_itself_is_no_conjunct_s_own():
    document = _contract(_where("-- whole\n a.x = 1 and a.y = 2"))
    assert all("comments" not in conjunct for conjunct in _conjuncts(document))


def test_a_having_splits_its_comments_the_same_way():
    sql = (
        "INSERT OVERWRITE TABLE dw.t_out SELECT a.k, max(a.v) AS v, max(a.dt) AS dt "
        "FROM ods.src a GROUP BY a.k HAVING count(*) > 1\n -- n\n and sum(a.w) > 2"
    )
    conjuncts = _conjuncts(_contract(sql), "having")
    assert [conjunct.get("comments", []) for conjunct in conjuncts] == [[], ["n"]]


# --- the profile ---------------------------------------------------------------------------


def test_a_line_end_comment_stays_on_its_own_rule():
    sql = (
        "INSERT OVERWRITE TABLE dw.t_out SELECT a.k, a.v, '2026-01-01' AS dt FROM ("
        "SELECT k, v FROM ods.src\n"
        "WHERE typ = '1' -- type note\n"
        "  AND dt = '2026-01-01'\n"
        ") a"
    )
    assert _rule_comments(_contract(sql)) == [["type note"], []]


def test_an_own_line_comment_goes_to_the_rule_below_it_only():
    body = "a.x = 1\n -- note for y\n and a.y = 2\n and a.z = 3 -- note for z"
    document = _contract(_where(body))
    assert _rule_comments(document) == [[], ["note for y"], ["note for z"]]


def test_a_comment_on_the_whole_where_goes_to_every_rule():
    document = _contract(_where("-- note for the whole where\n a.x = 1 and a.y = 2"))
    assert _rule_comments(document) == [
        ["note for the whole where"],
        ["note for the whole where"],
    ]


def test_a_single_predicate_where_keeps_its_comment():
    document = _contract(_where("a.x = 1 -- only"))
    assert _rule_comments(document) == [["only"]]


def test_a_contract_without_conjunct_comments_falls_back_to_each_expression():
    """An older contract has no ``comments`` on a conjunct: the expression's own still count."""
    document = _contract(_where("a.x = 1 -- n\n and a.y = 2"))
    for conjunct in _conjuncts(document):
        conjunct.pop("comments", None)
    assert _rule_comments(document) == [["n"], []]
