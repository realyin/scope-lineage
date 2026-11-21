"""``catalog search``: rank the catalog's objects against the words a reader uses.

``catalog query`` needs the catalog's own name for a thing and matches it exactly. A reader
has a business word or a whole question. ``search_catalog`` scores every concept, metric,
attribute, identifier, code set and table against that text and returns the best few, each
with its id, name, one line of summary and where it lives -- a list short enough to read in
full, for the reader to pick from and then ``query`` or ``context`` by id.

The match is lexical and needs nothing beyond the standard library. Text is cut into
tokens -- two-character windows over a run of CJK characters (so a business word matches
inside a longer one without a word list), lower-cased words over letters and digits (so
``loan_no`` matches ``LOAN_NO`` and each of its parts). A token found in a name counts for
more than one found in a definition, a rare token for more than a common one, and a name
the text covers whole for more than a name it only touches. The words that only frame a
question (每个, 多少, 是否, the 的 between two words ...) are left out of the text first.

A question often names two things, and one of them can bring many members -- attributes,
identifiers, tables -- that each match more of the words than the other thing's concept.
So the list keeps a concept's members to two places before every concept the text names is
listed; the rest of the members follow. Scores order the list otherwise; they mean nothing
across two searches.

It ranks and never decides: a hit is a candidate, and nothing here rewrites the catalog.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Optional

from .catalog_view import CatalogView, catalog_table_name

__all__ = ["SEARCH_KINDS", "named_objects", "render_search_text", "search_catalog"]

SEARCH_KINDS = ("concept", "metric", "attribute", "identifier", "code_set", "table")
KIND_TEXT = {
    "concept": "概念", "metric": "指标", "attribute": "属性", "identifier": "标识",
    "code_set": "码值集", "table": "表",
}
# Field label -> weight, in the order ``matched_in`` lists them. A name-like field also
# earns more the more of it the text covers.
_FIELDS = {
    "name": 3.0, "synonym": 3.0, "term": 3.0, "id": 2.0, "column": 2.0, "comment": 1.5,
    "definition": 1.0, "values": 1.0, "concept": 1.0, "semantics": 1.0,
}
_NAME_LIKE = ("name", "synonym", "term")
# A concept the text names in one of these fields of its own is named by the text.
_NAMING = ("name", "synonym", "term", "id")
# Kinds that belong to a concept: its attributes, its identifiers, its tables.
_MEMBER_KINDS = ("attribute", "identifier", "table")
# How many places a concept's members take before each concept the text names is listed.
_MEMBER_PLACES = 2
# Question scaffolding, set aside from the text only (never from the catalog): a two-character
# token made only of these characters (每个, 多少, 是否, 哪些, 有没 ...), a token holding a
# structural particle (月的, 的还, 什么 ...), and a few question verbs. A token with any other
# character stays: 还款, 个人, 一通.
_SCAFFOLDING = set("每个各哪些多少几是否有没不要会能可以怎如何和与或及并且这那都也就谁什")
_PARTICLES = set("的了吗呢吧么")
_SCAFFOLDING_WORDS = {"统计", "写出", "列出", "给出", "说明", "请问", "一下", "一共"}
_SUMMARY_LENGTH = 120
_CJK = re.compile(r"[㐀-䶿一-鿿]+")
_WORD = re.compile(r"[a-z0-9]+")


def search_catalog(
    document: Mapping,
    text: str,
    semantics: Optional[Mapping[str, Mapping]] = None,
    *,
    kinds: Optional[Iterable[str]] = None,
    limit: int = 10,
) -> dict:
    """``{"query": {text, kinds, limit}, "hits": [...]}``, best first."""
    wanted = list(kinds) if kinds else list(SEARCH_KINDS)
    unknown = [kind for kind in wanted if kind not in SEARCH_KINDS]
    if unknown:
        raise ValueError(f"unknown search kind {unknown[0]!r}; one of {', '.join(SEARCH_KINDS)}")
    result = {"query": {"text": text, "kinds": wanted, "limit": limit}, "hits": []}
    query = _query_tokens(text)
    if not query:
        return result
    items = _items(CatalogView(document), semantics or {})
    indexed = [
        (item, {label: [_tokens(value) for value in values] for label, values in item["fields"].items()})
        for item in items
    ]
    frequency: dict[str, int] = {}
    for _, fields in indexed:
        seen = set().union(*(tokens for values in fields.values() for tokens in values))
        for token in seen & query:
            frequency[token] = frequency.get(token, 0) + 1
    total = len(indexed)
    weight = {token: math.log(1 + total / count) for token, count in frequency.items()}
    phrase = _fold(text)
    hits = []
    for item, fields in indexed:
        if item["kind"] not in wanted:
            continue
        score, named, matched = _score(item, fields, query, weight, phrase)
        if score > 0:
            hit = {
                "kind": item["kind"],
                "id": item["id"],
                "name": item["name"],
                "summary": _one_line(item["summary"]),
                "score": round(score, 3),
                "matched_in": matched,
            }
            if item.get("where"):
                hit["where"] = item["where"]
            hits.append((hit, _family(item), named))
    hits.sort(key=lambda entry: (-entry[0]["score"], SEARCH_KINDS.index(entry[0]["kind"]), entry[0]["id"]))
    result["hits"] = _fold_families(hits, max(limit, 0))
    return result


def named_objects(document: Mapping, texts: Iterable[str]) -> list[dict]:
    """The objects whose own name, synonym, term or id *is* one of ``texts``.

    Not a search: equality after NFKC, case folding and collapsing whitespace, so a reader
    can tell whether the catalog now carries a word, not what resembles it. Each object
    once, ``{kind, id, name, matched_in}``, in the order ``search`` builds its items.
    """
    wanted = {_same_text(text) for text in texts if _same_text(text)}
    found = []
    for item in _items(CatalogView(document), {}):
        matched = [
            label
            for label in _NAMING
            if any(_same_text(value) in wanted for value in item["fields"].get(label) or [])
        ]
        if matched:
            found.append(
                {"kind": item["kind"], "id": item["id"], "name": item["name"], "matched_in": matched}
            )
    return found


def _same_text(text) -> str:
    return " ".join(_fold(text).split())


def _fold_families(hits: list, limit: int) -> list[dict]:
    """The first ``limit`` hits by score, except that a concept's members give way.

    Once a concept's attributes, identifiers and tables hold ``_MEMBER_PLACES`` places in the
    list, its next member waits behind every concept the text names (in that concept's own
    name, synonym, term or id) that is not listed yet. A text about one thing -- or a ``--kind``
    without ``concept`` -- has no such concept waiting and keeps the order of its scores.
    """
    listed: list[dict] = []
    members: dict[str, int] = {}
    waiting = list(hits)
    while waiting and len(listed) < limit:
        pick = waiting[0]
        hit, family, _ = pick
        if hit["kind"] in _MEMBER_KINDS and members.get(family, 0) >= _MEMBER_PLACES:
            named = next((other for other in waiting if other[0]["kind"] == "concept" and other[2]), None)
            pick = named or pick
        waiting.remove(pick)
        hit, family, _ = pick
        listed.append(hit)
        if hit["kind"] in _MEMBER_KINDS:
            members[family] = members.get(family, 0) + 1
    return listed


def _family(item: Mapping) -> str:
    """The concept an attribute, identifier or table belongs to; anything else is its own."""
    return item.get("family") or item["id"]


def _score(item, fields, query: set, weight: Mapping, phrase: str) -> tuple[float, bool, list[str]]:
    """``(score, whether a name-like or id field matched, fields matched)``."""
    best: dict[str, float] = {}
    named = False
    matched = []
    for label, base in _FIELDS.items():
        hit_here = False
        for index, tokens in enumerate(fields.get(label) or []):
            common = tokens & query
            if not common:
                continue
            hit_here = True
            named = named or label in _NAMING
            factor = base
            if label in _NAME_LIKE:
                factor *= 0.5 + 0.5 * len(common) / len(tokens)
                value = _fold(item["fields"][label][index])
                if value and value in phrase:
                    factor *= 1.5  # the text spells this name out whole
            for token in common:
                best[token] = max(best.get(token, 0.0), factor * weight.get(token, 0.0))
        if hit_here:
            matched.append(label)
    return sum(best.values()), named, matched


def _fold(text) -> str:
    return unicodedata.normalize("NFKC", str(text or "")).casefold().strip()


def _tokens(text) -> set[str]:
    folded = _fold(text)
    tokens = set(_WORD.findall(folded))
    for run in _CJK.findall(folded):
        if len(run) == 1:
            tokens.add(run)
        tokens.update(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


def _query_tokens(text) -> set[str]:
    """The text's tokens without the scaffolding of a question (see ``_SCAFFOLDING``)."""
    return {
        token for token in _tokens(text)
        if token not in _SCAFFOLDING_WORDS
        and not set(token) & _PARTICLES
        and not set(token) <= _SCAFFOLDING
    }


def _one_line(text) -> str:
    line = next((part.strip() for part in str(text or "").splitlines() if part.strip()), "")
    return line if len(line) <= _SUMMARY_LENGTH else line[: _SUMMARY_LENGTH - 1] + "…"


# -------------------------------------------------------------------- items


def _items(view: CatalogView, semantics: Mapping) -> list[dict]:
    terms: dict[str, list[str]] = {}
    for term in view.terms:
        terms.setdefault(term.get("refers_to"), []).append(term.get("term"))
    documents = {catalog_table_name(name).lower(): doc for name, doc in semantics.items()}
    items = []
    for concept in view.concepts.values():
        tables = [rep["table"] for rep in view.representations_of(concept["id"])]
        items.append(_item(
            "concept", concept, terms,
            synonym=concept.get("synonyms"),
            definition=[concept.get("definition")],
            where="、".join(tables) or "没有自己的表",
        ))
        for attribute in concept.get("attributes") or []:
            columns = [
                f"{rep['table']}.{binding['column']}"
                for rep, binding in view.bindings_of(attribute["id"])
            ]
            place = f"{concept['name']}（{concept['id']}）"
            items.append(_item(
                "attribute", attribute, terms,
                definition=[attribute.get("definition")],
                column=[column.rsplit(".", 1)[-1] for column in columns],
                where="；".join([place] + (["、".join(columns)] if columns else [])),
                family=concept["id"],
            ))
    for metric in view.metrics:
        on = metric.get("on")
        items.append(_item(
            "metric", metric, terms,
            definition=[metric.get("definition"), metric.get("filter")],
            where=f"{view.name(on)}（{on}）" if on else None,
        ))
    for identifier in view.identifiers.values():
        owner = identifier.get("identifies")
        items.append(_item(
            "identifier", identifier, terms,
            column=[s.get("column") for s in identifier.get("spellings") or []],
            definition=[identifier.get("notes")],
            where=f"{view.name(owner)}（{owner}）" if owner else None,
            family=owner,
        ))
    for code_set in view.code_sets.values():
        meanings = [str(v.get("meaning") or "") for v in code_set.get("values") or []]
        items.append(_item(
            "code_set", code_set, terms, values=meanings, summary="、".join(meanings[:6]),
        ))
    for table, rep in sorted(view.representations.items()):
        document = documents.get(table.lower()) or {}
        summary = document.get("summary") or {}
        comment = view.rep_evidence(table).get("table_comment")
        concept_id = rep["concept"]
        items.append({
            "kind": "table",
            "id": table,
            "name": table,
            "summary": summary.get("what") or comment or "",
            "where": f"{view.name(concept_id)}（{concept_id}）",
            "family": concept_id,
            "fields": _clean({
                "id": [table],
                "comment": [comment],
                "concept": [view.name(concept_id)],
                "semantics": [summary.get("what"), *(summary.get("good_for") or [])],
            }),
        })
    return items


def _item(
    kind: str, obj: Mapping, terms: Mapping, *, where=None, summary=None, family=None, **fields
) -> dict:
    object_id = obj["id"]
    return {
        "kind": kind,
        "id": object_id,
        "name": obj.get("name") or object_id,
        "summary": summary if summary is not None else (obj.get("definition") or ""),
        "where": where,
        "family": family,
        "fields": _clean({
            "name": [obj.get("name")],
            "term": terms.get(object_id),
            "id": [object_id.split(":", 1)[-1]],
            **fields,
        }),
    }


def _clean(fields: Mapping) -> dict:
    return {
        label: [str(value) for value in values if value]
        for label, values in fields.items()
        if values and any(values)
    }


# --------------------------------------------------------------------- text


def render_search_text(result: Mapping) -> str:
    """One line a hit (kind, name, id, summary), and one line saying where it lives."""
    if not result["hits"]:
        return f"没有找到与「{result['query']['text']}」相近的目录对象。\n"
    lines = []
    for number, hit in enumerate(result["hits"], 1):
        summary = f" — {hit['summary']}" if hit["summary"] else ""
        name = "" if hit["name"] == hit["id"] else f"{hit['name']} "
        lines.append(f"{number}. [{KIND_TEXT[hit['kind']]}] {name}{hit['id']}{summary}")
        if hit.get("where"):
            lines.append(f"   在：{hit['where']}")
    return "\n".join(lines) + "\n"
