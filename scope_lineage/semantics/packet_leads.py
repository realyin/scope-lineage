"""Governance leads only a packet can see: an input table's whole column list against a task.

The profile's findings are per statement and know only the columns a statement read; a
packet also holds every input table's metadata. Two leads compare the two, per producing
task, and join the profile's in ``lineage.findings`` (``warn``, worded as structure, to be
checked by the writer):

- :func:`marker_leads` -- ``marker_column_unused`` (D-G2): an input has a logical-delete
  column (the generic naming of one, :data:`DELETE_MARKER`) that no condition and no
  output of the task reads;
- :func:`declared_key_leads` -- ``declared_key_not_used`` (D-G3): an input column's
  comment declares a composite unique key as a ``$`` template of the table's columns
  (``唯一键 ($env_$id)``), and the task deduplicates or merges that table by part of it
  only. A MERGE whose dedup the profile already reports wider than the merge key
  (``dedup_wider``) says the same thing and is left out.

Both name columns by their generic shape only; no business word decides anything.
"""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from ..render.ontology import KEY_HINT_PHRASES
from .names import bare_table
from .sql_forms import DIALECT

# Pattern a of D-G2: the common names of a logical-delete flag (is_deleted, is_del,
# del_flag, delete_flag, deleted, deleted_mark …). Cancel and change-type names are not
# leads in this round.
DELETE_MARKER = re.compile(
    r"^(is_?)?(del|deleted|delete)(_?flag)?$|^(is_?)?deleted?_?(flag|mark|status)$", re.IGNORECASE)


def marker_leads(target: str, statements: list, rules: list[dict], inputs: list[dict]) -> list[dict]:
    """``marker_column_unused`` per producing task: the delete markers it never reads."""
    leads = []
    for task, group in _by_task(statements).items():
        cited = {ref.lower() for rule in rules if rule["task"] == task for ref in rule.get("columns") or []}
        hits, first = [], None
        for table, used, statement_id in _reads(group, target):
            entry = _input(inputs, table)
            for column in entry.get("columns") or []:
                name = str(column["name"])
                if (DELETE_MARKER.match(name) and name.lower() not in used
                        and f"{table}.{name}".lower() not in cited):
                    hits.append(f"`{table}.{name}`")
                    first = first or statement_id
        if hits:
            leads.append(_lead("marker_column_unused", task, first, (
                f"源表有删除标记列 {'、'.join(dict.fromkeys(hits))}，本任务没有任何条件或输出引用它："
                "已删除的记录会照常进入，需核实是否应过滤")))
    return leads


def declared_key_leads(
    target: str, statements: list, rules: list[dict], inputs: list[dict], lineage: dict,
) -> list[dict]:
    """``declared_key_not_used`` per (task, input, declared key): the key used falls short."""
    leads = []
    for task, group in _by_task(statements).items():
        for table, _used, _statement_id in _reads(group, target):
            names = [str(column["name"]) for column in _input(inputs, table).get("columns") or []]
            for column in _input(inputs, table).get("columns") or []:
                members = _declared_members(column.get("comment"), names)
                if not members:
                    continue
                uses = [
                    use for use in _key_uses(task, table, names, rules, lineage)
                    if use[0] & members and not members <= use[0]
                    and str(column["name"]).lower() not in use[0]
                ]
                if uses:
                    leads.append(_declared_lead(task, table, members, uses))
    return leads


def _declared_lead(task: str, table: str, members: set, uses: list[tuple]) -> dict:
    said = "、".join(f"按 ({'、'.join(sorted(used))}) {how}" for used, how, _rule, _sid in uses)
    used = sorted(set().union(*(use[0] for use in uses)))
    missing = sorted(members - set(used))
    lead = _lead("declared_key_not_used", task, uses[0][3], (
        f"{table} 的列注释声明 ({'、'.join(sorted(members))}) 唯一（作者说法），本任务在该表上{said}，"
        f"少了 {'、'.join(missing)}：同一 {'、'.join(used)} 可能对应多条源记录，需核实"))
    ids = [rule for _used, _how, rule, _sid in uses if rule]
    if ids:
        lead["rules"] = ids
    return lead


def _key_uses(task: str, table: str, names: list[str], rules: list[dict], lineage: dict) -> list[tuple]:
    """``(columns, how, rule id or None, statement)`` the task deduplicates or merges ``table`` by."""
    uses = []
    bare = table.rsplit(".", 1)[-1].lower()
    known = {name.lower() for name in names}
    # The profile already says a MERGE's dedup is wider than its merge key; neither the
    # merge nor that statement's dedups is said again.
    wider = {(key["task"], key["statement_id"]) for key in lineage.get("keys") or []
             if (key.get("merge") or {}).get("coverage") == "dedup_wider"}
    for rule in rules:
        if (rule["task"] != task or rule["kind"] != "dedup" or table not in rule.get("tables") or []
                or (task, rule["statement_id"]) in wider):
            continue
        # Only a window over the table itself names its columns: the profile qualifies
        # them by the table's name. Over a subquery a column may be derived.
        columns = {name for qualifier, name in _partition_columns(rule.get("expression"))
                   if name in known and qualifier == bare}
        if columns:
            uses.append((columns, f"去重（{rule['id']}）", rule["id"], rule["statement_id"]))
    for key in lineage.get("keys") or []:
        merge = key.get("merge") or {}
        if key["task"] != task or not merge or (task, key["statement_id"]) in wider:
            continue
        columns = _merge_key_sources(key, merge, table, lineage)
        if columns:
            uses.append((columns, f"合并（{key['statement_id']}）", None, key["statement_id"]))
    return uses


def _merge_key_sources(key: dict, merge: dict, table: str, lineage: dict) -> set[str]:
    """The ``table`` columns the MERGE's ON keys are written from, by the column lineage."""
    targets = {str(pair.get("target")) for pair in merge.get("merge_keys") or []}
    prefix = f"{table}.".lower()
    return {
        source.lower()[len(prefix):]
        for column in lineage.get("columns") or [] if column["column"] in targets
        for producer in column["producers"]
        if producer["task"] == key["task"] and producer["statement_id"] == key["statement_id"]
        for source in producer.get("sources") or [] if source.lower().startswith(prefix)
    }


def _partition_columns(expression) -> list[tuple[str, str]]:
    """``(qualifier, column)`` of each column a window's PARTITION BY reads.

    A column read inside an expression counts too: ``concat('p_', env)`` tells the
    ``env`` values apart as surely as ``env`` does.
    """
    try:
        node = sqlglot.parse_one(str(expression or ""), read=DIALECT)
    except (SqlglotError, ValueError, RecursionError):
        return []
    window = next(node.find_all(exp.Window), None) if node else None
    return [(column.table.lower(), column.name.lower())
            for item in (window.args.get("partition_by") or [] if window else [])
            for column in item.find_all(exp.Column)]


_TEMPLATE = re.compile(r"\$[A-Za-z0-9_$]+")


def _declared_members(comment, names: list[str]) -> set[str]:
    """The columns a key comment's ``$`` template names, two or more, else nothing.

    The comment must say it is a key (:data:`~..render.ontology.KEY_HINT_PHRASES`) and its
    template must split, greedily, into the table's own column names: ``$env_$ev_id``
    over ``env`` and ``ev_id``. A comment naming another table's key has no template.
    """
    text = str(comment or "")
    if not any(phrase in text.lower() for phrase in KEY_HINT_PHRASES):
        return set()
    template = _TEMPLATE.search(text)
    if not template:
        return set()
    known = {name.lower() for name in names}
    parts = [part.strip("_").lower() for part in template.group(0).split("$") if part.strip("_")]
    if len(parts) >= 2 and all(part in known for part in parts):
        return set(parts) if len(set(parts)) >= 2 else set()
    # `$a_b` with one `$` for two columns: split greedily over the column names, never
    # into the one column the whole template spells.
    spelled = template.group(0).replace("$", "").lower()
    candidates = sorted(known - {spelled}, key=len, reverse=True)
    found, index = [], 0
    while index < len(spelled):
        if spelled[index] == "_":
            index += 1
            continue
        name = next((n for n in candidates if spelled.startswith(n, index)
                     and (index + len(n) == len(spelled) or spelled[index + len(n)] == "_")), None)
        if name is None:
            return set()
        found.append(name)
        index += len(name)
    return set(found) if len(set(found)) >= 2 else set()


def _by_task(statements: list) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for task, statement in statements:
        grouped.setdefault(task, []).append(statement)
    return grouped


def _reads(group: list[dict], target: str) -> list[tuple[str, set[str], str]]:
    """``(input table, the columns the task reads by some usage, first statement reading it)``."""
    found: dict[str, tuple[set[str], str]] = {}
    for statement in group:
        for item in statement.get("inputs") or []:
            table = bare_table(item.get("table"))
            if table == target:
                continue
            used, first = found.setdefault(table, (set(), statement.get("statement_id")))
            used.update(str(column.get("name")).lower() for column in item.get("used_columns") or []
                        if column.get("usages"))
    return [(table, used, first) for table, (used, first) in found.items()]


def _input(inputs: list[dict], table: str) -> dict:
    return next((entry for entry in inputs if entry["table"] == table), {})


def _lead(kind: str, task: str, statement_id, text: str) -> dict:
    return {"kind": kind, "severity": "warn", "task": task, "statement_id": statement_id,
            "text": text}
