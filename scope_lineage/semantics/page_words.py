"""The Chinese words a table-semantics page uses for the document's enums, and its marks.

A rendered page never shows an English enum word: every ``role``, ``kind``, ``time`` and
source name is looked up here, so the page, the index and the validation section name a
thing the same way. The marks live here too:

- ✓ -- the item's sources include ``confirmed`` (``semantic confirm`` put it there), or a
  question was answered;
- ⚠ -- the item has its own ``watch`` text, or the summary's ``watch`` list refers to it
  (``column:<name>``, ``rule:<id>``);
- ✗n -- with a validation report, the item failed the page's n-th failed check.
"""

from __future__ import annotations

import re

from ..render.markdown_text import cell, expr_span

CONFIRMED = "confirmed"
TICK = " ✓"
WATCH = "⚠"
NONE = "（无）"

SOURCE_TEXT = {
    "comment": "注释",
    "sql": "SQL",
    "sql_comment": "SQL 注释",
    "metadata": "元数据",
    "task": "任务",
    "inferred": "推断",
    CONFIRMED: "确认",
}
CONFIDENCE_TEXT = {"medium": "中置信", "low": "低置信"}
CYCLE_TEXT = {"daily": "每天", "hourly": "每小时", "weekly": "每周", "monthly": "每月"}
TIME_TEXT = {
    "snapshot": "每个分区是一份**全量快照**",
    "incremental": "每个分区是当期的**增量**",
    "zipper": "**拉链**表，一行是一个有效期窗口",
    "unknown": "时间语义未写明",
}
GRAIN_SOURCE_TEXT = {"declared": "声明", "inferred": "推断", "proven": "已证明"}
UNIQUE_TEXT = {"yes": "全表唯一", "no": "**不能保证唯一**", "unknown": "是否唯一未知"}
ROLE_TEXT = {
    "main": "主表",
    "enrich": "补充字段",
    "filter": "过滤",
    "dedup": "去重",
    "union_branch": "合并分支",
    "lookup": "查码",
    "other": "其他",
}
RULE_KIND_TEXT = {
    "filter": "过滤",
    "join": "关联",
    "dedup": "去重",
    "derive": "派生",
    "union": "合并",
    "other": "其他",
}
WATCH_KIND_TEXT = {
    "conflict": "矛盾",
    "risk": "风险",
    "deprecated": "已废弃",
    "coverage": "覆盖",
    "other": "其他",
}
CHECK_TEXT = {
    "coverage": "字段覆盖",
    "source_columns": "来源列",
    "code_values": "码值",
    "grain": "粒度",
    "rules": "规则",
    "neighbours": "上下游",
    "sources": "来源",
    "digest": "材料包摘要",
    "time": "时间语义",
}
_TERMINAL = "。！？!?.；;…"


def text(value) -> str:
    """Document text for one markdown line: newlines kept literal, pipes escaped.

    A backslash before ``|`` is a plain escape outside a table as well, so one function
    serves paragraphs and table cells alike.
    """
    return cell(str(value).strip())


def code(value) -> str:
    return expr_span(str(value))


def sentence(value) -> str:
    """``value`` ending in sentence punctuation, so a clause can follow it directly."""
    body = text(value)
    return body if not body or body[-1] in _TERMINAL else body + "。"


def clause(value) -> str:
    """``value`` without its closing full stop, to sit inside brackets or a list."""
    return text(value).rstrip("。.")


def cycle_word(cycle) -> str:
    return CYCLE_TEXT.get(str(cycle), str(cycle))


def percent(rate) -> str:
    return f"{rate * 100:.1f}%"


def is_confirmed(item: dict) -> bool:
    return CONFIRMED in (item.get("sources") or [])


def sources_text(item: dict) -> str:
    """``SQL + 注释（中置信）``: where an item came from, and how sure the writer was."""
    labels = [SOURCE_TEXT.get(s, s) for s in item.get("sources") or [] if s != CONFIRMED]
    body = " + ".join(labels) or SOURCE_TEXT[CONFIRMED]
    confidence = CONFIDENCE_TEXT.get(str(item.get("confidence")))
    return f"{body}（{confidence}）" if confidence else body


# ------------------------------------------------------------------ marks

_ITEM = re.compile(
    r"^(?:summary\.)?(?P<key>row|refresh|scope|upstream|downstream|questions|columns|rules)"
    r"(?:\[(?P<index>\d+)\])?"
)
_INDEXED = frozenset({"scope", "upstream", "downstream", "columns", "rules"})
TABLE = "table"


def item_key(at: str) -> str:
    """The page item a report path names: ``columns[3].source_columns[1]`` -> ``columns:3``.

    A path naming no single item (``columns`` for a missing column, ``rules`` for an
    uncited filter, ``packet_digest``) is the table's own, listed in 校验 only.
    """
    match = _ITEM.match(str(at))
    if match is None:
        return TABLE
    key, index = match["key"], match["index"]
    if key not in _INDEXED:
        return key
    return TABLE if index is None else f"{key}:{index}"


class PageMarks:
    """The marks of one page: which items failed validation and which are watched."""

    def __init__(self, document: dict, entry: dict | None) -> None:
        failures = (entry or {}).get("failures") or []
        self.failed = [item for item in failures if item["status"] == "fail"]
        self.warned = [item for item in failures if item["status"] == "warn"]
        self._numbers: dict[str, list[int]] = {}
        for number, item in enumerate(self.failed, 1):
            self._numbers.setdefault(item_key(item["at"]), []).append(number)
        self._watched = {
            ref for watch in document["summary"]["watch"] for ref in watch.get("refs") or []
        }

    def fails(self, key: str) -> str:
        numbers = self._numbers.get(key)
        return f" ✗{'、'.join(map(str, numbers))}" if numbers else ""

    def notes(self, item: dict, ref: str | None = None) -> str:
        """``⚠ <watch>`` (or ``⚠（见要注意）`` when only the summary names it), then ✓."""
        if item.get("watch"):
            watch = f" {WATCH} {text(item['watch'])}"
        elif ref is not None and ref in self._watched:
            watch = f" {WATCH}（见要注意）"
        else:
            watch = ""
        return watch + (TICK if is_confirmed(item) else "")

    def after(self, item: dict, key: str) -> str:
        return self.notes(item) + self.fails(key)


def confirmed_count(document: dict) -> int:
    """How many items a person confirmed: sourced items marked confirmed, answered questions."""
    summary = document["summary"]
    items = [summary["row"], summary["refresh"], *summary["scope"], *summary["upstream"]]
    items += document["rules"]
    for column in document["columns"]:
        items += [column, *(column.get("code_values") or [])]
    answered = sum(1 for question in summary["questions"] if question["status"] == "answered")
    return sum(1 for item in items if is_confirmed(item)) + answered
