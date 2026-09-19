"""B9 / B10: a constant column is not a key, and a whole-table aggregate is one row.

Both rules narrow ``output_shape`` in the same direction -- towards the row count the
SQL actually writes -- and both were measured as wrong answers on the corpus:

**B9.** A scope that groups by ``(k, dt)`` while its own WHERE pins ``dt`` to one literal
returns one row per ``k``, because ``dt`` cannot vary inside that scope. Reading the
GROUP BY list literally made every such JOIN a fan-out ``risk`` -- by some margin the
commonest wrong verdict this rule produced -- and cost the statement its key confidence
with it. The
pinned column is dropped from the *unique key set* only: ``grain.keys`` keeps it, marked
``pinned``, because the reader still wants to see which day the output covers.

**B10.** ``SELECT COUNT(1) FROM t`` has an empty grouping set, which is a proof of
uniqueness rather than the absence of one: the output is exactly one row. It used to be
published as ``basis: group_by`` with no keys and ``key_confidence: none``, i.e. as a
failure to decide. A UNION ALL of several such aggregates is *not* one row, and the
union blocker that already stops the grain walk keeps saying so.

Every negative case here is a predicate that looks like a pin and is not one: only a
top-level AND conjunct comparing a column to a scalar literal or a ``${…}`` parameter
pins anything.
"""

from __future__ import annotations

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.semantic_markdown import render_semantic_markdown
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.scope.scope_builder import parse_scope_lineage


SCHEMA = {
    "ods.main": ["extract_number", "amount", "dt"],
    "ods.side": ["extract_number", "v", "dt"],
    "ods.extra": ["extract_number", "n", "dt"],
}


def _profile(sql: str) -> dict:
    return build_semantic_profile(
        to_lineage_dict(parse_scope_lineage(sql, "grain_case", schema=SCHEMA))
    )


def _shape(sql: str) -> dict:
    return _profile(sql)["output_shape"]


def _only_risk(shape: dict) -> dict:
    risks = shape["fan_out_risks"]
    assert len(risks) == 1, risks
    return risks[0]


def _joined_to_a_pinned_group(predicate: str) -> dict:
    """ROOT joins a subquery that groups by ``(extract_number, dt)`` on the first key."""
    return _shape(
        "INSERT INTO mart.t SELECT m.extract_number, t2.total FROM ods.main m "
        "LEFT JOIN (SELECT extract_number, dt, SUM(v) AS total FROM ods.side "
        f"WHERE {predicate} GROUP BY extract_number, dt) t2 "
        "ON m.extract_number = t2.extract_number"
    )


# ------------------------------------------------------- B9: the pin makes it safe


def test_an_equality_pinned_group_by_key_leaves_the_join_safe() -> None:
    risk = _only_risk(_joined_to_a_pinned_group("dt = '20260815'"))

    assert risk["status"] == "safe"
    assert risk["pinned_keys"] == [
        {"scope_id": "subq:t2", "column": "dt", "value": "'20260815'"}
    ]
    assert "dt 被等值过滤钉死为 '20260815'，不计入键集" in risk["reason"]
    assert "右侧按 extract_number GROUP BY" in risk["reason"]


def test_a_parameter_pins_the_key_just_as_a_literal_does() -> None:
    risk = _only_risk(_joined_to_a_pinned_group("dt = ${bizdate}"))

    assert risk["status"] == "safe"
    assert [item["column"] for item in risk["pinned_keys"]] == ["dt"]


def test_pinning_every_group_by_key_makes_the_right_side_a_single_row() -> None:
    shape = _shape(
        "INSERT INTO mart.t SELECT m.extract_number, t2.total FROM ods.main m "
        "LEFT JOIN (SELECT dt, SUM(v) AS total FROM ods.side "
        "WHERE dt = '20260815' GROUP BY dt) t2 ON m.dt = t2.dt"
    )
    risk = _only_risk(shape)

    assert risk["status"] == "safe"
    assert [item["column"] for item in risk["pinned_keys"]] == ["dt"]
    assert "键集为空" in risk["reason"] and "至多一行" in risk["reason"]


# ------------------------------------------------- B9: what does not pin a column


def test_an_in_list_does_not_pin_the_key() -> None:
    risk = _only_risk(_joined_to_a_pinned_group("dt IN ('20260815', '20260816')"))

    assert risk["status"] == "risk"
    assert "pinned_keys" not in risk


def test_a_between_range_does_not_pin_the_key() -> None:
    risk = _only_risk(
        _joined_to_a_pinned_group("dt BETWEEN '20260801' AND '20260815'")
    )

    assert risk["status"] == "risk"
    assert "pinned_keys" not in risk


def test_an_inequality_does_not_pin_the_key() -> None:
    risk = _only_risk(_joined_to_a_pinned_group("dt <> '20260815'"))

    assert risk["status"] == "risk"


def test_an_equality_nested_in_an_or_does_not_pin_the_key() -> None:
    risk = _only_risk(
        _joined_to_a_pinned_group("dt = '20260815' OR extract_number = 'x'")
    )

    assert risk["status"] == "risk"


def test_a_comparison_with_another_column_does_not_pin_the_key() -> None:
    risk = _only_risk(_joined_to_a_pinned_group("dt = extract_number"))

    assert risk["status"] == "risk"


def test_a_like_pattern_does_not_pin_the_key() -> None:
    risk = _only_risk(_joined_to_a_pinned_group("dt LIKE '202608%'"))

    assert risk["status"] == "risk"


# ----------------------------------------------------- B9: the key set that is left


def test_the_pin_raises_key_confidence_from_none_to_proven() -> None:
    """The pin is on the JOIN's right side, so today's ``risk`` sank the whole claim."""
    shape = _shape(
        "INSERT INTO mart.t SELECT a.extract_number, a.total, b.cnt "
        "FROM (SELECT extract_number, SUM(v) AS total FROM ods.side "
        "      GROUP BY extract_number) a "
        "LEFT JOIN (SELECT extract_number, dt, COUNT(1) AS cnt FROM ods.extra "
        "           WHERE dt = '20260815' GROUP BY extract_number, dt) b "
        "ON a.extract_number = b.extract_number"
    )

    assert _only_risk(shape)["status"] == "safe"
    assert shape["key_confidence"] == "proven"
    assert shape["candidate_keys"] == ["extract_number"]


def test_a_pinned_grain_key_is_kept_and_marked_rather_than_dropped() -> None:
    shape = _shape(
        "INSERT INTO mart.t SELECT extract_number, dt, SUM(v) AS total FROM ods.side "
        "WHERE dt = '20260815' GROUP BY extract_number, dt"
    )
    keys = shape["grain"]["keys"]

    assert [key["name"] for key in keys] == ["extract_number", "dt"]
    assert "pinned" not in keys[0]
    assert keys[1]["pinned"] == {"value": "'20260815'"}
    # the pinned column cannot identify a row, so it is not one of the keys either
    assert shape["candidate_keys"] == ["extract_number"]
    assert shape["key_confidence"] == "proven"


def test_a_pinned_key_that_never_reaches_the_target_is_not_a_governance_finding() -> None:
    """``proven_unexposed`` asks whether the key was written; a constant is not a key."""
    shape = _shape(
        "INSERT INTO mart.t SELECT extract_number, SUM(v) AS total FROM ods.side "
        "WHERE dt = '20260815' GROUP BY extract_number, dt"
    )

    assert shape["unexposed_keys"] == []
    assert shape["key_confidence"] == "proven"


# ------------------------------------------------------------ B10: the single row


def test_an_aggregate_without_group_by_is_one_row() -> None:
    shape = _shape("INSERT INTO mart.t SELECT COUNT(1) AS n FROM ods.side WHERE dt = '1'")

    assert shape["shape"] == "aggregated"
    assert shape["grain"]["basis"] == "single_row"
    assert shape["grain"]["keys"] == []
    assert shape["key_confidence"] == "proven"
    assert shape["candidate_keys"] == []


def test_a_union_of_whole_table_aggregates_is_not_one_row() -> None:
    shape = _shape(
        "INSERT INTO mart.t SELECT COUNT(1) AS n FROM ods.side "
        "UNION ALL SELECT COUNT(1) AS n FROM ods.extra"
    )

    assert shape["grain"]["basis"] == "unknown"
    assert shape["key_confidence"] == "none"


def test_a_group_by_with_items_is_not_a_single_row() -> None:
    shape = _shape(
        "INSERT INTO mart.t SELECT extract_number, COUNT(1) AS n FROM ods.side "
        "GROUP BY extract_number"
    )

    assert shape["grain"]["basis"] == "group_by"


# ------------------------------------------------------------------- the markdown


def test_the_markdown_says_a_single_row_output_is_a_whole_table_total() -> None:
    rendered = render_semantic_markdown(
        _profile("INSERT INTO mart.t SELECT COUNT(1) AS n FROM ods.side WHERE dt = '1'")
    )

    assert "- 粒度：一行 = 全表汇总" in rendered
    assert "basis=single_row" in rendered


def test_the_markdown_fan_out_line_names_the_pinned_column(
) -> None:
    rendered = render_semantic_markdown(
        _profile(
            "INSERT INTO mart.t SELECT m.extract_number, t2.total FROM ods.main m "
            "LEFT JOIN (SELECT extract_number, dt, SUM(v) AS total FROM ods.side "
            "WHERE dt = '20260815' GROUP BY extract_number, dt) t2 "
            "ON m.extract_number = t2.extract_number"
        )
    )

    assert "dt 被等值过滤钉死为 '20260815'，不计入键集" in rendered


def test_the_markdown_keeps_the_pinned_day_on_the_grain_line() -> None:
    rendered = render_semantic_markdown(
        _profile(
            "INSERT INTO mart.t SELECT extract_number, dt, SUM(v) AS total "
            "FROM ods.side WHERE dt = '20260815' GROUP BY extract_number, dt"
        )
    )

    assert "ROOT.dt（钉死为 '20260815'）" in rendered
