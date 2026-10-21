"""A ``*`` the parser could not expand is not a constant.

``SELECT * FROM db.unknown`` has no schema to expand against, so the scope keeps one
``*`` output. Its expression resolution called it a resolved CONSTANT whose value is
``*``: the text ``*`` holds no column node, and "no column refs" was read as "a literal".
That claim then stood in for every column read through the star that the scope did not
list itself -- a WHERE / JOIN on ``s.y`` traced to "the constant ``*``", complete.
"""

from __future__ import annotations

from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.scope.task_lineage import parse_task_lineage

SCHEMA = {"db.dim": ["y", "v"], "db.tgt": ["o", "v"]}


def test_an_unexpanded_star_output_claims_no_constant() -> None:
    result = parse_scope_lineage(
        "INSERT OVERWRITE TABLE db.tgt SELECT s.o FROM (SELECT * FROM db.unknown) s", "t",
        schema={},
    )
    [star] = [output for output in result.scopes["subq:s"].outputs if output.name == "*"]

    assert star.expression_resolution["generated_sources"] == []
    assert star.expression_resolution["source_kind"] != "generated"


def test_a_condition_read_through_an_unexpanded_star_is_not_traced_complete() -> None:
    result = parse_task_lineage(
        "INSERT OVERWRITE TABLE db.tgt SELECT s.o, d.v "
        "FROM (SELECT * FROM db.unknown) s JOIN db.dim d ON s.y = d.y",
        task_name="t",
        schema=SCHEMA,
    )

    assert [
        (gap["scope_id"], gap["column"])
        for gap in result.diagnostics["lineage_fact_gaps"]
        if gap["gap_type"] == "row_condition_source_unresolved"
    ] == [("subq:s", "y")]
