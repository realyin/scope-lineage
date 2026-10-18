"""Governance leads only a packet can see: an input table's whole column list against a task.

The profile's findings are per statement and know only the columns a statement read; a
packet also holds every input table's metadata. Two leads compare the two, per producing
task, and join the profile's in ``lineage.findings`` (``warn``, worded as structure, to be
checked by the writer):

- :func:`marker_leads` -- ``marker_column_unused`` (D-G2, round 3 G1): an input has a
  logical-delete, cancel or change-type column (the generic naming of one,
  :func:`_marker_kind`) that no condition and no output of the task reads;
- :func:`declared_key_leads` -- ``declared_key_not_used`` (D-G3): an input column's
  comment declares a composite unique key as a ``$`` template of the table's columns
  (``唯一键 ($env_$id)``), and the task deduplicates or merges that table by part of it
  only. A MERGE whose dedup the profile already reports wider than the merge key
  (``dedup_wider``) says the same thing and is left out. A template naming one column
  (``唯一键 ($id)``) is said when the dedup or merge key leaves it out (W8);
- :func:`partition_format_leads` -- ``partition_format_mismatch`` (W8): a partition
  literal in another date format than the one the column's comment documents;
- :func:`merge_key_leads` -- ``merge_same_key`` (W8, ``info``): two MERGEs into the
  table on one ON key set;
- :func:`state_leads` -- ``state_column_unfiltered`` (W7, ``info``): an input column
  that may hold a state, which the task never reads.

All name columns by their generic shape only; no business word decides anything.
"""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from ..render.ontology import KEY_HINT_PHRASES
from .names import bare_table
from .sql_forms import DIALECT

# The generic names of a column that marks rows a reader may have to leave out, by kind
# (D-G2, round 3 G1): a = a logical-delete flag (is_deleted, is_del, del_flag, deleted_mark
# …); b = a cancel / void flag (is_cancel, is_void, is_invalid …); c = a change-type
# column (record_type, op_type, change_type …), which counts only when its comment names
# at least two data-manipulation verbs, one of them a delete (CHANGE_TYPE_VERBS): a
# change-type name alone is as often a business "operation type".
DELETE_MARKER = re.compile(
    r"^(is_?)?(del|deleted|delete)(_?flag)?$|^(is_?)?deleted?_?(flag|mark|status)$", re.IGNORECASE)
CANCEL_MARKER = re.compile(r"^is_?(cancel|cancell?ed|void|voided|invalid)$", re.IGNORECASE)
CHANGE_TYPE_MARKER = re.compile(
    r"^(record_?type|op_?type|_?op|operation_?type|change_?type)$", re.IGNORECASE)
CHANGE_TYPE_VERBS = re.compile(
    r"\b(INSERT|UPSERT|UPDATE|DELETE)\b|(新增|插入|更新|修改|删除)", re.IGNORECASE)
_DELETE_VERBS = frozenset({"DELETE", "删除"})


def _marker_kind(column: dict) -> str | None:
    """``delete`` / ``cancel`` / ``change_type`` for a marker column, by its generic shape."""
    name = str(column.get("name"))
    if DELETE_MARKER.match(name):
        return "delete"
    if CANCEL_MARKER.match(name):
        return "cancel"
    if CHANGE_TYPE_MARKER.match(name):
        verbs = {(english or chinese).upper()
                 for english, chinese in CHANGE_TYPE_VERBS.findall(str(column.get("comment") or ""))}
        if len(verbs) >= 2 and verbs & _DELETE_VERBS:
            return "change_type"
    return None


# Per kind, in the order the lead says them: what the column is, what reaches the table.
_MARKER_SAID = {
    "delete": ("删除标记列", "已删除的记录会照常进入"),
    "cancel": ("作废标记列", "已作废的记录会照常进入"),
    "change_type": ("疑似变更类型列", "删除类记录会照常进入"),
}
_CHANGE_TYPE_NOTE = "（注释列出 INSERT / UPDATE / DELETE 类取值）"


def marker_leads(target: str, statements: list, rules: list[dict], inputs: list[dict]) -> list[dict]:
    """``marker_column_unused`` per producing task: the marker columns it never reads.

    One lead per task, a sentence per kind of marker (:func:`_marker_kind`).
    """
    leads = []
    for task, group in _by_task(statements).items():
        cited = {ref.lower() for rule in rules if rule["task"] == task for ref in rule.get("columns") or []}
        hits: dict[str, list[str]] = {}
        first = None
        for table, used, statement_id in _reads(group, target):
            entry = _input(inputs, table)
            for column in entry.get("columns") or []:
                name = str(column["name"])
                kind = _marker_kind(column)
                if (kind and name.lower() not in used
                        and f"{table}.{name}".lower() not in cited):
                    hits.setdefault(kind, []).append(f"`{table}.{name}`")
                    first = first or statement_id
        if hits:
            leads.append(_lead("marker_column_unused", task, first, _marker_text(hits)))
    return leads


def _marker_text(hits: dict[str, list[str]]) -> str:
    said = []
    for kind, (what, then) in _MARKER_SAID.items():
        if kind not in hits:
            continue
        columns = "、".join(dict.fromkeys(hits[kind])) + (_CHANGE_TYPE_NOTE if kind == "change_type" else "")
        unread = "本任务没有任何条件或输出引用它" if not said else "同样没有被引用"
        said.append(f"源表有{what} {columns}，{unread}：{then}")
    return "；".join(said) + "，需核实是否应过滤"


# W7: a column that may hold a record's state, by its name (status / state / effective /
# valid) or its comment (状态 / 是否有效). A date or time column (``status_time``,
# 「状态更新时间」) records when, not which state, and is left out; so are the markers
# above, which have a lead of their own.
_STATE_NAME = re.compile(r"status|effective|state$|(^|_)state(_|$)|valid$|(^|_)valid(_|$)",
                         re.IGNORECASE)
_STATE_COMMENT = re.compile(r"状态|是否有效")
_WHEN_NAME = re.compile(r"date|time|(^|_)(dt|ts|tm)$", re.IGNORECASE)
_WHEN_COMMENT = re.compile(r"时间|日期")
def _is_state(column: dict) -> bool:
    name, comment = str(column.get("name")), str(column.get("comment") or "")
    if _marker_kind(column) or column.get("partition") or _WHEN_NAME.search(name):
        return False
    return bool(_STATE_NAME.search(name)
                or (_STATE_COMMENT.search(comment) and not _WHEN_COMMENT.search(comment)))


def state_leads(target: str, statements: list, rules: list[dict], inputs: list[dict]) -> list[dict]:
    """``state_column_unfiltered`` (W7, ``info``) per task: state columns the task never reads.

    Weaker than :func:`marker_leads`: a state column may well be meant to let every state
    through, so the lead only asks. A column the task filters, joins, groups or writes out
    is read -- an output state column still tells the reader each row's state -- and is
    left out, as a marker column is.
    """
    leads = []
    for task, group in _by_task(statements).items():
        cited = {ref.lower() for rule in rules if rule["task"] == task for ref in rule.get("columns") or []}
        found, first = [], None
        for table, used, statement_id in _reads(group, target):
            for column in _input(inputs, table).get("columns") or []:
                name = str(column["name"])
                if (_is_state(column) and name.lower() not in used
                        and f"{table}.{name}".lower() not in cited):
                    found.append(f"`{table}.{name}`")
                    first = first or statement_id
        if found:
            lead = _lead("state_column_unfiltered", task, first, (
                f"源表有疑似状态列 {'、'.join(found)}（按列名或注释判断），本任务没有任何条件或输出"
                "引用它们：每种状态的记录都会进入，且目标表看不出状态，需核实是否应按状态取行"))
            leads.append({**lead, "severity": "info"})
    return leads


# W8: the date format a partition column's comment documents -- a pattern
# (``YYYY-MM-DD``, ``yyyymmdd``) or an example date -- against the literal a partition
# condition fixes it to.
_DASHED_FORMAT = re.compile(r"y{4}-m{2}-d{2}|(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)", re.IGNORECASE)
_COMPACT_FORMAT = re.compile(r"y{4}m{2}d{2}|(?<!\d)(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)",
                             re.IGNORECASE)
_DASHED_LITERAL = re.compile(r"^'\d{4}-\d{2}-\d{2}'$")
_COMPACT_LITERAL = re.compile(r"^'\d{8}'$")


def _documented_format(comment) -> tuple[str, str] | None:
    """``(dashed | compact, the comment's own spelling)`` when the comment documents one only."""
    text = str(comment or "")
    dashed, compact = _DASHED_FORMAT.search(text), _COMPACT_FORMAT.search(text)
    if bool(dashed) == bool(compact):
        return None
    return ("dashed", dashed.group(0)) if dashed else ("compact", compact.group(0))


def partition_format_leads(rules: list[dict], inputs: list[dict]) -> list[dict]:
    """``partition_format_mismatch`` (W8) per (task, table, column): literal and comment disagree.

    ``dt = '20250115'`` on a column whose comment says ``YYYY-mm-dd``: either the comment
    is stale or the condition reads no partition at all. Only a whole date literal is
    compared, and only with a comment documenting a single format.
    """
    found: dict[tuple, dict] = {}
    for rule in rules:
        reads = [(table, rule["expression"]) for table in rule.get("tables") or []
                 if rule.get("partition_filter")]
        reads += [(read.get("table"), read.get("expression")) for read in rule.get("partition_reads") or []]
        for table, expression in reads:
            for name, literal in _partition_literals(expression):
                column = next((c for c in _input(inputs, table).get("columns") or []
                               if str(c["name"]).lower() == name and c.get("partition")), None)
                documented = _documented_format((column or {}).get("comment"))
                shape = ("dashed" if _DASHED_LITERAL.match(literal)
                         else "compact" if _COMPACT_LITERAL.match(literal) else None)
                if not documented or not shape or shape == documented[0]:
                    continue
                entry = found.setdefault((rule["task"], table, str(column["name"])), {
                    "statement_id": rule["statement_id"], "said": documented[1],
                    "literals": [], "rules": []})
                entry["literals"].append(literal)
                entry["rules"].append(rule["id"])
    leads = []
    for (task, table, name), entry in found.items():
        literals = "、".join(dict.fromkeys(entry["literals"]))
        lead = _lead("partition_format_mismatch", task, entry["statement_id"], (
            f"{table}.{name} 的分区条件写 {literals}，列注释写的格式是 {entry['said']}：注释过时，"
            "或这条条件读不到任何分区，需核实"))
        lead["rules"] = list(dict.fromkeys(entry["rules"]))
        leads.append(lead)
    return leads


def _partition_literals(expression) -> list[tuple[str, str]]:
    """``(column, 'literal')`` of each column an equality or IN list fixes to a string."""
    try:
        node = sqlglot.parse_one(str(expression or ""), read=DIALECT)
    except (SqlglotError, ValueError, RecursionError):
        return []
    found = []
    for comparison in node.find_all(exp.EQ, exp.In) if node else []:
        pairs = ([(comparison.this, item) for item in comparison.expressions]
                 if isinstance(comparison, exp.In)
                 else [(comparison.this, comparison.expression), (comparison.expression, comparison.this)])
        found += [(column.name.lower(), f"'{literal.this}'") for column, literal in pairs
                  if isinstance(column, exp.Column) and isinstance(literal, exp.Literal)
                  and literal.is_string]
    return found


def merge_key_leads(lineage: dict) -> list[dict]:
    """``merge_same_key`` (W8, ``info``): two or more MERGEs into the table on one ON key set.

    A later MERGE meets the rows an earlier one inserted or updated: it may update them
    again, and move them when it writes a partition column. Which order the statements
    run in is not decided here.
    """
    groups: dict[frozenset, list[dict]] = {}
    for key in lineage.get("keys") or []:
        pairs = (key.get("merge") or {}).get("merge_keys") or []
        if pairs:
            groups.setdefault(frozenset(str(p.get("target")).lower() for p in pairs), []).append(key)
    leads = []
    for columns, keys in groups.items():
        if len(keys) < 2:
            continue
        where = "、".join(f"{key['task']} / {key['statement_id']}" for key in keys)
        lead = _lead("merge_same_key", keys[-1]["task"], keys[-1]["statement_id"], (
            f"{where} 都按 ({'、'.join(sorted(columns))}) MERGE 进本表：后执行的一条会遇到前一条插入或"
            "更新的行，可能再次更新它们（写分区列时还会换分区），需核实语句之间的先后影响"))
        leads.append({**lead, "severity": "info"})
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
                single = _declared_single(column.get("comment"), names, str(column["name"]))
                if single:
                    leads += _single_key_leads(task, table, single, str(column["name"]),
                                               _key_uses(task, table, names, rules, lineage))
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


def _single_key_leads(task: str, table: str, member: str, own: str, uses: list[tuple]) -> list[dict]:
    """W8: a one-column declared key (``唯一键 ($id)``) the task's dedup or merge leaves out."""
    missed = [use for use in uses if member not in use[0] and own.lower() not in use[0]]
    if not missed:
        return []
    said = "、".join(f"按 ({'、'.join(sorted(used))}) {how}" for used, how, _rule, _sid in missed)
    lead = _lead("declared_key_not_used", task, missed[0][3], (
        f"{table} 的列注释声明 ({member}) 唯一（作者说法），本任务在该表上{said}，不含 {member}："
        f"去重或合并的键不是声明的唯一键，同一键可能对应多条源记录，或把不同记录并成一条，需核实"))
    ids = [rule for _used, _how, rule, _sid in missed if rule]
    if ids:
        lead["rules"] = ids
    return [lead]


def _declared_single(comment, names: list[str], own: str) -> str | None:
    """W8: the one column a key comment's ``$`` template names (``$id``), not the commented one.

    A template naming two or more columns is :func:`_declared_members`'s.
    """
    text = str(comment or "")
    if not any(phrase in text.lower() for phrase in KEY_HINT_PHRASES):
        return None
    template = _TEMPLATE.search(text)
    spelled = template.group(0).replace("$", "").strip("_").lower() if template else ""
    known = {name.lower() for name in names}
    return spelled if spelled in known and spelled != own.lower() else None


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
