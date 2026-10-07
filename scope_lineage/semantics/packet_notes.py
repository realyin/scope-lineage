"""Statement facts the packet transcribes from the profile once its rules are numbered.

- :func:`mark_undecided_joins` -- where a JOIN the profile gave no fan-out verdict sits:
  inside the right side of joins that have one (``inside``), below an aggregate
  (``below_aggregate``), or neither;
- :func:`statement_findings` -- the governance findings a writer must see (a positional
  write whose aliases disagree with the target's columns, one alias naming two sources,
  an empty-string test on a column that is no string, a numeric test on a string column,
  a window grouped on fewer columns than the batch key of the rows it reads), each with
  its task, statement and the packet rules it is about;
- :func:`merge_block` -- a MERGE's merge key, WHEN clauses and the comparison of its
  USING side's dedup with the merge key, the profile's ``output_shape.merge``.

All three need the packet's rule numbers, so they run after the rules are numbered and
before the private keys the rules carried are dropped.
"""

from __future__ import annotations

from .packet_facts import LOGIC_BLOCK, PROFILE_RULE

# The findings a packet carries; the others are the semantic document's (``describe``).
PACKET_FINDINGS = (
    "alias_position_mismatch",
    "duplicate_alias",
    "empty_string_on_non_string",
    "numeric_compare_on_string",
    "window_partition_narrower",
)


def _statement_key(item: dict) -> tuple:
    return item.get("task"), item.get("statement_id")


def mark_undecided_joins(rules: list[dict], statements: list[tuple[str, dict]]) -> None:
    """Say, for each JOIN without a verdict, why it has none -- never "not on the path".

    The profile judges the joins on the grain path; a join with no verdict still sends its
    rows to the output when it sits in another join's right side, where its fan-out is
    counted in that join's verdict: ``inside`` lists every join with a verdict whose right
    side (with everything it reads) holds this join's scope. Failing that, a join under an
    aggregate (its scope read, at any depth, by a scope that aggregates) does not copy
    output rows but may inflate the aggregate: ``below_aggregate`` names that scope. A
    join with neither gets no key and reads as undecided.
    """
    stages = {(task, statement.get("statement_id")): statement.get("stages") or []
              for task, statement in statements}
    for rule in rules:
        if rule["kind"] != "join" or rule.get("fan_out") is not None:
            continue
        key = _statement_key(rule)
        reads = _reads(stages.get(key) or [])
        scope = str(rule.get("scope") or "")
        inside = [
            other["id"]
            for other in rules
            if other["kind"] == "join" and other.get("fan_out") is not None
            and _statement_key(other) == key and scope in _closure(reads, other.get("right"))
        ]
        if inside:
            rule["inside"] = inside
            continue
        below = next(
            (stage["scope_id"] for stage in stages.get(key) or []
             if _aggregates(stage) and scope in _closure(reads, stage["scope_id"])),
            None,
        )
        if below:
            rule["below_aggregate"] = below


def _reads(stages: list[dict]) -> dict[str, list[str]]:
    return {str(stage.get("scope_id")): [str(item) for item in stage.get("direct_inputs") or []]
            for stage in stages}


def _closure(reads: dict[str, list[str]], start) -> set[str]:
    """``start`` and every scope it reads, at any depth."""
    found: set[str] = set()
    pending = [str(start)] if start in reads else []
    while pending:
        scope = pending.pop()
        if scope not in found:
            found.add(scope)
            pending.extend(item for item in reads.get(scope, []) if item in reads)
    return found


def _aggregates(stage: dict) -> bool:
    return any(str(action.get("type")) == "aggregate" for action in stage.get("actions") or [])


def statement_findings(rules: list[dict], statements: list[tuple[str, dict]]) -> list[dict]:
    """``[{kind, severity, task, statement_id, text, rules?}]`` in the profile's order.

    ``rules`` lists the packet rules a finding's evidence names (an empty-string test
    names its rule); the text is the profile's, word for word.
    """
    numbered = {(_statement_key(rule), rule.get(PROFILE_RULE)): rule["id"] for rule in rules}
    found = []
    for task, statement in statements:
        key = (task, statement.get("statement_id"))
        for finding in (statement.get("confidence") or {}).get("findings") or []:
            if finding.get("kind") not in PACKET_FINDINGS:
                continue
            entry = {
                "kind": finding["kind"],
                "severity": finding.get("severity"),
                "task": task,
                "statement_id": statement.get("statement_id"),
                "text": finding.get("text"),
            }
            ids = [numbered[(key, item)] for item in finding.get("evidence") or []
                   if (key, item) in numbered]
            if ids:
                entry["rules"] = ids
            found.append(entry)
    return found


def merge_block(task: str, statement: dict, rules: list[dict]) -> dict | None:
    """The profile's ``output_shape.merge``, its JOINs after the dedup as packet rule ids."""
    merge = (statement.get("output_shape") or {}).get("merge")
    if not merge:
        return None
    block = dict(merge)
    if block.get("joins_after_dedup"):
        key = (task, statement.get("statement_id"))
        ids = {rule.get(LOGIC_BLOCK): rule["id"] for rule in rules
               if rule["kind"] == "join" and _statement_key(rule) == key}
        block["joins_after_dedup"] = [ids.get(item, item) for item in block["joins_after_dedup"]]
    return block
