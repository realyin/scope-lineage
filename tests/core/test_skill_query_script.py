"""The skill's artifact-query script must answer without loading artifacts into context.

skills/scope-lineage/scripts/query.py exists so an AI agent (this repo's skill, or any
other tool following the docs) can pull a focused answer out of a large lineage.json.
These tests run it the way an agent would -- as a subprocess over
artifacts produced by the real CLI -- and pin the three contracts: a task summary, a
field's transformation chain, and reverse impact lookup.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
QUERY = REPO / "skills" / "scope-lineage" / "scripts" / "query.py"

SQL = """
INSERT INTO mart.daily_orders
SELECT o.order_id,
       SUM(CASE WHEN o.status = 'PAID' THEN o.amount ELSE 0 END) AS paid_amount
FROM ods.orders o
GROUP BY o.order_id;
"""

PARTIAL_SQL = """
DROP TABLE IF EXISTS scratch.retired_events;
INSERT INTO mart.event_copy
SELECT * FROM raw.events;
"""


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("skill-artifacts")
    sql_path = root / "daily_orders.sql"
    sql_path.write_text(SQL, encoding="utf-8")
    out = root / "out"
    from scope_lineage.cli import main

    assert main(["parse", "--sql-file", str(sql_path), "--out", str(out)]) == 0
    return out / "daily_orders"


@pytest.fixture(scope="module")
def partial_artifacts(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("skill-partial-artifacts")
    sql_path = root / "event_copy.sql"
    sql_path.write_text(PARTIAL_SQL, encoding="utf-8")
    out = root / "out"
    from scope_lineage.cli import main

    assert main(["parse", "--sql-file", str(sql_path), "--out", str(out)]) == 0
    return out / "event_copy"


def _run(*args: str) -> str:
    result = subprocess.run(
        [sys.executable, str(QUERY), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_summary_reports_status_statements_and_gap_counts(artifacts: Path) -> None:
    lineage = json.loads((artifacts / "lineage.json").read_text(encoding="utf-8"))
    out = _run("summary", str(artifacts))
    assert "daily_orders" in out
    assert "parse_status: ok" in out
    assert "stmt:001" in out
    assert "mart.daily_orders" in out
    assert "analysis_status: complete" in out
    assert f"warnings: {lineage['diagnostics']['warning_count']}" in out
    assert f"fact_gaps: {lineage['diagnostics']['lineage_fact_gap_count']}" in out


def test_summary_reads_task_diagnostic_summary_and_full_root_gap_count(
    partial_artifacts: Path,
) -> None:
    lineage = json.loads((partial_artifacts / "lineage.json").read_text(encoding="utf-8"))
    diagnostics = json.loads(
        (partial_artifacts / "diagnostics.json").read_text(encoding="utf-8")
    )
    summary = lineage["diagnostics"]
    root_gap_count = sum(
        gap.get("root_impact") is True
        for gap in diagnostics.get("lineage_fact_gaps") or []
    )
    assert summary["warning_count"] > 0
    assert summary["lineage_fact_gap_count"] > 0
    assert root_gap_count > 0

    out = _run("summary", str(partial_artifacts))
    assert "analysis_status: partial" in out
    assert "blocking_reasons:" in out
    assert f"warnings: {summary['warning_count']}" in out
    assert f"fact_gaps: {summary['lineage_fact_gap_count']}" in out
    assert f"root_impact: {root_gap_count}" in out


def test_summary_does_not_invent_root_gap_count_without_diagnostics_file(
    partial_artifacts: Path,
    tmp_path: Path,
) -> None:
    copied = tmp_path / "lineage.json"
    copied.write_bytes((partial_artifacts / "lineage.json").read_bytes())

    out = _run("summary", str(copied))
    assert "fact_gaps:" in out
    assert "root_impact: unknown" in out


def test_chain_walks_a_field_back_to_physical_columns(artifacts: Path) -> None:
    out = _run("chain", "mart.daily_orders.paid_amount", str(artifacts))
    # the aggregation expression and both physical inputs must be visible
    assert "SUM(" in out
    assert "ods.orders" in out and "amount" in out and "status" in out
    # honesty flags travel with the answer
    assert "trace" in out
    # a field that does not exist says so instead of guessing
    missing = _run("chain", "mart.daily_orders.nope", str(artifacts))
    assert "not found" in missing.lower()


def test_chain_bounds_expression_output_unless_expanded_is_requested(
    artifacts: Path,
    tmp_path: Path,
) -> None:
    copied = tmp_path / "wide"
    copied.mkdir()
    lineage = json.loads((artifacts / "lineage.json").read_text(encoding="utf-8"))
    chain = lineage["statement_lineage"]["stmt:001"]["field_mapping_chains"][1]
    long_expression = "LONG_EXPRESSION_" + "x" * 2_000
    chain["expanded_expression"] = long_expression
    (copied / "lineage.json").write_text(json.dumps(lineage), encoding="utf-8")

    preview = _run("chain", "mart.daily_orders.paid_amount", str(copied))
    full = _run(
        "chain",
        "--expanded",
        "mart.daily_orders.paid_amount",
        str(copied),
    )

    assert "[truncated; rerun chain with --expanded]" in preview
    assert long_expression not in preview
    assert long_expression in full


def test_impact_finds_consumers_of_a_source_column(artifacts: Path) -> None:
    out = _run("impact", "ods.orders.amount", str(artifacts.parent))
    assert "daily_orders" in out          # the consuming task
    assert "paid_amount" in out           # the affected target column
    quiet = _run("impact", "ods.unrelated_table", str(artifacts.parent))
    assert "no consumers found" in quiet.lower()


def test_old_format_artifacts_get_a_diagnostic_not_a_shrug(tmp_path: Path) -> None:
    """A directory full of pre-0.2.0 per-statement documents is the likeliest real-world
    failure (a stale global install produced them); 'no task lineage.json found' sends
    the user hunting in the wrong direction."""
    (tmp_path / "lineage.json").write_text(
        '{"schema_version": "1.0", "task_id": "old"}', encoding="utf-8"
    )
    out = _run("summary", str(tmp_path))
    assert "0.2.0" in out and "statement document" in out
