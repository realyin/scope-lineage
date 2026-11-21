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

It records and reports. It never edits the catalog or the table semantics, and never
decides what a definition is; a match says where to look, the owner decides.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Optional

from .catalog_search import named_objects
from .catalog_sql_check import placeholders_of
from .catalog_view import catalog_table_name

__all__ = [
    "LIST_FORMAT",
    "PENDING_FORMAT",
    "lines_from_placeholders",
    "pending_line",
    "pending_report",
    "read_pending",
    "render_pending_text",
]

PENDING_FORMAT = "catalog-pending/1"
LIST_FORMAT = "catalog-pending-list/1"
_REQUIRED_TEXT = ("missing", "question", "date")
_LISTS = ("tables", "columns")


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


# --------------------------------------------------------------------- read


def read_pending(lines: Iterable[str]) -> tuple[list[dict], list[dict]]:
    """``(entries, problems)``: each entry with its 1-based ``line``; each problem
    ``{line, message}``. A blank line is neither."""
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


# ------------------------------------------------------------------- report


def pending_report(
    entries: Iterable[Mapping],
    problems: Iterable[Mapping] = (),
    *,
    document: Optional[Mapping] = None,
    semantics: Optional[Mapping[str, Mapping]] = None,
) -> dict:
    """``{doc_format, lines, checked, items, problems}``, the most-hit item first.

    ``recorded_questions`` / ``in_catalog`` are None when the table semantics / the
    ontology were not given, and a list (possibly empty) when they were.
    """
    entries = list(entries)
    groups: dict[str, list[Mapping]] = {}
    for entry in entries:
        groups.setdefault(_same_text(entry["missing"]), []).append(entry)
    documents = (
        {catalog_table_name(name).lower(): doc for name, doc in semantics.items()}
        if semantics is not None else None
    )
    items = [_item(group, document, documents) for group in groups.values()]
    items.sort(key=lambda item: (-item["hits"], item["lines"][0]))
    return {
        "doc_format": LIST_FORMAT,
        "lines": len(entries),
        "checked": {"ontology": document is not None, "semantics": semantics is not None},
        "items": items,
        "problems": list(problems),
    }


def _item(group: list[Mapping], document, documents) -> dict:
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
    if document is not None:
        item["in_catalog"] = named_objects(document, [item["missing"], *terms])
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
        lines.append("")
    for problem in report["problems"]:
        lines.append(f"- 第 {problem['line']} 行读不了：{problem['message']}")
    if report["problems"]:
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"
