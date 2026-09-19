"""``glossary.md``: the human rendering of the corpus term / value dictionary.

One section per column name, because the column name is what a reader has in hand when
they ask the question. Inside a section: the comments the warehouse carries for that
name (merged, with conflicts marked), the values the corpus's SQL compares it against,
and the parameterised predicates that pin it without giving it a value.

The meaning column is a three-state answer and says which state it is in: ``✓`` for a
human-confirmed meaning, ``?`` for a comment that literally spells the value out, and
"待确认" for everything else. Nothing here upgrades a ``?`` to a ``✓``.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .glossary_values import displayed_value
from .markdown_text import cell, expr_span, normalize_inline


CONFIRMED_MARK = "✓"
CANDIDATE_MARK = "?"
UNCONFIRMED_TEXT = "待确认"
CONFLICT_MARK = "⚠"
EMPTY_CELL = "—"

# `列引用` is the one column the WI-2.4 brief's table did not list, and it has to be
# here: a section is one column NAME, and one name can belong to nine tables. Without it
# two rows reading `1` / `literal` / `1` are indistinguishable.
_VALUE_TABLE_HEADER = (
    "| 值 | 列引用 | 种类 | 出现任务数 | 上下文 | 封闭集 | 含义 |",
    "| --- | --- | --- | --- | --- | --- | --- |",
)


def render_glossary_markdown(glossary: Mapping) -> str:
    """Render one ``glossary-json/1`` document. Same input, same bytes."""
    lines = ["# 术语与值域字典", *_summary(glossary)]
    sections = _sections(glossary)
    for column in sorted(sections):
        lines.extend(_render_column(column, sections[column]))
    lines.extend(_bare_columns_line(glossary, sections))
    return "\n".join(lines) + "\n"


def _summary(glossary: Mapping) -> list[str]:
    corpus = glossary.get("corpus") or {}
    values = glossary.get("values") or []
    terms = glossary.get("terms") or []
    applied = glossary.get("overrides_applied") or {}
    return [
        "",
        f"- 语料根目录：{expr_span(str(corpus.get('artifact_root') or ''))}；"
        f"任务 {corpus.get('task_count')} 个，写语句 {corpus.get('statement_count')} 条。",
        f"- 术语 {len(terms)} 个（注释冲突 "
        f"{sum(1 for term in terms if term.get('conflict'))} 个）；"
        f"值域观察 {len(values)} 条（封闭集 "
        f"{sum(1 for item in values if item.get('closed_set'))} 条，含义候选 "
        f"{sum(1 for item in values if item.get('meaning_candidates'))} 条）；"
        f"参数化值 {len(glossary.get('parameters') or [])} 条。",
        f"- 人工确认（overrides）：术语 {applied.get('terms', 0)} 条、值 "
        f"{applied.get('values', 0)} 条生效；未命中键 "
        f"{len(applied.get('unmatched') or [])} 个。",
        f"- 含义只有两个来源：人工确认（{CONFIRMED_MARK}）与注释里字面出现该值"
        f"（{CANDIDATE_MARK} 候选）；其余一律写「{UNCONFIRMED_TEXT}」，Core 不猜。",
        *_unmatched_line(applied),
    ]


def _unmatched_line(applied: Mapping) -> list[str]:
    unmatched = applied.get("unmatched") or []
    if not unmatched:
        return []
    return [
        f"- {CONFLICT_MARK} overrides 里有 {len(unmatched)} 个键在本语料中没有对应项："
        + "、".join(expr_span(str(key)) for key in unmatched)
    ]


def _sections(glossary: Mapping) -> dict[str, dict]:
    """``column -> {term, values, parameters}`` for every column worth a section."""
    sections: dict[str, dict] = {}
    for term in glossary.get("terms") or []:
        if term.get("comments") or term.get("meaning"):
            sections.setdefault(str(term["column"]), {})["term"] = term
    for value in glossary.get("values") or []:
        sections.setdefault(str(value["column"]), {}).setdefault("values", []).append(value)
    for parameter in glossary.get("parameters") or []:
        column = str(parameter["column_ref"]).rsplit(".", 1)[-1]
        sections.setdefault(column, {}).setdefault("parameters", []).append(parameter)
    for term in glossary.get("terms") or []:
        column = str(term["column"])
        if column in sections:
            sections[column]["term"] = term
    return sections


def _render_column(column: str, section: Mapping) -> list[str]:
    lines = ["", f"## {column}", ""]
    lines.extend(_term_lines(section.get("term")))
    values = section.get("values") or []
    if values:
        lines.extend(["", *_VALUE_TABLE_HEADER])
        lines.extend(_value_row(value) for value in values)
    for parameter in section.get("parameters") or []:
        lines.append(
            f"- 参数化值：{expr_span(str(parameter['expression']))}"
            f"（{parameter['kind']}，{parameter['task_count']} 个任务，"
            f"来自 {expr_span(str(parameter['column_ref']))}）"
        )
    return lines


def _term_lines(term: Mapping | None) -> list[str]:
    if term is None:
        return ["- 术语：本语料的元数据里没有这个列。"]
    lines = [_comment_line(term)]
    if term.get("conflict"):
        lines.append(
            f"- {CONFLICT_MARK} 注释冲突：{len(term.get('comments') or [])} 种不同说法，"
            "字典并列保留，不替作者裁决。"
        )
    missing = term.get("tables_without_comment") or []
    if missing:
        lines.append(
            f"- 缺列注释的表（{len(missing)}/{term.get('tables_total')}）："
            + "、".join(expr_span(str(name)) for name in missing)
        )
    lines.append(f"- 列含义：{_meaning_text(term.get('meaning'), ())}")
    return lines


def _comment_line(term: Mapping) -> str:
    comments = term.get("comments") or []
    if not comments:
        return f"- 术语：{term.get('tables_total')} 张表有这个列，没有一张写了列注释。"
    rendered = "；".join(
        f"{normalize_inline(str(item['text']))}"
        f"（{item['count']} 张表：" + "、".join(expr_span(str(name)) for name in item["tables"]) + "）"
        for item in comments
    )
    return f"- 术语（{term.get('tables_total')} 张表）：{rendered}"


def _value_row(value: Mapping) -> str:
    contexts = sorted({str(item["context"]) for item in value.get("observations") or []})
    reference = cell(expr_span(str(value["column_ref"])))
    if value.get("logical"):
        reference += "（scope 级）"
    return (
        f"| {cell(expr_span(displayed_value(value)))} | {reference} | {value['kind']} "
        f"| {value['task_count']} | {cell('、'.join(contexts))} "
        f"| {_closed_set_text(value.get('closed_set'))} "
        f"| {cell(_meaning_text(value.get('meaning'), value.get('meaning_candidates') or []))} |"
    )


def _closed_set_text(closed_set: Mapping | None) -> str:
    if not closed_set:
        return EMPTY_CELL
    values = "、".join(expr_span(str(item)) for item in closed_set.get("values") or [])
    return cell(f"{closed_set.get('basis')}：{values}")


def _meaning_text(meaning: Mapping | None, candidates: Sequence[Mapping]) -> str:
    if meaning:
        confirmed_by = meaning.get("confirmed_by")
        date = meaning.get("date")
        suffix = "，".join(str(item) for item in (confirmed_by, date) if item)
        text = f"{CONFIRMED_MARK} {normalize_inline(str(meaning.get('text') or ''))}"
        return f"{text}（{suffix}）" if suffix else text
    if candidates:
        return f"{CANDIDATE_MARK} " + "；".join(
            f"{normalize_inline(str(item['text']))}（{item['source']}）" for item in candidates
        )
    return UNCONFIRMED_TEXT


def _bare_columns_line(glossary: Mapping, sections: Mapping) -> list[str]:
    bare = [
        term for term in glossary.get("terms") or [] if str(term["column"]) not in sections
    ]
    if not bare:
        return []
    return [
        "",
        "## 其余列",
        "",
        f"- 另有 {len(bare)} 个列名在本语料里既没有列注释，也没有被任何常量比较过，"
        "本字典只记录它们的存在：" + "、".join(expr_span(str(term["column"])) for term in bare),
    ]
