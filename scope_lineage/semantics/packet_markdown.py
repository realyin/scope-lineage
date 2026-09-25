"""``packet.md``: the packet as a model (or a person) reads it.

Same facts as ``packet.json``, in the order a writer needs them: the table, the tasks
and their SQL, the inputs, the lineage facts, and last the column order the document
must follow. Nothing here is added or dropped relative to the JSON; the validator reads
the JSON.
"""

from __future__ import annotations

from ..render.markdown_text import cell, expr_span


def render_packet_markdown(packet: dict) -> str:
    lines = [
        f"# 材料包：{packet['table']}",
        "",
        f"- 格式：`{packet['doc_format']}`",
        f"- packet_digest：`{packet['packet_digest']}`（原样写进 table-semantics/1 的 "
        "`packet_digest`；材料变了它就变，校验据此判断文档是否过期）",
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


def _target(target: dict) -> list[str]:
    lines = [
        "## 1. 目标表",
        "",
        f"- 表：{_code(target['table'])}；表注释：{_text(target['comment'])}",
        f"- 说明：{_text(target['description'])}；层：{_text(target['layer'])}；"
        f"域：{_text(target['domain'])}；元数据来源：{target['metadata_source']}",
        "",
        "| # | 列 | 类型 | 注释 | 分区列 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for index, column in enumerate(target["columns"], start=1):
        lines.append(
            f"| {index} | {_code(column['name'])} | {_text(column['type'])} | "
            f"{_text(column['comment'])} | {'是' if column['partition'] else ''} |"
        )
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
            f"- 登记的上游任务：{_names(task['upstream_tasks'])}；"
            f"登记的下游任务：{_names(task['downstream_tasks'])}",
            f"- 写入语句：{_names(task['statements'])}；来源文件：{_text(task['source_file'])}",
            "",
        ]
        lines += [f"> {comment}" for comment in task["header_comments"]]
        lines += [""] if task["header_comments"] else []
        lines += _sql(task["sql"])
    return lines


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
            f"### {_code(entry['table'])}（{_text(entry['comment'])}）",
            "",
            f"- 在本表的作用：{_names(entry['roles'])}；主表：{'是' if entry['driving'] else '否'}；"
            f"层：{_text(entry['layer'])}；生产任务：{_names(entry['producers'])}",
            f"- 分区列（元数据）：{_names(entry['partition_columns'])}；"
            f"分区读取：{entry['partition_read']}（{_names(entry['partition_filters'])}）；"
            f"表名约定：{entry['name_convention']}；全量快照：{'是' if entry['full_snapshot'] else '否'}",
            "- 业务日期过滤：" + (
                "；".join(f"{_code(item['column'])}：{_code(item['expression'])}"
                         for item in entry["date_filters"]) or "无"
            ),
            "",
            "| 列 | 类型 | 注释 | 本表用到 |",
            "| --- | --- | --- | --- |",
        ]
        lines += [
            f"| {_code(c['name'])} | {_text(c['type'])} | {_text(c['comment'])} | "
            f"{'、'.join(c['usages']) or ('是' if c['used'] else '')} |"
            for c in entry["columns"]
        ]
        lines.append("")
    return lines


def _lineage(lineage: dict) -> list[str]:
    lines = ["## 4. 血缘事实", ""]
    lines += _column_sources(lineage["columns"])
    lines += _rules(lineage["rules"])
    lines += _keys(lineage["keys"], lineage["partition"])
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
                f"| {_code(entry['column'])} | {_text(producer['task'])} / {_text(producer['statement_id'])} | "
                f"{_text(producer['transform'])} | {_names(producer['sources'])} | "
                f"{_code(producer['expression'])} | {_text('；'.join(producer['steps']))} |"
            )
    return [*lines, ""]


def _rules(rules: list[dict]) -> list[str]:
    lines = [
        "### 4.2 规则（过滤 / 关联 / 去重 / 合并 / 分支）",
        "",
        "| 编号 | 类型 | 表达式 | 分区过滤 | 涉及表 | 说明 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| {rule['id']} | {rule['kind']}{('（' + rule['join_type'] + '）') if rule.get('join_type') else ''} | "
        f"{_code(rule['expression'])} | {'是' if rule['partition_filter'] else ''} | "
        f"{_names(rule['tables'])} | {_text(rule.get('text'))} |"
        for rule in rules
    ]
    if not rules:
        lines.append("| — | — | — | — | — | — |")
    return [*lines, ""]


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
    lines += [
        f"- 分区写入（{_text(item['task'])} / {_text(item['statement_id'])}）：{_names(item['columns'])}，"
        f"{_text(item['mode'])}，"
        + ("、".join(f"{name} = {_code(value)}" for name, value in item["spec"].items()) or "无分区值")
        for item in partitions
    ]
    return [*lines, ""]


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
