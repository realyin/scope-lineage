"""What one statement of the semantic profile contributes to a packet.

The semantic profile (``describe``'s builder) is the source of every lineage fact here:
a field's physical sources and derivation steps, the statement's rules, its grain and
keys, its inputs and how each is read. This module only re-shapes those facts per target
column and per input table; it derives nothing the profile has not already settled,
except the two time readings check 9 needs (how each input's partitions are read, and
which filters touch a business date).
"""

from __future__ import annotations

import re

from .names import bare_column, bare_table, normalize_sql
from .packet_meaning import case_outputs, code_expression, join_facts

_RULE_KINDS = {"filter": "filter", "having": "filter", "join_condition": "join",
               "case_branch": "case"}
# Stage actions that say how rows are merged or de-duplicated; the profile's rules only
# hold predicates, joins and CASE branches.
_STAGE_RULE_ACTIONS = {"window": "dedup", "distinct": "dedup", "union": "union"}

# Warehouse naming conventions for what one partition of a table holds. A convention,
# not a fact: published as `name_convention` so a reader sees what the check assumed.
_FULL_SUFFIX = re.compile(r"_(df|da|full|snapshot)$")
_INCREMENTAL_SUFFIX = re.compile(r"_(di|hi|inc|incr|delta)$")
_DATE_NAME = re.compile(r"(^|_)(date|dt|day|time|ts|month)$")
_DATE_TYPE = re.compile(r"^(date|timestamp|datetime)")
_DATE_COMMENT = re.compile(r"(date|time|日期|时间)", re.IGNORECASE)


def column_producer(task: str, statement: dict, field: dict) -> dict:
    """How one statement writes one target column."""
    sources = []
    for source in field.get("sources") or []:
        reference = bare_column(f"{source.get('table')}.{source.get('column')}")
        if reference not in sources:
            sources.append(reference)
    return {
        "task": task,
        "statement_id": statement.get("statement_id"),
        "transform": field.get("transform"),
        "role": field.get("structural_role"),
        "expression": field.get("expression"),
        "sources": sources,
        "steps": [str(step.get("text")) for step in field.get("derivation") or []],
        "case_outputs": case_outputs(code_expression(field)),
    }


def statement_rules(task: str, statement: dict) -> list[dict]:
    """The statement's filters, joins and CASE branches, then its dedup and union steps."""
    rules = [_profile_rule(task, statement, rule) for rule in statement.get("rules") or []]
    for stage in statement.get("stages") or []:
        for action in stage.get("actions") or []:
            kind = _STAGE_RULE_ACTIONS.get(str(action.get("type")))
            if kind == "dedup" and action.get("type") == "window" and stage.get("role") != "dedup":
                continue
            if kind:
                rules.append(_stage_rule(task, statement, stage, action, kind))
    return rules


def _profile_rule(task: str, statement: dict, rule: dict) -> dict:
    entry = {
        "kind": _RULE_KINDS.get(str(rule.get("kind")), str(rule.get("kind"))),
        "task": task,
        "statement_id": statement.get("statement_id"),
        "scope": rule.get("scope_id"),
        "expression": rule.get("expression"),
        "partition_filter": bool(rule.get("is_partition_filter")),
        "partition_basis": "lineage",
        "tables": _tables_of(rule.get("fields")),
        "columns": _columns_of(rule.get("fields")),
    }
    if rule.get("join_type"):
        entry["join_type"] = rule["join_type"]
    if entry["kind"] == "join":
        entry.update(join_facts(statement, rule))
    return entry


def _stage_rule(task: str, statement: dict, stage: dict, action: dict, kind: str) -> dict:
    return {
        "kind": kind,
        "task": task,
        "statement_id": statement.get("statement_id"),
        "scope": stage.get("scope_id"),
        "expression": action.get("expression"),
        "partition_filter": False,
        "partition_basis": "lineage",
        "tables": _tables_of(action.get("fields")) or sorted(
            bare_table(table) for table in stage.get("upstream_physical_tables") or []
        ),
        "text": action.get("text"),
    }


def _tables_of(fields) -> list[str]:
    return sorted({bare_table(item.get("table")) for item in fields or [] if item.get("table")})


def _columns_of(fields) -> list[str]:
    columns = []
    for item in fields or []:
        reference = bare_column(f"{item.get('table')}.{item.get('column')}")
        if item.get("table") and reference not in columns:
            columns.append(reference)
    return columns


def statement_keys(task: str, statement: dict) -> dict:
    """The statement's grain and keys, and whether the profile proves them."""
    shape = statement.get("output_shape") or {}
    grain = shape.get("grain") or {}
    confidence = shape.get("key_confidence")
    return {
        "task": task,
        "statement_id": statement.get("statement_id"),
        "shape": shape.get("shape"),
        "grain_basis": grain.get("basis"),
        "grain_keys": [str(key.get("name")) for key in grain.get("keys") or []],
        "candidate_keys": list(shape.get("candidate_keys") or []),
        "key_confidence": confidence,
        "proven": confidence == "proven",
    }


def statement_partition(task: str, statement: dict) -> dict:
    partition = (statement.get("task") or {}).get("partition") or {}
    return {
        "task": task,
        "statement_id": statement.get("statement_id"),
        "columns": list(partition.get("columns") or []),
        "mode": partition.get("mode"),
        "spec": partition.get("spec") or {},
    }


# ------------------------------------------------------------------ partition filters

# Names a warehouse gives its date partition column; read only for a table the metadata
# marks partitioned without saying which column is the partition.
_PARTITION_NAMES = frozenset({"dt", "ds", "pt", "p_date"})
_CONSTANT = r"('[^']*'|\d+|\$\{[a-z0-9_.\-]+\})"
_COMPARISON = re.compile(rf"^[a-z0-9_]+(=|<=|>=|<|>){_CONSTANT}$")
_BETWEEN = re.compile(rf"^[a-z0-9_]+between{_CONSTANT}and{_CONSTANT}$")


def mark_partition_filters(rules: list[dict], metadata) -> None:
    """Decide per filter conjunct whether it selects partitions, metadata first.

    The lineage's flag is a name rule over a whole WHERE clause, so ``dt = x AND
    status = 0`` marks neither conjunct. Here each conjunct is judged alone: a filter
    whose columns are all partition columns the metadata states (``isPartition``,
    ``PARTITIONED BY``) is a partition filter; failing that, a comparison with a constant
    on a ``dt``/``ds``/``pt``/``p_date`` column of a table the metadata marks partitioned
    is one; with neither, the lineage's flag stands. ``partition_basis`` says which.
    """
    for rule in rules:
        if rule["kind"] != "filter" or not rule.get("columns"):
            continue
        decided = [_partition_column(ref, rule["expression"], metadata) for ref in rule["columns"]]
        if any(verdict is None for verdict, _ in decided):
            continue
        rule["partition_filter"] = all(verdict for verdict, _ in decided)
        bases = {basis for _, basis in decided}
        rule["partition_basis"] = "metadata" if bases == {"metadata"} else "partition_name"


def _partition_column(reference: str, expression, metadata) -> tuple:
    """``(is a partition column, basis)``; ``(None, "lineage")`` when nothing says."""
    table, column = reference.rsplit(".", 1)
    meta = metadata(table) or {}
    if meta.get("partition_columns"):
        return column in meta["partition_columns"], "metadata"
    text = normalize_sql(expression)
    if (meta.get("partitioned") and column in _PARTITION_NAMES
            and (_COMPARISON.match(text) or _BETWEEN.match(text))):
        return True, "partition_name"
    return None, "lineage"


# ------------------------------------------------------------------ input time facts


def input_time_facts(table: str, rules: list[dict], columns: list[dict]) -> dict:
    """How one input's partitions are read, and its non-partition business-date filters."""
    partition = [r["expression"] for r in rules if r["partition_filter"] and table in r["tables"]]
    by_name = {column["name"]: column for column in columns}
    dated = [
        {"column": name, "expression": rule["expression"]}
        for rule in rules
        if rule["kind"] == "filter" and not rule["partition_filter"] and table in rule["tables"]
        for name in _filter_columns(rule, table)
        if _is_date_column(by_name.get(name) or {"name": name})
    ]
    read = _partition_read(partition)
    convention = _name_convention(table)
    return {
        "partition_read": read,
        "partition_filters": partition,
        "date_filters": dated,
        "name_convention": convention,
        "full_snapshot": read == "equality" and convention == "full",
    }


def _filter_columns(rule: dict, table: str) -> list[str]:
    prefix = f"{table}."
    return [ref[len(prefix):] for ref in rule.get("columns") or [] if ref.startswith(prefix)]


def _partition_read(expressions: list[str]) -> str:
    if not expressions:
        return "none"
    return "equality" if all(_is_equality(text) for text in expressions) else "range"


def _is_equality(expression: str) -> bool:
    text = normalize_sql(expression)
    return text.count("=") == 1 and not any(op in text for op in ("<", ">", "in(", "between"))


def _name_convention(table: str) -> str:
    name = table.rsplit(".", 1)[-1]
    if _FULL_SUFFIX.search(name):
        return "full"
    if _INCREMENTAL_SUFFIX.search(name):
        return "incremental"
    return "unknown"


def _is_date_column(column: dict) -> bool:
    return bool(
        _DATE_TYPE.match(str(column.get("type") or "").lower())
        or _DATE_NAME.search(str(column.get("name") or "").lower())
        or _DATE_COMMENT.search(str(column.get("comment") or ""))
    )
