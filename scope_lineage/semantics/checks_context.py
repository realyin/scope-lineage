"""Cross checks 5-9: rules, neighbours, sources, digest and time semantics.

Checks 1-4 (``checks``) hold each column and the grain to the lineage; these hold what
the document says *around* the columns -- which rows it keeps, who it reads and who reads
it, where each statement came from, which packet it was written against, and how its
partitions are to be read.
"""

from __future__ import annotations

from .checks import MAX_QUESTIONS, _plain, result
from .names import bare_table, normalize_sql

# 5 ------------------------------------------------------------------ rules


def check_rules(document: dict, packet: dict) -> list[dict]:
    """Every non-partition filter is cited; every quoted rule is in the SQL; refs resolve."""
    quoted = [normalize_sql(rule.get("sql")) for rule in document["rules"] if rule.get("sql")]
    results = []
    for rule in packet["lineage"]["rules"]:
        if rule["kind"] != "filter" or rule["partition_filter"]:
            continue
        expression = normalize_sql(rule["expression"])
        cited = any(text and (text == expression or text in expression or expression in text)
                    for text in quoted)
        results.append(result("rules", "pass", "rules") if cited else result(
            "rules", "fail", "rules",
            f"过滤 {_plain(rule['expression'])}（{rule['task']}）没有被任何 rules[].sql 引用；"
            "补一条 filter 规则（照抄 SQL 原文），并在 summary.scope 里用 rule_refs 引用它"))
    return results + _quoted_sql(document, packet) + _rule_refs(document)


def _quoted_sql(document: dict, packet: dict) -> list[dict]:
    scripts = [task["sql"] for task in packet["tasks"] if task["sql"]]
    text = normalize_sql("\n".join(scripts))
    results = []
    for index, rule in enumerate(document["rules"]):
        if not rule.get("sql"):
            continue
        at = f"rules[{index}].sql"
        if not scripts:
            results.append(result("rules", "warn", at, "材料包里没有任务 SQL，无法核对这段原文"))
        elif normalize_sql(rule["sql"]) in text:
            results.append(result("rules", "pass", at))
        else:
            results.append(result("rules", "fail", at, (
                f"{rule['sql']!r} 规范化后在任务 SQL 里找不到；照抄 SQL 原文片段，不要改写")))
    return results


def _rule_refs(document: dict) -> list[dict]:
    ids = {rule["id"] for rule in document["rules"]}
    return [
        result("rules", "pass", f"summary.scope[{si}].rule_refs[{ri}]") if ref in ids
        else result("rules", "fail", f"summary.scope[{si}].rule_refs[{ri}]",
                    f"引用了不存在的规则 {ref}；改成 rules 里的编号")
        for si, scope in enumerate(document["summary"]["scope"])
        for ri, ref in enumerate(scope.get("rule_refs") or [])
    ]


# 6 ------------------------------------------------------------------ neighbours


def check_neighbours(document: dict, packet: dict) -> list[dict]:
    """Upstream tables are lineage inputs; downstream tasks (and tables) are known."""
    upstream = set(packet["lineage"]["upstream_tables"])
    results = [
        result("neighbours", "pass", f"summary.upstream[{index}].table")
        if bare_table(item["table"]) in upstream
        else result("neighbours", "fail", f"summary.upstream[{index}].table",
                    f"{item['table']} 不是本表血缘里的输入表；上游只能写材料包 4.4 列出的表")
        for index, item in enumerate(document["summary"]["upstream"])
    ]
    known = {entry["task"]: entry["tables"] for entry in packet["lineage"]["downstream"]}
    for index, item in enumerate(document["summary"]["downstream"]):
        results.append(_downstream(f"summary.downstream[{index}]", item, known))
    return results


def _downstream(at: str, item: dict, known: dict) -> dict:
    task = item["task"]
    if task not in known:
        return result("neighbours", "fail", f"{at}.task",
                      f"下游任务 {task} 既不在血缘里也不在任务登记里；删掉或改成材料包 4.4 的下游")
    if "table" not in item:
        return result("neighbours", "pass", f"{at}.task")
    tables = known[task]
    if bare_table(item["table"]) in tables:
        return result("neighbours", "pass", f"{at}.table")
    if not tables:
        return result("neighbours", "warn", f"{at}.table",
                      f"不知道任务 {task} 写哪些表，无法核对 {item['table']}")
    return result("neighbours", "fail", f"{at}.table",
                  f"任务 {task} 写的是 {'、'.join(tables)}，不是 {item['table']}")


# 7 ------------------------------------------------------------------ sources


def check_sources(document: dict, _packet: dict) -> list[dict]:
    """Every sourced item names at least one source; at most five questions."""
    results = [
        result("sources", "pass" if item.get("sources") else "fail", f"{at}.sources",
               "" if item.get("sources") else "没有来源；写明 comment / sql / sql_comment / metadata / task / inferred")
        for at, item in _sourced_items(document)
    ]
    count = len(document["summary"]["questions"])
    results.append(result("sources", "pass", "summary.questions") if count <= MAX_QUESTIONS else result(
        "sources", "fail", "summary.questions",
        f"待确认问题最多 {MAX_QUESTIONS} 个，现在 {count} 个；合并或删掉次要的"))
    return results


def _sourced_items(document: dict):
    summary = document["summary"]
    yield "summary.row", summary["row"]
    yield "summary.refresh", summary["refresh"]
    for key in ("scope", "upstream"):
        for index, item in enumerate(summary[key]):
            yield f"summary.{key}[{index}]", item
    for ci, column in enumerate(document["columns"]):
        yield f"columns[{ci}]", column
        for vi, code in enumerate(column.get("code_values") or []):
            yield f"columns[{ci}].code_values[{vi}]", code
    for index, rule in enumerate(document["rules"]):
        yield f"rules[{index}]", rule


# 8 ------------------------------------------------------------------ digest


def check_digest(document: dict, packet: dict) -> list[dict]:
    if document["packet_digest"] == packet["packet_digest"]:
        return [result("digest", "pass", "packet_digest")]
    return [result("digest", "fail", "packet_digest", (
        f"stale: 文档按材料包 {document['packet_digest']} 写成，当前材料包是 "
        f"{packet['packet_digest']}；按新材料包重写或核对后更新"))]


def missing_packet(document: dict) -> dict:
    return result("digest", "fail", "packet_digest", (
        f"no packet for {document['table']}: 表名写错了，或还没为它生成材料包"))


# 9 ------------------------------------------------------------------ time


def check_time(document: dict, packet: dict) -> list[dict]:
    """``incremental`` over full snapshots fails; ``snapshot`` over a date window warns."""
    at, time = "summary.refresh.time", document["summary"]["refresh"]["time"]
    inputs = packet["inputs"]
    dated = [f"{item['table']}.{f['column']}：{_plain(f['expression'])}"
             for item in inputs for f in item["date_filters"]]
    if time == "incremental" and inputs and not dated and all(i["full_snapshot"] for i in inputs):
        tables = "、".join(item["table"] for item in inputs)
        return [result("time", "fail", at, (
            f"写了 incremental，但上游 {tables} 都按单一分区取全量快照，且没有按业务日期筛选："
            "每个分区是一份全量，按增量把多个分区相加会重复计数；改成 snapshot，"
            "并在 how_to_read 里写明只取一个分区"))]
    if time == "snapshot" and dated:
        return [result("time", "warn", at, (
            f"写了 snapshot，但写入按业务日期筛选（{'；'.join(dated)}）；确认这张表是不是按日增量"))]
    return [result("time", "pass", at)]
