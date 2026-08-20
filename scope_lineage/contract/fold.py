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
from typing import Any

# A relation defined through more than this many session-scoped hops is not something to keep
# walking; the bound exists so a cycle terminates rather than to model real nesting.
_MAX_HOPS = 16


def _index(document: dict) -> dict[tuple[str, str], list[dict]]:
    return {
        (item.get("table"), item.get("column")): item.get("value_sources") or []
        for item in document.get("end_to_end_lineage") or []
        if item.get("table") is not None
    }


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
        resolved.extend(_resolve(item, by_column, states_present, reasons, depth + 1))
    return resolved


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
    states_present = _states_present(document)
    scoped_tables = {
        source.get("table")
        for sources in by_column.values()
        for source in sources
        if source.get("session_scoped")
    }

    rows: list[dict[str, Any]] = []
    for row in folded.get("end_to_end_lineage") or []:
        if row.get("table") in scoped_tables:
            continue
        sources = row.get("value_sources") or []
        if not any(source.get("session_scoped") for source in sources):
            rows.append(row)
            continue

        reasons: set[str] = set()
        resolved: list[dict] = []
        seen: set[tuple] = set()
        for source in sources:
            for item in _resolve(source, by_column, states_present, reasons):
                key = (item.get("table"), item.get("column"), item.get("source_kind"))
                if key in seen:
                    continue
                seen.add(key)
                resolved.append(item)
        row["value_sources"] = resolved
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
