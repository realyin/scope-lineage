"""One concept page (``concepts/<slug>.md``): the six things a reader asks of a concept.

1. 定义与身份 -- what it is, how it is told apart (identifiers, states, synonyms);
2. 数据清单 -- which tables carry it, grouped by how they carry it;
3. 属性 -- its business attributes, each with the table columns that hold it;
4. 关系 -- relations, the events it takes part in, the roles it plays or is;
5. 约束 -- the rules on it, by kind;
6. 治理缺口 -- what the catalog still lacks and where the corpus disagrees.

The page reads the built ``ontology-json/3`` document only. Evidence merged by
``catalog build --lineage/--tables`` is shown beside the catalog's claim and labelled
「血缘」 so it is never mistaken for one; without evidence those cells say 「—」.
"""

from __future__ import annotations

from .catalog_gaps import concept_gaps, conflict_text, share_text
from .catalog_view import (
    CATEGORIES,
    CONFIDENCE_TEXT,
    GRAIN_SOURCE_TEXT,
    KIND_TEXT,
    MAPPING_TEXT,
    REPRESENTATION_KINDS,
    STRENGTH_TEXT,
    TABLE_STATUS_TEXT,
    TIME_TEXT,
    CatalogView,
    concept_filename,
    status_text,
)
from .catalog_view import CONSTRAINT_KINDS as _CONSTRAINT_KINDS
from .catalog_view import RELATION_KIND_TEXT as _RELATION_KIND_TEXT
from .markdown_text import cell, expr_span

NONE = "—"
CONSTRAINT_TEXT = dict(_CONSTRAINT_KINDS)
PARTICIPANT_TEXT = {"one": "一个", "many": "多个"}
SECTION_TITLES = ("定义与身份", "数据清单", "属性", "关系", "约束", "治理缺口")


def render_concept_page(view: CatalogView, concept_id: str) -> str:
    concept = view.concepts[concept_id]
    domain = view.domains.get(concept["domain"]) or {}
    lines = [
        f"# {concept['name']}",
        "",
        f"{expr_span(concept_id)} · {KIND_TEXT[concept['kind']]} · "
        f"[{domain.get('name', concept['domain'])}](../index.md) · {status_text(concept)}",
    ]
    sections = (_identity, _inventory, _attributes, _relations, _constraints, _gaps)
    for number, (title, section) in enumerate(zip(SECTION_TITLES, sections), start=1):
        lines += ["", f"## {number}. {title}", "", *section(view, concept)]
    return "\n".join(lines) + "\n"


def link(view: CatalogView, concept_id: str) -> str:
    if concept_id not in view.concepts:
        return expr_span(concept_id)
    return f"[{view.name(concept_id)}]({concept_filename(concept_id)})"


def table_row(*cells) -> str:
    return "| " + " | ".join(cells) + " |"


def table_head(*names) -> list[str]:
    return [table_row(*names), table_row(*(["---"] * len(names)))]


# ----------------------------------------------------------- 1. 定义与身份


def _identity(view: CatalogView, concept: dict) -> list[str]:
    lines = [cell(concept.get("definition") or "（目录未写定义）"), ""]
    lines += table_head("项", "内容")
    lines.append(table_row("种类", KIND_TEXT[concept["kind"]]))
    lines.append(table_row("状态", status_text(concept)))
    lines.append(table_row("同义词", cell("、".join(concept["synonyms"])) or NONE))
    primary = concept.get("primary_identifier")
    if primary:
        lines.append(table_row("主标识符", f"{view.name(primary)} {expr_span(primary)}"))
    lines += _kind_rows(view, concept)
    lines += _identifier_table(view, concept)
    lines += _state_machine(view, concept)
    return lines


def _kind_rows(view: CatalogView, concept: dict) -> list[str]:
    rows = []
    if concept.get("occurred_at"):
        rows.append(
            table_row(
                "发生时间",
                f"{view.name(concept['occurred_at'])} {expr_span(concept['occurred_at'])}",
            )
        )
    for participant in concept.get("participants") or []:
        count = PARTICIPANT_TEXT[participant["cardinality"]]
        rows.append(
            table_row(
                f"参与者 {cell(participant['role_name'])}",
                f"{link(view, participant['concept'])}（{count}）",
            )
        )
    if concept.get("player"):
        rows.append(table_row("承担者", link(view, concept["player"])))
        rows.append(table_row("语境", view.name(concept["context"])))
        rows.append(table_row("成立条件", cell(concept["condition"])))
    return rows


def _identifier_table(view: CatalogView, concept: dict) -> list[str]:
    identifiers = view.identifiers_of(concept["id"])
    if not identifiers:
        return ["", "### 标识符", "", "（目录未登记标识符）"]
    lines = ["", "### 标识符", ""]
    lines += table_head("标识符", "产生条件", "唯一范围", "物理拼写", "对照", "状态")
    for identifier in identifiers:
        primary = "（主）" if identifier["id"] == concept.get("primary_identifier") else ""
        lines.append(
            table_row(
                f"{identifier['name']} {expr_span(identifier['id'])}{primary}",
                arises_text(view, identifier),
                scope_text(view, identifier),
                spellings_text(identifier),
                mappings_text(view, identifier),
                status_text(identifier),
            )
        )
    return lines


def arises_text(view: CatalogView, identifier: dict) -> str:
    arises = identifier.get("arises_when")
    if not arises:
        return "始终"
    state = f"（状态：{view.state_name(arises['state'])}）" if arises.get("state") else ""
    return cell(arises["condition"]) + state


def scope_text(view: CatalogView, identifier: dict) -> str:
    scope = identifier["scope"]
    if scope == "global":
        return "全局"
    return "每个" + "、".join(view.name(item) for item in scope["per"]) + "内唯一"


def spellings_text(identifier: dict) -> str:
    return (
        "；".join(
            expr_span(f"{s['table']}.{s['column']}" if s.get("table") else s["column"])
            for s in identifier["spellings"]
        )
        or NONE
    )


def mappings_text(view: CatalogView, identifier: dict) -> str:
    parts = []
    for mapping in identifier["maps_to"]:
        via = "、".join(expr_span(table) for table in mapping["via"])
        text = f"{view.name(mapping['identifier'])} {MAPPING_TEXT[mapping['cardinality']]}"
        parts.append(f"{text}，经 {via}" if via else text)
    return "；".join(parts) or NONE


def _state_machine(view: CatalogView, concept: dict) -> list[str]:
    states = concept.get("states")
    if not states:
        return []
    names = {item["value"]: item["name"] for item in states["values"]}
    lines = [
        "",
        "### 状态机",
        "",
        f"状态属性：{view.name(states['attribute'])} {expr_span(states['attribute'])}",
        "",
    ]
    lines += table_head("值", "名称")
    lines += [table_row(expr_span(item["value"]), cell(item["name"])) for item in states["values"]]
    if states["transitions"]:
        lines += ["", *table_head("迁移事件", "从", "到")]
        lines += [
            table_row(
                link(view, t["event"]), names.get(t["from"], t["from"]), names.get(t["to"], t["to"])
            )
            for t in states["transitions"]
        ]
    return lines


# ------------------------------------------------------------- 2. 数据清单


def _inventory(view: CatalogView, concept: dict) -> list[str]:
    reps = view.representations_of(concept["id"])
    if not reps:
        return ["（目录未登记表现表）"]
    lines: list[str] = []
    for kind, label in REPRESENTATION_KINDS:
        group = [rep for rep in reps if rep["kind"] == kind]
        if not group:
            continue
        lines += [f"### {label}", ""]
        lines += table_head("表", "粒度", "时间语义", "更新频率", "记录范围", "生产任务", "表状态")
        lines += [_rep_row(view, rep) for rep in group]
        lines += [*_lineage_lines(view, group), ""]
    return lines[:-1]


def _rep_row(view: CatalogView, rep: dict) -> str:
    evidence = view.rep_evidence(rep["table"])
    return table_row(
        expr_span(rep["table"]),
        grain_text(view, rep),
        TIME_TEXT[rep["time"]],
        _refresh_text(rep, evidence),
        cell("；".join(rep["scope"])) or "全部",
        "、".join(evidence.get("producing_tasks") or []) or NONE,
        _table_status(rep),
    )


def grain_text(view: CatalogView, rep: dict) -> str:
    grain = rep["grain"]
    parts = [view.name(i) for i in grain["identifiers"]] + [expr_span(c) for c in grain["extra"]]
    text = f"{' + '.join(parts) or '未声明'}（{GRAIN_SOURCE_TEXT[grain['source']]}）"
    proof = view.rep_evidence(rep["table"]).get("grain_proof")
    if proof:
        keys = "、".join(expr_span(k) for k in proof["keys"]) or "无键"
        text += f"；血缘{CONFIDENCE_TEXT[proof['confidence']]} {keys}"
    return text


def _refresh_text(rep: dict, evidence: dict) -> str:
    parts = [cell(rep["refresh"])] if rep.get("refresh") else []
    if evidence.get("refresh"):
        parts.append("调度 " + "、".join(evidence["refresh"]))
    return "；".join(parts) or NONE


def _table_status(rep: dict) -> str:
    text = f"{TABLE_STATUS_TEXT[rep['table_status']]} · {status_text(rep)}"
    if rep.get("replaced_by"):
        text += f"；由 {expr_span(rep['replaced_by'])} 替代"
    return text


def _lineage_lines(view: CatalogView, reps: list[dict]) -> list[str]:
    lines = []
    for rep in reps:
        evidence = view.rep_evidence(rep["table"])
        hops = [
            f"{label} " + "、".join(expr_span(t) for t in evidence[key])
            for key, label in (("upstream_tables", "上游"), ("downstream_tables", "下游"))
            if evidence.get(key)
        ]
        if hops:
            lines.append(f"- {expr_span(rep['table'])} 血缘一跳：" + "；".join(hops))
    return ["", *lines] if lines else []


# ----------------------------------------------------------------- 3. 属性


def _attributes(view: CatalogView, concept: dict) -> list[str]:
    attributes = concept.get("attributes") or []
    if not attributes:
        return ["（目录未登记属性）"]
    lines: list[str] = []
    for category, label in CATEGORIES:
        group = [a for a in attributes if a["category"] == category]
        if not group:
            continue
        lines += [f"### {label}", ""]
        lines += table_head("属性", "定义", "类型/单位", "码值", "所在表列", "加工口径", "状态")
        lines += [_attribute_row(view, attribute) for attribute in group] + [""]
    return lines[:-1]


def _attribute_row(view: CatalogView, attribute: dict) -> str:
    kind = " / ".join(cell(attribute[key]) for key in ("type", "unit") if attribute.get(key))
    return table_row(
        f"{attribute['name']} {expr_span(attribute['id'])}",
        cell(attribute.get("definition") or NONE),
        kind or NONE,
        codes_text(view, attribute.get("code_set")),
        columns_text(view, attribute["id"]),
        derivation_text(view, attribute),
        status_text(attribute),
    )


def codes_text(view: CatalogView, code_set_id) -> str:
    code_set = view.code_sets.get(code_set_id)
    if not code_set:
        return NONE
    values = [
        f"{cell(v['value'])}={cell(v['meaning'])}" + ("（停用）" if v["retired"] else "")
        for v in code_set["values"]
    ]
    return "；".join(values) or NONE


def columns_text(view: CatalogView, ref: str) -> str:
    parts = []
    for rep, binding in view.bindings_of(ref):
        text = expr_span(f"{rep['table']}.{binding['column']}")
        if binding.get("code_map"):
            pairs = ", ".join(f"{cell(k)}→{cell(v)}" for k, v in binding["code_map"].items())
            text += f"（码值映射 {pairs}）"
        if view.binding_evidence(rep["table"], binding["column"]).get("declared_only"):
            text += "（元数据有、语料未用）"
        parts.append(text)
    return "；".join(parts) or "（未落表）"


def derivation_text(view: CatalogView, attribute: dict) -> str:
    parts = [cell(attribute["derivation"])] if attribute.get("derivation") else []
    for rep, binding in view.bindings_of(attribute["id"]):
        column = expr_span(f"{rep['table']}.{binding['column']}")
        if binding.get("derivation"):
            parts.append(f"{column}：{cell(binding['derivation'])}")
            continue
        evidence = view.binding_evidence(rep["table"], binding["column"])
        if evidence.get("expression"):
            parts.append(f"{column} = {expr_span(evidence['expression'])}（血缘）")
    return "；".join(parts) or NONE


# ----------------------------------------------------------------- 4. 关系


def _relations(view: CatalogView, concept: dict) -> list[str]:
    concept_id = concept["id"]
    plain = [r for r in view.relations_of(concept_id) if r["kind"] != "participation"]
    lines = ["### 关联、组成与泛化", ""]
    if plain:
        lines += table_head("关系", "种类", "读法", "对端", "基数", "证据连接", "状态")
        lines += [_relation_row(view, concept_id, relation) for relation in plain]
    else:
        lines.append("（无）")
    lines += _participations(view, concept)
    lines += _roles(view, concept)
    return lines


def _relation_row(view: CatalogView, concept_id: str, relation: dict) -> str:
    other = relation["to"] if relation["from"] == concept_id else relation["from"]
    return table_row(
        f"{cell(relation['name'])} {expr_span(relation['id'])}",
        _RELATION_KIND_TEXT[relation["kind"]],
        reading_text(view, concept_id, relation),
        link(view, other),
        f"{view.name(relation['from'])} {relation['cardinality']['from']} : "
        f"{view.name(relation['to'])} {relation['cardinality']['to']}",
        joins_text(view, relation["id"]),
        status_text(relation),
    )


def reading_text(view: CatalogView, concept_id: str, relation: dict) -> str:
    """The relation read from this concept's side: its inverse name when it is the target."""
    source, target = view.name(relation["from"]), view.name(relation["to"])
    if (
        relation["to"] == concept_id
        and relation["from"] != concept_id
        and relation.get("inverse_name")
    ):
        return cell(f"{target} {relation['inverse_name']} {source}")
    return cell(f"{source} {relation['name']} {target}")


def joins_text(view: CatalogView, relation_id: str) -> str:
    joins = view.relation_joins(relation_id)
    if joins is None:
        return "—（一端无表现表）" if view.lineage_checked() else NONE
    if not joins["count"]:
        return "0 次"
    return f"{joins['count']} 次（如 {expr_span(joins['samples'][0]['on'])}）"


def _participations(view: CatalogView, concept: dict) -> list[str]:
    concept_id = concept["id"]
    taking = [
        r
        for r in view.relations_of(concept_id)
        if r["kind"] == "participation" and r["to"] == concept_id
    ]
    lines = ["", "### 参与的事件", ""]
    if not taking:
        return lines + ["（无）"]
    lines += table_head("事件", "本概念角色", "事件表现表数", "证据连接")
    for relation in taking:
        tables = len(view.representations_of(relation["from"]))
        lines.append(
            table_row(
                link(view, relation["from"]),
                cell(relation["name"]),
                str(tables),
                joins_text(view, relation["id"]),
            )
        )
    return lines


def _roles(view: CatalogView, concept: dict) -> list[str]:
    roles = view.roles_played_by(concept["id"])
    lines = ["", "### 本概念的角色", ""]
    if concept["kind"] == "role":
        return lines + [
            f"本概念是{link(view, concept['player'])}的角色，成立条件：{cell(concept['condition'])}"
        ]
    if not roles:
        return lines + ["（无）"]
    lines += table_head("角色", "语境", "成立条件", "表现表数")
    for role in roles:
        tables = len(view.representations_of(role["id"]))
        lines.append(
            table_row(
                link(view, role["id"]),
                view.name(role["context"]),
                cell(role["condition"]),
                str(tables),
            )
        )
    return lines


# ----------------------------------------------------------------- 5. 约束


def _constraints(view: CatalogView, concept: dict) -> list[str]:
    constraints = view.constraints_on(concept["id"])
    if not constraints:
        return ["（无）"]
    lines = table_head("约束", "种类", "作用对象", "表达式", "强度", "状态")
    for constraint in constraints:
        lines.append(
            table_row(
                expr_span(constraint["id"]),
                CONSTRAINT_TEXT[constraint["kind"]],
                f"{view.name(constraint['on'])} {expr_span(constraint['on'])}",
                cell(constraint["expression"]),
                STRENGTH_TEXT[constraint["strength"]],
                status_text(constraint),
            )
        )
    return lines


# --------------------------------------------------------------- 6. 治理缺口


def _gaps(view: CatalogView, concept: dict) -> list[str]:
    gaps = concept_gaps(view, concept["id"])
    rows = [
        ("草拟占比", share_text(gaps.drafted, gaps.total)),
        ("没有表现表", "是" if gaps.no_representation else "否"),
        ("未绑定列", spans(gaps.unmapped_columns)),
        ("未落表属性", spans(gaps.unbound_attributes)),
        ("缺码值的状态/码值类属性", spans(gaps.missing_codes)),
    ]
    if view.has_evidence:
        rows += [
            (
                "证据与目录矛盾",
                "；".join(conflict_text(view, t, c) for t, c in gaps.conflicts) or "无",
            ),
            ("元数据有、语料未用的绑定列", spans(gaps.declared_only)),
            ("无连接证据的关系", spans(gaps.unjoined_relations)),
        ]
    return table_head("缺口", "明细") + [table_row(name, text) for name, text in rows]


def spans(items) -> str:
    return "；".join(expr_span(item) for item in items) or "无"
