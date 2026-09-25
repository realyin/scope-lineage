"""字段: every column, grouped the way a reader looks for one.

- 标识与关联 -- identifiers and foreign identifiers;
- 状态与码值 -- state columns and any column with code values (the only group with a 码值
  column: a value's meaning, ✓ once confirmed, ``值（含义待确认）`` while a guess);
- 金额 -- measures, their unit after the meaning;
- 时间 -- time columns, the partition column among them;
- 描述与技术列 -- one line, not a table: descriptive columns, then 技术列.

A column's 口径 spells out each branch (``线上：…；线下：…``), then the general wording,
then when it is empty; its own ``watch`` follows with ⚠.
"""

from __future__ import annotations

from ..render.catalog_concept_page import table_head, table_row
from ..render.catalog_view import is_unconfirmed
from .page_words import (
    TICK,
    PageMarks,
    clause,
    code,
    is_confirmed,
    sources_text,
    text,
)

IDENTIFIERS, CODES, AMOUNTS, TIMES, OTHERS = (
    "标识与关联",
    "状态与码值",
    "金额",
    "时间",
    "描述与技术列",
)
GROUPS = (IDENTIFIERS, CODES, AMOUNTS, TIMES, OTHERS)
_BY_CATEGORY = {
    "identifier": IDENTIFIERS,
    "foreign_identifier": IDENTIFIERS,
    "state": CODES,
    "measure": AMOUNTS,
    "time": TIMES,
}
UNCONFIRMED_CODE = "含义待确认"


def group_of(column: dict) -> str:
    if column.get("code_values"):
        return CODES
    return _BY_CATEGORY.get(column["category"], OTHERS)


def field_lines(document: dict, marks: PageMarks) -> list[str]:
    indexed = list(enumerate(document["columns"]))
    lines: list[str] = []
    for group in GROUPS:
        members = [(index, column) for index, column in indexed if group_of(column) == group]
        if not members:
            continue
        body = _prose(members, marks) if group == OTHERS else _table(group, members, marks)
        lines += ["", f"### {group}", "", *body]
    return lines[1:]


def _table(group: str, members: list, marks: PageMarks) -> list[str]:
    codes = group == CODES
    lines = table_head("字段", "含义", *(["码值"] if codes else []), "口径", "来源")
    for index, column in members:
        cells = [
            code(column["column"]) + marks.fails(f"columns:{index}"),
            _meaning(column),
            *([codes_text(column)] if codes else []),
            derivation_text(column) + marks.notes(_watch_only(column), f"column:{column['column']}"),
            sources_text(column),
        ]
        lines.append(table_row(*cells))
    return lines


def _watch_only(column: dict) -> dict:
    """The column's ⚠ without its ✓: the tick sits beside the meaning it confirms."""
    return {"watch": column["watch"]} if column.get("watch") else {}


def _meaning(column: dict) -> str:
    unit = f"（{text(column['unit'])}）" if column.get("unit") else ""
    return text(column["meaning"]) + unit + (TICK if is_confirmed(column) else "")


def derivation_text(column: dict) -> str:
    """``线上：…；线下：…；<general wording>；为空：…``, or ``—``."""
    parts = [f"{text(b['branch'])}：{clause(b['text'])}" for b in column.get("branches") or []]
    if str(column.get("derivation") or "").strip():
        parts.append(clause(column["derivation"]))
    if column.get("null_meaning"):
        parts.append(f"为空：{clause(column['null_meaning'])}")
    return "；".join(parts) or "—"


def codes_text(column: dict) -> str:
    return "、".join(_code_value(value) for value in column.get("code_values") or []) or "—"


def _code_value(value: dict) -> str:
    if is_unconfirmed(value):
        return f"{text(value['value'])}（{UNCONFIRMED_CODE}）"
    tick = TICK if is_confirmed(value) else ""
    return f"{text(value['value'])} {text(value['meaning'])}{tick}"


def _prose(members: list, marks: PageMarks) -> list[str]:
    """``` `c` 含义（口径）、…；技术列 `c` 含义（口径）``` on one line."""
    plain = [_prose_item(i, c, marks) for i, c in members if c["category"] != "technical"]
    technical = [_prose_item(i, c, marks) for i, c in members if c["category"] == "technical"]
    parts = ["、".join(plain)] if plain else []
    if technical:
        parts.append("技术列 " + "、".join(technical))
    return ["；".join(parts) + "。"]


def _prose_item(index: int, column: dict, marks: PageMarks) -> str:
    derivation = derivation_text(column)
    said = f"（{derivation}）" if derivation != "—" else ""
    notes = marks.notes(_watch_only(column), f"column:{column['column']}")
    return f"{code(column['column'])} {_meaning(column)}{said}{notes}" + marks.fails(
        f"columns:{index}"
    )
