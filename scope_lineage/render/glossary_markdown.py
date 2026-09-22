"""``glossary.md``: the human rendering of the corpus term / value dictionary.

One section per column name, because the column name is what a reader has in hand when
they ask the question. Inside a section: the comments the warehouse carries for that
name (merged, with conflicts marked), the values the corpus's SQL compares it against,
and the parameterised predicates that pin it without giving it a value.

The meaning column is a three-state answer and says which state it is in: ``✓`` for a
human-confirmed meaning, ``?`` for a comment that literally spells the value out, and
"待确认" for everything else. Nothing here upgrades a ``?`` to a ``✓``.

N6 puts one section in front of the column sections when the dictionary was built with
``--ontology``: 「按概念」, one row per concept ATTRIBUTE. It is the same facts read the
other way round -- not "what does this column name mean" but "what does this concept
call this thing, and how much of it has anybody answered" -- and it is the table a
reviewer reads to decide which single ``concept:<id>.<attribute>=<value>`` key to write.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .glossary_values import displayed_value
from .markdown_text import cell, expr_span, normalize_inline, sql_alias_note


CONFIRMED_MARK = "✓"
CANDIDATE_MARK = "?"
UNCONFIRMED_TEXT = "待确认"
CONFLICT_MARK = "⚠"
EMPTY_CELL = "—"

# P5. What a confirmed meaning was confirmed ON, printed beside who signed it.
BASIS_PREFIX = "依据："

# `列引用` is the one column the WI-2.4 brief's table did not list, and it has to be
# here: a section is one column NAME, and one name can belong to nine tables. Without it
# two rows reading `1` / `literal` / `1` are indistinguishable.
_VALUE_TABLE_HEADER = (
    "| 值 | 列引用 | 种类 | 出现任务数 | 上下文 | 封闭集 | 含义 |",
    "| --- | --- | --- | --- | --- | --- | --- |",
)

# N6. The concept layer, printed before the column sections because it is the coarser
# reading of the same facts: one row per concept attribute, however many tables write it.
_CONCEPT_TITLE = "## 按概念"
_CONCEPT_NOTE = (
    "- 概念层来自 `--ontology`：{concepts} 个概念、{attributes} 个属性，其中 {spanning} 个"
    "属性跨 ≥ 2 张表。一个属性在它的各张表示表上是同一件事，overrides 里写一条"
    " `concept:<概念 id>.<属性>=<取值>` 就答完整族；只落在一张表上的属性（表数 1）"
    "照常列出，但一条概念键对它而言并不比表级键多答什么。"
)
# N6b: 临时概念（每张放不进任何键的表都会有一个）不进这一层，否则它就是列层换了个长名字。
_CONCEPT_PROVISIONAL_NOTE = "- 临时概念（`tier: provisional`）不进本节：它只代表一张表，没有多说任何事。"
_CONCEPT_TABLE_HEADER = (
    "| 概念 | 属性 | 表数 | 列 | 术语 | 取值（已确认 / 共计） |",
    "| --- | --- | --- | --- | --- | --- |",
)


def render_glossary_markdown(glossary: Mapping) -> str:
    """Render one ``glossary-json/1`` document. Same input, same bytes."""
    lines = ["# 术语与值域字典", *_summary(glossary), *_concept_section(glossary)]
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
        f"- 含义只有两个来源：人工确认（{CONFIRMED_MARK}）与语料自己写下的候选"
        f"（{CANDIDATE_MARK}：注释里字面出现或枚举该值，或 CASE 把它标成某个标签）；"
        f"其余一律写「{UNCONFIRMED_TEXT}」，Core 不猜。",
        *_unmatched_line(applied),
        *_rejected_line(applied),
    ]


def _unmatched_line(applied: Mapping) -> list[str]:
    unmatched = applied.get("unmatched") or []
    if not unmatched:
        return []
    return [
        f"- {CONFLICT_MARK} overrides 里有 {len(unmatched)} 个键在本语料中没有对应项："
        + "、".join(expr_span(str(key)) for key in unmatched)
    ]


def _rejected_line(applied: Mapping) -> list[str]:
    """P5: a confirmation this run refused, and why. Silence would publish it as unasked."""
    rejected = applied.get("rejected") or []
    ignored = applied.get("ignored_fields") or []
    lines = []
    if rejected:
        lines.append(
            f"- {CONFLICT_MARK} overrides 里有 {len(rejected)} 条确认被拒绝，未写入："
            + "、".join(
                f"{expr_span(str(item.get('key')))}（{item.get('reason')}）"
                for item in rejected
            )
        )
    if ignored:
        lines.append(
            f"- {CONFLICT_MARK} overrides 里有 {len(ignored)} 条确认带本版本读不懂的字段："
            + "、".join(
                f"{expr_span(str(item.get('key')))}（"
                + "、".join(str(field) for field in item.get("fields") or [])
                + "）"
                for item in ignored
            )
        )
    return lines


def _concept_section(glossary: Mapping) -> list[str]:
    """N6's 「按概念」 table, or nothing at all when no ontology was read."""
    concepts = glossary.get("concept_terms") or []
    if not concepts:
        return []
    summary = glossary.get("concept_terms_summary") or {}
    return [
        "",
        _CONCEPT_TITLE,
        "",
        _CONCEPT_NOTE.format(
            concepts=summary.get("concepts", 0),
            attributes=summary.get("attributes", 0),
            spanning=summary.get("attributes_spanning_multiple_tables", 0),
        ),
        _CONCEPT_PROVISIONAL_NOTE,
        "",
        *_CONCEPT_TABLE_HEADER,
        *[_concept_row(item) for item in concepts],
    ]


def _concept_row(entry: Mapping) -> str:
    columns = "、".join(
        expr_span(f"{item['table']}.{item['column']}")
        for item in entry.get("columns") or []
    )
    return (
        f"| {expr_span(str(entry['concept']))}"
        f"（{cell(normalize_inline(str(entry.get('name') or '')))}） "
        f"| {expr_span(str(entry['attribute']))} "
        f"| {entry.get('representation_count', len(entry.get('columns') or []))} "
        f"| {cell(columns)} "
        f"| {cell(_concept_term_text(entry))} | {_concept_value_counts(entry)} |"
    )


def _concept_term_text(entry: Mapping) -> str:
    """The attribute's merged comments, with the conflict said out loud rather than resolved."""
    comments = entry.get("comments") or []
    if not comments:
        return EMPTY_CELL
    text = "；".join(
        f"{normalize_inline(str(item['text']))}（{item['count']} 张表）" for item in comments
    )
    return f"{CONFLICT_MARK} {text}" if entry.get("conflict") else text


def _concept_value_counts(entry: Mapping) -> str:
    """How much of this attribute's value domain somebody has already answered."""
    values = entry.get("values") or []
    confirmed = sum(1 for item in values if (item.get("meaning") or {}).get("text"))
    return f"{confirmed} / {len(values)}"


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
    lines = ["", f"## {column}{_alias_note(section.get('values') or ())}", ""]
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


def _alias_note(values: Sequence[Mapping]) -> str:
    """WI-B. A section is one column NAME, so it names every alias its values carry.

    Without it a reader sees a ``CASE`` they wrote as ``delta_18`` under the heading
    ``gap_10`` and concludes the dictionary is wrong.
    """
    aliases = sorted({str(item["sql_alias"]) for item in values if item.get("sql_alias")})
    return "".join(sql_alias_note(alias) for alias in aliases)


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
        if suffix:
            text = f"{text}（{suffix}）"
        # P5: what the confirmation rests on. An Agent's confirmation is required to
        # carry one, and a reader who cannot see it cannot review it.
        basis = normalize_inline(str(meaning.get("confirmed_basis") or ""))
        return f"{text}（{BASIS_PREFIX}{basis}）" if basis else text
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
