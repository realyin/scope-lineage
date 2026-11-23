"""The parts of ``index.md`` that read the table-semantics documents (``catalog render --docs``).

Two rows of the summary and a table with one row per catalog table, ordered by table
name and by nothing else: no score, no ranking. Each number has one definition:

- key evidence: lineage proved the table's grain (``grain_proof.confidence`` is
  ``proven``); shown only when the catalog was built with lineage evidence;
- what the document says: its ``summary.row.unique`` as written;
- measure columns: the table's columns bound to a measure attribute (from the catalog);
- unit not supported: those whose attribute ``unit_support`` judges unsupported -- the
  attribute's judgement, the same the context pack marks a unit by;
- unmapped columns: the table's bindings to ``unmapped``, the gap summary's source;
- watch items: the document's ``summary.watch``, and those of kind ``conflict``.

A table no document covers shows ``—`` wherever a number needs its document, and a
total that needs the documents counts only the covered tables and says so.
"""

from __future__ import annotations

import posixpath
from collections.abc import Callable, Mapping

from .catalog_concept_page import table_head, table_row
from .catalog_gaps import share_text
from .catalog_units import UNJUDGED, UNSUPPORTED, unit_support
from .catalog_view import CatalogView
from .markdown_text import expr_span

BY_TABLE_HEADING = "## 按表看"
KEY_ROW = "唯一键有血缘证据的表"
UNIT_ROW = "单位有材料依据的度量属性"
NOT_COVERED = "—"
UNIQUE_TEXT = {"yes": "唯一", "no": "不唯一", "unknown": "未知"}


def summary_rows(view: CatalogView, docs: Mapping[str, Mapping]) -> list[tuple[str, str]]:
    """The summary's rows on unique keys (with lineage evidence only) and on units."""
    tables = sorted(view.representations)
    covered = [table for table in tables if table.lower() in docs]
    rows = []
    if view.lineage_checked():
        proven = [table for table in tables if _proven(view, table)]
        not_unique = sum(1 for table in proven if _unique(docs.get(table.lower())) == "no")
        text = f"{len(proven)}/{len(tables)}；其中表语义说不唯一的 {not_unique} 张"
        if len(covered) < len(tables):
            text += f"（只数表语义覆盖到的 {len(covered)} 张表）"
        rows.append((KEY_ROW, text))
    outcomes = [
        support.outcome
        for attribute, _ in view.attributes.values()
        if (support := unit_support(view, attribute, docs)) is not None
    ]
    unjudged = outcomes.count(UNJUDGED)
    judged = len(outcomes) - unjudged
    text = f"{judged - outcomes.count(UNSUPPORTED)}/{judged}"
    if unjudged:
        text += f"；另有 {unjudged} 个没法判断（所绑的列没有一列被表语义描述）"
    rows.append((UNIT_ROW, text))
    return rows


def by_table_lines(
    view: CatalogView, docs: Mapping[str, Mapping], concept_link: Callable[[str], str]
) -> list[str]:
    """The by-table section: a short legend, one row per table, and the coverage note."""
    lineage = view.lineage_checked()
    lines = [
        BY_TABLE_HEADING,
        "",
        "每张表一行，按表名排列。度量列是绑定到度量属性的列；单位有没有材料依据按属性判断，"
        "与取数包标注单位用的是同一条规则。",
        "",
    ]
    lines += table_head(
        "表", "概念", *(("唯一键的证据", "表语义的说法") if lineage else ()),
        "度量列", "其中单位无材料依据", "未绑定列", "注意事项",
    )
    outcomes: dict[str, str] = {}
    tables = sorted(view.representations)
    for table in tables:
        rep = view.representations[table]
        doc = docs.get(table.lower())
        measures = [
            binding for binding in rep["bindings"]
            if binding.get("ref") in view.attributes
            and view.attributes[binding["ref"]][0].get("category") == "measure"
        ]
        cells = [_table_link(view, table), concept_link(rep["concept"])]
        if lineage:
            cells += [
                "已证明" if _proven(view, table) else "无",
                UNIQUE_TEXT.get(_unique(doc), UNIQUE_TEXT["unknown"]) if doc else NOT_COVERED,
            ]
        unsupported = sum(
            1 for binding in measures if _outcome(view, binding["ref"], docs, outcomes) == UNSUPPORTED
        )
        cells += [
            str(len(measures)),
            (share_text(unsupported, len(measures)) if measures else "0") if doc else NOT_COVERED,
            str(len({b["column"] for b in rep["bindings"] if b["to"] == "unmapped"})),
            _watch_text(doc) if doc else NOT_COVERED,
        ]
        lines.append(table_row(*cells))
    covered = sum(1 for table in tables if table.lower() in docs)
    if covered < len(tables):
        lines += [
            "",
            f"表语义只覆盖 {covered}/{len(tables)} 张表；没覆盖到的表，依赖表语义的格子显示「{NOT_COVERED}」。",
        ]
    return lines


def _outcome(view: CatalogView, ref: str, docs: Mapping, cache: dict[str, str]) -> str:
    if ref not in cache:
        support = unit_support(view, view.attributes[ref][0], docs)
        cache[ref] = support.outcome if support else UNJUDGED
    return cache[ref]


def _proven(view: CatalogView, table: str) -> bool:
    return (view.rep_evidence(table).get("grain_proof") or {}).get("confidence") == "proven"


def _unique(doc) -> str:
    return str((((doc or {}).get("summary") or {}).get("row") or {}).get("unique") or "")


def _watch_text(doc: Mapping) -> str:
    watch = (doc.get("summary") or {}).get("watch") or []
    if not watch:
        return "0"
    conflicts = sum(1 for item in watch if item.get("kind") == "conflict")
    return f"{len(watch)}（与材料矛盾 {conflicts}）"


def _table_link(view: CatalogView, table: str) -> str:
    """The table, linked to its table-semantics page the way concept pages link it, but
    from the index: the link ``--semantics`` gave is relative to ``concepts/``."""
    page = view.semantic_page(table)
    if not page:
        return expr_span(table)
    return f"[{expr_span(table)}]({posixpath.normpath(posixpath.join('concepts', page))})"
