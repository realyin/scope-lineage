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

``table_figures`` counts each row once, as data (None where the number needs a document
the table does not have); ``figure_cells`` turns a row into the cells the page prints.
The Markdown table and the browse page's table list (``catalog_browse``) both read them,
so the two cannot count differently.
"""

from __future__ import annotations

import posixpath
from collections.abc import Callable, Mapping
from typing import Optional

from .catalog_concept_page import table_head, table_row
from .catalog_gaps import share_text
from .catalog_units import UNJUDGED, UNSUPPORTED, unit_support
from .catalog_view import CatalogView
from .markdown_text import expr_span

BY_TABLE_HEADING = "## 按表看"
BY_TABLE_LEGEND = (
    "每张表一行，按表名排列。度量列是绑定到度量属性的列；单位有没有材料依据按属性判断，"
    "与取数包标注单位用的是同一条规则。"
)
KEY_ROW = "唯一键有血缘证据的表"
UNIT_ROW = "单位有材料依据的度量属性"
NOT_COVERED = "—"
UNIQUE_TEXT = {"yes": "唯一", "no": "不唯一", "unknown": "未知"}
# (key in a figures row, column heading); the first two only with lineage evidence
LINEAGE_COLUMNS = (("key_evidence", "唯一键的证据"), ("unique", "表语义的说法"))
COUNT_COLUMNS = (
    ("measures", "度量列"),
    ("unit_unsupported", "其中单位无材料依据"),
    ("unmapped", "未绑定列"),
    ("watch", "注意事项"),
)


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


def by_table_columns(view: CatalogView) -> list[tuple[str, str]]:
    """``(key, heading)`` of the by-table columns after the table and its concept."""
    return [*(LINEAGE_COLUMNS if view.lineage_checked() else ()), *COUNT_COLUMNS]


def table_figures(view: CatalogView, docs: Mapping[str, Mapping]) -> list[dict]:
    """One row per catalog table, in name order: ``{table, concept, covered, measures,
    unit_unsupported, unmapped, watch, watch_conflicts}`` and, with lineage evidence,
    ``key_evidence`` (``proven`` / ``none``) and ``unique`` (``yes`` / ``no`` /
    ``unknown``). A number that needs the table's document is None when it has none."""
    lineage = view.lineage_checked()
    outcomes: dict[str, str] = {}
    rows = []
    for table in sorted(view.representations):
        rep = view.representations[table]
        doc = docs.get(table.lower())
        measures = [
            binding for binding in rep["bindings"]
            if binding.get("ref") in view.attributes
            and view.attributes[binding["ref"]][0].get("category") == "measure"
        ]
        row: dict = {"table": table, "concept": rep["concept"], "covered": bool(doc)}
        if lineage:
            row["key_evidence"] = "proven" if _proven(view, table) else "none"
            unique = _unique(doc)
            row["unique"] = (unique if unique in UNIQUE_TEXT else "unknown") if doc else None
        watch = ((doc or {}).get("summary") or {}).get("watch") or []
        row.update(
            measures=len(measures),
            unit_unsupported=sum(
                1 for binding in measures
                if _outcome(view, binding["ref"], docs, outcomes) == UNSUPPORTED
            ) if doc else None,
            unmapped=len({b["column"] for b in rep["bindings"] if b["to"] == "unmapped"}),
            watch=len(watch) if doc else None,
            watch_conflicts=sum(1 for item in watch if item.get("kind") == "conflict")
            if doc else None,
        )
        rows.append(row)
    return rows


def figure_cells(row: Mapping) -> dict[str, str]:
    """``{key: cell text}`` of a ``table_figures`` row, as the index prints it."""
    cells = {}
    if "key_evidence" in row:
        cells["key_evidence"] = "已证明" if row["key_evidence"] == "proven" else "无"
        cells["unique"] = NOT_COVERED if row["unique"] is None else UNIQUE_TEXT[row["unique"]]
    measures, unsupported = row["measures"], row["unit_unsupported"]
    cells["measures"] = str(measures)
    if unsupported is None:
        cells["unit_unsupported"] = NOT_COVERED
    else:
        cells["unit_unsupported"] = share_text(unsupported, measures) if measures else "0"
    cells["unmapped"] = str(row["unmapped"])
    if row["watch"] is None:
        cells["watch"] = NOT_COVERED
    elif not row["watch"]:
        cells["watch"] = "0"
    else:
        cells["watch"] = f"{row['watch']}（与材料矛盾 {row['watch_conflicts']}）"
    return cells


def coverage_note(view: CatalogView, docs: Mapping[str, Mapping]) -> Optional[str]:
    """The sentence under the table when the documents do not cover every table."""
    tables = view.representations
    covered = sum(1 for table in tables if table.lower() in docs)
    if covered == len(tables):
        return None
    return (
        f"表语义只覆盖 {covered}/{len(tables)} 张表；没覆盖到的表，依赖表语义的格子显示「{NOT_COVERED}」。"
    )


def by_table_lines(
    view: CatalogView, docs: Mapping[str, Mapping], concept_link: Callable[[str], str]
) -> list[str]:
    """The by-table section: a short legend, one row per table, and the coverage note."""
    columns = by_table_columns(view)
    lines = [BY_TABLE_HEADING, "", BY_TABLE_LEGEND, ""]
    lines += table_head("表", "概念", *(heading for _, heading in columns))
    for row in table_figures(view, docs):
        cells = figure_cells(row)
        lines.append(table_row(
            _table_link(view, row["table"]), concept_link(row["concept"]),
            *(cells[key] for key, _ in columns),
        ))
    note = coverage_note(view, docs)
    if note:
        lines += ["", note]
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


def _table_link(view: CatalogView, table: str) -> str:
    """The table, linked to its table-semantics page the way concept pages link it, but
    from the index: the link ``--semantics`` gave is relative to ``concepts/``."""
    page = view.semantic_page(table)
    if not page:
        return expr_span(table)
    return f"[{expr_span(table)}]({posixpath.normpath(posixpath.join('concepts', page))})"
