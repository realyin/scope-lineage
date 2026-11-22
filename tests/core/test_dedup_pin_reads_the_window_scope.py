"""A rank is pinned only by a predicate that reads the window scope's own column.

``ROW_NUMBER() ... AS rn`` is a dedup stage when a scope that reads it keeps ``rn = 1``.
Two predicates were taken for that pin (1.13-f):

* the window scope's own ``WHERE a.rn = 1`` -- Spark evaluates WHERE before the
  projection, so that ``rn`` is a source column, never the window's output;
* a reader's ``o.rn = 1`` where ``o`` is another table that happens to have an ``rn``.

Both are now ``window``; a reader pinning ``w.rn = 1`` stays ``dedup`` (WP3k).

Every name here is synthetic.
"""

from __future__ import annotations

from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {"s.a": ["k", "ts", "rn", "v"], "s.o": ["k", "rn"]}
WINDOW = "SELECT a.k, ROW_NUMBER() OVER (PARTITION BY a.k ORDER BY a.ts) AS rn FROM s.a a"


def _role(sql: str) -> str:
    return parse_scope_lineage(sql, "t", schema=SCHEMA).scopes["cte:w"].role


def test_the_window_scopes_own_where_does_not_pin_its_rank() -> None:
    assert _role(
        f"WITH w AS ({WINDOW} WHERE a.rn = 1) INSERT OVERWRITE TABLE m.t SELECT k, rn FROM w"
    ) == "window"


def test_another_tables_rank_column_does_not_pin_the_window() -> None:
    assert _role(
        f"WITH w AS ({WINDOW}) INSERT OVERWRITE TABLE m.t SELECT w.k, w.rn FROM w "
        "JOIN s.o o ON w.k = o.k WHERE w.rn > 3 AND o.rn = 1"
    ) == "window"


def test_another_tables_rank_column_in_the_on_clause_does_not_pin_the_window() -> None:
    assert _role(
        f"WITH w AS ({WINDOW}) INSERT OVERWRITE TABLE m.t SELECT w.k, w.rn FROM w "
        "JOIN s.o o ON w.k = o.k AND o.rn = 1"
    ) == "window"


def test_a_reader_pinning_the_window_column_is_still_dedup() -> None:
    assert _role(
        f"WITH w AS ({WINDOW}) INSERT OVERWRITE TABLE m.t SELECT w.k FROM w WHERE w.rn = 1"
    ) == "dedup"


def test_a_reader_pinning_it_beside_another_tables_rank_is_still_dedup() -> None:
    assert _role(
        f"WITH w AS ({WINDOW}) INSERT OVERWRITE TABLE m.t SELECT w.k FROM w "
        "JOIN s.o o ON w.k = o.k WHERE o.rn > 3 AND w.rn = 1"
    ) == "dedup"


def test_an_unfiltered_window_is_window() -> None:
    assert _role(f"WITH w AS ({WINDOW}) INSERT OVERWRITE TABLE m.t SELECT k, rn FROM w") == "window"
