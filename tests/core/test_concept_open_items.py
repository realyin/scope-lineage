"""N3: the open questions folded once more, at the level the answer is actually true.

Q3 folded the open list by table family, which merges the copies of one logical table --
``_di``, ``_df``, ``_hi`` -- and nothing else. A concept is wider than a family: five
tables can represent one business thing under five unrelated names, each carrying the
same candidate key spelled its own way, and the table-level list then asks a reviewer
「这张表按这组列唯一吗」 five times. The five answers are one answer, because identity is
a property of the *concept*, not of the copy.

So ``concept_open_items[]`` folds the same list by (concept, question shape): the key
stems for an identity question, the far concept and its stems for a relation, the finding
kind for a contradiction. One item carries the table-level ids it folds, the tables it
covers, and the list of table-level write-back keys one concept answer expands to -- and
``ontology.overrides.json`` grows a ``concepts`` section so the reviewer writes that
answer once and the tool does the expanding.

Every table, column, comment and reviewer name below is synthetic.
"""

from __future__ import annotations

import json

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.ontology import (
    CARDINALITY_MANY_TO_ONE,
    CONCEPT_KEY_WRITE_BACK,
    CONCEPT_RELATION_WRITE_BACK,
    FINDING_KEY_HINT_CONFLICT,
    OPEN_ITEM_FINDING,
    OPEN_ITEM_KEY,
    OPEN_ITEM_RELATION,
    TIER_CONFIRMED,
    TIER_CONFLICT,
    TIER_HYPOTHESIS,
    build_ontology,
    render_concept_markdown,
    render_ontology_index_markdown,
)
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.render.table_cards import build_table_cards
from scope_lineage.scope.scope_builder import parse_scope_lineage


# --------------------------------------------------------------- the synthetic corpus

_PARTY_COLUMNS = [
    {"name": "party_id", "type": "bigint", "comment": "合成客户号"},
    {"name": "party_code", "type": "string", "comment": "合成客户编码"},
    {"name": "party_name", "type": "string", "comment": "合成名称"},
    {"name": "dt", "type": "string", "comment": "合成分区日"},
]
# The same concept spelled with a different key column: `party_no` and `party_id` reduce
# to one stem, which is exactly what the table-family fold can never see.
_PARTY_NO_COLUMNS = [
    {"name": "party_no", "type": "bigint", "comment": "合成客户号"},
    {"name": "party_name", "type": "string", "comment": "合成名称"},
    {"name": "dt", "type": "string", "comment": "合成分区日"},
]
# A column comment calling a *different* column the key: one `key_hint_conflict` per
# table it sits on, and two of them are one question about the concept.
_HINTED_PARTY_COLUMNS = [
    {**column, "comment": "合成主键编码"} if column["name"] == "party_code" else column
    for column in _PARTY_COLUMNS
]

# Five representations, none of them a suffix variant of another: the table-family fold
# leaves all five apart, so every fold below is the concept layer's own doing.
VARIANTS = {
    "alpha": _HINTED_PARTY_COLUMNS,
    "beta": _HINTED_PARTY_COLUMNS,
    "gamma": _PARTY_COLUMNS,
    "delta": _PARTY_NO_COLUMNS,
    "epsilon": _PARTY_NO_COLUMNS,
}
KEY_COLUMN = {
    "alpha": "party_id",
    "beta": "party_id",
    "gamma": "party_id",
    "delta": "party_no",
    "epsilon": "party_no",
}

SCHEMA = {
    **{
        f"ods.demo_party_{variant}": {"column_details": columns}
        for variant, columns in VARIANTS.items()
    },
    "ods.demo_order_main": {
        "column_details": [
            {"name": "order_id", "type": "bigint", "comment": "合成订单号"},
            {"name": "party_id", "type": "bigint", "comment": "合成客户号"},
            {"name": "dt", "type": "string", "comment": "合成分区日"},
        ]
    },
    "ods.demo_item_main": {
        "column_details": [
            {"name": "item_id", "type": "bigint", "comment": "合成明细号"},
            {"name": "order_id", "type": "bigint", "comment": "合成订单号"},
            {"name": "dt", "type": "string", "comment": "合成分区日"},
        ]
    },
}

CASES = tuple(
    (
        f"demo_party_task_{variant}",
        f"INSERT OVERWRITE TABLE mart.demo_wide_{variant} "
        f"SELECT o.order_id AS order_id, p.party_name AS party_name "
        f"FROM ods.demo_order_main o LEFT JOIN ods.demo_party_{variant} p "
        f"ON o.party_id = p.{KEY_COLUMN[variant]}",
    )
    for variant in VARIANTS
) + (
    (
        "demo_item_task",
        "INSERT OVERWRITE TABLE mart.demo_item "
        "SELECT i.item_id AS item_id, o.party_id AS party_id "
        "FROM ods.demo_item_main i LEFT JOIN ods.demo_order_main o "
        "ON i.order_id = o.order_id",
    ),
)

PARTY_CONCEPT = "concept:party"
ORDER_CONCEPT = "concept:order"
PARTY_TABLES = [f"ods.demo_party_{variant}" for variant in sorted(VARIANTS)]

KEY_ITEM = f"open:concept:{PARTY_CONCEPT}:key=party"
RELATION_ITEM = f"open:concept:{ORDER_CONCEPT}:rel={PARTY_CONCEPT}:party"
FINDING_ITEM = f"open:concept:{PARTY_CONCEPT}:finding={FINDING_KEY_HINT_CONFLICT}"

STAMP = {"confirmed_by": "agent:n3-test", "date": "2026-09-23", "basis": "合成依据"}


def _ontology(overrides=None, cases=CASES) -> dict:
    documents = [
        to_lineage_dict(parse_scope_lineage(sql, task, schema=SCHEMA))
        for task, sql in cases
    ]
    profiles = [build_semantic_profile(document) for document in documents]
    return build_ontology(
        documents,
        profiles,
        tables=build_table_cards(profiles, artifact_root="corpus"),
        overrides=overrides,
        artifact_root="corpus",
    )


@pytest.fixture(scope="module")
def corpus() -> dict:
    return _ontology()


def _item(ontology: dict, identifier: str) -> dict:
    return next(
        item for item in ontology["concept_open_items"] if item["id"] == identifier
    )


def _concept(ontology: dict, identifier: str) -> dict:
    return next(item for item in ontology["concepts"] if item["id"] == identifier)


def _section(markdown: str, title: str) -> str:
    _head, marker, tail = markdown.partition(f"\n## {title}")
    assert marker, title
    return tail.partition("\n## ")[0]


# ------------------------------------------------------------------- 1. key folding


def test_five_representations_asking_one_identity_question_are_one_item(
    corpus: dict,
) -> None:
    """The whole point: `party_id` and `party_no` reduce to one stem, so one question."""
    item = _item(corpus, KEY_ITEM)

    assert item["kind"] == OPEN_ITEM_KEY
    assert item["concept"] == PARTY_CONCEPT
    assert item["count"] == 5
    assert item["tables"] == PARTY_TABLES
    assert sorted(item["items"]) == [
        f"open:key:ods.demo_party_{variant}={KEY_COLUMN[variant]}"
        for variant in sorted(VARIANTS)
    ]


def test_the_table_level_list_still_asks_every_question(corpus: dict) -> None:
    """The concept fold is a view, exactly as the family fold is."""
    keys = [item for item in corpus["open_items"] if item["kind"] == OPEN_ITEM_KEY]

    assert len([item for item in keys if item["entity"].startswith("ods.demo_party")]) == 5


def test_the_question_names_the_concept_and_how_many_tables_it_covers(
    corpus: dict,
) -> None:
    question = _item(corpus, KEY_ITEM)["question"]

    assert _concept(corpus, PARTY_CONCEPT)["name"] in question
    assert "5" in question
    # The representations disagree on the spelling, so the question is asked of the stem.
    assert "`party`" in question


def test_one_spelling_is_named_as_itself(corpus: dict) -> None:
    """A concept whose representations agree keeps the column, not the stem."""
    question = _item(corpus, f"open:concept:{ORDER_CONCEPT}:key=order")["question"]

    assert "`order_id`" in question


def test_the_impact_is_the_sum_over_the_items_it_folds(corpus: dict) -> None:
    """One edge assumed each party key, so the concept answer unblocks five."""
    assert _item(corpus, KEY_ITEM)["impact"] == 5


def test_the_tier_is_the_weakest_member(corpus: dict) -> None:
    assert _item(corpus, KEY_ITEM)["tier"] == TIER_HYPOTHESIS
    assert _item(corpus, FINDING_ITEM)["tier"] == TIER_CONFLICT


# -------------------------------------------------------------- 2. relation folding


def test_one_concept_edge_is_one_relation_question(corpus: dict) -> None:
    item = _item(corpus, RELATION_ITEM)

    assert item["kind"] == OPEN_ITEM_RELATION
    assert item["concept"] == ORDER_CONCEPT
    assert item["count"] == 5
    assert sorted(item["items"]) == sorted(
        f"open:rel:ods.demo_order_main.party_id->"
        f"ods.demo_party_{variant}.{KEY_COLUMN[variant]}"
        for variant in VARIANTS
    )
    assert _concept(corpus, PARTY_CONCEPT)["name"] in item["question"]


def test_the_relation_item_is_filed_under_the_from_concept(corpus: dict) -> None:
    """Which is where the table-level item is filed too -- one reading, not two."""
    filed = {
        item["concept"]
        for item in corpus["open_items"]
        if item["kind"] == OPEN_ITEM_RELATION and item["entity"] == "ods.demo_order_main"
    }

    assert filed == {ORDER_CONCEPT}


# --------------------------------------------------------------- 3. finding folding


def test_one_kind_of_contradiction_over_one_concept_is_one_item(corpus: dict) -> None:
    item = _item(corpus, FINDING_ITEM)

    assert item["kind"] == OPEN_ITEM_FINDING
    assert item["count"] == 2
    assert item["tables"] == ["ods.demo_party_alpha", "ods.demo_party_beta"]
    assert FINDING_KEY_HINT_CONFLICT in item["question"]


# --------------------------------------------------- 4. the write-back expansion list


def test_the_concept_answer_carries_the_table_level_keys_it_expands_to(
    corpus: dict,
) -> None:
    item = _item(corpus, KEY_ITEM)

    assert item["write_back"] == [
        f"键:ods.demo_party_{variant}={KEY_COLUMN[variant]}"
        for variant in sorted(VARIANTS)
    ]
    assert item["concept_write_back"] == f"{CONCEPT_KEY_WRITE_BACK}{PARTY_CONCEPT}=party"


def test_a_relation_answer_expands_to_one_write_back_per_edge(corpus: dict) -> None:
    item = _item(corpus, RELATION_ITEM)

    assert len(item["write_back"]) == 5
    assert all(key.startswith("关系:ods.demo_order_main.party_id->") for key in item["write_back"])
    assert item["concept_write_back"] == (
        f"{CONCEPT_RELATION_WRITE_BACK}{ORDER_CONCEPT}->{PARTY_CONCEPT}"
    )


def test_a_contradiction_has_no_concept_level_write_back(corpus: dict) -> None:
    """`concepts` in the overrides answers identity and cardinality, nothing else."""
    assert _item(corpus, FINDING_ITEM)["concept_write_back"] is None


# ----------------------------------------------------- 5. the concept-level overrides


@pytest.fixture(scope="module")
def key_confirmed() -> dict:
    return _ontology(
        overrides={
            "concepts": {PARTY_CONCEPT: {"keys": [{"columns": ["party_id"], **STAMP}]}}
        }
    )


def test_a_concept_key_answer_reaches_every_representation(key_confirmed: dict) -> None:
    tiers = {
        entity["id"]: [key["tier"] for key in entity["identity"]["candidate_keys"]]
        for entity in key_confirmed["tables"]
        if entity["id"] in PARTY_TABLES
    }

    assert tiers == {table: [TIER_CONFIRMED] for table in PARTY_TABLES}


def test_the_expansion_is_reported_with_the_key_the_item_published(
    key_confirmed: dict,
) -> None:
    assert key_confirmed["overrides_applied"]["concept_expansions"] == [
        {"key": f"{CONCEPT_KEY_WRITE_BACK}{PARTY_CONCEPT}=party", "applied_to": 5}
    ]
    assert key_confirmed["overrides_applied"]["keys"] == 5
    assert key_confirmed["overrides_applied"]["unmatched"] == []


def test_the_answered_questions_stop_being_asked(key_confirmed: dict) -> None:
    open_keys = {
        item["id"] for item in key_confirmed["open_items"] if item["kind"] == OPEN_ITEM_KEY
    }

    assert not any(item.startswith("open:key:ods.demo_party_") for item in open_keys)
    assert KEY_ITEM not in {item["id"] for item in key_confirmed["concept_open_items"]}


def test_the_reviewer_stamp_reaches_every_expanded_table(key_confirmed: dict) -> None:
    for entity in key_confirmed["tables"]:
        if entity["id"] not in PARTY_TABLES:
            continue
        evidence = entity["identity"]["candidate_keys"][0]["evidence"]
        assert any(item.get("confirmed_by") == "agent:n3-test" for item in evidence)


# ------------------------------------------------------ 6. the relation-level answer


@pytest.fixture(scope="module")
def relation_confirmed() -> dict:
    return _ontology(
        overrides={
            "concepts": {
                ORDER_CONCEPT: {
                    "relations": {
                        PARTY_CONCEPT: {"cardinality": CARDINALITY_MANY_TO_ONE, **STAMP}
                    }
                }
            }
        }
    )


def test_a_concept_relation_answer_reaches_every_folded_edge(
    relation_confirmed: dict,
) -> None:
    edges = [
        relation
        for relation in relation_confirmed["table_relations"]
        if relation["from"]["entity"] == "ods.demo_order_main"
    ]

    assert len(edges) == 5
    assert {edge["cardinality"]["tier"] for edge in edges} == {TIER_CONFIRMED}
    assert {edge["cardinality"]["claim"] for edge in edges} == {CARDINALITY_MANY_TO_ONE}


def test_the_concept_edge_is_rebuilt_on_the_confirmed_evidence(
    relation_confirmed: dict,
) -> None:
    """A concept relation is a reading of its edges, so it cannot stay a hypothesis."""
    edge = next(
        relation
        for relation in relation_confirmed["relations"]
        if relation["from"] == ORDER_CONCEPT and relation["to"] == PARTY_CONCEPT
    )

    assert edge["cardinality"]["tier"] == TIER_CONFIRMED


def test_the_relation_expansion_is_reported_and_closes_the_item(
    relation_confirmed: dict,
) -> None:
    applied = relation_confirmed["overrides_applied"]

    assert applied["concept_expansions"] == [
        {
            "key": f"{CONCEPT_RELATION_WRITE_BACK}{ORDER_CONCEPT}->{PARTY_CONCEPT}",
            "applied_to": 5,
        }
    ]
    assert applied["relations"] == 5
    assert RELATION_ITEM not in {
        item["id"] for item in relation_confirmed["concept_open_items"]
    }


# ------------------------------------------------------------------- 7. what missed


@pytest.fixture(scope="module")
def unmatched() -> dict:
    return _ontology(
        overrides={
            "concepts": {
                "concept:demo_nothing": {"keys": [{"columns": ["party_id"], **STAMP}]},
                PARTY_CONCEPT: {
                    "keys": [{"columns": ["demo_missing_id"], **STAMP}],
                    "relations": {"concept:demo_nowhere": {**STAMP}},
                },
            }
        }
    )


def test_an_unknown_concept_id_is_reported_rather_than_dropped(unmatched: dict) -> None:
    reported = {
        item["key"]: item["reason"] for item in unmatched["overrides_applied"]["unmatched"]
    }

    assert reported["concept:demo_nothing"] == "unknown_concept: concept:demo_nothing"


def test_stems_no_representation_carries_are_reported(unmatched: dict) -> None:
    reported = {
        item["key"]: item["reason"] for item in unmatched["overrides_applied"]["unmatched"]
    }

    assert reported[f"{CONCEPT_KEY_WRITE_BACK}{PARTY_CONCEPT}=demo_missing"] == (
        "unmatched_stems: demo_missing"
    )


def test_a_concept_relation_the_corpus_never_read_is_reported(unmatched: dict) -> None:
    reported = {
        item["key"]: item["reason"] for item in unmatched["overrides_applied"]["unmatched"]
    }

    assert reported[
        f"{CONCEPT_RELATION_WRITE_BACK}{PARTY_CONCEPT}->concept:demo_nowhere"
    ] == "unknown_concept_relation: concept:demo_nowhere"


def test_nothing_was_confirmed_by_an_override_that_matched_nothing(
    unmatched: dict,
) -> None:
    applied = unmatched["overrides_applied"]

    assert applied["concept_expansions"] == []
    assert applied["keys"] == 0 and applied["relations"] == 0


# -------------------------------------------------------------- 8. the group back-link


def test_every_table_level_group_says_which_concept_question_it_belongs_to(
    corpus: dict,
) -> None:
    back = {
        group["group_id"]: group["concept_open_item"]
        for group in corpus["open_item_groups"]
    }

    assert back["open:group:key:ods.demo_party_alpha=party_id"] == KEY_ITEM
    assert back["open:group:rel:ods.demo_party_delta=party_no"] == RELATION_ITEM
    assert back["open:group:finding:ods.demo_party_beta=key_hint_conflict"] == FINDING_ITEM
    assert all(value for value in back.values())


# ------------------------------------------------------------- 9. the concept's file


def test_the_concept_file_asks_the_concept_level_question(corpus: dict) -> None:
    body = _section(
        render_concept_markdown(_concept(corpus, PARTY_CONCEPT), corpus), "待人工判定"
    )

    assert KEY_ITEM in body
    assert _item(corpus, KEY_ITEM)["question"] in body
    assert f"{CONCEPT_KEY_WRITE_BACK}{PARTY_CONCEPT}=party" in body
    for table in PARTY_TABLES:
        assert f"`{table}`" in body


def test_the_table_level_ids_stay_in_the_file_as_evidence(corpus: dict) -> None:
    body = _section(
        render_concept_markdown(_concept(corpus, PARTY_CONCEPT), corpus), "待人工判定"
    )

    for item in _item(corpus, KEY_ITEM)["items"]:
        assert item in body


def test_a_concept_with_nothing_open_says_so(key_confirmed: dict) -> None:
    body = _section(
        render_concept_markdown(_concept(key_confirmed, PARTY_CONCEPT), key_confirmed),
        "待人工判定",
    )

    assert KEY_ITEM not in body


# ------------------------------------------------------------------ 10. the counters


def test_the_index_counts_the_concept_level_questions_beside_the_table_level_ones(
    corpus: dict,
) -> None:
    markdown = render_ontology_index_markdown(corpus)
    expected = len(corpus["concept_open_items"])

    assert f"concept_open_item_count: {expected}" in markdown
    assert f"open_item_count: {len(corpus['open_items'])}" in markdown
    assert f"{expected} 个概念级问题" in markdown


# --------------------------------------------------------------- 11. the determinism


def test_the_concept_open_list_is_byte_identical_for_the_same_corpus() -> None:
    first = _ontology()
    second = _ontology(cases=tuple(reversed(CASES)))

    assert json.dumps(first["concept_open_items"], ensure_ascii=False) == json.dumps(
        second["concept_open_items"], ensure_ascii=False
    )
    assert [item["id"] for item in first["concept_open_items"]] == [
        RELATION_ITEM,
        KEY_ITEM,
        FINDING_ITEM,
        f"open:concept:concept:table:ods_demo_item_main:rel={ORDER_CONCEPT}:order",
        f"open:concept:{ORDER_CONCEPT}:key=order",
    ]
