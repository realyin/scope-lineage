"""What a person browsing a built catalog sees, one view at a time.

``catalog render`` writes a whole catalog as pages, and ``catalog query`` / ``context``
answer one name. A browser page over a large catalog needs neither the
whole document nor one name: it needs the part one view shows, small enough to send on a
click. These functions give those parts from the built ``ontology-json/3`` document (and,
where named, the ``{db.table: table-semantics document}`` mapping and a pending report);
nothing is read from disk here and nothing is written.

- ``browse_index`` -- the catalog's name and counts and each domain with how many concepts
  and tables it holds: the first screen; and the summary ``index.md`` opens with under
  「用之前先看」 (``catalog_pages.use_first_rows``: the same rows and numbers, the rows that
  need the table-semantics documents only when they are given).
- ``browse_list`` -- one page of concepts, tables or metrics, filtered by domain, concept or
  a piece of text, with the total, so a long list is paged where the data is. A
  concept row carries what the index page's domain table shows (kind, definition, how many
  tables, status); a table row what the concept page's table inventory leads with, and,
  given the table-semantics documents, the index's 「按表看」 row for it
  (``catalog_index_tables``). Tables come in name order unless ``sort`` names one of
  those columns; the sort is over the whole filtered list, before it is paged.
- ``table_units`` -- the unit of each of one table's measure columns, with the mark the
  context pack prints when the material does not give it.
- ``concept_neighbourhood`` -- a concept, the concepts one relation away, and every
  relation between those nodes, each with its join conditions: the JOINs the corpus showed
  (``joins`` / ``source_joins``, as the concept page cites them) and the foreign-key columns
  the catalog binds for it (``keys``, the columns ``catalog context`` lists as a table's
  joins). A role is drawn to the concept that plays it. Capped, saying how many it left out.
- ``table_semantics`` -- one table's semantics document, whole, matched the way the
  catalog matches table names.
- ``questions_board`` -- every open question registered for the catalog: those the
  table-semantics documents record, and the pending file's items (``pending_report``, its
  grouping and its catalog check unchanged), each placed at its tables' concepts and marked
  when the catalog does not carry it; filtered and paged. An answered question carries its
  answer, and a browsing page's answers and notes are marked as the context pack marks
  them (``catalog_context.mark_question``).

The catalog view, the summary rows and the by-table rows are computed once for the
document and semantics objects a caller holds, and kept for the next call with the same
objects (``_prepared``): a server answers a page of a large catalog without recounting it.
The documents are read, never changed; a caller that changes one passes a new object.

None of these is a ``scope-lineage`` command: they serve a browsing page
(``scope-lineage-service``), and the command line keeps ``query``, ``context`` and
``render`` for the same facts. A request these functions cannot answer raises
``ValueError`` with the sentence to show.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping
from typing import Optional

from .catalog_context import SET_ASIDE, mark_question, page_index, unit_mark, unit_text
from .catalog_index_tables import by_table_columns, coverage_note, figure_cells, table_figures
from .catalog_overview import table_about
from .catalog_pages import ANSWERING_USES, STRUCTURE_ONLY, USE_FIRST_HEADING, use_first_rows
from .catalog_query import find_concepts
from .catalog_units import material_documents
from .catalog_view import CatalogView, catalog_table_name, realises

__all__ = [
    "BOARD_PAGE_STATUSES",
    "BOARD_SOURCES",
    "BOARD_STATUSES",
    "DEFAULT_LIMIT",
    "LIST_KINDS",
    "MAX_LIMIT",
    "NEIGHBOURHOOD_LIMIT",
    "TABLE_SORTS",
    "browse_index",
    "browse_list",
    "concept_neighbourhood",
    "questions_board",
    "table_semantics",
    "table_units",
]

INDEX_FORMAT = "catalog-browse-index/1"
LIST_FORMAT = "catalog-browse-list/1"
NEIGHBOURHOOD_FORMAT = "catalog-neighbourhood/1"
SEMANTICS_FORMAT = "catalog-table-semantics/1"
BOARD_FORMAT = "catalog-questions/1"
UNITS_FORMAT = "catalog-table-units/1"

LIST_KINDS = ("concepts", "tables", "metrics")
BOARD_STATUSES = ("open", "answered", "all")
# the statuses a board takes when it is given a browsing page's states (``page_states``)
BOARD_PAGE_STATUSES = ("open", "answered", SET_ASIDE, "all")
BOARD_SOURCES = ("semantics", "pending")
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
NEIGHBOURHOOD_LIMIT = 40
NEIGHBOURHOOD_MAX = 200
# what ``sort`` may name for tables (``-`` before it: largest first): the table's name, or
# one by-table count (``catalog_index_tables.table_figures``)
TABLE_SORTS = ("table", "measures", "unit_unsupported", "unmapped", "watch", "watch_conflicts")
# join conditions shown on one edge, and target columns on one key
KEYS_SHOWN = 10


def _ref(view: CatalogView, object_id: str) -> dict:
    return {"id": object_id, "name": view.name(object_id)}


def _fold(text) -> str:
    return str(text or "").strip().casefold()


def check_page(offset: int, limit: int, most: int = MAX_LIMIT) -> None:
    """Refuse an offset below 0 or a limit outside 1..``most``."""
    if offset < 0:
        raise ValueError("offset takes an integer >= 0")
    if not 1 <= limit <= most:
        raise ValueError(f"limit takes an integer from 1 to {most}")


def _page(items: list, offset: int, limit: int) -> dict:
    return {"total": len(items), "offset": offset, "limit": limit,
            "items": items[offset:offset + limit]}


class _Prepared:
    """What the browse answers count over the whole catalog, for one (document,
    semantics) pair: the view at once, the summary and the by-table rows when first asked."""

    def __init__(self, document: Mapping, semantics: Optional[Mapping[str, Mapping]]) -> None:
        self.document, self.semantics = document, semantics
        self.view = CatalogView(document)
        self.docs = None if semantics is None else material_documents(semantics)
        self._lock = threading.Lock()
        self._use_first: Optional[list[tuple[str, str]]] = None
        self._figures: Optional[dict[str, dict]] = None

    def use_first(self) -> list[tuple[str, str]]:
        with self._lock:
            if self._use_first is None:
                self._use_first = use_first_rows(self.view, self.docs)
            return self._use_first

    def figures(self, docs: Mapping[str, Mapping]) -> dict[str, dict]:
        """``table -> its by-table row and cells`` (``docs`` is ``self.docs``)."""
        with self._lock:
            if self._figures is None:
                self._figures = {
                    row["table"]: {**row, "cells": figure_cells(row)}
                    for row in table_figures(self.view, docs)
                }
            return self._figures


_PREPARED: list[_Prepared] = []
_PREPARED_KEPT = 2  # a server holds one catalog; one more covers the switch to a rebuilt one
_PREPARED_LOCK = threading.Lock()


def _prepared(document: Mapping, semantics: Optional[Mapping[str, Mapping]] = None) -> _Prepared:
    """The counts for these very objects, made once and kept for the next call with them."""
    with _PREPARED_LOCK:
        for found in _PREPARED:
            if found.document is document and found.semantics is semantics:
                return found
        made = _Prepared(document, semantics)
        _PREPARED.insert(0, made)
        del _PREPARED[_PREPARED_KEPT:]
        return made


# ------------------------------------------------------------------ index


def browse_index(document: Mapping, semantics: Optional[Mapping[str, Mapping]] = None) -> dict:
    """``{doc_format, catalog, counts, evidence, domains, use_first}``: each domain with how
    many concepts, tables and metrics it holds, in id order, and the summary ``index.md``
    leads with under 「用之前先看」 -- its two sentences and its rows, with the rows counted
    from ``semantics`` (``{db.table: table-semantics document}``) only when it is given."""
    prepared = _prepared(document, semantics)
    view = prepared.view
    concepts: dict[str, int] = {}
    for concept in view.concepts.values():
        concepts[concept["domain"]] = concepts.get(concept["domain"], 0) + 1
    tables: dict[str, int] = {}
    for rep in view.representations.values():
        domain = (view.concepts.get(rep["concept"]) or {}).get("domain")
        tables[domain] = tables.get(domain, 0) + 1
    metrics: dict[str, int] = {}
    for metric in view.metrics:
        domain = (view.concepts.get(metric.get("on") or "") or {}).get("domain")
        metrics[domain] = metrics.get(domain, 0) + 1
    catalog = document.get("catalog") or {}
    return {
        "doc_format": INDEX_FORMAT,
        "catalog": {"name": catalog.get("name"), "description": catalog.get("description")},
        "counts": document.get("counts"),
        "evidence": sorted(view.evidence_inputs),
        "domains": [
            {
                "id": domain_id,
                "name": view.domains[domain_id].get("name") or domain_id,
                "description": view.domains[domain_id].get("description"),
                "concepts": concepts.get(domain_id, 0),
                "tables": tables.get(domain_id, 0),
                "metrics": metrics.get(domain_id, 0),
            }
            for domain_id in sorted(view.domains)
        ],
        "use_first": {
            "heading": USE_FIRST_HEADING.removeprefix("## "),
            "notes": [STRUCTURE_ONLY, ANSWERING_USES],
            "rows": [{"name": name, "value": value} for name, value in prepared.use_first()],
        },
    }


# ------------------------------------------------------------------ lists


def browse_list(
    document: Mapping,
    kind: str,
    *,
    semantics: Optional[Mapping[str, Mapping]] = None,
    domain: Optional[str] = None,
    concept: Optional[str] = None,
    text: Optional[str] = None,
    sort: Optional[str] = None,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """One page of ``kind`` (``concepts``, ``tables``, ``metrics``) and the total.

    ``domain`` is a domain id; ``concept`` a concept id, name, synonym or term (as
    ``catalog query concept`` finds it) and does not apply to ``concepts``; ``text`` is a
    piece of the id, name or synonym (of a table: its name), ignoring case. Concepts and
    metrics come in id order, tables in name order.

    Given ``semantics`` (``{db.table: table-semantics document}``), each table row carries
    ``by_table``, its row of the index's 「按表看」 (the numbers, None where the table has
    no document, and ``cells`` as the index prints them), and the answer's ``by_table``
    names the columns and says how many tables the documents cover. ``sort`` orders the
    tables by one of ``TABLE_SORTS`` (``-`` first: largest first; a table whose value is
    unknown last either way; equal values by name), over every table the filters keep,
    before the page is cut."""
    if kind not in LIST_KINDS:
        raise ValueError(f"kind must be one of {', '.join(LIST_KINDS)}, not {kind!r}")
    _check_sort(kind, sort, semantics)
    check_page(offset, limit)
    prepared = _prepared(document, semantics)
    view = prepared.view
    wanted = None
    if concept is not None:
        if kind == "concepts":
            raise ValueError("concept filters tables and metrics, not concepts")
        wanted = {found["id"] for found, _ in find_concepts(view, concept)}
    in_domain = None
    if domain is not None:
        in_domain = {c["id"] for c in view.concepts.values() if c["domain"] == domain}
    needle = _fold(text) if text else None
    builders = {"concepts": _concept_rows, "tables": _table_rows, "metrics": _metric_rows}
    items = builders[kind](view, wanted, in_domain, needle)
    query = {"kind": kind, "domain": domain, "concept": concept, "text": text, "sort": sort}
    answer: dict = {"doc_format": LIST_FORMAT, "query": query}
    if kind == "tables" and prepared.docs is not None:
        figures = prepared.figures(prepared.docs)
        for item in items:
            row = figures[item["table"]]
            item["by_table"] = {k: v for k, v in row.items() if k not in ("table", "concept")}
        answer["by_table"] = {
            "columns": [{"key": key, "label": label} for key, label in by_table_columns(view)],
            "covered": sum(1 for row in figures.values() if row["covered"]),
            "tables": len(figures),
            "note": coverage_note(view, prepared.docs),
        }
    if sort:
        items = _sorted_tables(items, sort)
    return {**answer, **_page(items, offset, limit)}


def _check_sort(kind: str, sort: Optional[str], semantics) -> None:
    if sort is None:
        return
    key = sort[1:] if sort.startswith("-") else sort
    if key not in TABLE_SORTS:
        raise ValueError(
            f"sort must be one of {', '.join(TABLE_SORTS)} (with - before it: largest "
            f"first), not {sort!r}"
        )
    if kind != "tables":
        raise ValueError("sort orders tables only")
    if key != "table" and semantics is None:
        raise ValueError(
            f"sort by {key} needs the table-semantics documents (the server's --semantics)"
        )


def _sorted_tables(items: list[dict], sort: str) -> list[dict]:
    """Table rows (in name order) by their name or one by-table number; unknown values
    last whichever way, equal values in name order (the sort is stable)."""
    descending = sort.startswith("-")
    key = sort[1:] if descending else sort
    if key == "table":
        return items[::-1] if descending else items
    known = [item for item in items if item["by_table"][key] is not None]
    known.sort(key=lambda item: item["by_table"][key], reverse=descending)
    return known + [item for item in items if item["by_table"][key] is None]


def _contains(needle: Optional[str], values: Iterable) -> bool:
    return needle is None or any(needle in _fold(value) for value in values)


def _concept_rows(view: CatalogView, wanted, in_domain, needle) -> list[dict]:
    tables: dict[str, int] = {}
    for rep in view.representations.values():
        tables[rep["concept"]] = tables.get(rep["concept"], 0) + 1
    return [
        {
            "id": concept["id"],
            "name": concept["name"],
            "kind": concept["kind"],
            "domain": _ref(view, concept["domain"]),
            "definition": concept.get("definition"),
            "tables": tables.get(concept["id"], 0),
            "status": concept.get("status"),
            "source": concept.get("source"),
        }
        for concept in sorted(view.concepts.values(), key=lambda c: c["id"])
        if (in_domain is None or concept["id"] in in_domain)
        and _contains(needle, [concept["id"], concept["name"], *(concept.get("synonyms") or [])])
    ]


def _table_rows(view: CatalogView, wanted, in_domain, needle) -> list[dict]:
    rows = []
    for table in sorted(view.representations):
        rep = view.representations[table]
        if wanted is not None and rep["concept"] not in wanted:
            continue
        if in_domain is not None and rep["concept"] not in in_domain:
            continue
        if not _contains(needle, [table]):
            continue
        row = {
            "table": table,
            "concept": _ref(view, rep["concept"]),
            "kind": rep.get("kind"),
            "time": rep.get("time"),
            "table_status": rep.get("table_status"),
            "status": rep.get("status"),
            "columns": len(rep.get("bindings") or []),
        }
        about = table_about(view, rep)
        if about:
            row["about"] = about
        rows.append(row)
    return rows


def _metric_rows(view: CatalogView, wanted, in_domain, needle) -> list[dict]:
    rows = []
    for metric in sorted(view.metrics, key=lambda m: m["id"]):
        on = metric.get("on") or ""
        if wanted is not None and on not in wanted:
            continue
        if in_domain is not None and on not in in_domain:
            continue
        if not _contains(needle, [metric["id"], metric.get("name") or ""]):
            continue
        rows.append({
            "id": metric["id"],
            "name": metric.get("name") or metric["id"],
            "on": _ref(view, on) if on else None,
            "definition": metric.get("definition"),
            "aggregation": metric.get("aggregation"),
            "unit": metric.get("unit"),
            "status": metric.get("status"),
        })
    return rows


# ------------------------------------------------------------- neighbourhood


def concept_neighbourhood(
    document: Mapping, term: str, *, limit: int = NEIGHBOURHOOD_LIMIT
) -> dict:
    """``{doc_format, query, centre, nodes, edges, truncated, others}`` for the concept a
    term names (id, the id without ``concept:``, name, synonym or term).

    The nodes are the concept and at most ``limit`` concepts one relation (or one role)
    away, in the order the document lists those relations; ``truncated`` counts the ones
    left out. Every relation between two kept nodes is an edge, so two neighbours related
    to each other are drawn so. ``centre`` is None when no concept matches; ``others`` lists
    further concepts the same term names."""
    check_page(0, limit, NEIGHBOURHOOD_MAX)
    view = CatalogView(document)
    found = find_concepts(view, term) or find_concepts(view, f"concept:{term}")
    query = {"concept": term, "limit": limit}
    if not found:
        return {"doc_format": NEIGHBOURHOOD_FORMAT, "query": query, "centre": None,
                "nodes": [], "edges": [], "truncated": 0, "others": []}
    centre = found[0][0]["id"]
    links = _links(view)
    neighbours: list[str] = []
    for source, target, _ in links:
        if centre in (source, target):
            other = target if source == centre else source
            if other != centre and other not in neighbours:
                neighbours.append(other)
    kept = [centre, *neighbours[:limit]]
    keep = set(kept)
    tables: dict[str, int] = {}
    for rep in view.representations.values():
        tables[rep["concept"]] = tables.get(rep["concept"], 0) + 1
    nodes = [_node(view, concept_id, concept_id == centre, tables) for concept_id in kept]
    edges = [
        _edge(view, edge)
        for source, target, edge in links
        if source in keep and target in keep
    ]
    return {
        "doc_format": NEIGHBOURHOOD_FORMAT,
        "query": query,
        "centre": centre,
        "nodes": nodes,
        "edges": edges,
        "truncated": max(0, len(neighbours) - limit),
        "others": [_ref(view, concept["id"]) for concept, _ in found[1:]],
    }


def _links(view: CatalogView) -> list[tuple[str, str, dict]]:
    """``(from, to, relation or role)``: every relation, then every role to its player."""
    found = [
        (relation["from"], relation["to"], relation)
        for relation in view.relations.values()
        if relation["from"] in view.concepts and relation["to"] in view.concepts
    ]
    found += [
        (concept["id"], concept["player"], {"kind": "role", "role": concept})
        for concept in view.concepts.values()
        if concept.get("player") in view.concepts
    ]
    return found


def _node(view: CatalogView, concept_id: str, centre: bool, tables: Mapping) -> dict:
    concept = view.concepts[concept_id]
    return {
        "id": concept_id,
        "name": concept["name"],
        "kind": concept["kind"],
        "domain": _ref(view, concept["domain"]),
        "tables": tables.get(concept_id, 0),
        "centre": centre,
    }


def _edge(view: CatalogView, edge: dict) -> dict:
    if edge["kind"] == "role":
        role = edge["role"]
        return {
            "kind": "role", "from": role["id"], "to": role["player"],
            "name": role.get("condition") or "", "status": role.get("status"),
            "joins": None, "source_joins": None, "keys": [], "keys_total": 0,
        }
    keys, total = _keys(view, edge)
    answer = {
        "id": edge["id"],
        "kind": edge["kind"],
        "name": edge.get("name") or "",
        "from": edge["from"],
        "to": edge["to"],
        "cardinality": edge.get("cardinality"),
        "status": edge.get("status"),
        "joins": _seen(view.relation_joins(edge["id"])),
        "source_joins": _seen(view.relation_source_joins(edge["id"])),
        "keys": keys,
        "keys_total": total,
    }
    if edge.get("inverse_name"):
        answer["inverse_name"] = edge["inverse_name"]
    return answer


def _seen(joins: Optional[Mapping]) -> Optional[dict]:
    """``{count, on}`` of the JOINs the evidence recorded, or None when it recorded none."""
    if joins is None:
        return None
    return {
        "count": joins.get("count", 0),
        "on": [sample["on"] for sample in joins.get("samples") or [] if sample.get("on")],
    }


def _join_keys(view: CatalogView, concept_id: str) -> set[str]:
    """The identifiers a foreign key to the concept holds: its own, or a role's player's."""
    keys = {identifier["id"] for identifier in view.identifiers_of(concept_id)}
    player = (view.concepts.get(concept_id) or {}).get("player")
    if not keys and player:
        keys = {identifier["id"] for identifier in view.identifiers_of(player)}
    return keys


def _keys(view: CatalogView, relation: Mapping) -> tuple[list[dict], int]:
    """``(the first KEYS_SHOWN, how many)`` foreign-key columns realising the relation: a
    table of one end holding the other end's identifier, each with the columns where that
    identifier is a table's key."""
    found: list[tuple[str, dict, str, list]] = []
    seen: set[str] = set()
    ends = (relation["from"], relation["to"])
    for holder, target in (ends, ends[::-1]):
        for identifier in sorted(_join_keys(view, target)):
            bindings = view.bindings_of(identifier)
            keyed = sorted(
                (r["table"], b["column"]) for r, b in bindings if b["to"] == "identifier"
            )
            for rep, binding in bindings:
                # a column naming another record of its own concept realises only a
                # relation from the concept to itself, and every other column only others
                if (
                    binding["to"] != "foreign_identifier"
                    or rep["concept"] != holder
                    or not realises(binding, relation["id"])
                    or bool(binding.get("self_reference")) != (holder == target)
                ):
                    continue
                column = f"{rep['table']}.{binding['column']}"
                if column not in seen:
                    seen.add(column)
                    found.append((column, binding, identifier, keyed))
        if holder == target:
            break
    return [_key(view, *item) for item in found[:KEYS_SHOWN]], len(found)


def _key(view: CatalogView, column: str, binding: Mapping, identifier: str, keyed: list) -> dict:
    """As ``catalog context`` lists a table's joins: the key columns of other tables, and
    of its own table too for a column naming another record of it."""
    table = column.rpartition(".")[0]
    to = [
        f"{other}.{key}" for other, key in keyed
        if other != table or binding.get("self_reference")
    ]
    return {"column": column, "identifier": _ref(view, identifier), "to": to[:KEYS_SHOWN],
            "to_total": len(to)}


# ------------------------------------------------------------------ semantics


def _documents(semantics: Optional[Mapping[str, Mapping]]) -> dict[str, Mapping]:
    return {catalog_table_name(name).lower(): doc for name, doc in (semantics or {}).items()}


def table_semantics(
    document: Mapping, semantics: Optional[Mapping[str, Mapping]], table: str
) -> dict:
    """``{doc_format, query, table, in_catalog, document}``: the table's semantics document
    whole (None when there is none), matched ignoring case and a catalog prefix."""
    view = CatalogView(document)
    key = catalog_table_name(str(table).strip()).lower()
    rep = view.representation(table)
    found = _documents(semantics).get(key)
    name = rep["table"] if rep else (found.get("table") if found else None) or key
    return {
        "doc_format": SEMANTICS_FORMAT,
        "query": {"table": table},
        "table": name,
        "in_catalog": rep is not None,
        "document": dict(found) if found else None,
    }


def table_units(
    document: Mapping, semantics: Optional[Mapping[str, Mapping]], table: str
) -> dict:
    """``{doc_format, query, table, in_catalog, checked, columns}``: each column of the
    table bound to a measure attribute or to an attribute with a unit, in binding order,
    with the attribute's ``unit``, the ``material_unit`` mark ``catalog context`` gives it
    (``catalog_context.unit_mark``; only when ``semantics`` is given, ``checked``) and
    ``text``, what the context pack's ``单位：`` line says (None when it prints none)."""
    prepared = _prepared(document, semantics)
    view = prepared.view
    rep = view.representation(table)
    columns = []
    for binding in (rep or {}).get("bindings") or []:
        ref = binding.get("ref")
        if ref not in view.attributes:
            continue
        attribute = view.attributes[ref][0]
        if attribute.get("category") != "measure" and not attribute.get("unit"):
            continue
        item: dict = {"column": binding["column"], "ref": _ref(view, ref)}
        if attribute.get("unit"):
            item["unit"] = attribute["unit"]
        mark = unit_mark(view, attribute, attribute.get("unit"), prepared.docs)
        if mark is not None:
            item["material_unit"] = mark
        item["text"] = unit_text(item)
        columns.append(item)
    return {
        "doc_format": UNITS_FORMAT,
        "query": {"table": table},
        "table": rep["table"] if rep else catalog_table_name(str(table).strip()),
        "in_catalog": rep is not None,
        "checked": semantics is not None,
        "columns": columns,
    }


# ------------------------------------------------------------------ questions


def questions_board(
    document: Mapping,
    semantics: Optional[Mapping[str, Mapping]],
    pending: Optional[Mapping] = None,
    *,
    table: Optional[str] = None,
    concept: Optional[str] = None,
    status: str = "open",
    source: Optional[str] = None,
    text: Optional[str] = None,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
    page_states: Optional[Mapping] = None,
) -> dict:
    """The registered questions, filtered and paged.

    ``pending`` is a ``pending_report`` built with this document and these semantics (or
    None: no pending file). A semantics question is ``in_catalog`` when the catalog has
    its table, and lists the columns it is ``about`` with whether the catalog binds each; a
    pending item is ``in_catalog`` when ``pending_report`` found catalog objects named by
    its text (``catalog_objects``). Every pending item is open. ``table`` is a table name
    (case and catalog prefix ignored); ``concept`` a concept id, name, synonym or term;
    ``text`` a piece of the question, the missing definition or the table name. ``concepts``
    counts the items per concept under ``status``, ``source`` and ``text`` alone, so a
    filter list offers every choice.

    An answered semantics question carries ``answer``, ``answered_by`` and
    ``answered_on`` (those its document has). ``page_states`` is a browsing page's
    ``{(table, question id): state}`` (``catalog_context.page_index``): an answer the page
    overlaid gains ``written: false``, a noted question ``page``, and a question a note sets
    aside has the status ``set_aside``. Only with ``page_states`` (even an empty one) does
    ``status`` take ``set_aside`` (``BOARD_PAGE_STATUSES``); ``all`` includes those items, and
    ``counts`` and ``concepts`` follow the status filter as they do for the others."""
    statuses = BOARD_STATUSES if page_states is None else BOARD_PAGE_STATUSES
    if status not in statuses:
        raise ValueError(f"status must be one of {', '.join(statuses)}, not {status!r}")
    if source is not None and source not in BOARD_SOURCES:
        raise ValueError(f"source must be one of {', '.join(BOARD_SOURCES)}, not {source!r}")
    check_page(offset, limit)
    states = page_index(page_states)
    view = CatalogView(document)
    items = []
    if source in (None, "pending") and pending is not None:
        items += [_pending_item(view, item) for item in pending.get("items") or []]
    if source in (None, "semantics"):
        items += _semantics_items(view, semantics, states)
    if status != "all":
        items = [item for item in items if item["status"] == status]
    needle = _fold(text) if text else None
    if needle is not None:
        items = [item for item in items if _contains(needle, _item_texts(item))]
    facets = _facets(items)
    if table is not None:
        wanted_table = catalog_table_name(str(table).strip()).lower()
        items = [item for item in items if wanted_table in _item_tables(item)]
    if concept is not None:
        wanted = {found["id"] for found, _ in find_concepts(view, concept)}
        items = [item for item in items if wanted & {c["id"] for c in item["concepts"]}]
    query = {"table": table, "concept": concept, "status": status, "source": source,
             "text": text}
    return {
        "doc_format": BOARD_FORMAT,
        "query": query,
        "checked": {"semantics": semantics is not None, "pending": pending is not None},
        "counts": {
            "semantics": sum(1 for item in items if item["source"] == "semantics"),
            "pending": sum(1 for item in items if item["source"] == "pending"),
            "not_in_catalog": sum(1 for item in items if not item["in_catalog"]),
        },
        "concepts": facets,
        **_page(items, offset, limit),
        "problems": list((pending or {}).get("problems") or []),
    }


def _semantics_items(view: CatalogView, semantics, states: Optional[Mapping] = None) -> list[dict]:
    found = []
    states = states or {}
    for key, document in sorted(_documents(semantics).items()):
        rep = view.representation(key)
        bound = {b["column"].casefold() for b in (rep or {}).get("bindings") or []}
        table = rep["table"] if rep else str(document.get("table") or key)
        concept = _ref(view, rep["concept"]) if rep else None
        for question in (document.get("summary") or {}).get("questions") or []:
            about = [str(ref) for ref in question.get("about") or []]
            columns = [
                ref.split(":", 1)[1] for ref in about if ref.casefold().startswith("column:")
            ]
            item = {
                "source": "semantics",
                "table": table,
                "id": question.get("id"),
                "text": question.get("text"),
                "status": question.get("status"),
                "about": about,
                "columns": [{"column": c, "bound": c.casefold() in bound} for c in columns],
                "concept": concept,
                "concepts": [concept] if concept else [],
                "in_catalog": rep is not None,
            }
            found.append(mark_question(item, question, states.get((key, str(question.get("id"))))))
    return found


def _pending_item(view: CatalogView, item: Mapping) -> dict:
    objects = list(item.get("in_catalog") or [])
    concepts: list[dict] = []
    for table in item.get("tables") or []:
        rep = view.representation(table)
        if rep and all(c["id"] != rep["concept"] for c in concepts):
            concepts.append(_ref(view, rep["concept"]))
    for found in objects:
        if found.get("kind") == "concept" and all(c["id"] != found["id"] for c in concepts):
            concepts.append(_ref(view, found["id"]))
    answer = {key: value for key, value in item.items() if key != "in_catalog"}
    answer.update(
        source="pending", status="open", concepts=concepts,
        catalog_objects=objects, in_catalog=bool(objects),
    )
    return answer


def _item_tables(item: Mapping) -> set[str]:
    names = [item["table"]] if item["source"] == "semantics" else item.get("tables") or []
    return {catalog_table_name(name).lower() for name in names}


def _item_texts(item: Mapping) -> list:
    if item["source"] == "semantics":
        return [item.get("text"), item.get("table")]
    return [item.get("missing"), *(item.get("questions") or []), *(item.get("tables") or []),
            *(item.get("terms") or [])]


def _facets(items: list[dict]) -> list[dict]:
    counts: dict[str, dict] = {}
    for item in items:
        for concept in item["concepts"]:
            entry = counts.setdefault(concept["id"], {**concept, "count": 0})
            entry["count"] += 1
    return sorted(counts.values(), key=lambda entry: (-entry["count"], entry["id"]))
