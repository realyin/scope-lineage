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
the text covers whole for more than a name it only touches. Scores order the list; they
mean nothing across two searches.

It ranks and never decides: a hit is a candidate, and nothing here rewrites the catalog.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Optional

from .catalog_view import CatalogView, catalog_table_name

__all__ = ["SEARCH_KINDS", "render_search_text", "search_catalog"]

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
    query = _tokens(text)
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
        score, matched = _score(item, fields, query, weight, phrase)
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
            hits.append(hit)
    hits.sort(key=lambda hit: (-hit["score"], SEARCH_KINDS.index(hit["kind"]), hit["id"]))
    result["hits"] = hits[: max(limit, 0)]
    return result


def _score(item, fields, query: set, weight: Mapping, phrase: str) -> tuple[float, list[str]]:
    best: dict[str, float] = {}
    matched = []
    for label, base in _FIELDS.items():
        hit_here = False
        for index, tokens in enumerate(fields.get(label) or []):
            common = tokens & query
            if not common:
                continue
            hit_here = True
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
    return sum(best.values()), matched


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
            "fields": _clean({
                "id": [table],
                "comment": [comment],
                "concept": [view.name(concept_id)],
                "semantics": [summary.get("what"), *(summary.get("good_for") or [])],
            }),
        })
    return items


def _item(kind: str, obj: Mapping, terms: Mapping, *, where=None, summary=None, **fields) -> dict:
    object_id = obj["id"]
    return {
        "kind": kind,
        "id": object_id,
        "name": obj.get("name") or object_id,
        "summary": summary if summary is not None else (obj.get("definition") or ""),
        "where": where,
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
