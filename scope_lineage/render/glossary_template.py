"""The fill-in overrides template (``glossary-overrides-template/1``).

WI-2.9 item C. The open-questions list used to spend most of its budget asking what each
``code`` means, one question per value, and the owner's answer was that there were too
many to work through. Those questions were never really questions: they are a *form*.
So the profile now says one sentence -- "write the meanings into
``glossary.overrides.template.md``" -- and this module generates that form from the
corpus dictionary, shortest useful version first.

What it leaves out is the whole design:

- **only ``literal``**: a ``pattern`` is a match shape (``'%UNIT_OUT_%'``), not a value
  anybody can give a meaning to;
- **no dates**: a day is an instance date, not a code (WI-2.9 item A);
- **no bare numbers without an enumerated context**: ``rn = 1`` and ``flag = 0`` are
  positions and switches, and asking what ``1`` means is how a form loses its reader.
  A number inside a set the SQL proved closed (``status IN (0, 1, 2)``) is kept;
- **nothing already answered**: a value a human confirmed is not asked twice.

What survives is ranked closed sets first, then by how much of the corpus rests on the
value -- how many tasks use it, and how many places it was observed in -- and the top
``top`` of them are published. Ranking is a total order over data the dictionary already
carries, so two runs of one corpus produce the same bytes.
"""

from __future__ import annotations

import datetime
import re
from typing import Mapping, Sequence

from . import glossary_values
from . import semantic_text
from .markdown_text import cell as _cell
from .markdown_text import expr_span as _expr_span
from .markdown_text import normalize_inline as _normalize_inline


DOC_FORMAT = "glossary-overrides-template/1"

# How many values one template asks about. Twenty is a form somebody fills in during one
# sitting; the rest stay in `glossary.json`, where a second run with a larger `--top`
# reaches them.
TEMPLATE_TOP_DEFAULT = 20

TEMPLATE_KEYS = ("doc_format", "generated", "terms", "values")

# `1`, `-1`, `0.5`: a position or a switch, not a code with a business meaning.
_BARE_NUMBER = re.compile(r"^[+-]?\d+(?:\.\d+)?$")

_TITLE = "# 取值含义待填模板"

_PREAMBLE = (
    "> 由 `scope-lineage glossary --template` 生成。一列一节，把业务含义写进「含义（待填）」"
    "列，同时把同一句话写进同名 `.json` 的 `values` 里，再跑",
    "> `scope-lineage glossary --lineage <语料> --out <目录> --overrides <本文件的 .json>`，"
    "下一轮画像里这些取值就是已确认的事实。",
    "> 含义不知道就留空——留空只是没答，猜一个会被下一轮当成事实。",
)

_TABLE_HEADER = (
    "| 取值 | 写法 | 出现任务数 | 观察次数 | 注释线索 | 含义（待填） |",
    "| --- | --- | --- | --- | --- | --- |",
)

_CLOSED_NOTE = "- 该列取值已被 SQL 证明封闭：{answer}"

EMPTY_TEMPLATE_NOTE = "语料里没有需要填含义的取值。"


def build_overrides_template(
    glossary: Mapping,
    *,
    top: int = TEMPLATE_TOP_DEFAULT,
    today: datetime.date | None = None,
) -> dict:
    """The ranked, filtered fill-in form for one corpus glossary."""
    day = (today or datetime.date.today()).isoformat()
    selected = _selected(glossary.get("values") or [], top)
    return {
        "doc_format": DOC_FORMAT,
        "generated": {
            "artifact_root": str((glossary.get("corpus") or {}).get("artifact_root") or ""),
            "top": int(top),
            "value_count": len(selected),
            "column_count": len({item["column_ref"] for item in selected}),
            "date": day,
        },
        "terms": {},
        "values": {
            _override_key(item): {"meaning": "", "confirmed_by": None, "date": day}
            for item in selected
        },
    }


def template_entries(glossary: Mapping, top: int = TEMPLATE_TOP_DEFAULT) -> list[dict]:
    """The dictionary entries the template asks about, in the order it asks them."""
    return _selected(glossary.get("values") or [], top)


def _selected(values: Sequence[Mapping], top: int) -> list[dict]:
    """The top ``top`` askable values, regrouped by column without re-ranking them.

    The cut is made over values, so ``--template-top`` means what it says; the regroup
    only moves a column's second value up beside its first, which is how somebody fills
    a form in -- one column at a time.
    """
    ranked = sorted((item for item in values if _is_askable(item)), key=_rank)[: max(top, 0)]
    return [
        item
        for column in _dedupe(item["column_ref"] for item in ranked)
        for item in ranked
        if item["column_ref"] == column
    ]


def _rank(entry: Mapping) -> tuple:
    """Closed sets first, then the values the most of the corpus rests on.

    The last two components are the column and the value themselves, so entries that
    tie on every count still have exactly one order.
    """
    return (
        0 if entry.get("closed_set") else 1,
        -int(entry.get("task_count") or 0),
        -len(entry.get("observations") or []),
        str(entry.get("column_ref") or ""),
        str(entry.get("value") or ""),
    )


def _is_askable(entry: Mapping) -> bool:
    """Whether a human can be asked what this value means, and has not already said."""
    if entry.get("logical") or (entry.get("meaning") or {}).get("text"):
        return False
    if str(entry.get("kind")) != glossary_values.VALUE_KIND_LITERAL:
        return False
    value = str(entry.get("value") or "")
    if not value or semantic_text.looks_like_date_literal(value):
        return False
    return bool(entry.get("closed_set")) or not _BARE_NUMBER.match(value.strip())


def _override_key(entry: Mapping) -> str:
    """``<table>.<column>=<value>``: the qualified form, so one answer binds one column."""
    return f"{entry['column_ref']}={entry['value']}"


# ------------------------------------------------------------------------ markdown


def render_overrides_template_markdown(template: Mapping, glossary: Mapping) -> str:
    """The same entries as the JSON, laid out one section per column."""
    known = {_override_key(item): item for item in glossary.get("values") or []}
    entries = [known[key] for key in template.get("values") or {} if key in known]
    lines = [_TITLE, "", *_PREAMBLE, ""]
    if not entries:
        lines.append(EMPTY_TEMPLATE_NOTE)
        return "\n".join(lines) + "\n"
    for column in _dedupe(item["column_ref"] for item in entries):
        lines.extend(
            _column_section(column, [item for item in entries if item["column_ref"] == column])
        )
    return "\n".join(lines).rstrip("\n") + "\n"


def _column_section(column: str, entries: Sequence[Mapping]) -> list[str]:
    closed = "是" if any(item.get("closed_set") for item in entries) else "未证明"
    return [
        f"## `{column}`（{len(entries)} 个取值）",
        "",
        _CLOSED_NOTE.format(answer=closed),
        "",
        *_TABLE_HEADER,
        *[_row(item) for item in entries],
        "",
    ]


def _row(entry: Mapping) -> str:
    return (
        f"| {_expr_span(str(entry['value']))} "
        f"| {_expr_span(str(entry.get('sql_literal') or entry['value']))} "
        f"| {entry.get('task_count') or 0} "
        f"| {len(entry.get('observations') or [])} "
        f"| {_cell(_candidate_text(entry))} |  |"
    )


def _candidate_text(entry: Mapping) -> str:
    """The comments that literally spell this value out, or an em dash for none."""
    texts = _dedupe(
        _normalize_inline(str(item.get("text") or ""))
        for item in entry.get("meaning_candidates") or []
    )
    return "；".join(texts) if texts else "—"


def _dedupe(items) -> list[str]:
    seen: set = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered
