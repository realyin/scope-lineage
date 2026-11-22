"""CUBE / ROLLUP / GROUPING SETS keep their grouping keys, and never prove them unique.

sqlglot puts the columns of ``GROUP BY CUBE(a, b)``, ``ROLLUP(a, b)`` and
``GROUPING SETS ((a, b), (a))`` in ``args["cube" | "rollup" | "grouping_sets"]``, not in
``group.expressions``; the scope read only the latter, so the GROUP BY vanished and the
profile called the output a single row with a ``proven`` empty key (audit 1.5). The keys
are now read from all four places and the scope records ``grouping_kind``.

Restoring the keys alone would only swap one wrong ``proven`` for another: the subtotal
rows these forms add carry NULL in the rolled-up key columns, and a NULL already present in
the data makes a subtotal row and a detail row share one key tuple. The profile therefore
lowers the key to ``candidate`` and says why.
"""

from __future__ import annotations

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {"ods.sales": ["region", "channel", "amt"]}

BASE = "INSERT INTO dw.agg SELECT region, channel, SUM(amt) AS amt FROM ods.sales "

ROLLED_UP = {
    "cube": "GROUP BY CUBE(region, channel)",
    "rollup": "GROUP BY ROLLUP(region, channel)",
    "grouping_sets": "GROUP BY GROUPING SETS((region, channel), (region))",
    "with_cube": "GROUP BY region, channel WITH CUBE",
    "with_rollup": "GROUP BY region, channel WITH ROLLUP",
}


def _lineage(group_by: str) -> dict:
    return to_lineage_dict(parse_scope_lineage(BASE + group_by, "agg", schema=SCHEMA))


def _group_by_columns(lineage: dict) -> list[str]:
    return [ref["column"] for ref in lineage["scopes"]["ROOT"].get("group_by") or []]


@pytest.mark.parametrize("kind", sorted(ROLLED_UP))
def test_rolled_up_grouping_keeps_its_keys(kind):
    lineage = _lineage(ROLLED_UP[kind])

    assert _group_by_columns(lineage) == ["region", "channel"]
    assert lineage["scopes"]["ROOT"]["grouping_kind"] == kind


@pytest.mark.parametrize("kind", sorted(ROLLED_UP))
def test_rolled_up_grouping_is_not_a_proven_key(kind):
    shape = build_semantic_profile(_lineage(ROLLED_UP[kind]))["output_shape"]

    assert shape["grain"]["basis"] == "group_by"
    assert shape["candidate_keys"] == ["region", "channel"]
    assert shape["key_confidence"] == "candidate"
    assert any("grouping_kind" in item for item in shape["key_evidence"])
    assert shape["key_claim"]["status"] != "proven"


def test_rolled_up_grouping_lists_its_keys_in_the_aggregation_detail():
    lineage = _lineage(ROLLED_UP["grouping_sets"])
    blocks = lineage["scopes"]["ROOT"]["logic_blocks"]
    detail = next(b["aggregation_detail"] for b in blocks if b.get("aggregation_detail"))

    assert [item["expression_sql"] for item in detail["group_by_items"]] == [
        "`sales`.`region`", "`sales`.`channel`",
    ]


def test_a_mixed_plain_and_rollup_group_by_keeps_both_parts():
    lineage = _lineage("GROUP BY region, ROLLUP(channel)")

    assert _group_by_columns(lineage) == ["region", "channel"]
    assert lineage["scopes"]["ROOT"]["grouping_kind"] == "rollup"


def test_a_plain_group_by_is_still_proven_and_carries_no_grouping_kind():
    """Sentinel: the plain GROUP BY path these forms now share keeps its proven key."""
    lineage = _lineage("GROUP BY region, channel")
    shape = build_semantic_profile(lineage)["output_shape"]

    assert "grouping_kind" not in lineage["scopes"]["ROOT"]
    assert shape["key_confidence"] == "proven"
    assert shape["candidate_keys"] == ["region", "channel"]
