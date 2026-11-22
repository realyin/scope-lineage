"""Resolve hops through relations that do not outlive the session.

The task document records what the SQL says: `mart.t.v` reads `tmp_v.v`, and `tmp_v.v` reads
`ods.real.v`. Both are facts, and Core keeps both -- removing the first would be a deletion no
consumer could detect. Collapsing them is a consumer's decision, and this is that decision
implemented once, correctly, instead of in each consumer.

Correctly is the operative word. Every guard below stands for a way the obvious implementation
is wrong, each found by running it rather than by reading it:

* a source with no table is not a relation to resolve. A constant is `source_kind=generated`;
  folding it away deletes a real fact.
* a relation defined in terms of itself needs a bound, or the walk never ends.
* `end_to_end_lineage` is a *final-state* view. A hop into an earlier state of a redefined
  relation has no row and cannot have one, and substituting the surviving definition asserts
  the wrong origin -- the artifact was ambiguous, and folding would make it confidently wrong.
* a relation whose own columns were never resolved has no row for the column being read, only
  one keyed on `*`.
* a hop through a relation passes through that relation's own row conditions. Folding the
  value alone kept ``ods.real.id`` and dropped the ``amt > 0`` that decided which ids exist --
  while claiming the fold was complete (C2.2).
* every field that names a relation folds, not only values and row conditions: a window's
  PARTITION BY and a MERGE condition read through a temp view named the view after it was
  gone (C2.3-1).
* the same sub-question recurs across a fanned-out chain of views; without a cache the walk
  is exponential in the chain's length (C2.3-4).

In each unresolvable case the original edge is kept and the row says why. Returning fewer
sources would turn a gap into a clean answer that happens to be false, which is the failure
this whole exercise exists to avoid.
"""

from __future__ import annotations

import copy
from typing import Any

from ..scope.composition import compose_hop, source_identity

# A relation defined through more than this many session-scoped hops is not something to keep
# walking; the bound exists so a cycle terminates rather than to model real nesting.
_MAX_HOPS = 16

# The row fields whose entries name a relation, and so can name a session-scoped one.
_REFERENCE_FIELDS = (
    "value_sources",
    "row_membership_sources",
    "value_condition_sources",
    "window_context_sources",
)


def _index(document: dict) -> dict[tuple[str, str], list[dict]]:
    return {
        (item.get("table"), item.get("column")): item.get("value_sources") or []
        for item in document.get("end_to_end_lineage") or []
        if item.get("table") is not None
    }


def _row_index(document: dict) -> dict[tuple[str, str], list[dict]]:
    return {
        (item.get("table"), item.get("column")): item.get("row_membership_sources") or []
        for item in document.get("end_to_end_lineage") or []
        if item.get("table") is not None
    }


def _relation_rowsets(document: dict) -> dict[str, list[str]]:
    """``state_id -> the physical tables whose rows that state's statement reads``.

    Walked from the statement's ROOT through the relations each scope reads, the same
    walk the task level uses for a ``COUNT(*)``'s own row set.
    """
    statements = document.get("statement_lineage") or {}
    found: dict[str, list[str]] = {}
    for step in document.get("statement_sequence") or []:
        state = step.get("output_state")
        scopes = (statements.get(step.get("statement_id")) or {}).get("scopes") or {}
        if not state or "ROOT" not in scopes:
            continue
        tables: list[str] = []
        pending, seen = ["ROOT"], set()
        while pending:
            scope_id = pending.pop(0)
            if scope_id in seen:
                continue
            seen.add(scope_id)
            for item in (scopes.get(scope_id) or {}).get("depends_on") or []:
                if item in scopes:
                    pending.append(item)
                elif item not in tables:
                    tables.append(item)
        found[state] = tables
    return found


def _states_read(document: dict) -> dict[str, dict[str, str]]:
    """``state_id -> {table: the state that table was in when that state's statement ran}``.

    What a statement read is the latest state each table had *before* it, not the one the
    script ends with: a view redefined after the read is not what was read.
    """
    current: dict[str, str] = {}
    found: dict[str, dict[str, str]] = {}
    for step in document.get("statement_sequence") or []:
        state = step.get("output_state")
        if not state:
            continue
        found[state] = dict(current)
        if step.get("target_table"):
            current[str(step["target_table"])] = str(state)
    return found


def _state_conditions(document: dict) -> dict[str, list[dict]]:
    """``state_id -> the row conditions that decided which rows that state holds``."""
    found: dict[str, list[dict]] = {}
    for row in document.get("end_to_end_lineage") or []:
        bucket = found.setdefault(str(row.get("target_state")), [])
        for condition in row.get("row_membership_sources") or []:
            if condition not in bucket:
                bucket.append(condition)
    return found


def _states_present(document: dict) -> set[str]:
    return {
        item.get("target_state")
        for item in document.get("end_to_end_lineage") or []
        if item.get("target_state")
    }


def _scoped_tables(document: dict) -> set:
    """Every relation the document says lives only in the session.

    Both the edges (``session_scoped`` on a source or condition) and the statements
    (``is_session_scoped_relation``): a temp view nobody reads has no edge naming it, and
    reading only the edges left it in the folded document as if it were a table (C2.3-2).
    """
    scoped = {
        step.get("target_table")
        for step in document.get("statement_sequence") or []
        if step.get("is_session_scoped_relation") and step.get("target_table")
    }
    for row in document.get("end_to_end_lineage") or []:
        for field in _REFERENCE_FIELDS:
            for item in row.get(field) or []:
                if item.get("session_scoped"):
                    scoped.add(item.get("table"))
    return scoped


def _field(item: dict) -> dict:
    return {"table": item.get("table"), "column": item.get("column")}


def _append_new(bucket: list[dict], items: list[dict]) -> None:
    for item in items:
        if item not in bucket:
            bucket.append(item)


class _Fold:
    """The indexes of one document and the answers already worked out for it.

    One instance per `fold_session_scoped` call. The cache is keyed by
    ``(table, column, source_state)``: the same column of the same state resolves to the same
    leaves and conditions whichever row asked, so a fanned-out chain of views is walked once
    per column instead of once per path.
    """

    def __init__(self, document: dict) -> None:
        self.by_column = _index(document)
        self.rows_by_column = _row_index(document)
        self.states_present = _states_present(document)
        self.rowsets = _relation_rowsets(document)
        self.states_read = _states_read(document)
        self.conditions_by_state = _state_conditions(document)
        self.scoped_tables = _scoped_tables(document)
        self._cache: dict[tuple, tuple[list[dict], list[dict], frozenset[str]]] = {}

    def hop(
        self, source: dict, reasons: set[str], depth: int = 0
    ) -> tuple[list[dict], list[dict]]:
        """``source`` as the leaves it reads, and the row conditions of every hop on the way.

        A source that does not read a session relation is its own leaf and passes no
        condition; one that cannot be resolved is kept as-is and ``reasons`` says why.
        """
        if not source.get("session_scoped"):
            return [source], []
        if depth >= _MAX_HOPS:
            reasons.add("fold_depth_exceeded")
            return [source], []

        state = source.get("source_state")
        if state is not None and state not in self.states_present:
            # The read saw an earlier definition of a relation that was later replaced. Only
            # the final state has a row, so substituting it would name the wrong origin.
            reasons.add("source_state_not_in_document")
            return [source], []

        key = (source.get("table"), source.get("column"))
        if key not in self.by_column:
            # Typically a relation built from an unexpanded `SELECT *`: its only row is keyed
            # on `*`, so the column being read was never described.
            reasons.add("source_column_not_in_document")
            return [source], []
        if not self.by_column[key]:
            reasons.add("source_column_has_no_sources")
            return [source], []

        leaves, conditions = self._expand(key, state, reasons, depth)
        return [compose_hop(source, leaf) for leaf in leaves], conditions

    def _expand(
        self, key: tuple, state: Any, reasons: set[str], depth: int
    ) -> tuple[list[dict], list[dict]]:
        cached = self._cache.get((*key, state))
        if cached is None:
            local: set[str] = set()
            leaves: list[dict] = []
            seen: set[str] = set()
            conditions: list[dict] = []
            for item in self.by_column[key]:
                sub_leaves, sub_conditions = self.hop(item, local, depth + 1)
                for leaf in sub_leaves:
                    identity = source_identity(leaf)
                    if identity not in seen:
                        seen.add(identity)
                        leaves.append(leaf)
                _append_new(conditions, sub_conditions)
            # The relation's own row conditions decided which of these values exist at all.
            for inner in self.rows_by_column.get(key) or []:
                _append_new(conditions, self.condition(inner, local, depth + 1))
            cached = (leaves, conditions, frozenset(local))
            if "fold_depth_exceeded" not in local:
                # A walk cut short by the bound depends on how deep it started; keep only
                # answers that hold from anywhere.
                self._cache[(*key, state)] = cached
        reasons |= cached[2]
        return cached[0], cached[1]

    def condition(self, condition: dict, reasons: set[str], depth: int = 0) -> list[dict]:
        """A condition field read through a session relation, as the physical fields it reads.

        ``tv.keep`` decides a row as ``tv``'s own ``keep`` does: the physical columns that
        value comes from, plus whatever decided which rows ``tv`` holds at all. Only
        ``(table, column)`` survives, because a condition names a field, not a path.
        """
        if not condition.get("session_scoped"):
            return [_field(condition)]
        leaves, conditions = self.hop({**condition, "source_kind": "physical_field"}, reasons, depth)
        if any(leaf.get("session_scoped") for leaf in leaves):
            return [condition]
        resolved = [
            _field(leaf)
            for leaf in leaves
            if leaf.get("table") is not None and leaf.get("column") is not None
        ]
        _append_new(resolved, conditions)
        return resolved

    def context(self, entry: dict, reasons: set[str]) -> list[dict]:
        """A window PARTITION BY / ORDER BY field read through a session relation.

        Only the fields the column comes from: the view's row conditions decide which rows
        exist, not how they are partitioned, and they reach the row through its values.
        """
        if not entry.get("session_scoped"):
            return [entry]
        leaves, _ = self.hop({**entry, "source_kind": "physical_field"}, reasons)
        if any(leaf.get("session_scoped") for leaf in leaves):
            return [entry]
        extra = {k: v for k, v in entry.items() if k == "role"}
        return [
            {**_field(leaf), **extra}
            for leaf in leaves
            if leaf.get("table") is not None and leaf.get("column") is not None
        ]

    def rowset(self, source: dict, reasons: set[str]) -> tuple[list[dict], list[dict]]:
        """A ``COUNT(*)`` read through a session relation, as the row sets of its tables.

        The relation's rows are its tables' rows kept by its own conditions, and those
        conditions decide the count as much as any of the outer; a relation that reads
        another session relation recurses into the state it read.
        """
        expanded = self._rowset_tables(str(source.get("source_state")), reasons, 0)
        if expanded is None:
            reasons.add("rowset_relation_unresolved")
            return [source], []
        tables, conditions = expanded
        leaves = [
            {
                "source_kind": "rowset",
                "table": table,
                "transform": source.get("transform"),
                "expression": source.get("expression"),
            }
            for table in tables
        ]
        return leaves, conditions

    def _rowset_tables(
        self, state: str, reasons: set[str], depth: int
    ) -> tuple[list[str], list[dict]] | None:
        tables = self.rowsets.get(state)
        if not tables:
            return None
        found: list[str] = []
        conditions: list[dict] = list(self.conditions_by_state.get(state) or [])
        for table in tables:
            if table not in self.scoped_tables:
                if table not in found:
                    found.append(table)
                continue
            if depth + 1 >= _MAX_HOPS:
                reasons.add("fold_depth_exceeded")
                return None
            inner = (self.states_read.get(state) or {}).get(table)
            if inner is None or inner not in self.states_present:
                # Read before a redefinition (or never defined in the script): the
                # surviving rows are not the ones that were counted.
                return None
            expanded = self._rowset_tables(inner, reasons, depth + 1)
            if expanded is None:
                return None
            for item in expanded[0]:
                if item not in found:
                    found.append(item)
            _append_new(conditions, expanded[1])
        return found, conditions

    def needs_fold(self, row: dict) -> bool:
        return any(
            item.get("session_scoped") or item.get("table") in self.scoped_tables
            for field in _REFERENCE_FIELDS
            for item in row.get(field) or []
        )

    def unmarked(self, row: dict) -> bool:
        """Does ``row`` still name a session relation on an entry nobody stamped?

        Such an entry comes from a producer that did not say which state it read; the fold
        cannot recognise it, and keeping it without a word would claim completeness.
        """
        return any(
            item.get("table") in self.scoped_tables and not item.get("session_scoped")
            for field in _REFERENCE_FIELDS
            for item in row.get(field) or []
        )


def _fold_values(fold: _Fold, sources: list[dict], reasons: set[str]) -> tuple[list[dict], list[dict]]:
    resolved: list[dict] = []
    conditions: list[dict] = []
    seen: set[str] = set()
    for source in sources:
        if source.get("source_kind") == "rowset" and source.get("session_scoped"):
            leaves, extra = fold.rowset(source, reasons)
        else:
            leaves, extra = fold.hop(source, reasons)
        _append_new(conditions, extra)
        for item in leaves:
            key = source_identity(item)
            if key in seen:
                continue
            seen.add(key)
            resolved.append(item)
    return resolved, conditions


def _fold_conditions(fold: _Fold, conditions: list[dict], reasons: set[str]) -> list[dict]:
    fields: list[dict] = []
    for condition in conditions:
        _append_new(fields, fold.condition(condition, reasons))
    return fields


def _fold_row(fold: _Fold, row: dict) -> None:
    reasons: set[str] = set()
    values, hop_conditions = _fold_values(fold, row.get("value_sources") or [], reasons)
    if any(source.get("session_scoped") for source in row.get("value_sources") or []):
        row["value_sources"] = values
    conditions = list(row.get("row_membership_sources") or [])
    _append_new(conditions, hop_conditions)
    if hop_conditions or any(item.get("session_scoped") for item in conditions):
        row["row_membership_sources"] = _fold_conditions(fold, conditions, reasons)
    value_conditions = row.get("value_condition_sources") or []
    if any(item.get("session_scoped") for item in value_conditions):
        row["value_condition_sources"] = _fold_conditions(fold, value_conditions, reasons)
    window = row.get("window_context_sources") or []
    if any(item.get("session_scoped") for item in window):
        context: list[dict] = []
        for entry in window:
            _append_new(context, fold.context(entry, reasons))
        row["window_context_sources"] = context
    if fold.unmarked(row):
        reasons.add("session_scoped_reference_unmarked")
    row["value_sources_folded"] = not reasons
    if reasons:
        row["fold_incomplete_reasons"] = sorted(reasons)


def fold_session_scoped(document: dict) -> dict:
    """A copy of `document` with hops through session-scoped relations resolved.

    Each `end_to_end_lineage` row that had such a hop -- in its values, row conditions,
    value conditions or window context -- gains `value_sources_folded`, and the rows
    describing the session-scoped relations themselves are dropped along with their
    `final_table_states` entries -- they were never tables in the warehouse. A value read
    through a relation also takes that relation's row conditions into
    `row_membership_sources`, at every hop.

    Where a hop could not be resolved the original source is kept and
    `fold_incomplete_reasons` says why, so an unresolved hop stays visible instead of becoming
    a shorter answer.

    The input is not modified.
    """
    folded = copy.deepcopy(document)
    fold = _Fold(document)
    rows: list[dict[str, Any]] = []
    for row in folded.get("end_to_end_lineage") or []:
        if row.get("table") in fold.scoped_tables:
            continue
        if fold.needs_fold(row):
            _fold_row(fold, row)
        rows.append(row)

    folded["end_to_end_lineage"] = rows
    folded["final_table_states"] = {
        table: state
        for table, state in (folded.get("final_table_states") or {}).items()
        if table not in fold.scoped_tables
    }
    return folded
