"""A truncated expansion is a text budget, not a lost source (Q2).

The expansion budget stops inlining upstream expression text once a guard is reached. Up
to now the statement then carried an ``expression_expansion_bounded`` lineage fact gap,
which blocks the task: ``analysis_status`` went ``partial`` and the field's chain reported
``trace_status=incomplete``, although the walk knew every physical column that feeds the
output -- only the concatenated *text* was too big to publish.

The guard is right to stop; the verdict was wrong. When the sources are resolved, a
tripped guard is now a statement-level **warning** (``expansion_truncated``): the expanded
text is published truncated with a trailing marker and flagged with
``expansion_truncated`` / ``expansion_limit`` on the output and on the mapping chain, and
the task stays ``complete``. A gap remains only where the sources themselves are unknown.

Synthetic SQL throughout; the budget is shrunk the way the other budget tests shrink it,
by monkeypatching the module constant.
"""

from __future__ import annotations

import pytest

from scope_lineage import parse_task_lineage
from scope_lineage.scope import expansion_budget


#: One CTE output whose CASE expands to more text than the shrunken ceiling allows, read
#: by a ROOT output that also reads a small field: the sources of `graded_total` are
#: exactly the three source columns, and only the text of the CASE is too big to inline.
_BRANCHES = " ".join(
    f"WHEN grade_flag = {index} THEN amount + {index}" for index in range(1, 9)
)
SQL = f"""
WITH staged AS (
  SELECT
    CASE {_BRANCHES} ELSE amount END AS graded_amount,
    region_code
  FROM ods.source_events
)
INSERT OVERWRITE TABLE mart.graded_report
SELECT s.graded_amount + LENGTH(s.region_code) AS graded_total,
       s.region_code AS region_code
FROM staged s
"""

SCHEMA = {"ods.source_events": ["grade_flag", "amount", "region_code"]}

#: Small enough that the CASE cannot be inlined, large enough that everything else in the
#: statement expands normally -- so the case under test is one guarded output, not a run
#: where nothing expanded.
SHRUNKEN_MAX_CHARS = 300


@pytest.fixture()
def shrunken_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(expansion_budget, "EXPANSION_MAX_CHARS", SHRUNKEN_MAX_CHARS)


def _parse():
    return parse_task_lineage(SQL, task_name="expansion_truncation", schema=SCHEMA)


def _statement(result) -> dict:
    return next(iter(result.statement_lineage.values()))


def _root_output(result, name: str) -> dict:
    outputs = _statement(result)["scopes"]["ROOT"]["outputs"]
    return next(output for output in outputs if output["name"] == name)


def _chain(result, field: str) -> dict:
    chains = _statement(result)["field_mapping_chains"]
    return next(chain for chain in chains if chain["target_field"] == field)


def _capacity_gaps(result) -> list[dict]:
    return [
        gap
        for gap in result.diagnostics.get("lineage_fact_gaps") or []
        if gap.get("gap_bucket") == "capacity_guard"
    ]


def _truncation_warnings(result) -> list[dict]:
    return [
        warning
        for lineage in result.statement_lineage.values()
        for warning in (lineage.get("diagnostics") or {}).get("warnings") or []
        if warning.get("type") == "expansion_truncated"
    ]


def test_a_guarded_output_keeps_its_sources_and_the_task_stays_complete(
    shrunken_budget,
) -> None:
    """The walk resolved every physical column; only the text did not fit."""
    result = _parse()

    output = _root_output(result, "graded_total")
    resolution = output["expression_resolution"]
    assert output["expansion_stop_reason"] == "max_chars"
    assert resolution["status"] == "resolved"
    assert resolution["missing_reasons"] == []
    assert {item["field"] for item in resolution["physical_source_fields"]} == {
        "grade_flag",
        "amount",
        "region_code",
    }
    assert _capacity_gaps(result) == []
    assert result.analysis_status == {"status": "complete", "blocking_reasons": []}


def test_the_chain_and_end_to_end_lineage_stay_resolved(shrunken_budget) -> None:
    """A text budget must not turn a fully traced field into an incomplete trace."""
    result = _parse()

    chain = _chain(result, "graded_total")
    assert chain["trace_status"] == "complete"
    assert chain["chain_status"] == "resolved"
    assert chain["missing_reasons"] == []
    assert set(chain["root_source_fields"]) == {
        "ods.source_events.grade_flag",
        "ods.source_events.amount",
        "ods.source_events.region_code",
    }

    edge = next(
        item
        for item in result.end_to_end_lineage
        if item["column"] == "graded_total"
    )
    assert edge["trace_complete"] is True
    assert edge["missing_reasons"] == []


def test_the_published_text_says_it_was_truncated(shrunken_budget) -> None:
    """Silent shortening is the failure mode: the text must carry its own marker."""
    result = _parse()

    output = _root_output(result, "graded_total")
    expanded = output["expanded_expression"]
    assert expanded.endswith(
        expansion_budget.expansion_truncation_marker("max_chars", SHRUNKEN_MAX_CHARS)
    )
    assert len(expanded) <= SHRUNKEN_MAX_CHARS
    assert output["expansion_truncated"] is True
    assert output["expansion_limit"] == {"guard": "max_chars", "limit": SHRUNKEN_MAX_CHARS}
    assert output["unexpanded_refs"], "被放弃的引用仍是继续追踪的指针"

    chain = _chain(result, "graded_total")
    assert chain["expansion_truncated"] is True
    assert chain["expansion_limit"] == {"guard": "max_chars", "limit": SHRUNKEN_MAX_CHARS}


def test_the_event_is_a_statement_warning(shrunken_budget) -> None:
    """Recorded where a reader looks for "something was capped", not as a missing fact."""
    result = _parse()

    warnings = _truncation_warnings(result)
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning["scope"] == "ROOT"
    assert "graded_total" in warning["msg"]
    assert "max_chars" in warning["msg"]
    assert str(SHRUNKEN_MAX_CHARS) in warning["msg"]


def test_the_default_budget_leaves_the_same_statement_untouched() -> None:
    """The flags and the marker exist only where a guard actually fired."""
    result = _parse()

    output = _root_output(result, "graded_total")
    assert "expansion_truncated" not in output
    assert "expansion_limit" not in output
    assert "expansion truncated" not in output["expanded_expression"]
    assert "expansion_status" not in output
    assert _truncation_warnings(result) == []
    assert result.analysis_status["status"] == "complete"


def test_the_substitution_guard_is_reported_the_same_way() -> None:
    """The other guard an operator can move, with its own number in the warning."""
    result = parse_task_lineage(
        SQL, task_name="expansion_truncation", schema=SCHEMA, expansion_limit=1
    )

    output = _root_output(result, "graded_total")
    assert output["expansion_truncated"] is True
    assert output["expansion_limit"] == {"guard": "max_substitutions", "limit": 1}
    assert _capacity_gaps(result) == []
    assert result.analysis_status["status"] == "complete"
    warning = _truncation_warnings(result)[0]
    assert "max_substitutions" in warning["msg"]
    # The guard that has a flag says so, where the reader already is.
    assert "--expansion-limit" in warning["msg"]


def test_the_marker_makes_room_for_itself_under_the_size_guard() -> None:
    """A note saying the text was cut must not be what pushes it over the ceiling."""
    marked = expansion_budget.truncated_expansion("x" * 500, "max_chars", 120)

    assert len(marked) <= 120
    assert marked.startswith("x")
    assert marked.endswith(expansion_budget.expansion_truncation_marker("max_chars", 120))


def test_the_substitution_guards_number_is_not_a_length() -> None:
    """``max_substitutions`` counts references, so it can say nothing about characters."""
    text = "`ods.source_events`.`amount`"
    marked = expansion_budget.truncated_expansion(text, "max_substitutions", 3)

    assert marked == (
        f"{text} "
        + expansion_budget.expansion_truncation_marker("max_substitutions", 3)
    )


#: The same guarded shape, except the output also reads a field the upstream scope does
#: not produce: its source set is genuinely incomplete, not merely unprinted.
UNRESOLVED_SQL = f"""
WITH staged AS (
  SELECT
    CASE {_BRANCHES} ELSE amount END AS graded_amount,
    region_code
  FROM ods.source_events
)
INSERT OVERWRITE TABLE mart.graded_report
SELECT s.graded_amount + LENGTH(s.not_a_column) AS graded_total
FROM staged s
"""


def test_an_unresolved_source_still_leaves_a_gap_and_a_partial_task(
    shrunken_budget,
) -> None:
    """Only the *text* is forgiven. A source nobody could name is still a fact gap."""
    result = parse_task_lineage(
        UNRESOLVED_SQL, task_name="expansion_truncation_gap", schema=SCHEMA
    )

    output = _root_output(result, "graded_total")
    assert output["expansion_stop_reason"] == "max_chars"
    assert "expansion_truncated" not in output
    assert _truncation_warnings(result) == []
    assert [gap["gap_bucket"] for gap in _capacity_gaps(result)] == ["capacity_guard"]
    assert result.analysis_status["status"] == "partial"
    assert "lineage_fact_gap" in result.analysis_status["blocking_reasons"]
