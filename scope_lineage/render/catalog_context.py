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

Two options shorten a table's pack for an agent that asks many questions. ``brief`` keeps
every item that decides how to query -- the catalog facts, what a row is, how to read it,
scope, not-for, watch items, open questions, the text of the cited rules -- and shortens the
parts that are long and do not: each column is named with its category but not described,
a cited rule loses its SQL, and a downstream reader is named by the table it writes (its
task only when it writes none). ``focus`` narrows a table's watch items, open questions and
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
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Optional

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
from .catalog_units import SUPPORTED, UNJUDGED, material_documents, unit_support
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
    table_columns: Iterable[str] = (),
    brief: bool = False,
    focus: bool = False,
) -> dict:
    """The pack for the named tables, columns (``db.table.column``) and concepts.

    ``table_columns`` are columns of the requested tables named without the table (or
    with ``table.`` to pin one); ``_table_columns`` says which table each goes to, and
    ``query.columns`` lists them as ``db.table.column`` after ``columns``. A concept term
    may name a metric: its concept is packed (``_concept_term``). ``brief`` shortens each
    table's semantics as the module says; ``focus`` narrows each table that has requested
    columns to them. Neither changes a concept or a column.
    """
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
            brief=brief, focus=focused.get(rep["table"].lower()),
        ))
    found = list({entry["table"]: entry for entry in pack["tables"]})
    if len(found) > 1:
        reps = [view.representation(table) for table in found]
        pack["links"] = [
            _link(view, a, b) for i, a in enumerate(reps) for b in reps[i + 1:]
        ]
    for term in pack["query"]["columns"]:
        answer = _column(view, term, documents, material)
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
    return answer


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
    answer["semantics"] = _semantics(document, brief=brief, focus=focus)
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


def _semantics(
    document: Optional[Mapping], *, brief: bool = False, focus: Optional[list[str]] = None
) -> dict:
    if not document:
        return {"present": False}
    summary = document.get("summary") or {}
    row = summary.get("row") or {}
    refresh = summary.get("refresh") or {}
    every_watch = [_pick(item, ("kind", "text", "refs")) for item in summary.get("watch") or []]
    every_question = [
        _pick(item, ("id", "text", "about", "status")) for item in summary.get("questions") or []
    ]
    scope = [_pick(item, ("text", "rule_refs")) for item in summary.get("scope") or []]
    watch = [item for item in every_watch if _about(item.get("refs"), focus)]
    questions = [item for item in every_question if _about(item.get("about"), focus)]
    cited = _cited_rules(scope, watch, questions)
    rule_keys = ("id", "kind", "text", "watch") if brief else ("id", "kind", "text", "sql", "watch")
    answer = {
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
            _pick(column, ("column", "category") if brief else ("column", "meaning", "category"))
            for column in document.get("columns") or []
        ],
    }
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


# ------------------------------------------------------------------- column


def _column(
    view: CatalogView, term: str, documents: Mapping, material: Optional[Mapping] = None
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
    return {
        "table": table,
        "column": name,
        "catalog": _binding(view, table, binding, material) if binding else None,
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
            if attribute.get("unit"):
                answer["unit"] = attribute["unit"]
            mark = unit_mark(view, attribute, attribute.get("unit"), material)
            if mark is not None:
                answer["material_unit"] = mark
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
    return [
        f"- 约束 {c['id']}（{c['kind']}，针对 {c['on']['name']}）：{c.get('expression') or ''}"
        for c in constraints
    ]


def _table_text(table: Mapping, brief: bool = False) -> list[str]:
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
    if table.get("partition"):
        lines.append(_partition_line(table["partition"]))
    for line in table["scope"]:
        lines.append(f"- 范围：{line}")
    for join in table["joins"]:
        lines += _join_lines(table["table"], join)
    lines += _constraint_lines(table["constraints"])
    if table["metrics"]:
        lines.append(
            "- 这个概念上的指标：" + "、".join(f"{m['name']}（{m['id']}）" for m in table["metrics"])
        )
    return lines + _semantics_text(table["semantics"], brief) + [""]


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
        lines.append(f"  - 语料中见过 {seen['count']} 次（{places[seen['where']]}）：{'；'.join(seen['on'])}")
    return lines


def _semantics_text(sem: Mapping, brief: bool = False) -> list[str]:
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
    lines += [_question_line(item) for item in sem["questions"]] or ["无"]
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
        for c in sem["columns"]
    ]
    return lines


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
            ("definition", "定义"), ("unit", "单位"), ("derivation", "取值"),
            ("time_role", "时间角色"), ("via", "经由"), ("expression", "表达式"),
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
        lines.append(f"- 含义：{sem.get('meaning') or ''}" + (f"（{sem['category']}）" if sem.get("category") else ""))
        for key, label in (("derivation", "加工"), ("null_meaning", "空值"), ("watch", "注意")):
            if sem.get(key):
                lines.append(f"  - {label}：{sem[key]}")
        for branch in sem.get("branches") or []:
            lines.append(f"  - 分支 {branch.get('branch')}：{branch.get('text')}")
        if sem.get("code_values"):
            pairs = "、".join(f"{v.get('value')!r}={v.get('meaning')}" for v in sem["code_values"])
            lines.append(f"  - 码值：{pairs}")
    if shown_in and (column["watch"] or column["questions"]):
        lines.append(
            f"- 点名本列的表级注意 {len(column['watch'])} 条、待确认问题 "
            f"{len(column['questions'])} 条：见上方表 {shown_in} 的「注意」「待确认问题」"
        )
        return lines + [""]
    for item in column["watch"]:
        lines.append(f"- 表级注意（{item.get('kind') or '注意'}）：{item.get('text') or ''}")
    for item in column["questions"]:
        lines.append("- 待确认问题 " + _question_line(item)[2:])
    return lines + [""]
