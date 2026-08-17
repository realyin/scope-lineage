"""Expression expansion has to finish, not stop after one substitution.

Substituting an upstream scope's expression can reintroduce a qualifier belonging to the
consuming scope: a LATERAL VIEW's expression is written in terms of the alias that feeds
it. Expanding once leaves that qualifier in place, so the field behind it never reaches
``physical_source_fields`` and the output is reported as an incomplete fact.
"""

from __future__ import annotations

from scope_lineage import parse_scope_lineage


SCHEMA = {
    "ods.source": ["id", "session_id", "created_at", "items"],
    "mart.target": ["id", "last_code"],
}

UDTF_OVER_CTE_SQL = """
INSERT INTO mart.target
WITH base AS (
  SELECT id, session_id, created_at, items FROM ods.source
)
SELECT id, last_code FROM (
  SELECT
    t.id,
    FIRST_VALUE(item.code) OVER (
      PARTITION BY t.session_id ORDER BY t.created_at DESC
    ) AS last_code
  FROM base t
  LATERAL VIEW EXPLODE(t.items) x AS item
) q
"""


def _output(result, scope_id: str, name: str):
    return next(
        output for output in result.scopes[scope_id].outputs if output.name == name
    )


def test_a_udtf_expression_over_a_cte_expands_to_its_physical_fields() -> None:
    result = parse_scope_lineage(UDTF_OVER_CTE_SQL, "udtf_over_cte", schema=SCHEMA)

    resolution = _output(result, "subq:q", "last_code").expression_resolution
    assert sorted(
        (field["table"], field["field"])
        for field in resolution["physical_source_fields"]
    ) == [
        ("ods.source", "created_at"),
        ("ods.source", "items"),
        ("ods.source", "session_id"),
    ]
    assert resolution["missing_reasons"] == []
    assert resolution["status"] == "resolved"
    assert result.diagnostics.lineage_fact_gaps == []


def test_the_same_shape_over_a_physical_table_is_unchanged() -> None:
    """The physical-upstream variant already resolved; it must stay that way."""
    result = parse_scope_lineage(
        """
        INSERT INTO mart.target
        SELECT
          t.id,
          FIRST_VALUE(item.code) OVER (
            PARTITION BY t.session_id ORDER BY t.created_at DESC
          ) AS last_code
        FROM ods.source t
        LATERAL VIEW EXPLODE(t.items) x AS item
        """,
        "udtf_over_physical",
        schema=SCHEMA,
    )

    assert result.diagnostics.lineage_fact_gaps == []


def test_expansion_that_cannot_finish_still_reports_the_missing_fact(
    monkeypatch,
) -> None:
    """The round budget must not clear the reason on its own.

    The gap disappears only as a consequence of the expansion actually happening. Take
    the rounds away and the same statement has to go back to reporting the unfinished
    fact — otherwise the limit would quietly convert "we stopped early" into "this
    lineage is complete".
    """
    from scope_lineage.scope import scope_facts

    monkeypatch.setattr(scope_facts, "_EXPRESSION_EXPANSION_ROUNDS", 0)
    result = parse_scope_lineage(UDTF_OVER_CTE_SQL, "udtf_over_cte", schema=SCHEMA)

    resolution = _output(result, "subq:q", "last_code").expression_resolution
    assert resolution["missing_reasons"] == [
        "expanded_expression_contains_unexpanded_alias:t"
    ]
    assert ("ods.source", "items") not in {
        (field["table"], field["field"])
        for field in resolution["physical_source_fields"]
    }
    assert result.diagnostics.lineage_fact_gaps != []
