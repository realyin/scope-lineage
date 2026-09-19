"""Render a semantic profile dict into ``semantic.md`` (``semantic-md/1``).

A second view of one source, never a second source. ``semantic_profile`` builds the
whole document as a dict; this module only turns that dict into markdown, so the two
artifacts cannot drift apart and nothing is stated here that ``semantic.json`` does not
already carry. Sibling of ``mapping_markdown``, and deliberately a different question:
mapping.md answers "which column came from where", semantic.md answers "what does this
task do, and what does each field mean".

Three grammar rules hold for every line, the same three mapping-md/1 keeps:

- **One line, one fact.** Rendered values have their newlines normalized to a literal
  ``\\n`` (``markdown_text``), so a multi-line SQL literal cannot become two facts.
- **Expressions live in code spans** whose fence grows past any backtick inside the SQL,
  and a pipe inside a table cell is escaped, so no SQL text can break the layout.
- **Every line carries its evidence class.** A line ends in ``（SQL事实）`` /
  ``（元数据事实）`` / ``（SQL事实+元数据事实）`` when it restates the contract, and in
  ``（结构推断；证据 <id>[, <id>]）`` when it states something the SQL structure proves
  but never says. ``⚠`` marks what the document could not prove at all.

**One deviation from the WI-2 brief**, in the direction of keeping facts: the brief
writes the fact suffix as a bare ``（SQL事实）``, which would drop the ``logic_block_id``
of every restated action. The suffix grammar is therefore uniform --
``（<标签>[；证据 <id>[, <id>]]）`` for all four labels -- so a fact line keeps the id
that a reader (or ``query.py``) joins back to ``lineage.json`` with.

Section numbering is fixed: ``--sections`` hides sections, it never renumbers them, so
"section 5" means the same thing in every rendered document.
"""

from __future__ import annotations

import json
import re
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from .markdown_text import cell as _cell
from .markdown_text import expr_span as _expr_span
from . import glossary_values as _glossary_values
from .markdown_text import normalize_inline as _normalize_inline
from .markdown_text import sql_alias_note as _sql_alias_note
from .sequences import unique_ordered
from .semantic_text import describe_nullable_argument as _describe_nullable_argument
from .semantic_text import equality_conjunct
from .semantic_text import predicate_literal_day_offset
from .semantic_text import generated_source_text as _generated_source_text


DOC_FORMAT = "semantic-md/1"

TASK_ARTIFACT_KIND = "task_semantic"

SECTION_ORDER = (
    "overview",
    "shape",
    "stages",
    "rules",
    "fields",
    "confidence",
    "agent",
)

_SECTION_TITLES = {
    "overview": "任务概览",
    "shape": "输出表形态与粒度",
    "stages": "加工链路",
    "rules": "规则清单",
    "fields": "字段语义",
    "confidence": "可信度与边界",
    "agent": "给 Agent 的说明",
}

# Not a section: the one sub-switch of section 5. Passing it instead of ``fields`` keeps
# the closing "完整字段清单" table and drops the per-field subsections, which is what a
# 112-field task needs when the document is read by a person rather than chunked.
FIELDS_TABLE_ONLY = "fields_table"

SECTION_NAMES = (*SECTION_ORDER, FIELDS_TABLE_ONLY)

TAG_SQL = "SQL事实"
TAG_METADATA = "元数据事实"
TAG_SQL_AND_METADATA = "SQL事实+元数据事实"
TAG_STRUCTURAL = "结构推断"
# WI-2.2. The fifth evidence class, and the only one whose text this document did not
# compose: a comment is the SQL author speaking, not the statement. It never goes in a
# code span -- a code span in this document means "verbatim SQL identifier or
# expression", and the anti-fabrication scan reads exactly those.
TAG_SQL_COMMENT = "SQL注释"

WARN = "⚠"

UNKNOWN_COMMENT = "注释未知"

# WI-2.6. A comment the warehouse never carried, written back after somebody answered the
# open-questions list. The reader is told which of the two they are looking at, because
# "the catalog says so" and "the owner told us" are different kinds of claim.
COMMENT_SOURCE_PATCH = "patch"
PATCHED_COMMENT_SUFFIX = "（人工确认）"

# Said only where the SQL proved it (an IN list, an exhaustive CASE) -- and only about the
# enumerated values, never about a match shape that happens to sit on the same line.
VALUE_DOMAIN_CLOSED_NOTE = "（该列取值已被 SQL 证明封闭）"

# Section 3 folds only when a document is too long to read stage by stage. Below the
# threshold every stage is expanded, however repetitive it is.
STAGE_FOLD_THRESHOLD = 12

# Longest action summary kept in a folded group's table row.
ACTION_SUMMARY_LIMIT = 120

# Longest output-column list printed inline before it is counted instead.
OUTPUT_PREVIEW_LIMIT = 20

# WI-1g item B: how many `derive` actions one stage lists in full. A scope computing 24
# metrics by arithmetic turns the stage into a second copy of section 5 otherwise; past
# the threshold the names are counted and the first few are still expanded.
DERIVE_FOLD_THRESHOLD = 8
DERIVE_PREVIEW_COUNT = 3

# WI-1g item D2: how many consecutive value-carrying steps section 5 folds into one line.
# Below this they are printed as they are -- folding two steps saves nothing.
DERIVATION_FOLD_MINIMUM = 2

# The step types that carry a value unchanged, mirrored from `semantic_text` so the
# markdown's folding and the summary's "直接取自" agree on what "carries" means.
_PASS_THROUGH_STEP_TYPES = ("direct_projection", "union")

# A single-branch `union` step merges nothing: it is the contract's way of writing "this
# scope reads that union", and its restatement says so.
_SINGLE_BRANCH_UNION_TEXT = "合并 1 个分支"

# WI-1g item E6: how many rules a same-shaped family needs before section 4 folds it,
# and how many varying literals the folded row spells out before it counts them.
RULE_FAMILY_FOLD_MINIMUM = 3
RULE_FAMILY_VALUE_LIMIT = 6

# WI-2.12. What the dictionary says the codes in a condition mean. The column and the
# action suffix exist only when a corpus glossary answered something: an empty one would
# add a column of em dashes to every document that never asked for a dictionary.
# Read-only stand-in for "this document has no dictionary", so the renderers can take a
# lookup without a mutable default.
_NO_RULE_VALUES: Mapping = MappingProxyType({})

RULE_VALUE_COLUMN_TITLE = "取值含义"
RULE_VALUE_EQUALS = "＝"
ACTION_VALUE_PREFIX = "（取值："
ACTION_VALUE_SUFFIX = "）"
ACTION_VALUE_SEPARATOR = "；"
# Three fits at the end of a restatement line; past that the line would bury the action
# it is annotating, and section 4 lists every one of them anyway.
ACTION_VALUE_LIMIT = 3
ACTION_VALUE_OVERFLOW = "等 {count} 个，见规则表"
_VALUE_ANNOTATED_ACTIONS = frozenset({"filter", "having", "join"})

# WI-2.12. The corpus's meaning for this column NAME, printed only where the target table
# carries no comment of its own. Its own line and its own label: a term is what the
# warehouse calls this column elsewhere, not the comment this table is missing.
TERM_MEANING_PREFIX = "- 术语："
TERM_MEANING_COLUMN_TITLE = "术语"
CONFIRMED_MARK = "✓"

_NUMBER_LITERAL = re.compile(r"\d+")

_DIRECTORY_TARGET_PREFIX = "directory:"

# `fields[7].structural_role` and `fields[8].structural_role` are the same inference.
_ARRAY_INDEX = re.compile(r"\[\d+\]")

_SHAPE_LABELS = {
    "aggregated": "聚合型",
    "deduplicated": "去重型",
    "union_merge": "合并型",
    "enriched_projection": "关联补充型投影",
    "filtered_projection": "过滤投影型",
    "unknown": "未能判定",
}

_GRAIN_BASIS_LABELS = {
    "group_by": "GROUP BY 键",
    "distinct": "DISTINCT 输出列",
    "window_partition": "窗口分区键",
    "driving_table_rows": "主表行",
    "unknown": "未知",
}

# WI-1d: how the candidate-key line is worded, per `output_shape.key_confidence`.
_KEY_CONFIDENCE_NOTES = {
    "proven": "由{basis}保证输出内唯一",
    "candidate": "仅为候选，输入中无主键声明",
}

# WI-1e: how many physical columns the grain line will name before it defers to the JSON.
GRAIN_SOURCE_INLINE_LIMIT = 4

_ROLE_LABELS = {
    "driving": "主表",
    "merge_source": "MERGE 来源",
    "aggregate_source": "聚合来源",
    "dedup_source": "去重来源",
    "union_branch": "合并分支",
    "enrich": "关联补充",
    "rowset_only": "仅行集引用",
}

_ACTION_LABELS = {
    "join": "关联",
    "filter": "过滤",
    "aggregate": "聚合",
    "having": "HAVING 过滤",
    "window": "窗口",
    "distinct": "去重",
    "union": "合并",
    "lateral_view": "展开",
    "derive": "表达式派生",
    "case_when": "条件派生",
}

_RULE_KIND_LABELS = {
    "filter": "过滤",
    "having": "HAVING",
    "join_condition": "连接条件",
    "case_branch": "CASE 分支",
}

_FAN_OUT_LABELS = {
    "safe": "安全",
    "risk": f"{WARN} 有放大风险",
    "unknown": f"{WARN} 未知",
}

# WI-1f: the one governance finding section 6 gives its own line, mirrored from the
# profile builder so the two cannot disagree about which kind that is.
FINDING_OWN_LINE = "target_binding"

# WI-2.9 item A. 治理线索 lists the leads somebody has to act on; everything else the
# profile proved is counted in one line and left in the JSON. A finding with no severity
# at all (an older document read back from disk) is listed rather than counted -- losing
# a lead is the failure this section exists to prevent.
SEVERITY_INFO = "info"

INFORMATION_LINE = "- 信息项：{count}（见 semantic.json findings）"

# Which evidence class each governance lead restates. None of them is an inference: two
# tables filtered to different literals is what the SQL says, and a table without a
# comment is what the metadata says. An unknown kind falls back to the SQL label rather
# than being upgraded to a fact class it did not earn.
_FINDING_TAGS = {
    "alias_position_mismatch": TAG_SQL_AND_METADATA,
    "partition_literal_mismatch": TAG_SQL,
    "nondeterministic_function": TAG_SQL,
    "hardcoded_date_literal": TAG_SQL,
    "metadata_conflicts": TAG_METADATA,
    "target_binding": TAG_METADATA,
    "table_comment_missing": TAG_METADATA,
}

_PARTITION_MODE_LABELS = {
    "static": "静态分区",
    "dynamic": "动态分区",
    "mixed": "混合分区",
}

# Section 7, verbatim. The only lines in the document that restate no contract value.
AGENT_NOTES = (
    "本文档是**事实骨架**：每条内容都来自同目录 `lineage.json` / `diagnostics.json`，"
    "可按行尾的证据 id 回查。",
    "业务画像（业务实体、表类型的业务称呼、模块命名、任务的业务目标）不在本文档内，"
    "请按 `skills/scope-lineage/references/semantic-profile-prompt.md` 生成，并标 "
    "`LLM推断` / `待业务确认`。",
    f"任何未标 `{TAG_METADATA}` 的中文含义都不是业务定义：它要么是 SQL 结构的复述，"
    "要么是本文档的结构推断。",
)


def render_semantic_markdown(
    profile: dict,
    *,
    sections: Iterable[str] | None = None,
) -> str:
    """Render one semantic profile -- a statement profile or a task profile.

    ``sections`` restricts which numbered sections appear (names from ``SECTION_ORDER``,
    plus ``fields_table`` for section 5's table without its per-field subsections).
    Numbering never shifts, so a filtered document still calls section 5 "5.".
    """
    if profile.get("artifact_kind") == TASK_ARTIFACT_KIND:
        return _render_task_profile(profile, sections)
    selected = _selected_sections(sections)
    lines = _front_matter(profile)
    lines.append("")
    lines.append(f"# 任务语义描述 {_target_display(profile)}")
    renderers = {
        "overview": lambda: _render_overview(profile),
        "shape": lambda: _render_shape(profile),
        "stages": lambda: _render_stages(profile),
        "rules": lambda: _render_rules(profile),
        "fields": lambda: _render_fields(profile, selected),
        "confidence": lambda: _render_confidence(profile),
        "agent": _render_agent_notes,
    }
    for index, name in enumerate(SECTION_ORDER, start=1):
        if name not in selected:
            continue
        lines.append("")
        lines.append(f"## {index}. {_SECTION_TITLES[name]}")
        lines.extend(renderers[name]())
    lines.append("")
    return "\n".join(lines)


def _render_task_profile(profile: dict, sections: Iterable[str] | None) -> str:
    """A task document: one task-level header, then one full document per statement."""
    statements = profile.get("statements") or []
    produced = [str(table) for table in profile.get("produced_tables") or []]
    produced_text = "、".join(f"`{table}`" for table in produced) or "无"
    lines = [
        f"# 任务语义描述：{profile.get('task_id') or ''}",
        "",
        f"共 {len(statements)} 条写入语句；最终产出表：{produced_text}"
        f"（来自 `final_table_states`，已排除会话内关系与目录写入）。",
    ]
    for statement in statements:
        lines.append("")
        lines.append(f"## {statement.get('statement_id') or ''}")
        lines.append("")
        lines.append(render_semantic_markdown(statement, sections=sections))
    # A statement document already ends in a newline; a task with no write statement
    # (a DELETE-only script) would otherwise end mid-line.
    text = "\n".join(lines)
    return text if text.endswith("\n") else text + "\n"


# --------------------------------------------------------------------------- helpers


def _selected_sections(sections: Iterable[str] | None) -> set[str]:
    if sections is None:
        return set(SECTION_ORDER)
    chosen = set(sections)
    unknown = chosen - set(SECTION_NAMES)
    if unknown:
        raise ValueError(
            f"unknown sections {sorted(unknown)}; valid names: {list(SECTION_NAMES)}"
        )
    if FIELDS_TABLE_ONLY in chosen:
        chosen.add("fields")
    return chosen


def _front_matter(profile: dict) -> list[str]:
    task = profile.get("task") or {}
    entries = (
        ("doc_format", DOC_FORMAT),
        ("schema_version", profile.get("schema_version")),
        # the contract's top-level `task_id` is a name-based statement identifier
        ("task_name", task.get("task_name")),
        ("target_table", task.get("target_table")),
        ("stmt_kind", task.get("stmt_kind")),
        ("lineage_digest", profile.get("lineage_digest")),
    )
    lines = ["---"]
    for key, value in entries:
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    lines.append("---")
    return lines


def _target_display(profile: dict) -> str:
    """The mapping document's naming rule: a directory write is named as a directory.

    Composing ``<db>.<table>`` for a path target would publish a table id that no
    catalog declares.
    """
    target = str((profile.get("task") or {}).get("target_table") or "")
    if target.startswith(_DIRECTORY_TARGET_PREFIX):
        return f"（写入目录 {target[len(_DIRECTORY_TARGET_PREFIX):]}）"
    return target


def _tagged(text: str, tag: str, evidence: Sequence = ()) -> str:
    ids = [str(item) for item in evidence if item]
    if ids:
        return f"{text}（{tag}；证据 {', '.join(ids)}）"
    return f"{text}（{tag}）"


def _label_phrase(label: str) -> str:
    """A label with the space Chinese needs before a Latin word and not before a CJK one.

    ``依据 GROUP BY 键`` reads correctly; ``依据 主表行`` does not.
    """
    return f" {label}" if label[:1].isascii() else label


def _comment(value, source: str | None = None) -> str:
    """R8: a comment is quoted verbatim or declared missing -- never invented.

    WI-2.6: a comment that came back from a confirmed write-back says so. The suffix is
    the reader's answer to "who claims this" -- the metadata export, or the person who
    answered the question -- and it is the same distinction ``target_comment_source``
    carries in ``semantic.json``.
    """
    if not value:
        return UNKNOWN_COMMENT
    return f"{value}{PATCHED_COMMENT_SUFFIX}" if source == COMMENT_SOURCE_PATCH else str(value)


def _span(value) -> str:
    return f"`{_normalize_inline(str(value)).replace('`', '')}`"


def _join_spans(values: Iterable, empty: str = "无") -> str:
    rendered = "、".join(_span(value) for value in values)
    return rendered or empty


def _field_note(field: dict) -> str:
    """One ``table.column（comment）`` note, or the scope-level form when the contract
    could not pierce to a physical field."""
    column = field.get("column")
    if field.get("table"):
        suffix = "（经生成列）" if field.get("via_generated_column") else ""
        return (
            f"{_span(str(field['table']) + '.' + str(column))}"
            f"（{_comment(field.get('comment'))}）{suffix}"
        )
    # A CTE id is not a table, so the scope-level form never pretends to be one.
    return f"{_span(str(field.get('scope')) + '.' + str(column))}（scope 内部列）"


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ------------------------------------------------------------------ 1. 任务概览


_TARGET_PLACEMENT_FIELDS = (
    ("target_table_domain", "业务域"),
    ("target_table_project", "项目"),
    ("target_table_owner", "负责人"),
)


def _target_placement_text(task: dict) -> str:
    """``；业务域 …；项目 …`` for the facts the metadata states, and "" when it states none.

    Continues the target table's own parenthesis rather than opening a second one, and a
    fact the metadata omits is left out: a line of "未知" is noise the reader has to skip.
    """
    parts = [
        f"{label} {_normalize_inline(str(task[key]))}"
        for key, label in _TARGET_PLACEMENT_FIELDS
        if task.get(key)
    ]
    return f"；{'；'.join(parts)}" if parts else ""


def _render_overview(profile: dict) -> list[str]:
    task = profile.get("task") or {}
    target = str(task.get("target_table") or "")
    lines = [""]
    if target.startswith(_DIRECTORY_TARGET_PREFIX):
        target_text = f"写入目录 {_span(target[len(_DIRECTORY_TARGET_PREFIX):])}"
    else:
        target_text = (
            f"{_span(target)}（表注释：{_comment(task.get('target_table_comment'))}"
            f"{_target_placement_text(task)}）"
        )
    lines.append(_tagged(f"- 目标表：{target_text}", TAG_METADATA))
    lines.append(
        _tagged(
            f"- 语句类型：{task.get('stmt_kind')}；{_partition_text(task.get('partition'))}",
            TAG_SQL,
        )
    )
    source = task.get("target_metadata_source")
    lines.append(
        _tagged(f"- 目标表元数据来源：{source if source else '无'}", TAG_METADATA)
    )
    lines.extend(_instance_date_lines(task))
    lines.append(
        _tagged(
            f"- 结构摘要：{_normalize_inline(str(task.get('structural_summary') or ''))}",
            TAG_STRUCTURAL,
            ["scope_profile"],
        )
    )
    lines.extend(_downstream_lines(task))
    lines.extend(_meta_lines(task))
    lines.extend(_header_comment_lines(task))
    lines.extend(_render_inputs_table(profile.get("inputs") or []))
    return lines


def _instance_date_lines(task: dict) -> list[str]:
    """WI-2.9 item A: which day this instance reads, before any line calls it a problem.

    Absent when no filter pins a day: a parameterised statement reads whatever the
    scheduler substitutes, and printing "取数日：无" would read as "it reads nothing".
    Two days are listed with the gap between them, because a statement reading a day and
    the day before is a口径 the reader has to know -- and is not, by itself, a defect.
    """
    days = [str(item) for item in task.get("instance_dates") or []]
    if not days:
        return []
    gap = _instance_date_gap(days)
    return [_tagged(f"- 取数日：{'、'.join(days)}{gap}", TAG_SQL)]


def _instance_date_gap(days: Sequence[str]) -> str:
    """"（相差 N 天）" across the widest pair, or "" for one day or an unmeasured pair."""
    if len(days) < 2:
        return ""
    spans = [
        predicate_literal_day_offset(f"d = '{days[0]}'", f"d = '{day}'")
        for day in days[1:]
    ]
    measured = [abs(item) for item in spans if item is not None]
    return f"（相差 {max(measured)} 天）" if len(measured) == len(spans) else ""


def _downstream_lines(task: dict) -> list[str]:
    """WI-2.5: who reads this target, from the corpus's table cards.

    Absent without ``describe --tables``, because "no corpus was supplied" and "the
    corpus proves nobody reads this" are different answers and must not render alike.
    """
    if "downstream_consumers" not in task:
        return []
    consumers = task.get("downstream_consumers") or []
    if not consumers:
        return [_tagged("- 下游消费：本语料内无任务读取该表", TAG_SQL, ["tables.json"])]
    rendered = "；".join(
        f"{_span(item.get('task'))}"
        f"（{_ROLE_LABELS.get(str(item.get('role_in_task')), '未知')}，"
        f"用到 {_join_spans(item.get('columns') or [], '—')}）"
        for item in consumers
    )
    return [_tagged(f"- 下游消费：{rendered}", TAG_SQL, ["tables.json"])]


def _meta_lines(task: dict) -> list[str]:
    """One line of task metadata, or nothing when no task JSON supplied any."""
    meta = task.get("meta") or {}
    parts = [
        f"{label} {_normalize_inline(str(meta[key]))}"
        for key, label in _TASK_META_ITEMS
        if meta.get(key)
    ]
    if not parts:
        return []
    return [_tagged(f"- 任务元信息：{'；'.join(parts)}", TAG_METADATA, ["task_meta"])]


def _header_comment_lines(task: dict) -> list[str]:
    """The statement's header comments, quoted verbatim, one blockquote line each.

    Rendered outside a code span deliberately: a span in this document means verbatim
    SQL, and free text put in one would be read (by a person and by the anti-fabrication
    scan) as an identifier the statement carries.
    """
    comments = [str(item) for item in task.get("header_comments") or []]
    if not comments:
        return []
    lines = ["", f"{HEADER_COMMENTS_TITLE}（{TAG_SQL_COMMENT}）：", ""]
    lines.extend(f"> {_normalize_inline(comment)}" for comment in comments)
    return lines


def _partition_text(partition: dict | None) -> str:
    partition = partition or {}
    columns = [str(column) for column in partition.get("columns") or []]
    if not columns:
        return "无分区"
    mode = partition.get("mode")
    label = _PARTITION_MODE_LABELS.get(str(mode), f"{mode} 分区" if mode else "分区")
    spec = partition.get("spec") or {}
    # A dynamic partition column has no value in the spec, and the contract says so with
    # `null`. Writing `dt = None` would state a literal the statement never carries, so
    # only a column the spec gives a value gets an `=`; a mixed spec keeps both forms.
    rendered = [
        f"{column} = {_expr_span(spec[column])}"
        if spec.get(column) is not None
        else str(column)
        for column in [*columns, *(key for key in spec if key not in columns)]
    ]
    return f"{label} {'、'.join(rendered)}"


def _render_inputs_table(inputs: Sequence[dict]) -> list[str]:
    if not inputs:
        return ["", "- 输入表：无物理来源表。（SQL事实）"]
    # WI-2.5: the "what is a row" column exists only when a corpus answered it.
    carded = any("card" in item for item in inputs)
    head = "| 输入表 | 表注释 | 角色 | 使用列 / 全宽 | 元数据 | 读取 scope |"
    rule = "| --- | --- | --- | --- | --- | --- |"
    if carded:
        head += " 一行是什么（来自生产任务） |"
        rule += " --- |"
    lines = [
        "",
        f"共 {len(inputs)} 张输入表（角色为结构推断，其余为 SQL/元数据事实）：",
        "",
        head,
        rule,
    ]
    for item in inputs:
        role = item.get("role_in_task")
        role_text = (
            f"{_ROLE_LABELS.get(str(role), '未知')}（{role}）" if role else "未知"
        )
        width = item.get("table_column_count")
        used = len(item.get("used_columns") or [])
        cells = [
            _cell(_span(item.get("table"))),
            _cell(_comment(item.get("comment"), item.get("comment_source"))),
            _cell(role_text),
            _cell(f"{used} / {width if width is not None else '未知'}"),
            _cell(_metadata_state(item.get("metadata_complete"))),
            _cell(_join_spans(item.get("read_by_scopes") or [], "—")),
        ]
        if carded:
            cells.append(_cell(_input_card_text(item.get("card"))))
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _input_card_text(card: dict | None) -> str:
    """One cell: the upstream task's own grain sentence, or why there is none."""
    if not card:
        return f"{WARN} 本语料内无生产任务"
    return (
        f"{_normalize_inline(str(card.get('grain_text') or ''))}"
        f"（来自 {card.get('produced_by_task')}）"
    )


def _metadata_state(complete) -> str:
    if complete is None:
        return f"{WARN} 未知"
    return "完整" if complete else f"{WARN} 不完整"


# ----------------------------------------------------------- 2. 输出表形态与粒度


def _render_shape(profile: dict) -> list[str]:
    shape = profile.get("output_shape") or {}
    name = str(shape.get("shape") or "unknown")
    label = _SHAPE_LABELS.get(name, name)
    marker = f"{WARN} " if name == "unknown" else ""
    lines = [
        "",
        _tagged(
            f"- {marker}形态：{label}（{name}）",
            TAG_STRUCTURAL,
            shape.get("shape_evidence") or [],
        ),
        _grain_line(shape.get("grain") or {}),
    ]
    lines.append(_candidate_key_line(shape))
    lines.append(
        _tagged(
            "- 分区列："
            + _join_spans(shape.get("partition_columns") or [], "无")
            + "；分区列不计入候选键",
            TAG_METADATA,
        )
    )
    lines.extend(_render_fan_out(shape.get("fan_out_risks") or []))
    return lines


def _candidate_key_line(shape: dict) -> str:
    """The keys as *target* columns, worded by ``key_confidence`` (WI-1d, WI-1e).

    A GROUP BY key set really is unique in the output, and calling it "only a candidate"
    understated a fact the SQL proves. Under a static or mixed partition spec the
    uniqueness holds inside the partition the statement writes, which the line says.
    """
    keys = shape.get("candidate_keys") or []
    confidence = str(shape.get("key_confidence") or "none")
    if confidence == "proven_unexposed":
        return _unexposed_key_line(shape, keys)
    if not keys or confidence not in _KEY_CONFIDENCE_NOTES:
        return _tagged("- 候选键：无（结构未证明任一键唯一）", TAG_STRUCTURAL)
    note = _KEY_CONFIDENCE_NOTES[confidence].format(basis=_basis_phrase(shape))
    scope = "（分区内）" if shape.get("partition_columns") else ""
    head = "键" if confidence == "proven" else "候选键"
    return _tagged(
        f"- {head}：目标表列 {_join_spans(keys)}——{note}{scope}"
        f"（key_confidence={confidence}）",
        TAG_STRUCTURAL,
    )


def _unexposed_key_line(shape: dict, keys: Sequence[str]) -> str:
    """The governance finding: the keys are proven, the written columns are not.

    ``proven_unexposed`` is the one case where naming the target columns would mislead,
    so the line names the key that never arrived first and the columns' weakness second.
    """
    missing = _key_labels(shape.get("unexposed_keys") or [])
    written = (
        f"目标表列 {_join_spans(keys)} 不能唯一标识一行"
        if keys
        else "目标表列中无任何键，不能唯一标识一行"
    )
    return _tagged(
        f"- {WARN} 键：{_basis_phrase(shape).strip()} {_join_spans(missing)} 未输出到目标表；"
        f"{written}（key_confidence=proven_unexposed）",
        TAG_STRUCTURAL,
    )


def _basis_phrase(shape: dict) -> str:
    basis = str((shape.get("grain") or {}).get("basis") or "unknown")
    return _label_phrase(_GRAIN_BASIS_LABELS.get(basis, basis))


def _key_labels(keys: Sequence[dict]) -> list[str]:
    """A logical key reads as ``scope.column``, or as its expression when unprojected."""
    return [
        f"{key.get('scope_id')}.{key['name']}"
        if key.get("name")
        else str(key.get("expression") or key.get("scope_id"))
        for key in keys
    ]


def _grain_source_text(keys: Sequence[dict]) -> str:
    """The physical columns behind the logical keys, inlined only while they stay short."""
    sources = _dedupe_sources(keys)
    if not sources:
        return ""
    if len(sources) <= GRAIN_SOURCE_INLINE_LIMIT:
        return f"（物理来源：{_join_spans(sources)}）"
    return f"（物理来源 {len(sources)} 列见 semantic.json grain.keys[].physical_sources）"


def _dedupe_sources(keys: Sequence[dict]) -> list[str]:
    ordered: list[str] = []
    for key in keys:
        for source in key.get("physical_sources") or []:
            name = f"{source.get('table')}.{source.get('column')}"
            if name not in ordered:
                ordered.append(name)
    return ordered


def _grain_line(grain: dict) -> str:
    """The grain in one line. ``evidence`` is the pierce path, so the table is its tail."""
    basis = str(grain.get("basis") or "unknown")
    label = _GRAIN_BASIS_LABELS.get(basis, basis)
    keys = grain.get("keys") or []
    evidence = grain.get("evidence") or []
    via = [str(item) for item in grain.get("via_scopes") or []]
    through = f"，经 {' → '.join(_span(item) for item in via)} 穿透" if via else ""
    if keys:
        text = (
            f"- 粒度：一行对应一组 {_join_spans(_key_labels(keys))}"
            f"{_grain_source_text(keys)}"
            f"（依据{_label_phrase(label)}，basis={basis}{through}）"
        )
    elif basis == "driving_table_rows":
        text = (
            f"- 粒度：一行对应 {_span(evidence[-1]) if evidence else '未知'} 的一行"
            f"（依据{_label_phrase(label)}，basis={basis}{through}）"
        )
    else:
        text = f"- {WARN} 粒度：未能判定（basis={basis}{through}）"
    return _tagged(text, TAG_STRUCTURAL, evidence)


def _render_fan_out(risks: Sequence[dict]) -> list[str]:
    """One line per JOIN on the grain path. A non-ROOT join names the scope it sits in.

    The risks are no longer ROOT's alone, so "LEFT JOIN x：安全" would leave the reader
    guessing which stage that join belongs to.
    """
    grain = [item for item in risks if item.get("path") not in _VALUE_ONLY_PATHS]
    argument = [item for item in risks if item.get("path") in _VALUE_ONLY_PATHS]
    if not grain:
        lines = ["- 行数放大风险：粒度链路上无 JOIN，不存在连接放大。（结构推断）"]
    else:
        lines = ["- 行数放大风险：", *[f"  {_fan_out_line(item)}" for item in grain]]
    if argument:
        lines.append(f"- {FAN_OUT_ARGUMENT_HEADING}")
        lines.extend(f"  {_fan_out_line(item)}" for item in argument)
    return lines


def _fan_out_line(risk: dict) -> str:
    status = str(risk.get("status") or "unknown")
    scope = str(risk.get("scope_id") or "")
    where = f"{_span(scope)} 中的 " if scope and scope != "ROOT" else ""
    return _tagged(
        f"- {where}{risk.get('join_type')} JOIN {_span(risk.get('right'))}："
        f"{_FAN_OUT_LABELS.get(status, status)}（{status}）"
        f"——{_normalize_inline(str(risk.get('reason') or ''))}",
        TAG_STRUCTURAL,
        [risk.get("logic_block_id")],
    )


# ------------------------------------------------------------------ 3. 加工链路


def _render_stages(profile: dict) -> list[str]:
    stages = profile.get("stages") or []
    if not stages:
        return ["", "- 本语句没有可展开的加工阶段。（SQL事实）"]
    values = _rule_value_lookup(profile)
    if len(stages) <= STAGE_FOLD_THRESHOLD:
        lines = ["", f"共 {len(stages)} 个阶段，按拓扑序逐个展开。"]
        for index, stage in enumerate(stages, start=1):
            lines.extend(
                _render_stage(
                    stage,
                    index,
                    previous=stages[index - 2] if index > 1 else None,
                    values=values,
                )
            )
        return lines
    return _render_folded_stages(stages, values)


def _rule_value_lookup(profile: Mapping) -> dict[tuple, list]:
    """``(evidence, expression) -> value meanings``: the rule behind one restated action.

    WI-2.12. A stage action and the rule it came from are two views of one logic block,
    and the block id alone does not separate the conjuncts a WHERE was split into -- so
    the condition text joins the key. Without it, "过滤 A" would show the codes of "过滤 B".
    """
    lookup: dict[tuple, list] = {}
    for statement in profile.get("statements") or [profile]:
        for rule in statement.get("rules") or []:
            meanings = [
                item
                for item in _glossary_values.rule_value_meanings(rule)
                if item.get("meaning")
            ]
            if meanings:
                key = (str(rule.get("evidence")), str(rule.get("expression")))
                lookup.setdefault(key, []).extend(meanings)
    return lookup


def _fold_key(stage: dict):
    """ROOT is keyed by itself: the statement's own projection is never a group member."""
    if str(stage.get("scope_id")) == "ROOT":
        return ("root", "ROOT")
    return ("signature", str(stage.get("pattern_signature")))


def _render_folded_stages(stages: Sequence[dict], values: Mapping = _NO_RULE_VALUES) -> list[str]:
    groups: dict = {}
    for index, stage in enumerate(stages, start=1):
        groups.setdefault(_fold_key(stage), []).append((index, stage))
    lines = [
        "",
        f"共 {len(stages)} 个阶段，超过 {STAGE_FOLD_THRESHOLD} 个；"
        f"`pattern_signature` 相同的阶段折叠为一张表（表中列出全部 scope_id），"
        "并展开其中第一个作代表。ROOT 永远展开。",
    ]
    emitted: set = set()
    for index, stage in enumerate(stages, start=1):
        key = _fold_key(stage)
        if key in emitted:
            continue
        emitted.add(key)
        members = groups[key]
        if len(members) >= 2:
            lines.extend(_render_folded_group(members, values))
        else:
            lines.extend(_render_stage(stage, index, values=values))
    return lines


def _render_folded_group(members: Sequence[tuple], values: Mapping = _NO_RULE_VALUES) -> list[str]:
    """One table for a family of same-shaped stages, keyed by their topological number.

    WI-1g item E2: the heading used to say "阶段 2 等 3 个同模式阶段" and the table gave
    only ``scope_id``, so a reader who had just read "阶段 6" could not tell whether it
    was in this group. Every member's ordinal is now in the heading and in its row.
    """
    signature = str(members[0][1].get("pattern_signature"))
    numbers = "、".join(str(index) for index, _ in members)
    lines = [
        "",
        f"### 阶段 {numbers} 等 {len(members)} 个同模式阶段",
        "",
        f"以下 {len(members)} 个阶段模式相同（{_expr_span(signature)}），展开第一个作代表。",
        "",
        "| 阶段 | scope_id | 角色 | 直接输入 | 动作摘要 | 输出列数 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for index, stage in members:
        summary = "；".join(
            str(action.get("text") or action.get("expression") or "")
            for action in stage.get("actions") or []
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    _cell(_span(stage.get("scope_id"))),
                    _cell(str(stage.get("role") or "未知")),
                    _cell(_join_spans(stage.get("direct_inputs") or [], "—")),
                    _cell(_truncate(_normalize_inline(summary), ACTION_SUMMARY_LIMIT) or "—"),
                    _cell(str(stage.get("output_count"))),
                ]
            )
            + " |"
        )
    first, number = members[0][1], members[0][0]
    lines.extend(_render_stage(first, number, heading_level="####", values=values))
    return lines


def _render_stage(
    stage: dict,
    index: int,
    *,
    heading_level: str = "###",
    previous: dict | None = None,
    values: Mapping = _NO_RULE_VALUES,
) -> list[str]:
    scope_id = stage.get("scope_id")
    lines = [
        "",
        f"{heading_level} 阶段 {index}：{stage.get('name')}"
        f"（{_span(scope_id)}，角色 {stage.get('role') or '未知'}）",
        "",
        _tagged(
            f"- 直接输入：{_join_spans(stage.get('direct_inputs') or [], '无')}", TAG_SQL
        ),
        _tagged(
            "- 直接读取物理表："
            + _join_spans(stage.get("direct_source_tables") or [], "无（仅读上游 scope）"),
            TAG_SQL,
        ),
    ]
    if not _upstream_is_redundant(stage, previous):
        lines.append(
            _tagged(
                "- 上游物理表（来源边界）："
                + _join_spans(stage.get("upstream_physical_tables") or [], "无"),
                TAG_SQL,
            )
        )
    lines.extend(_render_stage_actions(stage.get("actions") or [], values))
    lines.append(_outputs_line(stage))
    return lines


def _upstream_is_redundant(stage: dict, previous: dict | None) -> bool:
    """WI-1g item E5: the source boundary line is dropped when it repeats a neighbour.

    It exists to separate "reads this table" from "can be traced back to this table". A
    stage whose boundary is exactly its own direct inputs, or exactly the boundary the
    line above already stated, restates one of them instead of separating them. The fact
    stays in ``semantic.json``; only the line goes.
    """
    upstream = {str(item) for item in stage.get("upstream_physical_tables") or []}
    if upstream in (
        {str(item) for item in stage.get("direct_inputs") or []},
        {str(item) for item in stage.get("direct_source_tables") or []},
    ):
        return True
    if previous is None:
        return False
    return upstream == {
        str(item) for item in previous.get("upstream_physical_tables") or []
    }


def _render_stage_actions(actions: Sequence[dict], values: Mapping = _NO_RULE_VALUES) -> list[str]:
    if not actions:
        return ["- 动作：无（该 scope 只做投影）。（SQL事实）"]
    lines = ["- 动作："]
    derives = [action for action in actions if str(action.get("type")) == "derive"]
    fold = len(derives) > DERIVE_FOLD_THRESHOLD
    hidden = {id(action) for action in derives[DERIVE_PREVIEW_COUNT:]} if fold else set()
    for action in actions:
        if fold and action is derives[0]:
            lines.append("  " + _tagged(_derive_fold_line(derives), TAG_SQL))
        if id(action) in hidden:
            continue
        lines.append(
            "  "
            + _tagged(
                _action_body(action, values),
                str(action.get("tag") or TAG_SQL),
                [action.get("evidence"), action.get("consumed_by")],
            )
        )
    return lines


def _action_body(action: dict, values: Mapping = _NO_RULE_VALUES) -> str:
    kind = str(action.get("type"))
    label = _ACTION_LABELS.get(kind, kind)
    if action.get("intent"):
        label = f"{label}（意图 {action['intent']}）"
    if action.get("column"):
        label = f"{label} {_span(action['column'])}"
    text = action.get("text")
    body = (
        _normalize_inline(str(text))
        if text
        else _expr_span(action.get("expression") or "")
    )
    return (
        f"- {label}：{body}{_action_value_suffix(action, values)}"
        f"{_comment_suffix(action.get('sql_comments'))}"
    )


def _action_value_suffix(action: Mapping, values: Mapping) -> str:
    """``（取值：'01'＝人工队列）`` on the restatement of a condition that pins codes.

    WI-2.12. The restatement is where a reader learns what the stage does, and "只保留
    queue_code 为 '01' 的行" is a sentence nobody can act on until somebody says what
    '01' is. Only the answered codes are printed, and only for the actions that compare
    a column against one.
    """
    if str(action.get("type")) not in _VALUE_ANNOTATED_ACTIONS:
        return ""
    items = values.get((str(action.get("evidence")), str(action.get("expression")))) or []
    if not items:
        return ""
    shown = [_rule_value_text(item) for item in items[:ACTION_VALUE_LIMIT]]
    if len(items) > ACTION_VALUE_LIMIT:
        shown.append(ACTION_VALUE_OVERFLOW.format(count=len(items)))
    body = _normalize_inline(ACTION_VALUE_SEPARATOR.join(shown))
    return f"{ACTION_VALUE_PREFIX}{body}{ACTION_VALUE_SUFFIX}"


def _comment_suffix(comments) -> str:
    """``（注释：… SQL注释）`` for a line that has one, empty string for a line that does not.

    Carries its own label rather than borrowing the line's: the sentence before it is a
    restatement of the contract and the text after it is a quotation, and one evidence
    class cannot cover both.
    """
    quoted = [_normalize_inline(str(item)) for item in comments or [] if str(item).strip()]
    if not quoted:
        return ""
    return f"（注释：{'；'.join(quoted)}；{TAG_SQL_COMMENT}）"


def _derive_fold_line(derives: Sequence[dict]) -> str:
    """WI-1g item B: 24 arithmetic derivations are counted, not listed one per line.

    The first few stay expanded below this line, and ``semantic.json`` keeps every one
    of them -- the markdown folds, it never drops.
    """
    names = "、".join(
        _span(action.get("column")) for action in derives[:DERIVE_PREVIEW_COUNT]
    )
    return (
        f"- 派生 {len(derives)} 列：{names}…"
        f"（前 {DERIVE_PREVIEW_COUNT} 条展开，完整清单见 semantic.json stages[].actions[]）"
    )


def _outputs_line(stage: dict) -> str:
    outputs = [str(name) for name in stage.get("outputs") or []]
    count = stage.get("output_count")
    if not outputs:
        return _tagged("- 输出：0 列", TAG_SQL)
    if len(outputs) > OUTPUT_PREVIEW_LIMIT:
        preview = "、".join(_span(name) for name in outputs[:OUTPUT_PREVIEW_LIMIT])
        return _tagged(f"- 输出：{count} 列（前 {OUTPUT_PREVIEW_LIMIT} 个：{preview}…）", TAG_SQL)
    return _tagged(f"- 输出：{count} 列（{'、'.join(_span(name) for name in outputs)}）", TAG_SQL)


# ------------------------------------------------------------------ 4. 规则清单


def _render_rules(profile: dict) -> list[str]:
    rules = profile.get("rules") or []
    if not rules:
        return ["", "- 本语句没有过滤、连接或 CASE 规则。（SQL事实）"]
    summary = _rule_kind_summary(rules)
    families = _rule_families(rules)
    folded = {
        rule["rule_id"]: family
        for family in families
        for rule in family[1:]
    }
    valued = _rules_carry_a_meaning(rules)
    rows = _rule_rows(rules, families, folded, valued)
    note = (
        f"；其中 {len(families)} 组同构规则已折叠（semantic.json 不折叠）"
        if families
        else ""
    )
    values_column = f" {RULE_VALUE_COLUMN_TITLE} |" if valued else ""
    return [
        "",
        f"共 {len(rules)} 条规则（{summary}）{note}；条件为 SQL 原文，字段注释为元数据事实。",
        "",
        "| 规则 | 类型 | 阶段 | 条件 |"
        + values_column
        + " 涉及字段（注释） | SQL注释 | 分区过滤 | 证据 |",
        "| --- | --- | --- | --- |"
        + (" --- |" if valued else "")
        + " --- | --- | --- | --- |",
        *rows,
    ]


def _rules_carry_a_meaning(rules: Sequence[Mapping]) -> bool:
    """WI-2.12: the 取值含义 column exists once the dictionary has ANSWERED something.

    A glossary that merely recognises the codes would add a column of em dashes to every
    rule table in the corpus, which tells a reader nothing they did not already know.
    """
    return any(
        item.get("meaning")
        for rule in rules
        for item in _glossary_values.rule_value_meanings(rule)
    )


def _rule_rows(
    rules: Sequence[dict], families: Sequence[Sequence[dict]], folded: Mapping, valued: bool
) -> list[str]:
    """One row per rule, except that a folded family answers with a single row."""
    rows = []
    for rule in rules:
        if rule.get("rule_id") in folded:
            continue
        family = next((item for item in families if item[0] is rule), None)
        rows.append(
            _rule_family_row(family, valued) if family else _rule_row(rule, valued)
        )
    return rows


def _rule_kind_summary(rules: Sequence[Mapping]) -> str:
    """``过滤 6 条、连接条件 2 条`` -- the table's own census, in a stable order."""
    counts: dict[str, int] = {}
    for rule in rules:
        counts[str(rule.get("kind"))] = counts.get(str(rule.get("kind")), 0) + 1
    return "、".join(
        f"{_RULE_KIND_LABELS.get(kind, kind)} {counts[kind]} 条" for kind in sorted(counts)
    )


def _rule_value_cell(rules: Sequence[Mapping]) -> str:
    """``'01'＝人工队列；'07'＝? 自动队列`` -- only the codes somebody has answered."""
    texts = _dedupe_text(
        _rule_value_text(item)
        for rule in rules
        for item in _glossary_values.rule_value_meanings(rule)
        if item.get("meaning")
    )
    return _normalize_inline("；".join(texts)) or "—"


def _rule_value_text(item: Mapping) -> str:
    """One code and its meaning, candidates marked exactly as ``- 取值：`` marks them."""
    return (
        f"{_glossary_values.displayed_value(item)}{RULE_VALUE_EQUALS}"
        f"{_glossary_values.meaning_text(item.get('meaning'))}"
    )


def _rule_families(rules: Sequence[dict]) -> list[list[dict]]:
    """Groups of rules that differ only in their numeric literals (WI-1g item E6).

    A task that filters twelve hour buckets writes twelve rules whose only difference is
    ``9``, ``10``, … ``20``. Listing each one gives the reader twelve near-identical
    lines to diff by eye; one templated line plus the values does not lose a fact, and
    ``semantic.json`` keeps all twelve either way.
    """
    grouped: dict[tuple, list[dict]] = {}
    order: list[tuple] = []
    for rule in rules:
        expression = str(rule.get("expression") or "")
        template = _NUMBER_LITERAL.sub("N", expression)
        if template == expression:
            continue
        key = (str(rule.get("kind")), str(rule.get("scope_id")), template)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(rule)
    return [grouped[key] for key in order if len(grouped[key]) >= RULE_FAMILY_FOLD_MINIMUM]


def _rule_family_row(family: Sequence[dict], valued: bool = False) -> str:
    kind = str(family[0].get("kind"))
    partitions = {rule.get("is_partition_filter") for rule in family}
    partition = partitions.pop() if len(partitions) == 1 else None
    notes = _dedupe_text(note for rule in family for note in _rule_field_notes(rule))
    return (
        "| "
        + " | ".join(
            [
                _cell(f"{_rule_id_range(family)}（{len(family)} 条）"),
                _cell(f"{_RULE_KIND_LABELS.get(kind, kind)}（{kind}）"),
                _cell(_span(family[0].get("scope_id"))),
                _cell(_rule_family_condition(family)),
                *([_cell(_rule_value_cell(family))] if valued else []),
                _cell(_truncate("、".join(notes), ACTION_SUMMARY_LIMIT) or "—"),
                _cell(
                    _rule_comment_text(
                        {"sql_comments": _dedupe_text(
                            comment
                            for rule in family
                            for comment in rule.get("sql_comments") or []
                        )}
                    )
                ),
                _cell("是" if partition else ("否" if partition is False else "—")),
                _cell(f"{_span(family[0].get('evidence'))} 等 {len(family)} 条"),
            ]
        )
        + " |"
    )


def _rule_id_range(family: Sequence[dict]) -> str:
    first = str(family[0].get("rule_id"))
    last = str(family[-1].get("rule_id"))
    return f"{first}–{last.rpartition(':')[2] or last}"


def _rule_family_condition(family: Sequence[dict]) -> str:
    template = _NUMBER_LITERAL.sub("N", str(family[0].get("expression") or ""))
    values = [_NUMBER_LITERAL.findall(str(rule.get("expression") or "")) for rule in family]
    if any(len(item) != 1 for item in values):
        return f"{_expr_span(template)}（各条取值见 semantic.json rules[]）"
    flat = _dedupe_text(item[0] for item in values)
    if len(flat) > RULE_FAMILY_VALUE_LIMIT:
        listed = f"{flat[0]}…{flat[-1]}（{len(flat)} 个）"
    else:
        listed = "、".join(flat)
    return f"{_expr_span(template)}（N 取 {listed}）"


def _dedupe_text(values: Iterable[str]) -> list[str]:
    return unique_ordered(values)


def _rule_row(rule: dict, valued: bool = False) -> str:
    kind = str(rule.get("kind"))
    partition = rule.get("is_partition_filter")
    return (
        "| "
        + " | ".join(
            [
                _cell(str(rule.get("rule_id"))),
                _cell(f"{_RULE_KIND_LABELS.get(kind, kind)}（{kind}）"),
                _cell(_span(rule.get("scope_id"))),
                _cell(_rule_condition(rule)),
                *([_cell(_rule_value_cell([rule]))] if valued else []),
                _cell(_rule_fields_text(rule)),
                _cell(_rule_comment_text(rule)),
                _cell("是" if partition else ("否" if partition is False else "—")),
                _cell(_span(rule.get("evidence"))),
            ]
        )
        + " |"
    )


def _rule_comment_text(rule: dict) -> str:
    """The author's comment on this rule, verbatim, or an em dash when there is none.

    No code span: it is prose, and a code span here would put free text where the
    document's grammar promises SQL.
    """
    comments = [
        _normalize_inline(str(item))
        for item in rule.get("sql_comments") or []
        if str(item).strip()
    ]
    return "；".join(comments) or "—"


def _rule_condition(rule: dict) -> str:
    """The condition verbatim; a CASE is shown as its branch list, which is the same
    fact in the form a reader can scan."""
    if rule.get("kind") == "case_branch" and rule.get("branches") is not None:
        parts = [
            f"{branch.get('when')} → {branch.get('then')}"
            for branch in rule.get("branches") or []
        ]
        if rule.get("else") is not None:
            parts.append(f"否则 {rule['else']}")
        if parts:
            return _expr_span("；".join(parts))
    expression = rule.get("expression")
    if expression is None:
        return "—"
    return _expr_span(expression)


def _rule_fields_text(rule: dict) -> str:
    return "、".join(_rule_field_notes(rule)) or "—"


def _rule_field_notes(rule: dict) -> list[str]:
    return [
        _field_note(field)
        for field in [
            *(rule.get("fields") or []),
            *(rule.get("extra_condition_fields") or []),
            *(rule.get("scope_fields") or []),
        ]
    ]


# ------------------------------------------------------------------ 5. 字段语义


def _render_fields(profile: dict, selected: set) -> list[str]:
    """WI-1f: the whole list first, then the per-field subsections.

    A reader (or an agent) asking "what are the fields and what do they mean" gets the
    answer in one table at the top of the section instead of after N subsections, and
    the subsections stay for the field they then want in full.
    """
    fields = profile.get("fields") or []
    if not fields:
        return ["", "- 本语句没有目标字段。（SQL事实）"]
    lines = ["", f"共 {len(fields)} 个目标字段。"]
    lines.extend(_render_field_table(fields))
    if "fields" in selected and FIELDS_TABLE_ONLY not in selected:
        for field in fields:
            lines.extend(_render_field(field))
    return lines


def _render_field(field: dict) -> list[str]:
    comment = field.get("target_comment")
    lines = [
        "",
        f"### 字段 {field.get('column_label')}{_sql_alias_note(field.get('sql_alias'))}",
        "",
        # WI-1f: the one-sentence meaning leads, unlabelled, because it is the line a
        # reader stops at. Its own facts keep their labels on the lines below it.
        f"- 语义：{_normalize_inline(str(field.get('summary') or ''))}",
        *_render_metric_card(field),
        *_field_comment_lines(field),
        *_value_domain_lines(field),
        _tagged(
            f"- 目标注释：{_comment(comment, field.get('target_comment_source'))}",
            TAG_METADATA,
        ),
        *_term_meaning_lines(field),
        _tagged(f"- 类型：{field.get('type') or '未知'}", TAG_METADATA),
        _tagged(f"- 来源：{_sources_text(field)}", _sources_tag(field)),
        _tagged(
            f"- 结构角色：{field.get('structural_role') or '未知'}"
            f"（末步变换 {field.get('transform')}）",
            TAG_STRUCTURAL,
            [field.get("mapping_chain_id")],
        ),
    ]
    lines.extend(_render_derivation(field))
    lines.append(
        _tagged(f"- 最终表达式：{_expr_span(field.get('expression') or '')}", TAG_SQL)
    )
    lines.append(_trace_line(field))
    return lines


def _term_meaning_lines(field: Mapping) -> list[str]:
    """``- 术语：支付状态（人工确认）`` -- the corpus's meaning for this column NAME.

    WI-2.12. Present only where ``目标注释`` is empty, and never folded into that line: a
    term is what the warehouse calls this name elsewhere, confirmed by a person, while
    the line above it reports what THIS table's metadata says. Merging the two would
    publish a comment the catalog does not have.
    """
    text = (field.get("term_meaning") or {}).get("text")
    if not text:
        return []
    return [
        _tagged(
            f"{TERM_MEANING_PREFIX}{_normalize_inline(str(text))}"
            f"{PATCHED_COMMENT_SUFFIX}",
            TAG_METADATA,
        )
    ]


def _value_domain_lines(field: dict) -> list[str]:
    """``- 取值：`` -- the constants this column takes, and who vouched for each meaning.

    WI-2.4. The values are a SQL fact and the line is tagged as one; a meaning is not,
    so it is written inside the value with its own three-state marker (confirmed, ``?``
    candidate, 待确认) rather than letting the line's tag vouch for it.

    WI-2.4b. Match shapes (``LIKE`` / ``RLIKE``) trail the line under their own label:
    printed in the enumeration they read as values the column takes, which is the one
    thing ``col LIKE '%UNIT_OUT_%'`` does not say.
    """
    domain = field.get(_glossary_values.VALUE_DOMAIN_KEY) or []
    if not domain:
        return []
    evidence = sorted({item for entry in domain for item in entry.get("seen_in") or []})
    return [_tagged(f"- 取值：{_value_domain_body(domain)}", TAG_SQL, evidence)]


def _value_domain_body(domain: list) -> str:
    parts = []
    values = _glossary_values.enum_entries(domain)
    if values:
        rendered = _glossary_values.value_domain_text(
            values,
            _glossary_values.VALUE_DOMAIN_LINE_LIMIT,
            _glossary_values.VALUE_DOMAIN_OVERFLOW_NOTE,
        )
        closed = VALUE_DOMAIN_CLOSED_NOTE if _glossary_values.is_closed_domain(domain) else ""
        parts.append(_normalize_inline(rendered) + closed)
    patterns = _glossary_values.pattern_domain_text(domain)
    if patterns:
        parts.append(
            _glossary_values.VALUE_DOMAIN_PATTERN_PREFIX + _normalize_inline(patterns)
        )
    return "；".join(parts)


def _field_comment_lines(field: dict) -> list[str]:
    """``- 注释：…`` for a field the author commented on, nothing otherwise.

    Separate from ``- 目标注释：`` on purpose: that line is the table's column comment,
    an element of the warehouse metadata, while this one is what the SQL author wrote in
    the statement. They can disagree, and a reader has to be able to see that they do.
    """
    comments = [
        _normalize_inline(str(item))
        for item in field.get("sql_comments") or []
        if str(item).strip()
    ]
    if not comments:
        return []
    return [_tagged(f"- 注释：{'；'.join(comments)}", TAG_SQL_COMMENT)]


def _sources_text(field: dict) -> str:
    notes = [_field_note(source) for source in field.get("sources") or []]
    generated = [
        _generated_source_text(item) for item in field.get("generated_sources") or []
    ]
    if generated:
        notes.append("生成来源 " + "、".join(_normalize_inline(item) for item in generated))
    return "、".join(notes) or "无物理来源"


def _sources_tag(field: dict) -> str:
    if any(source.get("comment") for source in field.get("sources") or []):
        return TAG_SQL_AND_METADATA
    return TAG_SQL


def _render_derivation(field: dict) -> list[str]:
    steps = field.get("derivation") or []
    if not steps:
        return ["- 加工步骤：契约未给出该字段的分步加工链。（SQL事实）"]
    lines = ["- 加工步骤："]
    total = len(steps)
    for run in _derivation_runs(steps):
        if len(run) >= DERIVATION_FOLD_MINIMUM:
            lines.append("  " + _tagged(_carried_run_line(run, total), TAG_SQL))
            continue
        for step in run:
            lines.append("  " + _tagged(_derivation_step_line(step, total), TAG_SQL))
    return lines


def _derivation_step_line(step: dict, total: int) -> str:
    text = step.get("text")
    body = (
        _normalize_inline(str(text)) if text else _expr_span(step.get("expression") or "")
    )
    grain = step.get("grain") or "unknown"
    marker = f"{WARN} " if grain == "unknown" else ""
    return (
        f"- 步骤 {step.get('step_no')}/{total} @ {_span(step.get('scope_id'))}"
        f"（{step.get('step_type')}）：{body}；{marker}粒度={grain}"
    )


def _is_carrying_step(step: dict) -> bool:
    """A step that hands the value on unchanged (WI-1g item D2).

    A ``union`` step that merges one branch merges nothing -- it is how the contract
    writes "this scope reads that union" -- so it carries the value exactly as a direct
    projection does. A real UNION (two branches or more) is a fact worth its own line.
    """
    kind = str(step.get("step_type"))
    if kind not in _PASS_THROUGH_STEP_TYPES:
        return False
    if kind != "union":
        return True
    return str(step.get("text") or "").startswith(_SINGLE_BRANCH_UNION_TEXT)


def _derivation_runs(steps: Sequence[dict]) -> list[list[dict]]:
    """The steps split into maximal runs of carrying steps and single other steps."""
    runs: list[list[dict]] = []
    for step in steps:
        joins_previous = (
            _is_carrying_step(step)
            and runs
            and _is_carrying_step(runs[-1][0])
            # a branch step and a chain step are not the same kind of neighbour
            and bool(step.get("branch")) == bool(runs[-1][0].get("branch"))
        )
        if joins_previous:
            runs[-1].append(step)
        else:
            runs.append([step])
    return runs


def _carried_run_line(run: Sequence[dict], total: int) -> str:
    """One line for a run of carrying steps (WI-1g item D2).

    A chain is written as a path -- the value really does cross those scopes in that
    order. A run of UNION branch steps is not a path: each row takes exactly one of
    them, so they are listed rather than arrowed, which would state a sequence the
    statement never performs.
    """
    branches = bool(run[0].get("branch"))
    separator, verb = ("、", "各分支直接透传") if branches else (" → ", "直接透传")
    path = separator.join(_span(step.get("scope_id")) for step in run)
    grains = {str(step.get("grain") or "unknown") for step in run}
    grain = grains.pop() if len(grains) == 1 else "mixed"
    marker = f"{WARN} " if grain == "unknown" else ""
    return (
        f"- 第 {run[0].get('step_no')}–{run[-1].get('step_no')}/{total} 步："
        f"{verb}（经 {path}）；{marker}粒度={grain}"
    )


def _trace_line(field: dict) -> str:
    chain = field.get("mapping_chain_id")
    if field.get("trace_complete") and not field.get("ambiguous"):
        return _tagged(f"- 追溯：完整；mapping_chain_id={chain}", TAG_SQL)
    reasons = [str(item) for item in field.get("trace_incomplete_reasons") or []]
    if field.get("ambiguous"):
        reasons.append("裸列多源歧义（AMBIGUOUS，候选见 lineage.json 的 ambiguities）")
    detail = "；".join(reasons) or "契约未给出原因"
    return _tagged(
        f"- {WARN} 追溯：不完整——{_normalize_inline(detail)}；mapping_chain_id={chain}",
        TAG_SQL,
    )


def _render_field_table(fields: Sequence[dict]) -> list[str]:
    # WI-2.12: the 术语 column exists only where the corpus answered a column this table
    # has no comment for -- otherwise it would be a column of em dashes.
    termed = any(field.get("term_meaning") for field in fields)
    head = "| # | 字段 | 一句话语义 |"
    ruler = "| --- | --- | --- |"
    if termed:
        head += f" {TERM_MEANING_COLUMN_TITLE} |"
        ruler += " --- |"
    lines = [
        "",
        "### 完整字段清单",
        "",
        head + " 结构角色 | 口径 | 追溯 |",
        ruler + " --- | --- | --- |",
    ]
    for index, field in enumerate(fields, start=1):
        traced = "✓" if field.get("trace_complete") and not field.get("ambiguous") else WARN
        lines.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    _cell(
                        _span(field.get("column_label"))
                        + _sql_alias_note(field.get("sql_alias"))
                    ),
                    _cell(str(field.get("summary") or "—")),
                    *([_cell(_term_meaning_cell(field))] if termed else []),
                    _cell(str(field.get("structural_role") or "未知")),
                    _cell(_metric_cell(field)),
                    traced,
                ]
            )
            + " |"
        )
    return lines


def _term_meaning_cell(field: Mapping) -> str:
    """The term standing in for a missing target comment, ticked as human-confirmed."""
    text = (field.get("term_meaning") or {}).get("text")
    if not text:
        return "—"
    return f"{_normalize_inline(str(text))} {CONFIRMED_MARK}"


# ------------------------------------------------------------- 5b. 指标口径卡 (WI-2.1)

# The card is seven lines, always the same seven, in this order: a reader who has read
# one metric's definition knows where to look in the next one. A slot the contract could
# not fill says so on its own line rather than disappearing, because a missing line reads
# as "there is no such thing" instead of "nobody wrote it down".
METRIC_CARD_LABELS = (
    "统计对象",
    "时间范围",
    "纳入条件",
    "聚合",
    "单位/类型",
    "空值",
    "更新频率",
)

METRIC_EMPTY_TIME_RANGE = "未在聚合路径上发现日期过滤"
METRIC_EMPTY_INCLUSION = "无"
METRIC_NO_AGGREGATION = "无聚合步，直取上游取值"
METRIC_UNKNOWN_REFRESH = "未知（任务元信息未提供）"

# The scheduler's own cycle vocabulary, read into Chinese. An unlisted value is printed
# as the exporter wrote it -- guessing what a cycle name means is how a daily job becomes
# an hourly one in a document nobody re-checks.
_CYCLE_LABELS = {
    "MINUTE": "每分钟",
    "HOUR": "每小时",
    "DAY": "每日",
    "WEEK": "每周",
    "MONTH": "每月",
    "YEAR": "每年",
}

# WI-2.2 section 1. The header block is quoted, not restated: a blockquote makes the
# seam between "what the document derived" and "what a person wrote" visible at a glance.
HEADER_COMMENTS_TITLE = "SQL 头部注释（原文，作者说法，非 SQL 事实）"

# Section 1's task-metadata line, in the order a reader scans it. A slot the metadata did
# not supply is left out of the line rather than printed as "未知" -- nine unknowns would
# state that a task JSON was read and found empty.
_TASK_META_ITEMS = (
    ("project", "项目"),
    ("owner", "负责人"),
    ("schedule_cycle", "调度周期"),
    ("schedule", "调度表达式"),
    ("expect_date", "期望日期"),
    ("description", "任务描述"),
)
METRIC_UNKNOWN_UNIT = "单位未知"
METRIC_NO_NULL_FILL = "未见缺失回填"
METRIC_NOT_NULLABLE = "无可证明的关联致空"

# WI-2.1 fix: a condition read off the *argument* side rather than the driving side says
# so on the line it appears on. Two dates one day apart, one per path, is exactly the
# thing a reader must not take for a typo.
METRIC_ARGUMENT_PATH_MARK = "（参数来源侧）"

# The profile's own name for that path, mirrored so the two cannot disagree.
METRIC_ARGUMENT_PATH = "argument"

# The paths whose JOINs change a *value* rather than the output's row count: the metric
# argument's own path, and the input subtree below a metric's anchoring aggregation.
# Both belong under one heading, because the reader's action is the same for both.
METRIC_ANCHOR_PATH = "anchor"
_VALUE_ONLY_PATHS = (METRIC_ARGUMENT_PATH, METRIC_ANCHOR_PATH)

# WI-2.1c item 5. A JOIN that only feeds a metric's argument leaves the output's row
# count alone, so it is listed apart from the grain-path joins rather than among them --
# it inflates a number instead of adding rows, and the two need different action.
FAN_OUT_ARGUMENT_HEADING = "影响指标取值的关联："

# WI-2.1c item 2. A metric whose value is computed from the moment the job runs cannot
# be reproduced by a backfill, which is a property of the time range and is said there.
METRIC_TIME_DEPENDENT_MARK = "（含运行时刻函数，结果随跑批时间漂移）"

# WI-2.1c item 3. The same column pinned to two different literals on the two paths. The
# gap is stated in days when both literals are written as plain days, and as a bare
# disagreement otherwise -- a number nobody can compute is not invented.
METRIC_MISMATCH_UNMEASURED = "另一侧取另一天"

# The one time-range kind whose label carries its own value: 「实例日期 20260814」.
METRIC_INSTANCE_DATE_KIND = "instance_date"


_VALUE_KIND_LABELS = {
    "literal": "字面量",
    # WI-2.9 item A: the day this instance runs for, not a hardcoded value somebody
    # forgot to parameterise. The label carries the day itself, so the card reads
    # 「实例日期 20260814」 rather than 「字面量」.
    "instance_date": "实例日期",
    "parameter": "变量",
    "expression": "表达式",
    "range": "区间",
}

_UNIT_SOURCE_LABELS = {"comment": "注释", "function": "函数", "type": "类型"}


def _render_metric_card(field: dict) -> list[str]:
    """Section 5's七行口径卡, or nothing at all when the field is not a metric."""
    spec = field.get("metric_spec")
    if not spec:
        return []
    bodies = (
        _metric_subject_text(spec),
        _metric_time_range_text(spec),
        _metric_inclusion_text(spec),
        _metric_aggregation_text(spec),
        _metric_unit_text(spec),
        _metric_null_text(spec),
        _metric_refresh_text(spec),
    )
    return ["- 口径："] + [
        f"  - {label}：{body}" for label, body in zip(METRIC_CARD_LABELS, bodies)
    ]


def _metric_refresh_text(spec: dict) -> str:
    """The cadence row: the cycle a reader asks for, and the cron that actually runs it."""
    refresh = spec.get("refresh") or {}
    cycle = refresh.get("cycle")
    cron = refresh.get("cron")
    if not cycle and not cron:
        return METRIC_UNKNOWN_REFRESH
    head = _CYCLE_LABELS.get(str(cycle).upper(), str(cycle)) if cycle else "未声明周期"
    detail = f"（cron {_span(cron)}）" if cron else ""
    return f"{head}{detail}"


def _metric_subject_text(spec: dict) -> str:
    subject = spec.get("subject") or {}
    tables = subject.get("tables") or []
    arguments = subject.get("argument_tables") or []
    body = (
        f"{_join_spans(tables)} 的记录"
        if tables
        else _normalize_inline(str(subject.get("text") or "—"))
    )
    if arguments:
        body = f"{body}，指标值取自 {_join_spans(arguments)}"
    return f"{body}（聚合于 {_span(subject.get('scope_id'))}）"


def _metric_time_range_text(spec: dict) -> str:
    items = spec.get("time_range") or []
    if not items:
        body = METRIC_EMPTY_TIME_RANGE
    else:
        body = "；".join(_metric_time_range_item(item, items) for item in items)
    return f"{body}{METRIC_TIME_DEPENDENT_MARK}" if spec.get("time_dependent") else body


def _metric_time_range_item(item: dict, items: Sequence[dict]) -> str:
    return (
        f"{_expr_span(item.get('expression') or '')}"
        f"（{_metric_time_range_kind(item)}，{_span(item.get('column'))}）"
        f"{METRIC_ARGUMENT_PATH_MARK if item.get('path') == METRIC_ARGUMENT_PATH else ''}"
        f"{_metric_mismatch_note(item, items)}"
    )


def _metric_time_range_kind(item: dict) -> str:
    """The kind, with the day spelled out when the kind is the instance's own date."""
    kind = str(item.get("kind"))
    label = _VALUE_KIND_LABELS.get(kind, kind)
    if kind != METRIC_INSTANCE_DATE_KIND:
        return label
    day = _instance_day(item.get("expression"))
    return f"{label} {day}" if day else label


def _metric_mismatch_note(item: dict, items: Sequence[dict]) -> str:
    """What the other side of one disagreeing column reads, stated as a fact.

    WI-2.9 item A. The two sides of a metric reading two different days is a *definition*
    the reader needs -- the reminder side takes the day before -- and the line used to
    read as a complaint about it. So the note says which way round the other side goes,
    and the finding it came from is an information item rather than a governance lead.
    """
    if not item.get("mismatch"):
        return ""
    notes = []
    for other in items:
        if other is item or not other.get("mismatch"):
            continue
        if _bare_column(other) != _bare_column(item):
            continue
        notes.append(
            f"（{_expr_span(other.get('expression') or '')} "
            f"{_metric_mismatch_gap(item, other)}）"
        )
    return "".join(_dedupe_text(notes))


def _instance_day(expression: str | None) -> str:
    """The day one ``<col> = '<day>'`` conjunct pins, unquoted, or "" when it pins none."""
    parsed = equality_conjunct(expression)
    return str(parsed[1]).strip().strip("'\"") if parsed else ""


def _metric_mismatch_gap(item: dict, other: dict) -> str:
    """"另一侧取前 1 日" / "另一侧取后 1 日", or a bare disagreement when unmeasured."""
    days = predicate_literal_day_offset(item.get("expression"), other.get("expression"))
    if not days:
        return METRIC_MISMATCH_UNMEASURED
    return f"另一侧取{'前' if days < 0 else '后'} {abs(days)} 日"


def _bare_column(item: dict) -> str:
    return str(item.get("column") or "").rpartition(".")[2]


def _metric_inclusion_text(spec: dict) -> str:
    items = spec.get("inclusion") or []
    if not items:
        return METRIC_EMPTY_INCLUSION
    return "；".join(_normalize_inline(str(item.get("text") or "")) for item in items)


def _metric_aggregation_text(spec: dict) -> str:
    aggregation = spec.get("aggregation")
    if not aggregation:
        return METRIC_NO_AGGREGATION
    text = _normalize_inline(str(aggregation.get("text") or ""))
    landed = [key.get("target_column") for key in aggregation.get("group_keys") or []]
    if not landed:
        return text
    if not any(landed):
        return f"{text}（分组键未落到目标表列）"
    return f"{text}（分组键落目标列 {_join_spans([item for item in landed if item])}）"


def _metric_unit_text(spec: dict) -> str:
    unit = spec.get("unit") or {}
    declared = str(unit.get("type") or "未知")
    hint = unit.get("hint")
    if not hint:
        return f"{declared}；{METRIC_UNKNOWN_UNIT}"
    source = _UNIT_SOURCE_LABELS.get(str(unit.get("hint_source")), "未知来源")
    return f"{declared}；{hint}（来自{source}）"


def _metric_null_text(spec: dict) -> str:
    null_handling = spec.get("null_handling") or {}
    argument = _describe_nullable_argument(null_handling.get("nullable_argument"))
    if argument:
        head = argument
    elif null_handling.get("nullable_by_join"):
        head = "关联未命中时为空"
    else:
        head = METRIC_NOT_NULLABLE
    parts = [head]
    default = null_handling.get("default")
    if default is None:
        parts.append(METRIC_NO_NULL_FILL)
    else:
        parts.append(
            f"缺失回填 {_expr_span(default)}"
            f"（{null_handling.get('default_source') or '未知来源'}）"
        )
    return "，".join(parts)


def _metric_cell(field: dict) -> str:
    """The field table's 口径 column: the aggregation and the time range, compressed."""
    spec = field.get("metric_spec")
    if not spec:
        return "—"
    aggregation = spec.get("aggregation") or {}
    call = (
        f"{aggregation.get('function')}({aggregation.get('argument')})"
        if aggregation.get("function")
        else "直取"
    )
    ranges = "、".join(
        str(item.get("expression") or "") for item in spec.get("time_range") or []
    )
    return f"{call}；{ranges or METRIC_EMPTY_TIME_RANGE}"


# ------------------------------------------------------------ 6. 可信度与边界


def _render_confidence(profile: dict) -> list[str]:
    confidence = profile.get("confidence") or {}
    coverage = confidence.get("metadata_coverage") or {}
    complete = coverage.get("input_tables_complete")
    total = coverage.get("input_tables_total")
    target_available = coverage.get("target_comments_available")
    lines = [
        "",
        _tagged(
            f"- 元数据覆盖：输入表 {complete}/{total} 完整；目标表列注释"
            + (
                f"可用（来源 {coverage.get('target_metadata_source')}）"
                if target_available
                else f"{WARN} 不可用——字段语义退化为来源注释加加工复述"
            ),
            TAG_METADATA,
        ),
        _issue_line("追溯不完整字段", confidence.get("trace_incomplete_fields") or []),
        _issue_line("AMBIGUOUS 字段", confidence.get("ambiguous_fields") or []),
    ]
    lines.extend(_diagnostics_lines(confidence))
    findings = confidence.get("findings") or []
    lines.append(_target_binding_line(findings))
    lines.append(_inferred_line(confidence.get("inferred_items") or []))
    lines.extend(_render_findings(findings))
    return lines


def _target_binding_line(findings: Sequence[dict]) -> str:
    """WI-1f: how the written values reached their target columns, on its own line.

    A positional binding is the one thing in this section that silently goes wrong
    later -- the DDL changes and every value shifts one column -- so it is not listed
    among the other governance leads where it would be skimmed past.
    """
    found = [item for item in findings if item.get("kind") == FINDING_OWN_LINE]
    if not found:
        return _tagged("- 目标列绑定：契约未给出绑定事实", TAG_METADATA)
    return _tagged(
        f"- 目标列绑定：{_normalize_inline(str(found[0].get('text') or ''))}",
        TAG_METADATA,
    )


def _render_findings(findings: Sequence[dict]) -> list[str]:
    """Section 6's governance leads, one line each, kind first so they can be grouped.

    WI-2.9 item A: only the ``warn`` ones are listed. The rest are true and stay in
    ``semantic.json``, but a reader who has to act cannot find the one line that matters
    among six that need nothing -- so they are counted in a single line instead.
    """
    candidates = [item for item in findings if item.get("kind") != FINDING_OWN_LINE]
    listed = [item for item in candidates if item.get("severity") != SEVERITY_INFO]
    information = len(candidates) - len(listed)
    lines = ["", "#### 治理线索", ""]
    if not listed:
        lines.append(_tagged("- 治理线索：无", TAG_SQL))
    lines.extend(_finding_line(item) for item in listed)
    if information:
        lines.append(_tagged(INFORMATION_LINE.format(count=information), TAG_SQL))
    return lines


def _finding_line(finding: Mapping) -> str:
    kind = str(finding.get("kind"))
    return _tagged(
        f"- {WARN} {kind}：{_normalize_inline(str(finding.get('text') or ''))}",
        _FINDING_TAGS.get(kind, TAG_SQL),
        finding.get("evidence") or [],
    )


def _inferred_line(inferred) -> str:
    """The inference inventory, grouped by ``semantic.json`` path.

    These are paths into the profile, not catalog identifiers, so they are written as
    plain text: putting them in code spans would make them look like table ids. A 112
    field task has one entry per field, which is a count, not a list worth printing --
    the exact paths stay in ``confidence.inferred_items``.
    """
    if not inferred:
        return _tagged("- 本文档的结构推断项：无", TAG_STRUCTURAL)
    counts = _inferred_counts(inferred)
    total = sum(counts.values())
    grouped = "、".join(
        f"{path} {counts[path]}"
        for path in sorted(counts, key=lambda name: (-counts[name], name))
    )
    return _tagged(
        f"- 本文档的结构推断项：{total} 项（按 semantic.json 路径：{grouped}；"
        "完整清单见 semantic.json 的 confidence.inferred_items）",
        TAG_STRUCTURAL,
    )


def _inferred_counts(inferred) -> dict[str, int]:
    """``confidence.inferred_items`` as ``path -> count``.

    Since WI-1g the profile publishes the grouping itself; a list of indexed paths is
    still accepted so a profile recorded before that change renders unchanged.
    """
    if isinstance(inferred, dict):
        return {str(path): int(count) for path, count in inferred.items()}
    counts: dict[str, int] = {}
    for item in inferred:
        path = _ARRAY_INDEX.sub("[]", str(item))
        counts[path] = counts.get(path, 0) + 1
    return counts


def _issue_line(label: str, items: Sequence) -> str:
    if not items:
        return _tagged(f"- {label}：无", TAG_SQL)
    return _tagged(f"- {WARN} {label}：{_join_spans(items)}", TAG_SQL)


def _diagnostics_lines(confidence: dict) -> list[str]:
    if not confidence.get("diagnostics_available"):
        return [
            _tagged(
                f"- {WARN} 无 diagnostics 文档：事实缺口与解析警告无从判断",
                TAG_SQL,
            )
        ]
    gaps = confidence.get("fact_gap_count") or 0
    gap_types = confidence.get("fact_gap_types") or {}
    warnings = confidence.get("warning_counts") or {}
    marker = f"{WARN} " if gaps else ""
    return [
        _tagged(
            f"- {marker}事实缺口：{gaps} 条"
            + (f"（{_counts_text(gap_types)}）" if gap_types else ""),
            TAG_SQL,
        ),
        _tagged(
            "- 解析警告："
            + (
                f"{sum(warnings.values())} 条（{_counts_text(warnings)}；"
                "语义提示见 `scope-lineage render` 生成的 warnings.md）"
                if warnings
                else "无"
            ),
            TAG_SQL,
        ),
    ]


def _counts_text(counts: dict) -> str:
    return "、".join(f"{name} {counts[name]}" for name in sorted(counts))


# -------------------------------------------------------------- 7. 给 Agent 的说明


def _render_agent_notes() -> list[str]:
    return ["", *[f"- {note}" for note in AGENT_NOTES]]
