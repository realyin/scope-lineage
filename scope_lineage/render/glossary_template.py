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
- **only physical columns**: a ``logical`` reference is a scope id, and no overrides key
  can bind one;
- **no trivial values**: ``Y`` / ``N`` / ``true`` / ``false`` are switches, a bare number
  is a position, and a day is an instance date (WI-2.9 item A). None of the three has a
  business meaning waiting to be written down;
- **no column left with fewer than two values**: one value is not a code system, and the
  answer would teach a reader nothing about a set;
- **nothing already answered**: a value a human confirmed is not asked twice.

WI-2.10 B: the first version ranked closed sets first and then by observation count, and
a real corpus spent the whole first page on ``Y`` / ``N``, ``1`` / ``0`` and scope-level
columns -- the exclusions above are that finding. What survives is ranked by COLUMN, by
how much of the corpus rests on it: how many distinct values it has, how many tasks use
them, whether an ``IN`` list or a ``CASE`` puts the column in enumerated position, and
whether its comment reads like a code column's. The comment clue is a ranking signal and
never a meaning -- a column called 状态 is *likely* to be worth asking about, which is a
different claim from knowing what any of its values mean.

``--template-top`` still counts VALUES, so the cut can land inside a column; the columns
before it are whole. Ranking is a total order over data the dictionary already carries,
so two runs of one corpus produce the same bytes.
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
from .sequences import unique_ordered


DOC_FORMAT = "glossary-overrides-template/1"

# How many values one template asks about. Twenty is a form somebody fills in during one
# sitting; the rest stay in `glossary.json`, where a second run with a larger `--top`
# reaches them.
TEMPLATE_TOP_DEFAULT = 20

TEMPLATE_KEYS = ("doc_format", "generated", "terms", "values")

# `1`, `-1`, `0.5`: a position or a switch, not a code with a business meaning.
_BARE_NUMBER = re.compile(r"^[+-]?\d+(?:\.\d+)?$")

# The same argument in words: a two-state flag answers "yes or no", which every reader
# already knows. Matched case-insensitively, because one corpus writes all three.
_SWITCH_VALUES = frozenset({"y", "n", "yes", "no", "true", "false"})

# A column with one value left is not a code system -- asking about it buys one answer
# and no set.
MINIMUM_COLUMN_VALUES = 2

# Words that make a column LOOK like it carries codes. A ranking clue and nothing else:
# it moves a column up the form, and it never becomes a value's meaning.
_COMMENT_CLUES = (
    "编码",
    "代码",
    "类型",
    "状态",
    "标记",
    "code",
    "type",
    "status",
    "flag",
)

# What one column's presence in the form is worth, per unit of the evidence behind it.
_DISTINCT_VALUE_WEIGHT = 2
_FILTER_IN_WEIGHT = 3
_CASE_THEN_WEIGHT = 2
_COMMENT_CLUE_WEIGHT = 2

_EXCLUSION_NOTE = "> 排除了 {values} 个开关/数字/日期型取值与 {columns} 个 scope 级列。"

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
    selection = _selection(glossary, top)
    selected = selection["entries"]
    return {
        "doc_format": DOC_FORMAT,
        "generated": {
            "artifact_root": str((glossary.get("corpus") or {}).get("artifact_root") or ""),
            "top": int(top),
            "value_count": len(selected),
            "column_count": len({item["column_ref"] for item in selected}),
            # What the form stepped over, so a reader can tell "asks about little" from
            # "saw little". Both are counted before the top cut.
            "excluded_values": selection["excluded_values"],
            "excluded_scope_columns": selection["excluded_scope_columns"],
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
    return _selection(glossary, top)["entries"]


def _selection(glossary: Mapping, top: int) -> dict:
    """``{entries, excluded_values, excluded_scope_columns}`` for one corpus dictionary.

    The form is built column by column and cut value by value, so ``--template-top``
    still means what it says while a person still fills one column in at a time.
    """
    unanswered = [
        item for item in glossary.get("values") or [] if _is_unanswered_literal(item)
    ]
    physical = [item for item in unanswered if _is_physical(item)]
    askable = [item for item in physical if not _is_trivial(str(item.get("value") or ""))]
    clues = _clue_columns(glossary.get("terms") or [])
    ranked = [
        entry
        for _key, entries in sorted(
            _by_column(askable).items(), key=lambda pair: _column_rank(pair[0], pair[1], clues)
        )
        for entry in entries
    ]
    return {
        "entries": ranked[: max(top, 0)],
        "excluded_values": len(physical) - len(askable),
        "excluded_scope_columns": len(
            {str(item["column_ref"]) for item in unanswered if not _is_physical(item)}
        ),
    }


def _by_column(entries: Sequence[Mapping]) -> dict[str, list[dict]]:
    """The askable values of each column that has enough of them to be worth a section."""
    grouped: dict[str, list[dict]] = {}
    for entry in entries:
        grouped.setdefault(str(entry["column_ref"]), []).append(entry)
    return {
        column: sorted(items, key=_value_rank)
        for column, items in grouped.items()
        if len(items) >= MINIMUM_COLUMN_VALUES
    }


def _column_rank(column: str, entries: Sequence[Mapping], clues: frozenset) -> tuple:
    """How much of the corpus rests on this column, highest first, ties broken by name."""
    contexts = {
        str(item.get("context"))
        for entry in entries
        for item in entry.get("observations") or []
    }
    score = (
        len(entries) * _DISTINCT_VALUE_WEIGHT
        + sum(int(entry.get("task_count") or 0) for entry in entries)
        + (_FILTER_IN_WEIGHT if glossary_values.CONTEXT_FILTER_IN in contexts else 0)
        + (_CASE_THEN_WEIGHT if glossary_values.CONTEXT_CASE_THEN in contexts else 0)
        + (_COMMENT_CLUE_WEIGHT if column.rpartition(".")[2] in clues else 0)
    )
    return (-score, column)


def _value_rank(entry: Mapping) -> tuple:
    """Inside one column: the value the most of the corpus rests on, then by spelling."""
    return (
        -int(entry.get("task_count") or 0),
        -len(entry.get("observations") or []),
        str(entry.get("value") or ""),
    )


def _clue_columns(terms: Sequence[Mapping]) -> frozenset:
    """Column NAMES whose corpus comment reads like a code column's (a ranking clue)."""
    return frozenset(
        str(term.get("column"))
        for term in terms
        if any(
            clue in str(comment.get("text") or "").lower()
            for comment in term.get("comments") or []
            for clue in _COMMENT_CLUES
        )
    )


def _is_unanswered_literal(entry: Mapping) -> bool:
    """A value somebody could still be asked about: a literal with no meaning yet."""
    if (entry.get("meaning") or {}).get("text"):
        return False
    if str(entry.get("kind")) != glossary_values.VALUE_KIND_LITERAL:
        return False
    return bool(str(entry.get("value") or ""))


def _is_physical(entry: Mapping) -> bool:
    """False for a scope-level reference -- ``cte:d.rn`` binds nothing in an overrides."""
    return not entry.get("logical") and ":" not in str(entry.get("column_ref") or "")


def _is_trivial(value: str) -> bool:
    """A switch, a position or an instance date: three things nobody defines."""
    text = value.strip()
    if text.lower() in _SWITCH_VALUES or _BARE_NUMBER.match(text):
        return True
    return semantic_text.looks_like_date_literal(text)


def _override_key(entry: Mapping) -> str:
    """``<table>.<column>=<value>``: the qualified form, so one answer binds one column."""
    return f"{entry['column_ref']}={entry['value']}"


# ------------------------------------------------------------------------ markdown


def render_overrides_template_markdown(template: Mapping, glossary: Mapping) -> str:
    """The same entries as the JSON, laid out one section per column."""
    known = {_override_key(item): item for item in glossary.get("values") or []}
    entries = [known[key] for key in template.get("values") or {} if key in known]
    lines = [_TITLE, "", *_PREAMBLE, _exclusion_note(template), ""]
    if not entries:
        lines.append(EMPTY_TEMPLATE_NOTE)
        return "\n".join(lines) + "\n"
    for column in _dedupe(item["column_ref"] for item in entries):
        lines.extend(
            _column_section(column, [item for item in entries if item["column_ref"] == column])
        )
    return "\n".join(lines).rstrip("\n") + "\n"


def _exclusion_note(template: Mapping) -> str:
    """What the form did not ask about, so short is not mistaken for complete."""
    generated = template.get("generated") or {}
    return _EXCLUSION_NOTE.format(
        values=int(generated.get("excluded_values") or 0),
        columns=int(generated.get("excluded_scope_columns") or 0),
    )


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
    """Unique in first-seen order, with the empties dropped: a blank is not a column."""
    return unique_ordered(item for item in items if item)
