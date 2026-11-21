"""What the catalog says about joining two tables: one place for ``context`` and ``check-sql``.

``catalog context`` tells an agent how to join two tables before it writes SQL, and
``catalog check-sql`` judges the joins it wrote. Both read the same four facts from the
built document, here, so the advice and the check can never disagree:

- ``backed_pairs``: the column pairs the catalog backs between two tables -- both columns
  bind the same identifier (``identifier`` / ``foreign_identifier``), or the corpus evidence
  recorded a JOIN on exactly that pair.
- ``grain_columns``: the columns of a table's recorded grain, or None when it records none.
- ``uncovered``: the grain columns a set of columns leaves open (one row per key when none).
- ``time_groups``: the column groups a read must filter -- the load partition, and a
  zipper's validity window -- and ``pin_window``: a predicate on one window column pins the
  whole window.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Optional

from .catalog_view import IDENTIFYING_BINDINGS, CatalogView

__all__ = [
    "WINDOW_ROLES",
    "backed_pairs",
    "grain_columns",
    "pair_backed",
    "pin_window",
    "shares_identifier",
    "time_groups",
    "uncovered",
    "window_columns",
]

WINDOW_ROLES = ("valid_from", "valid_to")
_TIME_GROUPS = (("partition", ("partition",)), ("window", WINDOW_ROLES))


def shares_identifier(a: Mapping, b: Mapping) -> bool:
    """Whether two bindings hold the same identifier (a key, or a foreign key to it)."""
    return (
        a["to"] in IDENTIFYING_BINDINGS
        and b["to"] in IDENTIFYING_BINDINGS
        and bool(a.get("ref"))
        and a.get("ref") == b.get("ref")
    )


def backed_pairs(view: CatalogView, rep_a: Mapping, rep_b: Mapping) -> list[dict]:
    """The column pairs the catalog backs between two tables: shared identifiers (with
    ``identifier``), then the JOINs the corpus evidence recorded between them (with
    ``relation``). ``left`` is always a column of ``rep_a``, as ``db.table.column``."""
    found: list[dict] = []
    for a in rep_a["bindings"]:
        for b in rep_b["bindings"]:
            if shares_identifier(a, b):
                found.append({
                    "left": f"{rep_a['table']}.{a['column']}",
                    "right": f"{rep_b['table']}.{b['column']}",
                    "identifier": a["ref"],
                })
    wanted = {rep_a["table"].lower(), rep_b["table"].lower()}
    for relation_id in sorted(view.relations):
        joins = view.relation_joins(relation_id) or {}
        for sample in joins.get("samples") or []:
            left, _, right = str(sample.get("on") or "").partition(" = ")
            tables = {left.rpartition(".")[0].lower(), right.rpartition(".")[0].lower()}
            if tables != wanted or not left or not right:
                continue
            if rep_a["table"].lower() != left.rpartition(".")[0].lower():
                left, right = right, left
            if not any({p["left"], p["right"]} == {left, right} for p in found):
                found.append({"left": left, "right": right, "relation": relation_id})
    return found


def pair_backed(view: CatalogView, rep_a: Mapping, bind_a: Mapping, rep_b: Mapping,
                bind_b: Mapping) -> bool:
    """Whether the catalog backs joining ``rep_a.bind_a`` to ``rep_b.bind_b``."""
    if shares_identifier(bind_a, bind_b):
        return True
    asked = {f"{rep_a['table']}.{bind_a['column']}", f"{rep_b['table']}.{bind_b['column']}"}
    return any({p["left"], p["right"]} == asked for p in backed_pairs(view, rep_a, rep_b))


def grain_columns(rep: Mapping) -> Optional[list[str]]:
    """The columns of the table's recorded grain, or None when the catalog does not say."""
    grain = rep.get("grain") or {}
    columns = []
    for identifier in grain.get("identifiers") or []:
        column = next(
            (b["column"] for b in rep["bindings"]
             if b["to"] == "identifier" and b.get("ref") == identifier),
            None,
        )
        if column is None:
            return None
        columns.append(column)
    columns += list(grain.get("extra") or [])
    return columns or None


def uncovered(grain: Iterable[str], columns: Iterable[str]) -> list[str]:
    """The grain columns not among ``columns`` (names compared ignoring case)."""
    folded = {str(c).casefold() for c in columns}
    return [g for g in grain if g.casefold() not in folded]


def window_columns(rep: Mapping) -> set[str]:
    """A zipper's validity-window columns, case-folded."""
    return {b["column"].casefold() for b in rep["bindings"] if b.get("time_role") in WINDOW_ROLES}


def pin_window(rep: Mapping, pinned: set[str]) -> set[str]:
    """``pinned`` (case-folded) plus the whole window when it pins one window column."""
    window = window_columns(rep)
    return pinned | window if pinned & window else set(pinned)


def time_groups(rep: Mapping) -> list[tuple[str, list[dict]]]:
    """``[(partition | window, [{column, role}, ...])]``: the groups a read must filter."""
    groups = []
    for name, roles in _TIME_GROUPS:
        columns = [
            {"column": b["column"], "role": b["time_role"]}
            for b in rep["bindings"]
            if b.get("time_role") in roles
        ]
        if columns:
            groups.append((name, columns))
    return groups
