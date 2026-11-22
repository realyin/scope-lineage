"""An expression's resolution must not settle a reference the column layer left ambiguous.

``WITH c AS (...) SELECT CONCAT('p', v) FROM c JOIN s.b b`` with no metadata for ``s.b``:
the bare ``v`` could come from either side, so the column's source is ``AMBIGUOUS`` and the
end-to-end row is ``trace_complete: false`` (LINEAGE-002). sqlglot's ``qualify`` had already
rewritten the text to ``c.v`` (the only source whose columns it knew), and the internal-scope
expansion read that text as proof: the output's ``expression_resolution`` said ``resolved``
with ``s.a.x`` as its physical field and ``consumer_readiness`` said ``ready`` -- the same
field told two stories.

Every name here is synthetic.
"""

from __future__ import annotations

from scope_lineage.scope.task_lineage import parse_task_lineage

CTE_JOIN = (
    "WITH c AS (SELECT a.k, a.x AS v FROM s.a a) "
    "INSERT OVERWRITE TABLE m.t SELECT CONCAT('p', {ref}) AS v FROM c JOIN s.b b ON c.k = b.k"
)
SCHEMA = {"s.a": ["k", "x"], "m.t": ["v"]}


def _root_output(result) -> dict:
    [statement] = result.statement_lineage.values()
    [output] = statement["scopes"]["ROOT"]["outputs"]
    return output


def _e2e(result) -> dict:
    [row] = [row for row in result.end_to_end_lineage if row["table"] == "m.t"]
    return row


def test_a_bare_column_a_joined_table_without_metadata_may_own_is_not_resolved() -> None:
    result = parse_task_lineage(CTE_JOIN.format(ref="v"), "t", schema=SCHEMA)

    output = _root_output(result)
    assert output["sources"][0]["scope"] == "AMBIGUOUS"
    resolution = output["expression_resolution"]
    assert resolution["status"] != "resolved"
    assert resolution.get("physical_source_fields") in (None, [])
    assert "s.a" not in (output.get("expanded_expression") or "")
    assert output["consumer_readiness"]["status"] != "ready"
    assert _e2e(result)["trace_complete"] is False


def test_metadata_that_rules_the_other_table_out_still_resolves_it() -> None:
    result = parse_task_lineage(
        CTE_JOIN.format(ref="v"), "t", schema={**SCHEMA, "s.b": ["k", "y"]},
    )

    resolution = _root_output(result)["expression_resolution"]
    assert resolution["status"] == "resolved"
    assert resolution["physical_source_fields"] == [{"table": "s.a", "field": "x"}]
    assert _e2e(result)["trace_complete"] is True


def test_a_qualified_reference_resolves_without_metadata() -> None:
    result = parse_task_lineage(CTE_JOIN.format(ref="c.v"), "t", schema=SCHEMA)

    output = _root_output(result)
    assert output["expression_resolution"]["status"] == "resolved"
    assert output["expanded_expression"] == "CONCAT('p', `s.a`.`x`)"
    assert _e2e(result)["trace_complete"] is True
