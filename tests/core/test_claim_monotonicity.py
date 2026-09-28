"""More evidence never makes a conclusion stronger than it was (WP4, monotonicity).

A corpus that proves a key and a safe JOIN is given one more task at a time: a producer
that appends to the same table, a producer that writes it by another key, a task that
filters the same column. Each conclusion drawn over the corpus -- the consumer's JOIN
verdict, the card's claim, the ontology's relation, ``unique_per`` and identity tiers,
the glossary's closed set -- may stay or weaken, never strengthen. And the added task
must weaken at least one of them: otherwise the corpus never used what it was told,
which is how ``producer_key_conflict`` sat on a card while the key stayed proven (F2).
"""

from __future__ import annotations

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render import claims
from scope_lineage.render.glossary import apply_glossary, build_glossary
from scope_lineage.render.ontology import build_ontology
from scope_lineage.render.semantic_profile import build_semantic_profile, card_key_claim
from scope_lineage.render.table_cards import build_table_cards
from scope_lineage.scope.scope_builder import parse_scope_lineage

from .claim_witness import schema_map

PRODUCER = "CREATE TABLE mart.dim AS SELECT id, MAX(v) AS v, 1 AS dt FROM ods.e GROUP BY id"
CONSUMER = (
    "INSERT OVERWRITE TABLE mart.t "
    "SELECT b.rid, b.id, d.v FROM ods.base b LEFT JOIN mart.dim d ON b.id = d.id"
)
READER = "INSERT OVERWRITE TABLE mart.r SELECT e.id FROM ods.e e WHERE e.id IN (1, 2)"
BASE = [("producer", PRODUCER), ("consumer", CONSUMER), ("reader", READER)]

ADDITIONS = {
    "appending producer": (
        "appender",
        "INSERT INTO mart.dim SELECT id, MAX(v) AS v, 1 AS dt FROM ods.e GROUP BY id",
    ),
    "producer with another key": (
        "rewriter",
        "INSERT OVERWRITE TABLE mart.dim SELECT id, v, dt FROM ods.e",
    ),
    "task filtering the same column": (
        "narrower",
        "INSERT OVERWRITE TABLE mart.n SELECT e.id FROM ods.e e WHERE e.id IN (3)",
    ),
}

TIER_ORDER = ("proven", "confirmed", "implied", "hypothesis", "conflict")
WEAKEST = 99


def _tier(value: str | None) -> int:
    return TIER_ORDER.index(value) if value in TIER_ORDER else WEAKEST


def _conclusions(tasks) -> dict[str, int]:
    """Each conclusion as a rank: lower is stronger, ``WEAKEST`` is none at all."""
    documents = [
        to_lineage_dict(parse_scope_lineage(sql, task, schema=schema_map()))
        for task, sql in tasks
    ]
    profiles = [build_semantic_profile(document) for document in documents]
    cards = build_table_cards(profiles)
    ontology = build_ontology(documents, profiles, tables=cards, artifact_root="corpus")
    glossary = build_glossary(documents, artifact_root="corpus")

    consumer = next(document for document in documents if document["task_id"] == "consumer")
    risks = build_semantic_profile(consumer, table_cards=cards)["output_shape"][
        "fan_out_risks"
    ]
    claim = card_key_claim(next(item for item in cards["tables"] if item["table"] == "mart.dim"))
    relation = next(
        (
            item
            for item in ontology["table_relations"]
            if item["to"]["entity"] == "mart.dim"
        ),
        None,
    )
    unique_per = [
        item
        for item in ontology["constraints"]
        if item["kind"] == "unique_per" and item["target"]["entity"] == "mart.dim"
    ]
    identity = next(item for item in ontology["tables"] if item["id"] == "mart.dim")[
        "identity"
    ]["candidate_keys"]
    reader = next(document for document in documents if document["task_id"] == "reader")
    domain = next(
        item
        for item in apply_glossary(build_semantic_profile(reader), glossary)["fields"]
        if item["column"] == "id"
    ).get("value_domain") or []
    return {
        "join verdict": 0 if risks and risks[0]["status"] == "safe" else 1,
        "card claim": claims.STATUSES.index(claim.status) if claim else WEAKEST,
        "relation tier": _tier((relation or {}).get("cardinality", {}).get("tier")),
        "unique_per tier": min((_tier(item["tier"]) for item in unique_per), default=WEAKEST),
        "identity tier": min((_tier(item["tier"]) for item in identity), default=WEAKEST),
        "closed set": 0 if domain and all(item["closed_set"] for item in domain) else 1,
    }


BEFORE = _conclusions(BASE)


def test_the_base_corpus_starts_from_strong_conclusions() -> None:
    """Otherwise nothing could weaken and the property below would hold vacuously."""
    assert BEFORE == {
        "join verdict": 0,
        "card claim": 0,
        "relation tier": 0,
        "unique_per tier": 0,
        "identity tier": 0,
        "closed set": 0,
    }


@pytest.mark.parametrize("addition", ADDITIONS, ids=list(ADDITIONS))
def test_one_more_task_never_strengthens_a_conclusion(addition: str) -> None:
    after = _conclusions([*BASE, ADDITIONS[addition]])

    strengthened = {name: (BEFORE[name], after[name]) for name in BEFORE if after[name] < BEFORE[name]}
    assert not strengthened
    assert any(after[name] > BEFORE[name] for name in BEFORE), after
