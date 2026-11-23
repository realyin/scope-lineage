"""The WARNs a writer may keep are listed in three places, and they must list the same ones.

The writer template (T1), the orchestrator's step (S5) and the fix template (T4) each say
which ``semantic validate`` WARNs may stay. ``[9 time]`` tells the writer itself that a
table rebuilt whole every run, whose date filter only picks one version from upstream or
cuts a span of history, is still a snapshot: such a table may keep the WARN in all three,
as long as ``how_to_read`` says how to read it and which day the filter picks.
"""

from __future__ import annotations

from pathlib import Path

REFS = Path(__file__).resolve().parents[2] / "skills" / "scope-lineage-ontology" / "references"
PLACES = ("templates/T1.md", "steps/S5.md", "templates/T4.md")
REBUILT_WHOLE = "从上游挑一个版本"


def test_each_keep_list_lets_a_table_rebuilt_whole_keep_its_time_warning() -> None:
    for place in PLACES:
        text = (REFS / place).read_text(encoding="utf-8")
        line = next(line for line in text.splitlines() if "[9 time]" in line)
        assert "拉链表" in line and "维表" in line, place
        assert REBUILT_WHOLE in line, place


def test_the_review_checks_the_day_such_a_filter_picks() -> None:
    text = (REFS / "table-semantics-review-prompt.md").read_text(encoding="utf-8")
    assert REBUILT_WHOLE in text and "取的是哪一天" in text
