"""``index.md`` of the table-semantics pages: every table by domain, then by concept.

Each row says what the table is in one line, its validation pass rate (``—`` without a
report) and how many of its questions are still open. The domain is the concept's
domain when an ontology placed the table, else its database; tables representing no
known concept are listed last under 未关联概念.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..render.catalog_concept_page import table_head, table_row
from .page_places import Place

UNLINKED = "未关联概念"


@dataclass(frozen=True)
class IndexRow:
    table: str
    filename: str
    what: str
    place: Place
    rate: str
    open_questions: int

    def link(self) -> str:
        return f"[`{self.table}`]({self.filename})"


def render_index(rows: list[IndexRow]) -> str:
    lines = [
        "# 表语义目录",
        "",
        f"共 {len(rows)} 张表，每张一页。「校验通过率」取自 `semantic validate --json` 的报告，"
        "没有报告时写 —；「待确认问题」是还没回答的问题数。",
        "",
        "## 按域",
        *_by_domain(rows),
        "",
        "## 按概念",
        *_by_concept(rows),
    ]
    return "\n".join(lines) + "\n"


def _by_domain(rows: list[IndexRow]) -> list[str]:
    groups: dict[tuple, list[IndexRow]] = {}
    for row in rows:
        groups.setdefault((row.place.order, row.place.group), []).append(row)
    lines: list[str] = []
    for (_, heading), members in sorted(groups.items()):
        lines += ["", f"### {heading}", "", *table_head("表", "这张表是什么", "校验通过率", "待确认问题")]
        lines += [
            table_row(row.link(), row.what, row.rate, str(row.open_questions)) for row in members
        ]
    return lines


def _by_concept(rows: list[IndexRow]) -> list[str]:
    groups: dict[tuple, list[IndexRow]] = {}
    for row in rows:
        concept = row.place.concept
        key = (0, concept.id, concept.heading()) if concept else (1, "", UNLINKED)
        groups.setdefault(key, []).append(row)
    lines: list[str] = []
    for (_, _, heading), members in sorted(groups.items()):
        lines += ["", f"### {heading}", ""]
        lines += table_head("表", "表现类型", "这张表是什么", "校验通过率", "待确认问题")
        lines += [
            table_row(
                row.link(),
                (row.place.concept.kind if row.place.concept else None) or "—",
                row.what,
                row.rate,
                str(row.open_questions),
            )
            for row in members
        ]
    return lines
