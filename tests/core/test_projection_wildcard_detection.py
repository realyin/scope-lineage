"""``*`` means two different things, and only one of them is a gap.

``SELECT *`` that could not be expanded is a genuine hole: the target columns are unknown.
``COUNT(*)`` is the opposite — a resolved fact that the value depends on the whole row.
The task layer treated any source column named ``*`` as the first kind, so a statement whose
lineage was fully resolved was published as ``partial`` with a root-impact gap asking for
"source schema for wildcard expansion" that no metadata could ever satisfy.
"""

from __future__ import annotations

from scope_lineage.scope.task_lineage import (
    _projection_state_missing_reasons,
    parse_task_lineage,
)


SCHEMA = {
    "ods.events": ["app_code"],
    "mart.summary": ["app_code", "call_cnt"],
}


def _gap_types(result) -> list[str]:
    return [gap.get("gap_type") for gap in result.diagnostics["lineage_fact_gaps"]]


def test_an_aggregate_over_the_whole_row_is_not_an_unexpanded_wildcard() -> None:
    result = parse_task_lineage(
        "INSERT INTO mart.summary "
        "SELECT app_code, COUNT(*) AS call_cnt FROM ods.events GROUP BY app_code",
        task_name="aggregate_star",
        schema=SCHEMA,
    )

    assert _gap_types(result) == []
    assert result.analysis_status == {"status": "complete", "blocking_reasons": []}


def test_a_window_count_over_the_whole_row_is_not_an_unexpanded_wildcard() -> None:
    """``COUNT(*) OVER ()`` — an empty window is what keeps the star a row reference.

    With a PARTITION BY the expression resolves through the partition column and produces
    no star source at all, so that shape cannot pin this behaviour.
    """
    result = parse_task_lineage(
        "INSERT INTO mart.summary "
        "SELECT app_code, COUNT(*) OVER () AS call_cnt FROM ods.events",
        task_name="window_star",
        schema=SCHEMA,
    )

    assert _gap_types(result) == []
    assert result.analysis_status["status"] == "complete"


def test_a_wildcard_that_could_not_be_expanded_is_still_reported() -> None:
    result = parse_task_lineage(
        "INSERT INTO mart.summary SELECT * FROM ods.undocumented",
        task_name="real_wildcard",
        schema={"mart.summary": ["app_code", "call_cnt"]},
    )

    assert _gap_types(result) == ["projection_wildcard_unexpanded"]
    assert result.diagnostics["lineage_fact_gaps"][0]["root_impact"] is True
    assert result.analysis_status["status"] == "partial"


def _written(column: str, transform: str) -> dict[str, list[dict]]:
    return {
        column: [
            {
                "source_kind": "physical_field",
                "table": "ods.events",
                "column": "*",
                "transform": transform,
            }
        ]
    }


class _ResultWithoutGaps:
    class _Diagnostics:
        lineage_fact_gaps: list[dict] = []

    diagnostics = _Diagnostics()


def test_the_wildcard_check_distinguishes_the_two_meanings_of_star() -> None:
    """The three shapes, pinned at the check itself.

    The target column name is the discriminator the check already had; the source
    transform is the one it was missing.
    """
    result = _ResultWithoutGaps()

    # A projection that stayed a wildcard names its target column "*".
    assert _projection_state_missing_reasons(
        result, _written("*", "EXPAND_ALL")
    ) == ["projection_wildcard_unexpanded"]

    # A named column fed by an unexpanded wildcard is still a wildcard.
    assert _projection_state_missing_reasons(
        result, _written("call_cnt", "EXPAND_ALL")
    ) == ["projection_wildcard_unexpanded"]

    # A named column fed by a whole-row aggregate is a resolved fact.
    assert _projection_state_missing_reasons(result, _written("call_cnt", "AGGREGATE")) == []
    assert _projection_state_missing_reasons(result, _written("call_cnt", "WINDOW")) == []
