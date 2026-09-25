"""Corpus evidence attached to an ``ontology-json/3`` document (``catalog build``).

The catalog is what a person says; a lineage corpus and its table cards are what the
warehouse does. This module reads the second and files it **beside** the first, in one
top-level ``evidence`` block keyed by the catalog's own names, so no catalog object is
changed and a reader can always tell a claim from its evidence:

- ``evidence.representations["db.table"]``: the tasks that write the table, their
  schedule, the tables one hop up and down, the grain the producing SQL proves, and any
  disagreement between that proof and the grain the catalog declares; with ``--tables``
  also how many columns the metadata declares and how many the corpus uses.
- ``evidence.bindings["db.table.column"]``: the physical source columns and the final
  expression of a bound column -- only where the binding has no hand-written derivation
  -- and ``declared_only`` for a column the metadata declares and no task touches.
- ``evidence.relations["rel:..."]``: how many JOINs in the corpus connect the two
  concepts' tables on an identifying column, with up to three samples.

Nothing here parses a contract document: the statements and their profiles come from
``semantic_profile`` and ``ontology.write_statements``, the JOIN key pairs from
``ontology.join_key_pairs`` and the schedule from ``table_cards.refresh_from_task_meta``.
A table is matched on its last two dotted segments, because the catalog names tables
``db.table`` and a corpus may spell the same table ``catalog.db.table``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import NamedTuple, Optional

from .ontology import join_key_pairs, write_statements
from .semantic_profile import build_semantic_profile
from .table_cards import refresh_from_task_meta

EXPRESSION_LIMIT = 200
JOIN_SAMPLE_LIMIT = 3
IDENTIFYING_BINDINGS = ("identifier", "foreign_identifier")

# The profile's four key confidences, folded onto the three a catalog reader acts on.
# `proven_unexposed` is proven keys the target does not write, so the written columns
# can only be a candidate identity of the row.
_CONFIDENCE = {
    "proven": "proven",
    "proven_unexposed": "candidate",
    "candidate": "candidate",
    "none": "none",
}
_CONFIDENCE_ORDER = ("proven", "candidate", "none")
NO_GRAIN = {"confidence": "none", "keys": [], "basis": None}

REPRESENTATION_KEYS = (
    "producing_tasks",
    "refresh",
    "upstream_tables",
    "downstream_tables",
    "grain_proof",
    "conflicts",
    "declared_columns",
    "used_columns",
)
BINDING_KEYS = ("sources", "expression", "declared_only")


def catalog_table_name(name) -> str:
    """The ``db.table`` a corpus spelling names: its last two dotted segments."""
    return ".".join(str(name or "").split(".")[-2:])


class JoinFact(NamedTuple):
    """One JOIN between two physical tables, with its ``(left, right)`` key columns."""

    block: str
    left: str
    right: str
    columns: tuple


@dataclass(frozen=True)
class WriteStatement:
    """What the evidence merge needs of one write statement, table names normalised."""

    task: str
    statement_id: str
    target: str
    inputs: tuple = ()
    fields: tuple = ()
    joins: tuple = ()
    refresh: Optional[str] = None
    grain: Mapping = dataclass_field(default_factory=lambda: dict(NO_GRAIN))
    partition: tuple = ()


@dataclass(frozen=True)
class LineageFacts:
    statements: tuple
    tasks: int


# ------------------------------------------------------------------ reading lineage


def lineage_facts(pairs: Iterable[tuple[Mapping, Optional[Mapping]]]) -> LineageFacts:
    """``(lineage document, diagnostics or None)`` pairs, read into write statements."""
    documents, profiles = [], []
    for document, diagnostics in pairs:
        documents.append(dict(document))
        profiles.append(build_semantic_profile(dict(document), diagnostics))
    records = write_statements(documents, profiles)
    return LineageFacts(
        statements=tuple(_write_statement(record) for record in records),
        tasks=len({record.task for record in records}),
    )


def _write_statement(record) -> WriteStatement:
    profile = record.profile
    task_block = profile.get("task") or {}
    target = task_block.get("target_table")
    return WriteStatement(
        task=record.task,
        statement_id=record.statement_id,
        target=catalog_table_name(target) if target else "",
        inputs=tuple(sorted({
            catalog_table_name(item["table"])
            for item in profile.get("inputs") or []
            if item.get("table")
        })),
        fields=tuple(_field(field) for field in profile.get("fields") or []),
        joins=tuple(_joins(record.document)),
        refresh=_cycle(task_block.get("meta")),
        grain=_grain(profile.get("output_shape") or {}),
        partition=tuple((task_block.get("partition") or {}).get("columns") or ()),
    )


def _field(field: Mapping) -> dict:
    sources = [
        f"{catalog_table_name(source['table'])}.{source['column']}"
        for source in field.get("sources") or []
        if source.get("table") and source.get("column")
    ]
    return {"column": field.get("column"), "sources": sources, "expression": field.get("expression")}


def _joins(document: Mapping) -> Iterable[JoinFact]:
    for _scope_id, block_id, pairs in join_key_pairs(document):
        for (left, right), columns in pairs.items():
            yield JoinFact(block_id, catalog_table_name(left), catalog_table_name(right), tuple(columns))


def _cycle(task_meta) -> Optional[str]:
    refresh = refresh_from_task_meta(task_meta)
    if not refresh:
        return None
    return str(refresh.get("cycle") or refresh.get("cron"))


def _grain(shape: Mapping) -> dict:
    confidence = _CONFIDENCE.get(str(shape.get("key_confidence") or "none"), "none")
    grain = shape.get("grain") or {}
    if confidence == "proven":
        keys = [str(key.get("name")) for key in grain.get("keys") or []]
    else:
        keys = [str(key) for key in shape.get("candidate_keys") or []]
    return {"confidence": confidence, "keys": keys, "basis": grain.get("basis")}


# ------------------------------------------------------------------- the catalog side


class _Catalog:
    """The representations of one built document, indexed the ways the merge asks."""

    def __init__(self, ontology: Mapping) -> None:
        self.relations = list(ontology.get("relations") or [])
        self.reps = {rep["table"]: rep for rep in ontology.get("representations") or []}
        self.by_concept: dict[str, set] = {}
        for table, rep in self.reps.items():
            self.by_concept.setdefault(rep["concept"], set()).add(table)
        self.identifying = {
            table: {b["column"] for b in rep["bindings"] if b["to"] in IDENTIFYING_BINDINGS}
            for table, rep in self.reps.items()
        }


# ------------------------------------------------------------------------- merging


def attach_evidence(
    ontology: Mapping,
    *,
    lineage: Optional[LineageFacts] = None,
    tables: Optional[Mapping] = None,
) -> dict:
    """The document with its ``evidence`` block; unchanged when there is no input."""
    if lineage is None and tables is None:
        return dict(ontology)
    catalog = _Catalog(ontology)
    evidence: dict = {"inputs": {}, "representations": {}, "bindings": {}, "relations": {}}
    if lineage is not None:
        _merge_lineage(evidence, catalog, lineage)
    if tables is not None:
        _merge_tables(evidence, catalog, tables)
    return {**ontology, "evidence": _ordered_evidence(evidence)}


def _merge_lineage(evidence: dict, catalog: _Catalog, lineage: LineageFacts) -> None:
    writers: dict[str, list] = {}
    readers: dict[str, list] = {}
    for statement in lineage.statements:
        if statement.target:
            writers.setdefault(statement.target, []).append(statement)
        for table in statement.inputs:
            readers.setdefault(table, []).append(statement)
    matched = 0
    for table, rep in catalog.reps.items():
        entry = _lineage_entry(rep, writers.get(table, []), readers.get(table, []))
        if not entry:
            continue
        matched += 1
        evidence["representations"].setdefault(table, {}).update(entry)
        for key, found in _binding_lineage(rep, writers.get(table, [])):
            evidence["bindings"].setdefault(key, {}).update(found)
    evidence["relations"].update(_relation_joins(catalog, lineage.statements))
    evidence["inputs"]["lineage"] = {
        "tasks": lineage.tasks,
        "statements": len(lineage.statements),
        "representations_matched": matched,
        "relations_checked": len(evidence["relations"]),
    }


def _lineage_entry(rep: Mapping, writers: list, readers: list) -> dict:
    table = rep["table"]
    entry: dict = {}
    if writers:
        entry["producing_tasks"] = sorted({statement.task for statement in writers})
        cycles = sorted({statement.refresh for statement in writers if statement.refresh})
        if cycles:
            entry["refresh"] = cycles
        upstream = sorted({name for s in writers for name in s.inputs if name != table})
        if upstream:
            entry["upstream_tables"] = upstream
    downstream = sorted({s.target for s in readers if s.target and s.target != table})
    if downstream:
        entry["downstream_tables"] = downstream
    if writers:
        proof, partition = _strongest_proof(writers)
        entry["grain_proof"] = proof
        conflicts = grain_conflicts(rep, proof, partition)
        if conflicts:
            entry["conflicts"] = conflicts
    return entry


def _strongest_proof(writers: list) -> tuple[dict, set]:
    """The best-evidenced grain any writer proves, with that writer's partition columns."""
    best = min(
        writers,
        key=lambda s: (_CONFIDENCE_ORDER.index(s.grain["confidence"]), s.task, s.statement_id),
    )
    return {**best.grain, "task": best.task}, set(best.partition)


def grain_conflicts(rep: Mapping, proof: Mapping, partition: set) -> list[dict]:
    """Where the grain the SQL proves disagrees with the grain the catalog declares.

    Partition columns are left out of both sides: a statement writes one partition, so
    the grain it proves is the grain *within* it, while the catalog may name the
    partition column (``stat_date``) as part of the row's identity.
    """
    source = rep["grain"]["source"]
    if proof["confidence"] != "proven":
        if source != "proven":
            return []
        return [{"rule": "grain_not_proven", "declared_source": source, "confidence": proof["confidence"]}]
    declared = _declared_grain_columns(rep)
    if declared is None:
        return []
    declared, proven = declared - partition, set(proof["keys"]) - partition
    if not declared or declared == proven:
        return []
    return [{"rule": "grain_mismatch", "declared": sorted(declared), "proven": sorted(proven)}]


def _declared_grain_columns(rep: Mapping) -> Optional[set]:
    """The columns the declared grain names, or None when an identifier has no column."""
    columns = set(rep["grain"]["extra"])
    for identifier in rep["grain"]["identifiers"]:
        bound = {b["column"] for b in rep["bindings"] if b.get("ref") == identifier}
        if not bound:
            return None
        columns |= bound
    return columns


def _binding_lineage(rep: Mapping, writers: list) -> Iterable[tuple[str, dict]]:
    """``("db.table.column", {sources, expression})`` for each unexplained binding."""
    fields: dict[str, list] = {}
    for statement in sorted(writers, key=lambda s: (s.task, s.statement_id)):
        for field in statement.fields:
            fields.setdefault(str(field["column"]), []).append(field)
    for binding in rep["bindings"]:
        found = fields.get(binding["column"])
        if "derivation" in binding or not found:
            continue
        entry: dict = {}
        sources = sorted({source for field in found for source in field["sources"]})
        if sources:
            entry["sources"] = sources
        expression = next((f["expression"] for f in found if f.get("expression")), None)
        if expression:
            entry["expression"] = cut(str(expression))
        if entry:
            yield f"{rep['table']}.{binding['column']}", entry


def cut(text: str, limit: int = EXPRESSION_LIMIT) -> str:
    """``text`` at most ``limit`` characters long, an ellipsis marking the cut."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _relation_joins(catalog: _Catalog, statements: Iterable[WriteStatement]) -> dict:
    """``{relation id: {"joins": {count, samples}}}`` for relations with tables at both ends."""
    statements = tuple(statements)
    found = {}
    for relation in catalog.relations:
        ends = (catalog.by_concept.get(relation["from"]), catalog.by_concept.get(relation["to"]))
        if not ends[0] or not ends[1]:
            continue
        found[relation["id"]] = {"joins": _count_joins(catalog, ends, statements)}
    return found


def _count_joins(catalog: _Catalog, ends: tuple, statements: tuple) -> dict:
    count, samples = 0, []
    for statement in statements:
        for join in statement.joins:
            on = _identifying_pair(catalog, join, ends)
            if on is None:
                continue
            count += 1
            if len(samples) < JOIN_SAMPLE_LIMIT:
                samples.append({"task": statement.task, "statement_id": statement.statement_id, "on": on})
    return {"count": count, "samples": samples}


def _identifying_pair(catalog: _Catalog, join: JoinFact, ends: tuple) -> Optional[str]:
    """``"a.t.c = b.t.c"`` when this JOIN links the two ends on an identifying column."""
    first, second = ends
    crosses = (join.left in first and join.right in second) or (
        join.left in second and join.right in first
    )
    if join.left == join.right or not crosses:
        return None
    for left, right in join.columns:
        if left in catalog.identifying[join.left] or right in catalog.identifying[join.right]:
            return f"{join.left}.{left} = {join.right}.{right}"
    return None


def _merge_tables(evidence: dict, catalog: _Catalog, tables: Mapping) -> None:
    cards: dict[str, Mapping] = {}
    for card in tables.get("tables") or []:
        for name in [card.get("table"), *(card.get("aliases") or [])]:
            cards.setdefault(catalog_table_name(name), card)
    matched = 0
    for table, rep in catalog.reps.items():
        card = cards.get(table)
        if card is None:
            continue
        matched += 1
        evidence["representations"].setdefault(table, {}).update(_card_counts(card))
        unused = {c.get("name") for c in card.get("columns") or [] if not c.get("used_in_corpus")}
        for binding in rep["bindings"]:
            if binding["column"] in unused:
                key = f"{table}.{binding['column']}"
                evidence["bindings"].setdefault(key, {})["declared_only"] = True
    evidence["inputs"]["tables"] = {
        "cards": len(tables.get("tables") or []),
        "representations_matched": matched,
    }


def _card_counts(card: Mapping) -> dict:
    coverage = card.get("coverage") or {}
    counts = {}
    if coverage.get("columns_declared") is not None:
        counts["declared_columns"] = coverage["columns_declared"]
    counts["used_columns"] = coverage.get("columns_used") or 0
    return counts


def _ordered_evidence(evidence: dict) -> dict:
    def ordered(entry: Mapping, keys: tuple) -> dict:
        return {key: entry[key] for key in keys if key in entry}

    return {
        "inputs": evidence["inputs"],
        "representations": {
            table: ordered(entry, REPRESENTATION_KEYS)
            for table, entry in sorted(evidence["representations"].items())
        },
        "bindings": {
            key: ordered(entry, BINDING_KEYS) for key, entry in sorted(evidence["bindings"].items())
        },
        "relations": dict(sorted(evidence["relations"].items())),
    }
