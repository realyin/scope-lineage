"""B12: a JOIN upstream of the grouping does not cost the statement its key.

``key_confidence`` used to drop to ``none`` as soon as any JOIN on the grain walk was
not proven safe, whatever the grain's basis. For a GROUP BY -- and equally for a
DISTINCT or a ranking-window dedup -- that reads the risk against the wrong question: a
JOIN that duplicated the rows *being grouped* inflates the aggregated numbers, which the
metric-path risks already report, without adding a single row to the output. The
grouping set is unique in the output no matter how many rows went into it.

Only a JOIN **strictly downstream of the grain-deciding scope** can duplicate what the
grouping made unique: a join in ROOT, or in an intermediate scope between ROOT and the
grouping scope, multiplies rows the grouping already emitted. The rule is the one B10
already applied to ``single_row``, extended to every proven basis.

A ``driving_table_rows`` grain is untouched: it has no operation making anything unique,
so a fan-out anywhere on its path still matters.
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

# A right side no rule can prove unique by the join key: a plain projection.
UNPROVEN = "(SELECT extract_number, v FROM ods.side) s"
# A right side the GROUP BY rule proves unique by the very column the ON clause names.
PROVEN = "(SELECT extract_number, SUM(v) AS total FROM ods.side GROUP BY extract_number) s"

IGNORED_ROOT = "ROOT 的关联放大发生在分组之前，不影响输出键唯一性"


def _shape(sql: str) -> dict:
    return build_semantic_profile(
        to_lineage_dict(parse_scope_lineage(sql, "b12_case", schema=SCHEMA))
    )["output_shape"]


def _render(sql: str) -> str:
    profile = build_semantic_profile(
        to_lineage_dict(parse_scope_lineage(sql, "b12_case", schema=SCHEMA))
    )
    return render_semantic_markdown(profile, sections=["shape"])


def _only_risk(shape: dict) -> dict:
    risks = shape["fan_out_risks"]
    assert len(risks) == 1, risks
    return risks[0]


# ------------------------------------------- the join feeds the grouping (proven)


def test_a_join_below_the_group_by_leaves_the_grouped_key_proven() -> None:
    shape = _shape(
        "INSERT INTO mart.t SELECT m.extract_number, COUNT(*) AS cnt "
        f"FROM ods.main m JOIN {UNPROVEN} ON m.extract_number = s.extract_number "
        "GROUP BY m.extract_number"
    )

    assert shape["key_confidence"] == "proven"
    assert shape["candidate_keys"] == ["extract_number"]


def test_the_ignored_join_is_still_published_as_a_risk() -> None:
    shape = _shape(
        "INSERT INTO mart.t SELECT m.extract_number, COUNT(*) AS cnt "
        f"FROM ods.main m JOIN {UNPROVEN} ON m.extract_number = s.extract_number "
        "GROUP BY m.extract_number"
    )

    assert _only_risk(shape)["status"] == "risk"


def test_the_key_evidence_says_why_the_risk_did_not_count() -> None:
    shape = _shape(
        "INSERT INTO mart.t SELECT m.extract_number, COUNT(*) AS cnt "
        f"FROM ods.main m JOIN {UNPROVEN} ON m.extract_number = s.extract_number "
        "GROUP BY m.extract_number"
    )

    assert IGNORED_ROOT in shape["key_evidence"]


def test_a_distinct_basis_survives_the_same_join() -> None:
    shape = _shape(
        "INSERT INTO mart.t SELECT DISTINCT m.extract_number FROM ods.main m "
        f"JOIN {UNPROVEN} ON m.extract_number = s.extract_number"
    )

    assert shape["grain"]["basis"] == "distinct"
    assert shape["key_confidence"] == "proven"
    assert shape["candidate_keys"] == ["extract_number"]
    assert IGNORED_ROOT in shape["key_evidence"]


# ---------------------------------------- the join runs after the grouping (none)


def test_a_root_join_onto_a_grouped_cte_still_costs_the_key() -> None:
    shape = _shape(
        "INSERT INTO mart.t WITH g AS (SELECT extract_number, SUM(amount) AS total "
        "FROM ods.main GROUP BY extract_number) "
        "SELECT g.extract_number, g.total FROM g "
        f"LEFT JOIN {UNPROVEN} ON g.extract_number = s.extract_number"
    )

    assert shape["grain"]["keys"][0]["scope_id"] == "cte:g"
    assert shape["key_confidence"] == "none"
    assert shape["candidate_keys"] == []
    assert IGNORED_ROOT not in shape["key_evidence"]


def test_a_join_in_a_scope_between_root_and_the_grouping_costs_the_key() -> None:
    """The risk is neither in ROOT nor in the grouping scope, but still downstream."""
    shape = _shape(
        "INSERT INTO mart.t WITH g AS (SELECT extract_number, SUM(amount) AS total "
        "FROM ods.main GROUP BY extract_number), "
        f"j AS (SELECT g.extract_number, g.total FROM g LEFT JOIN {UNPROVEN} "
        "ON g.extract_number = s.extract_number) "
        "SELECT extract_number, total FROM j"
    )

    assert shape["grain"]["via_scopes"] == ["cte:j"]
    assert _only_risk(shape)["scope_id"] == "cte:j"
    assert shape["key_confidence"] == "none"
    assert shape["candidate_keys"] == []


def test_a_safe_root_join_over_a_grouped_cte_stays_proven_without_the_note() -> None:
    shape = _shape(
        "INSERT INTO mart.t WITH g AS (SELECT extract_number, SUM(amount) AS total "
        "FROM ods.main GROUP BY extract_number) "
        "SELECT g.extract_number, g.total FROM g "
        f"LEFT JOIN {PROVEN} ON g.extract_number = s.extract_number"
    )

    assert _only_risk(shape)["status"] == "safe"
    assert shape["key_confidence"] == "proven"
    assert shape["candidate_keys"] == ["extract_number"]
    assert IGNORED_ROOT not in shape["key_evidence"]


# --------------------------------------------- a driving-table grain is unchanged


def test_a_driving_table_grain_still_loses_its_key_to_any_fan_out() -> None:
    shape = _shape(
        "INSERT INTO mart.t SELECT m.extract_number, s.v FROM ods.main m "
        f"LEFT JOIN {UNPROVEN} ON m.extract_number = s.extract_number"
    )

    assert shape["grain"]["basis"] == "driving_table_rows"
    assert shape["key_confidence"] == "none"
    assert shape["candidate_keys"] == []
    assert IGNORED_ROOT not in shape["key_evidence"]


# ------------------------------------------- the note reaches the reader's document


GROUPED_OVER_JOIN_SQL = (
    "INSERT INTO mart.t SELECT m.extract_number, COUNT(*) AS cnt "
    f"FROM ods.main m JOIN {UNPROVEN} ON m.extract_number = s.extract_number "
    "GROUP BY m.extract_number"
)


def test_semantic_md_explains_the_surviving_key_under_the_key_line() -> None:
    """A reader who sees the JOIN listed as a risk needs the key line's own answer."""
    lines = _render(GROUPED_OVER_JOIN_SQL).splitlines()

    key_line = next(index for index, line in enumerate(lines) if line.startswith("- 键："))
    assert lines[key_line + 1] == (
        f"- 说明：{IGNORED_ROOT}（结构推断）"
    )


def test_a_statement_with_nothing_to_explain_renders_no_note() -> None:
    rendered = _render(
        "INSERT INTO mart.t SELECT extract_number, SUM(amount) AS total "
        "FROM ods.main GROUP BY extract_number"
    )

    assert "- 键：" in rendered
    assert "- 说明：" not in rendered


def test_the_other_key_evidence_notes_are_not_rendered_as_the_fan_out_one() -> None:
    """``key_evidence`` carries unrelated notes; only the B12 sentence is this bullet."""
    rendered = _render(
        "INSERT OVERWRITE TABLE mart.t PARTITION (dt) "
        "SELECT extract_number, dt FROM ods.main GROUP BY extract_number, dt"
    )

    assert "分区列不计入候选键" in rendered
    assert "- 说明：" not in rendered
