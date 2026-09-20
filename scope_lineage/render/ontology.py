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
from itertools import combinations

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
    CARD_DOC_FORMAT as TABLE_CARD_DOC_FORMAT,
)
from .table_cards import (
    FINDING_AMBIGUOUS_BARE_NAME,
    FINDING_PRODUCER_KEY_CONFLICT,
    build_table_cards,
    render_table_card_markdown,
    same_table,
    table_card_filename,
)

DOC_FORMAT = "ontology-json/1"
INDEX_DOC_FORMAT = "ontology-index-md/1"
# A table card the ontology appended its sections to is no longer a `tables-md/1`
# document: it carries five more sections and a different contract. It says so.
CARD_DOC_FORMAT = "ontology-md/1"

# P2: which keys of a semantic profile ``build_ontology`` reads *itself*, next to the
# code that reads them; `tests/core/test_corpus_cache_projection.py` fails until the two
# agree. The entity/relation half is read off the JOINs, so the profile answers for the
# rules and for which entity the statement writes -- everything else it needs comes from
# the table cards and the value dictionary underneath it.
#
# It is NOT the whole of what `scope-lineage ontology --incremental` stores: this command
# stacks three builders on one collected profile, and builds the cards from it whenever
# `--tables` was not supplied. Its runner therefore caches the union of this list and
# ``table_cards.PROFILE_FIELDS_READ`` (see ``corpus_cache.union_fields``), plus a second,
# glossary-projected profile when it has to build the dictionary as well.
PROFILE_FIELDS_READ = {
    "profile": ("artifact_kind",),
    "statement": {
        "statement_id": None,
        "task": ("task_name", "target_table"),
        "rules": None,
    },
}

# The five tiers, strongest first. Everything published carries exactly one of them.
# `confirmed` is the only one the corpus cannot produce: it arrives from a reviewed
# `ontology.overrides.json` and means a person answered the question.
TIER_CONFIRMED = "confirmed"
TIER_PROVEN = "proven"
TIER_IMPLIED = "implied"
TIER_HYPOTHESIS = "hypothesis"
TIER_CONFLICT = "conflict"

TIERS = (TIER_CONFIRMED, TIER_PROVEN, TIER_IMPLIED, TIER_HYPOTHESIS, TIER_CONFLICT)

# The markdown says the tier in Chinese; the JSON keeps the English token, because the
# JSON is what a knowledge graph loads and the markdown is what a person reads.
TIER_TEXT = {
    TIER_CONFIRMED: "已确认",
    TIER_PROVEN: "已证明",
    TIER_IMPLIED: "可推得",
    TIER_HYPOTHESIS: "作者假设",
    TIER_CONFLICT: "矛盾",
}

ENTITY_PHYSICAL = "physical_table"
ENTITY_PRODUCED = "produced_table"

RELATION_JOIN = "join_association"
RELATION_UNION = "union_sibling"

CARDINALITY_ONE_TO_MANY = "one_to_many"
CARDINALITY_MANY_TO_ONE = "many_to_one"
CARDINALITY_MANY_TO_ONE_ASSUMED = "many_to_one_assumed"
# The corpus never claims this one: a JOIN proves at most one side unique, so "one row
# each way" is something only a person can confirm. It exists so `--overrides` can say it.
CARDINALITY_ONE_TO_ONE_ASSUMED = "one_to_one_assumed"
CARDINALITY_UNKNOWN = "unknown"

CARDINALITY_CLAIMS = (
    CARDINALITY_ONE_TO_MANY,
    CARDINALITY_MANY_TO_ONE,
    CARDINALITY_MANY_TO_ONE_ASSUMED,
    CARDINALITY_ONE_TO_ONE_ASSUMED,
    CARDINALITY_UNKNOWN,
)

CARDINALITY_TEXT = {
    CARDINALITY_ONE_TO_MANY: "一对多",
    CARDINALITY_MANY_TO_ONE: "多对一",
    CARDINALITY_MANY_TO_ONE_ASSUMED: "多对一，作者假设",
    CARDINALITY_ONE_TO_ONE_ASSUMED: "一对一，作者假设",
    CARDINALITY_UNKNOWN: "未知",
}

# The ER symbols, read `from <symbol> to`. Mermaid writes the "many" crow's foot on the
# side that holds many rows, so `one_to_many` is `||--o{` and its mirror is `}o--||`.
CARDINALITY_MERMAID = {
    CARDINALITY_ONE_TO_MANY: "||--o{",
    CARDINALITY_MANY_TO_ONE: "}o--||",
    CARDINALITY_MANY_TO_ONE_ASSUMED: "}o--||",
    CARDINALITY_ONE_TO_ONE_ASSUMED: "||--||",
    CARDINALITY_UNKNOWN: "}o--o{",
}

# An ER diagram stops being readable long before it stops rendering. Past this many
# entities the overview keeps the best-connected ones and says how many it left out.
MERMAID_ENTITY_LIMIT = 60

# Why a cardinality is claimed. A token rather than a sentence: the JSON is read by
# machines, and the markdown renders the token into one line of Chinese.
BASIS_GROUP_BY = "group_by"
BASIS_RANKING_WINDOW = "ranking_window"
BASIS_PRODUCER_KEY = "producer_key_confidence"
BASIS_NO_DEDUP = "right_side_not_deduplicated"
BASIS_UNION_ALIGNMENT = "union_branch_alignment"
BASIS_NO_EVIDENCE = "no_uniqueness_evidence"
BASIS_HUMAN_CONFIRMATION = "human_confirmation"

# The markdown renders the token into one line of Chinese, so a reader never has to
# learn the vocabulary to know why a claim was made.
BASIS_TEXT = {
    BASIS_GROUP_BY: "关联前已按连接键聚合去重",
    BASIS_RANKING_WINDOW: "关联前已按连接键排名去重",
    BASIS_PRODUCER_KEY: "生产任务已证明该键唯一",
    BASIS_NO_DEDUP: "直接关联未去重，作者假设对端按该键唯一",
    BASIS_UNION_ALIGNMENT: "同一 UNION 的分支按列位置对齐",
    BASIS_NO_EVIDENCE: "语料内没有唯一性证据",
    BASIS_HUMAN_CONFIRMATION: "人工确认",
}

EVIDENCE_GROUP_BY = "group_by"
EVIDENCE_WINDOW_PARTITION = "window_partition"
EVIDENCE_JOINED_AS_RIGHT = "joined_as_right_without_dedup"
EVIDENCE_PRODUCER_KEY = "producer_key_confidence"
EVIDENCE_HUMAN_CONFIRMATION = "human_confirmation"
# H3: the catalog already answered part of the identity question, in prose, in the
# column comment. Reading past it and then asking a person is asking twice.
EVIDENCE_COLUMN_COMMENT = "column_comment"

# A column comment holding one of these calls its column a key. Lower-cased before the
# test, so `PRIMARY KEY` and `Unique` are the same phrase. The list is deliberately
# short: it is a *hint*, weighed against the corpus, never a claim on its own.
KEY_HINT_PHRASES = (
    "主键id",
    "主键",
    "唯一键",
    "唯一编号",
    "primary key",
    "unique",
)

# The fields an `ontology.overrides.json` entry may carry. Anything else is a typo or a
# convention this release does not know, and either way the reviewer has to be told
# rather than have it silently dropped (H2).
KEY_OVERRIDE_FIELDS = (
    "columns",
    "scope_columns",
    "basis",
    "note",
    "confirmed_by",
    "date",
)
RELATION_OVERRIDE_FIELDS = ("cardinality", "basis", "note", "confirmed_by", "date")

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

CONSTRAINT_TEXT = {
    CONSTRAINT_NOT_NULL: "非空",
    CONSTRAINT_IN_SET: "取值集合",
    CONSTRAINT_UNIQUE_PER: "每键唯一",
    CONSTRAINT_PARTITION: "分区列",
}

COMPLETENESS_COMPLETE = "complete"
COMPLETENESS_UNKNOWN = "unknown"

COMPLETENESS_TEXT = {
    COMPLETENESS_COMPLETE: "已封闭",
    COMPLETENESS_UNKNOWN: "是否完整未知",
}

SYNONYM_DIRECT_RENAME = "direct_rename"
SYNONYM_UNION_ALIGNMENT = "union_alignment"

SYNONYM_TEXT = {
    SYNONYM_DIRECT_RENAME: "直接改名投影",
    SYNONYM_UNION_ALIGNMENT: "UNION 同一位置",
}

FINDING_CARDINALITY_CONFLICT = "cardinality_conflict"
# H4: two authors assumed two different identities for one table. Publishing both with
# no word between them reads as "either is fine"; at most one of them is the key.
FINDING_COMPETING_CANDIDATE_KEYS = "competing_candidate_keys"
# H3: the column comment names one column the key and the corpus assumed another.
FINDING_KEY_HINT_CONFLICT = "key_hint_conflict"

FINDING_KINDS = (
    FINDING_CARDINALITY_CONFLICT,
    FINDING_COMPETING_CANDIDATE_KEYS,
    FINDING_KEY_HINT_CONFLICT,
    FINDING_PRODUCER_KEY_CONFLICT,
    FINDING_AMBIGUOUS_BARE_NAME,
)

# H5: one open question, whatever it is about. `finding` is a contradiction to resolve,
# `relation` an assumed cardinality, `candidate_key` an assumed identity.
OPEN_ITEM_FINDING = "finding"
OPEN_ITEM_RELATION = "relation"
OPEN_ITEM_KEY = "candidate_key"

OPEN_ITEM_TEXT = {
    OPEN_ITEM_FINDING: "发现",
    OPEN_ITEM_RELATION: "关系基数",
    OPEN_ITEM_KEY: "候选键",
}

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
    "open_items",
    "overrides_applied",
)
_ATTRIBUTE_KEYS = (
    "column",
    "type",
    "comment",
    "observed_roles",
    "used_in_corpus",
    "not_null_observed",
    "synonyms",
    # A6: present only when the card carries supplied sample values for this column.
    "samples",
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
_FINDING_KEYS = ("kind", "entity", "columns", "keys", "tasks", "text")
_OPEN_ITEM_KEYS = (
    "id",
    "kind",
    "entity",
    "relation",
    "columns",
    "tier",
    "write_back",
    "text",
)

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
    overrides: Mapping | None = None,
    artifact_root: str | None = None,
) -> dict:
    """Build one corpus's ontology candidate.

    ``documents`` are contract documents (1.0 statement or 2.0 task shape), exactly what
    ``tables`` and ``glossary`` read. ``profiles`` is one semantic profile per document
    in the same order, so a caller that already built them -- the CLI builds them once
    for all three corpus artifacts -- does not pay for them twice. ``tables`` and
    ``glossary`` are the two corpus documents this one is derived on top of; either is
    built in memory from the same corpus when it is not supplied. ``overrides`` is a
    reviewed ``ontology.overrides.json``: the answers a person gave to the hypotheses
    this document asked about, and the only way an assertion reaches ``confirmed``.
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
    entities = [_entity(card, facts) for card in cards.get("tables") or []]
    ontology = {
        "doc_format": DOC_FORMAT,
        "corpus": dict(cards.get("corpus") or {}),
        "entities": entities,
        "relations": _relations(edges),
        "constraints": constraints,
        "findings": _findings(cards, edges, facts["multiplicity"], entities),
        "open_items": [],
        "overrides_applied": {
            "relations": 0,
            "keys": 0,
            "unmatched": [],
            "ignored_fields": [],
        },
    }
    _apply_overrides(ontology, overrides or {})
    ontology["open_items"] = _open_items(ontology)
    return {key: ontology[key] for key in _ONTOLOGY_KEYS}


# ------------------------------------------------------------------- confirmations


def relation_override_key(relation: Mapping) -> str:
    """The stable name one relation answers to in ``ontology.overrides.json``.

    ``<from entity>.<col+col>-><to entity>.<col+col>``, exactly as the markdown prints
    it, so a reviewer copies the string out of the card instead of reconstructing it.
    """
    return (
        f"{relation['from']['entity']}.{'+'.join(relation['from']['columns'])}"
        f"->{relation['to']['entity']}.{'+'.join(relation['to']['columns'])}"
    )


def _apply_overrides(ontology: dict, overrides: Mapping) -> None:
    """Raise confirmed relations and keys to ``confirmed``; report what matched nothing.

    A confirmation is the one thing the corpus cannot derive and the only reason this
    document is worth reviewing twice: the hypotheses it publishes are questions, and an
    answered question must stop being asked. An override naming something the corpus does
    not contain is listed in ``overrides_applied.unmatched`` rather than dropped, because
    a typo in a reviewed file is exactly what a reviewer cannot see -- and H1 is why the
    *columns* are checked too: an override naming a column no entity carries used to be
    published as a ``confirmed`` candidate key, which is a typo at the strongest tier.
    """
    applied = ontology["overrides_applied"]
    columns = _entity_columns(ontology)
    _apply_relation_overrides(ontology, overrides.get("relations") or {}, applied, columns)
    _apply_key_overrides(ontology, overrides.get("keys") or {}, applied, columns)
    applied["unmatched"].sort(key=lambda item: (item["key"], item["reason"]))
    applied["ignored_fields"].sort(key=lambda item: item["key"])


def _entity_columns(ontology: Mapping) -> dict[str, set[str]]:
    """``entity -> every column name it carries``: declared, used, or already published."""
    found: dict[str, set[str]] = {}
    for entity in ontology.get("entities") or []:
        identity = entity.get("identity") or {}
        found[str(entity["id"])] = {
            *(str(item["column"]) for item in entity.get("attributes") or []),
            *(
                str(column)
                for key in identity.get("candidate_keys") or []
                for column in key["columns"]
            ),
            *(str(column) for column in identity.get("partition_columns") or []),
        }
    return found


def _apply_relation_overrides(
    ontology: dict, relations: Mapping, applied: dict, columns: Mapping[str, set[str]]
) -> None:
    index = {relation_override_key(item): item for item in ontology["relations"]}
    for name in sorted(relations):
        entry = dict(relations[name] or {})
        relation = index.get(str(name))
        if relation is None:
            applied["unmatched"].append(
                {"key": str(name), "reason": _relation_reason(str(name), columns)}
            )
            continue
        _record_ignored(applied, str(name), entry, RELATION_OVERRIDE_FIELDS)
        relation["cardinality"] = _confirmed_cardinality(relation["cardinality"], entry)
        applied["relations"] += 1


def _relation_reason(name: str, columns: Mapping[str, set[str]]) -> str:
    """Why one relation override matched nothing, as specifically as the string allows."""
    sides = name.split("->")
    if len(sides) != 2:
        return "unparsable_key"
    for side in sides:
        entity, _, joined = side.rpartition(".")
        if not entity or entity not in columns:
            return f"unknown_entity: {entity}" if entity else "unparsable_key"
        unknown = next(
            (item for item in joined.split("+") if item not in columns[entity]), None
        )
        if unknown is not None:
            return f"unknown_column: {unknown}"
    return "unknown_relation"


def _record_ignored(
    applied: dict, name: str, entry: Mapping, known: Sequence[str]
) -> None:
    """H2: a field this release does not read is reported, never dropped in silence."""
    extra = sorted(str(field) for field in entry if str(field) not in known)
    if extra:
        applied["ignored_fields"].append({"key": name, "fields": extra})


def _confirmed_cardinality(current: Mapping, entry: Mapping) -> dict:
    """The reviewed claim, or the corpus's own claim confirmed as it stands."""
    claim = str(entry.get("cardinality") or current.get("claim"))
    built = {
        "claim": claim if claim in CARDINALITY_CLAIMS else str(current.get("claim")),
        "tier": TIER_CONFIRMED,
        "basis": BASIS_HUMAN_CONFIRMATION,
    }
    return {**built, **_confirmation_stamp(entry)}


def _confirmation_stamp(entry: Mapping) -> dict:
    """Who answered, when, and on what grounds (H2).

    The reviewer's free-text ``basis`` is published as ``confirmed_basis`` because
    ``basis`` on a cardinality is a machine token from ``BASIS_TEXT``; one slot cannot
    be a vocabulary and a sentence at the same time.
    """
    stamp = {}
    for field, published in (
        ("confirmed_by", "confirmed_by"),
        ("date", "date"),
        ("basis", "confirmed_basis"),
        ("note", "note"),
    ):
        if entry.get(field):
            stamp[published] = str(entry[field])
    return stamp


def _apply_key_overrides(
    ontology: dict, keys: Mapping, applied: dict, columns: Mapping[str, set[str]]
) -> None:
    """Confirm one entity's identity key, adding it when the corpus never guessed it."""
    entities = {str(entity["id"]): entity for entity in ontology["entities"]}
    for name in sorted(keys):
        entry = dict(keys[name] or {})
        entity = entities.get(str(name))
        if entity is None:
            applied["unmatched"].append(
                {"key": str(name), "reason": f"unknown_entity: {name}"}
            )
            continue
        wanted = [str(column) for column in entry.get("columns") or []]
        scope = [str(column) for column in entry.get("scope_columns") or []]
        reason = _key_reason(wanted, scope, columns[str(name)])
        if reason:
            applied["unmatched"].append({"key": str(name), "reason": reason})
            continue
        _record_ignored(applied, str(name), entry, KEY_OVERRIDE_FIELDS)
        _confirm_key(entity, wanted, scope, entry)
        applied["keys"] += 1


def _key_reason(
    wanted: Sequence[str], scope: Sequence[str], carried: set[str]
) -> str | None:
    if not wanted:
        return "missing_columns"
    unknown = next(
        (column for column in [*wanted, *scope] if column not in carried), None
    )
    return f"unknown_column: {unknown}" if unknown is not None else None


def _confirm_key(
    entity: dict, columns: list[str], scope: list[str], entry: Mapping
) -> None:
    """Raise (or add) one candidate key at ``confirmed``, scoped when the answer was.

    ``scope_columns`` is the normal shape of a snapshot table: unique *within one* ``dt``
    and duplicated across them. Without the slot a reviewer had to answer "not unique",
    which is true and useless.
    """
    candidates = entity["identity"]["candidate_keys"]
    current = next(
        (item for item in candidates if list(item["columns"]) == columns), None
    )
    if current is None:
        current = {"columns": columns, "tier": TIER_CONFIRMED, "evidence": []}
        candidates.append(current)
        candidates.sort(key=lambda item: tuple(item["columns"]))
    current["tier"] = TIER_CONFIRMED
    if scope:
        evidence = current.pop("evidence")
        current["scope_columns"] = scope
        current["evidence"] = evidence
    stamp = {"kind": EVIDENCE_HUMAN_CONFIRMATION, **_confirmation_stamp(entry)}
    if stamp not in current["evidence"]:
        current["evidence"].append(stamp)


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
    return sorted(_merged_constraints(constraints), key=_constraint_sort_key)


def _merged_constraints(constraints: Sequence[Mapping]) -> list[dict]:
    """One entry per claim, however many statements proved it.

    ``unique_per`` is read off each producer in turn, so a table two tasks write with the
    same key set published that constraint twice -- identical but for its one evidence
    entry, and counted twice in 「共 N 条约束」. The claim is the target, the kind and the
    columns or values it names; everything else is how well it is known, which merges the
    way ``identity.candidate_keys`` already merges it: the strongest tier of the entries
    making the claim, and their evidence in corpus order.
    """
    merged: dict[tuple, dict] = {}
    for constraint in constraints:
        entry = merged.get(_constraint_identity(constraint))
        if entry is None:
            merged[_constraint_identity(constraint)] = dict(constraint)
            continue
        entry["tier"] = _stronger_tier(str(entry["tier"]), str(constraint["tier"]))
        evidence = list(entry.get("evidence") or [])
        for item in constraint.get("evidence") or []:
            if item not in evidence:
                evidence.append(item)
        entry["evidence"] = evidence
    return list(merged.values())


def _constraint_identity(constraint: Mapping) -> tuple:
    """What makes two constraints the same claim rather than two claims."""
    target = constraint.get("target") or {}
    return (
        str(target.get("entity")),
        str(target.get("column") or ""),
        str(constraint.get("kind")),
        tuple(str(item) for item in constraint.get("columns") or []),
        tuple(str(item) for item in constraint.get("values") or []),
    )


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
    keys = _candidate_keys(card, entity, facts)
    hints = _declared_hints(card)
    _agree_with_hints(keys, hints)
    return {
        "candidate_keys": keys,
        "declared_hints": hints,
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


def _declared_hints(card: Mapping) -> list[dict]:
    """H3: the column comments that call a column a key, exactly as the catalog wrote them.

    This is the ``declared`` evidence, and it is neither a candidate key nor proof: a
    comment can be stale, and a comment cannot say which *combination* identifies a row.
    It is published beside the corpus's own guesses so the two can be compared, and the
    comparison is what section 7 and the ``key_hint_conflict`` finding do.
    """
    return [
        {
            "columns": [str(column.get("name"))],
            "evidence": EVIDENCE_COLUMN_COMMENT,
            "text": str(column.get("comment")),
        }
        for column in card.get("columns") or []
        if _names_a_key(column.get("comment"))
    ]


def _names_a_key(comment) -> bool:
    text = str(comment or "").lower()
    return bool(text) and any(phrase in text for phrase in KEY_HINT_PHRASES)


def _agree_with_hints(keys: list[dict], hints: Sequence[Mapping]) -> None:
    """A comment and the corpus agreeing is one more tier than either one alone (H3).

    Two independent sources -- what the catalog declares and what the tasks do -- pointing
    at the same column is the definition of ``implied``: not written in the SQL, but not
    a bare assumption either.
    """
    for key in keys:
        if str(key["tier"]) != TIER_HYPOTHESIS:
            continue
        agreeing = [
            hint for hint in hints if set(hint["columns"]) <= set(key["columns"])
        ]
        if not agreeing:
            continue
        key["tier"] = TIER_IMPLIED
        for hint in agreeing:
            for column in hint["columns"]:
                evidence = {"kind": EVIDENCE_COLUMN_COMMENT, "column": str(column)}
                if evidence not in key["evidence"]:
                    key["evidence"].append(evidence)


def _attribute(entity: str, column: Mapping, facts: Mapping) -> dict:
    """One column, as the corpus saw it used -- never as a schema declares it.

    ``observed_roles`` is the card's own usage vocabulary (filter, join_key, group_by,
    window_partition, window_order, output, partition_filter) and nothing else, so a
    column no task read carries an empty list rather than an invented role.

    A1: every column the metadata declares is an attribute, whether or not the corpus
    touched it. ``used_in_corpus`` separates the two readings of an empty
    ``observed_roles`` -- "read, but never in a role this vocabulary names" from "the
    catalog declares it and no task in this corpus went near it".
    """
    name = str(column.get("name"))
    built = {
        "column": name,
        "type": column.get("type"),
        "comment": column.get("comment"),
        "observed_roles": list((column.get("consumer_usage_counts") or {}).keys()),
        "used_in_corpus": bool(column.get("used_in_corpus", True)),
        "not_null_observed": (entity, name) in facts["not_null"],
        "synonyms": facts["synonyms"].get((entity, name)) or [],
    }
    # A6: the card's supplied sample values, carried across unchanged. Absent when the
    # card has none, so an ontology built over a corpus with no samples file is the
    # document it always was.
    if column.get("samples"):
        built["samples"] = list(column["samples"])
    return {key: built[key] for key in _ATTRIBUTE_KEYS if key in built}


# --------------------------------------------------------------------- O7: findings


def _findings(
    cards: Mapping,
    edges: Sequence[Mapping],
    multiplicity: Mapping,
    entities: Sequence[Mapping],
) -> list[dict]:
    """O7: where the corpus contradicts itself, and the card findings that carry over."""
    findings = [
        *_cardinality_conflicts(edges, multiplicity),
        *_competing_candidate_keys(entities),
        *_key_hint_conflicts(entities),
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
    return [
        {key: item[key] for key in _FINDING_KEYS if key in item} for item in ordered
    ]


def _competing_candidate_keys(entities: Sequence[Mapping]) -> list[dict]:
    """H4: two authors assumed two different identities for the same table.

    A strict subset (``[id]`` against ``[id, dt]``) and two disjoint sets are the two
    shapes that cannot both be the identity: the first says the partition column is
    either needed or dead, the second says two tasks are modelling two different tables.
    Overlapping sets that are neither are left alone -- they may be two real keys.
    """
    findings = []
    for entity in entities:
        keys = [
            key
            for key in (entity.get("identity") or {}).get("candidate_keys") or []
            if str(key["tier"]) == TIER_HYPOTHESIS
        ]
        findings.extend(
            _competing_finding(entity, first, second)
            for first, second in combinations(keys, 2)
            if _competes(first, second)
        )
    return findings


def _competes(first: Mapping, second: Mapping) -> bool:
    left, right = set(first["columns"]), set(second["columns"])
    return left < right or right < left or not left & right


def _competing_finding(entity: Mapping, first: Mapping, second: Mapping) -> dict:
    sets = "；".join(
        "、".join(f"`{column}`" for column in key["columns"]) for key in (first, second)
    )
    return {
        "kind": FINDING_COMPETING_CANDIDATE_KEYS,
        "entity": str(entity["id"]),
        "columns": _dedupe([*first["columns"], *second["columns"]]),
        "keys": [
            {"columns": list(key["columns"]), "evidence": list(key["evidence"])}
            for key in (first, second)
        ],
        "tasks": {
            "assumed_unique": sorted(
                {
                    str(item["task"])
                    for key in (first, second)
                    for item in key["evidence"]
                    if item.get("task")
                }
            )
        },
        "text": (
            f"不同任务对 `{entity['id']}` 假设了两组不同的身份键：{sets}；"
            "至多一组是这张表的身份键，请人工判定哪一组成立。"
        ),
    }


def _key_hint_conflicts(entities: Sequence[Mapping]) -> list[dict]:
    """H3: the catalog names one column the key and every corpus guess names another."""
    findings = []
    for entity in entities:
        identity = entity.get("identity") or {}
        keys = list(identity.get("candidate_keys") or [])
        if not keys or any(str(key["tier"]) != TIER_HYPOTHESIS for key in keys):
            continue
        guessed = {str(column) for key in keys for column in key["columns"]}
        findings.extend(
            _key_hint_finding(entity, hint, keys)
            for hint in identity.get("declared_hints") or []
            if not set(hint["columns"]) & guessed
        )
    return findings


def _key_hint_finding(entity: Mapping, hint: Mapping, keys: Sequence[Mapping]) -> dict:
    hinted = "、".join(f"`{column}`" for column in hint["columns"])
    guessed = "；".join(
        "、".join(f"`{column}`" for column in key["columns"]) for key in keys
    )
    return {
        "kind": FINDING_KEY_HINT_CONFLICT,
        "entity": str(entity["id"]),
        "columns": list(hint["columns"]),
        "tasks": {},
        "text": (
            f"元数据注释称 {hinted} 为主键（{normalize_inline(str(hint['text']))}），"
            f"语料候选键为 {guessed}——两者不一致，请人工判定哪一个是身份键。"
        ),
    }


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


# ------------------------------------------------------------- H5: the open list


def _open_items(ontology: Mapping) -> list[dict]:
    """Every question this document still asks, once each, ranked by what it costs.

    Round one of a review reads five cards and answers four questions; round two has no
    way to tell what round one bought, because the questions live one card at a time.
    This list is that missing view: findings first (a contradiction is somebody's wrong
    number today), then the relations the most tasks depend on, then the identity keys.
    A confirmed assertion is simply not in it any more -- which is the whole point.
    """
    items = [
        *(_finding_item(finding) for finding in ontology.get("findings") or []),
        *_relation_items(ontology.get("relations") or []),
        *_key_items(ontology.get("entities") or []),
    ]
    return [{key: item[key] for key in _OPEN_ITEM_KEYS if key in item} for item in items]


def _key_item_id(entity: str, columns: Sequence[str]) -> str:
    """The list id one candidate-key question answers to, derived from the question."""
    return f"open:key:{entity}={'+'.join(str(column) for column in columns)}"


def _relation_item_id(relation: Mapping) -> str:
    return f"open:rel:{relation_override_key(relation)}"


def _finding_item_id(finding: Mapping) -> str:
    """Content-derived, so the same question keeps the same id in the next round.

    Competing key sets are part of the id rather than their union: three hypotheses over
    one table produce three pairs, and all three unions are the same column set.
    """
    sets = finding.get("keys")
    detail = (
        "~".join("+".join(str(column) for column in key["columns"]) for key in sets)
        if sets
        else "+".join(str(column) for column in finding.get("columns") or [])
    )
    name = f"open:finding:{finding['kind']}:{finding['entity']}"
    return f"{name}={detail}" if detail else name


def _finding_item(finding: Mapping) -> dict:
    # A hint conflict has exactly one answer shape -- "this column is the key, or it is
    # not" -- so it can name its write-back target. A contradiction between two tasks
    # cannot: answering it may confirm a key, a cardinality, or neither.
    write_back = (
        f"键:{finding['entity']}={'+'.join(str(item) for item in finding['columns'])}"
        if str(finding["kind"]) == FINDING_KEY_HINT_CONFLICT
        else None
    )
    return {
        "id": _finding_item_id(finding),
        "kind": OPEN_ITEM_FINDING,
        "entity": str(finding["entity"]),
        "columns": list(finding.get("columns") or []),
        "tier": TIER_CONFLICT,
        "write_back": write_back,
        "text": str(finding.get("text") or ""),
    }


def _relation_items(relations: Sequence[Mapping]) -> list[dict]:
    """One item per hypothesis edge -- not one per side, which is how a card reads it."""
    ordered = sorted(
        (
            relation
            for relation in relations
            if str((relation.get("cardinality") or {}).get("tier")) == TIER_HYPOTHESIS
        ),
        key=lambda item: (-int(item.get("task_count") or 0), relation_override_key(item)),
    )
    return [
        {
            "id": _relation_item_id(relation),
            "kind": OPEN_ITEM_RELATION,
            "entity": str(relation["from"]["entity"]),
            "relation": str(relation["id"]),
            "columns": list(relation["to"]["columns"]),
            "tier": TIER_HYPOTHESIS,
            "write_back": f"关系:{relation_override_key(relation)}",
            "text": _relation_question(relation),
        }
        for relation in ordered
    ]


def _key_items(entities: Sequence[Mapping]) -> list[dict]:
    return [
        {
            "id": _key_item_id(str(entity["id"]), key["columns"]),
            "kind": OPEN_ITEM_KEY,
            "entity": str(entity["id"]),
            "columns": list(key["columns"]),
            "tier": TIER_HYPOTHESIS,
            "write_back": f"键:{entity['id']}={'+'.join(key['columns'])}",
            "text": _key_question(key),
        }
        for entity in entities
        for key in (entity.get("identity") or {}).get("candidate_keys") or []
        if str(key["tier"]) == TIER_HYPOTHESIS
    ]


def _key_question(key: Mapping) -> str:
    columns = "、".join(f"`{column}`" for column in key["columns"])
    return f"候选键 {columns}：只有任务直接关联时的假设，语料没有证明它唯一。"


def _relation_question(relation: Mapping) -> str:
    cardinality = relation.get("cardinality") or {}
    claim = str(cardinality.get("claim"))
    basis = str(cardinality.get("basis"))
    return (
        f"关系 `{relation['from']['entity']}` → `{relation['to']['entity']}` "
        f"的基数写作「{CARDINALITY_TEXT.get(claim, claim)}」，依据只是"
        f"{BASIS_TEXT.get(basis, basis)}。"
    )


def _confirmed_count(ontology: Mapping) -> int:
    """How many assertions a person has answered so far -- the other half of the counter."""
    return sum(
        [
            sum(
                1
                for entity in ontology.get("entities") or []
                for key in (entity.get("identity") or {}).get("candidate_keys") or []
                if str(key["tier"]) == TIER_CONFIRMED
            ),
            sum(
                1
                for relation in ontology.get("relations") or []
                if str((relation.get("cardinality") or {}).get("tier")) == TIER_CONFIRMED
            ),
            sum(
                1
                for constraint in ontology.get("constraints") or []
                if str(constraint.get("tier")) == TIER_CONFIRMED
            ),
        ]
    )


# ------------------------------------------------------------------------- markdown


def render_ontology_index_markdown(ontology: Mapping) -> str:
    """``ontology.md``: the ER overview first, then the four tables behind it.

    A reader opens this file to find out which entity card is worth opening, so the
    diagram comes before the prose and every entity row links to its card. The diagram is
    a *summary* -- it carries the identity columns and the cardinality symbols, and the
    evidence behind each edge lives in the tables below and in the card itself.
    """
    corpus = ontology.get("corpus") or {}
    entities = list(ontology.get("entities") or [])
    relations = list(ontology.get("relations") or [])
    constraints = list(ontology.get("constraints") or [])
    findings = list(ontology.get("findings") or [])
    items = list(ontology.get("open_items") or [])
    identifiers = mermaid_entity_ids(entities)
    lines = [
        "---",
        f'doc_format: "{INDEX_DOC_FORMAT}"',
        f"task_count: {corpus.get('task_count')}",
        f"entity_count: {len(entities)}",
        f"relation_count: {len(relations)}",
        f"open_item_count: {len(items)}",
        "---",
        "",
        "# 语料本体候选索引",
        "",
        f"共 {corpus.get('task_count')} 个任务、{len(entities)} 个实体、"
        f"{len(relations)} 条关系、{len(constraints)} 条约束、"
        f"{len(findings)} 条矛盾发现；"
        f"待人工判定 {len(items)} 条（已确认 {_confirmed_count(ontology)} 条）。",
        "",
        "每条断言都带置信层级：`proven`（已证明，SQL 直接写着）、`implied`（可推得，"
        "由结构证明的推论）、`hypothesis`（作者假设，未被证明）、`conflict`（矛盾，"
        "跨任务证据打架）、`confirmed`（已确认，只来自人工回写的 `ontology.overrides.json`）。",
    ]
    lines.extend(_mermaid_section(entities, relations, findings, identifiers))
    lines.extend(_entities_section(entities, relations, constraints, identifiers))
    lines.extend(_relations_section(relations))
    lines.extend(_constraints_section(constraints))
    lines.extend(_findings_section(findings))
    lines.extend(_open_items_section(items))
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------- mermaid ER


def mermaid_entity_ids(entities: Sequence[Mapping]) -> dict[str, str]:
    """``entity id -> the identifier the ER diagram calls it``.

    Mermaid's entity names are identifiers, so a warehouse name has to be rewritten:
    every character outside ``[A-Za-z0-9_]`` becomes ``_``. Two different tables can
    rewrite to the same identifier (``a.b`` and ``a_b``), and then the later one -- in
    the corpus's own sorted order, so the choice cannot drift between runs -- takes a
    numeric suffix rather than silently merging two entities into one box.
    """
    identifiers: dict[str, str] = {}
    taken: set[str] = set()
    for entity in entities:
        name = str(entity.get("id"))
        base = "".join(
            char if char.isascii() and (char.isalnum() or char == "_") else "_"
            for char in name
        ) or "entity"
        if base[0].isdigit():
            base = f"e_{base}"
        candidate = base
        suffix = 2
        while candidate in taken:
            candidate = f"{base}_{suffix}"
            suffix += 1
        taken.add(candidate)
        identifiers[name] = candidate
    return identifiers


def _mermaid_section(
    entities: Sequence[Mapping],
    relations: Sequence[Mapping],
    findings: Sequence[Mapping],
    identifiers: Mapping[str, str],
) -> list[str]:
    if not entities:
        return ["", "## 实体关系总览", "", "本语料没有实体。"]
    shown = _diagram_entities(entities, relations)
    names = {str(entity.get("id")) for entity in shown}
    conflicted = _conflicted_pairs(findings)
    lines = ["", "## 实体关系总览", ""]
    omitted = len(entities) - len(shown)
    if omitted:
        lines.extend(
            [
                f"实体数 {len(entities)} 超过 {MERMAID_ENTITY_LIMIT}，"
                f"下图按关系度数取前 {MERMAID_ENTITY_LIMIT} 个实体，省略 {omitted} 个；"
                "完整清单见下面的实体表。",
                "",
            ]
        )
    lines.extend(["```mermaid", "erDiagram"])
    for entity in shown:
        lines.extend(_mermaid_entity(entity, identifiers))
    for relation in relations:
        left, right = str(relation["from"]["entity"]), str(relation["to"]["entity"])
        if left not in names or right not in names:
            continue
        lines.append(_mermaid_relation(relation, identifiers, conflicted))
    lines.extend(["```", ""])
    lines.append(
        "实体框里只列候选键列（标 `PK`），完整字段见每张表的卡片。边上的 `?` 表示这条基数"
        "只是作者假设、未被证明，`!` 表示语料里对这组键存在矛盾证据。"
    )
    return lines


def _diagram_entities(
    entities: Sequence[Mapping], relations: Sequence[Mapping]
) -> list[dict]:
    """Every entity, or the best-connected ``MERMAID_ENTITY_LIMIT`` of them."""
    if len(entities) <= MERMAID_ENTITY_LIMIT:
        return [dict(entity) for entity in entities]
    degree: dict[str, int] = {str(entity.get("id")): 0 for entity in entities}
    for relation in relations:
        for side in ("from", "to"):
            name = str(relation[side]["entity"])
            if name in degree:
                degree[name] += 1
    ranked = sorted(
        entities, key=lambda entity: (-degree[str(entity.get("id"))], str(entity.get("id")))
    )
    kept = {str(entity.get("id")) for entity in ranked[:MERMAID_ENTITY_LIMIT]}
    return [dict(entity) for entity in entities if str(entity.get("id")) in kept]


def _mermaid_entity(entity: Mapping, identifiers: Mapping[str, str]) -> list[str]:
    identity = entity.get("identity") or {}
    types = {
        str(attribute.get("column")): attribute.get("type")
        for attribute in entity.get("attributes") or []
    }
    columns = _dedupe(
        column
        for key in identity.get("candidate_keys") or []
        for column in key.get("columns") or []
    )
    name = identifiers[str(entity["id"])]
    # An entity with no candidate key is declared bare rather than with an empty block:
    # both parse, and the bare form does not invite the reader to read "{ }" as "no
    # columns" when the truth is "no column the corpus could prove identifies a row".
    if not columns:
        return [f"    {name}"]
    lines = [f"    {name} {{"]
    lines.extend(
        f"        {_mermaid_type(types.get(str(column)))} {_mermaid_word(column)} PK"
        for column in columns
    )
    lines.append("    }")
    return lines


def _mermaid_type(value) -> str:
    """A column type Mermaid can parse: one word, or ``unknown`` when there is none."""
    return _mermaid_word(value) if value else "unknown"


def _mermaid_word(value) -> str:
    word = "".join(
        char if char.isascii() and (char.isalnum() or char == "_") else "_"
        for char in str(value or "")
    )
    return word or "unknown"


def _mermaid_relation(
    relation: Mapping, identifiers: Mapping[str, str], conflicted: set[tuple[str, tuple]]
) -> str:
    cardinality = relation.get("cardinality") or {}
    symbol = CARDINALITY_MERMAID.get(str(cardinality.get("claim")), "}o--o{")
    marker = ""
    if str(cardinality.get("tier")) == TIER_HYPOTHESIS:
        marker = " ?"
    if (
        str(relation["to"]["entity"]),
        tuple(relation["to"]["columns"]),
    ) in conflicted:
        marker = f"{marker} !" if marker else " !"
    return (
        f"    {identifiers[str(relation['from']['entity'])]} {symbol} "
        f"{identifiers[str(relation['to']['entity'])]} : "
        f'"{_edge_label(relation)}{marker}"'
    )


def _edge_label(relation: Mapping) -> str:
    """The joined keys, ``a = b`` per aligned pair, so the edge says what it joins on."""
    left = [_mermaid_word(column) for column in relation["from"]["columns"]]
    right = [_mermaid_word(column) for column in relation["to"]["columns"]]
    if len(left) == len(right):
        return ", ".join(f"{a} = {b}" for a, b in zip(left, right))
    return f"{'+'.join(left)} = {'+'.join(right)}"


def _conflicted_pairs(findings: Sequence[Mapping]) -> set[tuple[str, tuple]]:
    return {
        (str(finding["entity"]), tuple(finding["columns"]))
        for finding in findings
        if str(finding["kind"]) == FINDING_CARDINALITY_CONFLICT
    }


# ------------------------------------------------------------------ index sections


def _entities_section(
    entities: Sequence[Mapping],
    relations: Sequence[Mapping],
    constraints: Sequence[Mapping],
    identifiers: Mapping[str, str],
) -> list[str]:
    if not entities:
        return ["", "## 实体", "", "本语料没有实体。"]
    outgoing: dict[str, int] = {}
    incoming: dict[str, int] = {}
    for relation in relations:
        outgoing[str(relation["from"]["entity"])] = (
            outgoing.get(str(relation["from"]["entity"]), 0) + 1
        )
        incoming[str(relation["to"]["entity"])] = (
            incoming.get(str(relation["to"]["entity"]), 0) + 1
        )
    counts: dict[str, int] = {}
    for constraint in constraints:
        name = str((constraint.get("target") or {}).get("entity"))
        counts[name] = counts.get(name, 0) + 1
    lines = [
        "",
        "## 实体",
        "",
        "| 实体 | 图中 id | 类型 | 注释 | 键置信 | 属性 | 出边 | 入边 | 约束数 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for entity in entities:
        name = str(entity.get("id"))
        lines.append(
            "| "
            + " | ".join(
                [
                    cell(f"[`{name}`](tables/{table_card_filename(name)})"),
                    cell(f"`{identifiers[name]}`"),
                    cell(str(entity.get("kind"))),
                    cell(normalize_inline(entity["comment"]) if entity.get("comment") else "—"),
                    cell(_key_tier_text(entity)),
                    cell(_attribute_count_text(entity)),
                    cell(str(outgoing.get(name, 0))),
                    cell(str(incoming.get(name, 0))),
                    cell(str(counts.get(name, 0))),
                ]
            )
            + " |"
        )
    return lines


def _attribute_count_text(entity: Mapping) -> str:
    """``12（语料用到 4）`` -- A1: the table's declared width beside what the corpus read.

    Without the second number a reader of an 88-column entity cannot tell a well-covered
    table from one this corpus barely touched, and both used to publish the same count.
    """
    attributes = entity.get("attributes") or []
    used = sum(1 for item in attributes if item.get("used_in_corpus", True))
    return f"{len(attributes)}（语料用到 {used}）"


def _key_tier_text(entity: Mapping) -> str:
    keys = (entity.get("identity") or {}).get("candidate_keys") or []
    if not keys:
        return "无候选键"
    tier = min((str(key.get("tier")) for key in keys), key=TIERS.index)
    return f"{TIER_TEXT.get(tier, tier)}（{tier}）"


def _relations_section(relations: Sequence[Mapping]) -> list[str]:
    if not relations:
        return ["", "## 关系", "", "本语料没有可证明的关系边。"]
    lines = [
        "",
        "## 关系",
        "",
        "| 关系 | 从 | 到 | 类型 | 基数 | 层级 | 依据 | 任务数 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines.extend(_relation_row(relation) for relation in relations)
    return lines


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


def _constraints_section(constraints: Sequence[Mapping]) -> list[str]:
    if not constraints:
        return ["", "## 约束", "", "本语料没有可证明的约束。"]
    lines = [
        "",
        "## 约束",
        "",
        "| 实体 | 目标 | 约束 | 内容 | 层级 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for constraint in constraints:
        target = constraint.get("target") or {}
        lines.append(
            "| "
            + " | ".join(
                [
                    cell(f"`{target.get('entity')}`"),
                    cell(f"`{target['column']}`" if target.get("column") else "整表"),
                    cell(_constraint_kind_text(constraint)),
                    cell(_constraint_body(constraint)),
                    cell(_tier_text(constraint.get("tier"))),
                ]
            )
            + " |"
        )
    return lines


def _constraint_kind_text(constraint: Mapping) -> str:
    kind = str(constraint.get("kind"))
    return f"{CONSTRAINT_TEXT.get(kind, kind)}（{kind}）"


def _constraint_body(constraint: Mapping) -> str:
    """The one cell that differs per constraint kind: the value set, or the key set."""
    if constraint.get("values") is not None:
        values = "、".join(f"`{value}`" for value in constraint["values"])
        completeness = str(constraint.get("completeness") or COMPLETENESS_UNKNOWN)
        return f"{values}（{COMPLETENESS_TEXT.get(completeness, completeness)}）"
    if constraint.get("columns"):
        return "、".join(f"`{column}`" for column in constraint["columns"])
    return normalize_inline(str(constraint.get("note") or "")) or "—"


def _tier_text(tier) -> str:
    """``已证明（`proven`）`` -- the Chinese for the reader, the token for a grep."""
    name = str(tier)
    return f"{TIER_TEXT.get(name, name)}（`{name}`）"


def _findings_section(findings: Sequence[Mapping]) -> list[str]:
    if not findings:
        return ["", "## 待人工判定", "", "本语料没有发现矛盾证据。"]
    lines = [
        "",
        "## 待人工判定",
        "",
        "| 实体 | 类型 | 列 | 涉及任务 | 说明 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for finding in findings:
        lines.append(
            "| "
            + " | ".join(
                [
                    cell(f"`{finding['entity']}`"),
                    cell(str(finding["kind"])),
                    cell("、".join(f"`{column}`" for column in finding["columns"]) or "—"),
                    cell(_finding_tasks(finding)),
                    cell(normalize_inline(str(finding.get("text") or ""))),
                ]
            )
            + " |"
        )
    return lines


def _open_items_section(items: Sequence[Mapping]) -> list[str]:
    """The consolidated list: what is still open, in the order it is worth answering."""
    if not items:
        return ["", "## 待人工判定清单（0 条）", "", "本语料没有待人工判定项。"]
    lines = [
        "",
        f"## 待人工判定清单（{len(items)} 条）",
        "",
        "矛盾与发现在前，其次是任务数多的关系，最后是候选键；`回写目标` 照抄进 "
        "`ontology.overrides.json` 即可，答完的条目下一轮不再出现。",
        "",
        "| # | id | 类型 | 实体 | 层级 | 回写目标 | 说明 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for index, item in enumerate(items, start=1):
        kind = str(item["kind"])
        lines.append(
            "| "
            + " | ".join(
                [
                    cell(str(index)),
                    cell(f"`{item['id']}`"),
                    cell(OPEN_ITEM_TEXT.get(kind, kind)),
                    cell(f"`{item['entity']}`"),
                    cell(_tier_text(item["tier"])),
                    cell(f"`{item['write_back']}`" if item.get("write_back") else "—"),
                    cell(normalize_inline(str(item.get("text") or ""))),
                ]
            )
            + " |"
        )
    return lines


def _finding_tasks(finding: Mapping) -> str:
    tasks = finding.get("tasks") or {}
    return (
        "；".join(
            f"{role}：{'、'.join(f'`{task}`' for task in names)}"
            for role, names in sorted(tasks.items())
            if names
        )
        or "—"
    )


# ---------------------------------------------------------------- per-entity cards


def render_ontology_table_card_markdown(card: Mapping, ontology: Mapping) -> str:
    """One table's card with the ontology's five sections appended (``ontology-md/1``).

    The card the corpus already writes answers "what is this table"; these sections
    answer "what is it in the model" -- its identity, what it relates to, what holds
    about its values, which other columns carry the same value, and what a person still
    has to decide. They are appended rather than published separately because a reader
    with a question about a table opens one file, and splitting the answer across two
    guarantees one of them is read without the other.
    """
    entity = _entity_by_id(ontology, str(card.get("table")))
    base = render_table_card_markdown(dict(card)).replace(
        f'doc_format: "{TABLE_CARD_DOC_FORMAT}"', f'doc_format: "{CARD_DOC_FORMAT}"', 1
    )
    lines = base.rstrip("\n").split("\n")
    sections = (
        ("7. 身份（本体）", _card_identity(entity)),
        ("8. 关系", _card_relations(entity, ontology)),
        ("9. 约束", _card_constraints(entity, ontology)),
        ("10. 属性同义", _card_synonyms(entity)),
        ("11. 待人工判定", _card_open_items(entity, ontology)),
    )
    for title, body in sections:
        lines.extend(["", f"## {title}", ""])
        lines.extend(body)
    lines.append("")
    return "\n".join(lines)


def _entity_by_id(ontology: Mapping, table: str) -> dict:
    for entity in ontology.get("entities") or []:
        if str(entity.get("id")) == table:
            return dict(entity)
    return {"id": table, "identity": {}, "attributes": []}


def _evidence_ids(evidence: Sequence[Mapping]) -> str:
    """``task/statement/logic block`` per item -- every id a reader can look up."""
    ids = [
        "/".join(
            str(item[key])
            for key in ("task", "statement_id", "rule_id", "scope_id", "logic_block_id")
            if item.get(key)
        )
        or str(item.get("kind") or "")
        for item in evidence or []
    ]
    return "、".join(f"`{item}`" for item in _dedupe(ids) if item) or "—"


def _claim_line(text: str, tier, evidence: Sequence[Mapping]) -> str:
    return f"- {text} — {_tier_text(tier)}；证据 {_evidence_ids(evidence)}"


def _key_line(key: Mapping) -> str:
    """One candidate key, its scope when it has one, and who confirmed it (H2)."""
    columns = "、".join(f"`{column}`" for column in key["columns"])
    scope = key.get("scope_columns") or []
    if scope:
        columns += "（在 " + "、".join(f"`{column}`" for column in scope) + " 内唯一）"
    evidence = key.get("evidence") or []
    return _claim_line(columns, key.get("tier"), evidence) + _confirmation_text(evidence)


def _confirmation_text(evidence: Sequence[Mapping]) -> str:
    """``；确认人 X、确认日期 Y、依据 Z`` -- an answer without its basis is a rumour."""
    stamp = next(
        (
            item
            for item in evidence
            if str(item.get("kind")) == EVIDENCE_HUMAN_CONFIRMATION
        ),
        None,
    )
    parts = [
        f"{label}{normalize_inline(str(stamp[field]))}"
        for field, label in (
            ("confirmed_by", "确认人 "),
            ("date", "确认日期 "),
            ("confirmed_basis", "依据 "),
        )
        if stamp and stamp.get(field)
    ]
    return "；" + "、".join(parts) if parts else ""


def _hint_lines(hints: Sequence[Mapping]) -> list[str]:
    """H3: what the catalog already says about identity, beside what the corpus guessed."""
    lines = ["", "**元数据键线索**", ""]
    if not hints:
        return [*lines, "- 元数据注释没有把任何列称作主键或唯一键。"]
    lines.extend(
        "- "
        + "、".join(f"`{column}`" for column in hint["columns"])
        + f" — 列注释：{normalize_inline(str(hint['text']))}"
        + "（元数据线索，不是语料证据）"
        for hint in hints
    )
    return lines


def _card_identity(entity: Mapping) -> list[str]:
    """Candidate keys, multiplicity and partition columns -- three answers, never merged."""
    identity = entity.get("identity") or {}
    keys = identity.get("candidate_keys") or []
    multiplicity = identity.get("multiplicity") or []
    partitions = identity.get("partition_columns") or []
    lines = [f"- 属性 {_attribute_count_text(entity)}", "", "**候选键**", ""]
    if keys:
        lines.extend(_key_line(key) for key in keys)
    else:
        lines.append("- 语料内没有可发布的候选键证据。")
    lines.extend(_hint_lines(identity.get("declared_hints") or []))
    lines.extend(["", "**多行性**", ""])
    if multiplicity:
        lines.extend(
            _claim_line(
                "按 " + "、".join(f"`{column}`" for column in item["columns"]) + " 有多行",
                item.get("tier"),
                item.get("evidence") or [],
            )
            for item in multiplicity
        )
    else:
        lines.append("- 语料内没有任务按某个键对这张表去重或聚合。")
    lines.extend(["", "**分区列**", ""])
    if partitions:
        columns = "、".join(f"`{column}`" for column in partitions)
        lines.append(f"- {columns} — {_tier_text(TIER_PROVEN)}")
    else:
        lines.append("- 语料内没有观察到分区列。")
    return lines


def _card_relations(entity: Mapping, ontology: Mapping) -> list[str]:
    name = str(entity.get("id"))
    relations = list(ontology.get("relations") or [])
    outgoing = [item for item in relations if str(item["from"]["entity"]) == name]
    incoming = [item for item in relations if str(item["to"]["entity"]) == name]
    lines = ["**出边（本表在左）**", ""]
    lines.extend(_relation_table(outgoing, "from", "to"))
    lines.extend(["", "**入边（本表在右）**", ""])
    lines.extend(_relation_table(incoming, "to", "from"))
    return lines


def _relation_table(relations: Sequence[Mapping], own: str, other: str) -> list[str]:
    if not relations:
        return ["- 无。"]
    lines = [
        "| 对端 | 键 | JOIN 类型 | 基数 | 层级 | 依据 | 任务数 | 证据 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for relation in relations:
        cardinality = relation.get("cardinality") or {}
        claim = str(cardinality.get("claim"))
        basis = str(cardinality.get("basis"))
        keys = "、".join(
            f"`{left}` = `{right}`"
            for left, right in zip(relation[own]["columns"], relation[other]["columns"])
        ) or "—"
        lines.append(
            "| "
            + " | ".join(
                [
                    cell(
                        f"[`{relation[other]['entity']}`]"
                        f"({table_card_filename(str(relation[other]['entity']))})"
                    ),
                    cell(keys),
                    cell("、".join(relation.get("join_types") or []) or "—"),
                    cell(f"{CARDINALITY_TEXT.get(claim, claim)}（{claim}）"),
                    cell(_tier_text(cardinality.get("tier"))),
                    cell(BASIS_TEXT.get(basis, basis)),
                    cell(str(relation.get("task_count"))),
                    cell(_evidence_ids(relation.get("evidence") or [])),
                ]
            )
            + " |"
        )
    return lines


def _card_constraints(entity: Mapping, ontology: Mapping) -> list[str]:
    name = str(entity.get("id"))
    constraints = [
        item
        for item in ontology.get("constraints") or []
        if str((item.get("target") or {}).get("entity")) == name
    ]
    if not constraints:
        return ["- 语料内没有可发布的约束。"]
    lines = [
        "| 约束 | 目标 | 值集 / 完整性 | 层级 | 证据 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for constraint in constraints:
        target = constraint.get("target") or {}
        body = _constraint_body(constraint)
        note = normalize_inline(str(constraint.get("note") or ""))
        lines.append(
            "| "
            + " | ".join(
                [
                    cell(_constraint_kind_text(constraint)),
                    cell(f"`{target['column']}`" if target.get("column") else "整表"),
                    cell(f"{body}（{note}）" if note and body != note else body),
                    cell(_tier_text(constraint.get("tier"))),
                    cell(_evidence_ids(constraint.get("evidence") or [])),
                ]
            )
            + " |"
        )
    return lines


def _card_synonyms(entity: Mapping) -> list[str]:
    rows = [
        (str(attribute.get("column")), synonym)
        for attribute in entity.get("attributes") or []
        for synonym in attribute.get("synonyms") or []
    ]
    if not rows:
        return ["- 语料内没有证明本表任何列与别处同名异写。"]
    lines = [
        "| 本表列 | 同义列 | 依据 | 层级 | 证据 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for column, synonym in rows:
        via = str(synonym.get("via"))
        lines.append(
            "| "
            + " | ".join(
                [
                    cell(f"`{column}`"),
                    cell(f"`{synonym['entity']}`.`{synonym['column']}`"),
                    cell(f"{SYNONYM_TEXT.get(via, via)}（{via}）"),
                    cell(_tier_text(synonym.get("tier"))),
                    cell(_evidence_ids(synonym.get("evidence") or [])),
                ]
            )
            + " |"
        )
    return lines


def _card_open_items(entity: Mapping, ontology: Mapping) -> list[str]:
    """Every hypothesis about this table, plus the findings, as one list of questions.

    A hypothesis is a question the corpus asked and could not answer, and it stays a
    question until a person answers it in ``ontology.overrides.json``. Listing them
    together -- with the override key each answer is filed under -- is what turns the
    document from a report into a round trip.
    """
    name = str(entity.get("id"))
    lines: list[str] = []
    lines.extend(
        f"- ⚠ {finding['kind']}：{normalize_inline(str(finding.get('text') or ''))}"
        f"{_cites(_finding_item_id(finding))}"
        for finding in ontology.get("findings") or []
        if str(finding.get("entity")) == name
    )
    identity = entity.get("identity") or {}
    for key in identity.get("candidate_keys") or []:
        if str(key.get("tier")) != TIER_HYPOTHESIS:
            continue
        lines.append(
            f"- [待确认] {_key_question(key)}"
            f"回写 `键:{name}={'+'.join(key['columns'])}`。"
            f"{_cites(_key_item_id(name, key['columns']))}"
        )
    for relation in ontology.get("relations") or []:
        if name not in (str(relation["from"]["entity"]), str(relation["to"]["entity"])):
            continue
        if str((relation.get("cardinality") or {}).get("tier")) != TIER_HYPOTHESIS:
            continue
        lines.append(
            f"- [待确认] {_relation_question(relation)}"
            f"回写 `关系:{relation_override_key(relation)}`。"
            f"{_cites(_relation_item_id(relation))}"
        )
    for constraint in ontology.get("constraints") or []:
        target = constraint.get("target") or {}
        if str(target.get("entity")) != name or str(constraint.get("tier")) != TIER_HYPOTHESIS:
            continue
        lines.append(
            f"- [待确认] {_constraint_kind_text(constraint)}"
            f"{'：`' + str(target['column']) + '`' if target.get('column') else ''}"
            f" — {_constraint_body(constraint)}"
            f"{'；' + normalize_inline(str(constraint['note'])) if constraint.get('note') else ''}"
        )
    return lines or ["- 本表没有待人工判定的项。"]


def _cites(item_id: str) -> str:
    """The card asks the question; the index's list is where the count of them lives."""
    return f"（清单 `{item_id}`）"


def _dedupe(items: Iterable) -> list:
    seen: list = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen
