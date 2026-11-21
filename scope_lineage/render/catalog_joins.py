"""What the catalog says about joining two tables: one place for ``context`` and ``check-sql``.

``catalog context`` tells an agent how to join two tables before it writes SQL, and
``catalog check-sql`` judges the joins it wrote. Both read the same four facts from the
built document, here, so the advice and the check can never disagree:

- ``backed_pairs``: the column pairs the catalog backs between two tables -- both columns
  bind the same identifier (``identifier`` / ``foreign_identifier``), or the corpus evidence
  recorded a JOIN on exactly that pair.
- ``grain_columns``: the columns of a table's recorded grain, or None when it records none.
- ``uncovered``: the grain columns a set of columns leaves open (one row per key when none).
- ``time_groups``: the column groups a read must filter -- the partition of a table whose
  every partition is a full copy, and a zipper's validity window -- and ``pin_window``: a
  predicate on one window column pins the whole window.

Whether a partition must be filtered is the representation's ``time``: only a ``snapshot``
table holds a full copy in each partition, so reading two partitions counts every row twice.
An ``incremental`` table's partition is the batch that first wrote a row, not the day the
event happened, and a period is read across partitions by the event-time column; a missing
partition predicate there is no correctness problem. A ``zipper`` is read by its window, and
an ``unknown`` (or missing) form says nothing either way: ``partition_reading`` names the
three cases so ``context`` can say which one a table is in.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Optional

from .catalog_view import IDENTIFYING_BINDINGS, CatalogView

__all__ = [
    "PARTITION_BATCH",
    "PARTITION_FULL",
    "PARTITION_UNSTATED",
    "WINDOW_ROLES",
    "backed_pairs",
    "grain_columns",
    "pair_backed",
    "partition_columns",
    "partition_reading",
    "period_columns",
    "pin_window",
    "shares_identifier",
    "time_groups",
    "uncovered",
    "window_columns",
]

WINDOW_ROLES = ("valid_from", "valid_to")
# what a table's partition is, by the representation's ``time``
PARTITION_FULL = "full_copy"  # snapshot: each partition is a full copy, read one
PARTITION_BATCH = "write_batch"  # incremental: the batch that wrote the row, not the event day
PARTITION_UNSTATED = "unstated"  # zipper, unknown or missing: the catalog does not say
_PARTITION_BY_TIME = {"snapshot": PARTITION_FULL, "incremental": PARTITION_BATCH}
# the roles a period is filtered on, in order of preference
_PERIOD_ROLES = ("event_time", "business_date")


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


def partition_columns(rep: Mapping) -> list[str]:
    """The columns bound with ``time_role: partition``."""
    return [b["column"] for b in rep["bindings"] if b.get("time_role") == "partition"]


def partition_reading(rep: Mapping) -> Optional[str]:
    """``PARTITION_FULL`` / ``PARTITION_BATCH`` / ``PARTITION_UNSTATED`` for a table with a
    partition column, by its ``time``; None for a table with none."""
    if not partition_columns(rep):
        return None
    return _PARTITION_BY_TIME.get(rep.get("time"), PARTITION_UNSTATED)


def period_columns(rep: Mapping) -> list[str]:
    """The columns a period is filtered on: those with ``time_role: event_time``, or, when
    there are none, those with ``business_date``."""
    for role in _PERIOD_ROLES:
        columns = [b["column"] for b in rep["bindings"] if b.get("time_role") == role]
        if columns:
            return columns
    return []


def time_groups(rep: Mapping) -> list[tuple[str, list[dict]]]:
    """``[(partition | window, [{column, role}, ...])]``: the groups a read must filter --
    the partition only when each partition is a full copy (see the module)."""
    groups = []
    roles = [("window", WINDOW_ROLES)]
    if partition_reading(rep) == PARTITION_FULL:
        roles.insert(0, ("partition", ("partition",)))
    for name, wanted in roles:
        columns = [
            {"column": b["column"], "role": b["time_role"]}
            for b in rep["bindings"]
            if b.get("time_role") in wanted
        ]
        if columns:
            groups.append((name, columns))
    return groups
