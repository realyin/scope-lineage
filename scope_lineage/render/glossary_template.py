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
  business meaning waiting to be written down -- *unless the column's own comment
  enumerates it* (P5b): ``Y``/``N`` answers "yes or no" only until somebody wrote down
  which is which, and then it is the cheapest row in the form;
- **no self-describing values**: ``委外`` is Chinese prose, and the only definition
  anybody can give it is itself (P5b);
- **no column left with fewer than two values**: one value is not a code system, and the
  answer would teach a reader nothing about a set -- except under ``--template-top 0``,
  which promises every askable value and therefore keeps them (WI-D);
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
before it are whole, and ``0`` means no cut at all -- single-value columns included. Ranking is a total order over data
the dictionary already carries, so two runs of one corpus produce the same bytes.

P5 adds the 候选来源 column and one ranking key in front of the score: which evidence kinds
each value carries, and the columns carrying any of them first. Those are the rows
somebody can close by reading instead of by asking a business owner, which is the whole
point of printing the evidence next to the question.

P5b says which of them can actually be closed. A review round closed a small fraction of
what the form offered, and the reason was in this column: ``comment`` covered both "the
comment defines this value" and "the comment happens to mention it", and ``case_label``
covered both a 1:1 translation and a bucket several codes share.

Q1 finishes that split on the label side, because two further rounds rejected most of the
1:1 labels they were offered for two reasons the column could not say:

- **a label is only a translation inside its own labelling system.** One column may carry
  two CASEs at once -- one sorting its values into ownership classes, another into stage
  classes -- so a value alone in a branch of one of them looked like a translation. The
  column heading now warns ``⚠ N 套标签体系`` and the cell reads ``case_label(体系 k/N)``;
  a lone branch of a CASE that buckets the column's other values reads
  ``case_label(单值分支)`` and is not evidence;
- **a "label" may itself be a code.** ``CU_OS_S1_1_1 → S1_1_1`` translates one coding
  system into another and defines neither; it now reads ``code_alias``.

Q1 also stops asking one repeated code table once per table: a ``(column name, value)``
pair askable in :data:`FAMILY_MINIMUM_TABLES` tables or more is asked once, under the
family key ``*.<column>=<value>``, in a section of its own.
"""

from __future__ import annotations

import datetime
from typing import Mapping, Sequence

from . import glossary_values
from .markdown_text import cell as _cell
from .markdown_text import expr_span as _expr_span
from .markdown_text import normalize_inline as _normalize_inline
from .markdown_text import sql_alias_note as _sql_alias_note
from .sequences import unique_ordered


DOC_FORMAT = "glossary-overrides-template/1"

# How many values one template asks about. Twenty is a form somebody fills in during one
# sitting; the rest stay in `glossary.json`, where a second run with a larger `--top`
# reaches them.
TEMPLATE_TOP_DEFAULT = 20

TEMPLATE_KEYS = ("doc_format", "generated", "terms", "values")

# A column with one value left is not a code system -- asking about it buys one answer
# and no set.
MINIMUM_COLUMN_VALUES = 2

# Q1. How many tables have to share one `(column name, value)` pair before the form
# stops asking about it table by table. Two tables may legitimately disagree -- that is
# the cross-table conflict the review prompt asks about on purpose. Three is a code
# table travelling with its column, and typing the same sentence once per table is how
# a review round spends its budget on transcription.
FAMILY_MINIMUM_TABLES = 3

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

_EXCLUSION_NOTE = "> 排除了 {values} 个开关/数字/日期/中文自述型取值与 {columns} 个 scope 级列。"

_TITLE = "# 取值含义待填模板"

_PREAMBLE = (
    "> 由 `scope-lineage glossary --template` 生成。一列一节，把业务含义写进「含义（待填）」"
    "列，同时把同一句话写进同名 `.json` 的 `values` 里，再跑",
    "> `scope-lineage glossary --lineage <语料> --out <目录> --overrides <本文件的 .json>`，"
    "下一轮画像里这些取值就是已确认的事实。",
    "> 含义不知道就留空——留空只是没答，猜一个会被下一轮当成事实。",
)

_TABLE_HEADER = (
    "| 取值 | 写法 | 出现任务数 | 观察次数 | 注释线索 | 候选来源 | 含义（待填） |",
    "| --- | --- | --- | --- | --- | --- | --- |",
)

# P5. The three kinds of evidence a reviewer (or an Agent following
# `references/glossary-review-prompt.md`) may answer a value FROM, printed per value so
# the form says which rows can be closed without asking anybody.
EVIDENCE_COMMENT_ENUM = glossary_values.CANDIDATE_SOURCE_COMMENT_ENUM
EVIDENCE_COMMENT_MENTION = glossary_values.CANDIDATE_SOURCE_COMMENT_MENTION
EVIDENCE_CASE_LABEL = glossary_values.CANDIDATE_SOURCE_CASE_LABEL
EVIDENCE_CODE_ALIAS = glossary_values.CANDIDATE_SOURCE_CODE_ALIAS
EVIDENCE_SAME_NAME = "same_name_confirmed"
EVIDENCE_NONE = "—"

# P5b. A CASE label several values share, said out loud in the column a reviewer reads
# to decide whether a row can be closed without asking anybody. It cannot.
EVIDENCE_BUCKET = "case_label(桶 {count})"

# Q1. The two other ways a 1:1 label is not a translation, said out loud in the same
# column: the CASE it came from buckets this column's other values (so it is sorting,
# not naming), and the column carries more than one labelling system at once (so no
# value of it can be answered on its own, whatever any one CASE calls it).
EVIDENCE_SINGLE_BRANCH = "case_label(单值分支)"
EVIDENCE_LABEL_SYSTEM = "case_label(体系 {index}/{total})"

_LABEL_SYSTEM_NOTE = "⚠ {count} 套标签体系"

_CLOSED_NOTE = "- 该列取值已被 SQL 证明封闭：{answer}"

_FAMILY_HEADING = "## `*.{column}`（出现在 {tables} 张表）"
_FAMILY_NOTE = (
    "- 同一个列名的同一个取值出现在 {tables} 张表上，用家族键 `*.{column}=<取值>` 问一次即可："
    "答案会写回每一张观察到该取值的表，下面各表小节不再重复这些取值。"
)

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
            _form_key(item, selection["families"]): {
                "meaning": "",
                "confirmed_by": None,
                "date": day,
            }
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
    askable = [item for item in physical if _is_askable(item)]
    clues = _clue_columns(glossary.get("terms") or [])
    confirmed = same_name_confirmed(glossary)
    ranked = [
        entry
        for _key, entries in sorted(
            _by_column(askable, keep_single=top <= 0).items(),
            key=lambda pair: _column_rank(pair[0], pair[1], clues, confirmed),
        )
        for entry in entries
    ]
    return {
        # WI-D: `0` is "no cap". A corpus larger than the default is exactly when a
        # reader asks for the whole form, and the old reading handed them an empty one.
        "entries": ranked if top <= 0 else ranked[:top],
        # Q1: counted over every askable value rather than over the cut, because a
        # family key answers the tables the cut did not reach as well.
        "families": _family_pairs(askable),
        "excluded_values": len(physical) - len(askable),
        "excluded_scope_columns": len(
            {str(item["column_ref"]) for item in unanswered if not _is_physical(item)}
        ),
    }


def _family_pairs(entries: Sequence[Mapping]) -> dict[tuple[str, str], int]:
    """``(column name, value) -> table count`` for the pairs one answer can close.

    Q1. A code table travels with its column: the same ``(column name, value)`` pair is
    observed in table after table, and the form used to print one row per table -- the
    same question, answered by hand as many times as the warehouse happens to have
    copied the column. Counted over TABLES rather than over entries, because one table
    writing the value in several statements is still one table.
    """
    tables: dict[tuple[str, str], set] = {}
    for entry in entries:
        key = (str(entry["column"]), str(entry["value"]))
        tables.setdefault(key, set()).add(str(entry["column_ref"]).rsplit(".", 1)[0])
    return {
        key: len(owners)
        for key, owners in tables.items()
        if len(owners) >= FAMILY_MINIMUM_TABLES
    }


def _by_column(entries: Sequence[Mapping], *, keep_single: bool = False) -> dict[str, list[dict]]:
    """The askable values of each column that has enough of them to be worth a section.

    WI-D: ``MINIMUM_COLUMN_VALUES`` is a statement about ranking worth -- a one-value
    column buys one answer and teaches nothing about a set, so it does not earn a place
    in a form somebody fills in during one sitting. It was never a statement that the
    value may not be asked about at all, and an uncapped form (``--template-top 0``)
    promises every askable value, so it keeps them.
    """
    grouped: dict[str, list[dict]] = {}
    for entry in entries:
        grouped.setdefault(str(entry["column_ref"]), []).append(entry)
    minimum = 1 if keep_single else MINIMUM_COLUMN_VALUES
    return {
        column: sorted(items, key=_value_rank)
        for column, items in grouped.items()
        if len(items) >= minimum
    }


def same_name_confirmed(glossary: Mapping) -> frozenset:
    """``(column name, value)`` pairs a PERSON has already confirmed somewhere (P5).

    The same-name rule of the review prompt: ``pay_status='PAID'`` answered on one table
    is evidence for the identically named column of another. Only a human confirmation
    counts -- an Agent's own answer spreading itself across the corpus would be the
    layer confirming its own inference.
    """
    return frozenset(
        (str(entry.get("column")), str(entry.get("value")))
        for entry in glossary.get("values") or []
        if glossary_values.human_confirmed(entry.get("meaning"))
    )


def evidence_kinds(
    entry: Mapping, confirmed: frozenset, systems: Sequence[str] = ()
) -> list[str]:
    """Which kinds of evidence this one value carries, in reading order.

    P5b splits what used to print as one word: an enumeration defines the value and a
    mention only contains it, and a CASE label shared by several values is named as the
    bucket it is. Q1 splits the remaining half of ``case_label`` the same way -- a lone
    branch of a bucketing CASE and a label that is itself a code are not translations
    either -- so the column now says which of its rows a reviewer may close by reading.

    ``systems`` is the column's labelling systems in printing order; it is what turns a
    candidate's ``label_system`` into the ``体系 k/N`` a reader can act on.
    """
    candidates = entry.get("meaning_candidates") or []
    sources = {str(item.get("source")) for item in candidates}
    kinds = [
        kind
        for kind in (EVIDENCE_COMMENT_ENUM, EVIDENCE_COMMENT_MENTION)
        if kind in sources
    ]
    if EVIDENCE_CASE_LABEL in sources:
        kinds.append(_label_kind(candidates, systems))
    if EVIDENCE_CODE_ALIAS in sources:
        kinds.append(EVIDENCE_CODE_ALIAS)
    if (str(entry.get("column")), str(entry.get("value"))) in confirmed:
        kinds.append(EVIDENCE_SAME_NAME)
    return kinds


def label_systems(entries: Sequence[Mapping]) -> tuple[str, ...]:
    """The labelling systems of one column, in the order the form numbers them."""
    return tuple(
        sorted(
            {
                str(item["label_system"])
                for entry in entries
                for item in entry.get("meaning_candidates") or []
                if item.get("label_system")
            }
        )
    )


def _label_kind(candidates: Sequence[Mapping], systems: Sequence[str] = ()) -> str:
    """What this value's best CASE label actually says, named so nobody over-reads it.

    The strongest label wins: a value one CASE translates 1:1 and another lumps into a
    bucket is still a value somebody can read an answer off. What it is called then
    follows the strongest thing standing in the way of reading it -- a bucket, a lone
    branch of a bucketing CASE, or a column that carries two labelling systems at once.
    """
    best = min(
        (item for item in candidates if str(item.get("source")) == EVIDENCE_CASE_LABEL),
        key=lambda item: (
            0 if _confirmable_label(item) else 1,
            int(item.get("fan_out") or 1),
            str(item.get("label_system") or ""),
        ),
    )
    fan_out = int(best.get("fan_out") or 1)
    if fan_out > 1:
        return EVIDENCE_BUCKET.format(count=fan_out)
    if best.get("single_branch"):
        return EVIDENCE_SINGLE_BRANCH
    system = str(best.get("label_system") or "")
    if system in systems:
        return EVIDENCE_LABEL_SYSTEM.format(
            index=list(systems).index(system) + 1, total=len(systems)
        )
    return EVIDENCE_CASE_LABEL


def _confirmable_label(item: Mapping) -> bool:
    """A CASE label somebody may answer from: one value, one branch, one real name."""
    return (
        str(item.get("source")) == EVIDENCE_CASE_LABEL
        and int(item.get("fan_out") or 1) <= 1
        and not item.get("single_branch")
    )


def confirmable_evidence(entry: Mapping, confirmed: frozenset = frozenset()) -> bool:
    """Whether this value carries evidence a reviewer may close it FROM (Q1).

    The same three routes the review prompt admits, and no more: the column's own
    comment enumerates the value, a CASE translates it one to one inside a system that
    buckets nothing, or a PERSON has confirmed the same value on a same-named column
    elsewhere. A mention, a bucket, a lone branch of a bucketing CASE and a synonym are
    all leads for a person -- they used to lift a whole column to the front of the form,
    which is how a review round spent its first page on rows nobody could answer by
    reading.
    """
    if (str(entry.get("column")), str(entry.get("value"))) in confirmed:
        return True
    return any(
        str(item.get("source")) == EVIDENCE_COMMENT_ENUM or _confirmable_label(item)
        for item in entry.get("meaning_candidates") or []
    )


def _column_rank(
    column: str, entries: Sequence[Mapping], clues: frozenset, confirmed: frozenset
) -> tuple:
    """How much of the corpus rests on this column, highest first, ties broken by name.

    P5 puts one key in front of the score: a column any of whose values carries evidence
    is asked first. Those are the rows a reviewer can close by reading rather than by
    asking, so they are the cheapest part of the form -- and the score keeps deciding
    everything else, exactly as it did. Q1 narrows "evidence" to what
    :func:`confirmable_evidence` admits -- the review prompt's own three routes; a column
    whose only clue is a mention, a bucket, a lone branch of a bucketing CASE or a
    synonym ranks with the ones that carry nothing, because that is what it is.
    """
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
    evidence = any(confirmable_evidence(entry, confirmed) for entry in entries)
    return (0 if evidence else 1, -score, column)


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


def _is_askable(entry: Mapping) -> bool:
    """Whether a person could add anything by answering this one value (P5b).

    Q1: the rule itself lives in :func:`glossary_values.askable_value`, beside the
    coverage denominator that has to agree with it. The form keeps the name it reads
    this question by, and nothing else.
    """
    return glossary_values.askable_value(entry)


def _override_key(entry: Mapping) -> str:
    """``<table>.<column>=<value>``: the qualified form, so one answer binds one column."""
    return f"{entry['column_ref']}={entry['value']}"


def _family_key(entry: Mapping) -> str:
    """``*.<column>=<value>``: one answer for every table whose column saw that value."""
    return f"*.{entry['column']}={entry['value']}"


def _is_family(entry: Mapping, families: Mapping) -> bool:
    return (str(entry["column"]), str(entry["value"])) in families


def _form_key(entry: Mapping, families: Mapping) -> str:
    """The key this row is asked under: the family key when one answer covers them all."""
    return _family_key(entry) if _is_family(entry, families) else _override_key(entry)


# ------------------------------------------------------------------------ markdown


def render_overrides_template_markdown(template: Mapping, glossary: Mapping) -> str:
    """The same entries as the JSON, laid out one section per column.

    Q1: a section may now be a column FAMILY (`*.<column>`) rather than one table's
    column, so the selection is re-derived from the dictionary and then filtered to the
    keys the JSON actually asks about -- the two documents still ask the same questions,
    and a family question is one question.
    """
    selection = _selection(glossary, _top_of(template))
    families = selection["families"]
    asked = set(template.get("values") or {})
    entries = [
        entry for entry in selection["entries"] if _form_key(entry, families) in asked
    ]
    lines = [_TITLE, "", *_PREAMBLE, _exclusion_note(template), ""]
    if not entries:
        lines.append(EMPTY_TEMPLATE_NOTE)
        return "\n".join(lines) + "\n"
    confirmed = same_name_confirmed(glossary)
    for section in _dedupe(_section_key(entry, families) for entry in entries):
        members = [
            entry for entry in entries if _section_key(entry, families) == section
        ]
        lines.extend(_section(section, members, families, confirmed))
    return "\n".join(lines).rstrip("\n") + "\n"


def _top_of(template: Mapping) -> int:
    generated = template.get("generated") or {}
    return int(generated["top"]) if "top" in generated else TEMPLATE_TOP_DEFAULT


def _section_key(entry: Mapping, families: Mapping) -> str:
    """Which section this row belongs to: its own table's column, or the family."""
    return (
        f"*.{entry['column']}"
        if _is_family(entry, families)
        else str(entry["column_ref"])
    )


def _section(
    section: str, entries: Sequence[Mapping], families: Mapping, confirmed: frozenset
) -> list[str]:
    if not section.startswith("*."):
        return _column_section(section, entries, confirmed)
    return _family_section(section.partition(".")[2], entries, families, confirmed)


def _family_section(
    column: str, entries: Sequence[Mapping], families: Mapping, confirmed: frozenset
) -> list[str]:
    """One code table asked once, however many tables the warehouse copied it into."""
    tables = max(
        families[(str(entry["column"]), str(entry["value"]))] for entry in entries
    )
    unique = _unique_values(entries)
    closed = "是" if any(item.get("closed_set") for item in unique) else "未证明"
    return [
        _FAMILY_HEADING.format(column=column, tables=tables),
        "",
        _FAMILY_NOTE.format(column=column, tables=tables),
        _CLOSED_NOTE.format(answer=closed),
        "",
        *_TABLE_HEADER,
        *[_row(item, confirmed, label_systems(unique)) for item in unique],
        "",
    ]


def _unique_values(entries: Sequence[Mapping]) -> list[dict]:
    """One row per value: the same code observed in five tables is one question."""
    found: dict[str, dict] = {}
    for entry in entries:
        found.setdefault(str(entry["value"]), dict(entry))
    return [found[value] for value in sorted(found)]


def _exclusion_note(template: Mapping) -> str:
    """What the form did not ask about, so short is not mistaken for complete."""
    generated = template.get("generated") or {}
    return _EXCLUSION_NOTE.format(
        values=int(generated.get("excluded_values") or 0),
        columns=int(generated.get("excluded_scope_columns") or 0),
    )


def _column_section(
    column: str, entries: Sequence[Mapping], confirmed: frozenset
) -> list[str]:
    closed = "是" if any(item.get("closed_set") for item in entries) else "未证明"
    # WI-B: the person filling this in searches their SQL for the name they typed, which
    # under a positional write is not the column name this section is headed by.
    alias = next((str(item["sql_alias"]) for item in entries if item.get("sql_alias")), "")
    systems = label_systems(entries)
    return [
        f"## `{column}`{_sql_alias_note(alias)}（{len(entries)} 个取值）"
        f"{_label_system_note(entries)}",
        "",
        _CLOSED_NOTE.format(answer=closed),
        "",
        *_TABLE_HEADER,
        *[_row(item, confirmed, systems) for item in entries],
        "",
    ]


def _label_system_note(entries: Sequence[Mapping]) -> str:
    """Q1: the column heading says when no value of it may be answered on its own."""
    count = max(int(entry.get("label_systems") or 0) for entry in entries)
    return _LABEL_SYSTEM_NOTE.format(count=count) if count >= 2 else ""


def _row(entry: Mapping, confirmed: frozenset, systems: Sequence[str] = ()) -> str:
    kinds = evidence_kinds(entry, confirmed, systems)
    return (
        f"| {_expr_span(str(entry['value']))} "
        f"| {_expr_span(str(entry.get('sql_literal') or entry['value']))} "
        f"| {entry.get('task_count') or 0} "
        f"| {len(entry.get('observations') or [])} "
        f"| {_cell(_candidate_text(entry))} "
        f"| {_cell('、'.join(kinds) if kinds else EVIDENCE_NONE)} |  |"
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
