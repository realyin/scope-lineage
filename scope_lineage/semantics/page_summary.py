"""一页纸: the nine things a reader of one table asks, in the order they ask them.

这张表是什么 · 一行是什么 · 更新与取数 · 收哪些数据 · 数据从哪来 · 谁在用 · 适合用来/不适合 ·
要注意 · 待确认问题 -- one bold label each, a paragraph, a bullet list or a two-column table
under it. A reader who stops here can already use the table.
"""

from __future__ import annotations

from ..render.catalog_concept_page import table_head, table_row
from .page_words import (
    GRAIN_SOURCE_TEXT,
    NONE,
    ROLE_TEXT,
    TICK,
    TIME_TEXT,
    UNIQUE_TEXT,
    WATCH_KIND_TEXT,
    PageMarks,
    code,
    cycle_word,
    sentence,
    text,
)


def summary_lines(document: dict, marks: PageMarks) -> list[str]:
    summary = document["summary"]
    row, refresh = summary["row"], summary["refresh"]
    blocks = [
        [f"**这张表是什么**：{text(summary['what'])}"],
        [f"**一行是什么**：{_row_text(row)}{marks.after(row, 'row')}"],
        [f"**更新与取数**：{_refresh_text(refresh)}{marks.after(refresh, 'refresh')}"],
        _scope(summary["scope"], marks),
        _upstream(summary["upstream"], marks),
        [f"**谁在用**：{_downstream(summary['downstream'], marks)}"],
        [_uses("适合用来", summary["good_for"]), _uses("不适合", summary["not_for"])],
        _watch(summary["watch"]),
        _questions(summary["questions"], marks),
    ]
    return join_blocks(blocks)


def join_blocks(blocks: list[list[str]]) -> list[str]:
    lines: list[str] = []
    for block in (b for b in blocks if b):
        lines += ["", *block] if lines else block
    return lines


def _row_text(row: dict) -> str:
    grain = " + ".join(code(column) for column in row["grain_columns"])
    body = sentence(row["text"]) + (f"粒度按 {grain}" if grain else "粒度未写明")
    body += f"，来源为{GRAIN_SOURCE_TEXT[row['grain_source']]}，{UNIQUE_TEXT[row['unique']]}。"
    return body + (sentence(row["note"]) if row.get("note") else "")


def _refresh_text(refresh: dict) -> str:
    return (
        f"{cycle_word(refresh['cycle'])}跑一次，{TIME_TEXT[refresh['time']]}。"
        f"{sentence(refresh['how_to_read'])}"
    )


def _scope(items: list[dict], marks: PageMarks) -> list[str]:
    if not items:
        return [f"**收哪些数据**：{NONE}"]
    lines = ["**收哪些数据**：", ""]
    for index, item in enumerate(items):
        refs = "、".join(text(ref) for ref in item.get("rule_refs") or [])
        cited = f"（规则 {refs}）" if refs else ""
        lines.append(f"- {sentence(item['text'])}{cited}{marks.after(item, f'scope:{index}')}")
    return lines


def _upstream(items: list[dict], marks: PageMarks) -> list[str]:
    if not items:
        return [f"**数据从哪来**：{NONE}"]
    lines = ["**数据从哪来**：", "", *table_head("上游表", "在本表的作用")]
    for index, item in enumerate(items):
        lines.append(
            table_row(
                f"{code(item['table'])}（{ROLE_TEXT[item['role']]}）"
                + marks.fails(f"upstream:{index}"),
                text(item["provides"]) + marks.notes(item),
            )
        )
    return lines


def _downstream(items: list[dict], marks: PageMarks) -> str:
    if not items:
        return "材料里没有下游任务。"
    parts = []
    for index, item in enumerate(items):
        writes = f"（写 {code(item['table'])}）" if item.get("table") else ""
        parts.append(f"{code(item['task'])}{writes}{marks.fails(f'downstream:{index}')}")
    return "下游任务 " + "、".join(parts) + "。"


def _uses(label: str, items: list[str]) -> str:
    return f"**{label}**：" + ("；".join(text(item) for item in items) or NONE)


def _watch(items: list[dict]) -> list[str]:
    if not items:
        return [f"**要注意**：{NONE}"]
    bullets = [f"- {text(item['text'])}（{WATCH_KIND_TEXT[item['kind']]}）" for item in items]
    return ["**要注意**：", "", *bullets]


def _questions(items: list[dict], marks: PageMarks) -> list[str]:
    label = f"**待确认问题**：{marks.fails('questions').strip()}"
    if not items:
        return [label + NONE]
    lines = [label, ""]
    for number, question in enumerate(items, 1):
        lines.append(f"{number}. {text(question['text'])}（{question['id']}）{_answer(question)}")
    return lines


def _answer(question: dict) -> str:
    if question["status"] != "answered":
        return ""
    who = "，".join(
        text(question[key]) for key in ("answered_by", "answered_on") if question.get(key)
    )
    answer = f" 回答：{text(question['answer'])}" if question.get("answer") else " 已回答"
    return TICK + answer + (f"（{who}）" if who else "")
