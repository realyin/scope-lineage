"""Unsupported read queries and data changes have different blocking reasons."""

from __future__ import annotations

import pytest

from scope_lineage.scope.task_lineage import parse_task_lineage


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("SELECT id FROM ods.source", "unsupported_statement"),
        (
            "SELECT id FROM ods.source UNION ALL SELECT id FROM ods.other",
            "unsupported_statement",
        ),
        ("DROP TABLE mart.target", "unsupported_data_change"),
    ],
)
def test_unsupported_statement_blocker_names_its_semantics(
    sql: str,
    reason: str,
) -> None:
    result = parse_task_lineage(
        sql,
        task_name="unsupported_taxonomy",
        schema={"ods.source": ["id"], "ods.other": ["id"]},
    )

    assert result.analysis_status == {
        "status": "partial",
        "blocking_reasons": [reason],
    }
    assert result.statements[0]["model_status"] == "unsupported"
    assert [warning["type"] for warning in result.diagnostics["warnings"]] == [
        "unsupported_statement"
    ]


def test_mixed_unsupported_kinds_keep_both_blocking_reasons() -> None:
    result = parse_task_lineage(
        "DROP TABLE mart.target; SELECT id FROM ods.source",
        task_name="mixed_unsupported_taxonomy",
        schema={"ods.source": ["id"]},
    )

    assert result.analysis_status["blocking_reasons"] == [
        "unsupported_data_change",
        "unsupported_statement",
    ]
