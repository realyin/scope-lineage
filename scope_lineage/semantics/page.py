"""``semantic render``: one markdown page per ``table-semantics/1`` document, and an index.

A page follows the layout of a hand-made sample page:

- a title and one line: the domain, the concept the table represents, how many items a
  person has confirmed (and, with a validation report, its pass rate);
- 一页纸 (``page_summary``), 字段 (``page_fields``), 加工过程 (the producing task and the
  steps), 规则（原文） (each rule with its SQL quoted), 来源说明 (what the source words
  and marks mean, and which prompt wrote the page against which packet);
- 校验, last, only when a ``table-semantics-validation/1`` report is given: its pass
  rate and every failure and warning, the failures numbered as the page marks them.

Only the documents (and the optional report and ontology) are read; nothing is guessed.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Optional

from ..render.catalog_concept_page import table_head, table_row
from .checks import CHECKS
from .names import bare_table
from .page_fields import field_lines
from .page_index import IndexRow, render_index
from .page_places import Place, Places
from .page_summary import join_blocks, summary_lines
from .page_words import (
    CHECK_TEXT,
    NONE,
    RULE_KIND_TEXT,
    PageMarks,
    code,
    confirmed_count,
    cycle_word,
    percent,
    text,
)
from .schema import DOC_FORMAT

INDEX_FILENAME = "index.md"
SOURCES_NOTE = (
    "每条内容的来源：注释（表或字段注释）、SQL（加工逻辑）、SQL 注释（作者在 SQL 里写的说明）、"
    "元数据（表结构登记）、任务（任务登记信息）、推断（模型根据以上材料推断）、确认（owner 确认，标 ✓）；"
    "来源后的「中置信」「低置信」是写作者没有把握的条目。⚠ 表示材料之间有矛盾或存在风险；"
    "码值写「含义待确认」的，是材料只给了值、没给含义。"
)
FAILS_NOTE = "✗ 后的编号是校验未通过的条目，见文末「校验」。"


@dataclass(frozen=True)
class PageContext:
    place: Place
    marks: PageMarks
    validated: bool
    entry: Optional[dict]


def page_filename(document: dict) -> str:
    return f"{bare_table(document['table'])}.md"


def render_semantic_pages(
    documents: Iterable[dict], *, validation: Optional[dict] = None, ontology: Optional[dict] = None
) -> dict[str, str]:
    """``{file name: markdown}``: ``index.md`` and ``<db.table>.md`` per document."""
    documents = list(documents)
    for document in documents:
        if document.get("doc_format") != DOC_FORMAT:
            raise ValueError(f"expects {DOC_FORMAT} documents, got {document.get('doc_format')!r}")
    entries = {
        bare_table(entry["table"]): entry
        for entry in (validation or {}).get("tables") or []
        if entry.get("table")
    }
    places = Places(ontology)
    pages, rows = {}, []
    for document in sorted(documents, key=page_filename):
        entry = entries.get(bare_table(document["table"]))
        context = PageContext(
            places.of(document), PageMarks(document, entry), validation is not None, entry
        )
        pages[page_filename(document)] = render_table_page(document, context)
        rows.append(_index_row(document, context))
    return {INDEX_FILENAME: render_index(rows), **pages}


def _index_row(document: dict, context: PageContext) -> IndexRow:
    questions = document["summary"]["questions"]
    return IndexRow(
        table=bare_table(document["table"]),
        filename=page_filename(document),
        what=text(document["summary"]["what"]),
        place=context.place,
        rate=rate_cell(context) if context.validated else "—",
        open_questions=sum(1 for q in questions if q["status"] == "open"),
    )


def rate_cell(context: PageContext) -> str:
    entry = context.entry
    if entry is None:
        return "未校验"
    if entry["schema_errors"]:
        return "Schema 错误"
    return percent(entry["pass_rate"])


def render_table_page(document: dict, context: PageContext) -> str:
    marks = context.marks
    sections = [
        ("一页纸", summary_lines(document, marks)),
        ("字段", field_lines(document, marks)),
        ("加工过程", _process_lines(document)),
        ("规则（原文）", _rule_lines(document, marks)),
        ("来源说明", _sources_lines(document, context)),
    ]
    if context.validated:
        sections.append(("校验", _validation_lines(context)))
    lines = _header(document, context)
    for title, body in sections:
        lines += ["", f"## {title}", "", *body]
    return "\n".join(lines) + "\n"


def _header(document: dict, context: PageContext) -> list[str]:
    parts = [context.place.label]
    if context.place.concept is not None:
        parts.append(context.place.concept.phrase())
    parts.append(f"本页 {confirmed_count(document)} 项已确认，✓ 表示已确认")
    if context.validated:
        parts.append(_rate_phrase(context))
    return [f"# {document['table']}", "", " · ".join(parts)]


def _rate_phrase(context: PageContext) -> str:
    entry = context.entry
    if entry is None or entry["schema_errors"]:
        return f"校验：{rate_cell(context)}"
    failed = len(context.marks.failed)
    tail = f"（{failed} 项未通过，见文末「校验」）" if failed else ""
    return f"校验通过率 {percent(entry['pass_rate'])}{tail}"


def _process_lines(document: dict) -> list[str]:
    tasks = document.get("tasks") or [document["task"]]
    blocks = []
    for task in tasks:
        cycle = f"（{cycle_word(task['cycle'])}）" if task.get("cycle") else ""
        blocks.append([f"**产出任务**：{code(task['name'])}{cycle}：{text(task['purpose'])}"])
    steps = [f"{number}. {text(step)}" for number, step in enumerate(document["steps"], 1)]
    return join_blocks([*blocks, steps])


def _rule_lines(document: dict, marks: PageMarks) -> list[str]:
    if not document["rules"]:
        return [NONE]
    lines = table_head("规则", "业务说法", "SQL 原文")
    for index, rule in enumerate(document["rules"]):
        lines.append(
            table_row(
                f"{rule['id']} {RULE_KIND_TEXT[rule['kind']]}{marks.fails(f'rules:{index}')}",
                text(rule["text"]) + marks.notes(rule, f"rule:{rule['id']}"),
                text(code(rule["sql"])) if rule.get("sql") else "—",
            )
        )
    return lines


def _sources_lines(document: dict, context: PageContext) -> list[str]:
    note = SOURCES_NOTE + (FAILS_NOTE if context.validated else "")
    generator = document.get("generator") or {}
    written = text(generator["prompt"]) if generator.get("prompt") else "（未写明的提示词）"
    if generator.get("model"):
        written += f"（{text(generator['model'])}）"
    return [note, "", f"写作：提示词 {written}；依据材料包 {code(document['packet_digest'])}。"]


def _validation_lines(context: PageContext) -> list[str]:
    entry = context.entry
    if entry is None:
        return ["校验报告里没有这张表。"]
    if entry["schema_errors"]:
        return ["Schema 不通过，没有做交叉检查：", ""] + [
            f"- {code(error['at'] or '(document)')}：{text(error['message'])}"
            for error in entry["schema_errors"]
        ]
    counts, rate = entry["counts"], percent(entry["pass_rate"])
    total = sum(counts.values())
    if not entry["failures"]:
        return [f"通过率 {rate}：{total} 项检查全部通过。"]
    lines = [
        f"通过率 {rate}：{total} 项检查，{counts['fail']} 项未通过、{counts['warn']} 项警告。"
        "页面上 ✗ 后的编号对应下表。",
        "",
        *table_head("标记", "结果", "检查", "位置", "说明"),
    ]
    marks = context.marks
    lines += [_failure_row(f"✗{n}", "未通过", item) for n, item in enumerate(marks.failed, 1)]
    return lines + [_failure_row("—", "警告", item) for item in marks.warned]


def _failure_row(mark: str, status: str, item: dict) -> str:
    check = item["check"]
    number = CHECKS.index(check) + 1 if check in CHECKS else "?"
    label = f"{number} {CHECK_TEXT.get(check, check)}"
    return table_row(mark, status, label, text(code(item["at"])), text(item["message"]))
