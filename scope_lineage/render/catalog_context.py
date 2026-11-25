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
readers ask of a table. Under a table each constraint on its concept says which tables it
comes from (``catalog_scopes.constraint_tables``) and how they relate to this table in the
catalog's lineage evidence (``_table_constraints``), since a condition from an upstream, a
downstream or an unrelated table means different things here.

Two options shorten a table's pack for an agent that asks many questions. ``brief`` keeps
every item that decides how to query -- the catalog facts, what a row is, how to read it,
scope, not-for, watch items, open questions, the text of the cited rules -- and shortens the
parts that are long and do not: each column is named with its category but not described,
a cited rule loses its SQL, a downstream reader is named by the table it writes (its
task only when it writes none), and a join column's sample JOINs between two tables both
outside the catalog are counted rather than listed. ``focus`` narrows a table's watch items, open questions and
cited rules to the requested columns of that table: an item names a column by a
``column:<name>`` reference (``refs`` of a watch item, ``about`` of a question), and one that
names no column is about the whole table and always stays. A rule carries no column
reference of its own, so it stays while a scope line or a kept item cites it. The pack says
how many items ``focus`` left out.

Both inputs are plain dicts: the built ``ontology-json/3`` document and
``{db.table: table-semantics document}``. Nothing is read from disk here. A table with no
semantics document says so (``{"present": false}``) rather than carrying empty fields, so
a reader can tell "nothing to watch" from "nobody wrote it down".

A measure's unit, on a column's binding and on a metric over that measure, is compared
with the table semantics when they are given (``unit_mark``, on the rule
``catalog_units.unit_support`` keeps for the index page too): a unit none of the
attribute's bound columns has in the material is marked as not given by it and
unconfirmed, and a measure with no unit says whether the material gives one
(``material_unit``). Without semantics nothing is compared and the pack is unchanged.

An answered question carries its answer, who gave it and when (``answer``,
``answered_by``, ``answered_on``, those the document has), under a table and under a named
column, and the text gives the answer on the line after the question. A browsing page may
hold answers and notes the documents do not have yet; ``page_states`` takes them, keyed by
``(table, question id)`` (``page_index``), and the pack marks them (``mark_question``):
``written: false`` on an answer overlaid from the page, ``page`` on a question with a note,
and ``status: "set_aside"`` on one the note sets aside (it stays listed, and the text puts it
apart from the open ones). A page may also answer with a structured value -- the row's
grain, a column's meaning, one code value -- overlaid on the documents; ``page_states`` then
also takes ``(table, slot)`` keys (``row``, ``column:<c>.meaning``,
``column:<c>.code_values:<value>``, each ``{"written": False}``), and the pack marks the row
``written: false`` and a column ``unwritten: ["meaning", "code_values:<value>", ...]``, the
text adding 「（页面填写，尚未写回）」 after the row, the column's line and its meaning and
code values. The documents gain no key. Without ``page_states`` (or with an empty one) the
pack is what it was.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Optional

from ..catalog.soft_checks import UNIT_LEFT_TO_OWNER
from ..observation_words import observed_input_text, observed_row_text, observed_values_text

from .catalog_gaps import conflict_text
from .catalog_joins import (
    PARTITION_BATCH,
    PARTITION_FULL,
    backed_pairs,
    grain_columns,
    partition_columns,
    partition_reading,
    period_columns,
    pin_window,
    time_groups,
    uncovered,
)
from .catalog_query import find_concepts, find_metrics
from .catalog_scopes import constraint_tables
from .catalog_units import SUPPORTED, UNJUDGED, material_documents, unit_support
from .catalog_view import CatalogView, catalog_table_name, realises

__all__ = [
    "CONTEXT_FORMAT",
    "PAGE_KINDS",
    "ROW_SLOT",
    "SET_ASIDE",
    "SET_ASIDE_KINDS",
    "context_pack",
    "mark_question",
    "page_index",
    "render_context_text",
    "unwritten_slots",
]

CONTEXT_FORMAT = "catalog-context/1"
# Keys of a semantics column kept in a column's full answer, in this order.
_COLUMN_KEYS = (
    "meaning", "category", "derivation", "branches", "code_values", "null_meaning", "watch",
    "observed_values",
)
_BINDING_KEYS = ("derivation", "time_role", "via", "code_map", "relation", "self_reference")
# A question's own keys a pack and the questions board carry once it is answered.
ANSWER_KEYS = ("answer", "answered_by", "answered_on")
# The notes a browsing page may leave on an open question (``page_states``), and the two of
# them that set the question aside rather than leave it open.
PAGE_KINDS = ("partial", "deferred", "redirect", "invalid", "not_applicable")
SET_ASIDE_KINDS = frozenset({"invalid", "not_applicable"})
SET_ASIDE = "set_aside"
_NOTE_KEYS = ("kind", "reason", "choice", "to", "by", "date")
_NOT_WRITTEN = {"written": False}
# A structured slot a browsing page answered (``page_index``): the row, a column's meaning,
# one of a column's code values.
ROW_SLOT = "row"
_SLOT = re.compile(r"row|column:(?P<column>[^.\s]+)\.(?:meaning|code_values:(?P<value>.+))", re.S)
UNWRITTEN_TEXT = "（页面填写，尚未写回）"


def context_pack(
    document: Mapping,
    semantics: Optional[Mapping[str, Mapping]],
    *,
    tables: Iterable[str] = (),
    columns: Iterable[str] = (),
    concepts: Iterable[str] = (),
    table_columns: Iterable[str] = (),
    brief: bool = False,
    focus: bool = False,
    page_states: Optional[Mapping] = None,
) -> dict:
    """The pack for the named tables, columns (``db.table.column``) and concepts.

    ``table_columns`` are columns of the requested tables named without the table (or
    with ``table.`` to pin one); ``_table_columns`` says which table each goes to, and
    ``query.columns`` lists them as ``db.table.column`` after ``columns``. A concept term
    may name a metric: its concept is packed (``_concept_term``). ``brief`` shortens each
    table's semantics as the module says; ``focus`` narrows each table that has requested
    columns to them. Neither changes a concept or a column. ``page_states`` marks the
    questions a browsing page answered or noted (``page_index``, ``mark_question``).
    """
    states = page_index(page_states)
    view = CatalogView(document)
    documents = material_documents(semantics)
    # what a measure's unit is compared with (``unit_mark``); None without semantics
    material = documents if semantics is not None else None
    tables = list(tables)
    expanded, unplaced = _table_columns(view, documents, tables, list(columns), table_columns)
    query: dict = {"tables": tables, "columns": expanded, "concepts": list(concepts)}
    if brief:
        query["brief"] = True
    if focus:
        query["focus"] = True
    pack: dict = {
        "doc_format": CONTEXT_FORMAT,
        "query": query,
        "concepts": [],
        "tables": [],
        "columns": [],
        "missing": [],
    }
    focused = _requested_columns(view, query["columns"]) if focus else {}
    for term in pack["query"]["concepts"]:
        _concept_term(view, term, pack, material)
    for term in pack["query"]["tables"]:
        rep = view.representation(term)
        if rep is None:
            pack["missing"].append({"kind": "table", "term": term})
            continue
        pack["tables"].append(_table(
            view, rep, documents.get(rep["table"].lower()),
            brief=brief, focus=focused.get(rep["table"].lower()), states=states,
        ))
    found = list({entry["table"]: entry for entry in pack["tables"]})
    if len(found) > 1:
        reps = [view.representation(table) for table in found]
        pack["links"] = [
            _link(view, a, b) for i, a in enumerate(reps) for b in reps[i + 1:]
        ]
    for term in pack["query"]["columns"]:
        answer = _column(view, term, documents, material, states)
        if answer is None:
            pack["missing"].append({"kind": "column", "term": term})
        else:
            pack["columns"].append(answer)
    pack["missing"] += unplaced
    return pack


def _concept_term(
    view: CatalogView, term: str, pack: dict, material: Optional[Mapping] = None
) -> None:
    """Add the concepts one ``--concept`` term names to the pack, or a ``missing`` entry.

    A concept is looked for first (by id, the id without ``concept:`` -- the page name --,
    name, synonym or term); only when none matches is the term read as a metric (id, id
    without ``metric:``, name or term), and the metric's concept is packed with that metric
    first and named in ``via_metric``."""
    found = find_concepts(view, term) or find_concepts(view, f"concept:{term}")
    if found:
        pack["concepts"].extend(
            _concept(view, concept, material=material) for concept, _ in found
        )
        return
    metrics = find_metrics(view, term) or find_metrics(view, f"metric:{term}")
    if not metrics:
        pack["missing"].append({"kind": "concept", "term": term})
    for metric, _ in metrics:
        concept = view.concepts.get(metric.get("on") or "")
        if concept is None:
            pack["missing"].append(
                {"kind": "concept", "term": term, "metric": _metric_ref(metric)}
            )
        else:
            pack["concepts"].append(_concept(view, concept, via=metric, material=material))


def _table_columns(
    view: CatalogView,
    documents: Mapping,
    tables: list[str],
    columns: list[str],
    table_columns: Iterable[str],
) -> tuple[list[str], list[dict]]:
    """``columns`` followed by the ``table_columns`` terms as ``db.table.column``, and the
    ``missing`` entries of the terms no requested table takes.

    With one requested table every bare name is that table's, as written. With several, a
    bare name goes to each requested table that has the column -- bound in the catalog, or
    described by the table's semantics document -- and ``table.col`` to the requested table
    of that name; ``db.table.col`` is taken as it is. A term already asked (ignoring case)
    is not asked again."""
    found = list(columns)
    asked = {term.casefold() for term in found}
    unplaced: list[dict] = []

    def add(term: str) -> None:
        if term.casefold() not in asked:
            asked.add(term.casefold())
            found.append(term)

    names = [str(term).strip() for term in table_columns if str(term).strip()]
    if len(tables) == 1:
        for name in names:
            add(f"{tables[0]}.{name}")
        return found, unplaced
    reps = list({
        rep["table"]: rep for rep in (view.representation(t) for t in tables) if rep is not None
    }.values())
    tried = [rep["table"] for rep in reps]
    for name in names:
        table_part, _, column = name.rpartition(".")
        if "." in table_part:
            add(name)
            continue
        if table_part:
            folded = table_part.casefold()
            targets = [r for r in reps if r["table"].rpartition(".")[2].casefold() == folded]
        else:
            targets = [r for r in reps if _has_column(r, documents.get(r["table"].lower()), column)]
        if not targets:
            unplaced.append({"kind": "column", "term": name, "tables": tried})
        for rep in targets:
            add(f"{rep['table']}.{column}")
    return found, unplaced


def _has_column(rep: Mapping, document: Optional[Mapping], column: str) -> bool:
    """Whether the catalog binds the column on the table or its semantics document has it."""
    folded = column.casefold()
    return any(b["column"].casefold() == folded for b in rep["bindings"]) or any(
        str(c.get("column", "")).casefold() == folded for c in (document or {}).get("columns") or []
    )


def _address(view: CatalogView, term: str):
    """``(representation or None, db.table, column)`` of a ``db.table.column`` term, or None."""
    table_name, _, column_name = str(term).strip().rpartition(".")
    if not table_name:
        return None
    rep = view.representation(table_name)
    table = rep["table"] if rep else catalog_table_name(table_name).lower()
    return rep, table, column_name


def _requested_columns(view: CatalogView, terms: Iterable[str]) -> dict[str, list[str]]:
    """``{db.table (lower case): [column, ...]}``: the columns requested of each table."""
    found: dict[str, list[str]] = {}
    for term in terms:
        address = _address(view, term)
        if address is None:
            continue
        names = found.setdefault(address[1].lower(), [])
        if address[2].casefold() not in names:
            names.append(address[2].casefold())
    return found


def _ref(view: CatalogView, object_id: str) -> dict:
    return {"id": object_id, "name": view.name(object_id)}


# ------------------------------------------------------------------ concept


def _concept(
    view: CatalogView,
    concept: Mapping,
    via: Optional[Mapping] = None,
    material: Optional[Mapping] = None,
) -> dict:
    """A concept's entry; reached through the metric ``via``, that metric comes first."""
    concept_id = concept["id"]
    metrics = view.metrics_on(concept_id)
    if via is not None:
        metrics = [via] + [m for m in metrics if m["id"] != via["id"]]
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
        "metrics": [_metric(view, metric, material) for metric in metrics],
    }
    if via is not None:
        answer["via_metric"] = _metric_ref(via)
    if concept.get("notes"):
        answer["notes"] = concept["notes"]
    return answer


def _metric_ref(metric: Mapping) -> dict:
    return {"id": metric["id"], "name": metric.get("name") or metric["id"]}


def _constraint(view: CatalogView, constraint: Mapping) -> dict:
    return {
        "id": constraint["id"],
        "kind": constraint["kind"],
        "on": _ref(view, constraint["on"]),
        "expression": constraint.get("expression"),
        "strength": constraint.get("strength"),
    }


def _constraints(view: CatalogView, concept_id: str) -> list[dict]:
    """A concept's constraints, each with the tables it comes from (``constraint_tables``)
    when it names any."""
    found = []
    for constraint in view.constraints_on(concept_id):
        entry = _constraint(view, constraint)
        tables = constraint_tables(view, constraint)
        if tables:
            entry["tables"] = tables
        found.append(entry)
    return found


# How a constraint's source tables relate to the table it is listed under, in the order
# a constraint takes the first that holds and the text lists them.
THIS_TABLE, UPSTREAM, DOWNSTREAM, UNRELATED, OTHER_TABLE = (
    "this_table", "upstream", "downstream", "unrelated", "other_table",
)


def _table_constraints(view: CatalogView, rep: Mapping) -> tuple[list[dict], dict]:
    """The constraints on a table's concept, each saying how its sources relate to the
    table, and ``{relation: n}`` of those from other tables left out for being on an
    attribute the table binds no column to (one from this table's own rules is always
    listed, so that segment is what ``catalog query table`` lists).

    A constraint from this table's rules is ``this_table``. Otherwise, with lineage
    evidence in the catalog, it is ``upstream`` when a source is upstream of this table
    (``also_downstream`` names its sources that read this table), else ``downstream``,
    else ``unrelated`` -- upstream and downstream followed through catalog tables only.
    Without lineage evidence it is ``other_table``. A constraint naming no table is listed
    as it always was: no ``tables``, no ``relation``.
    """
    table = rep["table"]
    lineage = view.lineage_checked()
    upstream = _reach(view, table, "upstream_tables") if lineage else set()
    downstream = _reach(view, table, "downstream_tables") if lineage else set()
    bound = {b.get("ref") for b in rep["bindings"] if b.get("ref")}
    listed: list[dict] = []
    unbound: dict[str, int] = {}
    for constraint in view.constraints_on(rep["concept"]):
        entry = _constraint(view, constraint)
        tables = constraint_tables(view, constraint)
        if not tables:
            listed.append(entry)
            continue
        if table in tables:
            relation, both = THIS_TABLE, []
        elif not lineage:
            relation, both = OTHER_TABLE, []
        elif any(t in upstream for t in tables):
            relation, both = UPSTREAM, [t for t in tables if t in downstream]
        elif any(t in downstream for t in tables):
            relation, both = DOWNSTREAM, []
        else:
            relation, both = UNRELATED, []
        if (
            relation != THIS_TABLE
            and constraint["on"] in view.attributes
            and constraint["on"] not in bound
        ):
            unbound[relation] = unbound.get(relation, 0) + 1
            continue
        entry.update(tables=tables, relation=relation)
        if both:
            entry["also_downstream"] = both
        listed.append(entry)
    return listed, unbound


def _reach(view: CatalogView, table: str, key: str) -> set[str]:
    """The catalog tables reached from ``table`` by following the lineage evidence's
    ``upstream_tables`` or ``downstream_tables``, hop after hop, through catalog tables."""
    found: set[str] = set()
    todo = [table]
    while todo:
        for name in view.rep_evidence(todo.pop()).get(key) or []:
            rep = view.representation(name)
            if rep is not None and rep["table"] != table and rep["table"] not in found:
                found.add(rep["table"])
                todo.append(rep["table"])
    return found


def _metric(view: CatalogView, metric: Mapping, material: Optional[Mapping] = None) -> dict:
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
        if measure in view.attributes:
            mark = unit_mark(view, view.attributes[measure][0], metric.get("unit"), material)
            if mark is not None:
                answer["material_unit"] = mark
    answer["dimensions"] = [_ref(view, d) for d in metric.get("dimensions") or []]
    answer["constraints"] = [
        {"id": c, "expression": (by_id.get(c) or {}).get("expression")}
        for c in metric.get("constraints") or []
    ]
    notes = shown_notes(metric.get("notes"), answer.get("material_unit"))
    if notes:
        answer["notes"] = notes
    return answer


_CLAUSE_END = re.compile(r"(?<=[。；;])")


def shown_notes(notes, mark: Optional[Mapping]) -> Optional[str]:
    """An item's ``notes`` as the answer prints them, or None when there is nothing to say.

    Where the answer already says the material gives no unit (``material_unit`` with
    ``given: false``), the sentence leaving the unit to the owner says the same and is left
    out; every other sentence is kept as written."""
    text = "；".join(str(note) for note in notes) if isinstance(notes, list) else str(notes or "")
    if mark is not None and not mark.get("given"):
        text = "".join(
            clause for clause in _CLAUSE_END.split(text)
            if clause.strip().rstrip("。；; ") != UNIT_LEFT_TO_OWNER
        )
    return text.strip() or None


# -------------------------------------------------------------------- links

_ALIASES = ("a", "b")
_AS_OF = "'<as_of_date>'"
_PERIOD = ("'<period_start>'", "'<period_end>'")


def _link(view: CatalogView, rep_a: Mapping, rep_b: Mapping) -> dict:
    """How two requested tables join: the backed pairs (the same ones ``check-sql``
    accepts), how many rows of each side meet a key, the filters each needs, the partitions
    that are not filters (a write batch, or a form the catalog does not record), and a SQL
    skeleton -- or, with no backed pair, the tables that join to both."""
    pairs = backed_pairs(view, rep_a, rep_b)
    filters = [
        {"table": rep["table"], "group": group, "columns": columns}
        for rep in (rep_a, rep_b)
        for group, columns in time_groups(rep)
    ]
    on = _on_pairs(rep_a, rep_b, pairs)
    sides = [
        _link_side(rep, [_column_of(pairs[i][key]) for i in on])
        for rep, key in ((rep_a, "left"), (rep_b, "right"))
    ]
    link: dict = {
        "tables": [rep_a["table"], rep_b["table"]],
        "pairs": [{**_link_pair(view, pair), "in_skeleton": i in on} for i, pair in enumerate(pairs)],
        "sides": sides,
        "filters": filters,
        "partitions": [
            {"table": rep["table"], **_partition(rep)}
            for rep in (rep_a, rep_b)
            if partition_reading(rep) not in (None, PARTITION_FULL)
        ],
    }
    link["skeleton"] = (
        _skeleton(rep_a, rep_b, pairs, on, sides, filters, link["partitions"]) if pairs else None
    )
    if not pairs:
        link["bridges"] = sorted(
            rep["table"]
            for rep in view.representations.values()
            if rep["table"] not in link["tables"]
            and backed_pairs(view, rep, rep_a)
            and backed_pairs(view, rep, rep_b)
        )
    return link


def _column_of(qualified: str) -> str:
    return qualified.rpartition(".")[2]


def _on_pairs(rep_a: Mapping, rep_b: Mapping, pairs: list[dict]) -> list[int]:
    """The pairs the skeleton puts in ON, by index. Backed pairs are often different paths
    -- a key and a self reference to it, the borrower and the payer -- so they are not all
    AND-ed: ON takes the pair that meets the most grain columns of the two sides (the first
    on a tie), then each pair on columns not used yet that closes a grain column still open.
    The others stay alternatives for the writer to choose."""
    if not pairs:
        return []
    grains = [
        {g.casefold() for g in grain_columns(rep) or []} for rep in (rep_a, rep_b)
    ]

    def columns(pair: Mapping) -> tuple[str, str]:
        return _column_of(pair["left"]).casefold(), _column_of(pair["right"]).casefold()

    def meets(pair: Mapping) -> int:
        return sum(column in grain for column, grain in zip(columns(pair), grains))

    first = max(range(len(pairs)), key=lambda i: (meets(pairs[i]), -i))
    chosen = [first]
    used = [{c} for c in columns(pairs[first])]
    for i, pair in enumerate(pairs):
        if i in chosen:
            continue
        pair_columns = columns(pair)
        if any(column in used[side] for side, column in enumerate(pair_columns)):
            continue
        if any(column in grains[side] for side, column in enumerate(pair_columns)):
            chosen.append(i)
            for side, column in enumerate(pair_columns):
                used[side].add(column)
    return sorted(chosen)


def _link_pair(view: CatalogView, pair: Mapping) -> dict:
    if pair.get("identifier"):
        return {"left": pair["left"], "right": pair["right"], "basis": "identifier",
                "identifier": _ref(view, pair["identifier"])}
    return {"left": pair["left"], "right": pair["right"], "basis": "seen_join",
            "relation": pair["relation"]}


def _link_side(rep: Mapping, columns: list[str]) -> dict:
    """Whether the join columns cover the side's recorded grain: one row per key, one row
    once the side's partition / window filters are applied, several, or not known."""
    side: dict = {"table": rep["table"], "grain": grain_columns(rep), "join_columns": []}
    for column in columns:
        if column not in side["join_columns"]:
            side["join_columns"].append(column)
    if side["grain"] is None:
        return {**side, "rows_per_key": "unknown", "open": [], "pinned_by_filters": []}
    left_open = uncovered(side["grain"], columns)
    filtered = pin_window(rep, {c["column"].casefold() for _, cs in time_groups(rep) for c in cs})
    still = uncovered(left_open, filtered)
    if not left_open:
        rows = "one"
    elif not still:
        rows = "one_once_filtered"
    else:
        rows = "several"
    return {
        **side,
        "rows_per_key": rows,
        "open": left_open,
        "pinned_by_filters": [c for c in left_open if c not in still],
    }


def _time_role_of(rep: Mapping, column: str) -> Optional[str]:
    return next(
        (b.get("time_role") for b in rep["bindings"] if b["column"].casefold() == column.casefold()),
        None,
    )


def _open_text(rep: Mapping, columns: list[str]) -> str:
    kinds = {"partition": "分区列", "valid_from": "拉链有效期列", "valid_to": "拉链有效期列"}
    return "、".join(
        column + (f"（{kinds[role]}）" if (role := _time_role_of(rep, column)) in kinds else "")
        for column in columns
    )


def _side_warning(side: Mapping, rep: Mapping, alias: str, other: str) -> Optional[str]:
    """The caution a side carries, or None when each key meets at most one of its rows."""
    who = f"{alias}（{side['table']}）"
    if side["rows_per_key"] == "unknown":
        return f"{who}没有记录粒度：每个关联键对上它几行不知道"
    if side["rows_per_key"] == "several":
        still = [c for c in side["open"] if c not in side["pinned_by_filters"]]
        pinned = (
            f"（{_open_text(rep, side['pinned_by_filters'])}由 WHERE 的过滤钉住）"
            if side["pinned_by_filters"] else ""
        )
        return (
            f"{who}每个关联键对上多行：粒度列 {_open_text(rep, still)} 没被关联列覆盖{pinned}，"
            f"对 {other} 的列求 SUM/COUNT 会重复计数"
        )
    if side["rows_per_key"] == "one_once_filtered":
        return (
            f"{who}要按粒度里的 {_open_text(rep, side['pinned_by_filters'])}钉住"
            "（分区取一个值、拉链取一个时点）才每个关联键一行，否则对上多行"
        )
    return None


def _filter_predicates(alias: str, filters: list[dict]) -> list[str]:
    found = []
    for item in filters:
        for column in item["columns"]:
            if column["role"] == "valid_from":
                found.append(f"{alias}.{column['column']} <= {_AS_OF}")
            elif column["role"] == "valid_to":
                found.append(f"{alias}.{column['column']} > {_AS_OF}")
            else:
                found.append(f"{alias}.{column['column']} = '<{column['column']}>'")
    return found


def _partition(rep: Mapping) -> dict:
    """``{columns, reading, period_columns}`` of a table with a partition column."""
    return {
        "columns": partition_columns(rep),
        "reading": partition_reading(rep),
        "period_columns": period_columns(rep),
    }


def _partition_comment(alias: str, item: Mapping) -> str:
    """How the skeleton treats a partition that is not a filter, as one comment line."""
    columns = "、".join(item["columns"])
    if item["reading"] != PARTITION_BATCH:
        return (
            f"-- {alias}（{item['table']}）的分区 {columns}：目录没记录每个分区是不是一份全量，"
            "骨架不加分区条件；按表语义「取数」决定"
        )
    period = item["period_columns"]
    if len(period) == 1:
        how = f"按 {alias}.{period[0]} 过滤时段（下面的占位换成时段起止，列的格式以「取数」为准）"
    elif period:
        how = f"按事件时间列（{'、'.join(period)}，选哪一列看「取数」）过滤时段"
    else:
        how = "时段按「取数」写明的日期列过滤"
    return f"-- {alias}（{item['table']}）的分区 {columns} 是写入批次，不是事件日期：不加分区条件，{how}"


def _period_predicates(alias: str, item: Mapping) -> list[str]:
    """``alias.col >= '<period_start>'`` and ``< '<period_end>'`` when the write-batch table
    has exactly one period column; otherwise none (the comment names the choices)."""
    if item["reading"] != PARTITION_BATCH or len(item["period_columns"]) != 1:
        return []
    column = item["period_columns"][0]
    return [f"{alias}.{column} >= {_PERIOD[0]}", f"{alias}.{column} < {_PERIOD[1]}"]


def _pair_reason(pair: Mapping) -> str:
    if pair.get("identifier"):
        return f"同一标识 {pair['identifier']}"
    return f"语料中见过（{pair['relation']}）"


def _skeleton(
    rep_a: Mapping, rep_b: Mapping, pairs: list[dict], on: list[int], sides: list[dict],
    filters: list[dict], partitions: list[dict],
) -> str:
    """``FROM a JOIN b ON <backed pairs> WHERE <one predicate a filter column>``, with
    the cautions as comment lines. A write-batch partition gets no predicate: a period on
    its one event-time column instead. Placeholders are string literals, so it parses."""
    a, b = _ALIASES
    lines = ["-- 关联方式（JOIN、LEFT JOIN 等）由写 SQL 的人决定：目录不说明该用哪一种"]
    for side, rep, alias, other in ((sides[0], rep_a, a, b), (sides[1], rep_b, b, a)):
        warning = _side_warning(side, rep, alias, other)
        if warning:
            lines.append(f"-- {warning}")
    for i, pair in enumerate(pairs):
        if i not in on:
            lines.append(
                f"-- 另一对有目录依据的关联列：{a}.{_column_of(pair['left'])} = "
                f"{b}.{_column_of(pair['right'])}（{_pair_reason(pair)}）；可能是另一条关联路径，"
                "意思不同，按问题替换或补进 ON，不要不加判断地 AND 上"
            )
    aliases = {rep_a["table"]: a, rep_b["table"]: b}
    for item in partitions:
        lines.append(_partition_comment(aliases[item["table"]], item))
    if any(f["group"] == "window" for f in filters):
        lines.append("-- 拉链有效期的开闭（> 还是 >=、未失效的结束日期怎么写）以表的约定为准")
    lines += ["SELECT *", f"FROM {rep_a['table']} {a}", f"JOIN {rep_b['table']} {b}"]
    for n, i in enumerate(on):
        left, right = _column_of(pairs[i]["left"]), _column_of(pairs[i]["right"])
        lines.append(
            f"  {'ON ' if n == 0 else 'AND'} {a}.{left} = {b}.{right}  -- {_pair_reason(pairs[i])}"
        )
    predicates = []
    for rep, alias in ((rep_a, a), (rep_b, b)):
        predicates += _filter_predicates(alias, [f for f in filters if f["table"] == rep["table"]])
        for item in partitions:
            if item["table"] == rep["table"]:
                predicates += _period_predicates(alias, item)
    for i, predicate in enumerate(predicates):
        lines.append(f"{'WHERE' if i == 0 else '  AND'} {predicate}")
    return "\n".join(lines) + "\n"


# -------------------------------------------------------------------- table


def _table(
    view: CatalogView,
    rep: Mapping,
    document: Optional[Mapping],
    *,
    brief: bool = False,
    focus: Optional[list[str]] = None,
    states: Optional[Mapping] = None,
) -> dict:
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
        **({"partition": _partition(rep)} if partition_reading(rep) else {}),
        "joins": _joins(view, rep, brief=brief),
    }
    answer["constraints"], unbound = _table_constraints(view, rep)
    if unbound:
        answer["constraints_unbound"] = unbound
    answer["metrics"] = [
        {"id": m["id"], "name": m["name"]} for m in view.metrics_on(concept_id)
    ]
    conflicts = view.rep_evidence(rep["table"]).get("conflicts")
    if conflicts:
        answer["conflicts"] = [
            {"rule": conflict["rule"], "text": conflict_text(view, rep["table"], conflict)}
            for conflict in conflicts
        ]
    answer["semantics"] = _semantics(
        document, brief=brief, focus=focus, states=_table_states(states, rep["table"])
    )
    return answer


def _joins(view: CatalogView, rep: Mapping, *, brief: bool = False) -> list[dict]:
    """One entry per foreign-key column: the identifier it holds and where that key lives.

    ``brief`` folds the JOINs whose two tables are both outside the catalog into a count
    (``seen_outside_catalog``); a JOIN involving a catalog table is always listed."""
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
        if brief:
            outside = _fold_outside(view, join)
            if outside:
                join["seen_outside_catalog"] = outside
        if binding.get("derivation"):
            join["derivation"] = binding["derivation"]
        found.append(join)
    return found


def _seen(view: CatalogView, rep: Mapping, binding: Mapping, other) -> list[dict]:
    """The JOINs the corpus showed for the relations this column realises, kept to the
    samples that involve this column, one entry for the same evidence.

    The evidence is per relation, so two things went wrong when it was copied under every
    column: a column naming no ``relation`` realises every parallel relation between the
    two concepts, and each of them carried the same JOINs (now one entry, ``relations``
    naming them all); and a relation's samples were listed under each column realising
    it, whichever column they filled (now only those that involve this one: a JOIN inside
    a producing task by the column it fills, a JOIN between catalog tables by its two
    sides).

    ``count`` is this column's: from the build's ``by_column`` when it is there (a column
    it does not name has no entry; one whose JOINs kept no sample gets an entry with no
    ``on``). A document built before ``by_column`` existed only has the relation's samples:
    when they are all its JOINs, ``count`` is how many are this column's; when the build
    cut them short, the JOINs left unsampled are ``unsampled`` -- whether they are this
    column's is not recorded -- and when no kept sample is this column's the entry says so
    (``count`` 0, ``relation_count``) rather than disappearing.
    """
    column = f"{rep['table']}.{binding['column']}".casefold()
    seen: list[dict] = []
    for relation in view.relations_of(rep["concept"]):
        if other not in (relation["from"], relation["to"]):
            continue
        if not realises(binding, relation["id"]):
            continue
        for where, joins in (
            ("between_catalog_tables", view.relation_joins(relation["id"])),
            ("inside_producing_task", view.relation_source_joins(relation["id"])),
        ):
            if not joins or not joins.get("count"):
                continue
            entry = _column_joins(joins, column)
            if entry is None:
                continue
            same = next((s for s in seen if _same_evidence(s, where, entry)), None)
            if same is not None:
                same.setdefault("relations", [same["relation"]]).append(relation["id"])
                continue
            seen.append({"relation": relation["id"], "where": where, **entry})
    return seen


def _column_joins(joins: Mapping, column: str) -> Optional[dict]:
    """``{count, on[, unsampled, relation_count]}`` of one relation's JOINs for one
    column (``_seen``), or None when they are not this column's."""
    samples = joins.get("samples") or []
    mine = [sample for sample in samples if _involves(sample, column)]
    on = list(dict.fromkeys(sample["on"] for sample in mine))
    if "by_column" in joins:
        count = next(
            (n for name, n in joins["by_column"].items() if str(name).casefold() == column), 0
        )
        return {"count": count, "on": on} if count else None
    unsampled = joins["count"] - len(samples)
    if samples and unsampled <= 0:
        return {"count": len(mine), "on": on} if mine else None
    if not samples:
        return {"count": joins["count"], "on": []}
    entry = {"count": len(mine), "on": on, "unsampled": unsampled}
    if not mine:
        entry["relation_count"] = joins["count"]
    return entry


def _same_evidence(seen: Mapping, where: str, entry: Mapping) -> bool:
    keys = ("count", "on", "unsampled", "relation_count")
    return seen["where"] == where and all(seen.get(k) == entry.get(k) for k in keys)


def _involves(sample: Mapping, column: str) -> bool:
    """Whether a sample JOIN is about ``db.table.column`` (lower case): the column a
    JOIN inside a producing task fills, else one side of the JOIN's ``a = b``."""
    if sample.get("column"):
        return str(sample["column"]).casefold() == column
    return column in {side.strip().casefold() for side in str(sample.get("on") or "").split(" = ")}


def _fold_outside(view: CatalogView, join: dict) -> int:
    """For ``--brief``: take out of ``join["seen"]`` the samples whose two tables are both
    outside the catalog, an entry left with none dropped, and return how many there were."""
    folded = 0
    kept = []
    for seen in join["seen"]:
        inside = [on for on in seen["on"] if _names_catalog_table(view, on)]
        folded += len(seen["on"]) - len(inside)
        if inside or not seen["on"]:
            kept.append({**seen, "on": inside})
    join["seen"] = kept
    return folded


def _names_catalog_table(view: CatalogView, on: str) -> bool:
    """Whether either side of ``a.t.c = b.t.c`` is a column of a catalog table."""
    return any(
        view.representation(side.strip().rpartition(".")[0]) is not None
        for side in str(on).split(" = ")
    )


def _semantics(
    document: Optional[Mapping],
    *,
    brief: bool = False,
    focus: Optional[list[str]] = None,
    states: Optional[Mapping] = None,
) -> dict:
    if not document:
        return {"present": False}
    summary = document.get("summary") or {}
    row = summary.get("row") or {}
    refresh = summary.get("refresh") or {}
    every_watch = [_pick(item, ("kind", "text", "refs")) for item in summary.get("watch") or []]
    every_question = [_question(item, states) for item in summary.get("questions") or []]
    scope = [_pick(item, ("text", "rule_refs")) for item in summary.get("scope") or []]
    watch = [item for item in every_watch if _about(item.get("refs"), focus)]
    questions = [item for item in every_question if _about(item.get("about"), focus)]
    cited = _cited_rules(scope, watch, questions)
    rule_keys = ("id", "kind", "text", "watch") if brief else ("id", "kind", "text", "sql", "watch")
    row_entry = _row(row)
    if (states or {}).get(ROW_SLOT) == _NOT_WRITTEN:
        row_entry["written"] = False
    answer = {
        "present": True,
        "what": summary.get("what"),
        "row": row_entry,
        "refresh": _pick(refresh, ("cycle", "time", "how_to_read", "watch")),
        "scope": scope,
        "good_for": list(summary.get("good_for") or []),
        "not_for": list(summary.get("not_for") or []),
        "watch": watch,
        "questions": questions,
        "rules": [
            _pick(rule, rule_keys)
            for rule in document.get("rules") or []
            if rule.get("id") in cited
        ],
        # who reads this table: what a change to it reaches (the one lineage fact kept)
        "downstream": [
            _reader(item) if brief else _pick(item, ("task", "table"))
            for item in summary.get("downstream") or []
        ],
        "columns": [
            _mark_column(_pick(column, ("column", "category") if brief
                               else ("column", "meaning", "category", "observed_values")), states,
                         column.get("column"))
            for column in document.get("columns") or []
        ],
    }
    if document.get("observed_inputs"):
        # what a platform query found about an input table, under this table's read
        # conditions only: never carried to another table
        answer["observed_inputs"] = [dict(item) for item in document["observed_inputs"]]
    if focus is not None:
        every_cited = _cited_rules(scope, every_watch, every_question)
        answer["focus"] = {
            "columns": list(focus),
            "left_out": {
                "watch": len(every_watch) - len(watch),
                "questions": len(every_question) - len(questions),
                "rules": sum(
                    1 for rule in document.get("rules") or []
                    if rule.get("id") in every_cited - cited
                ),
            },
        }
    return answer


def _row(row: Mapping) -> dict:
    """The row's words a query depends on. A grain a platform query observed also carries
    ``grain_source`` and the observation (its partitions and date): ``unique`` then speaks
    of those partitions only."""
    answer = _pick(row, ("text", "grain_columns", "unique", "note"))
    if row.get("observed") or row.get("grain_source") == "observed":
        answer.update(_pick(row, ("grain_source", "observed")))
    return answer


def _about(refs, focus: Optional[list[str]]) -> bool:
    """Whether an item stays under ``focus``: it names a requested column, or none at all."""
    if focus is None:
        return True
    named = {
        str(ref).split(":", 1)[1].casefold()
        for ref in refs or []
        if str(ref).casefold().startswith("column:")
    }
    return not named or bool(named & set(focus))


def _reader(item: Mapping) -> dict:
    """A downstream reader in a brief pack: the table it writes, or its task when none."""
    return {"table": item["table"]} if item.get("table") else _pick(item, ("task",))


def _cited_rules(scope: list, watch: list, questions: list) -> set[str]:
    cited = {ref for line in scope for ref in line.get("rule_refs") or []}
    for item in watch:
        cited |= {r.split(":", 1)[1] for r in item.get("refs") or [] if r.startswith("rule:")}
    for item in questions:
        cited |= {r.split(":", 1)[1] for r in item.get("about") or [] if r.startswith("rule:")}
    return cited


def _pick(item: Mapping, keys: tuple) -> dict:
    return {key: item[key] for key in keys if item.get(key) not in (None, "", [])}


# --------------------------------------------------------------- page states


def page_index(page_states: Optional[Mapping]) -> dict[tuple[str, str], dict]:
    """``{(db.table in lower case, question id): state}`` of a browsing page's states.

    A state is ``{"written": False}`` (an answer overlaid from the page, not written back)
    or a note ``{"kind", "reason", "by", "date"}`` with an optional ``choice`` (``yes`` /
    ``no``) and, for ``redirect``, ``to``; ``kind`` is one of ``PAGE_KINDS``. The table
    is matched the way the documents are (``catalog_table_name``, any case).

    A second kind of key names a structured slot the page answered, overlaid and not
    written back: ``(table, slot)`` with ``slot`` ``row``, ``column:<c>.meaning`` or
    ``column:<c>.code_values:<value>``; its state is ``{"written": False}`` only. A key
    that is ``row`` or starts with ``column:`` is a slot (a question id is ``q<n>``).
    Anything else raises ``ValueError``.
    """
    found: dict[tuple[str, str], dict] = {}
    for key, state in (page_states or {}).items():
        if not (isinstance(key, tuple) and len(key) == 2):
            raise ValueError(f"a page state is keyed by (table, question id), not {key!r}")
        where = (catalog_table_name(str(key[0]).strip()).lower(), str(key[1]))
        if not isinstance(state, Mapping):
            raise ValueError(f"page state of {where[0]} {where[1]} is not an object: {state!r}")
        if where[1] == ROW_SLOT or where[1].startswith("column:"):
            if not _SLOT.fullmatch(where[1]):
                raise ValueError(
                    f"page slot of {where[0]} is row, column:<c>.meaning or "
                    f"column:<c>.code_values:<value>, not {where[1]!r}"
                )
            if dict(state) != _NOT_WRITTEN:
                raise ValueError(
                    f"page slot {where[1]} of {where[0]} takes {{'written': False}} only, "
                    f"not {dict(state)!r}"
                )
            found[where] = dict(_NOT_WRITTEN)
            continue
        if "kind" not in state:
            if dict(state) != _NOT_WRITTEN:
                raise ValueError(
                    f"page state of {where[0]} {where[1]} is neither "
                    f"{{'written': False}} nor a note: {dict(state)!r}"
                )
            found[where] = dict(_NOT_WRITTEN)
            continue
        if state["kind"] not in PAGE_KINDS:
            raise ValueError(
                f"page note of {where[0]} {where[1]}: kind must be one of "
                f"{', '.join(PAGE_KINDS)}, not {state['kind']!r}"
            )
        found[where] = _pick(state, _NOTE_KEYS)
    return found


def _table_states(states: Optional[Mapping], table: str) -> dict[str, dict]:
    """``{question id or slot: state}`` of one table, from ``page_index``."""
    key = catalog_table_name(str(table).strip()).lower()
    return {qid: state for (name, qid), state in (states or {}).items() if name == key}


def unwritten_slots(states: Optional[Mapping], column: str) -> list[str]:
    """What the page answered of one column and has not written back, from one table's
    states: ``meaning`` first, then ``code_values:<value>`` in value order."""
    meaning, codes = [], []
    for key, state in (states or {}).items():
        match = _SLOT.fullmatch(str(key))
        if not match or match["column"] != column or state != _NOT_WRITTEN:
            continue
        if match["value"] is None:
            meaning.append("meaning")
        else:
            codes.append(match["value"])
    return meaning + [f"code_values:{value}" for value in sorted(codes)]


def _mark_column(entry: dict, states: Optional[Mapping], column: str) -> dict:
    unwritten = unwritten_slots(states, column)
    if unwritten:
        entry["unwritten"] = unwritten
    return entry


def mark_question(entry: dict, question: Mapping, state: Optional[Mapping]) -> dict:
    """``entry`` (a question as an output shows it) with its answer and page state.

    An answered question gains its answer keys, and ``written: false`` when the page says
    the answer is its own, not written back. An open one with a page note gains ``page``,
    and ``status: "set_aside"`` when the note sets it aside. A note on a question the
    document already answers is ignored: the document's answer stands.
    """
    if question.get("status") == "answered":
        entry.update(_pick(question, ANSWER_KEYS))
        if state == _NOT_WRITTEN:
            entry["written"] = False
    elif state and "kind" in state:
        if state["kind"] in SET_ASIDE_KINDS:
            entry["status"] = SET_ASIDE
        entry["page"] = dict(state)
    return entry


def _question(item: Mapping, states: Optional[Mapping]) -> dict:
    entry = _pick(item, ("id", "text", "about", "status"))
    return mark_question(entry, item, (states or {}).get(str(item.get("id"))))


# ------------------------------------------------------------------- column


def _column(
    view: CatalogView,
    term: str,
    documents: Mapping,
    material: Optional[Mapping] = None,
    states: Optional[Mapping] = None,
) -> Optional[dict]:
    address = _address(view, term)
    if address is None:
        return None
    rep, table, column_name = address
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
    own = _table_states(states, table)
    return {
        "table": table,
        "column": name,
        "catalog": _binding(view, table, binding, material) if binding else None,
        "semantics": _mark_column(_described(described), own, described.get("column"))
        if described else None,
        "watch": [
            _pick(item, ("kind", "text", "refs"))
            for item in summary.get("watch") or []
            if tag in {str(r).casefold() for r in item.get("refs") or []}
        ],
        "questions": [
            _question(item, own)
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


def _binding(
    view: CatalogView, table: str, binding: Mapping, material: Optional[Mapping] = None
) -> dict:
    answer: dict = {"to": binding["to"]}
    ref = binding.get("ref")
    if ref:
        answer["ref"] = _ref(view, ref)
        if ref in view.attributes:
            attribute = view.attributes[ref][0]
            if attribute.get("definition"):
                answer["definition"] = attribute["definition"]
            if attribute.get("type"):
                answer["type"] = attribute["type"]
            if attribute.get("unit"):
                answer["unit"] = attribute["unit"]
            mark = unit_mark(view, attribute, attribute.get("unit"), material)
            if mark is not None:
                answer["material_unit"] = mark
            notes = shown_notes(attribute.get("notes"), mark)
            if notes:
                answer["notes"] = notes
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


def unit_mark(
    view: CatalogView, attribute: Mapping, unit, material: Optional[Mapping]
) -> Optional[dict]:
    """``material_unit`` of a measure's unit (``unit``: the attribute's own, or that of a
    metric over it), or None when there is nothing to mark.

    The material is the table-semantics documents (``material``; None without them), and
    the judgement is ``unit_support``'s, the attribute's. A supported unit carries no mark.
    An unsupported one is marked ``{"given": false}`` (the catalog filled it in,
    unconfirmed), and so is no unit; no unit while the material gives one is
    ``{"given": true, "units": [...]}``. An attribute that cannot be judged, or is not a
    measure, carries no mark.
    """
    if material is None:
        return None
    support = unit_support(view, attribute, material)
    if support is None or support.outcome == UNJUDGED:
        return None
    if support.outcome == SUPPORTED:
        return None if unit else {"given": True, "units": list(support.units)}
    return {"given": False}


# --------------------------------------------------------------------- text


def render_context_text(pack: Mapping) -> str:
    """The pack as short Markdown: one block a concept, a table, a column."""
    lines: list[str] = []
    for concept in pack["concepts"]:
        lines += _concept_text(concept)
    brief = bool(pack["query"].get("brief"))
    for table in pack["tables"]:
        lines += _table_text(table, brief)
    for link in pack.get("links") or []:
        lines += _link_text(link)
    # a brief pack does not repeat a table's notes under each of its columns
    shown = {table["table"] for table in pack["tables"]} if brief else set()
    for column in pack["columns"]:
        lines += _column_text(column, column["table"] if column["table"] in shown else None)
    kinds = {"concept": "概念", "table": "表", "column": "字段"}
    for item in pack["missing"]:
        lines.append(f"未找到：{kinds[item['kind']]} {item['term']}{_missing_why(item)}")
    return "\n".join(lines).rstrip("\n") + "\n"


def _missing_why(item: Mapping) -> str:
    if item.get("metric"):
        return f"（指标 {item['metric']['name']} 没有挂在目录里的概念上）"
    if "tables" in item:
        return f"（{'、'.join(item['tables']) or '请求的表'} 都没有这一列）"
    return ""


def _concept_text(concept: Mapping) -> list[str]:
    lines = [f"# 概念 {concept['name']}（{concept['id']}，{concept['kind']}）", ""]
    via = concept.get("via_metric")
    if via:
        lines.append(f"- 由指标 {via['name']}（{via['id']}）找到：它是下面「指标」的第一条")
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
            lines += _metric_lines(metric, asked=bool(via) and metric["id"] == via["id"])
    else:
        lines += ["", "## 指标", "目录没有为这个概念定义指标。"]
    return lines + [""]


def _metric_lines(metric: Mapping, asked: bool = False) -> list[str]:
    mark = "（所问）" if asked else ""
    lines = [f"- {mark}{metric['name']}（{metric['id']}）：{metric.get('definition') or ''}"]
    measure = metric.get("measure")
    if measure:
        columns = "、".join(measure["columns"]) or "没有绑定的列"
        lines.append(f"  - 度量：{measure['name']}（{columns}）")
    for key, label in (
        ("aggregation", "聚合"), ("filter", "过滤"), ("time_window", "时间窗"),
        ("additivity", "可加性"), ("unit", "单位"), ("status", "状态"),
    ):
        if key == "unit":
            lines += [f"  - {line}" for line in _unit_line(metric)]
        elif metric.get(key):
            lines.append(f"  - {label}：{metric[key]}")
    if metric["dimensions"]:
        lines.append("  - 维度：" + "、".join(d["name"] for d in metric["dimensions"]))
    for constraint in metric["constraints"]:
        lines.append(f"  - 约束 {constraint['id']}：{constraint.get('expression') or ''}")
    if metric.get("notes"):
        lines.append(f"  - 备注：{metric['notes']}")
    return lines


def _unit_line(item: Mapping) -> list[str]:
    """The ``单位：…`` line of a binding or a metric with what ``material_unit`` says; none
    when there is neither a unit nor a mark."""
    text = unit_text(item)
    return [f"单位：{text}"] if text is not None else []


def unit_text(item: Mapping) -> Optional[str]:
    """What the ``单位：`` line says of an item's ``unit`` and ``material_unit``; None when
    there is neither (the browse page shows a table's units in the same words)."""
    mark = item.get("material_unit")
    if item.get("unit"):
        if mark is not None and not mark.get("given"):
            return f"{item['unit']}（材料未给，目录所填未经确认）"
        return str(item["unit"])
    if mark is None:
        return None
    if mark.get("given"):
        return f"{'、'.join(mark.get('units') or [])}（目录未填）"
    return "材料未给"


def _constraint_lines(constraints: list) -> list[str]:
    """A concept's constraints, each naming the tables it comes from when it has any."""
    return [
        f"- 约束 {c['id']}（{c['kind']}，针对 {c['on']['name']}"
        + (f"；来源 {'、'.join(c['tables'])}" if c.get("tables") else "")
        + f"）：{c.get('expression') or ''}"
        for c in constraints
    ]


# Each relation's heading and the one sentence saying what it means for this table.
_SEGMENTS = (
    (THIS_TABLE, "本表的规则带出", ""),
    (
        UPSTREAM, "上游表的规则带出",
        "本表的行若就是从这张上游表来的，条件已经带进来；本表若只是关联它补字段，条件不适用。"
        "工具分不出是哪一种，按来源表核对",
    ),
    (DOWNSTREAM, "下游表的规则带出", "是下游表加工时才做的，本表没有做"),
    (
        UNRELATED, "与本表没有血缘关系的表的规则带出",
        "目录的血缘证据里来源表与本表没有上下游关系，是否对本表成立工具不知道",
    ),
    (
        OTHER_TABLE, "其他表的规则带出",
        "目录没有合并血缘证据，来源表与本表是什么关系、是否对本表成立工具不知道",
    ),
)
_UNIQUE_UPSTREAM = "  - 上游的唯一性在本表不一定还成立：本表的粒度可能与上游不同"


def _table_constraint_lines(table: Mapping) -> list[str]:
    """A table's constraints: those naming no table as they always were, then one segment
    a relation, each line naming its sources, an upstream ``unique`` set apart, and a count
    of those on an attribute the table binds no column to."""
    constraints = table["constraints"]
    lines = _constraint_lines([c for c in constraints if not c.get("relation")])
    unbound = table.get("constraints_unbound") or {}
    for relation, label, meaning in _SEGMENTS:
        group = [c for c in constraints if c.get("relation") == relation]
        if not group and not unbound.get(relation):
            continue
        lines.append(f"- 约束（{label}）：{meaning}")
        unique = [c for c in group if relation == UPSTREAM and c["kind"] == "unique"]
        lines += [_sourced_line(c, table["table"]) for c in group if c not in unique]
        if unique:
            lines += [_UNIQUE_UPSTREAM] + [_sourced_line(c, table["table"]) for c in unique]
        if unbound.get(relation):
            lines.append(f"  - 另有 {unbound[relation]} 条约束针对本表没有绑定列的属性，未列出")
    return lines


def _sourced_line(constraint: Mapping, table: str) -> str:
    if constraint["relation"] == THIS_TABLE:
        others = [t for t in constraint["tables"] if t != table]
        source = f"；也来自 {'、'.join(others)}" if others else ""
    else:
        source = f"；来源 {'、'.join(constraint['tables'])}"
        if constraint.get("also_downstream"):
            source += f"；{'、'.join(constraint['also_downstream'])} 也读本表"
    return (
        f"  - 约束 {constraint['id']}（{constraint['kind']}，针对 {constraint['on']['name']}"
        f"{source}）：{constraint.get('expression') or ''}"
    )


def _table_text(table: Mapping, brief: bool = False) -> list[str]:
    lines = [f"# 表 {table['table']}", "", "## 目录"]
    concept = table["concept"]
    lines.append(f"- 承载概念：{concept['name']}（{concept['id']}），表的种类 {table['kind']}")
    grain = table["grain"]
    if grain["columns"]:
        lines.append(f"- 粒度：{'、'.join(grain['columns'])}（{grain.get('source') or '未说明'}）")
    for conflict in table.get("conflicts") or []:
        lines.append(f"- 证据与目录矛盾：{conflict['text']}")
    lines += _refresh_line(table)
    for column in table["time_columns"]:
        lines.append(f"- 时间列：{column['column']}（{column['role']}）")
    if table.get("partition"):
        lines.append(_partition_line(table["partition"]))
    for line in table["scope"]:
        lines.append(f"- 范围：{line}")
    for join in table["joins"]:
        lines += _join_lines(table["table"], join)
    lines += _table_constraint_lines(table)
    if table["metrics"]:
        lines.append(
            "- 这个概念上的指标：" + "、".join(f"{m['name']}（{m['id']}）" for m in table["metrics"])
        )
    return lines + _semantics_text(table["semantics"], brief) + [""]


def _refresh_line(table: Mapping) -> list[str]:
    """The time shape and refresh the catalog records, then the cycle the table-semantics
    document wrote (often the only place saying on which days a task runs)."""
    cycle = ((table.get("semantics") or {}).get("refresh") or {}).get("cycle")
    if not (table.get("time") or table.get("refresh") or cycle):
        return []
    line = f"- 时间形态：{table.get('time') or '未说明'}；刷新：{table.get('refresh') or '未说明'}"
    return [line + (f"；表语义写的周期：{cycle}" if cycle else "")]


def _partition_line(item: Mapping) -> str:
    """How to read the table's partition, by its time form: one partition, a write batch
    read by the event time, or not recorded."""
    columns = "、".join(item["columns"])
    if item["reading"] == PARTITION_FULL:
        return f"- 分区 {columns}：每个分区一份全量，只取一个分区（跨分区相加会重复计数）"
    if item["reading"] == PARTITION_BATCH:
        period = item["period_columns"]
        how = (
            f"按事件时间列 {'、'.join(period)} 过滤时段" if period
            else "时段按「取数」写明的日期列过滤"
        )
        return f"- 分区 {columns}：写入批次，不是事件日期，{how}；读一段时间要跨分区读，不靠分区条件"
    return f"- 分区 {columns}：目录没记录每个分区是不是一份全量，按「取数」读"


_ROWS_TEXT = {
    "one": "骨架的关联列覆盖了粒度，每个关联键一行",
    "one_once_filtered": "骨架的关联列没覆盖 {open}，按下面的过滤钉住（分区取一个值、拉链取一个时点）后每个关联键一行",
    "several": "骨架的关联列没覆盖 {open}{pinned}，每个关联键对上多行：对另一张表的列求 SUM/COUNT 会重复计数",
}


def _link_text(link: Mapping) -> list[str]:
    a, b = link["tables"]
    lines = [f"# 关联 {a} ↔ {b}", ""]
    if link["pairs"]:
        lines.append("- 目录支持的关联列对（与 check-sql 的判断相同）：")
        for pair in link["pairs"]:
            if pair["basis"] == "identifier":
                why = f"同一标识 {pair['identifier']['name']}（{pair['identifier']['id']}）"
            else:
                why = f"语料中见过这样关联（{pair['relation']}）"
            mark = "（骨架的 ON 用这一对）" if pair["in_skeleton"] else ""
            lines.append(f"  - {pair['left']} = {pair['right']}：{why}{mark}")
    else:
        lines.append("- 目录没有支持这两张表直接关联的列对：没有共同的标识，语料中也没见过它们之间的 JOIN")
        if link["bridges"]:
            lines.append(
                f"- 一跳的桥（与两张表都有目录支持的关联列对）：{'、'.join(link['bridges'])}；"
                "把它加进 --table 可看各段怎么关联"
            )
        else:
            lines.append("- 目录里也没有一张表同时与这两张表有目录支持的关联列对")
    for side in link["sides"]:
        if side["grain"] is None:
            tail = "，每个关联键对上几行不知道" if link["pairs"] else ""
            lines.append(f"- {side['table']} 一侧：目录没有记录粒度{tail}")
            continue
        head = f"- {side['table']} 一侧：粒度 {'、'.join(side['grain'])}"
        if not link["pairs"]:
            lines.append(head)
            continue
        still = [c for c in side["open"] if c not in side["pinned_by_filters"]]
        pinned = (
            f"（其中 {'、'.join(side['pinned_by_filters'])} 由下面的过滤钉住，"
            f"{'、'.join(still)} 仍敞开）" if side["pinned_by_filters"] and still else ""
        )
        rows = _ROWS_TEXT[side["rows_per_key"]]
        lines.append(f"{head}；{rows.format(open='、'.join(side['open']), pinned=pinned)}")
    names = {"partition": "分区列", "window": "拉链有效期列"}
    for item in link["filters"]:
        columns = "、".join(c["column"] for c in item["columns"])
        lines.append(f"- 要过滤：{item['table']} 按{names[item['group']]} {columns}")
    for item in link["partitions"]:
        lines.append(f"- {item['table']} 的{_partition_line(item)[2:]}")
    if link["skeleton"]:
        lines += ["- SQL 骨架（占位值换成真实值；关联方式由你定）：", "", "```sql",
                  link["skeleton"].rstrip("\n"), "```"]
    return lines + [""]


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
        lines.append(_seen_line(seen, places[seen["where"]]))
    if join.get("seen_outside_catalog"):
        lines.append(
            f"  - 另有 {join['seen_outside_catalog']} 条产出任务内部的连接证据两边的表都不在目录里，"
            "去掉 --brief 可看"
        )
    return lines


def _seen_line(seen: Mapping, place: str) -> str:
    """One relation's JOINs under a join column: the count and samples, a count with no
    sample, or -- from a build that kept no count per column -- what is not recorded."""
    unknown = "是否涉及本列没有记录（重新 build 可知）"
    if not seen["count"] and seen.get("unsampled"):
        return (
            f"  - {place}见过 {seen['relation_count']} 次连接，留下的样例都是别的列的，"
            f"其余 {seen['unsampled']} 次{unknown}"
        )
    if not seen["on"]:
        return f"  - 语料中见过 {seen['count']} 次（{place}），没有留下样例"
    line = f"  - 语料中见过 {seen['count']} 次（{place}）：{'；'.join(seen['on'])}"
    if seen.get("unsampled"):
        line += f"；另有 {seen['unsampled']} 次没留样例，{unknown}"
    return line


def _semantics_text(sem: Mapping, brief: bool = False) -> list[str]:
    if not sem["present"]:
        return ["", "## 怎么读", "本表没有表语义文档：怎么读、不适用场景、注意事项和待确认问题都没有人写下来。"]
    lines = ["", "## 怎么读"]
    if sem.get("what"):
        lines.append(f"- 是什么：{sem['what']}")
    row = sem.get("row") or {}
    if row:
        note = f"；{row['note']}" if row.get("note") else ""
        written = UNWRITTEN_TEXT if row.get("written") is False else ""
        lines.append(f"- 一行是：{row.get('text') or ''}（{_unique_text(row)}）{note}{written}")
    lines += [
        f"- 上游观测：{item['table']} {observed_input_text(item)}"
        for item in sem.get("observed_inputs") or []
    ]
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
    if sem.get("focus"):
        lines.append(_focus_line(sem["focus"]))
    lines += ["", "## 不适用"] + ([f"- {line}" for line in sem["not_for"]] or ["无"])
    lines += ["", "## 注意"]
    lines += [
        f"- （{item.get('kind') or '注意'}）{item.get('text') or ''}"
        + (f" [{'、'.join(item['refs'])}]" if item.get("refs") else "")
        for item in sem["watch"]
    ] or ["无"]
    lines += ["", "## 待确认问题"]
    kept = [item for item in sem["questions"] if item.get("status") != SET_ASIDE]
    lines += [line for item in kept for line in _question_lines(item)] or ["无"]
    lines += [_set_aside_line(item) for item in sem["questions"] if item.get("status") == SET_ASIDE]
    if sem["rules"]:
        lines += ["", "## 被引用的规则（不带 SQL，去掉 --brief 可看）" if brief else "## 被引用的规则"]
        for rule in sem["rules"]:
            lines.append(f"- {rule['id']}（{rule.get('kind') or ''}）：{rule.get('text') or ''}")
            if rule.get("sql"):
                lines.append(f"  - SQL：`{rule['sql']}`")
            if rule.get("watch"):
                lines.append(f"  - 注意：{rule['watch']}")
    lines += ["", "## 下游"]
    if brief:
        return lines + _brief_tail(sem)
    lines += [
        f"- {item.get('task') or '（任务未知）'}" + (f" → {item['table']}" if item.get("table") else "")
        for item in sem["downstream"]
    ] or ["表语义没有列出读这张表的任务。"]
    lines += ["", "## 字段一览"]
    lines += [
        f"- {c['column']}：{c.get('meaning') or ''}" + (f"（{c['category']}）" if c.get("category") else "")
        + (f"；{observed_values_text(c)}" if c.get("observed_values") else "")
        + _unwritten_text(c.get("unwritten"))
        for c in sem["columns"]
    ]
    return lines


def _unwritten_text(unwritten) -> str:
    """「（页面填写，尚未写回：含义、码值 'X'）」 after a column, or nothing."""
    if not unwritten:
        return ""
    codes = [item.split(":", 1)[1] for item in unwritten if item.startswith("code_values:")]
    parts = ["含义"] if "meaning" in unwritten else []
    if codes:
        parts.append("码值 " + "、".join(repr(code) for code in codes))
    return f"（页面填写，尚未写回：{'、'.join(parts)}）"


def _unique_text(row: Mapping) -> str:
    """``唯一：yes``; a grain a platform query observed is said as that observation, never as
    unique outright, and an observation backing a declared grain follows it."""
    observed = row.get("observed")
    if row.get("grain_source") == "observed":
        return f"观测：{observed_row_text(observed)}" if observed else "观测，只说明观测的分区"
    said = f"唯一：{row.get('unique') or '未说明'}"
    return f"{said}；观测：{observed_row_text(observed)}" if observed else said


def _focus_line(focus: Mapping) -> str:
    left = focus["left_out"]
    return (
        f"- 聚焦 {'、'.join(focus['columns'])}：略去只点名其他字段的注意 {left['watch']} 条、"
        f"待确认问题 {left['questions']} 条、规则 {left['rules']} 条；去掉 --focus 可看全部"
    )


def _brief_tail(sem: Mapping) -> list[str]:
    """Downstream readers by name and columns by name, grouped by category."""
    readers = list(dict.fromkeys(item.get("table") or item.get("task") or "" for item in sem["downstream"]))
    lines = [f"- 共 {len(sem['downstream'])} 个：{'、'.join(readers)}"] if readers else [
        "表语义没有列出读这张表的任务。"
    ]
    groups: dict[str, list[str]] = {}
    for column in sem["columns"]:
        groups.setdefault(column.get("category") or "未分类", []).append(column["column"])
    lines += ["", "## 字段一览", f"- 共 {len(sem['columns'])} 列，只列名字：--column 看一列的全文，去掉 --brief 看每列一行"]
    lines += [f"- {category}：{'、'.join(names)}" for category, names in groups.items()]
    return lines


def _question_line(item: Mapping) -> str:
    about = f" [{'、'.join(item['about'])}]" if item.get("about") else ""
    return f"- {item.get('id')}（{item.get('status') or '未说明'}）：{item.get('text') or ''}{about}"


_NOTE_LABELS = {
    "partial": "部分回答", "deferred": "暂缓", "redirect": "转问",
    "invalid": "问题有误", "not_applicable": "不适用",
}
_CHOICES = {"yes": "是", "no": "否"}


def _who(*parts) -> str:
    return "，".join(str(part) for part in parts if part)


def _question_lines(item: Mapping) -> list[str]:
    """A question not set aside: its line (with the page's note, if any), then its answer."""
    line = _question_line(item)
    if item.get("page"):
        line += _note_text(item["page"])
    lines = [line]
    if item.get("answer"):
        label = "回答（页面填写，尚未写回）" if item.get("written") is False else "回答"
        who = _who(item.get("answered_by"), item.get("answered_on"))
        lines.append(f"  - {label}：{item['answer']}" + (f"（{who}）" if who else ""))
    return lines


def _set_aside_line(item: Mapping) -> str:
    about = f" [{'、'.join(item['about'])}]" if item.get("about") else ""
    return f"- 已搁置：{item.get('id')} {item.get('text') or ''}{about}{_note_text(item['page'])}"


def _note_text(page: Mapping) -> str:
    """``（暂缓：理由；谁，日期）``: a page note after its question."""
    text = _NOTE_LABELS.get(page.get("kind"), str(page.get("kind")))
    if page.get("kind") == "redirect" and page.get("to"):
        text += f" {page['to']}"
    if page.get("choice") in _CHOICES:
        text += f"，{_CHOICES[page['choice']]}"
    if page.get("reason"):
        text += f"：{page['reason']}"
    who = _who(page.get("by"), page.get("date"))
    if who:
        text += f"；{who}"
    return f"（{text}）"


def _column_text(column: Mapping, shown_in: Optional[str] = None) -> list[str]:
    lines = [f"# 字段 {column['table']}.{column['column']}", ""]
    catalog = column.get("catalog")
    if catalog is None:
        lines.append("- 目录：没有绑定这一列")
    else:
        ref = catalog.get("ref")
        bound = f"{ref['name']}（{ref['id']}）" if ref else ""
        lines.append(f"- 目录：{catalog['to']} {bound}".rstrip())
        for key, label in (
            ("definition", "定义"), ("type", "类型"), ("unit", "单位"), ("derivation", "取值"),
            ("time_role", "时间角色"), ("via", "经由"), ("expression", "表达式"),
            ("notes", "备注"),
        ):
            if key == "unit":
                lines += [f"  - {line}" for line in _unit_line(catalog)]
            elif catalog.get(key):
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
        unwritten = sem.get("unwritten") or []
        lines.append(f"- 含义：{sem.get('meaning') or ''}" + (f"（{sem['category']}）" if sem.get("category") else "")
                     + (UNWRITTEN_TEXT if "meaning" in unwritten else ""))
        for key, label in (("derivation", "加工"), ("null_meaning", "空值"), ("watch", "注意")):
            if sem.get(key):
                lines.append(f"  - {label}：{sem[key]}")
        for branch in sem.get("branches") or []:
            lines.append(f"  - 分支 {branch.get('branch')}：{branch.get('text')}")
        if sem.get("code_values"):
            pairs = "、".join(f"{v.get('value')!r}={v.get('meaning')}" for v in sem["code_values"])
            codes = [item for item in unwritten if item.startswith("code_values:")]
            lines.append(f"  - 码值：{pairs}" + (_unwritten_text(codes) if codes else ""))
        if sem.get("observed_values"):
            lines.append(f"  - 观测取值：{observed_values_text(sem)}")
    if shown_in and (column["watch"] or column["questions"]):
        lines.append(
            f"- 点名本列的表级注意 {len(column['watch'])} 条、待确认问题 "
            f"{len(column['questions'])} 条：见上方表 {shown_in} 的「注意」「待确认问题」"
        )
        return lines + [""]
    for item in column["watch"]:
        lines.append(f"- 表级注意（{item.get('kind') or '注意'}）：{item.get('text') or ''}")
    for item in column["questions"]:
        if item.get("status") != SET_ASIDE:
            first, *rest = _question_lines(item)
            lines += ["- 待确认问题 " + first[2:], *rest]
    lines += [_set_aside_line(item) for item in column["questions"] if item.get("status") == SET_ASIDE]
    return lines + [""]
