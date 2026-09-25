"""Cross checks 12-13: what the material already says, passed on to the reader.

- 12 ``documented_meaning`` -- a value whose meaning a column comment spells out is not
  a question (fail); a distinctive qualifier of the upstream -- 增值税, 手续费, 测试 ... --
  that the target's own comments drop must reach the summary or the columns it affects
  (warn);
- 13 ``header_facts`` -- a lifecycle or data volume the script header states belongs in
  how the table is read (warn).
"""

from __future__ import annotations

import re

from .checks import result, source_comments
from .comment_values import listed_labels, value_labels
from .names import bare_table

# 12 ------------------------------------------------------------------ documented meaning

# Qualifiers that change what a number or a row means. Kept short on purpose: every term
# here is one a reader would misread the table without. Pass ``terms`` to use another list.
QUALIFIER_TERMS = ("增值税", "税", "手续费", "罚息", "冲正", "测试")
PENDING = "待确认"


def check_documented_meaning(
    document: dict, packet: dict, terms: tuple[str, ...] = QUALIFIER_TERMS
) -> list[dict]:
    """No 待确认 for a value a comment explains; upstream qualifiers reach the page."""
    sql = "\n".join(task["sql"] or "" for task in packet["tasks"])
    results = []
    for ci, column in enumerate(document["columns"]):
        comments = _comments(packet, column["column"])
        for vi, code in enumerate(column.get("code_values") or []):
            if code.get("unconfirmed") or PENDING in code["meaning"]:
                results.append(_documented(f"columns[{ci}].code_values[{vi}]", code, comments, sql))
    return results + _qualifiers(document, packet, terms)


def _comments(packet: dict, name: str) -> list[str]:
    target = [c["comment"] for c in packet["target"]["columns"] if c["name"] == name and c["comment"]]
    return target + [comment for _, comment in source_comments(packet, name)]


def _documented(at: str, code: dict, comments: list[str], sql: str) -> dict:
    value = str(code["value"]).strip()
    for comment in comments:
        label = value_labels(comment).get(value)
        if label is None and value in listed_labels(comment) and _quoted_in(value, sql):
            label = value
        if label and PENDING in label and not code.get("unconfirmed"):
            break  # the state is literally 待确认, and the document says so
        if label:
            return result("documented_meaning", "fail", at, (
                f"码值 {value!r} 标成了待确认，但注释已写明它的含义：「{comment}」"
                f"（{value} = {label}）；meaning 写「{label}」，sources 写 comment，去掉 "
                "unconfirmed，并删掉就此提的问题"))
    return result("documented_meaning", "pass", at)


def _quoted_in(value: str, sql: str) -> bool:
    return f"'{value}'" in sql or f'"{value}"' in sql


def _qualifiers(document: dict, packet: dict, terms: tuple[str, ...]) -> list[dict]:
    """One item per qualifier of a main input, then one per qualifier of the source columns."""
    target = packet["target"]
    known = "\n".join([target["comment"] or ""] + [c["comment"] or "" for c in target["columns"]])
    everything = _column_text(document, document["columns"])
    results = [
        _qualifier("summary.what", term, f"上游主表 {table}", comment, term in everything,
                   "summary.what（或相关列的 meaning / derivation）")
        for table, comment in _main_comments(document, packet)
        for term in _distinct_terms(comment, terms, known)
    ]
    found = _source_terms(document, packet, terms, known)
    return results + [_column_qualifier(document, term, hits) for term, hits in found.items()]


def _source_terms(document: dict, packet: dict, terms: tuple[str, ...], known: str) -> dict:
    """``term -> [(column index, source column, comment)]``, one entry per target column."""
    found: dict[str, list[tuple[int, str, str]]] = {}
    for ci, column in enumerate(document["columns"]):
        for source, comment in source_comments(packet, column["column"]):
            for term in _distinct_terms(comment, terms, known):
                hits = found.setdefault(term, [])
                if not hits or hits[-1][0] != ci:
                    hits.append((ci, source, comment))
    return found


def _column_qualifier(document: dict, term: str, hits: list[tuple[int, str, str]]) -> dict:
    columns = [document["columns"][ci] for ci, _, _ in hits]
    names = "、".join(column["column"] for column in columns[:6])
    names += f" 等 {len(columns)} 列" if len(columns) > 6 else ""
    first, source, comment = hits[0]
    return _qualifier(f"columns[{first}]", term, f"来源列 {source}", comment,
                      term in _column_text(document, columns),
                      f"列 {names} 的 meaning 或 derivation（或 summary.what）")


def _main_comments(document: dict, packet: dict) -> list[tuple[str, str]]:
    """``(table, comment)`` of each main input: the packet's driving ones and the document's."""
    main = {bare_table(item["table"]) for item in document["summary"]["upstream"] if item["role"] == "main"}
    return [
        (item["table"], item["comment"])
        for item in packet["inputs"]
        if item["comment"] and (item["driving"] or item["table"] in main)
    ]


def _distinct_terms(comment: str, terms: tuple[str, ...], known: str) -> list[str]:
    """The terms in ``comment`` the target's comments lack, a term inside a longer one once."""
    found = [term for term in terms if term in comment and term not in known]
    return [term for term in found if not any(term != other and term in other for other in found)]


def _column_text(document: dict, columns: list[dict]) -> str:
    parts = [document["summary"]["what"]]
    for column in columns:
        parts += [column["meaning"], column.get("derivation") or ""]
        parts += [branch["text"] for branch in column.get("branches") or []]
    return "\n".join(parts)


def _qualifier(at: str, term: str, where: str, comment: str, said: bool, place: str) -> dict:
    if said:
        return result("documented_meaning", "pass", at)
    return result("documented_meaning", "warn", at, (
        f"{where} 的注释带有限定「{term}」（「{comment}」），目标表的注释里没有；在 {place} "
        f"里写明「{term}」，不要把它写成一般口径"))


# 13 ------------------------------------------------------------------ header facts

_LIFECYCLE_SAID = re.compile(r"生命周期|lifecycle|保留[^。；;]{0,8}\d+天|永久保留|保留永久", re.IGNORECASE)
_VOLUME_SAID = re.compile(r"数据规模|数据量|量级")


def check_header_facts(document: dict, packet: dict) -> list[dict]:
    """A lifecycle or volume the SQL header states is in how_to_read or a watch."""
    refresh, summary = document["summary"]["refresh"], document["summary"]
    texts = [refresh["how_to_read"], refresh.get("watch") or ""] + [w["text"] for w in summary["watch"]]
    said = re.sub(r"\s+", "", "\n".join(texts)).lower()
    stated: dict[tuple[str, str], str] = {}
    for task in packet["tasks"]:
        facts = task.get("header_facts") or {}
        for key in ("lifecycle", "volume"):
            if facts.get(key):
                stated.setdefault((key, facts[key]), task["name"])
    at = "summary.refresh.how_to_read"
    results = []
    for (key, value), task in stated.items():
        pattern = _LIFECYCLE_SAID if key == "lifecycle" else _VOLUME_SAID
        if value.lower() in said or pattern.search(said):
            results.append(result("header_facts", "pass", at))
        else:
            results.append(result("header_facts", "warn", at, _header_hint(key, value, task)))
    return results


def _header_hint(key: str, value: str, task: str) -> str:
    if key == "volume":
        return (f"任务 {task} 的 SQL 头注释写明数据规模 {value}；在 summary.refresh.how_to_read 或"
                f"一条 summary.watch 里写明量级（约 {value}），方便读者估算取数代价")
    keep = "分区永久保留，历史日期都能取到" if value in ("永久", "永远") else (
        f"分区只保留最近 {value}，更早的日期取不到")
    return (f"任务 {task} 的 SQL 头注释写明生命周期 {value}；在 summary.refresh.how_to_read 或"
            f"一条 summary.watch 里写明{keep}")
