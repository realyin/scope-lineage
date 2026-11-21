"""``catalog context``: what one question needs about a few tables, columns and concepts.

``catalog query`` answers one name at a time from the built ontology, and a table's
semantics page says how to read the table -- but the page is the whole document, tens of
kilobytes a table. An agent writing one query needs a part of each: from the ontology,
what the table carries, its keys, its time columns, the tables each foreign key joins to,
and the constraints and metrics on its concept; from the semantics document, how to read
the table, what it is not for, what to watch, the open questions, the rules its scope
cites, and one line a column. ``context_pack`` returns exactly that, and a named column in
full. Provenance (``sources``, ``confidence``), upstream tables and the processing steps stay
in the document: they explain how the table was built, not how to query it. The tasks and
tables that read the table are kept, because "what does a change here reach" is a question
readers ask of a table.

Both inputs are plain dicts: the built ``ontology-json/3`` document and
``{db.table: table-semantics document}``. Nothing is read from disk here. A table with no
semantics document says so (``{"present": false}``) rather than carrying empty fields, so
a reader can tell "nothing to watch" from "nobody wrote it down".
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Optional

from .catalog_gaps import conflict_text
from .catalog_query import find_concepts
from .catalog_view import CatalogView, catalog_table_name, realises

__all__ = ["CONTEXT_FORMAT", "context_pack", "render_context_text"]

CONTEXT_FORMAT = "catalog-context/1"
# Keys of a semantics column kept in a column's full answer, in this order.
_COLUMN_KEYS = (
    "meaning", "category", "derivation", "branches", "code_values", "null_meaning", "watch",
)
_BINDING_KEYS = ("derivation", "time_role", "via", "code_map", "relation", "self_reference")


def context_pack(
    document: Mapping,
    semantics: Optional[Mapping[str, Mapping]],
    *,
    tables: Iterable[str] = (),
    columns: Iterable[str] = (),
    concepts: Iterable[str] = (),
) -> dict:
    """The pack for the named tables, columns (``db.table.column``) and concepts."""
    view = CatalogView(document)
    documents = {
        catalog_table_name(name).lower(): doc for name, doc in (semantics or {}).items()
    }
    pack: dict = {
        "doc_format": CONTEXT_FORMAT,
        "query": {"tables": list(tables), "columns": list(columns), "concepts": list(concepts)},
        "concepts": [],
        "tables": [],
        "columns": [],
        "missing": [],
    }
    for term in pack["query"]["concepts"]:
        # the page of a concept is named by its id without the prefix, so that spelling works
        found = find_concepts(view, term) or find_concepts(view, f"concept:{term}")
        if not found:
            pack["missing"].append({"kind": "concept", "term": term})
        pack["concepts"].extend(_concept(view, concept) for concept, _ in found)
    for term in pack["query"]["tables"]:
        rep = view.representation(term)
        if rep is None:
            pack["missing"].append({"kind": "table", "term": term})
            continue
        pack["tables"].append(_table(view, rep, documents.get(rep["table"].lower())))
    for term in pack["query"]["columns"]:
        answer = _column(view, term, documents)
        if answer is None:
            pack["missing"].append({"kind": "column", "term": term})
        else:
            pack["columns"].append(answer)
    return pack


def _ref(view: CatalogView, object_id: str) -> dict:
    return {"id": object_id, "name": view.name(object_id)}


# ------------------------------------------------------------------ concept


def _concept(view: CatalogView, concept: Mapping) -> dict:
    concept_id = concept["id"]
    answer = {
        "id": concept_id,
        "name": concept["name"],
        "kind": concept["kind"],
        "definition": concept.get("definition"),
        "synonyms": list(concept.get("synonyms") or []),
        "identifiers": [_ref(view, i["id"]) for i in view.identifiers_of(concept_id)],
        "tables": [
            {"table": rep["table"], "kind": rep["kind"]}
            for rep in view.representations_of(concept_id)
        ],
        "constraints": _constraints(view, concept_id),
        "metrics": [_metric(view, metric) for metric in view.metrics_on(concept_id)],
    }
    if concept.get("notes"):
        answer["notes"] = concept["notes"]
    return answer


def _constraints(view: CatalogView, concept_id: str) -> list[dict]:
    return [
        {
            "id": c["id"],
            "kind": c["kind"],
            "on": _ref(view, c["on"]),
            "expression": c.get("expression"),
            "strength": c.get("strength"),
        }
        for c in view.constraints_on(concept_id)
    ]


def _metric(view: CatalogView, metric: Mapping) -> dict:
    by_id = {c["id"]: c for c in view.constraints}
    answer = {
        key: metric[key]
        for key in (
            "id", "name", "definition", "aggregation", "filter", "time_window", "additivity",
            "unit", "status",
        )
        if metric.get(key) is not None
    }
    measure = metric.get("measure")
    if measure:
        answer["measure"] = {
            **_ref(view, measure),
            "columns": [
                f"{rep['table']}.{binding['column']}" for rep, binding in view.bindings_of(measure)
            ],
        }
    answer["dimensions"] = [_ref(view, d) for d in metric.get("dimensions") or []]
    answer["constraints"] = [
        {"id": c, "expression": (by_id.get(c) or {}).get("expression")}
        for c in metric.get("constraints") or []
    ]
    return answer


# -------------------------------------------------------------------- table


def _table(view: CatalogView, rep: Mapping, document: Optional[Mapping]) -> dict:
    concept_id = rep["concept"]
    grain = rep.get("grain") or {}
    key_ids = set(grain.get("identifiers") or [])
    key_columns = [
        b["column"]
        for b in rep["bindings"]
        if b["to"] == "identifier" and b.get("ref") in key_ids
    ]
    answer = {
        "table": rep["table"],
        "concept": _ref(view, concept_id),
        "kind": rep["kind"],
        "grain": {
            "columns": key_columns + list(grain.get("extra") or []),
            "source": grain.get("source"),
        },
        "time": rep.get("time"),
        "refresh": rep.get("refresh"),
        "scope": list(rep.get("scope") or []),
        "time_columns": [
            {"column": b["column"], "role": b["time_role"]}
            for b in rep["bindings"]
            if b.get("time_role")
        ],
        "joins": _joins(view, rep),
        "constraints": _constraints(view, concept_id),
        "metrics": [
            {"id": m["id"], "name": m["name"]} for m in view.metrics_on(concept_id)
        ],
    }
    conflicts = view.rep_evidence(rep["table"]).get("conflicts")
    if conflicts:
        answer["conflicts"] = [
            {"rule": conflict["rule"], "text": conflict_text(view, rep["table"], conflict)}
            for conflict in conflicts
        ]
    answer["semantics"] = _semantics(document)
    return answer


def _joins(view: CatalogView, rep: Mapping) -> list[dict]:
    """One entry per foreign-key column: the identifier it holds and where that key lives."""
    found = []
    for binding in rep["bindings"]:
        if binding["to"] != "foreign_identifier" or not binding.get("ref"):
            continue
        identifier = view.identifiers.get(binding["ref"]) or {}
        other = identifier.get("identifies")
        targets = [
            {"table": target["table"], "column": b["column"]}
            for target, b in view.bindings_of(binding["ref"])
            if b["to"] == "identifier"
            and (target["table"] != rep["table"] or binding.get("self_reference"))
        ]
        join = {
            "column": binding["column"],
            "identifier": _ref(view, binding["ref"]),
            "concept": _ref(view, other) if other else None,
            "to": sorted(targets, key=lambda t: (t["table"], t["column"])),
            "seen": _seen(view, rep, binding, other),
        }
        if binding.get("derivation"):
            join["derivation"] = binding["derivation"]
        found.append(join)
    return found


def _seen(view: CatalogView, rep: Mapping, binding: Mapping, other) -> list[dict]:
    """The JOINs the corpus showed for the relations this column realises."""
    seen = []
    for relation in view.relations_of(rep["concept"]):
        if other not in (relation["from"], relation["to"]):
            continue
        if not realises(binding, relation["id"]):
            continue
        for where, joins in (
            ("between_catalog_tables", view.relation_joins(relation["id"])),
            ("inside_producing_task", view.relation_source_joins(relation["id"])),
        ):
            if joins and joins.get("count"):
                seen.append({
                    "relation": relation["id"],
                    "where": where,
                    "count": joins["count"],
                    "on": [sample["on"] for sample in joins.get("samples") or []],
                })
    return seen


def _semantics(document: Optional[Mapping]) -> dict:
    if not document:
        return {"present": False}
    summary = document.get("summary") or {}
    row = summary.get("row") or {}
    refresh = summary.get("refresh") or {}
    watch = [_pick(item, ("kind", "text", "refs")) for item in summary.get("watch") or []]
    questions = [
        _pick(item, ("id", "text", "about", "status")) for item in summary.get("questions") or []
    ]
    scope = [_pick(item, ("text", "rule_refs")) for item in summary.get("scope") or []]
    cited = _cited_rules(scope, watch, questions)
    return {
        "present": True,
        "what": summary.get("what"),
        "row": _pick(row, ("text", "grain_columns", "unique", "note")),
        "refresh": _pick(refresh, ("cycle", "time", "how_to_read", "watch")),
        "scope": scope,
        "good_for": list(summary.get("good_for") or []),
        "not_for": list(summary.get("not_for") or []),
        "watch": watch,
        "questions": questions,
        "rules": [
            _pick(rule, ("id", "kind", "text", "sql", "watch"))
            for rule in document.get("rules") or []
            if rule.get("id") in cited
        ],
        # who reads this table: what a change to it reaches (the one lineage fact kept)
        "downstream": [_pick(item, ("task", "table")) for item in summary.get("downstream") or []],
        "columns": [
            _pick(column, ("column", "meaning", "category"))
            for column in document.get("columns") or []
        ],
    }


def _cited_rules(scope: list, watch: list, questions: list) -> set[str]:
    cited = {ref for line in scope for ref in line.get("rule_refs") or []}
    for item in watch:
        cited |= {r.split(":", 1)[1] for r in item.get("refs") or [] if r.startswith("rule:")}
    for item in questions:
        cited |= {r.split(":", 1)[1] for r in item.get("about") or [] if r.startswith("rule:")}
    return cited


def _pick(item: Mapping, keys: tuple) -> dict:
    return {key: item[key] for key in keys if item.get(key) not in (None, "", [])}


# ------------------------------------------------------------------- column


def _column(view: CatalogView, term: str, documents: Mapping) -> Optional[dict]:
    table_name, _, column_name = str(term).strip().rpartition(".")
    if not table_name:
        return None
    rep = view.representation(table_name)
    table = rep["table"] if rep else catalog_table_name(table_name).lower()
    document = documents.get(table.lower())
    folded = column_name.casefold()
    binding = next(
        (b for b in (rep or {}).get("bindings") or [] if b["column"].casefold() == folded), None
    )
    described = next(
        (
            c for c in (document or {}).get("columns") or []
            if str(c.get("column", "")).casefold() == folded
        ),
        None,
    )
    if binding is None and described is None:
        return None
    name = (binding or described)["column"]
    summary = (document or {}).get("summary") or {}
    tag = f"column:{name}".casefold()
    return {
        "table": table,
        "column": name,
        "catalog": _binding(view, table, binding) if binding else None,
        "semantics": _described(described) if described else None,
        "watch": [
            _pick(item, ("kind", "text", "refs"))
            for item in summary.get("watch") or []
            if tag in {str(r).casefold() for r in item.get("refs") or []}
        ],
        "questions": [
            _pick(item, ("id", "text", "about", "status"))
            for item in summary.get("questions") or []
            if tag in {str(r).casefold() for r in item.get("about") or []}
        ],
    }


def _described(column: Mapping) -> dict:
    answer = _pick(column, _COLUMN_KEYS)
    if answer.get("code_values"):
        # an empty string is a value a column can hold, so it is kept, not dropped
        answer["code_values"] = [
            {"value": v.get("value"), "meaning": v.get("meaning")} for v in answer["code_values"]
        ]
    if answer.get("branches"):
        answer["branches"] = [_pick(b, ("branch", "text")) for b in answer["branches"]]
    return answer


def _binding(view: CatalogView, table: str, binding: Mapping) -> dict:
    answer: dict = {"to": binding["to"]}
    ref = binding.get("ref")
    if ref:
        answer["ref"] = _ref(view, ref)
        if ref in view.attributes:
            attribute = view.attributes[ref][0]
            if attribute.get("definition"):
                answer["definition"] = attribute["definition"]
            if attribute.get("unit"):
                answer["unit"] = attribute["unit"]
            values = [
                {"code_set": code_set["id"], "values": [
                    _pick(value, ("value", "meaning", "retired", "unconfirmed"))
                    for value in code_set.get("values") or []
                ]}
                for code_set in view.attribute_code_sets(attribute)
            ]
            if values:
                answer["code_sets"] = values
    for key in _BINDING_KEYS:
        if binding.get(key) not in (None, "", [], False):
            answer[key] = binding[key]
    expression = view.binding_evidence(table, binding["column"]).get("expression")
    if expression:
        answer["expression"] = expression
    return answer


# --------------------------------------------------------------------- text


def render_context_text(pack: Mapping) -> str:
    """The pack as short Markdown: one block a concept, a table, a column."""
    lines: list[str] = []
    for concept in pack["concepts"]:
        lines += _concept_text(concept)
    for table in pack["tables"]:
        lines += _table_text(table)
    for column in pack["columns"]:
        lines += _column_text(column)
    kinds = {"concept": "概念", "table": "表", "column": "字段"}
    for item in pack["missing"]:
        lines.append(f"未找到：{kinds[item['kind']]} {item['term']}")
    return "\n".join(lines).rstrip("\n") + "\n"


def _concept_text(concept: Mapping) -> list[str]:
    lines = [f"# 概念 {concept['name']}（{concept['id']}，{concept['kind']}）", ""]
    if concept.get("definition"):
        lines.append(f"- 定义：{concept['definition']}")
    if concept.get("synonyms"):
        lines.append(f"- 同义词：{'、'.join(concept['synonyms'])}")
    if concept["identifiers"]:
        lines.append("- 标识：" + "、".join(f"{i['name']}（{i['id']}）" for i in concept["identifiers"]))
    lines.append(
        "- 表：" + ("、".join(f"{t['table']}（{t['kind']}）" for t in concept["tables"]) or "无")
    )
    if concept.get("notes"):
        lines.append(f"- 备注：{concept['notes']}")
    lines += _constraint_lines(concept["constraints"])
    if concept["metrics"]:
        lines += ["", "## 指标"]
        for metric in concept["metrics"]:
            lines += _metric_lines(metric)
    else:
        lines += ["", "## 指标", "目录没有为这个概念定义指标。"]
    return lines + [""]


def _metric_lines(metric: Mapping) -> list[str]:
    lines = [f"- {metric['name']}（{metric['id']}）：{metric.get('definition') or ''}"]
    measure = metric.get("measure")
    if measure:
        columns = "、".join(measure["columns"]) or "没有绑定的列"
        lines.append(f"  - 度量：{measure['name']}（{columns}）")
    for key, label in (
        ("aggregation", "聚合"), ("filter", "过滤"), ("time_window", "时间窗"),
        ("additivity", "可加性"), ("unit", "单位"), ("status", "状态"),
    ):
        if metric.get(key):
            lines.append(f"  - {label}：{metric[key]}")
    if metric["dimensions"]:
        lines.append("  - 维度：" + "、".join(d["name"] for d in metric["dimensions"]))
    for constraint in metric["constraints"]:
        lines.append(f"  - 约束 {constraint['id']}：{constraint.get('expression') or ''}")
    return lines


def _constraint_lines(constraints: list) -> list[str]:
    return [
        f"- 约束 {c['id']}（{c['kind']}，针对 {c['on']['name']}）：{c.get('expression') or ''}"
        for c in constraints
    ]


def _table_text(table: Mapping) -> list[str]:
    lines = [f"# 表 {table['table']}", "", "## 目录"]
    concept = table["concept"]
    lines.append(f"- 承载概念：{concept['name']}（{concept['id']}），表的种类 {table['kind']}")
    grain = table["grain"]
    if grain["columns"]:
        lines.append(f"- 粒度：{'、'.join(grain['columns'])}（{grain.get('source') or '未说明'}）")
    for conflict in table.get("conflicts") or []:
        lines.append(f"- 证据与目录矛盾：{conflict['text']}")
    if table.get("time") or table.get("refresh"):
        lines.append(f"- 时间形态：{table.get('time') or '未说明'}；刷新：{table.get('refresh') or '未说明'}")
    for column in table["time_columns"]:
        lines.append(f"- 时间列：{column['column']}（{column['role']}）")
    for line in table["scope"]:
        lines.append(f"- 范围：{line}")
    for join in table["joins"]:
        lines += _join_lines(table["table"], join)
    lines += _constraint_lines(table["constraints"])
    if table["metrics"]:
        lines.append(
            "- 这个概念上的指标：" + "、".join(f"{m['name']}（{m['id']}）" for m in table["metrics"])
        )
    return lines + _semantics_text(table["semantics"]) + [""]


def _join_lines(table: str, join: Mapping) -> list[str]:
    concept = join.get("concept")
    target = f"→ {concept['name']}" if concept else ""
    lines = [f"- 关联列 {join['column']}：{join['identifier']['name']} {target}".rstrip()]
    for other in join["to"]:
        lines.append(f"  - {table}.{join['column']} = {other['table']}.{other['column']}")
    if not join["to"]:
        lines.append("  - 目录里没有以这个标识为主键的表")
    if join.get("derivation"):
        lines.append(f"  - 取值：{join['derivation']}")
    places = {"between_catalog_tables": "目录表之间", "inside_producing_task": "产出任务内部"}
    for seen in join["seen"]:
        lines.append(f"  - 语料中见过 {seen['count']} 次（{places[seen['where']]}）：{'；'.join(seen['on'])}")
    return lines


def _semantics_text(sem: Mapping) -> list[str]:
    if not sem["present"]:
        return ["", "## 怎么读", "本表没有表语义文档：怎么读、不适用场景、注意事项和待确认问题都没有人写下来。"]
    lines = ["", "## 怎么读"]
    if sem.get("what"):
        lines.append(f"- 是什么：{sem['what']}")
    row = sem.get("row") or {}
    if row:
        note = f"；{row['note']}" if row.get("note") else ""
        lines.append(f"- 一行是：{row.get('text') or ''}（唯一：{row.get('unique') or '未说明'}）{note}")
    refresh = sem.get("refresh") or {}
    if refresh.get("how_to_read"):
        lines.append(f"- 取数：{refresh['how_to_read']}")
    if refresh.get("watch"):
        lines.append(f"- 取数注意：{refresh['watch']}")
    for line in sem["scope"]:
        refs = f"（规则 {'、'.join(line['rule_refs'])}）" if line.get("rule_refs") else ""
        lines.append(f"- 范围：{line.get('text') or ''}{refs}")
    for line in sem["good_for"]:
        lines.append(f"- 适用：{line}")
    lines += ["", "## 不适用"] + ([f"- {line}" for line in sem["not_for"]] or ["无"])
    lines += ["", "## 注意"]
    lines += [
        f"- （{item.get('kind') or '注意'}）{item.get('text') or ''}"
        + (f" [{'、'.join(item['refs'])}]" if item.get("refs") else "")
        for item in sem["watch"]
    ] or ["无"]
    lines += ["", "## 待确认问题"]
    lines += [_question_line(item) for item in sem["questions"]] or ["无"]
    if sem["rules"]:
        lines += ["", "## 被引用的规则"]
        for rule in sem["rules"]:
            lines.append(f"- {rule['id']}（{rule.get('kind') or ''}）：{rule.get('text') or ''}")
            if rule.get("sql"):
                lines.append(f"  - SQL：`{rule['sql']}`")
            if rule.get("watch"):
                lines.append(f"  - 注意：{rule['watch']}")
    lines += ["", "## 下游"]
    lines += [
        f"- {item.get('task') or '（任务未知）'}" + (f" → {item['table']}" if item.get("table") else "")
        for item in sem["downstream"]
    ] or ["表语义没有列出读这张表的任务。"]
    lines += ["", "## 字段一览"]
    lines += [
        f"- {c['column']}：{c.get('meaning') or ''}" + (f"（{c['category']}）" if c.get("category") else "")
        for c in sem["columns"]
    ]
    return lines


def _question_line(item: Mapping) -> str:
    about = f" [{'、'.join(item['about'])}]" if item.get("about") else ""
    return f"- {item.get('id')}（{item.get('status') or '未说明'}）：{item.get('text') or ''}{about}"


def _column_text(column: Mapping) -> list[str]:
    lines = [f"# 字段 {column['table']}.{column['column']}", ""]
    catalog = column.get("catalog")
    if catalog is None:
        lines.append("- 目录：没有绑定这一列")
    else:
        ref = catalog.get("ref")
        bound = f"{ref['name']}（{ref['id']}）" if ref else ""
        lines.append(f"- 目录：{catalog['to']} {bound}".rstrip())
        for key, label in (
            ("definition", "定义"), ("unit", "单位"), ("derivation", "取值"),
            ("time_role", "时间角色"), ("via", "经由"), ("expression", "表达式"),
        ):
            if catalog.get(key):
                lines.append(f"  - {label}：{catalog[key]}")
        if catalog.get("code_map"):
            pairs = "、".join(f"{k}={v}" for k, v in catalog["code_map"].items())
            lines.append(f"  - 本列码值：{pairs}")
        for code_set in catalog.get("code_sets") or []:
            pairs = "、".join(
                f"{v.get('value')}={v.get('meaning')}" + ("（待确认）" if v.get("unconfirmed") else "")
                for v in code_set["values"]
            )
            lines.append(f"  - 码值集 {code_set['code_set']}：{pairs}")
    sem = column.get("semantics")
    if sem is None:
        lines.append("- 表语义：没有这一列的说明")
    else:
        lines.append(f"- 含义：{sem.get('meaning') or ''}" + (f"（{sem['category']}）" if sem.get("category") else ""))
        for key, label in (("derivation", "加工"), ("null_meaning", "空值"), ("watch", "注意")):
            if sem.get(key):
                lines.append(f"  - {label}：{sem[key]}")
        for branch in sem.get("branches") or []:
            lines.append(f"  - 分支 {branch.get('branch')}：{branch.get('text')}")
        if sem.get("code_values"):
            pairs = "、".join(f"{v.get('value')!r}={v.get('meaning')}" for v in sem["code_values"])
            lines.append(f"  - 码值：{pairs}")
    for item in column["watch"]:
        lines.append(f"- 表级注意（{item.get('kind') or '注意'}）：{item.get('text') or ''}")
    for item in column["questions"]:
        lines.append("- 待确认问题 " + _question_line(item)[2:])
    return lines + [""]
