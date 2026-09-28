"""Equivalent SQL, equivalent conclusions (WP4, metamorphic).

Reading ``ods.e`` directly, through a pass-through temp view, through a CTE, or through a
``SELECT *`` subquery computes the same rows. The task-level answer must not notice: the
same root sources with the same transforms, the same row conditions, the same output
key. F6 was exactly this failing -- one extra temp view turned ``v * 2`` into ``DIRECT``
and merged two constants into one.

Rewrites the tool cannot yet treat as equivalent are listed with ``xfail(strict=True)``
and the work package that owes them, so fixing one turns its test red until the marker
is removed.
"""

from __future__ import annotations

from typing import Callable

import pytest

from scope_lineage import fold_session_scoped
from scope_lineage.contract.task_lineage import to_task_lineage_dict
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.scope.task_lineage import parse_task_lineage

from .claim_witness import schema_map

TARGET = "mart.out"


def _through_view(sql: str) -> str:
    return "CREATE OR REPLACE TEMP VIEW tv AS SELECT * FROM ods.e;\n" + sql.replace(
        "ods.e", "tv"
    )


def _through_cte(sql: str) -> str:
    head, select = sql.split(" SELECT ", 1)
    return f"{head} WITH c AS (SELECT * FROM ods.e) SELECT " + select.replace("ods.e", "c")


def _through_subquery(sql: str) -> str:
    return sql.replace("FROM ods.e e", "FROM (SELECT * FROM ods.e) e")


REWRITES: dict[str, Callable[[str], str]] = {
    "temp view": _through_view,
    "cte": _through_cte,
    "subquery": _through_subquery,
}

STATEMENTS = {
    "grouped": (
        f"INSERT OVERWRITE TABLE {TARGET} "
        "SELECT e.id, MAX(e.v) AS v FROM ods.e e WHERE e.keep = 1 GROUP BY e.id"
    ),
    "expression over a join": (
        f"INSERT OVERWRITE TABLE {TARGET} "
        "SELECT e.id, e.v * 2 AS v FROM ods.e e JOIN ods.base b ON e.id = b.id"
    ),
    "case constants": (
        f"INSERT OVERWRITE TABLE {TARGET} "
        "SELECT e.id, CASE WHEN e.keep = 1 THEN 'A' ELSE 'B' END AS v FROM ods.e e"
    ),
    "count": (
        f"INSERT OVERWRITE TABLE {TARGET} "
        "SELECT e.dt AS id, COUNT(*) AS v FROM ods.e e WHERE e.keep = 1 GROUP BY e.dt"
    ),
}

# What the fold cannot carry through a session relation yet (design 5.1, WP5): a row set
# read through a temp view is left unfolded rather than resolved to the table behind it.
KNOWN_GAPS = {
    ("count", "temp view"): "WP5: fold does not expand a rowset read through a temp view",
}


def _answer(sql: str) -> dict:
    """Per target column: root sources, row conditions, completeness; plus the key."""
    document = fold_session_scoped(
        to_task_lineage_dict(parse_task_lineage(sql, task_name="meta", schema=schema_map()))
    )
    columns = {}
    for row in document["end_to_end_lineage"]:
        if row.get("table") != TARGET:
            continue
        columns[row["column"]] = {
            "values": sorted(
                (
                    str(source.get("source_kind")),
                    str(source.get("table")),
                    str(source.get("column")),
                    str(source.get("transform")),
                    str(source.get("value") or source.get("expression") or ""),
                )
                for source in row["value_sources"]
            ),
            "rows": sorted(
                (str(item["table"]), str(item["column"]))
                for item in row["row_membership_sources"]
            ),
            "complete": bool(row["trace_complete"]) and row.get("value_sources_folded", True),
        }
    profile = build_semantic_profile(
        to_task_lineage_dict(parse_task_lineage(sql, task_name="meta", schema=schema_map()))
    )
    statement = next(
        item
        for item in profile.get("statements") or [profile]
        if (item.get("task") or {}).get("target_table") == TARGET
    )
    shape = statement["output_shape"]
    return {
        "columns": columns,
        "key": (shape["key_confidence"], list(shape["candidate_keys"])),
    }


CASES = [
    pytest.param(
        name,
        rewrite,
        id=f"{name}/{rewrite}",
        marks=(
            [pytest.mark.xfail(strict=True, reason=KNOWN_GAPS[(name, rewrite)])]
            if (name, rewrite) in KNOWN_GAPS
            else []
        ),
    )
    for name in STATEMENTS
    for rewrite in REWRITES
]


@pytest.mark.parametrize(("name", "rewrite"), CASES)
def test_an_equivalent_rewrite_keeps_the_answer(name: str, rewrite: str) -> None:
    direct = _answer(STATEMENTS[name])
    rewritten = _answer(REWRITES[rewrite](STATEMENTS[name]))

    assert rewritten == direct
