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

from typing import Mapping, NamedTuple

from sqlglot import exp

from ..render.semantic_text import equals_one_predicate, parse_expression
from .packet_facts import INTENT, LOGIC_BLOCK, PROFILE_RULE, WINDOW

# The findings a packet carries; the others are the semantic document's (``describe``).
PACKET_FINDINGS = (
    "alias_position_mismatch",
    "duplicate_alias",
    "empty_string_on_non_string",
    "numeric_compare_on_string",
    "literal_outside_comment_codes",
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
    stages = _stages(statements)
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
        below = _aggregate_above(stages.get(key) or [], scope)
        if below:
            rule["below_aggregate"] = below


def mark_verdict_paths(rules: list[dict], statements: list[tuple[str, dict]]) -> None:
    """C-P3: name the aggregate a JOIN with a verdict off the grain path sits under.

    The profile judges JOINs on three paths (``fan_out.path``): one on the grain path
    copies output rows, one under an aggregate (``argument``, ``anchor``) does not -- it
    may count a value twice inside the aggregate. ``verdict_aggregate`` is the aggregating
    scope that reads the JOIN's scope, at any depth, when there is one. Unlike
    ``below_aggregate`` it is said of a JOIN that has a verdict.
    """
    stages = _stages(statements)
    for rule in rules:
        path = (rule.get("fan_out") or {}).get("path") if rule["kind"] == "join" else None
        if path in (None, GRAIN_PATH):
            continue
        found = _aggregate_above(stages.get(_statement_key(rule)) or [], rule.get("scope"))
        if found:
            rule["verdict_aggregate"] = found


def mark_unfiltered_rankings(rules: list[dict], statements: list[tuple[str, dict]]) -> None:
    """C-P4: a JOIN not proven safe whose right side ranks rows and keeps them all.

    ``unfiltered_ranking`` lists the ``window`` rows (a ranking the profile found no
    ``= 1`` filter for) in the right side of a JOIN whose verdict is ``risk`` or
    ``unknown``: the rows were numbered, not deduplicated. A safe verdict says nothing
    is copied whatever the right side does, so it gets no note.
    """
    stages = _stages(statements)
    for rule in rules:
        status = (rule.get("fan_out") or {}).get("status") if rule["kind"] == "join" else None
        if status in (None, "safe"):
            continue
        key = _statement_key(rule)
        right = _closure(_reads(stages.get(key) or []), rule.get("right"))
        found = [other["id"] for other in rules
                 if other["kind"] == WINDOW and other.get(INTENT) == RANK_WITHIN_GROUP
                 and _statement_key(other) == key and other.get("scope") in right]
        if found:
            rule["unfiltered_ranking"] = found


class RightSides(NamedTuple):
    """A statement's structural right-side shapes: ``(logic block, window output)`` pairs
    that keep a ranking's first row, and the scopes reading an inline VALUES list."""

    first_row_filters: list[tuple[str, str]]
    values_scopes: set[str]


RANK_FIRST = "rank_first"
VALUES = "values"
_PRESERVING_LEFT = ("LEFT", "LEFT_OUTER")


def mark_right_side_filters(
    rules: list[dict], statements: list[tuple[str, dict]], shapes: Mapping[tuple, RightSides]
) -> None:
    """B-V2: a filter inside a LEFT JOIN's right side, and the structural kind it has.

    ``right_of`` lists the LEFT JOINs whose right side (with everything it reads) holds
    the filter's scope. It is a non-partition filter's only, and only when nothing of the
    statement's driving rows reads that scope: the driving rows are what every root stage
    reads, at any depth, except through a LEFT JOIN's right input -- so a CTE read both
    as ``FROM c a`` and as ``LEFT JOIN c a1`` drives. A LEFT JOIN whose own scope also
    filters on its right side (``WHERE r.k IS NULL``) lets the right side decide which
    target rows survive, and holds no ``right_of`` filter.

    ``right_side_kind`` says what such a filter structurally is, when it is one of two
    things: ``rank_first`` (it keeps a ranking's first row, :class:`RightSides`) or
    ``values`` (its scope reads an inline VALUES list down a single-input chain).
    """
    profile_rules = {(task, statement.get("statement_id")): statement.get("rules") or []
                     for task, statement in statements}
    stages = _stages(statements)
    for key, statement_rules in profile_rules.items():
        reads = _reads(stages.get(key) or [])
        driving = _driving_scopes(reads, statement_rules)
        joins = [rule for rule in rules if rule["kind"] == "join" and _statement_key(rule) == key
                 and rule.get("join_type") in _PRESERVING_LEFT
                 and not _filters_its_right_side(rule, rules)]
        shape = shapes.get(key) or RightSides([], set())
        for rule in rules:
            if (rule["kind"] != "filter" or rule["partition_filter"]
                    or _statement_key(rule) != key or str(rule.get("scope")) in driving):
                continue
            right_of = [join["id"] for join in joins
                        if str(rule.get("scope")) in _closure(reads, join.get("right"))]
            if not right_of:
                continue
            rule["right_of"] = right_of
            kind = _right_side_kind(rule, shape)
            if kind:
                rule["right_side_kind"] = kind


def _driving_scopes(reads: dict[str, list[str]], profile_rules: list[dict]) -> set[str]:
    """Every scope the statement's root stages read without crossing a LEFT JOIN's right."""
    cut: dict[str, set[str]] = {}
    left: dict[str, set[str]] = {}
    for rule in profile_rules:
        if rule.get("kind") != "join_condition":
            continue
        scope = str(rule.get("scope_id"))
        left.setdefault(scope, set()).add(str(rule.get("left_input")))
        if str(rule.get("join_type")) in _PRESERVING_LEFT:
            cut.setdefault(scope, set()).add(str(rule.get("right_input")))
    read = {item for items in reads.values() for item in items}
    pending = [scope for scope in reads if scope not in read]
    found: set[str] = set()
    while pending:
        scope = pending.pop()
        if scope in found:
            continue
        found.add(scope)
        skipped = cut.get(scope, set()) - left.get(scope, set())
        pending.extend(item for item in reads.get(scope, []) if item in reads and item not in skipped)
    return found


def _filters_its_right_side(join: dict, rules: list[dict]) -> bool:
    """A filter of the JOIN's own scope reads its right side (an anti-join's IS NULL)."""
    aliases = {str(name).lower() for name in join.get("right_aliases") or []}
    return any(
        other["kind"] == "filter" and _statement_key(other) == _statement_key(join)
        and other.get("scope") == join.get("scope")
        and aliases & _qualifiers(other.get("expression"))
        for other in rules
    )


def _qualifiers(expression) -> set[str]:
    node = parse_expression(str(expression or ""))
    return {column.table.lower() for column in node.find_all(exp.Column)} if node else set()


def _right_side_kind(rule: dict, shape: RightSides) -> str | None:
    block = rule.get(LOGIC_BLOCK)
    if any(block == consumer and equals_one_predicate(rule.get("expression"), output)
           for consumer, output in shape.first_row_filters):
        return RANK_FIRST
    if str(rule.get("scope")) in shape.values_scopes:
        return VALUES
    return None


GRAIN_PATH = "grain"
RANK_WITHIN_GROUP = "rank_within_group"


def _stages(statements: list[tuple[str, dict]]) -> dict[tuple, list[dict]]:
    return {(task, statement.get("statement_id")): statement.get("stages") or []
            for task, statement in statements}


def _aggregate_above(stages: list[dict], scope) -> str | None:
    reads = _reads(stages)
    return next((stage["scope_id"] for stage in stages
                 if _aggregates(stage) and str(scope or "") in _closure(reads, stage["scope_id"])),
                None)


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
    numbered = {(_statement_key(rule), rule.get(PROFILE_RULE)): rule["id"] for rule in rules
                if rule.get(PROFILE_RULE)}
    # A finding about a stage action (A-M4: a window) names its logic block; a rule's own
    # number wins, the first rule of a block is the one named (README 裁决 2).
    for rule in rules:
        if rule.get(LOGIC_BLOCK):
            numbered.setdefault((_statement_key(rule), rule[LOGIC_BLOCK]), rule["id"])
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
    """The profile's ``output_shape.merge``, its JOINs after a dedup as packet rule ids.

    Those of the USING side and those of each UNION branch (``union_branches``) alike.
    """
    merge = (statement.get("output_shape") or {}).get("merge")
    if not merge:
        return None
    key = (task, statement.get("statement_id"))
    ids = {rule.get(LOGIC_BLOCK): rule["id"] for rule in rules
           if rule["kind"] == "join" and _statement_key(rule) == key}

    def numbered(item: dict) -> dict:
        joins = item.get("joins_after_dedup")
        return {**item, "joins_after_dedup": [ids.get(j, j) for j in joins]} if joins else dict(item)

    block = numbered(merge)
    if block.get("union_branches"):
        block["union_branches"] = [numbered(branch) for branch in block["union_branches"]]
    return block
