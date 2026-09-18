"""WI-2.9 item A: a task instance's own day is a fact, not a governance problem.

The owner's complaint was concrete: "a task instance belongs to one day, so a partition
date written as a literal is normal -- it does not need its own warning". The skeleton
used to answer that with two findings (``hardcoded_date_literal``,
``partition_literal_mismatch``) rendered beside "the job writes into the wrong columns",
and with a metric time range labelled 字面量, which reads like an accusation.

Three changes are pinned here: the ``instance_date`` kind for a date-shaped literal in a
metric's time range, the ``取数日`` line section 1 publishes for the whole statement, and
the mismatch note restated as a fact about the other side rather than as a complaint.
"""

from __future__ import annotations

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render import semantic_text
from scope_lineage.render.semantic_markdown import render_semantic_markdown
from scope_lineage.render.semantic_profile import (
    METRIC_TIME_RANGE_KINDS,
    build_semantic_profile,
)
from scope_lineage.scope.scope_builder import parse_scope_lineage


AGGREGATE_SQL = """
INSERT INTO mart.daily
SELECT o.cust_id, SUM(o.amount) AS paid_total
FROM ods.orders o
WHERE o.dt = '20260814'
GROUP BY o.cust_id
"""

AGGREGATE_SCHEMA = {"ods.orders": ["cust_id", "amount", "dt"]}


def _profile(sql: str, schema=None) -> dict:
    document = to_lineage_dict(parse_scope_lineage(sql, "wi29", schema=schema))
    return build_semantic_profile(document)


def _time_range(profile: dict, column: str) -> list[dict]:
    field = next(item for item in profile["fields"] if item["column"] == column)
    return (field.get("metric_spec") or {})["time_range"]


# ------------------------------------------------------- 1. the instance_date kind


def test_a_date_shaped_literal_is_an_instance_date_not_a_bare_literal() -> None:
    ranges = _time_range(_profile(AGGREGATE_SQL, AGGREGATE_SCHEMA), "paid_total")

    assert [item["kind"] for item in ranges] == ["instance_date"]
    assert ranges[0]["expression"] == "dt = '20260814'"


def test_a_literal_that_is_not_written_like_a_day_stays_a_literal() -> None:
    sql = AGGREGATE_SQL.replace("'20260814'", "'ABC'")
    ranges = _time_range(_profile(sql, AGGREGATE_SCHEMA), "paid_total")

    assert [item["kind"] for item in ranges] == ["literal"]


def test_a_scheduler_variable_is_still_a_parameter() -> None:
    sql = AGGREGATE_SQL.replace("'20260814'", "${bizdate}")
    ranges = _time_range(_profile(sql, AGGREGATE_SCHEMA), "paid_total")

    assert [item["kind"] for item in ranges] == ["parameter"]


def test_the_new_kind_is_declared_in_the_vocabulary() -> None:
    assert semantic_text.VALUE_KIND_INSTANCE_DATE in METRIC_TIME_RANGE_KINDS
    ranges = _time_range(_profile(AGGREGATE_SQL, AGGREGATE_SCHEMA), "paid_total")
    assert all(item["kind"] in METRIC_TIME_RANGE_KINDS for item in ranges)


def test_the_card_calls_it_an_instance_date_in_words() -> None:
    rendered = render_semantic_markdown(
        _profile(AGGREGATE_SQL, AGGREGATE_SCHEMA), sections=["fields"]
    )

    assert "实例日期 20260814" in rendered
    assert "（字面量，" not in rendered


# --------------------------------------------------------------- 2. the 取数日 line


def test_section_one_publishes_the_day_this_instance_reads() -> None:
    profile = _profile(AGGREGATE_SQL, AGGREGATE_SCHEMA)

    assert profile["task"]["instance_dates"] == ["20260814"]

    rendered = render_semantic_markdown(profile, sections=["overview"])
    assert "- 取数日：20260814（SQL事实）" in rendered


def test_two_days_are_listed_with_the_gap_between_them() -> None:
    sql = """
    INSERT INTO mart.joined
    SELECT a.id, b.amount
    FROM ods.left_side a
    JOIN ods.right_side b ON a.id = b.id
    WHERE a.dt = '20260814' AND b.dt = '20260813'
    """
    profile = _profile(
        sql,
        {"ods.left_side": ["id", "dt"], "ods.right_side": ["id", "amount", "dt"]},
    )

    assert profile["task"]["instance_dates"] == ["20260813", "20260814"]

    rendered = render_semantic_markdown(profile, sections=["overview"])
    assert "- 取数日：20260813、20260814（相差 1 天）（SQL事实）" in rendered


def test_a_parameterised_task_has_no_instance_date_and_no_line() -> None:
    sql = AGGREGATE_SQL.replace("'20260814'", "${bizdate}")
    profile = _profile(sql, AGGREGATE_SCHEMA)

    assert profile["task"]["instance_dates"] == []
    assert "- 取数日：" not in render_semantic_markdown(profile, sections=["overview"])


def test_the_line_states_a_day_once_however_many_conjuncts_pin_it() -> None:
    sql = """
    INSERT INTO mart.joined
    SELECT a.id, b.amount
    FROM ods.left_side a
    JOIN ods.right_side b ON a.id = b.id
    WHERE a.dt = '20260814' AND b.dt = '20260814'
    """
    profile = _profile(
        sql,
        {"ods.left_side": ["id", "dt"], "ods.right_side": ["id", "amount", "dt"]},
    )

    assert profile["task"]["instance_dates"] == ["20260814"]


# ------------------------------------------------------- 3. the mismatch, restated


MISMATCH_SQL = """
INSERT INTO mart.daily
SELECT a.k, MAX(x.amount) AS paid_total
FROM ods.main a
LEFT JOIN (SELECT id, amount FROM ods.oper WHERE dt = '20260813') x ON a.k = x.id
WHERE a.dt = '20260814'
GROUP BY a.k
"""

MISMATCH_SCHEMA = {
    "ods.main": ["k", "dt"],
    "ods.oper": ["id", "amount", "dt"],
}


def test_the_two_sides_are_still_flagged_as_disagreeing() -> None:
    ranges = _time_range(_profile(MISMATCH_SQL, MISMATCH_SCHEMA), "paid_total")

    assert [item["kind"] for item in ranges] == ["instance_date", "instance_date"]
    assert all(item.get("mismatch") for item in ranges)


def test_the_note_states_what_the_other_side_takes_and_carries_no_warning_sign() -> None:
    rendered = render_semantic_markdown(
        _profile(MISMATCH_SQL, MISMATCH_SCHEMA), sections=["fields"]
    )
    line = next(
        item for item in rendered.splitlines() if "时间范围" in item
    )

    assert "另一侧取前 1 日" in line
    assert "⚠" not in line
