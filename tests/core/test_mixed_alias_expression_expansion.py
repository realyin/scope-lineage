"""One expression, two kinds of alias — and only one kind was ever expanded.

``_resolved_scope_alias_expression_fact`` walks an expression's qualified references and
inlines each upstream scope output. A reference to a physical table has no scope output to
inline, and the function skipped it outright: the alias stayed in the text and its field
never reached the physical source list. Because the function then filters the source list
to fields the text mentions, the field is unrecoverable afterwards.

An expression made only of physical references returns None, so a later candidate handles
it; an expression made only of scope references works. Only the mix produces a result that
looks complete and is not.
"""

from __future__ import annotations

from scope_lineage import parse_scope_lineage
from scope_lineage.scope import scope_facts
from scope_lineage.scope.scope_types import ScopeOutputField


SCHEMA = {
    "ods.s": ["id", "a"],
    "ods.f": ["id", "b"],
    "mart.t": ["x"],
}

# The CASE arm references the CTE alias and the joined physical table in one expression,
# which is what routes it through the alias-expansion helper as a mixed reference set.
MIXED_ALIAS_SQL = """
INSERT INTO mart.t
WITH c AS (SELECT id, a FROM ods.s)
SELECT ROW_NUMBER() OVER (
  PARTITION BY CASE WHEN p.a IS NULL THEN 1 WHEN NOT f.b IS NULL THEN 2 ELSE 3 END
  ORDER BY p.id
) AS x
FROM c p
LEFT JOIN ods.f f ON p.id = f.id
"""


def _root_output(result):
    return result.scopes["ROOT"].outputs[0]


def test_a_physical_reference_beside_a_scope_reference_reaches_its_field() -> None:
    result = parse_scope_lineage(MIXED_ALIAS_SQL, "mixed_alias", schema=SCHEMA)

    resolution = _root_output(result).expression_resolution
    assert sorted(
        (field["table"], field["field"])
        for field in resolution["physical_source_fields"]
    ) == [("ods.f", "b"), ("ods.s", "a"), ("ods.s", "id")]
    assert resolution["missing_reasons"] == []
    assert result.diagnostics.lineage_fact_gaps == []


def test_the_physical_alias_is_rewritten_in_the_expanded_expression() -> None:
    """Adding the field is not enough on its own.

    The unexpanded-alias check reads the expanded text, so a fix that collected the field
    but left ``f.b`` in place would report the gap anyway. This pins the text.
    """
    result = parse_scope_lineage(MIXED_ALIAS_SQL, "mixed_alias", schema=SCHEMA)

    expanded = _root_output(result).expanded_expression
    assert "`ods.f`.`b`" in expanded
    assert "`f`.`b`" not in expanded


def _upstream_output() -> ScopeOutputField:
    output = ScopeOutputField(name="a", transform="DIRECT")
    output.expression_resolution = {
        "status": "resolved",
        "physical_source_fields": [{"table": "ods.s", "field": "a"}],
        "generated_sources": [],
        "expanded_expression": "`ods.s`.`a`",
        "source_kind": "physical",
    }
    return output


def test_alias_expansion_handles_scope_physical_and_mixed_reference_sets() -> None:
    """The three shapes, pinned at the helper itself.

    Only the mixed shape was wrong, which is why every whole-statement reproduction
    attempt that used one kind of alias came back clean.
    """
    lookup = {("cte:c", "a"): _upstream_output()}

    scope_only = scope_facts._resolved_scope_alias_expression_fact(
        "CASE WHEN `p`.`a` IS NULL THEN 1 ELSE 2 END", {"p": "cte:c"}, lookup
    )
    assert scope_only["expanded_expression"] == (
        "CASE WHEN `ods.s`.`a` IS NULL THEN 1 ELSE 2 END"
    )
    assert [
        (field["table"], field["field"])
        for field in scope_only["expression_resolution"]["physical_source_fields"]
    ] == [("ods.s", "a")]

    # Nothing to inline: the helper declines so a later candidate can try.
    assert (
        scope_facts._resolved_scope_alias_expression_fact(
            "CASE WHEN `f`.`b` IS NULL THEN 1 ELSE 2 END", {"f": "ods.f"}, lookup
        )
        is None
    )

    mixed = scope_facts._resolved_scope_alias_expression_fact(
        "CASE WHEN `p`.`a` IS NULL THEN `f`.`b` ELSE 2 END",
        {"p": "cte:c", "f": "ods.f"},
        lookup,
    )
    assert mixed["expanded_expression"] == (
        "CASE WHEN `ods.s`.`a` IS NULL THEN `ods.f`.`b` ELSE 2 END"
    )
    assert sorted(
        (field["table"], field["field"])
        for field in mixed["expression_resolution"]["physical_source_fields"]
    ) == [("ods.f", "b"), ("ods.s", "a")]


def test_an_unresolvable_qualifier_keeps_its_missing_reason() -> None:
    """Rewriting must stay evidence-driven.

    An implementation that rewrote every unknown qualifier into a table name would make
    this gap disappear while inventing the table it names.
    """
    lookup = {("cte:c", "a"): _upstream_output()}

    mixed = scope_facts._resolved_scope_alias_expression_fact(
        "CASE WHEN `p`.`a` IS NULL THEN `nobody`.`b` ELSE 2 END",
        {"p": "cte:c"},
        lookup,
    )
    assert "`nobody`.`b`" in mixed["expanded_expression"]
    assert [
        (field["table"], field["field"])
        for field in mixed["expression_resolution"]["physical_source_fields"]
    ] == [("ods.s", "a")]
