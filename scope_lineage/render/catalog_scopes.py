"""Record scope and validity: which rows a table keeps, gathered across the catalog.

A representation's ``scope`` lines say, in the author's words, which rows the table holds
("only active customers", "latest row per account"). A reader asking "which tables drop
deleted records?" should not have to open every concept page, so this module files every
line under the kind of filter it states, found by keywords:

- ``validity``  有效记录/记录状态 -- valid or active rows, a record status;
- ``deletion``  删除/注销 -- deleted, cancelled or void rows;
- ``dedup``     去重/最新 -- one row kept per key: the latest, the first, distinct;
- ``partition`` 分区/快照日期 -- a partition or snapshot date;
- ``other``     其他 -- none of these.

A line stating two kinds is filed under both. The business rules and value domains that
cite a table (in their evidence or their expression) are gathered beside the lines.
``scopes.md`` renders all of it; ``catalog query scope <keyword|kind>`` answers from it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from .catalog_view import (
    CONSTRAINT_KINDS,
    STRENGTH_TEXT,
    CatalogView,
    concept_filename,
    status_text,
    time_text,
    usage_hint,
)
from .markdown_text import cell, expr_span

SCOPE_KINDS = (
    ("validity", "有效记录/记录状态"),
    ("deletion", "删除/注销"),
    ("dedup", "去重/最新"),
    ("partition", "分区/快照日期"),
    ("other", "其他"),
)
SCOPE_KIND_TEXT = dict(SCOPE_KINDS)
# Keywords per kind: Chinese ones match anywhere, ASCII ones as whole words (an
# underscore separates words, so ``is_deleted`` says ``deleted``).
_KEYWORDS = {
    "validity": ("有效", "生效", "失效", "状态", "在用", "valid", "active", "status", "effective"),
    "deletion": (
        "删除", "注销", "作废", "销户", "撤销",
        "delete", "deleted", "del", "cancel", "cancelled", "canceled", "void", "removed",
    ),
    "dedup": (
        "去重", "最新", "最后一条", "第一条", "取一条",
        "dedup", "distinct", "latest", "newest", "row_number", "rn",
    ),
    "partition": ("分区", "快照", "截至", "dt", "ds", "pt", "partition", "snapshot"),
}
RULE_KINDS = ("business_rule", "value_domain")
CONSTRAINT_TEXT = dict(CONSTRAINT_KINDS)
SCOPES_FILENAME = "scopes.md"


def _matcher(words: tuple) -> re.Pattern:
    parts = [
        re.escape(word) if not word.isascii() else rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])"
        for word in words
    ]
    return re.compile("|".join(parts))


_MATCHERS = {kind: _matcher(words) for kind, words in _KEYWORDS.items()}


def classify_scope(line: str) -> list[str]:
    """The kinds of filter one scope line states, in ``SCOPE_KINDS`` order; ``other`` if none."""
    text = str(line).casefold()
    kinds = [kind for kind, matcher in _MATCHERS.items() if matcher.search(text)]
    return kinds or ["other"]


def scope_lines(view: CatalogView) -> list[tuple[dict, str, list[str]]]:
    """``(representation, line, kinds)`` for every scope line, tables in name order."""
    return [
        (rep, line, classify_scope(line))
        for table in sorted(view.representations)
        for rep in (view.representations[table],)
        for line in rep["scope"]
    ]


def cited_rules(view: CatalogView) -> list[tuple[str, dict]]:
    """``(table, constraint)`` for every business rule or value domain citing the table."""
    found = []
    for table in sorted(view.representations):
        for constraint in sorted(view.constraints, key=lambda c: c["id"]):
            if constraint["kind"] in RULE_KINDS and _cites(constraint, table):
                found.append((table, constraint))
    return found


def _cites(constraint: Mapping, table: str) -> bool:
    evidence = [str(item) for item in constraint.get("evidence") or []]
    if any(item == table or item.startswith(f"{table}.") for item in evidence):
        return True
    return table in str(constraint.get("expression") or "")


# ------------------------------------------------------------------ scopes.md


def render_scopes(view: CatalogView) -> str:
    lines = [
        "# 记录范围与有效性",
        "",
        "[返回目录](index.md)",
        "",
        "每张表现表的记录范围（scope）按过滤类别归组，类别由关键词判断；一行说到几类时每类都列。",
    ]
    rows = scope_lines(view)
    for kind, label in SCOPE_KINDS:
        group = [(rep, line) for rep, line, kinds in rows if kind in kinds]
        lines += ["", f"## {label}", "", *_scope_table(view, group)]
    lines += ["", "## 未声明记录范围的表", "", *_unscoped(view)]
    lines += ["", "## 引用了表的业务规则与值域约束", "", *_rules_table(view)]
    return "\n".join(lines) + "\n"


def _concept_link(view: CatalogView, concept_id: str) -> str:
    return f"[{view.name(concept_id)}](concepts/{concept_filename(concept_id)})"


def _scope_table(view: CatalogView, group: list) -> list[str]:
    if not group:
        return ["（无）"]
    lines = ["| 表 | 概念 | 时间语义 | 记录范围 |", "| --- | --- | --- | --- |"]
    for rep, line in group:
        cells = (
            expr_span(rep["table"]),
            _concept_link(view, rep["concept"]),
            time_text(rep),
            cell(line),
        )
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _unscoped(view: CatalogView) -> list[str]:
    items = [
        f"- {expr_span(table)}（{_concept_link(view, rep['concept'])}）"
        for table, rep in sorted(view.representations.items())
        if not rep["scope"]
    ]
    return items or ["（无）"]


def _rules_table(view: CatalogView) -> list[str]:
    rules = cited_rules(view)
    if not rules:
        return ["（无）"]
    lines = [
        "| 表 | 约束 | 种类 | 作用对象 | 表达式 | 强度 | 状态 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for table, rule in rules:
        cells = (
            expr_span(table),
            expr_span(rule["id"]),
            CONSTRAINT_TEXT[rule["kind"]],
            f"{view.name(rule['on'])} {expr_span(rule['on'])}",
            cell(rule["expression"]),
            STRENGTH_TEXT[rule["strength"]],
            status_text(rule),
        )
        lines.append("| " + " | ".join(cells) + " |")
    return lines


# ---------------------------------------------------------------- the query


def _kind_of(term: str) -> str | None:
    """The kind a term names: its id, its label, or one half of the label."""
    key = str(term).strip().casefold()
    for kind, label in SCOPE_KINDS:
        if key in {kind, label.casefold(), *label.split("/")}:
            return kind
    return None


def query_scopes(view: CatalogView, term: str) -> list[dict]:
    """Tables whose scope lines or cited rules state the kind, or contain the keyword."""
    kind = _kind_of(term)
    key = str(term).strip().casefold()

    def hit(text: str) -> bool:
        return kind in classify_scope(text) if kind else key in str(text).casefold()

    rules: dict[str, list] = {}
    for table, rule in cited_rules(view):
        if hit(rule["expression"]):
            rules.setdefault(table, []).append(rule)
    matches = []
    for table in sorted(view.representations):
        rep = view.representations[table]
        lines = [line for line in rep["scope"] if hit(line)]
        if lines or table in rules:
            matches.append(_scope_answer(view, rep, lines, rules.get(table, []), kind))
    return matches


def _scope_answer(view: CatalogView, rep: dict, lines: list, rules: list, kind) -> dict:
    answer = {
        "table": rep["table"],
        "matched_by": "kind" if kind else "keyword",
        "concept": {"id": rep["concept"], "name": view.name(rep["concept"])},
        "time": rep["time"],
    }
    hint = usage_hint(rep)
    if hint:
        answer["usage"] = hint
    answer["scope"] = [{"line": line, "kinds": classify_scope(line)} for line in lines]
    answer["constraints"] = [rule_answer(rule) for rule in rules]
    return answer


def rule_answer(rule: Mapping) -> dict:
    keys = ("id", "kind", "on", "expression", "strength", "status")
    return {key: rule[key] for key in keys if key in rule}


def rules_citing(view: CatalogView, table: str) -> list[dict]:
    return [rule_answer(rule) for cited, rule in cited_rules(view) if cited == table]
