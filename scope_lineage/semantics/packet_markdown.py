"""``packet.md``: the packet as a model (or a person) reads it.

Same facts as ``packet.json``, in the order a writer needs them: the table, the tasks
and their SQL, the inputs, the lineage facts, and last the column order the document
must follow. Nothing here is added or dropped relative to the JSON; the validator reads
the JSON.

What the owner already confirmed is shown where it applies and only when there is some:
a patched comment carries 「（已确认，元数据补丁）」, and a column table gains an
「已确认码值」 column when one of its columns has confirmed values -- so a packet built
without either renders exactly as it did before.
"""

from __future__ import annotations

import re

from ..render.markdown_text import cell, expr_span
from .packet_facts import partition_values


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
    lines += _tasks(packet["tasks"])
    lines += _inputs(packet["inputs"])
    lines += _lineage(packet["lineage"])
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


def _tasks(tasks: list[dict]) -> list[str]:
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


def _inputs(inputs: list[dict]) -> list[str]:
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
            f"分区读取：{entry['partition_read']}（{_names(entry['partition_filters'])}）；"
            f"表名约定：{entry['name_convention']}；全量快照：{full_snapshot_text(entry)}",
            "- 日期列上的过滤（只有「窗口」按业务日期筛行）：" + (
                "；".join(f"{_code(item['column'])}：{_code(item['expression'])}"
                         f"（{_DATE_SHAPES.get(item.get('shape'), _DATE_SHAPES['window'])}）"
                         for item in entry["date_filters"]) or "无"
            ),
            *_producer_header(entry),
            "",
        ]
        rows = [
            [_code(c["name"]), _text(c["type"]), _comment(c),
             "、".join(c["usages"]) or ("是" if c["used"] else "")]
            for c in entry["columns"]
        ]
        lines += _column_table(["列", "类型", "注释", "本表用到"], rows, entry["columns"])
        lines.append("")
    return lines


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


def _lineage(lineage: dict) -> list[str]:
    lines = ["## 4. 血缘事实", ""]
    lines += _column_sources(lineage["columns"])
    lines += _rules(lineage["rules"], lineage.get("findings") or [])
    lines += _keys(lineage["keys"], lineage["partition"])
    lines += _findings(lineage.get("findings") or [])
    lines += _neighbours(lineage)
    return lines


def _column_sources(columns: list[dict]) -> list[str]:
    lines = [
        "### 4.1 字段来源",
        "",
        "| 列 | 任务 / 语句 | 加工 | 来源列 | 表达式 | 步骤 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for entry in columns:
        if not entry["producers"]:
            lines.append(f"| {_code(entry['column'])} | — | 未由 SELECT 写出（分区列或未写） | — | — | — |")
        for producer in entry["producers"]:
            lines.append(
                f"| {_produced_column(entry['column'], producer)} | {_written_by(producer)} | "
                f"{_transform(producer)} | {_producer_sources(producer)} | "
                f"{_code(producer['expression'])} | {_steps(producer)} |"
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


def _steps(producer: dict) -> str:
    comments = producer.get("sql_comments") or []
    steps = "；".join(producer["steps"])
    if comments:
        steps = f"注释：{'；'.join(comments)}" + (f"；{steps}" if steps else "")
    return _text(steps)


def _rules(rules: list[dict], findings: list[dict]) -> list[str]:
    lines = [
        "### 4.2 规则（过滤 / 关联 / 去重 / 合并 / 分支）",
        "",
        "| 编号 | 类型 | 表达式 | 分区过滤 | 涉及表 | 行数放大 | 说明 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| {rule['id']} | {rule['kind']}{('（' + rule['join_type'] + '）') if rule.get('join_type') else ''} | "
        f"{_code(rule['expression'])} | {_partition_cell(rule)} | "
        f"{_names(rule['tables'])} | {_fan_out(rule)} | {_rule_note(rule, findings)} |"
        for rule in rules
    ]
    if not rules:
        lines.append("| — | — | — | — | — | — | — |")
    return [*lines, ""]


def _rule_note(rule: dict, findings: list[dict]) -> str:
    """Everything the 说明 column says of a rule, joined in :data:`_NOTE_PARTS` order."""
    return _text("；".join(text for part in _NOTE_PARTS for text in part(rule, findings)))


def _note_text(rule: dict, _findings: list[dict]) -> list[str]:
    return [str(rule["text"])] if rule.get("text") else []


def _note_position(rule: dict, _findings: list[dict]) -> list[str]:
    """A filter inside a LEFT JOIN's right side decides which right rows match, no more."""
    joins = rule.get("right_of") or []
    return [f"在 {'、'.join(joins)} 右侧：不丢目标行，决定右侧哪些行参与匹配"] if joins else []


def _note_comments(rule: dict, _findings: list[dict]) -> list[str]:
    return [f"注释：{'；'.join(rule['sql_comments'])}"] if rule.get("sql_comments") else []


def _note_switched_off(rule: dict, _findings: list[dict]) -> list[str]:
    sql = rule.get("commented_out_sql") or []
    return [f"相邻的注释掉的 SQL（不生效）：{'；'.join(sql)}"] if sql else []


def _note_unconsumed(rule: dict, _findings: list[dict]) -> list[str]:
    return ["未被消费：这条分支的输出没有被任何下游读取"] if rule.get("consumed") is False else []


def _note_findings(rule: dict, findings: list[dict]) -> list[str]:
    return [str(item["text"]) for item in findings if rule["id"] in (item.get("rules") or [])]


# The 说明 column's parts, in the one order every packet change fills (README 裁决 11):
# the rule's text; the date offsets of its literals (C-G6, right after the text); where
# the rule sits (`right_of`); the author's notes; the SQL switched off beside it; whether
# anybody reads it; the findings about it. A part with nothing to say says nothing.
_NOTE_PARTS = (
    _note_text,
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
        "| 任务 / 语句 | 形态 | 粒度依据 | 粒度键 | 候选键 | 键置信 | 已证明 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| {_text(key['task'])} / {_text(key['statement_id'])} | {_text(key['shape'])} | "
        f"{_text(key['grain_basis'])} | {_names(key['grain_keys'])} | {_names(key['candidate_keys'])} | "
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
    ]


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


def _coverage(merge: dict) -> str:
    basis = (merge.get("using_grain") or {}).get("basis")
    keys = merge.get("dedup_keys") or []
    head = (
        "USING 去重键 " + "、".join(
            _code(item["column"]) + ("（派生）" if item.get("derived") else "") for item in keys)
        if keys else f"USING 无去重（{_text(basis)}）"
    )
    coverage = merge.get("coverage")
    if coverage == "dedup_wider":
        said = (f"dedup_wider（去重键多出 {_names(merge.get('extra_keys') or [])}：同一合并键在 USING "
                "侧可能多行，matched 更新会遇到多行匹配，not matched 会重复插入）")
    else:
        said = _COVERAGE.get(str(coverage), _text(coverage))
    joins = merge.get("joins_after_dedup") or []
    after = f"；去重之后还有未证明唯一的关联 {'、'.join(joins)}" if joins else ""
    return f"{head}；与合并键比较：{said}{after}"


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
    if not chosen:
        return f"{_text(item['mode'])}，{spec or '无分区值'}"
    constants = "；".join(
        f"{name} = {_code(values[0])}" if len(values) == 1
        else f"{name} ∈ {'、'.join(_code(value) for value in values)}"
        for name, values in chosen.items()
    )
    return f"{_text(item['mode'])}（SELECT 写常量：{constants}）" + (f"，{spec}" if spec else "")


def _neighbours(lineage: dict) -> list[str]:
    lines = [
        "### 4.4 上下游",
        "",
        f"- 上游表：{_names(lineage['upstream_tables'])}",
        f"- 上游任务：{_names(lineage['upstream_tasks'])}",
        "",
        "| 下游任务 | 写入的表 | 依据 | 读法 |",
        "| --- | --- | --- | --- |",
    ]
    lines += [
        f"| {_code(entry['task'])} | {_names(entry['tables'])} | "
        f"{'血缘' if entry['source'] == 'lineage' else '任务登记'} | {_names(entry['roles'])} |"
        for entry in lineage["downstream"]
    ]
    if not lineage["downstream"]:
        lines.append("| — | — | — | — |")
    return [*lines, ""]


def _column_order(target: dict) -> list[str]:
    return [
        "## 5. 目标列顺序",
        "",
        "table-semantics/1 的 `columns` 必须按下面的顺序逐一覆盖，不多不少：",
        "",
        "、".join(_code(column["name"]) for column in target["columns"]),
        "",
    ]
