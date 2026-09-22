"""K3: the relations between concepts, folded out of the table-level ones.

``ontology.relations[]`` answer "which two **tables** did some task join, on which
columns, and how many rows did that imply". That is the honest reading of a warehouse's
JOINs, and it is not the reading a business asks for. A business asks whether 「消息发送」
involves 「客户」 -- and in which role, 发送方 or 接收方 -- and whether 「客户日汇总」 is an
aggregate *of* the event or *of* the entity. Those are questions about K1's concepts, and
the table-level edges already carry the evidence to answer them.

This module folds each edge onto two concepts and groups the result by ``(from concept,
to concept)``. Four rules keep it a reading of the corpus rather than a new claim.

1. **The two ends answer two different questions.** The ``from`` end answers *what this
   table is*: the concept its own candidate key or declared hint placed it on -- never a
   ``reference`` membership a JOIN lent it, and never the columns this edge happened to
   join on. Reading the columns there folds every edge onto itself, because an event
   table joins 客户 *on* ``cust_no`` and is a ``reference`` member of 客户 for exactly
   that reason. The ``to`` end answers *what it points at*: the concept the join columns
   name (the same ``key_stem`` K1 seeds with, folded across the corpus's O5 synonyms),
   and only failing that the ``to`` table's own identity -- with one mirror of the same
   idea, that columns naming the very concept the ``from`` table *is* say nothing new,
   so a ``to`` table the corpus placed elsewhere wins over them and 客户 joined onto
   消息发送 is a participation written the other way round. An end that answers neither
   leaves the edge out, counted in ``concept_relations_unmapped`` under
   ``from_table_unplaced`` or ``to_table_unplaced``, because a wrong fold is worse than a
   missing one.
2. **The type is read off the two kinds**, never off a word: ``association`` between two
   entities, ``participation`` between an event and an entity, ``aggregation`` when a
   summary meets either, ``derivation`` between two of a kind that are not entities. A
   participation also publishes the ``roles`` the event gives the entity, taken from the
   ``from`` side's column comment and stripped exactly as a key comment is (发送方编号 →
   发送方), or from the column's own name when the metadata says nothing. One concept on
   both sides is a ``self_reference`` -- 上级客户 → 客户 is a relation the business has --
   unless the two *tables* are two representations of that one concept, which is a seam
   in K1's fold rather than a relation: those are published apart, in
   ``concept_representation_links[]``.
3. **The cardinality is the strongest member claim, and it says which.** Tier first
   (``proven`` outranks ``confirmed`` here: a claim the corpus proved outranks one a
   reviewer confirmed for a single pair of tables, because the fold is about the corpus),
   then definiteness, and ``basis`` names the edges that carried the winning claim.
   ``evidence[]`` is every member edge id and ``task_count`` the tasks behind them.
4. **Nothing is merged that K2 refused to merge.** A concept carrying
   ``possible_duplicate_of`` keeps its own relations on its own id: whether two stems are
   one thing is the review round's question, and answering it here would hide it.

Input is the ontology document being built -- its ``concepts``, its ``entities`` (read
only for the column comments and the synonym folding) and its ``relations``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .concepts import (
    BASIS_REFERENCE,
    CONCEPT_ENTITY,
    CONCEPT_EVENT,
    CONCEPT_SUMMARY,
    key_comment_name,
    key_stem,
    synonym_folding,
)

#: What one concept is to another.
TYPE_ASSOCIATION = "association"
TYPE_PARTICIPATION = "participation"
TYPE_AGGREGATION = "aggregation"
TYPE_DERIVATION = "derivation"
#: The same concept at both ends of a relation the business really has: 上级客户 → 客户.
TYPE_SELF_REFERENCE = "self_reference"

#: Publication order, strongest statement about the business first.
TYPE_ORDER = (
    TYPE_ASSOCIATION,
    TYPE_PARTICIPATION,
    TYPE_AGGREGATION,
    TYPE_DERIVATION,
    TYPE_SELF_REFERENCE,
)

#: The unordered pair of kinds → the type. Total over the six pairs three kinds make.
_TYPE_BY_KINDS = {
    frozenset({CONCEPT_ENTITY}): TYPE_ASSOCIATION,
    frozenset({CONCEPT_ENTITY, CONCEPT_EVENT}): TYPE_PARTICIPATION,
    frozenset({CONCEPT_SUMMARY, CONCEPT_ENTITY}): TYPE_AGGREGATION,
    frozenset({CONCEPT_SUMMARY, CONCEPT_EVENT}): TYPE_AGGREGATION,
    frozenset({CONCEPT_EVENT}): TYPE_DERIVATION,
    frozenset({CONCEPT_SUMMARY}): TYPE_DERIVATION,
}

#: Why an edge could not be folded. The ``from`` end is asked first, so an edge that
#: fails both is counted once, under the end that failed first.
UNMAPPED_FROM_TABLE = "from_table_unplaced"
UNMAPPED_TO_TABLE = "to_table_unplaced"
UNMAPPED_REASONS = (UNMAPPED_FROM_TABLE, UNMAPPED_TO_TABLE)

# Mirrors `ontology.TIERS` and `ontology.CARDINALITY_CLAIMS`, spelled here rather than
# imported because `ontology` imports this module; `tests/core/test_concept_relations.py`
# pins both equal. The tier *order* is deliberately not `ontology.TIERS`': see rule 3.
CARDINALITY_TIER_ORDER = ("proven", "confirmed", "implied", "hypothesis", "conflict")
#: Claims, most definite first; `unknown` is last, so a definite claim wins its tier.
CARDINALITY_CLAIMS = (
    "one_to_many",
    "many_to_one",
    "many_to_one_assumed",
    "one_to_one_assumed",
    "unknown",
)

CONCEPT_RELATION_KEYS = (
    "from",
    "to",
    "type",
    # Present on a `participation` only: what the entity is *to* the event.
    "roles",
    "cardinality",
    "task_count",
    "evidence",
)


@dataclass(frozen=True)
class _Context:
    """What placing one edge's two ends needs, read off the document once."""

    by_stem: Mapping[str, str]
    identity: Mapping[str, str]
    synonyms: Mapping[str, str]


# ------------------------------------------------------------------------ public API


def build_concept_relations(ontology: Mapping) -> dict:
    """The concept-level reading of ``relations[]``, and what it could not read.

    ``ontology`` is the document being built, after ``build_concepts`` attached the
    concept layer: the concepts, the entities their columns are described on, and the
    table-level relations this folds.
    """
    concepts = list(ontology.get("concepts") or [])
    entities = list(ontology.get("entities") or [])
    context = _Context(
        by_stem={
            stem: str(concept.get("id"))
            for concept in concepts
            for stem in _stems(concept)
        },
        identity=_identity_memberships(concepts),
        synonyms=synonym_folding(entities),
    )
    groups, seams, unmapped = _fold(ontology.get("relations") or [], context)
    kinds = {str(concept.get("id")): str(concept.get("kind")) for concept in concepts}
    comments = _column_comments(entities)
    built = [
        _concept_relation(pair, members, kinds, comments)
        for pair, members in groups.items()
    ]
    built.sort(key=_order)
    return {
        "concept_relations": built,
        "concept_representation_links": sorted(
            (_link(seam, members) for seam, members in seams.items()),
            key=lambda item: (item["concept"], item["from_table"], item["to_table"]),
        ),
        "concept_relations_unmapped": {
            "total": sum(unmapped.values()),
            "by_reason": {reason: unmapped[reason] for reason in UNMAPPED_REASONS},
        },
    }


# ------------------------------------------------------------ placing an endpoint


def _stems(concept: Mapping) -> list[str]:
    """Every key stem this concept answers to.

    Its own, plus whatever a reviewed ``concepts.overrides.json`` merged into it (K4b).
    A merge that moved the tables but not the stems would leave the far end of every
    edge that named the folded concept pointing at an id nothing publishes any more.
    """
    identity = concept.get("identity") or {}
    return [
        str(identity.get("stem")),
        *(str(item) for item in identity.get("merged_stems") or []),
    ]


def _identity_memberships(concepts: Sequence[Mapping]) -> dict[str, str]:
    """``{table: concept id}`` for the tables their own identity placed exactly once.

    A ``reference`` membership is the weakest one K1 publishes -- the table merely
    *carries* that key -- so it never stands in for what a table *is*. A table with two
    identity-backed memberships is left out: the rule exists because there was nothing
    to choose between, and choosing anyway would invent the answer.
    """
    found: dict[str, list[str]] = {}
    for concept in concepts:
        for item in concept.get("tables") or []:
            if str(item.get("membership_basis")) == BASIS_REFERENCE:
                continue
            found.setdefault(str(item.get("table")), []).append(str(concept.get("id")))
    return {table: ids[0] for table, ids in found.items() if len(ids) == 1}


def _fold(relations: Sequence[Mapping], context: _Context) -> tuple[dict, dict, dict]:
    """``(relation groups, representation seams, unmapped counts)`` over every edge."""
    groups: dict[tuple[str, str], list[Mapping]] = {}
    seams: dict[tuple[str, str, str], list[Mapping]] = {}
    unmapped = {reason: 0 for reason in UNMAPPED_REASONS}
    for relation in relations:
        source = context.identity.get(_table(relation, "from"))
        if source is None:
            unmapped[UNMAPPED_FROM_TABLE] += 1
            continue
        target = _to_endpoint(relation.get("to") or {}, source, context)
        if target is None:
            unmapped[UNMAPPED_TO_TABLE] += 1
            continue
        seam = _representation_seam(relation, source, target, context)
        if seam is not None:
            seams.setdefault(seam, []).append(relation)
            continue
        groups.setdefault((source, target), []).append(relation)
    return groups, seams, unmapped


def _to_endpoint(side: Mapping, source: str, context: _Context) -> str | None:
    """What this end points at: the concept its columns name, else what the table is.

    One exception, and it is the mirror of rule 1. When the columns name the very
    concept the ``from`` table *is*, they say nothing new -- the two tables share that
    key, which is why the JOIN could be written at all. If the corpus placed the ``to``
    table on some other concept, that is the answer: 客户 joined onto 消息发送 on
    ``cust_no`` is a participation written the other way round, not 客户 → 客户. A table
    that really is the same concept (a self-join, or a snapshot of it) has nothing else
    to reach for, and keeps what the stem said.
    """
    identity = context.identity.get(str(side.get("entity")))
    stems = {key_stem(str(column), context.synonyms) for column in side.get("columns") or []}
    named = context.by_stem.get(stems.pop()) if len(stems) == 1 else None
    if named is None:
        return identity
    if named == source and identity is not None and identity != source:
        return identity
    return named


def _representation_seam(
    relation: Mapping, source: str, target: str, context: _Context
) -> tuple[str, str, str] | None:
    """``(concept, from table, to table)`` when this edge is a seam in K1's fold.

    Two *tables* the corpus placed on one concept, joined to each other, say the two are
    the same thing -- a snapshot onto its primary. Publishing that as a relation would
    claim 客户 relates to 客户. A table joined to *itself* is the other case and stays a
    ``self_reference``: 上级客户 → 客户 is a relation the business has.
    """
    if source != target:
        return None
    tables = (_table(relation, "from"), _table(relation, "to"))
    if tables[0] == tables[1] or context.identity.get(tables[1]) != source:
        return None
    return (source, tables[0], tables[1])


def _table(relation: Mapping, side: str) -> str:
    return str((relation.get(side) or {}).get("entity"))


def _link(seam: tuple[str, str, str], members: Sequence[Mapping]) -> dict:
    concept, source, target = seam
    return {
        "concept": concept,
        "from_table": source,
        "to_table": target,
        "evidence": sorted(str(item.get("id")) for item in members),
    }


def _column_comments(entities: Sequence[Mapping]) -> dict[tuple[str, str], str]:
    return {
        (str(entity.get("id")), str(attribute.get("column"))): str(
            attribute.get("comment") or ""
        )
        for entity in entities
        for attribute in entity.get("attributes") or []
    }


# ------------------------------------------------------------- one concept relation


def _concept_relation(
    pair: tuple[str, str],
    members: Sequence[Mapping],
    kinds: Mapping[str, str],
    comments: Mapping[tuple[str, str], str],
) -> dict:
    source, target = pair
    kind_pair = frozenset({kinds.get(source, ""), kinds.get(target, "")})
    published = (
        TYPE_SELF_REFERENCE
        if source == target
        else _TYPE_BY_KINDS.get(kind_pair, TYPE_ASSOCIATION)
    )
    built = {
        "from": source,
        "to": target,
        "type": published,
        "cardinality": _cardinality(members),
        "task_count": _task_count(members),
        "evidence": sorted(str(item.get("id")) for item in members),
    }
    if published == TYPE_PARTICIPATION:
        built["roles"] = _roles(members, comments)
    return {key: built[key] for key in CONCEPT_RELATION_KEYS if key in built}


def _order(relation: Mapping) -> tuple:
    return (
        TYPE_ORDER.index(str(relation["type"])),
        str(relation["from"]),
        str(relation["to"]),
    )


def _cardinality(members: Sequence[Mapping]) -> dict:
    """The strongest claim the member edges made, and the edges that made it."""
    best = min(members, key=_claim_rank).get("cardinality") or {}
    claim = str(best.get("claim"))
    tier = str(best.get("tier"))
    return {
        "claim": claim,
        "tier": tier,
        "basis": sorted(
            str(item.get("id"))
            for item in members
            if str((item.get("cardinality") or {}).get("claim")) == claim
            and str((item.get("cardinality") or {}).get("tier")) == tier
        ),
    }


def _claim_rank(relation: Mapping) -> tuple:
    cardinality = relation.get("cardinality") or {}
    tier = str(cardinality.get("tier"))
    claim = str(cardinality.get("claim"))
    return (
        _index(CARDINALITY_TIER_ORDER, tier),
        _index(CARDINALITY_CLAIMS, claim),
        str(relation.get("id")),
    )


def _index(vocabulary: Sequence[str], value: str) -> int:
    """Where ``value`` sits, with anything unknown to this version sorted last."""
    return vocabulary.index(value) if value in vocabulary else len(vocabulary)


def _task_count(members: Sequence[Mapping]) -> int:
    """The tasks that WROTE the member edges, counted once each.

    The same discipline ``relations[].task_count`` keeps: a borrowed proof and a column
    comment are evidence carried on an edge, never another author of it.
    """
    return len(
        {
            str(item.get("task"))
            for relation in members
            for item in relation.get("evidence") or []
            if item.get("task") and not item.get("kind")
        }
    )


def _roles(
    members: Sequence[Mapping], comments: Mapping[tuple[str, str], str]
) -> list[str]:
    """What the entity is to the event, once per distinct answer.

    One group can hold several: 发送方编号 and 接收方编号 are the same fold of the same two
    concepts, and the roles are exactly what tells the two edges apart.
    """
    found = {_role(relation, comments) for relation in members}
    return sorted(text for text in found if text)


def _role(relation: Mapping, comments: Mapping[tuple[str, str], str]) -> str:
    side = relation.get("from") or {}
    table = str(side.get("entity"))
    columns = [str(column) for column in side.get("columns") or []]
    for column in columns:
        text = key_comment_name(comments.get((table, column), ""))
        if text:
            return text
    return columns[0] if columns else ""
