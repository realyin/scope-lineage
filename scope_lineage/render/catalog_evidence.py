"""Corpus evidence attached to an ``ontology-json/3`` document (``catalog build``).

The catalog is what a person says; a lineage corpus and its table cards are what the
warehouse does. This module reads the second and files it **beside** the first, in one
top-level ``evidence`` block keyed by the catalog's own names, so no catalog object is
changed and a reader can always tell a claim from its evidence:

- ``evidence.representations["db.table"]``: the tasks that write the table, their
  schedule, the tables one hop up and down, the grain the producing SQL proves, and any
  disagreement between that proof and the grain the catalog declares; with ``--tables``
  also the table comment and how many columns the metadata declares and the corpus uses.
- ``evidence.bindings["db.table.column"]``: the physical source columns and the final
  expression of a bound column -- only where the binding has no hand-written derivation
  -- and ``declared_only`` for a column the metadata declares and no task touches.
- ``evidence.code_sets["code:..."]``: with ``--tables``, the lookup columns a code set
  names that the card of its lookup table does not declare -- a lookup pointing at a
  column the warehouse does not have. Present only when there is such a column.
- ``evidence.relations["rel:..."]``: how many JOINs in the corpus connect the two
  concepts' tables on a key pair whose two columns are both bound to one identifier of
  either concept, with up to three samples. A relation from a
  concept to itself counts only JOINs on a column the build marked ``self_reference``
  (another instance of the concept) that realises it -- names it as its ``relation``, or
  names none -- never the same instance met in a second table.
  ``source_joins`` beside it is a second, separate count: the JOINs *inside a statement
  that writes one end's table* that fill a foreign key -- one key column is a lineage
  source of a column the table binds as ``foreign_identifier`` to an identifier K of the
  other end (for a self relation, a ``self_reference`` column realising it), the other
  key column holds K (bound to it, or spelled as it). ``joins`` says the relation is
  used downstream; ``source_joins`` says how the producing task looked the key up. It
  needs a table at the written end only, and a column naming its ``relation`` is
  attributed to that relation alone. Whether a table *represents* a concept is never
  guessed from the identifiers it happens to spell.

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
from functools import partial
from typing import NamedTuple, Optional

from .catalog_view import catalog_table_name, lookup_columns, realises
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
    "table_comment",
    "declared_columns",
    "used_columns",
)
BINDING_KEYS = ("sources", "expression", "declared_only")


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
        inputs=tuple(
            sorted(
                {
                    catalog_table_name(item["table"])
                    for item in profile.get("inputs") or []
                    if item.get("table")
                }
            )
        ),
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
    return {
        "column": field.get("column"),
        "sources": sources,
        "expression": field.get("expression"),
    }


def _joins(document: Mapping) -> Iterable[JoinFact]:
    for _scope_id, block_id, pairs in join_key_pairs(document):
        for (left, right), columns in pairs.items():
            yield JoinFact(
                block_id, catalog_table_name(left), catalog_table_name(right), tuple(columns)
            )


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
        # table -> {column: the identifier it is bound to}, identifying bindings only
        self.identifying = {
            table: {
                b["column"]: b.get("ref")
                for b in rep["bindings"]
                if b["to"] in IDENTIFYING_BINDINGS
            }
            for table, rep in self.reps.items()
        }
        # concept -> the identifiers naming its instances: those it declares, and those
        # its tables bind as `identifier` (a role is named by its player's)
        self.keys: dict[str, set] = {
            concept["id"]: set(concept.get("identifiers") or [])
            for concept in ontology.get("concepts") or []
        }
        for rep in self.reps.values():
            self.keys.setdefault(rep["concept"], set()).update(
                b.get("ref") for b in rep["bindings"] if b["to"] == "identifier"
            )
        # table -> its self-referencing columns, each with its binding
        self.self_referencing = {
            table: {b["column"]: b for b in rep["bindings"] if b.get("self_reference")}
            for table, rep in self.reps.items()
        }
        # identifier -> {(lower-cased table or None, lower-cased column)} it is spelled as
        self.spelled: dict[str, set] = {
            identifier["id"]: {
                (
                    catalog_table_name(s["table"]).lower() if s.get("table") else None,
                    str(s["column"]).lower(),
                )
                for s in identifier.get("spellings") or []
            }
            for identifier in ontology.get("identifiers") or []
        }
        self.lookups = {
            code_set["id"]: code_set["lookup"]
            for code_set in ontology.get("code_sets") or []
            if code_set.get("lookup")
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
    checked = len(evidence["relations"])
    for relation_id, found in _source_joins(catalog, writers).items():
        evidence["relations"].setdefault(relation_id, {})["source_joins"] = found
    evidence["inputs"]["lineage"] = {
        "tasks": lineage.tasks,
        "statements": len(lineage.statements),
        "representations_matched": matched,
        "relations_checked": checked,
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
        return [
            {
                "rule": "grain_not_proven",
                "declared_source": source,
                "confidence": proof["confidence"],
            }
        ]
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
        if relation["from"] == relation["to"]:
            match = partial(_self_pair, relation_id=relation["id"])
        else:
            match = _identifying_pair
        keys = catalog.keys.get(relation["from"], set()) | catalog.keys.get(relation["to"], set())
        found[relation["id"]] = {"joins": _count_joins(catalog, ends, keys, statements, match)}
    return found


def _count_joins(catalog: _Catalog, ends: tuple, keys: set, statements: tuple, match) -> dict:
    count, samples = 0, []
    for statement in statements:
        for join in statement.joins:
            on = match(catalog, join, ends, keys)
            if on is None:
                continue
            count += 1
            if len(samples) < JOIN_SAMPLE_LIMIT:
                samples.append(
                    {"task": statement.task, "statement_id": statement.statement_id, "on": on}
                )
    return {"count": count, "samples": samples}


def _identifying_pair(
    catalog: _Catalog, join: JoinFact, ends: tuple, keys: set
) -> Optional[str]:
    """``"a.t.c = b.t.c"`` when this JOIN links the two ends on one of their identifiers."""
    first, second = ends
    crosses = (join.left in first and join.right in second) or (
        join.left in second and join.right in first
    )
    if join.left == join.right or not crosses:
        return None
    for left, right in join.columns:
        if _same_key(catalog, join, left, right, keys):
            return f"{join.left}.{left} = {join.right}.{right}"
    return None


def _self_pair(
    catalog: _Catalog, join: JoinFact, ends: tuple, keys: set, relation_id: str
) -> Optional[str]:
    """``"a.t.c = b.t.c"`` when this JOIN links two instances of one concept: both sides
    carry it and one side's key is a self-referencing column realising ``relation_id``
    (a table joined to itself counts too -- that is how a renewal meets the loan it
    renews)."""
    tables = ends[0]
    if join.left not in tables or join.right not in tables:
        return None
    left_refs = _realising(catalog.self_referencing[join.left], relation_id)
    right_refs = _realising(catalog.self_referencing[join.right], relation_id)
    for left, right in join.columns:
        if (left in left_refs or right in right_refs) and _same_key(
            catalog, join, left, right, keys
        ):
            return f"{join.left}.{left} = {join.right}.{right}"
    return None


def _realising(columns: Mapping, relation_id: str) -> set:
    return {column for column, binding in columns.items() if realises(binding, relation_id)}


def _same_key(catalog: _Catalog, join: JoinFact, left: str, right: str, keys: set) -> bool:
    """Both key columns are bound -- as ``identifier`` or ``foreign_identifier`` -- to one
    identifier, and that identifier names an instance of one of the relation's concepts.

    One bound side is not enough: a phone number met by a customer id is a JOIN on two
    different things, and two customer ids meeting between a call and a contact back a
    relation of the customer's, not one between the call and the contact.
    """
    left_ref = catalog.identifying[join.left].get(left)
    right_ref = catalog.identifying[join.right].get(right)
    return left_ref is not None and left_ref == right_ref and left_ref in keys


def _source_joins(catalog: _Catalog, writers: Mapping) -> dict:
    """``{relation id: {count, samples}}`` for relations a producing task's JOIN backs."""
    found = {}
    for relation in catalog.relations:
        ends = (relation["from"], relation["to"])
        directions = [ends] if ends[0] == ends[1] else [ends, ends[::-1]]
        hits: dict = {}
        for near, far in directions:
            for table in sorted(catalog.by_concept.get(near, ())):
                for statement in writers.get(table, ()):
                    anchors = _anchors(catalog, relation, table, far, statement)
                    for index, join in enumerate(statement.joins):
                        key = (statement.task, statement.statement_id, index)
                        hit = key not in hits and _filling_join(catalog, anchors, join)
                        if hit:
                            hits[key] = {
                                "task": statement.task,
                                "statement_id": statement.statement_id,
                                "column": f"{table}.{hit[0]}",
                                "on": hit[1],
                            }
        if hits:
            samples = [hits[key] for key in sorted(hits)][:JOIN_SAMPLE_LIMIT]
            found[relation["id"]] = {"count": len(hits), "samples": samples}
    return found


def _anchors(catalog: _Catalog, relation: Mapping, table: str, far: str, statement) -> dict:
    """``{lower-cased source column: [(identifier, bound column)]}``: the lineage sources of
    the columns ``table`` binds as ``foreign_identifier`` to one of ``far``'s identifiers
    and that may realise ``relation`` (a self relation: only ``self_reference`` columns).
    One source can feed several such columns, each bound to its own identifier."""
    self_relation = relation["from"] == relation["to"]
    far_keys = catalog.keys.get(far, set())
    bound = {
        str(b["column"]).lower(): (b["ref"], b["column"])
        for b in catalog.reps[table]["bindings"]
        if b["to"] == "foreign_identifier"
        and b.get("ref") in far_keys
        and (b.get("self_reference") or not self_relation)
        and realises(b, relation["id"])
    }
    anchors: dict = {}
    for field in statement.fields:
        target = bound.get(str(field["column"]).lower())
        for source in field["sources"] if target else ():
            anchors.setdefault(source.lower(), []).append(target)
    return anchors


def _filling_join(catalog: _Catalog, anchors: Mapping, join: JoinFact) -> Optional[tuple]:
    """``(bound column, "a.t.c = b.t.c")`` when one key column of ``join`` is an anchor and
    the other holds the identifier that anchor's column is bound to."""
    for left, right in join.columns:
        for (table, column), (other_table, other_column) in (
            ((join.left, left), (join.right, right)),
            ((join.right, right), (join.left, left)),
        ):
            targets = anchors.get(f"{table}.{column}".lower())
            held = _held(catalog, other_table, other_column) if targets else set()
            for identifier, bound in targets or ():
                if identifier in held:
                    return bound, f"{join.left}.{left} = {join.right}.{right}"
    return None


def _held(catalog: _Catalog, table: str, column: str) -> set:
    """The identifiers a column holds: bound to them, or spelled as them."""
    column = column.lower()
    held = {
        ref
        for bound, ref in (catalog.identifying.get(table) or {}).items()
        if str(bound).lower() == column
    }
    held |= {
        identifier
        for identifier, spellings in catalog.spelled.items()
        if (table.lower(), column) in spellings or (None, column) in spellings
    }
    return held


def _merge_tables(evidence: dict, catalog: _Catalog, tables: Mapping) -> None:
    cards: dict[str, Mapping] = {}
    for card in tables.get("tables") or []:
        for name in [card.get("table"), *(card.get("aliases") or [])]:
            cards.setdefault(catalog_table_name(name).lower(), card)
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
    for code_set_id, lookup in sorted(catalog.lookups.items()):
        card = cards.get(lookup["table"])
        if card is None:
            continue
        declared = {str(c.get("name")).lower() for c in card.get("columns") or []}
        missing = list(dict.fromkeys(
            column for column, _role in lookup_columns(lookup) if column.lower() not in declared
        ))
        if missing:
            evidence.setdefault("code_sets", {})[code_set_id] = {
                "table": lookup["table"],
                "missing_columns": missing,
            }


def _card_counts(card: Mapping) -> dict:
    """The card's table comment, and how many columns it declares and the corpus uses."""
    coverage = card.get("coverage") or {}
    counts = {}
    if card.get("comment"):
        counts["table_comment"] = str(card["comment"])
    if coverage.get("columns_declared") is not None:
        counts["declared_columns"] = coverage["columns_declared"]
    counts["used_columns"] = coverage.get("columns_used") or 0
    return counts


def _ordered_evidence(evidence: dict) -> dict:
    def ordered(entry: Mapping, keys: tuple) -> dict:
        return {key: entry[key] for key in keys if key in entry}

    result = {
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
    if evidence.get("code_sets"):
        result["code_sets"] = dict(sorted(evidence["code_sets"].items()))
    return result
