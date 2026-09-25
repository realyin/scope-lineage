"""The few lines a person reads for one ``catalog query`` answer.

Reads only the structured result ``query_catalog`` returns, so the text never says
anything the ``--json`` answer does not.
"""

from __future__ import annotations

from collections.abc import Mapping

from .catalog_view import (
    BINDING_TEXT,
    CATEGORIES,
    CONFIDENCE_TEXT,
    GRAIN_SOURCE_TEXT,
    KIND_TEXT,
    REPRESENTATION_KINDS,
    TABLE_STATUS_TEXT,
    TIME_TEXT,
    code_value_text,
    status_text,
)

REP_KIND_TEXT = dict(REPRESENTATION_KINDS)
CATEGORY_TEXT = dict(CATEGORIES)


def render_query_text(result: Mapping) -> str:
    query, matches = result["query"], result["matches"]
    if not matches:
        return f"无匹配：{query['kind']} {query['term']!r}\n"
    render = {
        "concept": _concept,
        "table": _table,
        "column": _column,
        "identifier": _identifier,
        "attribute": _attribute,
        "related": _related,
        "carriers": _carriers,
    }[query["kind"]]
    return "\n\n".join("\n".join(render(match)) for match in matches) + "\n"


def _names(items, key: str = "name") -> str:
    return "、".join(str(item[key]) for item in items) or "（无）"


def _concept(match: Mapping) -> list[str]:
    identifiers = "、".join(
        f"{i['name']} {i['id']}" + ("（主）" if i["primary"] else "") for i in match["identifiers"]
    )
    lines = [
        f"{match['name']} {match['id']} · {KIND_TEXT[match['kind']]} · "
        f"{match['domain']['name']} · {status_text(match)}",
        f"  {match.get('definition') or '（目录未写定义）'}",
        f"  标识符：{identifiers or '（无）'}",
        f"  属性：{_names(match['attributes'])}",
    ]
    if match["states"]:
        lines.append(f"  状态：{'、'.join(match['states'])}")
    tables = "、".join(f"{t['table']}（{REP_KIND_TEXT[t['kind']]}）" for t in match["tables"])
    return lines + [f"  表：{tables or '（无）'}", f"  页面：{match['page']}"]


def _grain(match: Mapping) -> str:
    grain = match["grain"]
    parts = " + ".join([*grain["identifiers"], *grain["extra"]]) or "未声明"
    text = f"  粒度：{parts}（{GRAIN_SOURCE_TEXT[grain['source']]}）"
    proof = (match.get("evidence") or {}).get("grain_proof")
    if proof:
        text += f"；血缘{CONFIDENCE_TEXT[proof['confidence']]} {', '.join(proof['keys']) or '无键'}"
    return text


def _table(match: Mapping) -> list[str]:
    lines = [
        f"{match['table']} · {match['concept']['name']} {match['concept']['id']} · "
        f"{REP_KIND_TEXT[match['kind']]} · {TABLE_STATUS_TEXT[match['table_status']]}",
        _grain(match),
        f"  时间语义：{TIME_TEXT[match['time']]}"
        + (f"；{match['usage']}" if match.get("usage") else ""),
    ]
    evidence = match.get("evidence") or {}
    about = [
        f"{label} {text}"
        for label, text in (("表注释", evidence.get("table_comment")), ("备注", match.get("notes")))
        if text
    ]
    if about:
        lines.append(f"  说明：{'；'.join(about)}")
    facts = [
        f"{label}：{'、'.join(evidence[key])}"
        for key, label in (
            ("producing_tasks", "生产任务"),
            ("refresh", "调度"),
            ("upstream_tables", "上游"),
            ("downstream_tables", "下游"),
        )
        if evidence.get(key)
    ]
    if facts:
        lines.append("  " + "；".join(facts))
    return lines + [f"  - {_column_text(column)}" for column in match["columns"]]


def _column_text(column: Mapping) -> str:
    text = f"{column['column']} → {BINDING_TEXT[column['to']]}"
    if column.get("ref"):
        text += f" {column['ref_name']} {column['ref']}"
    if column["to"] == "foreign_attribute":
        text += f" of {column['concept']['name']}（经 {column['via']}）"
    elif column.get("concept"):
        text += f"（概念 {column['concept']['name']}）"
    if column.get("self_reference"):
        relations = "、".join(f"{r['name']} {r['id']}" for r in column["self_relations"])
        text += f"（自关联：{relations}）"
    if column.get("code_map"):
        text += "（码值 " + ", ".join(f"{k}→{v}" for k, v in column["code_map"].items()) + "）"
    evidence = column.get("evidence") or {}
    if column.get("derivation"):
        text += f"；口径 {column['derivation']}"
    elif evidence.get("expression"):
        text += f"；血缘 {evidence['expression']}"
    if evidence.get("declared_only"):
        text += "；元数据有、语料未用"
    return text


def _column(match: Mapping) -> list[str]:
    where = f"{match['table']}.{match['column']}"
    if "spelling_of" in match:
        spelled = match["spelling_of"]
        return [f"{where} 是标识符 {spelled['name']} {spelled['id']} 的物理拼写（目录未绑定此列）"]
    head = f"{match['table']}.{_column_text(match)}"
    sources = (match.get("evidence") or {}).get("sources")
    return [head] + ([f"  血缘来源：{'、'.join(sources)}"] if sources else [])


def _identifier(match: Mapping) -> list[str]:
    scope = match["scope"]
    scope_text = "全局" if scope == "global" else f"每个 {'、'.join(scope['per'])} 内唯一"
    spellings = "、".join(
        f"{s['table']}.{s['column']}" if s.get("table") else s["column"] for s in match["spellings"]
    )
    bound = "、".join(f"{b['table']}.{b['column']}" for b in match["bound_columns"])
    return [
        f"{match['name']} {match['id']} · 识别 {match['identifies']['name']} · {scope_text}",
        f"  物理拼写：{spellings or '（无）'}",
        f"  绑定列：{bound or '（无）'}",
    ]


def _attribute(match: Mapping) -> list[str]:
    kind = " / ".join(str(match[key]) for key in ("type", "unit") if match.get(key))
    lines = [
        f"{match['name']} {match['id']} · {match['concept']['name']} · "
        f"{CATEGORY_TEXT[match['category']]} · {kind}",
        f"  {match.get('definition') or '（目录未写定义）'}",
    ]
    if match.get("code_set"):
        values = "；".join(code_value_text(v) for v in match["code_set"]["values"])
        lines.append(f"  码值：{values}")
    if match.get("derivation"):
        lines.append(f"  口径：{match['derivation']}")
    return lines + [f"  - {c['table']}.{_column_text(c)}" for c in match["columns"]]


def _joins(item: Mapping) -> str:
    """``（2 次连接）``; without a JOIN, the tables holding both ends and the citations."""
    if item["joins"]:
        return f"（{item['joins']} 次连接）"
    parts = ["0 次连接"] if item["joins"] == 0 else []
    if item.get("carried_together"):
        parts.append("同表携带：" + "、".join(item["carried_together"]))
    if item.get("evidence"):
        parts.append("目录证据：" + "；".join(item["evidence"]))
    return f"（{'；'.join(parts)}）" if parts else ""


def _related(match: Mapping) -> list[str]:
    lines = [f"{match['concept']['name']} {match['concept']['id']} 的一跳邻居"]
    if match.get("player"):
        lines.append(f"  承担者：{match['player']['name']}")
    relations = "；".join(r["reading"] + _joins(r) for r in match["relations"])
    lines.append(f"  关系：{relations or '（无）'}")
    if "participants" in match:
        parts = "、".join(
            f"{p['concept']['name']}（{p['role_name']}）{_joins(p)}" for p in match["participants"]
        )
        lines.append(f"  参与者：{parts or '（无）'}")
    events = "、".join(
        f"{e['event']['name']}（{e['role_name']}）{_joins(e)}" for e in match["events"]
    )
    lines.append(f"  参与的事件：{events or '（无）'}")
    lines.append(f"  角色：{_names(match['roles'])}")
    lines.append(f"  表：{_names(match['tables'], 'table')}")
    carriers = "、".join(f"{t['table']}（{t['concept']['name']}）" for t in match["carriers"])
    lines.append(f"  带本概念标识的表：{carriers or '（无）'}")
    return lines


def _carriers(match: Mapping) -> list[str]:
    concept = match["concept"]
    if not match["identifiers"]:
        player = match.get("player")
        where = f"，见承担者 {player['name']} {player['id']}" if player else ""
        kind = "角色" if player else "本概念"
        return [f"{concept['name']} {concept['id']}：{kind}没有自己的标识符{where}"]
    identifiers = "、".join(f"{i['name']} {i['id']}" for i in match["identifiers"])
    lines = [f"带 {concept['name']} {concept['id']} 标识的表（{identifiers}）"]
    for table in match["tables"]:
        columns = "；".join(_carrier_column(c) for c in table["columns"])
        lines.append(f"  - {table['table']}（{table['concept']['name']}）：{columns}")
    return lines if match["tables"] else [*lines, "  （没有表绑定这些标识符）"]


def _carrier_column(column: Mapping) -> str:
    text = f"{column['column']} → {BINDING_TEXT[column['to']]} {column['identifier']['name']}"
    return text + ("（自关联）" if column.get("self_reference") else "")
