"""The one-page overview that opens every concept page, in plain Chinese.

A reader opening a concept page asks what it is, how to tell one apart, where its data
lives and what it is tied to -- and should not have to read ids, eight-column tables or a
hundred attributes to find out. ``concept_overview`` answers those questions as a small
structure of names (never ids, never English enum words); ``overview_lines`` renders it
as the page's first section, and ``catalog query concept`` prints the same fields. The
full detail stays on the page, after the overview, as its appendix.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Callable, Optional

from .catalog_gaps import concept_gaps
from .catalog_view import KIND_TEXT, CatalogView
from .markdown_text import normalize_inline

# The representation kinds that say where a concept's own data lives, by concept kind.
MAIN_KINDS = {"entity": ("core", "extension"), "event": ("event_detail",), "role": ("role_view",)}
WATCH_LIMIT = 5
ABOUT_CHARS, CONDITION_CHARS, WATCH_CHARS = 30, 30, 60
CONFIRMED = " ✓"


def clip(text, limit: int) -> str:
    """``text`` cut to ``limit`` characters, the ellipsis counted among them."""
    text = normalize_inline(str(text)).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def scope_words(view: CatalogView, scope) -> str:
    """``global`` -> 全局唯一; ``{per: [客户, App]}`` -> 每个客户×App 一个."""
    if scope == "global":
        return "全局唯一"
    names = "×".join(view.name(item) for item in scope["per"])
    return f"每个{names}{' ' if names[-1:].isascii() else ''}一个"


def arises_words(view: CatalogView, arises: Optional[Mapping]) -> str:
    """When an identifier comes into being: 一开始就有, or its condition and state."""
    if not arises:
        return "一开始就有"
    text = clip(arises["condition"], CONDITION_CHARS)
    if arises.get("state"):
        text += f"（进入「{view.state_name(arises['state'])}」状态时）"
    return text


def state_flow(view: CatalogView, states: Mapping) -> str:
    """The state values in order, each step naming the events that move it; transitions
    between values that are not neighbours in that order follow in brackets."""
    names = {item["value"]: item["name"] for item in states["values"]}
    order = [item["value"] for item in states["values"]]

    def moved(source, target) -> list:
        return [
            view.name(t["event"])
            for t in states["transitions"]
            if (t["from"], t["to"]) == (source, target)
        ]

    def step(source, target) -> str:
        events = "、".join(moved(source, target))
        return f" —{events}→ " if events else " → "

    text = names[order[0]] if order else ""
    for source, target in zip(order, order[1:]):
        text += step(source, target) + names[target]
    chain = set(zip(order, order[1:]))
    others = dict.fromkeys(
        (t["from"], t["to"]) for t in states["transitions"] if (t["from"], t["to"]) not in chain
    )
    extra = "；".join(
        names.get(s, s) + step(s, t).rstrip() + " " + names.get(t, t) for s, t in others
    )
    return f"{text}（另：{extra}）" if extra else text


def _confirmed(obj: Mapping) -> bool:
    return obj.get("status") == "confirmed"


# ----------------------------------------------------------------- building


def concept_overview(view: CatalogView, concept_id: str) -> dict:
    """The overview's fields: names and short texts, every list in the catalog's order."""
    concept = view.concepts[concept_id]
    gaps = concept_gaps(view, concept_id)
    states = concept.get("states")
    return {
        "kind": KIND_TEXT[concept["kind"]],
        "domain": view.name(concept["domain"]),
        "drafted_percent": round(100 * gaps.drafted / gaps.total) if gaps.total else 0,
        "what": normalize_inline(concept.get("definition") or "") or None,
        "identified_by": _identified_by(view, concept),
        "states": state_flow(view, states) if states and states.get("values") else None,
        "player": view.name(concept["player"]) if concept.get("player") else None,
        "condition": normalize_inline(concept["condition"]) if concept.get("condition") else None,
        "participants": [
            {"role_name": p["role_name"], "concept": view.name(p["concept"])}
            for p in concept.get("participants") or []
        ],
        "occurred_at": view.name(concept["occurred_at"]) if concept.get("occurred_at") else None,
        "data": _data(view, concept),
        "carriers": _carriers(view, concept),
        **_relations(view, concept_id),
        "events": _events(view, concept_id),
        "roles": [
            {
                "name": role["name"],
                "condition": clip(role["condition"], CONDITION_CHARS),
                "confirmed": _confirmed(role),
            }
            for role in view.roles_played_by(concept_id)
        ],
        "watch": _watch(view, concept),
    }


def _identified_by(view: CatalogView, concept: dict) -> list[dict]:
    return [
        {
            "name": identifier["name"],
            "arises": arises_words(view, identifier.get("arises_when")),
            "scope": scope_words(view, identifier["scope"]),
            "primary": identifier["id"] == concept.get("primary_identifier"),
            "confirmed": _confirmed(identifier),
        }
        for identifier in view.identifiers_of(concept["id"])
    ]


def _listed_reps(view: CatalogView, concept: dict) -> list[dict]:
    """The concept's own tables by its kind, then any deprecated one (to say what replaced it)."""
    reps = view.representations_of(concept["id"])
    kinds = MAIN_KINDS[concept["kind"]]
    main = [
        rep
        for kind in kinds
        for rep in reps
        if rep["kind"] == kind and rep["table_status"] != "deprecated"
    ]
    return main + [r for r in reps if r["table_status"] == "deprecated"]


def _data(view: CatalogView, concept: dict) -> list[dict]:
    return [
        {
            "table": rep["table"],
            "about": _about(view, rep),
            "replaced_by": rep.get("replaced_by"),
            "confirmed": _confirmed(rep),
        }
        for rep in _listed_reps(view, concept)
    ]


def _about(view: CatalogView, rep: dict) -> Optional[str]:
    """The table card's comment, else the first line of the catalog's notes on the table."""
    comment = view.rep_evidence(rep["table"]).get("table_comment")
    note = str(rep.get("notes") or "").strip().splitlines()
    text = comment or (note[0] if note else "")
    return clip(text, ABOUT_CHARS) if text else None


def _carriers(view: CatalogView, concept: dict) -> dict:
    """How many more tables carry one of the concept's identifiers, over how many domains."""
    listed = {rep["table"] for rep in _listed_reps(view, concept)}
    others = [rep for rep, _ in view.carriers_of(concept["id"]) if rep["table"] not in listed]
    domains = {(view.concepts.get(rep["concept"]) or {}).get("domain") for rep in others}
    return {"tables": len(others), "domains": len(domains)}


def _relations(view: CatalogView, concept_id: str) -> dict:
    """``owns``: compositions whose whole this concept is; ``associates``: the rest, each
    read from this concept's side."""
    owns, associates = [], []
    for relation in view.relations_of(concept_id):
        if relation["kind"] == "participation":
            continue
        item = {"text": _reading(view, concept_id, relation), "confirmed": _confirmed(relation)}
        whole = relation["kind"] == "composition" and relation["from"] == concept_id
        (owns if whole else associates).append(item)
    return {"owns": owns, "associates": associates}


def _reading(view: CatalogView, concept_id: str, relation: dict) -> str:
    """``<verb> <other>``: the name from the source, the inverse name from the target; a
    target with no inverse name reads the whole relation."""
    if relation["from"] == concept_id:
        return normalize_inline(f"{relation['name']} {view.name(relation['to'])}")
    if relation.get("inverse_name"):
        return normalize_inline(f"{relation['inverse_name']} {view.name(relation['from'])}")
    source, target = view.name(relation["from"]), view.name(relation["to"])
    return normalize_inline(f"{source} {relation['name']} {target}")


def _events(view: CatalogView, concept_id: str) -> list[dict]:
    """The events the concept takes part in, grouped by the event's domain."""
    groups: dict[str, list] = {}
    for relation in view.relations_of(concept_id):
        if relation["kind"] != "participation" or relation["to"] != concept_id:
            continue
        event = view.concepts.get(relation["from"]) or {}
        domain = view.name(event.get("domain") or "")
        groups.setdefault(domain, []).append(
            {"name": view.name(relation["from"]), "confirmed": _confirmed(relation)}
        )
    return [{"domain": domain, "events": events} for domain, events in groups.items()]


def _watch(view: CatalogView, concept: dict) -> list[dict]:
    """Hard rules and business rules on the concept, its attributes and identifiers."""
    targets = {concept["id"], *(a["id"] for a in concept.get("attributes") or [])}
    targets |= {i["id"] for i in view.identifiers_of(concept["id"])}
    found = [
        c
        for c in view.constraints_on(concept["id"])
        if c["on"] in targets and (c["strength"] == "hard" or c["kind"] == "business_rule")
    ]
    found.sort(key=lambda c: not _confirmed(c))
    return [
        {"text": clip(c["expression"], WATCH_CHARS), "confirmed": _confirmed(c)}
        for c in found[:WATCH_LIMIT]
    ]


# ----------------------------------------------------------------- wording


def _mark(item: Mapping) -> str:
    return CONFIRMED if item.get("confirmed") else ""


def identifier_items(overview: Mapping) -> list[str]:
    return [
        f"{i['name']}：{i['arises']}，{i['scope']}" + ("（主标识）" if i["primary"] else "") + _mark(i)
        for i in overview["identified_by"]
    ]


def data_label(overview: Mapping) -> str:
    return "记录在" if overview["kind"] == KIND_TEXT["event"] else "数据在哪"


def data_items(overview: Mapping, code: Callable[[str], str], pointer: str = "") -> list[str]:
    """Each listed table (``code`` formats a table name), then the count of the others."""
    items = []
    for item in overview["data"]:
        if item["replaced_by"]:
            items.append(f"{code(item['table'])} 已废弃，改用 {code(item['replaced_by'])}")
            continue
        about = f"（{item['about']}）" if item["about"] else ""
        items.append(code(item["table"]) + about + _mark(item))
    carriers = overview["carriers"]
    if carriers["tables"]:
        lead = "另有 " if items else ""
        items.append(
            f"{lead}{carriers['tables']} 张表带本概念的标识，"
            f"分布在 {carriers['domains']} 个域{pointer}"
        )
    return items


def _joined(items: list, key: str = "text") -> str:
    return "、".join(f"{item[key]}{_mark(item)}" for item in items)


def _kind_lines(overview: Mapping) -> list[tuple[str, str]]:
    """``(label, text)`` for the one-line fields; empty texts are dropped by the caller."""
    participants = "；".join(f"{p['role_name']} → {p['concept']}" for p in overview["participants"])
    role = ""
    if overview["player"]:
        role = f"{overview['player']}；**成立条件**：{overview['condition'] or '—'}"
    return [
        ("承担者", role),
        ("参与者", participants),
        ("发生时间", overview["occurred_at"] or ""),
    ]


def overview_lines(
    overview: Mapping, link: Callable[[str], Optional[str]] = lambda _table: None
) -> list[str]:
    """The overview as markdown: one paragraph per field, lists as bullets, no tables.

    ``link`` gives a table's page to link its name to (``catalog render --semantics``).
    """

    def code(table: str) -> str:
        target = link(table)
        return f"[{_code(table)}]({target})" if target else _code(table)

    blocks = [
        _line("是什么", overview["what"] or ""),
        _bullets("怎么认出来", identifier_items(overview)),
        _line("状态", overview["states"] or ""),
        *(_line(label, text) for label, text in _kind_lines(overview)),
        _bullets(data_label(overview), data_items(overview, code, "（见附录 A3）")),
        _line("拥有的", _joined(overview["owns"])),
        _line("关联的", _joined(overview["associates"])),
        _bullets(
            "参与的事件",
            [f"{g['domain']}：{_joined(g['events'], 'name')}" for g in overview["events"]],
        ),
        _bullets("扮演的角色", [f"{r['name']}：{r['condition']}{_mark(r)}" for r in overview["roles"]]),
        _bullets("要注意", [f"{w['text']}{_mark(w)}" for w in overview["watch"]]),
    ]
    lines: list[str] = []
    for block in (b for b in blocks if b):
        lines += ["", *block] if lines else block
    return lines


def _code(table: str) -> str:
    return f"`{table}`"


def _line(label: str, text: str) -> list[str]:
    return [f"**{label}**：{text}"] if text else []


def _bullets(label: str, items: list[str]) -> list[str]:
    return [f"**{label}**：", "", *(f"- {item}" for item in items)] if items else []
