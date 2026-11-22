"""The semantic profile describes EXCEPT and INTERSECT as what they are, not as a UNION.

Since WP3b the contract labels a set operation's scope ``set_op = EXCEPT`` / ``INTERSECT``,
but the profile kept reading every set operation as a UNION: the grain blocker said
「行数为各分支之和」, the stage action said 「合并 2 个分支」, the shape line said 合并型,
and every branch's table was a driving table. EXCEPT keeps the first branch's rows that
no other branch has; INTERSECT keeps the first branch's rows every other branch also has.
So the rows come from the first branch, and the other branches only drop rows -- the
role ``filter_partner`` already names. The key confidence is not raised: nothing here
proves a key.
"""

from __future__ import annotations

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.semantic_markdown import render_semantic_markdown
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {"ods.a": ["id", "amount"], "ods.b": ["id", "amount"]}


def _profile(op: str) -> dict:
    sql = f"INSERT INTO mart.t SELECT id, amount FROM ods.a {op} SELECT id, amount FROM ods.b"
    return build_semantic_profile(to_lineage_dict(parse_scope_lineage(sql, "set_op", schema=SCHEMA)))


def _roles(profile: dict) -> dict[str, list[str]]:
    return {item["table"]: item["roles"] for item in profile["inputs"]}


def _union_action_texts(profile: dict) -> list[str]:
    return [
        action["text"]
        for stage in profile["stages"]
        for action in stage["actions"]
        if action["type"] == "union"
    ]


@pytest.mark.parametrize("op", ["EXCEPT", "INTERSECT"])
def test_the_grain_blocker_does_not_call_the_rows_a_sum_of_branches(op: str) -> None:
    shape = _profile(op)["output_shape"]

    [evidence] = shape["grain"]["evidence"]
    assert "各分支之和" not in evidence
    assert op in evidence
    assert shape["grain"]["basis"] == "unknown"
    assert shape["key_confidence"] == "none"
    assert shape["candidate_keys"] == []


def test_except_reads_as_the_first_branch_minus_the_others() -> None:
    profile = _profile("EXCEPT")

    assert _union_action_texts(profile) == ["差集：取 ods.a 的行，去掉在 ods.b 中出现的行"]
    assert "差集型" in render_semantic_markdown(profile)


def test_intersect_reads_as_the_rows_every_branch_has() -> None:
    profile = _profile("INTERSECT")

    assert _union_action_texts(profile) == ["交集：取 ods.a 的行，只留在 ods.b 中也出现的行"]
    assert "交集型" in render_semantic_markdown(profile)


@pytest.mark.parametrize("op", ["EXCEPT", "INTERSECT"])
def test_only_the_first_branch_drives_the_rows(op: str) -> None:
    roles = _roles(_profile(op))

    assert roles["ods.a"][0] == "driving"
    assert "driving" not in roles["ods.b"]
    assert "filter_partner" in roles["ods.b"]


@pytest.mark.parametrize("op", ["UNION ALL", "UNION"])
def test_a_union_still_sums_its_branches(op: str) -> None:
    """Sentinel: a UNION keeps every branch driving and its 合并 wording."""
    profile = _profile(op)

    assert "各分支之和" in profile["output_shape"]["grain"]["evidence"][0]
    assert _union_action_texts(profile) == ["合并 2 个分支（来自 ods.a、ods.b）"]
    assert all(roles[0] == "driving" for roles in _roles(profile).values())
    assert "合并型" in render_semantic_markdown(profile)


def test_a_later_branch_is_a_filter_partner_under_an_aggregate_too() -> None:
    sql = (
        "INSERT INTO mart.t SELECT id, COUNT(*) AS n "
        "FROM (SELECT id FROM ods.a EXCEPT SELECT id FROM ods.b) t GROUP BY id"
    )
    profile = build_semantic_profile(to_lineage_dict(parse_scope_lineage(sql, "set_op", schema=SCHEMA)))

    roles = _roles(profile)
    assert roles["ods.a"][0] == "driving"
    assert roles["ods.b"] == ["filter_partner"]
