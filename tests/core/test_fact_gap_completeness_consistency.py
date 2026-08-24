"""A fact gap has one completeness meaning in every consumer view.

The scope pipeline can discover an incomplete expression below ROOT after the final target
column already has physical sources.  Mapping chains and statement end-to-end lineage used to
call that field complete, while task lineage called every column in the target incomplete.  The
right boundary is per target column: the affected field is incomplete everywhere, and an
unrelated resolved field stays complete.
"""

from __future__ import annotations

from scope_lineage.scope import scope_facts
from scope_lineage.scope.task_lineage import parse_task_lineage


SQL = """
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

SCHEMA = {
    "ods.source": ["id", "session_id", "created_at", "items"],
    "mart.target": ["id", "last_code"],
}


def _by_field(items: list[dict], key: str) -> dict[str, dict]:
    return {item[key]: item for item in items}


def test_root_gap_is_incomplete_only_for_its_affected_target_column(
    monkeypatch,
) -> None:
    # Keep the otherwise-resolvable alias in place to exercise the propagation boundary.
    # The expression-expansion tests separately prove that a normal run closes this gap.
    monkeypatch.setattr(scope_facts, "_EXPRESSION_EXPANSION_ROUNDS", 0)
    result = parse_task_lineage(SQL, task_name="gap_consistency", schema=SCHEMA)
    statement = result.statement_lineage["stmt:001"]

    gaps = [
        gap
        for gap in result.diagnostics["lineage_fact_gaps"]
        if gap.get("root_impact")
    ]
    assert len(gaps) == 1
    assert gaps[0]["downstream_impact"]["target_columns"] == [
        "mart.target.last_code"
    ]

    chains = _by_field(statement["field_mapping_chains"], "target_field")
    statement_e2e = _by_field(statement["end_to_end_lineage"], "column")
    task_e2e = _by_field(result.end_to_end_lineage, "column")

    assert chains["last_code"]["trace_status"] == "incomplete"
    assert chains["last_code"]["missing_reasons"]
    assert statement_e2e["last_code"]["trace_complete"] is False
    assert statement_e2e["last_code"]["trace_incomplete_reasons"]
    assert task_e2e["last_code"]["trace_complete"] is False
    assert task_e2e["last_code"]["missing_reasons"]

    assert chains["id"]["trace_status"] == "complete"
    assert statement_e2e["id"]["trace_complete"] is True
    assert task_e2e["id"]["trace_complete"] is True
    assert task_e2e["id"]["missing_reasons"] == []
