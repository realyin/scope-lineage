"""Corpus-level ontology candidates (``ontology-json/1``) derived from the contracts.

``tables.json`` answers "what is this table". A corpus answers one more question that no
single table card can: **how do these tables relate**. Every JOIN in the corpus is an
assertion about two entities and their keys; every GROUP BY before a JOIN is an
assertion that the grouped table holds many rows per that key; every closed ``IN`` list
is an assertion about a column's value set. This module collects those assertions, one
corpus at a time, and publishes them as an ontology **candidate**: entities, attributes,
relations, constraints and the contradictions between them.

Three rules keep the candidate honest, and they are the reason it is a candidate.

1. **Every assertion carries a tier and its evidence.** ``proven`` is written in the SQL,
   ``implied`` follows from what the SQL does (a task that deduplicates a table by ``k``
   before joining it proves that table holds many rows per ``k`` -- otherwise the author
   would not have written the dedup), ``hypothesis`` is what an author assumed without
   proving it (a direct JOIN onto a physical table assumes that table is unique by the
   ON columns), and ``conflict`` is two tasks disagreeing. A claim with no evidence is
   not published at all.
2. **Domain neutrality.** No entity gets a business name, a class, a type or a parent.
   ``naming_hints`` holds metadata facts -- the table comment, the domain, the project,
   the owner -- exactly as the catalog wrote them, and the naming is left to whoever
   knows the business.
3. **Nothing is named that the corpus did not name.** Every entity, column, task and
   logic block here was copied from a contract document through a table card, a glossary
   entry or a semantic profile.

The vocabulary deliberately lines up with OWL/SHACL/LinkML slots (entity ~ class,
attribute ~ datatype property, relation ~ object property, constraint ~ node shape) so a
later exporter is a rename rather than a re-derivation. This release publishes JSON and
one index document; per-entity cards and the Mermaid ER overview are WI-10.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from sqlglot import exp

from . import glossary_values, semantic_text
from .glossary import build_glossary
from .markdown_text import cell, normalize_inline
from .semantic_profile import (
    TASK_PROFILE_ARTIFACT_KIND,
    TASK_SCHEMA_VERSION,
    aggregation_keys,
    build_semantic_profile,
    card_key_proof,
    card_lookup,
    comparable,
    driving_table,
    grouped_uniqueness,
    join_blocks,
    join_side_columns,
    ranking_partition_keys,
    ranking_uniqueness,
)
from .table_cards import (
    FINDING_AMBIGUOUS_BARE_NAME,
    FINDING_PRODUCER_KEY_CONFLICT,
    build_table_cards,
    same_table,
)

DOC_FORMAT = "ontology-json/1"
INDEX_DOC_FORMAT = "ontology-index-md/1"

# The four tiers, strongest first. Everything published carries exactly one of them.
TIER_PROVEN = "proven"
TIER_IMPLIED = "implied"
TIER_HYPOTHESIS = "hypothesis"
TIER_CONFLICT = "conflict"

TIERS = (TIER_PROVEN, TIER_IMPLIED, TIER_HYPOTHESIS, TIER_CONFLICT)

ENTITY_PHYSICAL = "physical_table"
ENTITY_PRODUCED = "produced_table"

RELATION_JOIN = "join_association"
RELATION_UNION = "union_sibling"

CARDINALITY_ONE_TO_MANY = "one_to_many"
CARDINALITY_MANY_TO_ONE = "many_to_one"
CARDINALITY_MANY_TO_ONE_ASSUMED = "many_to_one_assumed"
CARDINALITY_UNKNOWN = "unknown"

CARDINALITY_CLAIMS = (
    CARDINALITY_ONE_TO_MANY,
    CARDINALITY_MANY_TO_ONE,
    CARDINALITY_MANY_TO_ONE_ASSUMED,
    CARDINALITY_UNKNOWN,
)

# Why a cardinality is claimed. A token rather than a sentence: the JSON is read by
# machines, and the markdown renders the token into one line of Chinese.
BASIS_GROUP_BY = "group_by"
BASIS_RANKING_WINDOW = "ranking_window"
BASIS_PRODUCER_KEY = "producer_key_confidence"
BASIS_NO_DEDUP = "right_side_not_deduplicated"
BASIS_UNION_ALIGNMENT = "union_branch_alignment"
BASIS_NO_EVIDENCE = "no_uniqueness_evidence"

EVIDENCE_GROUP_BY = "group_by"
EVIDENCE_WINDOW_PARTITION = "window_partition"
EVIDENCE_JOINED_AS_RIGHT = "joined_as_right_without_dedup"
EVIDENCE_PRODUCER_KEY = "producer_key_confidence"

CLAIM_MULTIPLE_ROWS = "multiple_rows_per_key"

CONSTRAINT_NOT_NULL = "not_null"
CONSTRAINT_IN_SET = "in_set"
CONSTRAINT_UNIQUE_PER = "unique_per"
CONSTRAINT_PARTITION = "partition"

CONSTRAINT_KINDS = (
    CONSTRAINT_NOT_NULL,
    CONSTRAINT_IN_SET,
    CONSTRAINT_UNIQUE_PER,
    CONSTRAINT_PARTITION,
)

COMPLETENESS_COMPLETE = "complete"
COMPLETENESS_UNKNOWN = "unknown"

SYNONYM_DIRECT_RENAME = "direct_rename"
SYNONYM_UNION_ALIGNMENT = "union_alignment"

FINDING_CARDINALITY_CONFLICT = "cardinality_conflict"

FINDING_KINDS = (
    FINDING_CARDINALITY_CONFLICT,
    FINDING_PRODUCER_KEY_CONFLICT,
    FINDING_AMBIGUOUS_BARE_NAME,
)

# `key_confidence` on a table card is a statement about the producing task's proof;
# an ontology tier is a statement about the table. `proven_unexposed` proves the keys
# and not the target columns, so it cannot carry the target's identity claim.
KEY_CONFIDENCE_TIERS = {"proven": TIER_PROVEN, "candidate": TIER_HYPOTHESIS}

# A NOT NULL read off a filter is a fact about the TASK, never about the source: the
# task discarded the NULLs, which is evidence that there were some to discard.
NOT_NULL_NOTE = "任务用过滤丢弃了 NULL，源表本身可能仍含 NULL"

_ENTITY_KEYS = ("id", "kind", "comment", "identity", "attributes", "naming_hints")
_RELATION_KEYS = (
    "id",
    "from",
    "to",
    "kind",
    "cardinality",
    "join_types",
    "task_count",
    "evidence",
)
_ONTOLOGY_KEYS = (
    "doc_format",
    "corpus",
    "entities",
    "relations",
    "constraints",
    "findings",
)
_ATTRIBUTE_KEYS = (
    "column",
    "type",
    "comment",
    "observed_roles",
    "not_null_observed",
    "synonyms",
)
_CONSTRAINT_KEYS = (
    "target",
    "kind",
    "columns",
    "values",
    "completeness",
    "note",
    "tier",
    "evidence",
)
_FINDING_KEYS = ("kind", "entity", "columns", "tasks", "text")

_DIRECT_TRANSFORM = "DIRECT"


@dataclass(frozen=True)
class _Statement:
    """One write statement of one task: the contract document and its profile."""

    task: str
    statement_id: str
    document: dict
    profile: dict


# ----------------------------------------------------------------------------- builder


def build_ontology(
    documents: Iterable[Mapping],
    profiles: Sequence[Mapping] | None = None,
    *,
    tables: Mapping | None = None,
    glossary: Mapping | None = None,
    artifact_root: str | None = None,
) -> dict:
    """Build one corpus's ontology candidate.

    ``documents`` are contract documents (1.0 statement or 2.0 task shape), exactly what
    ``tables`` and ``glossary`` read. ``profiles`` is one semantic profile per document
    in the same order, so a caller that already built them -- the CLI builds them once
    for all three corpus artifacts -- does not pay for them twice. ``tables`` and
    ``glossary`` are the two corpus documents this one is derived on top of; either is
    built in memory from the same corpus when it is not supplied.
    """
    documents = [dict(document) for document in documents]
    profiles = (
        [dict(item) for item in profiles]
        if profiles is not None
        else [build_semantic_profile(document) for document in documents]
    )
    statements = _statements(documents, profiles)
    cards = dict(tables) if tables else build_table_cards(profiles, artifact_root=artifact_root)
    values = _glossary_values(documents, glossary, artifact_root)
    names = _name_index(cards)
    # The unmerged edges are kept beside the merged relations on purpose: merging is
    # what publishes the strongest claim per pair, and the claims it overrode are
    # exactly what O7 reports as a conflict.
    edges = _edges(statements, names, cards)
    constraints = _constraints(statements, cards, values, names)
    facts = {
        "multiplicity": _multiplicity(statements, names),
        "keys": _joined_keys(edges),
        "synonyms": _synonyms(statements, names),
        "not_null": _not_null_columns(constraints),
    }
    ontology = {
        "doc_format": DOC_FORMAT,
        "corpus": dict(cards.get("corpus") or {}),
        "entities": [_entity(card, facts) for card in cards.get("tables") or []],
        "relations": _relations(edges),
        "constraints": constraints,
        "findings": _findings(cards, edges, facts["multiplicity"]),
    }
    return {key: ontology[key] for key in _ONTOLOGY_KEYS}


def _not_null_columns(constraints: Sequence[Mapping]) -> set[tuple[str, str]]:
    return {
        (str(item["target"]["entity"]), str(item["target"]["column"]))
        for item in constraints
        if str(item["kind"]) == CONSTRAINT_NOT_NULL
    }


def _glossary_values(
    documents: Sequence[Mapping], glossary: Mapping | None, artifact_root: str | None
) -> list[dict]:
    """The corpus dictionary's value entries, supplied or built over the same corpus."""
    if glossary is not None:
        return [dict(entry) for entry in glossary.get("values") or []]
    built = build_glossary(documents, artifact_root=str(artifact_root or "."))
    return [dict(entry) for entry in built.get("values") or []]


def _statements(
    documents: Sequence[Mapping], profiles: Sequence[Mapping]
) -> list[_Statement]:
    """One record per write statement, contract document paired with its profile."""
    records: list[_Statement] = []
    for document, profile in zip(documents, profiles):
        task = str(document.get("task_id") or (profile.get("task") or {}).get("task_name") or "")
        if document.get("schema_version") != TASK_SCHEMA_VERSION:
            records.append(
                _Statement(task, str(profile.get("statement_id") or ""), dict(document), dict(profile))
            )
            continue
        lineage = document.get("statement_lineage") or {}
        if profile.get("artifact_kind") != TASK_PROFILE_ARTIFACT_KIND:
            continue
        records.extend(
            _Statement(task, str(item.get("statement_id")), lineage[item["statement_id"]], item)
            for item in profile.get("statements") or []
            if item.get("statement_id") in lineage
        )
    return sorted(records, key=lambda record: (record.task, record.statement_id))


# ------------------------------------------------------------------ name normalization


def _name_index(cards: Mapping) -> dict[str, str]:
    """``every spelling the corpus wrote -> the card's primary name``."""
    index: dict[str, str] = {}
    for card in cards.get("tables") or []:
        primary = str(card.get("table"))
        for name in [primary, *(card.get("aliases") or [])]:
            index[str(name)] = primary
    return index


def _entity_of(name, index: Mapping[str, str]) -> str | None:
    """The entity one table spelling belongs to, or None when the corpus cannot tell.

    An exact spelling answers itself. Anything else is resolved by the corpus-wide
    dotted-suffix rule the table cards group by, and an unqualified name several
    qualified entities could be stays unresolved rather than guessing a database.
    """
    text = str(name or "")
    if not text:
        return None
    if text in index:
        return index[text]
    hosts = {primary for spelling, primary in index.items() if same_table(text, spelling)}
    return hosts.pop() if len(hosts) == 1 else None


# --------------------------------------------------------------- O1 / O2: relations


def _edges(
    statements: Sequence[_Statement], names: Mapping[str, str], cards: Mapping
) -> list[dict]:
    """One edge per JOIN key pair and per UNION sibling pair, before any merging (O1)."""
    lookup = card_lookup(cards)
    return [
        edge
        for statement in statements
        for edge in [
            *_join_edges(statement, names, lookup),
            *_union_edges(statement, names),
        ]
    ]


def _relations(edges: Sequence[Mapping]) -> list[dict]:
    """The corpus's relations: one per ``(from, columns, to, columns, kind)`` (O1, O2)."""
    merged: dict[tuple, dict] = {}
    for edge in edges:
        _merge_edge(merged, dict(edge))
    ordered = sorted(merged.values(), key=_relation_sort_key)
    numbered = []
    for index, relation in enumerate(ordered, start=1):
        relation["id"] = f"rel:{index:03d}"
        numbered.append({key: relation[key] for key in _RELATION_KEYS if key in relation})
    return numbered


def _relation_sort_key(relation: Mapping) -> tuple:
    return (
        str(relation["from"]["entity"]),
        tuple(relation["from"]["columns"]),
        str(relation["to"]["entity"]),
        tuple(relation["to"]["columns"]),
        str(relation["kind"]),
    )


def _merge_edge(merged: dict[tuple, dict], edge: dict) -> None:
    """One edge per ``(from entity, from columns, to entity, to columns, kind)``."""
    key = _relation_sort_key(edge)
    current = merged.get(key)
    if current is None:
        merged[key] = edge
        return
    current["join_types"] = sorted({*current["join_types"], *edge["join_types"]})
    current["evidence"].extend(
        item for item in edge["evidence"] if item not in current["evidence"]
    )
    current["task_count"] = len({item["task"] for item in current["evidence"]})
    current["cardinality"] = _stronger_cardinality(
        current["cardinality"], edge["cardinality"]
    )


def _stronger_cardinality(current: Mapping, other: Mapping) -> dict:
    """The better-evidenced of two claims; a disagreement is reported in ``findings``.

    Publishing the stronger claim is not a vote: a task that deduplicated a table by a
    key proved something about the table, and a task that joined it directly only
    assumed something. The assumption stays visible as a ``cardinality_conflict``.
    """
    pair = sorted(
        [dict(current), dict(other)],
        key=lambda item: (
            TIERS.index(str(item.get("tier"))),
            CARDINALITY_CLAIMS.index(str(item.get("claim"))),
            str(item.get("basis")),
        ),
    )
    return pair[0]


def _join_edges(
    statement: _Statement, names: Mapping[str, str], lookup
) -> list[dict]:
    """O1: one edge per ``(left table, right table)`` a JOIN's key pairs pierce to."""
    document = statement.document
    edges = []
    for scope_id, block_id, detail in join_blocks(document):
        cardinality = _cardinality(document, block_id, detail, lookup)
        sides = {side: _side_entity(document, detail, side) for side in ("left", "right")}
        for (left, right), pairs in _key_pairs_by_table(document, detail, sides).items():
            from_entity = _entity_of(left, names)
            to_entity = _entity_of(right, names)
            if not from_entity or not to_entity:
                continue
            edges.append(
                {
                    "from": {"entity": from_entity, "columns": _dedupe(item[0] for item in pairs)},
                    "to": {"entity": to_entity, "columns": _dedupe(item[1] for item in pairs)},
                    "kind": RELATION_JOIN,
                    "cardinality": cardinality,
                    "join_types": [str(detail.get("join_type") or "")],
                    "task_count": 1,
                    "evidence": [_join_evidence(statement, scope_id, block_id, sides)],
                }
            )
    return edges


def _join_evidence(
    statement: _Statement, scope_id: str, block_id: str, sides: Mapping[str, tuple]
) -> dict:
    """The task, the block, and the scopes a CTE side was pierced through to a table."""
    evidence = {
        "task": statement.task,
        "statement_id": statement.statement_id,
        "scope_id": scope_id,
        "logic_block_id": block_id,
    }
    for side in ("left", "right"):
        via = sides[side][1]
        if via:
            evidence[f"{side}_via_scopes"] = list(via)
    return evidence


def _side_entity(document: Mapping, detail: Mapping, side: str) -> tuple[str | None, list[str]]:
    """``(the physical table this JOIN side's rows are, the scopes walked to reach it)``.

    A JOIN side that names a table answers itself; a side that names a CTE is pierced
    with R3's own driving-input descent, because a CTE is not an entity and the entity
    behind it is whatever physical table supplies its rows.
    """
    item = str(detail.get(f"{side}_input") or "")
    if not item:
        return None, []
    if item in set(document.get("source_tables") or []):
        return item, []
    return driving_table(document, item)


def _key_pairs_by_table(
    document: Mapping, detail: Mapping, sides: Mapping[str, tuple]
) -> dict[tuple[str, str], list[tuple[str, str]]]:
    """``(left table, right table) -> [(left column, right column)]`` for one JOIN.

    Grouping by the table pair is what keeps a key pair written over a 12-branch UNION
    from becoming twelve invented keys: the contract's physical pierce is a cross
    product of both sides' fields, and each product member belongs to exactly one table
    pair. A pierced pair that degenerates to ``t.c = t.c`` is dropped, exactly as the
    mapping document drops it.
    """
    grouped: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for pair in detail.get("join_key_pairs") or []:
        left = _pair_endpoints(pair, "left", sides["left"][0])
        right = _pair_endpoints(pair, "right", sides["right"][0])
        for left_table, left_column in left:
            for right_table, right_column in right:
                if (left_table, left_column) == (right_table, right_column):
                    continue
                grouped.setdefault((left_table, right_table), []).append(
                    (left_column, right_column)
                )
    return grouped


def _pair_endpoints(
    pair: Mapping, side: str, fallback_table: str | None
) -> list[tuple[str, str]]:
    """One side of one key pair as ``(table, column)``, pierced or carried by the walk.

    The contract's pierce answers first. When it cannot -- the key is a column the CTE
    computed, so it has no single physical source -- the entity is the table that side's
    rows come from and the column is the name the ON clause itself wrote.
    """
    fields = [
        (str(field.get("table")), str(field.get("field")))
        for field in pair.get(f"{side}_fields") or []
        if field.get("table") and field.get("field")
    ]
    if fields:
        return _dedupe(fields)
    reference = pair.get(side) or {}
    if fallback_table and reference.get("column"):
        return [(fallback_table, str(reference["column"]))]
    return []


def _cardinality(document: Mapping, block_id: str, detail: Mapping, lookup) -> dict:
    """O2: what this JOIN proves about how many rows the right side holds per key.

    Four answers, in the order their evidence is strong. A right side the task grouped
    or ranked by the join keys before joining proves the table *under* it holds many
    rows per key -- otherwise the dedup would be pointless, which is the ``implied``
    tier's whole argument. A right side another task is known to write one row per these
    columns is ``proven`` many-to-one. A physical table joined directly is the author's
    ``hypothesis`` that it is unique. Anything else is unknown, and says so.
    """
    right = str(detail.get("right_input") or "")
    columns = join_side_columns(detail, "right")
    if right in set(document.get("source_tables") or []):
        return _physical_cardinality(right, columns, lookup)
    if not columns or right not in (document.get("scopes") or {}):
        return _claim(CARDINALITY_UNKNOWN, TIER_HYPOTHESIS, BASIS_NO_EVIDENCE)
    if _right_is_grouped(document, right, columns):
        return _claim(CARDINALITY_ONE_TO_MANY, TIER_IMPLIED, BASIS_GROUP_BY)
    if _right_is_ranked(document, right, block_id, detail, columns):
        return _claim(CARDINALITY_ONE_TO_MANY, TIER_IMPLIED, BASIS_RANKING_WINDOW)
    return _claim(CARDINALITY_UNKNOWN, TIER_HYPOTHESIS, BASIS_NO_EVIDENCE)


def _physical_cardinality(right: str, columns: Sequence[str], lookup) -> dict:
    """A JOIN straight onto a table: the corpus's proof if there is one, else the guess."""
    proof = card_key_proof(lookup(right)) if lookup is not None else None
    if proof is not None:
        task, keys, level = proof
        if columns and comparable(keys) <= comparable(columns) and KEY_CONFIDENCE_TIERS.get(
            level
        ) == TIER_PROVEN:
            return _claim(
                CARDINALITY_MANY_TO_ONE, TIER_PROVEN, BASIS_PRODUCER_KEY, producer=task
            )
    return _claim(CARDINALITY_MANY_TO_ONE_ASSUMED, TIER_HYPOTHESIS, BASIS_NO_DEDUP)


def _claim(claim: str, tier: str, basis: str, **extra) -> dict:
    return {"claim": claim, "tier": tier, "basis": basis, **extra}


def _right_is_grouped(document: Mapping, scope_id: str, columns: Sequence[str]) -> bool:
    """R3's own GROUP BY verdict: the scope's key set is covered by the join keys."""
    verdict = grouped_uniqueness(dict(document), scope_id, list(columns))
    return bool(verdict and verdict[0] == "safe")


def _right_is_ranked(
    document: Mapping, scope_id: str, block_id: str, detail: Mapping, columns: Sequence[str]
) -> bool:
    """R3's own ranking verdict: a window over the join keys, filtered to ``= 1``."""
    return (
        ranking_uniqueness(dict(document), scope_id, (block_id, dict(detail)), list(columns))
        is not None
    )


def _union_edges(statement: _Statement, names: Mapping[str, str]) -> list[dict]:
    """O1: two branches of one UNION are siblings, aligned column by column."""
    edges = []
    for scope_id, alignment in _union_alignments(statement.document):
        branches = _branch_columns(alignment)
        for index, (left_table, left_columns) in enumerate(branches):
            for right_table, right_columns in branches[index + 1 :]:
                pair = _aligned_pairs(left_columns, right_columns)
                from_entity = _entity_of(left_table, names)
                to_entity = _entity_of(right_table, names)
                if not pair or not from_entity or not to_entity or from_entity == to_entity:
                    continue
                edges.append(
                    {
                        "from": {"entity": from_entity, "columns": [item[0] for item in pair]},
                        "to": {"entity": to_entity, "columns": [item[1] for item in pair]},
                        "kind": RELATION_UNION,
                        "cardinality": _claim(
                            CARDINALITY_UNKNOWN, TIER_IMPLIED, BASIS_UNION_ALIGNMENT
                        ),
                        "join_types": [],
                        "task_count": 1,
                        # A UNION's alignment is a property of the scope, and the
                        # contract files the `union` logic blocks on whichever scope
                        # READS it -- so the evidence names the scope and stops there
                        # rather than pointing at a block that may belong elsewhere.
                        "evidence": [
                            {
                                "task": statement.task,
                                "statement_id": statement.statement_id,
                                "scope_id": scope_id,
                            }
                        ],
                    }
                )
    return edges


def _union_alignments(document: Mapping) -> list[tuple[str, dict]]:
    return [
        (str(scope_id), scope["union_branch_alignment"])
        for scope_id, scope in sorted((document.get("scopes") or {}).items())
        if (scope or {}).get("union_branch_alignment")
    ]


def _branch_columns(alignment: Mapping) -> list[tuple[str, dict[int, str]]]:
    """``(branch table, {position: physical column})`` for branches reading one table.

    A branch over several tables has no single entity behind it, and a select item whose
    value is computed rather than read has no physical column: both are skipped rather
    than attributed to whichever table happened to be first.
    """
    found = []
    for branch in alignment.get("branches") or []:
        tables = [str(table) for table in branch.get("source_tables") or []]
        if len(tables) != 1:
            continue
        columns = {}
        for item in branch.get("select_items") or []:
            fields = (item.get("expression_resolution") or {}).get(
                "physical_source_fields"
            ) or []
            if len(fields) == 1 and str(fields[0].get("table")) == tables[0]:
                columns[int(item.get("position") or 0)] = str(fields[0].get("field"))
        found.append((tables[0], columns))
    return found


def _aligned_pairs(
    left: Mapping[int, str], right: Mapping[int, str]
) -> list[tuple[str, str]]:
    return [
        (left[position], right[position])
        for position in sorted(set(left) & set(right))
    ]


# --------------------------------------------------------------- O3: multiplicity


def _multiplicity(
    statements: Sequence[_Statement], names: Mapping[str, str]
) -> dict[tuple[str, tuple], list[dict]]:
    """O3: ``(entity, key columns) -> evidence`` for "this table holds many rows per key".

    A task that groups a table by ``k``, or ranks its rows within ``k``, is telling the
    reader that ``k`` does not identify a row of that table -- nobody deduplicates a
    table that is already unique. The claim is only made when every key of the grouping
    pierces to the same single table, because a GROUP BY over a join names no table's
    key set.
    """
    found: dict[tuple[str, tuple], list[dict]] = {}
    for statement in statements:
        for kind, scope_id, block_id, keys in _grouping_keys(statement.document):
            entity, columns = _single_table_keys(keys, names)
            if not entity or not columns:
                continue
            found.setdefault((entity, tuple(columns)), []).append(
                {
                    "task": statement.task,
                    "statement_id": statement.statement_id,
                    "kind": kind,
                    "scope_id": scope_id,
                    "logic_block_id": block_id,
                }
            )
    return found


def _grouping_keys(document: Mapping) -> list[tuple[str, str, str, list[dict]]]:
    """Every GROUP BY and every ranking PARTITION BY as ``(kind, scope, block, keys)``."""
    found: list[tuple[str, str, str, list[dict]]] = []
    for scope_id in document.get("scopes") or {}:
        keys = aggregation_keys(dict(document), str(scope_id))
        blocks = [
            str(block.get("logic_block_id"))
            for block in (document["scopes"][scope_id] or {}).get("logic_blocks") or []
            if str(block.get("logic_type")) == "group_by"
        ]
        if keys and blocks:
            found.append((EVIDENCE_GROUP_BY, str(scope_id), blocks[0], keys))
    found.extend(
        (EVIDENCE_WINDOW_PARTITION, scope_id, block_id, keys)
        for scope_id, block_id, keys in ranking_partition_keys(dict(document))
        if keys
    )
    return found


def _single_table_keys(
    keys: Sequence[Mapping], names: Mapping[str, str]
) -> tuple[str | None, list[str]]:
    """``(entity, columns)`` when every key pierces to one and the same table, else None."""
    entities: set[str] = set()
    columns: list[str] = []
    for key in keys:
        sources = key.get("physical_sources") or []
        if len(sources) != 1:
            return None, []
        entity = _entity_of(sources[0].get("table"), names)
        if not entity:
            return None, []
        entities.add(entity)
        columns.append(str(sources[0].get("column")))
    if len(entities) != 1 or not columns:
        return None, []
    return entities.pop(), _dedupe(columns)


def _joined_keys(edges: Sequence[Mapping]) -> dict[tuple[str, tuple], list[dict]]:
    """The key sets a task assumed unique by joining a table directly (O2's hypothesis).

    They are the entity's candidate keys at ``hypothesis`` tier: an author who writes
    ``LEFT JOIN t ON x.k = t.k`` and does not deduplicate ``t`` is asserting that ``t``
    is one row per ``k`` -- an assertion worth publishing and worth confirming, never
    worth believing on its own.
    """
    found: dict[tuple[str, tuple], list[dict]] = {}
    for relation in edges:
        if str((relation.get("cardinality") or {}).get("claim")) not in (
            CARDINALITY_MANY_TO_ONE,
            CARDINALITY_MANY_TO_ONE_ASSUMED,
        ):
            continue
        key = (str(relation["to"]["entity"]), tuple(relation["to"]["columns"]))
        found.setdefault(key, []).extend(
            {
                "task": item["task"],
                "statement_id": item["statement_id"],
                "kind": EVIDENCE_JOINED_AS_RIGHT,
                "logic_block_id": item.get("logic_block_id"),
            }
            for item in relation.get("evidence") or []
        )
    return found


# ------------------------------------------------------------------- O5: synonyms


def _synonyms(
    statements: Sequence[_Statement], names: Mapping[str, str]
) -> dict[tuple[str, str], list[dict]]:
    """O5: ``(entity, column) -> [the other columns proven to carry the same value]``."""
    found: dict[tuple[str, str], list[dict]] = {}
    for statement in statements:
        for left, right, via, tier in [
            *_rename_pairs(statement, names),
            *_union_synonym_pairs(statement, names),
        ]:
            evidence = {"task": statement.task, "statement_id": statement.statement_id}
            _record_synonym(found, left, right, via, tier, evidence)
            _record_synonym(found, right, left, via, tier, evidence)
    return found


def _record_synonym(
    found: dict[tuple[str, str], list[dict]],
    owner: tuple[str, str],
    other: tuple[str, str],
    via: str,
    tier: str,
    evidence: dict,
) -> None:
    entries = found.setdefault(owner, [])
    current = next(
        (
            item
            for item in entries
            if (item["entity"], item["column"], item["via"]) == (*other, via)
        ),
        None,
    )
    if current is None:
        entries.append(
            {
                "entity": other[0],
                "column": other[1],
                "tier": tier,
                "via": via,
                "evidence": [evidence],
            }
        )
        return
    if evidence not in current["evidence"]:
        current["evidence"].append(evidence)


def _rename_pairs(
    statement: _Statement, names: Mapping[str, str]
) -> list[tuple[tuple[str, str], tuple[str, str], str, str]]:
    """A DIRECT end-to-end field whose target column is named differently from its source.

    ``transform`` on the end-to-end entry is the LAST step, so DIRECT alone would admit
    a field that was aggregated and then passed through. The single physical source is
    required to carry DIRECT too, which is the shape the contract writes for a plain
    column carried to the target under another name.
    """
    target = _entity_of((statement.profile.get("task") or {}).get("target_table"), names)
    if not target:
        return []
    found = []
    for entry in statement.document.get("end_to_end_lineage") or []:
        sources = entry.get("physical_sources") or []
        if str(entry.get("transform")) != _DIRECT_TRANSFORM or len(sources) != 1:
            continue
        source = sources[0]
        column = str(entry.get("column") or "")
        entity = _entity_of(source.get("table"), names)
        if str(source.get("transform")) != _DIRECT_TRANSFORM or not entity or not column:
            continue
        if str(source.get("column")) == column:
            continue
        found.append(
            (
                (entity, str(source.get("column"))),
                (target, column),
                SYNONYM_DIRECT_RENAME,
                TIER_PROVEN,
            )
        )
    return found


def _union_synonym_pairs(
    statement: _Statement, names: Mapping[str, str]
) -> list[tuple[tuple[str, str], tuple[str, str], str, str]]:
    """Two differently named columns the same UNION position reads: the same attribute."""
    found = []
    for _scope_id, alignment in _union_alignments(statement.document):
        branches = _branch_columns(alignment)
        for index, (left_table, left_columns) in enumerate(branches):
            for right_table, right_columns in branches[index + 1 :]:
                left_entity = _entity_of(left_table, names)
                right_entity = _entity_of(right_table, names)
                if not left_entity or not right_entity:
                    continue
                found.extend(
                    (
                        (left_entity, left),
                        (right_entity, right),
                        SYNONYM_UNION_ALIGNMENT,
                        TIER_IMPLIED,
                    )
                    for left, right in _aligned_pairs(left_columns, right_columns)
                    if left != right
                )
    return found


# ----------------------------------------------------------------- O6: constraints


def _constraints(
    statements: Sequence[_Statement],
    cards: Mapping,
    values: Sequence[Mapping],
    names: Mapping[str, str],
) -> list[dict]:
    """O6: the four shapes the corpus can prove about a column or a table's rows."""
    constraints = [
        *_not_null_constraints(statements, names),
        *_in_set_constraints(values, names),
        *_partition_constraints(cards),
        *_unique_per_constraints(cards),
    ]
    return sorted(constraints, key=_constraint_sort_key)


def _constraint_sort_key(constraint: Mapping) -> tuple:
    target = constraint.get("target") or {}
    return (
        str(target.get("entity")),
        str(target.get("column") or ""),
        CONSTRAINT_KINDS.index(str(constraint["kind"])),
        tuple(constraint.get("columns") or []),
    )


def _constraint(kind: str, entity: str, column: str | None, tier: str, **extra) -> dict:
    target = {"entity": entity}
    if column:
        target["column"] = column
    built = {"target": target, "kind": kind, "tier": tier, **extra}
    return {key: built[key] for key in _CONSTRAINT_KEYS if key in built}


def _not_null_constraints(
    statements: Sequence[_Statement], names: Mapping[str, str]
) -> list[dict]:
    """``NOT x IS NULL`` in a WHERE: the task discarded NULLs, which is not a schema fact."""
    found: dict[tuple[str, str], dict] = {}
    for statement in statements:
        for rule in statement.profile.get("rules") or []:
            column = _not_null_column(rule)
            entity, name = _rule_column_owner(rule, column, names)
            if not entity or not name:
                continue
            evidence = {
                "task": statement.task,
                "statement_id": statement.statement_id,
                "rule_id": str(rule.get("rule_id") or ""),
                "logic_block_id": str(rule.get("evidence") or ""),
            }
            current = found.setdefault(
                (entity, name),
                _constraint(
                    CONSTRAINT_NOT_NULL,
                    entity,
                    name,
                    TIER_HYPOTHESIS,
                    note=NOT_NULL_NOTE,
                    evidence=[],
                ),
            )
            if evidence not in current["evidence"]:
                current["evidence"].append(evidence)
    return list(found.values())


def _not_null_column(rule: Mapping) -> str | None:
    """The column one conjunct tests for non-nullity, or None when it is not that test."""
    if str(rule.get("kind")) != "filter":
        return None
    node = semantic_text.parse_expression(rule.get("expression"))
    if not isinstance(node, exp.Not) or not isinstance(node.this, exp.Is):
        return None
    predicate = node.this
    if not isinstance(predicate.expression, exp.Null) or not isinstance(
        predicate.this, exp.Column
    ):
        return None
    return str(predicate.this.name)


def _rule_column_owner(
    rule: Mapping, column: str | None, names: Mapping[str, str]
) -> tuple[str | None, str | None]:
    """The entity one rule's named column belongs to, when exactly one field carries it."""
    if not column:
        return None, None
    fields = [
        field
        for field in rule.get("fields") or []
        if str(field.get("column")) == column and field.get("table")
    ]
    if len(fields) != 1:
        return None, None
    return _entity_of(fields[0].get("table"), names), column


def _in_set_constraints(
    values: Sequence[Mapping], names: Mapping[str, str]
) -> list[dict]:
    """The dictionary's enumerable codes, one constraint per column.

    Completeness is the dictionary's own ``closed_set`` claim and nothing weaker: an
    observed set is a floor, never a ceiling, so a column whose values were merely seen
    is published ``unknown`` at ``hypothesis`` tier. Only a closed ``IN`` list or an
    exhaustive CASE makes it ``complete``, and then the set is ``proven``.
    """
    grouped: dict[tuple[str, str], list[Mapping]] = {}
    for entry in values:
        if entry.get("logical") or not glossary_values.enumerable_code(entry):
            continue
        owner, _, column = str(entry.get("column_ref") or "").rpartition(".")
        entity = _entity_of(owner, names)
        if entity and column:
            grouped.setdefault((entity, column), []).append(entry)
    return [
        _in_set_constraint(entity, column, entries)
        for (entity, column), entries in grouped.items()
    ]


def _in_set_constraint(entity: str, column: str, entries: Sequence[Mapping]) -> dict:
    closed = all(entry.get("closed_set") for entry in entries)
    return _constraint(
        CONSTRAINT_IN_SET,
        entity,
        column,
        TIER_PROVEN if closed else TIER_HYPOTHESIS,
        values=sorted({str(entry.get("value")) for entry in entries}),
        completeness=COMPLETENESS_COMPLETE if closed else COMPLETENESS_UNKNOWN,
        evidence=_value_evidence(entries),
    )


def _value_evidence(entries: Sequence[Mapping]) -> list[dict]:
    seen: list[dict] = []
    for entry in entries:
        for observation in entry.get("observations") or []:
            item = {
                "task": str(observation.get("task") or ""),
                "statement_id": str(observation.get("statement_id") or ""),
                "context": str(observation.get("context") or ""),
            }
            if item not in seen:
                seen.append(item)
    return sorted(seen, key=lambda item: (item["task"], item["statement_id"], item["context"]))


def _partition_constraints(cards: Mapping) -> list[dict]:
    """A partition column is a metadata fact about the write, so it is ``proven``."""
    found = []
    for card in cards.get("tables") or []:
        for column in _partition_columns(card):
            found.append(
                _constraint(
                    CONSTRAINT_PARTITION,
                    str(card.get("table")),
                    column,
                    TIER_PROVEN,
                    evidence=_producer_evidence(card),
                )
            )
    return found


def _unique_per_constraints(cards: Mapping) -> list[dict]:
    """A produced table's identity: its candidate keys, per partition, at the card's tier."""
    found = []
    for card in cards.get("tables") or []:
        for producer in card.get("produced_by") or []:
            keys = [str(key) for key in producer.get("candidate_keys") or []]
            tier = KEY_CONFIDENCE_TIERS.get(str(producer.get("key_confidence")))
            if not keys or tier is None:
                continue
            found.append(
                _constraint(
                    CONSTRAINT_UNIQUE_PER,
                    str(card.get("table")),
                    None,
                    tier,
                    columns=_dedupe([*keys, *_partition(producer)]),
                    evidence=[
                        {
                            "task": str(producer.get("task")),
                            "statement_id": str(producer.get("statement_id")),
                            "kind": EVIDENCE_PRODUCER_KEY,
                            "basis": str(producer.get("key_confidence")),
                        }
                    ],
                )
            )
    return found


def _partition(producer: Mapping) -> list[str]:
    return [str(column) for column in (producer.get("partition") or {}).get("columns") or []]


def _partition_columns(card: Mapping) -> list[str]:
    return _dedupe(
        column for producer in card.get("produced_by") or [] for column in _partition(producer)
    )


def _producer_evidence(card: Mapping) -> list[dict]:
    return [
        {"task": str(item.get("task")), "statement_id": str(item.get("statement_id"))}
        for item in card.get("produced_by") or []
    ]


# -------------------------------------------------------------------- entities


def _entity(card: Mapping, facts: Mapping) -> dict:
    entity = str(card.get("table"))
    built = {
        "id": entity,
        "kind": ENTITY_PRODUCED if card.get("produced_by") else ENTITY_PHYSICAL,
        "comment": card.get("comment"),
        "identity": _identity(card, entity, facts),
        "attributes": [
            _attribute(entity, column, facts) for column in card.get("columns") or []
        ],
        "naming_hints": {
            "table_comment": card.get("comment"),
            "domain": card.get("domain"),
            "project": card.get("project"),
            "owner": card.get("owner"),
        },
    }
    return {key: built[key] for key in _ENTITY_KEYS}


def _identity(card: Mapping, entity: str, facts: Mapping) -> dict:
    """Candidate keys, multiplicity and partition columns side by side, never merged.

    They answer three different questions and one of them can be true while another is:
    a producing task proves its own output's key, a consuming task assumes an input's,
    and a third task's GROUP BY proves that the very same key set has many rows. Merging
    them into one "primary key" is exactly the guess this layer refuses to make.
    """
    return {
        "candidate_keys": _candidate_keys(card, entity, facts),
        "multiplicity": [
            {
                "columns": list(columns),
                "tier": TIER_IMPLIED,
                "claim": CLAIM_MULTIPLE_ROWS,
                "evidence": evidence,
            }
            for (owner, columns), evidence in sorted(facts["multiplicity"].items())
            if owner == entity
        ],
        "partition_columns": _partition_columns(card),
    }


def _candidate_keys(card: Mapping, entity: str, facts: Mapping) -> list[dict]:
    keys: dict[tuple, dict] = {}
    for producer in card.get("produced_by") or []:
        columns = tuple(str(key) for key in producer.get("candidate_keys") or [])
        tier = KEY_CONFIDENCE_TIERS.get(str(producer.get("key_confidence")))
        if not columns or tier is None:
            continue
        entry = keys.setdefault(
            columns, {"columns": list(columns), "tier": tier, "evidence": []}
        )
        entry["tier"] = _stronger_tier(entry["tier"], tier)
        entry["evidence"].append(
            {
                "task": str(producer.get("task")),
                "statement_id": str(producer.get("statement_id")),
                "kind": EVIDENCE_PRODUCER_KEY,
                "basis": str(producer.get("key_confidence")),
            }
        )
    for (owner, columns), evidence in sorted(facts["keys"].items()):
        if owner != entity or not columns:
            continue
        entry = keys.setdefault(
            columns, {"columns": list(columns), "tier": TIER_HYPOTHESIS, "evidence": []}
        )
        entry["evidence"].extend(item for item in evidence if item not in entry["evidence"])
    return [keys[columns] for columns in sorted(keys)]


def _stronger_tier(current: str, other: str) -> str:
    return min([current, other], key=TIERS.index)


def _attribute(entity: str, column: Mapping, facts: Mapping) -> dict:
    """One column, as the corpus saw it used -- never as a schema declares it.

    ``observed_roles`` is the card's own usage vocabulary (filter, join_key, group_by,
    window_partition, window_order, output, partition_filter) and nothing else, so a
    column no task read carries an empty list rather than an invented role.
    """
    name = str(column.get("name"))
    built = {
        "column": name,
        "type": column.get("type"),
        "comment": column.get("comment"),
        "observed_roles": list((column.get("consumer_usage_counts") or {}).keys()),
        "not_null_observed": (entity, name) in facts["not_null"],
        "synonyms": facts["synonyms"].get((entity, name)) or [],
    }
    return {key: built[key] for key in _ATTRIBUTE_KEYS}


# --------------------------------------------------------------------- O7: findings


def _findings(
    cards: Mapping, edges: Sequence[Mapping], multiplicity: Mapping
) -> list[dict]:
    """O7: where the corpus contradicts itself, and the card findings that carry over."""
    findings = [
        *_cardinality_conflicts(edges, multiplicity),
        *_card_findings(cards),
    ]
    ordered = sorted(
        findings,
        key=lambda item: (
            FINDING_KINDS.index(str(item["kind"])),
            str(item["entity"]),
            tuple(item["columns"]),
        ),
    )
    return [{key: item[key] for key in _FINDING_KEYS} for item in ordered]


def _cardinality_conflicts(
    edges: Sequence[Mapping], multiplicity: Mapping
) -> list[dict]:
    """One task deduplicated a table by ``k``; another joined it directly on ``k``.

    Both cannot be right about the same table: either the direct join multiplies rows
    nobody expected, or the dedup is dead weight. This is a governance finding rather
    than an ontology fact, which is why it is published here and not as a cardinality.
    """
    assumed = _assumed_unique(edges)
    findings = []
    for (entity, columns), evidence in sorted(multiplicity.items()):
        tasks = sorted({item["task"] for item in evidence})
        direct = sorted(assumed.get((entity, columns)) or [])
        if not direct:
            continue
        findings.append(
            {
                "kind": FINDING_CARDINALITY_CONFLICT,
                "entity": entity,
                "columns": list(columns),
                "tasks": {"multiple_rows_per_key": tasks, "assumed_unique": direct},
                "text": (
                    f"{'、'.join(tasks)} 先按 {'、'.join(columns)} 去重/聚合了 `{entity}`，"
                    f"{'、'.join(direct)} 直接以同一键关联它；"
                    "要么后者存在行数放大，要么前者的去重是多余的，请人工判定。"
                ),
            }
        )
    return findings


def _assumed_unique(edges: Sequence[Mapping]) -> dict[tuple[str, tuple], list[str]]:
    found: dict[tuple[str, tuple], list[str]] = {}
    for relation in edges:
        if str((relation.get("cardinality") or {}).get("claim")) != (
            CARDINALITY_MANY_TO_ONE_ASSUMED
        ):
            continue
        key = (str(relation["to"]["entity"]), tuple(relation["to"]["columns"]))
        found.setdefault(key, []).extend(
            str(item["task"]) for item in relation.get("evidence") or []
        )
    return {key: sorted(set(tasks)) for key, tasks in found.items()}


def _card_findings(cards: Mapping) -> list[dict]:
    """The two table-card findings an ontology reader has to see, carried over verbatim."""
    carried = (FINDING_PRODUCER_KEY_CONFLICT, FINDING_AMBIGUOUS_BARE_NAME)
    return [
        {
            "kind": str(finding["kind"]),
            "entity": str(card.get("table")),
            "columns": [],
            "tasks": {
                "reported_by": sorted(
                    {str(item.get("task")) for item in finding.get("evidence") or []}
                )
            },
            "text": str(finding.get("text") or ""),
        }
        for card in cards.get("tables") or []
        for finding in card.get("findings") or []
        if str(finding.get("kind")) in carried
    ]


# ------------------------------------------------------------------------- markdown


def render_ontology_index_markdown(ontology: Mapping) -> str:
    """``ontology.md``: the counts, then one row per relation.

    The minimum a reviewer needs to accept the JSON. WI-10 adds the per-entity cards and
    the Mermaid ER overview; the entry point is kept here so the caller does not change.
    """
    corpus = ontology.get("corpus") or {}
    entities = ontology.get("entities") or []
    relations = ontology.get("relations") or []
    findings = ontology.get("findings") or []
    lines = [
        "---",
        f'doc_format: "{INDEX_DOC_FORMAT}"',
        f"task_count: {corpus.get('task_count')}",
        f"entity_count: {len(entities)}",
        f"relation_count: {len(relations)}",
        "---",
        "",
        "# 语料本体候选索引",
        "",
        f"共 {corpus.get('task_count')} 个任务、{len(entities)} 个实体、"
        f"{len(relations)} 条关系、{len(ontology.get('constraints') or [])} 条约束、"
        f"{len(findings)} 条待人工判定的发现。",
        "",
        "每条断言都带置信层级：`proven`（SQL 直接写着）、`implied`（可由结构证明的推论）、"
        "`hypothesis`（作者假设，未被证明）、`conflict`（跨任务证据矛盾）。",
        "",
        "## 关系",
        "",
        "| 关系 | 从 | 到 | 类型 | 基数 | 层级 | 依据 | 任务数 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines.extend(_relation_row(relation) for relation in relations)
    lines.extend(_findings_section(findings))
    lines.append("")
    return "\n".join(lines)


def _relation_row(relation: Mapping) -> str:
    cardinality = relation.get("cardinality") or {}
    return (
        "| "
        + " | ".join(
            [
                cell(str(relation.get("id"))),
                cell(f"`{relation['from']['entity']}`.{_columns(relation['from'])}"),
                cell(f"`{relation['to']['entity']}`.{_columns(relation['to'])}"),
                cell(str(relation.get("kind"))),
                cell(str(cardinality.get("claim"))),
                cell(str(cardinality.get("tier"))),
                cell(str(cardinality.get("basis"))),
                cell(str(relation.get("task_count"))),
            ]
        )
        + " |"
    )


def _columns(side: Mapping) -> str:
    return "、".join(f"`{column}`" for column in side.get("columns") or []) or "—"


def _findings_section(findings: Sequence[Mapping]) -> list[str]:
    if not findings:
        return ["", "## 待人工判定", "", "本语料没有发现矛盾证据。"]
    lines = ["", "## 待人工判定", ""]
    lines.extend(
        f"- `{finding['entity']}`（{finding['kind']}）：{normalize_inline(finding['text'])}"
        for finding in findings
    )
    return lines


def _dedupe(items: Iterable) -> list:
    seen: list = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen
