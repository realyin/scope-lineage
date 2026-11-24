"""``catalog pending``: definitions an agent found missing, kept for the catalog's owner.

An agent answering a data question meets words the catalog does not define -- which code
values mean a state, what decides a category. It does not guess: it writes the SQL with a
``/* 待确认：… */`` placeholder (see ``scope.sql_placeholders``) and says what is missing.
This module turns each such missing definition into one line of a JSON Lines file
(``catalog-pending/1``) and reads the file back as a report for the owner:

- ``pending_line`` builds one line from what the asker said; ``lines_from_placeholders``
  builds one a placeholder of the facts ``query_facts`` extracted. The date is always
  passed in -- nothing here reads a clock.
- ``read_pending`` reads the lines, keeping each line's number and setting aside the ones
  that are not ``catalog-pending/1`` entries.
- ``pending_report`` groups the entries naming the same missing thing -- equal text after
  NFKC, case folding and collapsing whitespace, nothing fuzzier -- counts the hits and the
  questions behind them, and, when given, marks two things: an open (or answered) question
  a table-semantics document already records about one of the entry's columns, and the
  catalog objects whose own name, synonym, term or id now *is* the entry's text or term.
- ``reply_line`` builds the owner's reply to one group: a line of its own in the same file
  (``kind: reply``), keyed by the same normalised ``missing`` text. A reply is not a hit --
  it adds no question and moves no date; the group's latest reply (by line) gives its
  status, and ``pending_report`` leaves out the groups that reply closed unless asked.

It records and reports. It never edits the catalog or the table semantics, and never
decides what a definition is; a match says where to look, the owner decides.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Optional

from .catalog_search import named_finder
from .catalog_sql_check import placeholders_of
from .catalog_view import catalog_table_name

__all__ = [
    "CLOSED_STATUSES",
    "LIST_FORMAT",
    "LIST_STATUSES",
    "PENDING_FORMAT",
    "REPLY_STATUSES",
    "lines_from_placeholders",
    "pending_line",
    "pending_report",
    "read_pending",
    "render_pending_text",
    "reply_line",
    "reply_text_problem",
    "same_missing",
]

PENDING_FORMAT = "catalog-pending/1"
LIST_FORMAT = "catalog-pending-list/1"
_REQUIRED_TEXT = ("missing", "question", "date")
_LISTS = ("tables", "columns")

REPLY = "reply"
# answered: the owner gave the definition, the catalog does not carry it yet (still listed);
# resolved: the catalog now carries it; rejected: it will not be defined (both close it)
REPLY_STATUSES = ("answered", "resolved", "rejected")
CLOSED_STATUSES = ("resolved", "rejected")
OPEN = "open"  # a group no reply answers
# what ``list --status`` takes: a group's status, ``active`` (not closed: the default) or all
ACTIVE = "active"
LIST_STATUSES = (ACTIVE, OPEN, *REPLY_STATUSES, "all")
REPLY_LIMIT = 2000
BY_LIMIT = 100
_REFUSED = frozenset({"Cc", "Cf", "Cs", "Co", "Zl", "Zp"})


def pending_line(
    *,
    missing: str,
    question: str,
    date: str,
    tables: Iterable[str] = (),
    columns: Iterable[str] = (),
    term: Optional[str] = None,
    proposed: Optional[str] = None,
    source: Optional[Mapping] = None,
) -> dict:
    """One ``catalog-pending/1`` entry. A column's table is listed among the tables; an
    empty optional field is left out."""
    columns = _unique(str(c).strip() for c in columns if str(c).strip())
    tables = _unique(
        [str(t).strip() for t in tables if str(t).strip()]
        + [column.rsplit(".", 1)[0] for column in columns]
    )
    line: dict = {
        "doc_format": PENDING_FORMAT,
        "date": date,
        "missing": missing.strip(),
        "question": question.strip(),
    }
    if term and term.strip():
        line["term"] = term.strip()
    if tables:
        line["tables"] = tables
    if columns:
        line["columns"] = columns
    if proposed and proposed.strip():
        line["proposed"] = proposed.strip()
    if source:
        line["source"] = dict(source)
    return line


def lines_from_placeholders(
    statements: Iterable[Mapping], *, question: str, date: str, sql: str
) -> tuple[list[dict], list[dict]]:
    """``(lines, empty)``: one line a placeholder of the statements' facts, and the
    placeholders that say nothing (``{statement}``), which make no line.

    A placeholder tied to a column concerns that column and its table; one tied to nothing
    concerns every table its statement reads (recorded under ``tables``, no column).
    """
    statements = list(statements)
    reads = {
        s["statement"]: _unique(read["table"] for read in s["reads"]) for s in statements
    }
    lines, empty = [], []
    for placeholder in placeholders_of(statements):
        number = placeholder["statement"]
        if not placeholder["text"].strip():
            empty.append({"statement": number})
            continue
        source: dict = {"sql": sql, "statement": number}
        if placeholder["table"]:
            source["written"] = placeholder["written"]
            column = f"{placeholder['table']}.{placeholder['column']}"
            lines.append(pending_line(
                missing=placeholder["text"], question=question, date=date,
                columns=[column], source=source,
            ))
        else:
            lines.append(pending_line(
                missing=placeholder["text"], question=question, date=date,
                tables=reads.get(number, []), source=source,
            ))
    return lines, empty


def reply_line(
    *, missing: str, reply: str, status: str, date: str, by: Optional[str] = None
) -> dict:
    """One ``catalog-pending/1`` reply: ``missing`` names the group (compared as ``list``
    groups), ``status`` is one of ``REPLY_STATUSES``; ``by`` is left out when empty."""
    line: dict = {
        "doc_format": PENDING_FORMAT,
        "kind": REPLY,
        "date": date,
        "missing": missing.strip(),
        "reply": reply.strip(),
        "status": status,
    }
    if by and by.strip():
        line["by"] = by.strip()
    return line


def reply_text_problem(value: Optional[str], name: str, limit: int) -> Optional[str]:
    """Why ``value`` cannot be written in a reply, or None: blank, longer than ``limit``
    characters, or carrying a line break or a control character."""
    text = (value or "").strip()
    if not text:
        return f"{name} must say something"
    bad = next((char for char in text if unicodedata.category(char) in _REFUSED), None)
    if bad is not None:
        return (
            f"{name} carries a line break or a control character (U+{ord(bad):04X}); "
            "write it on one line"
        )
    if len(text) > limit:
        return f"{name} is {len(text)} characters; at most {limit}"
    return None


def same_missing(text: str) -> str:
    """The key ``list`` groups by: NFKC, case folding, whitespace collapsed."""
    return _same_text(text)


# --------------------------------------------------------------------- read


def read_pending(lines: Iterable[str]) -> tuple[list[dict], list[dict]]:
    """``(entries, problems)``: each entry -- a reply too (``kind: reply``) -- with its
    1-based ``line``; each problem ``{line, message}``. A blank line is neither."""
    entries, problems = [], []
    for number, text in enumerate(lines, 1):
        if not text.strip():
            continue
        try:
            entry = json.loads(text)
        except ValueError as error:
            problems.append({"line": number, "message": f"不是 JSON：{error}"})
            continue
        problem = _problem(entry)
        if problem:
            problems.append({"line": number, "message": problem})
        else:
            entries.append({**entry, "line": number})
    return entries, problems


def _problem(entry) -> Optional[str]:
    if not isinstance(entry, dict):
        return "不是一个 JSON 对象"
    if entry.get("doc_format") != PENDING_FORMAT:
        return f"doc_format 不是 {PENDING_FORMAT}"
    if entry.get("kind") == REPLY:
        return _reply_problem(entry)
    for key in _REQUIRED_TEXT:
        if not isinstance(entry.get(key), str) or not entry[key].strip():
            return f"缺少 {key}，或它不是非空的文字"
    for key in _LISTS:
        value = entry.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            return f"{key} 不是文字的列表"
    for key in ("term", "proposed"):
        if key in entry and not isinstance(entry[key], str):
            return f"{key} 不是文字"
    return None


def _reply_problem(entry: Mapping) -> Optional[str]:
    for key in ("missing", "reply", "date"):
        if not isinstance(entry.get(key), str) or not entry[key].strip():
            return f"回复缺少 {key}，或它不是非空的文字"
    if entry.get("status") not in REPLY_STATUSES:
        return f"回复的 status 不是 {'、'.join(REPLY_STATUSES)} 之一"
    if "by" in entry and not isinstance(entry["by"], str):
        return "回复的 by 不是文字"
    return None


# ------------------------------------------------------------------- report


def pending_report(
    entries: Iterable[Mapping],
    problems: Iterable[Mapping] = (),
    *,
    document: Optional[Mapping] = None,
    semantics: Optional[Mapping[str, Mapping]] = None,
    status: str = ACTIVE,
) -> dict:
    """``{doc_format, lines, checked, items, problems}``, the most-hit item first.

    ``recorded_questions`` / ``in_catalog`` are None when the table semantics / the
    ontology were not given, and a list (possibly empty) when they were.

    Replies (``kind: reply``) are not entries: ``lines`` counts the entries. When there is
    a reply or ``status`` names a reply's status, the report also has ``replies`` (how many
    reply lines were read), ``status`` (the filter) and ``closed`` (the groups a reply
    closed that the filter left out), and every item ``status`` (``open`` when no reply
    answers it) and ``reply`` (its latest, or None); a reply naming no group is a problem.
    ``status`` is one of ``LIST_STATUSES``: ``active`` lists every group not closed,
    ``all`` every group, any other only the groups of that status.
    """
    if status not in LIST_STATUSES:
        raise ValueError(f"status must be one of {', '.join(LIST_STATUSES)}, not {status!r}")
    entries = list(entries)
    replies = [entry for entry in entries if entry.get("kind") == REPLY]
    entries = [entry for entry in entries if entry.get("kind") != REPLY]
    problems = list(problems)
    groups: dict[str, list[Mapping]] = {}
    for entry in entries:
        groups.setdefault(_same_text(entry["missing"]), []).append(entry)
    latest: dict[str, Mapping] = {}
    for reply in sorted(replies, key=lambda r: r["line"]):
        key = _same_text(reply["missing"])
        if key in groups:
            latest[key] = reply
        else:
            problems.append({"line": reply["line"], "message": "回复的 missing 没有对应的记录"})
    if replies:
        problems.sort(key=lambda problem: problem["line"])
    documents = (
        {catalog_table_name(name).lower(): doc for name, doc in semantics.items()}
        if semantics is not None else None
    )
    find = named_finder(document) if document is not None else None
    items = []
    for key, group in groups.items():
        item = _item(group, find, documents)
        reply = latest.get(key)
        items.append((item, reply))
    items.sort(key=lambda pair: (-pair[0]["hits"], pair[0]["lines"][0]))
    report = {
        "doc_format": LIST_FORMAT,
        "lines": len(entries),
        "checked": {"ontology": document is not None, "semantics": semantics is not None},
        "items": [item for item, _ in items],
        "problems": problems,
    }
    if not replies and status not in REPLY_STATUSES:
        return report  # a file without replies reads exactly as it always did
    for item, reply in items:
        item["status"] = reply["status"] if reply else OPEN
        item["reply"] = _reply_of(reply) if reply else None
    shown = [item for item, _ in items if _wanted(item["status"], status)]
    report.update(
        replies=len(replies),
        status=status,
        closed=sum(
            1 for item, _ in items
            if item["status"] in CLOSED_STATUSES and not _wanted(item["status"], status)
        ),
        items=shown,
    )
    return report


def _wanted(item_status: str, wanted: str) -> bool:
    if wanted == "all":
        return True
    if wanted == ACTIVE:
        return item_status not in CLOSED_STATUSES
    return item_status == wanted


def _reply_of(reply: Mapping) -> dict:
    shown = {"reply": reply["reply"].strip(), "status": reply["status"]}
    if isinstance(reply.get("by"), str) and reply["by"].strip():
        shown["by"] = reply["by"].strip()
    shown.update(date=reply["date"], line=reply["line"])
    return shown


def _item(group: list[Mapping], find, documents) -> dict:
    dates = sorted(entry["date"] for entry in group)
    columns = _unique(c for entry in group for c in entry.get("columns") or [])
    terms = _unique(entry["term"].strip() for entry in group if entry.get("term"))
    item = {
        "missing": group[0]["missing"].strip(),
        "hits": len(group),
        "questions": _unique(entry["question"].strip() for entry in group),
        "terms": terms,
        "tables": _unique(t for entry in group for t in entry.get("tables") or []),
        "columns": columns,
        "proposed": _unique(entry["proposed"].strip() for entry in group if entry.get("proposed")),
        "dates": {"first": dates[0], "last": dates[-1]},
        "lines": [entry["line"] for entry in group],
        "recorded_questions": None,
        "in_catalog": None,
    }
    if documents is not None:
        item["recorded_questions"] = _recorded_questions(columns, documents)
    if find is not None:
        item["in_catalog"] = find([item["missing"], *terms])
    return item


def _recorded_questions(columns: list[str], documents: Mapping) -> list[dict]:
    """The questions a table's semantics document records ``about`` one of the columns."""
    found = []
    for address in columns:
        if address.count(".") < 2:
            continue
        table, column = address.rsplit(".", 1)
        document = documents.get(catalog_table_name(table).lower())
        if not document:
            continue
        tag = f"column:{column}".casefold()
        for question in (document.get("summary") or {}).get("questions") or []:
            if tag in {str(ref).casefold() for ref in question.get("about") or []}:
                entry = {
                    "table": document.get("table") or table,
                    "id": question.get("id"),
                    "text": question.get("text"),
                    "status": question.get("status"),
                    "about": list(question.get("about") or []),
                }
                if entry not in found:
                    found.append(entry)
    return found


def _same_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _unique(values: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


# --------------------------------------------------------------------- text


_KIND_TEXT = {
    "concept": "概念", "metric": "指标", "attribute": "属性", "identifier": "标识",
    "code_set": "码值集", "table": "表",
}


def render_pending_text(report: Mapping) -> str:
    """One block an item, most hit first, then the lines that could not be read."""
    items = report["items"]
    lines = [f"# 待确认的定义：{report['lines']} 条记录，{len(items)} 项", ""]
    if "status" in report:
        lines += [_filter_line(report), ""]
    if not items:
        lines += ["没有待确认的定义。", ""]
    for number, item in enumerate(items, 1):
        lines.append(f"## {number}. {item['missing']}（{item['hits']} 次）")
        lines.append(f"- 问到它的问题：{'；'.join(item['questions'])}")
        if item["terms"]:
            lines.append(f"- 业务词：{'、'.join(item['terms'])}")
        concerns = item["columns"] or item["tables"]
        if concerns:
            lines.append(f"- 涉及：{'、'.join(concerns)}")
        for proposed in item["proposed"]:
            lines.append(f"- 提议的定义：{proposed}")
        dates = item["dates"]
        span = dates["first"] if dates["first"] == dates["last"] else f"{dates['first']} 至 {dates['last']}"
        lines.append(f"- 记录日期：{span}（第 {'、'.join(str(n) for n in item['lines'])} 行）")
        if item["recorded_questions"] is not None:
            if not item["columns"]:
                lines.append("- 表语义：这一项没有指明列，无法对照已记录的问题")
            elif item["recorded_questions"]:
                for question in item["recorded_questions"]:
                    lines.append(
                        f"- 表语义已记录的问题：{question['table']} {question['id']}"
                        f"（{question['status']}）{question['text']}"
                    )
            else:
                lines.append("- 表语义没有记录同一列的问题")
        if item["in_catalog"] is not None:
            if item["in_catalog"]:
                found = "；".join(
                    f"[{_KIND_TEXT.get(o['kind'], o['kind'])}] {o['name']} {o['id']}"
                    for o in item["in_catalog"]
                )
                lines.append(f"- 目录现在有同名对象（核对是否已回答）：{found}")
            else:
                lines.append("- 目录还没有同名对象")
        if "status" in item:
            lines.append(_reply_text(item))
        lines.append("")
    for problem in report["problems"]:
        lines.append(f"- 第 {problem['line']} 行读不了：{problem['message']}")
    if report["problems"]:
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


_STATUS_TEXT = {
    OPEN: "未回复", "answered": "已答复", "resolved": "已解决", "rejected": "不予定义",
    ACTIVE: "未关闭", "all": "全部",
}


def _filter_line(report: Mapping) -> str:
    line = f"列出：{_STATUS_TEXT[report['status']]}（{report['replies']} 条回复）"
    if report["closed"]:
        line += f"；另有 {report['closed']} 项已关闭，--status all 列出全部"
    return line


def _reply_text(item: Mapping) -> str:
    reply = item["reply"]
    if reply is None:
        return f"- 状态：{_STATUS_TEXT[OPEN]}"
    who = f"，{reply['by']}" if reply.get("by") else ""
    return (
        f"- 状态：{_STATUS_TEXT[reply['status']]}（{reply['date']}{who}，第 {reply['line']} 行）"
        f"：{reply['reply']}"
    )
