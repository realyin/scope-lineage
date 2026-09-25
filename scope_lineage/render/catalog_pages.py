"""``catalog render``: the built ``ontology-json/3`` document as a set of markdown pages.

- ``index.md`` -- the concepts by domain (name, kind, definition, how many tables carry
  it, status), the identifiers, and a summary of the governance gaps;
- ``concepts/<slug>.md`` -- one six-section page per concept (``catalog_concept_page``);
- ``identifiers.md`` -- every identifier in full, with the columns bound to it;
- ``governance.md`` -- every gap of every concept, one table per kind of gap;
- ``scopes.md`` -- every table's record scope grouped by the kind of filter it states,
  and the business rules and value domains that cite a table (``catalog_scopes``).

Only the document is read, never the catalog directory: the pages show exactly what was
built, including the evidence ``catalog build --lineage/--tables`` attached. Headings are
Chinese like the other rendered documents (semantic.md, ontology.md); the names are the
catalog's own.
"""

from __future__ import annotations

from collections.abc import Mapping

from .catalog_concept_page import (
    arises_text,
    mappings_text,
    render_concept_page,
    scope_text,
    spellings_text,
    table_head,
    table_row,
)
from .catalog_gaps import concept_gaps, conflict_text, share_text
from .catalog_scopes import SCOPES_FILENAME, cited_rules, render_scopes
from .catalog_view import (
    BINDING_TEXT,
    KIND_TEXT,
    ONTOLOGY_FORMAT,
    CatalogView,
    concept_filename,
    status_text,
    unconfirmed_guess,
)
from .markdown_text import cell, expr_span

CONCEPTS_DIR = "concepts"
INDEX_FILENAME = "index.md"
IDENTIFIERS_FILENAME = "identifiers.md"
GOVERNANCE_FILENAME = "governance.md"


def render_catalog_pages(document: Mapping) -> dict[str, str]:
    """``{relative path: markdown}`` for every page, in a stable order."""
    if document.get("doc_format") != ONTOLOGY_FORMAT:
        raise ValueError(
            f"expects an {ONTOLOGY_FORMAT} document, got {document.get('doc_format')!r}"
        )
    view = CatalogView(document)
    pages = {
        INDEX_FILENAME: render_index(view),
        IDENTIFIERS_FILENAME: render_identifiers(view),
        GOVERNANCE_FILENAME: render_governance(view),
        SCOPES_FILENAME: render_scopes(view),
    }
    for concept_id in sorted(view.concepts):
        pages[f"{CONCEPTS_DIR}/{concept_filename(concept_id)}"] = render_concept_page(
            view, concept_id
        )
    return pages


def _concept_link(view: CatalogView, concept_id: str) -> str:
    return f"[{view.name(concept_id)}]({CONCEPTS_DIR}/{concept_filename(concept_id)})"


# -------------------------------------------------------------------- index.md


def render_index(view: CatalogView) -> str:
    catalog = view.document["catalog"]
    lines = [f"# 本体目录：{catalog['name']}", ""]
    if catalog.get("description"):
        lines += [cell(catalog["description"]), ""]
    lines += [_index_summary(view), "", "## 概念"]
    for domain_id in sorted(view.domains):
        lines += ["", *_domain_block(view, domain_id)]
    lines += ["", "## 标识符", "", *_identifier_summary(view)]
    lines += ["", "## 治理缺口", "", *_gap_summary(view)]
    lines += ["", "## 记录范围与有效性", "", _scope_summary(view)]
    return "\n".join(lines) + "\n"


def _scope_summary(view: CatalogView) -> str:
    scoped = sum(1 for rep in view.representations.values() if rep["scope"])
    return (
        f"{scoped} 张表声明了记录范围，{len(cited_rules(view))} 条业务规则/值域约束引用了表；"
        f"按过滤类别归组见 [{SCOPES_FILENAME}]({SCOPES_FILENAME})。"
    )


def _index_summary(view: CatalogView) -> str:
    counts = view.document["counts"]
    text = (
        f"> {ONTOLOGY_FORMAT} · {counts['concepts']} 个概念 · {counts['attributes']} 个属性 · "
        f"{counts['relations']} 条关系 · {counts['representations']} 张表现表"
    )
    inputs = view.evidence_inputs
    if "lineage" in inputs:
        text += f" · 血缘证据 {inputs['lineage']['tasks']} 个任务"
    if "tables" in inputs:
        text += f" · 表卡证据 {inputs['tables']['cards']} 张"
    return text


def _domain_block(view: CatalogView, domain_id: str) -> list[str]:
    domain = view.domains[domain_id]
    lines = [f"### {domain['name']} {expr_span(domain_id)}", ""]
    if domain.get("description"):
        lines += [cell(domain["description"]), ""]
    concepts = sorted(
        (c for c in view.concepts.values() if c["domain"] == domain_id), key=lambda c: c["id"]
    )
    if not concepts:
        return lines + ["（本域没有概念）"]
    lines += table_head("概念", "种类", "定义", "表现表", "状态")
    for concept in concepts:
        lines.append(
            table_row(
                _concept_link(view, concept["id"]),
                KIND_TEXT[concept["kind"]],
                cell(concept.get("definition") or "—"),
                str(len(view.representations_of(concept["id"]))),
                status_text(concept),
            )
        )
    return lines


def _identifier_summary(view: CatalogView) -> list[str]:
    lines = table_head("标识符", "识别", "唯一范围", "物理拼写", "状态")
    for identifier_id in sorted(view.identifiers):
        identifier = view.identifiers[identifier_id]
        lines.append(
            table_row(
                f"{identifier['name']} {expr_span(identifier_id)}",
                _concept_link(view, identifier["identifies"]),
                scope_text(view, identifier),
                spellings_text(identifier),
                status_text(identifier),
            )
        )
    return lines + ["", f"完整说明见 [{IDENTIFIERS_FILENAME}]({IDENTIFIERS_FILENAME})。"]


def _gap_summary(view: CatalogView) -> list[str]:
    all_gaps = [concept_gaps(view, concept_id) for concept_id in sorted(view.concepts)]
    drafted, total = _document_drafted(view)
    rows = [
        ("草拟对象占比", share_text(drafted, total)),
        ("没有表现表的概念", str(sum(1 for g in all_gaps if g.no_representation))),
        ("未绑定列", str(len({c for g in all_gaps for c in g.unmapped_columns}))),
        ("未落表属性", str(sum(len(g.unbound_attributes) for g in all_gaps))),
        ("缺码值的状态/码值类属性", str(sum(len(g.missing_codes) for g in all_gaps))),
        ("含义待确认的码值", str(sum(len(values) for _, values in view.unconfirmed_codes()))),
    ]
    if view.has_evidence:
        rows += [
            ("证据与目录矛盾", str(len({(t, str(c)) for g in all_gaps for t, c in g.conflicts}))),
            (
                "元数据有、语料未用的绑定列",
                str(len({c for g in all_gaps for c in g.declared_only})),
            ),
            ("无连接证据的关系", str(len({r for g in all_gaps for r in g.unjoined_relations}))),
        ]
    lines = table_head("缺口", "数量") + [table_row(name, value) for name, value in rows]
    return lines + ["", f"逐项明细见 [{GOVERNANCE_FILENAME}]({GOVERNANCE_FILENAME})。"]


def _document_drafted(view: CatalogView) -> tuple[int, int]:
    """``(drafted, all)`` over every object in the document, attributes and bindings too."""
    doc = view.document
    objects = [
        *(
            doc[key]
            for key in (
                "domains",
                "identifiers",
                "code_sets",
                "concepts",
                "relations",
                "constraints",
                "terms",
            )
        ),
        [a for c in doc["concepts"] for a in c["attributes"]],
        doc["representations"],
        [b for r in doc["representations"] for b in r["bindings"]],
    ]
    flat = [obj for group in objects for obj in group]
    return sum(1 for obj in flat if obj.get("status") == "drafted"), len(flat)


# -------------------------------------------------------------- identifiers.md


def render_identifiers(view: CatalogView) -> str:
    lines = ["# 标识符", "", "[返回目录](index.md)"]
    for identifier_id in sorted(view.identifiers):
        lines += ["", *_identifier_block(view, view.identifiers[identifier_id])]
    return "\n".join(lines) + "\n"


def _identifier_block(view: CatalogView, identifier: dict) -> list[str]:
    lines = [f"## {identifier['name']} {expr_span(identifier['id'])}", ""]
    lines += table_head("项", "内容")
    rows = [
        ("识别", _concept_link(view, identifier["identifies"])),
        ("产生条件", arises_text(view, identifier)),
        ("唯一范围", scope_text(view, identifier)),
        ("物理拼写", spellings_text(identifier)),
        ("对照", mappings_text(view, identifier)),
        ("格式", cell(identifier.get("format") or "—")),
        ("绑定列", _bound_columns(view, identifier["id"])),
        ("状态", status_text(identifier)),
    ]
    if identifier.get("notes"):
        rows.append(("备注", cell(identifier["notes"])))
    return lines + [table_row(name, text) for name, text in rows]


def _bound_columns(view: CatalogView, ref: str) -> str:
    parts = []
    for rep, binding in view.bindings_of(ref):
        label = BINDING_TEXT[binding["to"]] + ("，自关联" if binding.get("self_reference") else "")
        parts.append(f"{expr_span(rep['table'] + '.' + binding['column'])}（{label}）")
    return "；".join(parts) or "（无）"


# --------------------------------------------------------------- governance.md


def render_governance(view: CatalogView) -> str:
    lines = ["# 治理缺口", "", "[返回目录](index.md)", "", "## 按概念", ""]
    lines += table_head("概念", "草拟占比", "没有表现表", "未绑定列", "未落表属性", "缺码值属性")
    gaps = {concept_id: concept_gaps(view, concept_id) for concept_id in sorted(view.concepts)}
    for concept_id, gap in gaps.items():
        lines.append(
            table_row(
                _concept_link(view, concept_id),
                share_text(gap.drafted, gap.total),
                "是" if gap.no_representation else "否",
                str(len(gap.unmapped_columns)),
                str(len(gap.unbound_attributes)),
                str(len(gap.missing_codes)),
            )
        )
    lines += _gap_lists(view, gaps)
    lines += _unconfirmed_code_lines(view)
    lines += _foreign_attribute_tables(view)
    return "\n".join(lines) + "\n"


def _unconfirmed_code_lines(view: CatalogView) -> list[str]:
    """Code values seen in the data whose meaning nobody has confirmed yet."""
    lines = ["", "## 含义待确认的码值", ""]
    found = view.unconfirmed_codes()
    if not found:
        return lines + ["（无）"]
    lines += table_head("码值集", "待确认的值（目录的猜测）", "使用它的属性")
    for code_set, values in found:
        guesses = "；".join(_guess_text(value) for value in values)
        users = "；".join(
            f"{a['name']} {expr_span(a['id'])}" for a in view.attributes_coded_by(code_set["id"])
        )
        lines.append(
            table_row(f"{code_set['name']} {expr_span(code_set['id'])}", guesses, users or "（无）")
        )
    return lines


def _guess_text(value: dict) -> str:
    guess = unconfirmed_guess(value)
    return expr_span(value["value"]) + (f"（{cell(guess)}）" if guess else "")


def _foreign_attribute_tables(view: CatalogView) -> list[str]:
    """Wide tables repeating another concept's attributes: counted, not a gap."""
    lines = [
        "",
        "## 冗余属性列（按表）",
        "",
        "信息项，不算缺口：这些列在另一个概念的标识符旁重复该概念的属性。",
        "",
    ]
    found = view.foreign_attribute_bindings()
    if not found:
        return lines + ["（无）"]
    lines += table_head("表", "冗余属性列数", "列")
    for rep, bindings in found:
        columns = "；".join(_foreign_attribute_text(view, b) for b in bindings)
        lines.append(table_row(expr_span(rep["table"]), str(len(bindings)), columns))
    return lines


def _foreign_attribute_text(view: CatalogView, binding: dict) -> str:
    attribute, concept = view.attributes[binding["ref"]]
    return (
        f"{expr_span(binding['column'])}：{concept['name']}.{attribute['name']}"
        f"（经 {expr_span(binding['via'])}）"
    )


def _gap_lists(view: CatalogView, gaps: dict) -> list[str]:
    sections = [
        (
            "没有表现表的概念",
            [_concept_link(view, c) for c, g in gaps.items() if g.no_representation],
        ),
        ("未绑定列", _unique(expr_span(c) for g in gaps.values() for c in g.unmapped_columns)),
        (
            "未落表属性",
            [f"{view.name(a)} {expr_span(a)}" for g in gaps.values() for a in g.unbound_attributes],
        ),
        (
            "缺码值的状态/码值类属性",
            [f"{view.name(a)} {expr_span(a)}" for g in gaps.values() for a in g.missing_codes],
        ),
    ]
    if view.has_evidence:
        sections += [
            (
                "证据与目录矛盾",
                _unique(conflict_text(view, t, c) for g in gaps.values() for t, c in g.conflicts),
            ),
            (
                "元数据有、语料未用的绑定列",
                _unique(expr_span(c) for g in gaps.values() for c in g.declared_only),
            ),
            (
                "无连接证据的关系",
                _unique(
                    _relation_label(view, r) for g in gaps.values() for r in g.unjoined_relations
                ),
            ),
        ]
    lines: list[str] = []
    for title, items in sections:
        lines += ["", f"## {title}", ""]
        lines += [f"- {item}" for item in items] or ["（无）"]
    return lines


def _relation_label(view: CatalogView, relation_id: str) -> str:
    relation = view.relations[relation_id]
    return (
        f"{expr_span(relation_id)}：{view.name(relation['from'])} {cell(relation['name'])} "
        f"{view.name(relation['to'])}"
    )


def _unique(items) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen
