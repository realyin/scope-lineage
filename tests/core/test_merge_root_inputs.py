"""A MERGE's ROOT scope has to declare the relation it reads.

Input edges are populated by walking the sqlglot scopes, and a MERGE's ROOT is a synthetic
scope with none of its own — so it declared no inputs at all. Every consumer of
``alias_source_bindings`` then treats ``source`` as an unknown alias, even though column
resolution has already bound it, and an expression that has to resolve a qualifier by alias
reports a root-impact gap for a fact the parser already holds.

The target relation is declared without an alias;
``test_a_correlated_target_reference_is_not_reported_as_an_unexpanded_alias`` below pins
why it must stay alias-less.
"""

from __future__ import annotations

from scope_lineage import parse_scope_lineage


SCHEMA = {
    "ods.source": ["id", "attribution_id"],
    "mart.target": ["id", "attr_id"],
}

# The USING relation sits one query block further away than the target, which is what
# forces the expression resolver to go through the alias bindings.
NESTED_USING_SQL = """
WITH tmp AS (SELECT id, attribution_id FROM ods.source)
MERGE INTO mart.target target
USING (SELECT a_.id, a_.attribution_id FROM (SELECT id, attribution_id FROM tmp) a_) source
ON target.id = source.id
WHEN MATCHED THEN UPDATE SET
  target.attr_id = COALESCE(target.attr_id, source.attribution_id)
"""

UNKNOWN_USING_SCHEMA_SQL = """
MERGE INTO mart.target target
USING (SELECT id, attribution_id FROM tmp_external) source
ON target.id = source.id
WHEN MATCHED THEN UPDATE SET
  target.attr_id = COALESCE(target.attr_id, source.attribution_id)
"""


def _bindings(result) -> list[tuple[str, str, str]]:
    return [
        (binding["alias"], binding["source_id"], binding["source_type"])
        for binding in result.scopes["ROOT"].alias_source_bindings
    ]


def test_merge_root_declares_both_relations_it_reads() -> None:
    result = parse_scope_lineage(NESTED_USING_SQL, "merge_nested_using", schema=SCHEMA)

    # "from" rather than new position values: the contract constrains that field to a
    # closed set, and both relations are ones this statement reads from.
    assert [
        (edge.alias, edge.source_id, edge.position)
        for edge in result.scopes["ROOT"].input_edges
    ] == [
        ("source", "subq:source", "from"),
        # Appended, not prepended: input_ref_id is positional, so inserting ahead of the
        # USING relation would renumber a cross-reference consumers already hold.
        ("target", "mart.target", "from"),
    ]
    # The alias is on the input ref too, which is what lets a consumer map target.x back
    # to the relation it names.
    assert [
        (ref["alias"], ref["source_id"]) for ref in result.scopes["ROOT"].input_source_refs
    ] == [("source", "subq:source"), ("target", "mart.target")]
    # It is deliberately absent from the binding table: those drive alias expansion, and
    # the correlated-reference test below pins why the target must stay out of it.
    assert _bindings(result) == [("source", "subq:source", "scope")]


def test_a_merge_expression_over_both_relations_resolves_without_a_gap() -> None:
    result = parse_scope_lineage(NESTED_USING_SQL, "merge_nested_using", schema=SCHEMA)

    output = next(
        item for item in result.scopes["ROOT"].outputs if item.name == "attr_id"
    )
    assert output.expression_resolution["missing_reasons"] == []
    assert sorted(
        (field["table"], field["field"])
        for field in output.expression_resolution["physical_source_fields"]
    ) == [("mart.target", "attr_id"), ("ods.source", "attribution_id")]
    assert result.diagnostics.lineage_fact_gaps == []


def test_a_using_relation_without_schema_still_binds_its_alias() -> None:
    """Missing column metadata is not a reason to lose the alias binding itself."""
    result = parse_scope_lineage(
        UNKNOWN_USING_SCHEMA_SQL, "merge_unknown_using_schema", schema=SCHEMA
    )

    assert _bindings(result) == [("source", "subq:source", "scope")]
    assert not any(
        reason.startswith("alias_not_bound_to_input_source:")
        for output in result.scopes["ROOT"].outputs
        for reason in (output.expression_resolution or {}).get("missing_reasons") or []
    )


def test_an_unaliased_using_relation_falls_back_to_source() -> None:
    result = parse_scope_lineage(
        """
        MERGE INTO mart.target target
        USING ods.source
        ON target.id = ods.source.id
        WHEN MATCHED THEN UPDATE SET target.attr_id = ods.source.attribution_id
        """,
        "merge_unaliased_using",
        schema=SCHEMA,
    )

    aliases = [alias for alias, _source_id, _kind in _bindings(result)]
    assert aliases == ["source"]


def test_a_correlated_target_reference_is_not_reported_as_an_unexpanded_alias() -> None:
    """Why the target relation is not declared as a ROOT input.

    A MERGE action's scalar subquery keeps its correlated ``target.id`` on purpose — that
    is what ``_protect_merge_correlated_target_refs`` exists for. It sits inside a scalar
    subquery's text, so no rewrite in the ROOT scope reaches it; putting ``target`` in the
    binding table would make the unexpanded-alias check read that deliberate reference as
    an expansion that failed, trading one wrong gap for another.

    The relation is therefore declared as an input, alias included, but kept out of the
    binding table — "declared, not alias-expanded", said with the fields the contract
    already has.
    """
    result = parse_scope_lineage(
        """
        WITH staged AS (SELECT e.id, e.event_type FROM ods.events e)
        MERGE INTO mart.event_target target
        USING (SELECT id, event_type FROM staged) source
        ON target.id = source.id
        WHEN MATCHED THEN UPDATE SET
          target.event_type = source.event_type,
          target.account_key = (
            SELECT MAX(lookup.name) FROM dim.lookup lookup WHERE lookup.id = target.id
          )
        """,
        "merge_correlated_target_ref",
        schema={
            "ods.events": ["id", "event_type"],
            "dim.lookup": ["id", "name"],
            "mart.event_target": ["id", "event_type", "account_key"],
        },
    )

    assert [alias for alias, _source_id, _kind in _bindings(result)] == ["source"]
    assert result.diagnostics.lineage_fact_gaps == []


def test_merge_root_inputs_are_order_stable_across_runs() -> None:
    first = parse_scope_lineage(NESTED_USING_SQL, "merge_nested_using", schema=SCHEMA)
    second = parse_scope_lineage(NESTED_USING_SQL, "merge_nested_using", schema=SCHEMA)

    assert _bindings(first) == _bindings(second)
