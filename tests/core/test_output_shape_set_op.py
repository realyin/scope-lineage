"""``output_shape.set_op`` names the set operation of a ``union_merge`` (decision 4.4).

EXCEPT / INTERSECT keep ``shape: union_merge`` (and their output columns ``transform:
UNION``) so consumers branching on those values keep working. Nothing structured in
``semantic.json`` said which set operation it was: only ``grain.evidence`` and the stage
action's Chinese text did, and ``semantic.md`` picked 差集型 / 交集型 by that text's
prefix. ``set_op`` is the structured answer, and ``semantic.md`` reads it.

Every name here is synthetic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scope_lineage import parse_task_lineage
from scope_lineage.contract import to_lineage_dict
from scope_lineage.contract.task_lineage import to_task_lineage_dict
from scope_lineage.render.semantic_markdown import render_semantic_markdown
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.scope.scope_builder import parse_scope_lineage

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "sql"


def _statements(path: Path) -> list[dict]:
    task = to_task_lineage_dict(parse_task_lineage(path.read_text(), task_name="t"))
    profile = build_semantic_profile(task)
    return profile["statements"]


def _profile(sql: str) -> dict:
    return build_semantic_profile(to_lineage_dict(parse_scope_lineage(sql, "t")))


def test_except_and_intersect_name_their_set_op() -> None:
    first, second = _statements(EXAMPLES / "set_operation_except_intersect.sql")

    assert (first["output_shape"]["shape"], first["output_shape"]["set_op"]) == (
        "union_merge", "EXCEPT",
    )
    assert (second["output_shape"]["shape"], second["output_shape"]["set_op"]) == (
        "union_merge", "INTERSECT",
    )


def test_a_mixed_chain_names_its_outer_operator() -> None:
    # `A UNION B UNION ALL C` is `(A UNION B) UNION ALL C`: ROOT reads the UNION ALL.
    [statement] = _statements(EXAMPLES / "union_distinct_chain.sql")

    assert statement["output_shape"]["set_op"] == "UNION_ALL"


@pytest.mark.parametrize(("operator", "label"), [("UNION", "UNION"), ("UNION ALL", "UNION_ALL")])
def test_a_union_names_its_set_op(operator: str, label: str) -> None:
    profile = _profile(
        f"INSERT INTO m.t SELECT id FROM s.a {operator} SELECT id FROM s.b"
    )

    assert profile["output_shape"]["set_op"] == label


def test_other_shapes_carry_no_set_op() -> None:
    profile = _profile("INSERT INTO m.t SELECT id FROM s.a WHERE id > 0")

    assert profile["output_shape"]["shape"] != "union_merge"
    assert "set_op" not in profile["output_shape"]


def test_the_shape_line_reads_the_field_not_the_action_text() -> None:
    profile = _profile(
        "INSERT INTO m.t SELECT id FROM s.a EXCEPT SELECT id FROM s.b"
    )
    for stage in profile["stages"]:
        for action in stage["actions"]:
            action["text"] = "（改写过的文字）"

    assert "差集型" in render_semantic_markdown(profile)


@pytest.mark.parametrize(("operator", "label"), [
    ("EXCEPT", "差集型"), ("INTERSECT", "交集型"), ("UNION ALL", "合并"),
])
def test_the_shape_line_wording_is_unchanged(operator: str, label: str) -> None:
    markdown = render_semantic_markdown(
        _profile(f"INSERT INTO m.t SELECT id FROM s.a {operator} SELECT id FROM s.b")
    )

    [line] = [line for line in markdown.splitlines() if line.startswith("- 形态：")]
    assert label in line
