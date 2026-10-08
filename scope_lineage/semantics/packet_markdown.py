"""``packet.md``: the packet as a model (or a person) reads it.

Same facts as ``packet.json``, in the order a writer needs them: the table, the tasks
and their SQL, the inputs, the lineage facts, and last the column order the document
must follow. No fact here is missing from the JSON (one fixed sentence explains how
SQLGlot writes a default time format), and only one thing is left to it: a 4.1 step
chain longer than :data:`STEPS_CELL_LIMIT` shows its computing steps, or failing that
its last step, and its length. The validator reads the JSON, and ``packet_digest`` is
computed over the JSON alone, so a layout change here never makes a written document
stale.

What the owner already confirmed is shown where it applies and only when there is some:
a patched comment carries 「（已确认，元数据补丁）」, and a column table gains an
「已确认码值」 column when one of its columns has confirmed values -- so a packet built
without either renders exactly as it did before.
"""

from __future__ import annotations

import re

from sqlglot import exp

from ..render.markdown_text import cell, expr_span
from ..render.semantic_text import PASS_THROUGH_TEXT_PREFIXES, parse_expression
from .packet_context import string_literals
from .packet_facts import partition_filter_rules, partition_values
from .sql_forms import DIALECT


def render_packet_markdown(packet: dict) -> str:
    lines = [
        f"# 材料包：{packet['table']}",
        "",
        f"- 格式：`{packet['doc_format']}`",
        f"- packet_digest：`{packet['packet_digest']}`（原样写进 table-semantics/1 的 "
        "`packet_digest`；材料变了它就变，校验据此判断文档是否过期）",
        *_confirmed_note(packet),
        *_marker_note(packet),
        "",
    ]
    lines += _target(packet["target"])
    lines += _tasks(packet["tasks"], packet["table"])
    lines += _inputs(packet["inputs"], packet["lineage"]["rules"])
    lines += _lineage(packet["lineage"], packet["tasks"])
    lines += _column_order(packet["target"])
    return "\n".join(lines).rstrip("\n") + "\n"


def _code(value) -> str:
    return expr_span(value) if value not in (None, "") else "—"


def _text(value) -> str:
    return cell(value) if value not in (None, "", []) else "—"


def _names(values) -> str:
    return "、".join(_code(value) for value in values) if values else "—"


PATCHED = "（已确认，元数据补丁）"


def _confirmed_note(packet: dict) -> list[str]:
    """One line saying how to use the confirmed facts, in a packet that has any."""
    items = [packet["target"], *packet["inputs"]]
    entries = items + [column for item in items for column in item["columns"]]
    if not any("comment_source" in entry or "confirmed_values" in entry for entry in entries):
        return []
    return [
        "- 已确认事实：标「已确认，元数据补丁」的注释与「已确认码值」一列都是负责人确认过的，照写，"
        "`sources` 写 `confirmed`；这些码值不标 `unconfirmed`，也不再提问"
    ]


def _marker_note(packet: dict) -> list[str]:
    """The comment markers of the packet's columns, counted, with what not to do with them."""
    keys = packet.get("comment_marker_keys") or {}
    if not keys:
        return []
    counted = "、".join(f"{key}×{entry['count']}" for key, entry in keys.items())
    return [
        f"- 注释标记（工具不解释含义）：{counted}；含义未登记前，文档不得把标记当业务事实，"
        "需要时写进待确认问题"
    ]


_REF_STATUS = {
    "in_run": "本运行有任务读写这张表",
    "metadata_only": "只有元数据，本运行没有任务读写",
    "unknown": "本运行无此表",
}


def _comment(entry: dict) -> str:
    """A table's or a column's comment, marked when the metadata patch gave it.

    A column's ``[db.table.col]`` references follow, each with what the run knows of it.
    """
    text = _text(entry["comment"])
    text = text + PATCHED if entry.get("comment_source") == "patch" else text
    refs = [
        f"引用 {_code(ref['ref'])}：{_REF_STATUS.get(ref['status'], ref['status'])}"
        + (f"；名字相近：{_names(ref['near'])}（未证实同一张表）" if ref.get("near") else "")
        for ref in entry.get("comment_refs") or []
    ]
    return text + "".join(f"（{cell(item)}）" for item in refs)


def _confirmed_values(column: dict) -> str:
    values = column.get("confirmed_values") or []
    return _text("；".join(f"{item['value']}={item['meaning']}" for item in values))


def _column_table(header: list[str], rows: list[list[str]], columns: list[dict]) -> list[str]:
    """A markdown table of columns, with 已确认码值 last when any column has one."""
    if any(column.get("confirmed_values") for column in columns):
        header = [*header, "已确认码值"]
        rows = [[*row, _confirmed_values(column)] for row, column in zip(rows, columns)]
    return [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
        *("| " + " | ".join(row) + " |" for row in rows),
    ]


def _target(target: dict) -> list[str]:
    lines = [
        "## 1. 目标表",
        "",
        f"- 表：{_code(target['table'])}；表注释：{_comment(target)}",
        f"- 说明：{_text(target['description'])}；层：{_text(target['layer'])}；"
        f"域：{_text(target['domain'])}；元数据来源：{target['metadata_source']}",
        "",
    ]
    rows = [
        [str(index), _code(column["name"]), _text(column["type"]), _comment(column),
         "是" if column["partition"] else ""]
        for index, column in enumerate(target["columns"], start=1)
    ]
    lines += _column_table(["#", "列", "类型", "注释", "分区列"], rows, target["columns"])
    return [*lines, ""]


def _tasks(tasks: list[dict], table: str = "") -> list[str]:
    lines = ["## 2. 生产任务", ""]
    for index, task in enumerate(tasks, start=1):
        lines += [
            f"### 2.{index} {_code(task['name'])}",
            "",
            f"- 任务编号：{_text(task['task_id'])}；调度：{_text(task['schedule'])}；"
            f"周期：{_text(task['schedule_cycle'])}；项目：{_text(task['project'])}",
            f"- 任务描述：{_text(task['description'])}",
            f"- 登记的上游任务：{_names(task['upstream_tasks'])}{_unmatched(task)}；"
            f"登记的下游任务：{_names(task['downstream_tasks'])}",
            *_run_dates(task),
            f"- 写入语句：{_names(task['statements'])}；来源文件：{_text(task['source_file'])}",
            *_header_facts(task.get("header_facts") or {}),
            *_added_columns(task.get("header_facts") or {}, table),
            "",
        ]
        lines += [f"> {comment}" for comment in task["header_comments"]]
        lines += [""] if task["header_comments"] else []
        lines += _sql(task["sql"])
    return lines


def _unmatched(task: dict) -> str:
    names = task.get("upstream_unmatched") or []
    return f"（其中 {_names(names)} 按任务名对不上本任务 SQL 读取的任何表）" if names else ""


def _run_dates(task: dict) -> list[str]:
    """The expected run date and how far each date literal sits from it; no conclusion."""
    if not task.get("expect_date"):
        return []
    parts = [f"- 期望日期：{_text(task['expect_date'])}"]
    if "${" not in str(task.get("sql") or ""):
        parts.append("SQL 里没有 `${…}` 参数")
    literals = task.get("date_literals") or []
    if literals:
        parts.append("日期字面量：" + "、".join(
            f"{_code(item['literal'])} ×{item['count']}（{_offset(item['days_from_expect_date'])}）"
            for item in literals))
    return ["；".join(parts)]


def _offset(days: int) -> str:
    if days == 0:
        return "期望日期当天"
    if abs(days) > 31:
        return "不在期望日期前后一个月内"
    return f"期望日期 {'−' if days < 0 else '+'}{abs(days)} 天"


_HEADER_LABELS = (
    ("primary_key", "主键"), ("storage", "存储设计"), ("partition_design", "分区设计"),
    ("lifecycle", "生命周期"), ("volume", "数据规模"),
)


def _stated(facts: dict) -> str:
    return "；".join(f"{label} {facts[key]}" for key, label in _HEADER_LABELS if facts.get(key))


def _header_facts(facts: dict) -> list[str]:
    stated = _stated(facts)
    if facts.get("about"):
        return [f"- 头注释（描述的是同任务写的 {_code(facts['about'])}，不是本表）：{stated or '—'}"]
    return [f"- 头注释：{stated}"] if stated else []


def _added_columns(facts: dict, table: str) -> list[str]:
    """D-G4: the header's ``alter table … add columns`` records, the table named if another."""
    said = [
        f"{item.get('date') or '日期不明'} 加 {_names(item['columns'])}"
        + (f"（alter 写的是 {_code(item['table'])}）" if item["table"] != table else "")
        for item in facts.get("added_columns") or []
    ]
    return [f"- 头注释加列记录：{'；'.join(said)}"] if said else []


def _added_dates(tasks: list[dict]) -> dict[tuple, str]:
    """``(task, column) -> date`` of every column a task's header says was added later."""
    return {
        (task["name"], column): item.get("date") or "日期不明"
        for task in tasks
        for item in (task.get("header_facts") or {}).get("added_columns") or []
        for column in item["columns"]
    }


def _producer_header(entry: dict) -> list[str]:
    headers = entry.get("producer_header") or []
    if not headers:
        return []
    said = " / ".join(f"{_code(header['task'])}：{_stated(header)}" for header in headers)
    return [f"- 生产任务头注释（作者说法，非 SQL 事实）：{said}"]


def _sql(sql) -> list[str]:
    if not sql:
        return ["（`--tasks` 里没有这个任务的 JSON：SQL 缺失，规则原文无法核对）", ""]
    fence = "````" if "```" in sql else "```"
    return [f"{fence}sql", sql.rstrip("\n"), fence, ""]


# An input column the task reads in (most often through ``select *``) but no output,
# condition or key uses: ``used`` with no ``usages`` (C-P8). Not "used by this table".
READ_UNUSED = "读入未用（select * 等）"


def _inputs(inputs: list[dict], rules: list[dict] = ()) -> list[str]:
    lines = ["## 3. 输入表", ""]
    if not inputs:
        return [*lines, "（没有输入表）", ""]
    for entry in inputs:
        lines += [
            f"### {_code(entry['table'])}（{_comment(entry)}）",
            "",
            f"- 在本表的作用：{_names(entry['roles'])}；主表：{'是' if entry['driving'] else '否'}；"
            f"层：{_text(entry['layer'])}；生产任务：{_names(entry['producers'])}",
            f"- 分区列（元数据）：{_names(entry['partition_columns'])}；"
            f"分区读取：{entry['partition_read']}（{_partition_filters(entry, rules)}）"
            f"{_unfixed_partitions(entry)}；"
            f"表名约定：{entry['name_convention']}；全量快照：{full_snapshot_text(entry)}",
            "- 日期列上的过滤（只有「窗口」按业务日期筛行）：" + (_date_filters(entry, rules) or "无"),
            *_producer_header(entry),
            *_producer_columns(entry),
            "",
        ]
        rows = [
            [_code(c["name"]), _text(c["type"]), _comment(c),
             "、".join(c["usages"]) or (READ_UNUSED if c["used"] else "")]
            for c in entry["columns"]
        ]
        lines += _column_table(["列", "类型", "注释", "本表用到"], rows, entry["columns"])
        lines.append("")
    return lines


def _ids(rules) -> str:
    return "、".join(dict.fromkeys(str(rule["id"]) for rule in rules if rule.get("id")))


def _partition_filters(entry: dict, rules: list[dict]) -> str:
    """Each partition condition once, with the rules it is written in (C-P5)."""
    expressions = list(dict.fromkeys(entry["partition_filters"]))
    if not expressions:
        return "—"
    found = partition_filter_rules(entry["table"], list(rules))
    said = []
    for expression in expressions:
        ids = _ids(rule for text, rule in found if text == expression)
        said.append(_code(expression) + (f"（{ids}）" if ids else ""))
    return "、".join(said)


def _unfixed_partitions(entry: dict) -> str:
    """D-G7b: the partition columns no condition fixes, when some other one is fixed.

    Each with its comment as written, no verdict: whether reading every value of the
    column multiplies rows depends on the data, which the comment may speak to. A read
    with no partition condition at all is said by 全量快照 already.
    """
    fixed: set[str] = set()
    for text in entry["partition_filters"]:
        node = parse_expression(text)
        fixed |= {column.name.lower() for column in node.find_all(exp.Column)} if node else set()
    partitions = [str(name) for name in entry["partition_columns"]]
    unfixed = [name for name in partitions if name.lower() not in fixed]
    if not fixed & {name.lower() for name in partitions} or not unfixed:
        return ""
    columns = {str(column["name"]).lower(): column for column in entry["columns"]}
    said = []
    for name in unfixed:
        column = columns.get(name.lower()) or {}
        said.append(_code(name) + (f"（注释：{_comment(column)}）" if column.get("comment")
                                   else "（无注释）"))
    return f"；未限定的分区列：{'、'.join(said)}"


def _date_filters(entry: dict, rules: list[dict]) -> str:
    """Each business-date filter once per column, expression and shape, with its rules (C-P5).

    A filter's rules are the non-partition filters on this input with the same expression
    in the same statement -- the rules its ``date_filters`` entries were read from.
    """
    grouped: dict[tuple, list[dict]] = {}
    for item in entry["date_filters"]:
        shape = _DATE_SHAPES.get(item.get("shape"), _DATE_SHAPES["window"])
        grouped.setdefault((item["column"], item["expression"], shape), []).append(item)
    said = []
    for (column, expression, shape), items in grouped.items():
        statements = {item.get("statement_id") for item in items}
        ids = _ids(
            rule for rule in rules
            if rule["kind"] == "filter" and not rule["partition_filter"]
            and entry["table"] in rule["tables"] and rule["expression"] == expression
            and rule.get("statement_id") in statements
        )
        said.append(f"{_code(column)}：{_code(expression)}（{shape}{'；' + ids if ids else ''}）")
    return "；".join(said)


def _producer_columns(entry: dict) -> list[str]:
    """D-G5a-1: the producer's own summary of the columns this table reads by key."""
    written = entry.get("producer_columns") or []
    if not written:
        return []
    said = "；".join(f"{_code(item['task'])} / {_text(item['statement_id'])} "
                    f"{_code(item['column'])}：{cell(item['summary'])}" for item in written)
    return [f"- 生产任务怎么写这些列（表卡摘要，非本任务 SQL）：{said}"]


_DATE_SHAPES = {
    "window": "窗口",
    "as_of": "有效期取数（拉链）",
    "upper_bound": "只有上界",
    "null_check": "非空判断",
}


def full_snapshot_text(entry: dict) -> str:
    """``full_snapshot`` with the reason it is not proven, when it is not.

    The JSON keeps the boolean check 9 reads; a bare 否 could mean "not partitioned",
    "no partition condition seen", "several partitions read" or "the name says it is not
    a full table", and a reader needs to know which.
    """
    if entry["full_snapshot"]:
        return "是"
    if not (entry.get("partitioned") or entry.get("partition_columns")):
        return "不适用（非分区表）"
    if entry["partition_read"] == "none":
        return "未证明（未见分区条件）"
    if entry["partition_read"] == "multi_equality":
        return f"否（{_fixed_partitions(entry)}）"
    if entry["partition_read"] != "equality":
        return "否（读多个分区 / 范围）"
    return f"未证明（表名约定 {entry['name_convention']}）"


def _fixed_partitions(entry: dict) -> str:
    """C-P7: which fixed partitions are read, and that a full table holds a copy in each."""
    values = list(dict.fromkeys(
        value for text in entry["partition_filters"] for value in partition_values(text) or []))
    said = f"读 {len(values)} 个固定分区 {'、'.join(values)}"
    if entry["name_convention"] == "full":
        said += "；表名约定 full：每个分区是一份快照，同一记录在每份里各一行"
    return said


def _lineage(lineage: dict, tasks: list[dict] = ()) -> list[str]:
    lines = ["## 4. 血缘事实", ""]
    lines += _column_sources(lineage["columns"], _added_dates(list(tasks)))
    lines += _rules(lineage["rules"], lineage.get("findings") or [], list(tasks))
    lines += _keys(lineage["keys"], lineage["partition"])
    lines += _findings(lineage.get("findings") or [])
    lines += _neighbours(lineage)
    return lines


def _column_sources(columns: list[dict], added: dict | None = None) -> list[str]:
    """4.1; a column a producing task's header says was added later says so first (D-G4)."""
    added = added or {}
    lines = [
        "### 4.1 字段来源",
        "",
        *_default_time_format_note(
            text for entry in columns for producer in entry["producers"]
            for text in [producer["expression"], *producer["steps"]]),
        "| 列 | 任务 / 语句 | 加工 | 来源列 | 表达式 | 步骤 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for entry in columns:
        if not entry["producers"]:
            lines.append(f"| {_code(entry['column'])} | — | 未由 SELECT 写出（分区列或未写） | — | — | — |")
        for producer in entry["producers"]:
            date = added.get((producer["task"], entry["column"]))
            later = f"头注释：{date} 才加入，此前写入的行该列可能为空" if date else ""
            lines.append(
                f"| {_produced_column(entry['column'], producer)} | {_written_by(producer)} | "
                f"{_transform(producer)} | {_producer_sources(producer)} | "
                f"{_code(producer['expression'])} | {_steps(producer, later)} |"
            )
    return [*lines, ""]


def _produced_column(column: str, producer: dict) -> str:
    alias = producer.get("sql_alias")
    return f"{_code(column)}（SQL 别名 {_code(alias)}，按位置写入）" if alias else _code(column)


_BRANCH = re.compile(r"（([^（）]*)）$")


def _written_by(producer: dict) -> str:
    """Task / statement, and the MERGE branches a folded producer stands for."""
    said = f"{_text(producer['task'])} / {_text(producer['statement_id'])}"
    branches = producer.get("branches") or []
    if not branches:
        return said
    names = [(_BRANCH.search(label) or [None, label])[1] for label in branches]
    return f"{said}（{len(branches)} 支：{cell('、'.join(names))}）"


def _transform(producer: dict) -> str:
    computed = producer.get("computed_by") or []
    if not computed:
        return _text(producer["transform"])
    return f"{_text(producer['transform'])}（末层）；链上：{cell(' → '.join(computed))}"


def _producer_sources(producer: dict) -> str:
    keys = producer.get("lookup_keys") or []
    if not keys:
        return _names(producer["sources"])
    return f"{_names(producer['sources'])}；查码键（决定读哪一行，不是取值来源）：{_names(keys)}"


# A 4.1 step cell holds the whole chain up to this many characters. A longer chain -- a
# UNION's branches one after another, a deep CTE chain -- says its computing steps, the
# direct projections and merges left out (D-G5); when those still do not fit, or there
# are none, it says its last step and how many steps there are. Either way the chain is
# left to ``packet.json`` (C-P8, option b): each producer stays one bounded table row,
# which a reader's file tool takes in one piece.
STEPS_CELL_LIMIT = 300

_FULL_CHAIN = "完整步骤见同目录 packet.json 该列 producers[].steps"


def _steps(producer: dict, later: str = "") -> str:
    comments = producer.get("sql_comments") or []
    parts = [later] if later else []
    parts += [f"注释：{'；'.join(comments)}"] if comments else []
    steps = [str(step) for step in producer["steps"]]
    if len("；".join(steps)) > STEPS_CELL_LIMIT:
        steps = [_computing_steps(steps) or _last_step(steps)]
    return _text("；".join([*parts, *steps]))


def _computing_steps(steps: list[str]) -> str:
    """``计算步骤：…`` -- the chain without its pass-throughs, each text once; "" if too long.

    ``packet.json`` keeps a step as words only, so a pass-through is told by the prefix
    ``semantic_text`` words it with (:data:`PASS_THROUGH_TEXT_PREFIXES`).
    """
    prefixes = tuple(PASS_THROUGH_TEXT_PREFIXES.values())
    computing = [step for step in steps if not step.startswith(prefixes)]
    unique = list(dict.fromkeys(computing))
    if not unique or len("；".join(unique)) > STEPS_CELL_LIMIT:
        return ""
    left_out = f"略去 {len(steps) - len(computing)} 个直接投影 / 合并步骤"
    if len(computing) > len(unique):
        left_out += f"、{len(computing) - len(unique)} 个重复步骤"
    return f"计算步骤：{'；'.join(unique)}（{left_out}；{_FULL_CHAIN}）"


def _last_step(steps: list[str]) -> str:
    last = steps[-1]
    last = last if len(last) <= STEPS_CELL_LIMIT else last[:STEPS_CELL_LIMIT] + "…"
    return f"末层：{last}（共 {len(steps)} 步；{_FULL_CHAIN}）"


# D-G4. SQLGlot writes FROM_UNIXTIME / UNIX_TIMESTAMP without a format argument equal to
# the dialect's default, so ``from_unixtime(x, 'yyyy-MM-dd HH:mm:ss')`` comes back as
# ``FROM_UNIXTIME(x)`` -- in the contract already, not here. The meaning is the same (the
# default is that format); what the SQL text wrote is not, and a reader comparing the two
# needs telling once per section, not once per row.
DEFAULT_TIME_FORMAT_NOTE = (
    "注：FROM_UNIXTIME / UNIX_TIMESTAMP 只有一个参数的，格式是默认的 'yyyy-MM-dd HH:mm:ss'；"
    "SQL 原文写了这个格式时，解析后会省略"
)

_UNIX_TIME_CALL = re.compile(r"\b(FROM_UNIXTIME|UNIX_TIMESTAMP)\s*\(", re.IGNORECASE)


def _default_time_format_note(texts) -> list[str]:
    """The note and a blank line, when one of ``texts`` holds a one-argument call."""
    return [DEFAULT_TIME_FORMAT_NOTE, ""] if any(map(_has_default_time_format, texts)) else []


def _has_default_time_format(text) -> bool:
    text = str(text or "")
    for match in _UNIX_TIME_CALL.finditer(text):
        node = parse_expression(_call_text(text, match.start(), match.end() - 1))
        if isinstance(node, (exp.UnixToStr, exp.StrToUnix)) and node.this is not None:
            name = match.group(1).upper()
            if node.sql(dialect=DIALECT) == f"{name}({node.this.sql(dialect=DIALECT)})":
                return True
    return False


def _call_text(text: str, start: int, opening: int) -> str:
    """``text[start:]`` up to the parenthesis closing the one at ``opening``."""
    depth, quote = 0, ""
    for index in range(opening, len(text)):
        char = text[index]
        if quote:
            quote = "" if char == quote else quote
        elif char in "'\"`":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return text[start:]


def _rules(rules: list[dict], findings: list[dict], tasks: list[dict] = ()) -> list[str]:
    lines = [
        "### 4.2 规则（过滤 / 关联 / 去重 / 合并 / 分支）",
        "",
        *_default_time_format_note(rule["expression"] for rule in rules),
        "| 编号 | 类型 | 位置 | 表达式 | 分区过滤 | 涉及表 | 行数放大 | 说明 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    several = len({rule.get("task") for rule in rules}) > 1
    lines += [
        f"| {rule['id']} | {rule['kind']}{('（' + rule['join_type'] + '）') if rule.get('join_type') else ''} | "
        f"{_position(rule, several)} | {_code(rule['expression'])} | {_partition_cell(rule)} | "
        f"{_names(rule['tables'])} | {_fan_out(rule)} | {_rule_note(rule, findings, tasks)} |"
        for rule in rules
    ]
    if not rules:
        lines.append("| — | — | — | — | — | — | — | — |")
    return [*lines, ""]


def _position(rule: dict, several_tasks: bool) -> str:
    """``stmt:00N / <scope>``, the task first when the packet has several (C-P5).

    Two rules with one expression in two subqueries read apart by it.
    """
    parts = [rule.get("task")] if several_tasks else []
    parts += [rule.get("statement_id"), rule.get("scope")]
    return cell(" / ".join(str(part) for part in parts if part)) or "—"


def _rule_note(rule: dict, findings: list[dict], tasks: list[dict] = ()) -> str:
    """Everything the 说明 column says of a rule, joined in :data:`_NOTE_PARTS` order."""
    context = {"findings": findings, "tasks": tasks}
    return _text("；".join(text for part in _NOTE_PARTS for text in part(rule, context)))


def _note_text(rule: dict, _context: dict) -> list[str]:
    return [str(rule["text"])] if rule.get("text") else []


def _note_dates(rule: dict, context: dict) -> list[str]:
    """D-G6: how far each date literal of the rule sits from its task's expected run date.

    The offsets 2.x gives for the task's ``date_literals``, matched by string literal; an
    offset only -- which literal is the batch date is the writer's call (E1).
    """
    literals = next((task.get("date_literals") or [] for task in context["tasks"]
                     if task.get("name") == rule.get("task")), [])
    offsets = {item["literal"]: item["days_from_expect_date"] for item in literals}
    said = [f"{literal}（{_offset(offsets[literal])}）"
            for literal in dict.fromkeys(string_literals(rule.get("expression")))
            if literal in offsets]
    return [f"日期字面量 {'、'.join(said)}"] if said else []


def _note_position(rule: dict, _context: dict) -> list[str]:
    """A filter inside a LEFT JOIN's right side decides which right rows match, no more.

    A partition filter there decides which partitions the right side reads (round 3 V2).
    """
    joins = rule.get("right_of") or []
    if not joins:
        return []
    decides = "读哪些分区" if rule.get("partition_filter") else "哪些行参与匹配"
    return [f"在 {'、'.join(joins)} 右侧：不丢目标行，决定右侧{decides}"]


def _note_comments(rule: dict, _context: dict) -> list[str]:
    return [f"注释：{'；'.join(rule['sql_comments'])}"] if rule.get("sql_comments") else []


def _note_switched_off(rule: dict, _context: dict) -> list[str]:
    sql = rule.get("commented_out_sql") or []
    return [f"相邻的注释掉的 SQL（不生效）：{'；'.join(sql)}"] if sql else []


def _note_unconsumed(rule: dict, _context: dict) -> list[str]:
    return ["未被消费：这条分支的输出没有被任何下游读取"] if rule.get("consumed") is False else []


def _note_findings(rule: dict, context: dict) -> list[str]:
    return [str(item["text"]) for item in context["findings"]
            if rule["id"] in (item.get("rules") or [])]


# The 说明 column's parts, in the one order every packet change fills (README 裁决 11):
# the rule's text; the date offsets of its literals (D-G6, right after the text); where
# the rule sits (`right_of`); the author's notes; the SQL switched off beside it; whether
# anybody reads it; the findings about it. A part with nothing to say says nothing.
_NOTE_PARTS = (
    _note_text,
    _note_dates,
    _note_position,
    _note_comments,
    _note_switched_off,
    _note_unconsumed,
    _note_findings,
)


def _partition_cell(rule: dict) -> str:
    if rule.get("partition_reads"):
        return f"是（右表 {'、'.join(_code(read['expression']) for read in rule['partition_reads'])}）"
    return "是" if rule["partition_filter"] else ""


def _fan_out(rule: dict) -> str:
    """A JOIN's verdict (anything but ``safe`` must be named in the document); else blank."""
    if rule["kind"] != "join":
        return ""
    verdict = rule.get("fan_out")
    if verdict:
        return _text(_verdict(rule, verdict) + _unfiltered(rule))
    if rule.get("inside"):
        return f"在 {'、'.join(rule['inside'])} 右侧内部；行数影响已计入这些关联的判定"
    if rule.get("below_aggregate"):
        return (f"位于聚合 {_code(rule['below_aggregate'])} 之下：不复制输出行，可能放大聚合值；"
                "工具未判定")
    return f"工具未判定（{_code(rule.get('scope'))}）"


def _verdict(rule: dict, verdict: dict) -> str:
    """``status：reason``; a JOIN off the grain path first says where it sits (C-P3)."""
    if verdict.get("path") in (None, "grain"):
        return f"{verdict['status']}：{verdict['reason']}"
    where = (f"位于聚合 {_code(rule['verdict_aggregate'])} 之下" if rule.get("verdict_aggregate")
             else "在聚合参数路径上")
    return f"{verdict['status']}（{where}：不复制输出行，可能让聚合值重复计入）：{verdict['reason']}"


def _unfiltered(rule: dict) -> str:
    ranked = rule.get("unfiltered_ranking") or []
    return f"；右侧的 {'、'.join(ranked)} 算了排名但没有 = 1 过滤，未去重" if ranked else ""


def _keys(keys: list[dict], partitions: list[dict]) -> list[str]:
    lines = [
        "### 4.3 粒度、键与分区",
        "",
        "| 任务 / 语句 | 形态 | 粒度依据 | 粒度键（目标列） | 候选键 | 键置信 | 已证明 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| {_text(key['task'])} / {_text(key['statement_id'])} | {_text(key['shape'])} | "
        f"{_text(key['grain_basis'])} | {_grain_cell(key)} | {_names(key['candidate_keys'])} | "
        f"{_text(key['key_confidence'])} | {'是' if key['proven'] else '否'} |"
        for key in keys
    ]
    lines.append("")
    for key in keys:
        lines += _merge_lines(key)
    lines += [
        f"- 分区写入（{_text(item['task'])} / {_text(item['statement_id'])}）：{_names(item['columns'])}，"
        + _partition_values(item)
        for item in partitions
    ]
    return [*lines, ""]


_CLAUSES = {"matched": "matched", "not_matched": "not matched",
            "not_matched_by_source": "not matched by source"}
_LEFT_ALONE = {
    "matched": "matched 但条件不满足的行既不更新也不插入",
    "not_matched": "not matched 但条件不满足的源行不插入",
    "not_matched_by_source": "not matched by source 但条件不满足的目标行不动",
}


def _grain_cell(key: dict) -> str:
    """The target column of each grain key; without ``grain_columns`` the keys are those columns.

    Round 3 M1: a key reaching the target through an expression or a MERGE's ON equality
    says so, and a key the write leaves out is named as the scope's column it is.
    """
    columns = key.get("grain_columns")
    if not columns:
        return _names(key["grain_keys"])
    said = []
    for item in columns:
        logical = _text(item.get("logical"))
        if item.get("via") == "unexposed" or not item.get("column"):
            said.append(f"{logical}（未写入目标表）")
        elif item.get("via") == "derived":
            said.append(f"{_code(item['column'])}（派生自 {logical}）")
        elif item.get("via") == "merge_on":
            said.append(f"{_code(item['column'])}（经 ON 等值，USING 侧 {logical}）")
        else:
            said.append(_code(item["column"]))
    return "、".join(said)


def _merge_lines(key: dict) -> list[str]:
    """A MERGE's merge key, its WHEN clauses, and its USING dedup against the merge key."""
    merge = key.get("merge")
    if not merge:
        return []
    at = f"（{_text(key['task'])} / {_text(key['statement_id'])}）"
    pairs = [f"target.{pair['target']} = source.{pair['source']}"
             for pair in merge.get("merge_keys") or []]
    on = cell("、".join(pairs)) if pairs else "—"
    if merge.get("other_on_conditions"):
        on += "；其他 ON 条件：" + "、".join(_code(text) for text in merge["other_on_conditions"])
    return [
        f"- MERGE 合并键{at}：{on}",
        f"- MERGE WHEN{at}：{_whens(merge.get('whens') or [])}",
        f"- MERGE 去重与合并键{at}：{_coverage(merge)}",
        *_writer_keys(merge, at),
        *_table_key(merge, at),
        *_update_facts(merge, at),
    ]


def _writer_keys(merge: dict, at: str) -> list[str]:
    """Round 3 M4b: a USING side read from a table whose writer keys its batch on more columns.

    The writer's batch key is an inference about what tells the table's rows apart, so
    the line says so; the consequence follows the statement's WHEN clauses (M4a).
    """
    found = merge.get("using_writer_keys") or []
    if not found:
        return []
    table = ((merge.get("using_grain") or {}).get("evidence") or [""])[-1]
    then = _multi_row_consequence(merge.get("whens") or [])
    said = "；".join(
        f"{_text(item.get('label'))}是 {_names(item.get('keys') or [])}（推断为行的区分键），"
        f"比合并键多出 {_names(item.get('extra') or [])}"
        for item in found)
    return [f"- MERGE USING 与写入方的键{at}：USING 读 {_code(table)} 的行；{said}：同一合并键在 USING 侧"
            f"可能多行{'，' + then if then else ''}"]


def _table_key(merge: dict, at: str) -> list[str]:
    """A-M1: the key the MERGE suggests for the table -- inferred, never proven."""
    table_key = merge.get("table_key")
    if not table_key:
        return []
    if table_key.get("status") == "update_only":
        return [f"- MERGE 后目标表的键{at}：只更新已有行、不新增行，本语句不决定目标表的行粒度"]
    return [f"- MERGE 后目标表的候选键{at}：{_names(table_key.get('keys') or [])}"
            "（按 ON 合并键与 USING 去重键推断，未证明）"]


def _update_facts(merge: dict, at: str) -> list[str]:
    """A-M2: what a matched UPDATE leaves alone, changes, or may overwrite with NULL.

    Round 3 M2: a column only some UNION branches may blank out is said with those
    branches, and a column a branch fills with a literal on a miss (M2b) on a line of its
    own -- an old value overwritten by ``''`` is lost as surely as by NULL.
    """
    lines = []
    if merge.get("insert_only_columns"):
        lines.append(f"- MERGE matched UPDATE 不改的列{at}：{_names(merge['insert_only_columns'])}"
                     "（只在首次 INSERT 时写入，之后不随更新变化）")
    if merge.get("update_columns"):
        lines.append(f"- MERGE matched UPDATE 只改{at}：{_names(merge['update_columns'])}，其余列保持原值")
    blanks = _blanked(merge)
    if blanks:
        lines.append(f"- MERGE matched UPDATE 可能写入空值{at}：{'；'.join(blanks)}")
    filled = _filled(merge.get("update_filled_on_miss") or [])
    if filled:
        lines.append(f"- MERGE matched UPDATE 关联未命中时写回填值{at}：{filled}："
                     "本次关联未命中时会把已有值覆盖成该值")
    return lines


def _blanked(merge: dict) -> list[str]:
    """The columns every branch may blank, then those some branches may, grouped by branches."""
    said = []
    if merge.get("update_nullable_by_join"):
        said.append(f"{_names(merge['update_nullable_by_join'])} 来自 LEFT JOIN，"
                    "本次关联未命中时会把已有值覆盖成 NULL")
    groups: dict[tuple, list[str]] = {}
    for column, branches in (merge.get("update_nullable_by_join_branches") or {}).items():
        groups.setdefault(tuple(branches), []).append(column)
    said += [f"{_names(columns)} 只在 USING 的 UNION 分支 {'、'.join(map(str, branches))} 来自 LEFT JOIN："
             "这些分支的行本次关联未命中时，会把已有值覆盖成 NULL"
             for branches, columns in groups.items()]
    return said


def _filled(entries: list[dict]) -> str:
    """M2b: each column with the literal it gets on a miss, per UNION branch when there are any."""
    values: dict[str, list[str]] = {}
    for entry in entries:
        branches = entry.get("branches")
        where = f"分支 {'、'.join(map(str, branches))} " if branches else ""
        values.setdefault(str(entry.get("column")), []).append(f"{where}写 {_code(entry.get('value'))}")
    return "、".join(f"{_code(column)}（{'；'.join(said)}）" for column, said in values.items())


def _whens(whens: list[dict]) -> str:
    parts = []
    for when in whens:
        clause = _CLAUSES.get(str(when.get("clause")), str(when.get("clause")))
        condition = f" AND {_code(when['condition'])}" if when.get("condition") else ""
        action = str(when.get("action") or "?").upper()
        star = (" SET *" if action == "UPDATE" else " *") if when.get("star") else ""
        parts.append(f"{clause}{condition} → {action}{star}")
    for clause, said in _LEFT_ALONE.items():
        mine = [when for when in whens if when.get("clause") == clause]
        if mine and all(when.get("condition") for when in mine):
            parts.append(said)
    return "；".join(parts) or "—"


_COVERAGE = {
    "covered": "covered（去重键都在合并键里，USING 侧每个合并键至多一行）",
    "no_dedup": "no_dedup（USING 侧没有去重，同一合并键可能有多行）",
    "unknown": "unknown（工具无法比较）",
}


def _multi_row_consequence(whens: list[dict]) -> str:
    """Round 3 M4a: what the statement's own WHEN clauses do with two USING rows of one key.

    A matched UPDATE / DELETE meets several source rows for one target row; a not matched
    INSERT inserts a missing key once per USING row. Nothing is said of a clause the
    statement does not have, nor of which engine fails how.
    """
    said = []
    if any(when.get("clause") == "matched" and str(when.get("action")) in ("update", "delete")
           for when in whens):
        said.append("matched 分支会遇到多个 USING 行匹配同一目标行（通常报错终止，引擎行为，推断）")
    if any(when.get("clause") == "not_matched" and str(when.get("action")) == "insert"
           for when in whens):
        said.append("目标里没有的合并键会按 USING 行数重复插入")
    return "，".join(said)


def _coverage(merge: dict) -> str:
    """The USING side's dedup, branch by branch for a UNION, against the merge key.

    A grain the tool did not decide is said to be undecided, never "no dedup" (A-M3).
    Where one merge key may have two USING rows -- no dedup, a dedup wider than the merge
    key, UNION branches -- the statement's WHEN clauses say what follows (round 3 M4a).
    """
    basis = (merge.get("using_grain") or {}).get("basis")
    keys = merge.get("dedup_keys") or []
    then = _multi_row_consequence(merge.get("whens") or [])
    if merge.get("union_branches"):
        head = ("USING 是 UNION，逐分支：" + "；".join(map(_branch, merge["union_branches"]))
                + "；分支之间没有去重：同一合并键可能在不同分支各出一行" + (f"，{then}" if then else ""))
    elif keys:
        head = "USING 去重键 " + _dedup_keys(keys)
    elif basis == "unknown":
        head = "USING 粒度未判定（unknown）"
    else:
        head = f"USING 无去重（{_text(basis)}）"
    coverage = merge.get("coverage")
    if coverage == "dedup_wider":
        said = (f"dedup_wider（去重键多出 {_names(merge.get('extra_keys') or [])}：同一合并键在 USING "
                f"侧可能多行{'，' + then if then else ''}）")
    elif coverage == "no_dedup" and then:
        said = f"no_dedup（USING 侧没有去重，同一合并键可能有多行：{then}）"
    else:
        said = _COVERAGE.get(str(coverage), _text(coverage))
    joins = merge.get("joins_after_dedup") or []
    after = f"；去重之后还有未证明唯一的关联 {'、'.join(joins)}" if joins else ""
    return f"{head}；与合并键比较：{said}{after}"


_DEDUP_BASES = ("group_by", "distinct", "window_partition")


def _dedup_keys(keys: list[dict]) -> str:
    return "、".join(_code(item["column"]) + ("（派生）" if item.get("derived") else "")
                    for item in keys)


def _branch(branch: dict) -> str:
    """One UNION branch of a USING side: its dedup and how it compares, or its grain."""
    basis = branch.get("basis")
    if not branch.get("dedup_keys"):
        said = ("粒度未判定" if basis == "unknown"
                else "去重键没有抬到 USING 输出" if basis in _DEDUP_BASES else "无去重")
        return f"分支 {branch['branch']} {said}（{_text(basis)}）"
    joins = branch.get("joins_after_dedup") or []
    after = f"；去重之后还有未证明唯一的关联 {'、'.join(joins)}" if joins else ""
    return (f"分支 {branch['branch']} 按 {_dedup_keys(branch['dedup_keys'])} 去重"
            f"（{_text(branch.get('coverage'))}{after}）")


def _findings(findings: list[dict]) -> list[str]:
    """The governance findings a writer must see, after the keys they are often about."""
    if not findings:
        return []
    lines = ["#### 治理线索（工具发现，需核实）", ""]
    lines += [
        f"- {item['kind']}（{_text(item['task'])} / {_text(item['statement_id'])}"
        + (f"，规则 {'、'.join(item['rules'])}" if item.get("rules") else "")
        + f"）：{_text(item['text'])}"
        for item in findings
    ]
    return [*lines, ""]


def _partition_values(item: dict) -> str:
    """The write mode and each partition's value: the spec's, or the constants a SELECT writes."""
    chosen = item.get("select_values") or {}
    spec = "、".join(f"{name} = {_code(value)}" for name, value in item["spec"].items()
                     if name not in chosen)
    constants = "；".join(
        f"{name} = {_code(values[0])}" if len(values) == 1
        else f"{name} ∈ {'、'.join(_code(value) for value in values)}"
        for name, values in chosen.items()
    )
    if item["mode"] == "merge_row_values":
        states = item.get("merge_columns")
        rows = ("；".join(_merge_partition(name, state) for name, state in states.items()) if states
                else "UPDATE 不改该列时行留在原分区")
        return ("MERGE 无 PARTITION 子句：按写入行的分区列值落分区（INSERT 时取 USING 该列的值；"
                f"{rows}）" + (f"（INSERT 写常量：{constants}）" if chosen else ""))
    if not chosen:
        return f"{_text(item['mode'])}，{spec or '无分区值'}"
    return f"{_text(item['mode'])}（SELECT 写常量：{constants}）" + (f"，{spec}" if spec else "")


def _merge_partition(name: str, state: dict) -> str:
    """Round 3 M3: whether a MERGE's UPDATE leaves, moves or cannot reach a partition's rows.

    A matched condition pinning the column (``pinned``) confines the update to that one
    partition: a same-key row elsewhere is neither updated nor inserted again, so no old
    partition is rewritten.
    """
    column = _code(name)
    pinned = state.get("pinned")
    where = (f"matched 条件限定 target.{name} = {_code(pinned)}：只有 {name} = {_code(pinned)} 的已有行会被更新"
             if pinned else "")
    elsewhere = "既不更新、也不会再插入（本次 USING 行被丢弃），旧分区不被本语句改写"
    if state.get("update") == "none":
        return f"{column}：只插入新行，已有行不动"
    if state.get("key"):
        return f"{column}：合并键列，matched 行上 ON 保证 {name} 不变，行留在原分区"
    if state.get("update") == "writes":
        if pinned:
            return (f"{column}：matched UPDATE 也写 {name}，但 {where}，其中 USING 的 {name} 不同的行换到新值的"
                    f"分区；其他分区的同键行{elsewhere}")
        return f"{column}：matched UPDATE 也写 {name}：已有行的 {name} 与本次写入值不同时，行换到新值对应的分区"
    if pinned:
        return (f"{column}：matched UPDATE 不改 {name}：被更新的已有行留在原分区；{where}，"
                f"同一合并键落在其他分区的已有行{elsewhere}")
    return f"{column}：matched UPDATE 不改 {name}：被更新的已有行留在原分区，本语句会改写旧分区里的行"


def _neighbours(lineage: dict) -> list[str]:
    lines = [
        "### 4.4 上下游",
        "",
        f"- 上游表：{_names(lineage['upstream_tables'])}",
        f"- 上游任务：{_names(lineage['upstream_tasks'])}",
        "",
        "| 下游任务 | 写入的表 | 依据 | 读法 | 按哪些列读（关联 / 过滤） |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| {_code(entry['task'])} | {_names(entry['tables'])} | "
        f"{'血缘' if entry['source'] == 'lineage' else '任务登记'} | {_names(entry['roles'])} | "
        f"{_read_by(entry.get('columns') or {})} |"
        for entry in lineage["downstream"]
    ]
    if not lineage["downstream"]:
        lines.append("| — | — | — | — | — |")
    return [*lines, ""]


_READ_BY = {"join_key": "关联", "filter": "过滤"}


def _read_by(columns: dict) -> str:
    """D-G5b: this table's columns a consumer joins and filters on (its table card)."""
    said = [f"{_names(names)}（{_READ_BY.get(usage, usage)}）" for usage, names in columns.items()]
    return "；".join(said) or "—"


def _column_order(target: dict) -> list[str]:
    return [
        "## 5. 目标列顺序",
        "",
        "table-semantics/1 的 `columns` 必须按下面的顺序逐一覆盖，不多不少：",
        "",
        "、".join(_code(column["name"]) for column in target["columns"]),
        "",
    ]
