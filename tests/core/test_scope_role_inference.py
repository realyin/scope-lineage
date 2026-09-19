"""C1: a scope that only computes window functions is not a ``dedup``.

``scope_role_inferrer`` used to label every window-bearing scope ``dedup``, on the
assumption that a window is always the ROW_NUMBER-then-``rn = 1`` pattern. A scope that
computes ``LAG`` / ``SUM(...) OVER (...)``, or even a ``ROW_NUMBER`` nobody filters on,
deduplicates nothing, and ``role`` is the one label a reader takes as the stage's
purpose.

The rule pinned here: ``dedup`` needs a **ranking** window (``ROW_NUMBER`` / ``RANK`` /
``DENSE_RANK`` / ``NTILE``) whose output column is pinned to a small constant by an
``=`` / ``<=`` / ``<`` predicate -- in this scope, or in a scope that reads it (its
WHERE, HAVING, or a JOIN ON clause). Every other window scope is ``window``.
"""

from __future__ import annotations

import pytest

from scope_lineage.scope.scope_builder import parse_scope_lineage


SCHEMA = {
    "ods.e": ["id", "v", "ts", "grp", "dt"],
    "ods.dim": ["id", "name"],
}


def _roles(sql: str) -> dict[str, str]:
    result = parse_scope_lineage(sql, "role_case", schema=SCHEMA)
    return {scope_id: data.role for scope_id, data in result.scopes.items()}


def _ranked_subquery(window: str, tail: str = "") -> str:
    return f"""
INSERT OVERWRITE TABLE mart.t
SELECT id, v
FROM (
  SELECT id, v, {window} AS rn
  FROM ods.e
) s
{tail}
"""


# ------------------------------------------------------------------ not a dedup


def test_a_running_aggregate_window_is_not_a_dedup() -> None:
    roles = _roles(_ranked_subquery("SUM(v) OVER (PARTITION BY grp)"))
    assert roles["subq:s"] == "window"


def test_a_lag_window_is_not_a_dedup() -> None:
    roles = _roles(_ranked_subquery("LAG(v) OVER (PARTITION BY id ORDER BY ts)"))
    assert roles["subq:s"] == "window"


def test_a_ranking_window_nobody_filters_on_is_not_a_dedup() -> None:
    """The ROW_NUMBER is computed and published; no predicate keeps row 1 only."""
    roles = _roles(
        _ranked_subquery("ROW_NUMBER() OVER (PARTITION BY id ORDER BY ts DESC)")
    )
    assert roles["subq:s"] == "window"


def test_a_rank_compared_to_a_large_constant_is_not_a_dedup() -> None:
    """``rn <= 5000`` is a guard rail, not a record-selection rule."""
    roles = _roles(
        _ranked_subquery(
            "ROW_NUMBER() OVER (PARTITION BY id ORDER BY ts DESC)",
            "WHERE s.rn <= 5000",
        )
    )
    assert roles["subq:s"] == "window"


def test_a_predicate_on_another_column_does_not_make_a_window_scope_a_dedup() -> None:
    roles = _roles(
        _ranked_subquery(
            "ROW_NUMBER() OVER (PARTITION BY id ORDER BY ts DESC)",
            "WHERE s.v = 1",
        )
    )
    assert roles["subq:s"] == "window"


# ---------------------------------------------------------------------- a dedup


@pytest.mark.parametrize(
    "window",
    [
        "ROW_NUMBER() OVER (PARTITION BY id ORDER BY ts DESC)",
        "RANK() OVER (PARTITION BY id ORDER BY ts DESC)",
        "DENSE_RANK() OVER (PARTITION BY id ORDER BY ts DESC)",
    ],
)
def test_a_ranking_window_pinned_to_one_by_its_reader_is_a_dedup(window: str) -> None:
    roles = _roles(_ranked_subquery(window, "WHERE s.rn = 1"))
    assert roles["subq:s"] == "dedup"


def test_a_ranking_window_cut_to_a_small_top_n_is_a_dedup() -> None:
    roles = _roles(
        _ranked_subquery(
            "RANK() OVER (PARTITION BY id ORDER BY ts DESC)", "WHERE s.rn <= 3"
        )
    )
    assert roles["subq:s"] == "dedup"


def test_a_ranking_window_pinned_inside_a_join_on_clause_is_a_dedup() -> None:
    """``LEFT JOIN d ON x.id = d.id AND d.rn = 1`` is the same dedup, written in ON."""
    roles = _roles(
        """
INSERT OVERWRITE TABLE mart.t
WITH latest AS (
  SELECT id, name, ROW_NUMBER() OVER (PARTITION BY id ORDER BY id DESC) AS rn
  FROM ods.dim
)
SELECT e.id, l.name
FROM ods.e e
LEFT JOIN latest l ON e.id = l.id AND l.rn = 1
"""
    )
    assert roles["cte:latest"] == "dedup"


def test_a_column_whose_name_merely_ends_in_the_rank_name_is_not_the_pin() -> None:
    """``turn = 1`` must not be read as a pin on a rank column called ``rn``."""
    roles = _roles(
        """
INSERT OVERWRITE TABLE mart.t
SELECT id, v
FROM (
  SELECT id, v, grp AS turn, ROW_NUMBER() OVER (PARTITION BY id ORDER BY ts) AS rn
  FROM ods.e
) s
WHERE s.turn = 1
"""
    )
    assert roles["subq:s"] == "window"


# --------------------------------------------------------- the rest of the vocabulary


def test_the_other_roles_are_untouched() -> None:
    roles = _roles(
        """
INSERT OVERWRITE TABLE mart.t
WITH agg AS (
  SELECT id, SUM(v) AS total FROM ods.e GROUP BY id
), joined AS (
  SELECT a.id, a.total, d.name FROM agg a JOIN ods.dim d ON a.id = d.id
)
SELECT id, total, name FROM joined WHERE total > 0
"""
    )
    assert roles["cte:agg"] == "aggregate"
    assert roles["cte:joined"] == "join"
    assert roles["ROOT"] == "filter"
