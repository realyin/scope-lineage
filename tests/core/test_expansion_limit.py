"""``parse --expansion-limit``: the capacity guard as a declared number, not a constant.

The expansion budget stops inlining upstream expression text once it has made
``EXPANSION_MAX_SUBSTITUTIONS`` substitutions. Two things were missing for the operator
holding that artifact: the number the run actually stopped at (the diagnostic named the
guard, never its limit) and any way to raise it short of editing the package.

Since Q2 the guard is reported as a truncation warning where the sources are nonetheless
complete, so these tests read the number off that warning; the gap shape stays covered by
``test_expansion_truncation`` for the case where the sources really are missing.

The flag defaults to the constant, so a run that does not pass it is the run it always
was -- these tests pin that equality rather than the constant's value, which is tuning.
"""

from __future__ import annotations

import json
from pathlib import Path

from scope_lineage.cli import main
from scope_lineage.scope.expansion_budget import EXPANSION_MAX_SUBSTITUTIONS


#: Five upstream expressions inlined into one output: deep enough to need more than three
#: substitutions, small enough that nothing else in the run is bounded.
SQL = """
WITH base AS (
  SELECT a + 1 AS c1, a + 2 AS c2, a + 3 AS c3, a + 4 AS c4, a + 5 AS c5
  FROM ods.src
)
INSERT INTO mart.total
SELECT b.c1 + b.c2 + b.c3 + b.c4 + b.c5 AS total
FROM base b
"""

SCHEMA = {"ods.src": {"columns": [{"name": "a", "type": "bigint"}]}}


def _parse(tmp_path: Path, out: str, *extra: str) -> Path:
    sql = tmp_path / "total.sql"
    sql.write_text(SQL, encoding="utf-8")
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps(SCHEMA), encoding="utf-8")
    assert (
        main(
            [
                "parse",
                "--sql-file",
                str(sql),
                "--schema",
                str(schema),
                "--out",
                str(tmp_path / out),
                *extra,
            ]
        )
        == 0
    )
    return next((tmp_path / out).rglob("lineage.json")).parent


def _document(task_dir: Path) -> dict:
    """``diagnostics.json``: the full gap list, of which lineage.json keeps samples."""
    return json.loads((task_dir / "diagnostics.json").read_text(encoding="utf-8"))


def _capacity_gaps(document: dict) -> list[dict]:
    return [
        gap
        for gap in document.get("lineage_fact_gaps") or []
        if gap.get("gap_bucket") == "capacity_guard"
    ]


def _truncations(document: dict) -> list[dict]:
    return [
        warning
        for statement in (document.get("statement_diagnostics") or {}).values()
        for warning in statement.get("warnings") or []
        if warning.get("type") == "expansion_truncated"
    ]


def test_a_small_limit_trips_the_guard_and_the_warning_names_the_number(
    tmp_path: Path,
) -> None:
    document = _document(_parse(tmp_path, "out", "--expansion-limit", "3"))

    truncations = _truncations(document)
    assert len(truncations) == 1
    # The number the run stopped at, and the way to move it -- both in the sentence a
    # reader of the artifact already reads.
    message = truncations[0]["msg"]
    assert "max_substitutions" in message
    assert "3" in message
    assert "--expansion-limit" in message
    # The sources were never in doubt, so the guard costs text, not a blocked task.
    assert _capacity_gaps(document) == []
    assert document["analysis_status"]["status"] == "complete"


def test_the_same_statement_is_untouched_at_the_default_limit(tmp_path: Path) -> None:
    document = _document(_parse(tmp_path, "out"))

    assert _capacity_gaps(document) == []
    assert _truncations(document) == []
    assert document["analysis_status"]["status"] == "complete"


def test_the_default_is_todays_constant(tmp_path: Path) -> None:
    """Passing the default explicitly must produce the artifact byte for byte."""
    implicit = _parse(tmp_path, "implicit")
    explicit = _parse(
        tmp_path, "explicit", "--expansion-limit", str(EXPANSION_MAX_SUBSTITUTIONS)
    )

    for name in ("lineage.json", "diagnostics.json"):
        assert (explicit / name).read_text(encoding="utf-8") == (
            implicit / name
        ).read_text(encoding="utf-8")


def test_the_summary_counts_the_tasks_that_hit_the_guard(
    tmp_path: Path, capsys
) -> None:
    _parse(tmp_path, "out", "--expansion-limit", "3")

    assert "capacity_guard=1" in capsys.readouterr().out


def test_the_summary_stays_silent_when_no_task_hit_the_guard(
    tmp_path: Path, capsys
) -> None:
    """A count that is always there is a count nobody reads."""
    _parse(tmp_path, "out")

    assert "capacity_guard" not in capsys.readouterr().out


def test_the_limit_does_not_leak_into_the_next_parse(tmp_path: Path) -> None:
    """The flag is one run's policy, not a process-wide setting."""
    _parse(tmp_path, "bounded", "--expansion-limit", "3")

    assert _truncations(_document(_parse(tmp_path, "after"))) == []
