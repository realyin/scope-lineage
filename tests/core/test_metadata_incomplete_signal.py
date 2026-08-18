"""A run that never received a table's columns must say so where the reader looks.

`metadata_coverage` already records it. But a reader goes to `analysis_status` and
`lineage_fact_gaps` first, and those said `partial`, `lineage_fact_gap`, and four thousand
records — every one of those words meaning "the parser could not handle this SQL". Nothing
said "you did not give me the schema", so the same run was read three times as a capability
gap report (METADATA-003).

Symmetric to how a repaired parse is reported: name it in `blocking_reasons`, ahead of
`lineage_fact_gap`, so the cause is read before the symptom.

Not marked per gap. Which individual gap a missing table caused is not computable here —
candidate sources are scope ids, not tables — and asserting it anyway would be the same
confident misattribution this exists to prevent. The honest granularity is the document.
"""

from __future__ import annotations

from scope_lineage.scope.task_lineage import parse_task_lineage

# A bare column with several inputs whose column sets are unknown: the shape that turns
# absent metadata into gaps. A qualified reference resolves without the column list, so it
# would not reproduce this at all.
SQL = (
    "INSERT INTO mart.t SELECT s.id, b "
    "FROM (SELECT * FROM ods.src) s "
    "JOIN (SELECT * FROM ods.other) o ON s.id = o.id "
    "JOIN (SELECT * FROM ods.third) x ON s.id = x.id"
)
# The target table counts as referenced, so complete metadata describes it too.
FULL = {
    "ods.src": ["id", "a"], "ods.other": ["id", "b"],
    "ods.third": ["id", "c"], "mart.t": ["id", "b"],
}
HALF = {"ods.src": ["id", "a"], "mart.t": ["id", "b"]}


def test_complete_metadata_reports_no_metadata_reason():
    result = parse_task_lineage(SQL, task_name="t", schema=FULL)

    assert "metadata_incomplete" not in result.analysis_status["blocking_reasons"]
    coverage = result.diagnostics["metadata_coverage"]
    assert coverage["missing_table_count"] == 0


def test_missing_metadata_is_named_in_blocking_reasons():
    result = parse_task_lineage(SQL, task_name="t", schema=HALF)

    reasons = result.analysis_status["blocking_reasons"]
    assert "metadata_incomplete" in reasons


def test_the_cause_is_listed_before_the_symptom():
    """A reader takes the first reason as the headline, so ordering is the point."""
    result = parse_task_lineage(SQL, task_name="t", schema=HALF)

    reasons = result.analysis_status["blocking_reasons"]
    if "lineage_fact_gap" in reasons:
        assert reasons.index("metadata_incomplete") < reasons.index("lineage_fact_gap")


def test_a_warning_names_the_tables_that_were_missing():
    result = parse_task_lineage(SQL, task_name="t", schema=HALF)

    warnings = [
        w for w in result.diagnostics["warnings"]
        if w.get("type") == "metadata_incomplete"
    ]
    assert len(warnings) == 1
    assert "ods.other" in warnings[0]["msg"]
    assert "ods.third" in warnings[0]["msg"]


def test_a_missing_target_schema_is_not_reported_as_incomplete():
    """Target DDL arrives through its own input, and cannot be why a source failed."""
    sql = "INSERT INTO mart.t SELECT s.a FROM ods.src s"

    result = parse_task_lineage(sql, task_name="t", schema={"ods.src": ["a"]})

    assert not [
        w for w in result.diagnostics["warnings"] if w.get("type") == "metadata_incomplete"
    ]
    assert "metadata_incomplete" not in result.analysis_status["blocking_reasons"]


def test_the_warning_appears_even_when_nothing_else_is_wrong():
    """A warning, not a blocking reason: the lineage produced is not in doubt, only the
    completeness of what it was given."""
    sql = "INSERT INTO mart.t SELECT s.a FROM ods.src s JOIN ods.other o ON s.a = o.a"

    result = parse_task_lineage(sql, task_name="t", schema={"ods.src": ["a"], "mart.t": ["a"]})

    warnings = [
        w for w in result.diagnostics["warnings"]
        if w.get("type") == "metadata_incomplete"
    ]
    assert len(warnings) == 1
    assert "ods.other" in warnings[0]["msg"]


def test_no_warning_when_every_referenced_table_is_covered():
    result = parse_task_lineage(SQL, task_name="t", schema=FULL)

    assert not [
        w for w in result.diagnostics["warnings"]
        if w.get("type") == "metadata_incomplete"
    ]
