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

In each unresolvable case the original edge is kept and the row says why. Returning fewer
sources would turn a gap into a clean answer that happens to be false, which is the failure
this whole exercise exists to avoid.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from ..scope.end_to_end import dominant_transform

# A relation defined through more than this many session-scoped hops is not something to keep
# walking; the bound exists so a cycle terminates rather than to model real nesting.
_MAX_HOPS = 16


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


def _resolve_condition(
    condition: dict,
    by_column: dict[tuple[str, str], list[dict]],
    rows_by_column: dict[tuple[str, str], list[dict]],
    states_present: set[str],
    reasons: set[str],
    depth: int = 0,
) -> list[dict]:
    """A row condition read through a session relation, as the physical fields it reads.

    ``tv.keep`` decides a row as ``tv``'s own ``keep`` does: the physical columns that
    value comes from, plus whatever decided which rows ``tv`` holds at all. Only
    ``(table, column)`` survives, because a condition names a field, not a path.
    """
    if not condition.get("session_scoped"):
        return [{"table": condition.get("table"), "column": condition.get("column")}]
    if depth >= _MAX_HOPS:
        reasons.add("fold_depth_exceeded")
        return [condition]
    key = (condition.get("table"), condition.get("column"))
    leaves = _resolve(
        {**condition, "source_kind": "physical_field"},
        by_column,
        states_present,
        reasons,
    )
    if any(leaf.get("session_scoped") for leaf in leaves):
        return [condition]
    resolved = [
        {"table": leaf.get("table"), "column": leaf.get("column")}
        for leaf in leaves
        if leaf.get("table") is not None and leaf.get("column") is not None
    ]
    for inner in rows_by_column.get(key) or []:
        resolved.extend(
            _resolve_condition(
                inner, by_column, rows_by_column, states_present, reasons, depth + 1
            )
        )
    return resolved


def _states_present(document: dict) -> set[str]:
    return {
        item.get("target_state")
        for item in document.get("end_to_end_lineage") or []
        if item.get("target_state")
    }


def _resolve(
    source: dict,
    by_column: dict[tuple[str, str], list[dict]],
    states_present: set[str],
    reasons: set[str],
    depth: int = 0,
) -> list[dict]:
    if not source.get("session_scoped"):
        return [source]
    if depth >= _MAX_HOPS:
        reasons.add("fold_depth_exceeded")
        return [source]

    state = source.get("source_state")
    if state is not None and state not in states_present:
        # The read saw an earlier definition of a relation that was later replaced. Only the
        # final state has a row, so substituting it would name the wrong origin.
        reasons.add("source_state_not_in_document")
        return [source]

    key = (source.get("table"), source.get("column"))
    if key not in by_column:
        # Typically a relation built from an unexpanded `SELECT *`: its only row is keyed on
        # `*`, so the column being read was never described.
        reasons.add("source_column_not_in_document")
        return [source]

    upstream = by_column[key]
    if not upstream:
        reasons.add("source_column_has_no_sources")
        return [source]

    resolved: list[dict] = []
    for item in upstream:
        for leaf in _resolve(item, by_column, states_present, reasons, depth + 1):
            resolved.append(_through(source, leaf))
    return resolved


def _through(hop: dict, leaf: dict) -> dict:
    """``leaf`` as read through ``hop``: the path's transform is the stronger of the two.

    Returning the upstream fact unchanged dropped what the hop itself did -- ``v * 2``
    over a pass-through view came back ``DIRECT`` -- so the same SQL read through one
    more relation got a different explanation.
    """
    if not hop.get("transform") or not leaf.get("transform"):
        return leaf
    composed = dominant_transform(str(hop["transform"]), str(leaf["transform"]))
    return leaf if composed == leaf["transform"] else {**leaf, "transform": composed}


def _identity(source: dict) -> str:
    """A source's whole content: `(table, column, source_kind)` is not an identity.

    Two constants both have no table and no column, and two paths to one column differ
    by transform; the contract keeps each participation path, so only an exact
    duplicate is one.
    """
    return json.dumps(source, sort_keys=True, ensure_ascii=False, default=str)


def fold_session_scoped(document: dict) -> dict:
    """A copy of `document` with hops through session-scoped relations resolved.

    Each `end_to_end_lineage` row that had such a hop gains `value_sources_folded`, and the
    rows describing the session-scoped relations themselves are dropped along with their
    `final_table_states` entries -- they were never tables in the warehouse.

    Where a hop could not be resolved the original source is kept and
    `fold_incomplete_reasons` says why, so an unresolved hop stays visible instead of becoming
    a shorter answer.

    The input is not modified.
    """
    folded = copy.deepcopy(document)
    by_column = _index(document)
    rows_by_column = _row_index(document)
    states_present = _states_present(document)
    scoped_tables = {
        source.get("table")
        for sources in by_column.values()
        for source in sources
        if source.get("session_scoped")
    }

    rows: list[dict[str, Any]] = []
    scoped_tables |= {
        condition.get("table")
        for conditions in rows_by_column.values()
        for condition in conditions
        if condition.get("session_scoped")
    }
    for row in folded.get("end_to_end_lineage") or []:
        if row.get("table") in scoped_tables:
            continue
        sources = row.get("value_sources") or []
        conditions = row.get("row_membership_sources") or []
        scoped_values = any(source.get("session_scoped") for source in sources)
        scoped_conditions = any(item.get("session_scoped") for item in conditions)
        if not scoped_values and not scoped_conditions:
            rows.append(row)
            continue

        reasons: set[str] = set()
        if scoped_values:
            resolved: list[dict] = []
            seen: set[str] = set()
            for source in sources:
                for item in _resolve(source, by_column, states_present, reasons):
                    key = _identity(item)
                    if key in seen:
                        continue
                    seen.add(key)
                    resolved.append(item)
            row["value_sources"] = resolved
        if scoped_conditions:
            fields: list[dict] = []
            for condition in conditions:
                for item in _resolve_condition(
                    condition, by_column, rows_by_column, states_present, reasons
                ):
                    if item not in fields:
                        fields.append(item)
            row["row_membership_sources"] = fields
        row["value_sources_folded"] = not reasons
        if reasons:
            row["fold_incomplete_reasons"] = sorted(reasons)
        rows.append(row)

    folded["end_to_end_lineage"] = rows
    folded["final_table_states"] = {
        table: state
        for table, state in (folded.get("final_table_states") or {}).items()
        if table not in scoped_tables
    }
    return folded
