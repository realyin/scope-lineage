"""K3: relations between concepts, aggregated from the table-level ones.

``relations[]`` answer "which two *tables* were joined, on which columns". A business
does not ask that. It asks whether 「消息发送」 involves 「客户」, and in which role --
发送方 or 接收方 -- and whether 「客户日汇总」 aggregates the event or the entity.

The two ends of an edge answer two different questions, and reading them the same way is
what makes every edge fold onto itself. The ``from`` end answers *what this table is* --
its own identity, never the columns it happened to join on, and never a membership a
JOIN lent it. The ``to`` end answers *what it points at* -- the concept the join columns
name, and only failing that the table's own identity.

Every table, column and comment in these tests is synthetic. The corpus they stand in
for is never named.
"""

from __future__ import annotations

import json

import pytest

from scope_lineage.render import concept_relations as module
from scope_lineage.render.concept_relations import (
    CARDINALITY_CLAIMS,
    CARDINALITY_TIER_ORDER,
    TYPE_AGGREGATION,
    TYPE_ASSOCIATION,
    TYPE_DERIVATION,
    TYPE_ORDER,
    TYPE_PARTICIPATION,
    TYPE_SELF_REFERENCE,
    UNMAPPED_FROM_TABLE,
    UNMAPPED_REASONS,
    UNMAPPED_TO_TABLE,
    build_concept_relations,
)
from scope_lineage.render.concepts import (
    BASIS_REFERENCE,
    CONCEPT_ENTITY,
    CONCEPT_EVENT,
    CONCEPT_SUMMARY,
    build_concepts,
)
from scope_lineage.render.ontology import (
    CARDINALITY_CLAIMS as ONTOLOGY_CARDINALITY_CLAIMS,
    TIER_CONFIRMED,
    TIER_HYPOTHESIS,
    TIER_IMPLIED,
    TIER_PROVEN,
    TIERS,
    build_ontology,
    table_family,
)
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.render.table_cards import build_table_cards
from scope_lineage.contract import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage


# ------------------------------------------------------------------ synthetic inputs


def _attribute(column: str, *, comment=None) -> dict:
    return {
        "column": column,
        "type": None,
        "comment": comment,
        "observed_roles": [],
        "used_in_corpus": True,
        "not_null_observed": False,
        "synonyms": [],
    }


def _entity(table: str, *, keys=(), columns=(), comment=None, tier=TIER_PROVEN) -> dict:
    """One ontology entity, shaped exactly as ``ontology.py`` publishes it.

    ``columns`` are ``(name, comment)`` pairs; the key columns are added when missing so
    a caller only spells the comments that matter to the rule under test.
    """
    declared = dict(columns)
    for key in keys:
        declared.setdefault(str(key), None)
    return {
        "id": table,
        "kind": "physical_table",
        "family": table_family(table),
        "comment": comment,
        "identity": {
            "candidate_keys": (
                [{"columns": [str(key) for key in keys], "tier": tier, "evidence": []}]
                if keys
                else []
            ),
            "declared_hints": [],
            "multiplicity": [],
            "partition_columns": [],
        },
        "attributes": [
            _attribute(name, comment=text) for name, text in declared.items()
        ],
        "naming_hints": {
            "table_comment": comment,
            "domain": None,
            "project": None,
            "owner": None,
        },
    }


def _relation(
    identifier: str,
    source: str,
    columns,
    target: str,
    target_columns,
    *,
    kind: str = "join_association",
    claim: str = "many_to_one_assumed",
    tier: str = TIER_HYPOTHESIS,
    tasks=("task_a",),
) -> dict:
    return {
        "id": identifier,
        "from": {"entity": source, "columns": [str(item) for item in columns]},
        "to": {"entity": target, "columns": [str(item) for item in target_columns]},
        "kind": kind,
        "cardinality": {"claim": claim, "tier": tier, "basis": "no_uniqueness_evidence"},
        "join_types": ["INNER"],
        "task_count": len(tasks),
        "evidence": [
            {"task": str(task), "statement_id": "stmt:001"} for task in tasks
        ],
    }


def _cards() -> dict:
    """No table cards: every kind in these tests is decided by keys and comments."""
    return {"doc_format": "tables-json/1", "tables": []}


def _built(entities, relations) -> dict:
    """The ontology document the two builders publish together, as ``ontology.py`` does."""
    document = {
        "doc_format": "ontology-json/1",
        "entities": list(entities),
        "relations": list(relations),
    }
    document.update(build_concepts(document, _cards()))
    document.update(build_concept_relations(document))
    return document


def _relations(entities, relations) -> dict:
    document = _built(entities, relations)
    return {
        (str(item["from"]), str(item["to"])): item
        for item in document["concept_relations"]
    }


def _unmapped(reasons) -> dict:
    """The counter as it is published: every reason, so its shape never moves."""
    return {
        "total": sum(reasons.values()),
        "by_reason": {reason: reasons.get(reason, 0) for reason in UNMAPPED_REASONS},
    }


# The concepts every test below draws on: two entities, two events and a summary, each
# seeded by its own business key.
CUSTOMER = _entity(
    "ods.customer_base",
    keys=["cust_no"],
    columns=[
        ("cust_no", "客户编号"),
        ("parent_cust_no", "上级客户编号"),
        ("home_chan_no", "归属渠道编码"),
        ("bill_amt", "账单金额"),
    ],
    comment="客户信息表",
)
CHANNEL = _entity(
    "dim.channel",
    keys=["chan_no"],
    columns=[("chan_no", "渠道编码")],
    comment="渠道维表",
)
MESSAGE = _entity(
    "dwd.message_send_di",
    keys=["msg_id"],
    columns=[
        ("msg_id", None),
        ("cust_no", "客户编号"),
        ("sender_cust_no", "发送方编号"),
        ("receiver_cust_no", "接收方编号"),
        ("via_chan_no", None),
        ("src_reply_id", None),
    ],
    comment="消息发送流水表",
)
REPLY = _entity(
    "dwd.reply_send_di",
    keys=["reply_id"],
    columns=[("reply_id", None)],
    comment="回复发送记录表",
)
SUMMARY = _entity(
    "mart.cust_stat",
    keys=["stat_no"],
    columns=[("stat_no", None), ("owner_cust_no", None), ("of_msg_id", None)],
    comment="客户统计汇总表",
)
SNAPSHOT = _entity(
    "dwd.customer_df", keys=["cust_no"], columns=[("cust_no", "客户编号")]
)


def test_the_concepts_the_relation_tests_stand_on_are_the_kinds_they_claim() -> None:
    """A guard on the fixtures: the types below are only readable if the kinds hold."""
    concepts = {
        str(concept["id"]): str(concept["kind"])
        for concept in build_concepts(
            {"entities": [CUSTOMER, CHANNEL, MESSAGE, REPLY, SUMMARY], "relations": []},
            _cards(),
        )["concepts"]
    }

    assert concepts == {
        "concept:cust": CONCEPT_ENTITY,
        "concept:chan": CONCEPT_ENTITY,
        "concept:msg": CONCEPT_EVENT,
        "concept:reply": CONCEPT_EVENT,
        "concept:stat": CONCEPT_SUMMARY,
    }


# ------------------------------------------------------- the `from` end: what it IS


def test_the_from_end_is_the_tables_own_identity_not_the_columns_it_joined_on() -> None:
    """The event carries `cust_no`, so reading its columns folds 消息发送 into 客户.

    An event table is a `reference` member of 客户 *because* it carries that key. The
    `from` end asks what the table is, and its own key says 消息发送.
    """
    built = _relations(
        [CUSTOMER, MESSAGE],
        [_relation("rel:001", MESSAGE["id"], ["cust_no"], CUSTOMER["id"], ["cust_no"])],
    )

    assert list(built) == [("concept:msg", "concept:cust")]
    assert built[("concept:msg", "concept:cust")]["type"] == TYPE_PARTICIPATION


def test_the_from_end_never_reads_a_membership_a_join_lent_the_table() -> None:
    document = _built(
        [CUSTOMER, MESSAGE],
        [_relation("rel:001", MESSAGE["id"], ["cust_no"], CUSTOMER["id"], ["cust_no"])],
    )
    memberships = {
        str(concept["id"]): {
            str(item["table"]): str(item["membership_basis"])
            for item in concept["tables"]
        }
        for concept in document["concepts"]
    }

    assert memberships["concept:cust"][MESSAGE["id"]] == BASIS_REFERENCE
    assert memberships["concept:msg"][MESSAGE["id"]] != BASIS_REFERENCE
    assert [str(item["from"]) for item in document["concept_relations"]] == ["concept:msg"]


def test_a_from_table_no_key_placed_leaves_the_relation_unmapped() -> None:
    reference_only = _entity("ods.rows_a", columns=[("cust_no", "客户编号")])

    document = _built(
        [CUSTOMER, reference_only],
        [_relation("rel:001", reference_only["id"], ["cust_no"], CUSTOMER["id"], ["cust_no"])],
    )

    assert document["concept_relations"] == []
    assert document["concept_relations_unmapped"] == _unmapped({UNMAPPED_FROM_TABLE: 1})


# --------------------------------------------- the `to` end: what it POINTS AT


def test_the_to_end_is_the_concept_its_columns_name() -> None:
    built = _relations(
        [CUSTOMER, MESSAGE],
        [_relation("rel:001", MESSAGE["id"], ["sender_cust_no"], CUSTOMER["id"], ["cust_no"])],
    )

    assert list(built) == [("concept:msg", "concept:cust")]


def test_the_to_end_falls_back_to_the_to_tables_own_identity() -> None:
    """`bill_amt` is nobody's stem, so the question becomes what that table is."""
    built = _relations(
        [CUSTOMER, MESSAGE],
        [_relation("rel:001", MESSAGE["id"], ["msg_id"], CUSTOMER["id"], ["bill_amt"])],
    )

    assert list(built) == [("concept:msg", "concept:cust")]


def test_the_to_end_prefers_the_tables_identity_over_the_from_ends_own_concept() -> None:
    """客户 JOIN 消息发送 on `cust_no` is a participation, written the other way round.

    The `to` columns name 客户 -- which is what the `from` table already *is*, so they
    say nothing new. The corpus placed the `to` table on 消息发送, and that is the
    answer; taking the stem would publish 客户 → 客户.
    """
    built = _relations(
        [CUSTOMER, MESSAGE],
        [_relation("rel:001", CUSTOMER["id"], ["cust_no"], MESSAGE["id"], ["cust_no"])],
    )

    assert list(built) == [("concept:cust", "concept:msg")]
    relation = built[("concept:cust", "concept:msg")]
    assert relation["type"] == TYPE_PARTICIPATION
    assert relation["roles"] == ["客户"]


def test_the_clause_does_not_fire_when_the_to_table_is_the_same_concept() -> None:
    """The negative: a genuine self-join has nothing else to prefer, so it stays.

    `ods.customer_base` is 客户 on both ends -- there is no other identity to reach for,
    and 上级客户 → 客户 is a relation the business really has.
    """
    document = _built(
        [CUSTOMER],
        [_relation("rel:001", CUSTOMER["id"], ["parent_cust_no"], CUSTOMER["id"], ["cust_no"])],
    )

    assert [
        (str(item["from"]), str(item["to"]), str(item["type"]))
        for item in document["concept_relations"]
    ] == [("concept:cust", "concept:cust", TYPE_SELF_REFERENCE)]
    assert document["concept_representation_links"] == []


def test_a_to_table_neither_the_columns_nor_a_key_placed_is_unmapped() -> None:
    orphan = _entity("ods.rows_b", columns=[("free_txt", None)])

    document = _built(
        [CUSTOMER, orphan],
        [_relation("rel:001", CUSTOMER["id"], ["bill_amt"], orphan["id"], ["free_txt"])],
    )

    assert document["concept_relations"] == []
    assert document["concept_relations_unmapped"] == _unmapped({UNMAPPED_TO_TABLE: 1})


def test_the_two_unmapped_reasons_are_counted_apart() -> None:
    orphan = _entity("ods.rows_b", columns=[("free_txt", None)])

    document = _built(
        [CUSTOMER, MESSAGE, orphan],
        [
            _relation("rel:001", orphan["id"], ["free_txt"], CUSTOMER["id"], ["cust_no"]),
            _relation("rel:002", CUSTOMER["id"], ["bill_amt"], orphan["id"], ["free_txt"]),
            _relation("rel:003", MESSAGE["id"], ["msg_id"], CUSTOMER["id"], ["cust_no"]),
        ],
    )

    assert document["concept_relations_unmapped"] == _unmapped(
        {UNMAPPED_FROM_TABLE: 1, UNMAPPED_TO_TABLE: 1}
    )


def test_an_edge_that_fails_both_ends_is_counted_once_on_the_from_end() -> None:
    first = _entity("ods.rows_a", columns=[("free_txt", None)])
    second = _entity("ods.rows_b", columns=[("free_txt", None)])

    document = _built(
        [CUSTOMER, first, second],
        [_relation("rel:001", first["id"], ["free_txt"], second["id"], ["free_txt"])],
    )

    assert document["concept_relations_unmapped"] == _unmapped({UNMAPPED_FROM_TABLE: 1})


# --------------------------------------------------------------------- the types


def test_two_entities_make_an_association() -> None:
    built = _relations(
        [CUSTOMER, CHANNEL],
        [_relation("rel:001", CUSTOMER["id"], ["home_chan_no"], CHANNEL["id"], ["chan_no"])],
    )

    assert built[("concept:cust", "concept:chan")]["type"] == TYPE_ASSOCIATION


def test_an_event_onto_an_entity_makes_a_participation() -> None:
    built = _relations(
        [CUSTOMER, MESSAGE],
        [_relation("rel:001", MESSAGE["id"], ["sender_cust_no"], CUSTOMER["id"], ["cust_no"])],
    )

    assert built[("concept:msg", "concept:cust")]["type"] == TYPE_PARTICIPATION


def test_a_summary_onto_an_event_or_an_entity_makes_an_aggregation() -> None:
    built = _relations(
        [CUSTOMER, MESSAGE, SUMMARY],
        [
            _relation("rel:001", SUMMARY["id"], ["owner_cust_no"], CUSTOMER["id"], ["cust_no"]),
            _relation("rel:002", SUMMARY["id"], ["of_msg_id"], MESSAGE["id"], ["msg_id"]),
        ],
    )

    assert built[("concept:stat", "concept:cust")]["type"] == TYPE_AGGREGATION
    assert built[("concept:stat", "concept:msg")]["type"] == TYPE_AGGREGATION


def test_two_events_make_a_derivation() -> None:
    built = _relations(
        [MESSAGE, REPLY],
        [_relation("rel:001", MESSAGE["id"], ["src_reply_id"], REPLY["id"], ["reply_id"])],
    )

    assert built[("concept:msg", "concept:reply")]["type"] == TYPE_DERIVATION


# ------------------------------------- one concept twice: a self-join or a fold seam


def test_a_table_joined_to_itself_on_its_own_key_is_a_self_reference() -> None:
    """上级客户 → 客户 is 客户 pointing at itself, and the business wants to see it."""
    built = _relations(
        [CUSTOMER],
        [_relation("rel:001", CUSTOMER["id"], ["parent_cust_no"], CUSTOMER["id"], ["cust_no"])],
    )

    assert built[("concept:cust", "concept:cust")]["type"] == TYPE_SELF_REFERENCE


def test_two_representations_of_one_concept_are_a_representation_link() -> None:
    """A snapshot joined onto its primary says the two tables are the same thing.

    That is a fact about K1's fold, not a relation the business has; publishing it as a
    `self_reference` would claim 客户 relates to 客户.
    """
    document = _built(
        [CUSTOMER, SNAPSHOT],
        [_relation("rel:001", SNAPSHOT["id"], ["cust_no"], CUSTOMER["id"], ["cust_no"])],
    )

    assert document["concept_relations"] == []
    assert document["concept_representation_links"] == [
        {
            "concept": "concept:cust",
            "from_table": SNAPSHOT["id"],
            "to_table": CUSTOMER["id"],
            "evidence": ["rel:001"],
        }
    ]
    assert document["concept_relations_unmapped"] == _unmapped({})


def test_a_representation_link_gathers_every_edge_between_the_two_tables() -> None:
    document = _built(
        [CUSTOMER, SNAPSHOT],
        [
            _relation("rel:002", SNAPSHOT["id"], ["cust_no"], CUSTOMER["id"], ["cust_no"]),
            _relation(
                "rel:001", SNAPSHOT["id"], ["bill_amt"], CUSTOMER["id"], ["bill_amt"],
                kind="union_sibling",
            ),
        ],
    )

    assert [item["evidence"] for item in document["concept_representation_links"]] == [
        ["rel:001", "rel:002"]
    ]


# ---------------------------------------------------- the role in a participation


def test_the_participation_role_is_the_from_side_column_comment() -> None:
    """发送方编号 and 接收方编号 are the same JOIN twice; the roles are what differ."""
    built = _relations(
        [CUSTOMER, MESSAGE],
        [
            _relation("rel:001", MESSAGE["id"], ["sender_cust_no"], CUSTOMER["id"], ["cust_no"]),
            _relation("rel:002", MESSAGE["id"], ["receiver_cust_no"], CUSTOMER["id"], ["cust_no"]),
        ],
    )

    assert built[("concept:msg", "concept:cust")]["roles"] == ["发送方", "接收方"]


def test_the_participation_role_falls_back_to_the_column_name() -> None:
    built = _relations(
        [CHANNEL, MESSAGE],
        [_relation("rel:001", MESSAGE["id"], ["via_chan_no"], CHANNEL["id"], ["chan_no"])],
    )

    assert built[("concept:msg", "concept:chan")]["roles"] == ["via_chan_no"]


def test_only_a_participation_carries_roles() -> None:
    built = _relations(
        [CUSTOMER, CHANNEL],
        [_relation("rel:001", CUSTOMER["id"], ["home_chan_no"], CHANNEL["id"], ["chan_no"])],
    )

    assert "roles" not in built[("concept:cust", "concept:chan")]


# -------------------------------------------------------------- the cardinality


def test_the_concept_tiers_and_claims_are_the_ontology_ones() -> None:
    """K3 spells both vocabularies itself, because `ontology` imports this module."""
    assert set(CARDINALITY_TIER_ORDER) == set(TIERS)
    assert CARDINALITY_CLAIMS == ONTOLOGY_CARDINALITY_CLAIMS
    # Deliberately *not* `TIERS`: a claim the corpus proved outranks one a reviewer
    # confirmed for a single pair of tables, because the fold is about the corpus.
    assert CARDINALITY_TIER_ORDER.index(TIER_PROVEN) < CARDINALITY_TIER_ORDER.index(
        TIER_CONFIRMED
    )


def test_the_strongest_tier_across_the_group_wins() -> None:
    built = _relations(
        [CUSTOMER, MESSAGE],
        [
            _relation(
                "rel:001", MESSAGE["id"], ["sender_cust_no"], CUSTOMER["id"], ["cust_no"],
                claim="many_to_one_assumed", tier=TIER_HYPOTHESIS,
            ),
            _relation(
                "rel:002", MESSAGE["id"], ["receiver_cust_no"], CUSTOMER["id"], ["cust_no"],
                claim="many_to_one", tier=TIER_PROVEN,
            ),
            _relation(
                "rel:003", MESSAGE["id"], ["sender_cust_no"], CUSTOMER["id"], ["cust_no"],
                kind="hinted", claim="many_to_one", tier=TIER_CONFIRMED,
            ),
        ],
    )

    cardinality = built[("concept:msg", "concept:cust")]["cardinality"]
    assert cardinality["claim"] == "many_to_one"
    assert cardinality["tier"] == TIER_PROVEN
    assert cardinality["basis"] == ["rel:002"]


def test_within_one_tier_a_definite_claim_beats_unknown() -> None:
    built = _relations(
        [CUSTOMER, MESSAGE],
        [
            _relation(
                "rel:001", MESSAGE["id"], ["sender_cust_no"], CUSTOMER["id"], ["cust_no"],
                claim="unknown", tier=TIER_IMPLIED,
            ),
            _relation(
                "rel:002", MESSAGE["id"], ["receiver_cust_no"], CUSTOMER["id"], ["cust_no"],
                claim="one_to_many", tier=TIER_IMPLIED,
            ),
        ],
    )

    cardinality = built[("concept:msg", "concept:cust")]["cardinality"]
    assert cardinality["claim"] == "one_to_many"
    assert cardinality["tier"] == TIER_IMPLIED
    assert cardinality["basis"] == ["rel:002"]


def test_the_basis_names_every_relation_that_carried_the_winning_claim() -> None:
    built = _relations(
        [CUSTOMER, MESSAGE],
        [
            _relation(
                "rel:001", MESSAGE["id"], ["sender_cust_no"], CUSTOMER["id"], ["cust_no"],
                claim="many_to_one", tier=TIER_PROVEN,
            ),
            _relation(
                "rel:002", MESSAGE["id"], ["receiver_cust_no"], CUSTOMER["id"], ["cust_no"],
                claim="many_to_one", tier=TIER_PROVEN,
            ),
            _relation(
                "rel:003", MESSAGE["id"], ["via_chan_no"], CUSTOMER["id"], ["cust_no"],
                claim="unknown", tier=TIER_HYPOTHESIS,
            ),
        ],
    )

    assert built[("concept:msg", "concept:cust")]["cardinality"]["basis"] == [
        "rel:001",
        "rel:002",
    ]


# --------------------------------------------------------- evidence and the tasks


def test_the_evidence_is_every_member_relation_and_the_tasks_are_their_union() -> None:
    built = _relations(
        [CUSTOMER, MESSAGE],
        [
            _relation(
                "rel:002", MESSAGE["id"], ["receiver_cust_no"], CUSTOMER["id"], ["cust_no"],
                tasks=("task_a", "task_b"),
            ),
            _relation(
                "rel:001", MESSAGE["id"], ["sender_cust_no"], CUSTOMER["id"], ["cust_no"],
                tasks=("task_b",),
            ),
        ],
    )

    relation = built[("concept:msg", "concept:cust")]
    assert relation["evidence"] == ["rel:001", "rel:002"]
    assert relation["task_count"] == 2


# ------------------------------------------------------- duplicates and the order


def test_two_concepts_that_may_be_duplicates_keep_their_own_relations() -> None:
    """K2 refused to merge them; K3 does not merge them behind its back."""
    first = _entity("ods.contr_base", keys=["contr_no"], columns=[("contr_no", "合同编号")])
    second = _entity("ods.contra_base", keys=["contra_no"], columns=[("contra_no", "合同编号")])

    document = _built(
        [CUSTOMER, first, second],
        [
            _relation("rel:001", first["id"], ["party_no"], CUSTOMER["id"], ["cust_no"]),
            _relation("rel:002", second["id"], ["party_no"], CUSTOMER["id"], ["cust_no"]),
        ],
    )

    assert {str(item["name"]) for item in document["concepts"]} == {"合同", "客户"}
    assert [
        (str(item["from"]), str(item["to"])) for item in document["concept_relations"]
    ] == [("concept:contr", "concept:cust"), ("concept:contra", "concept:cust")]


def test_the_order_is_the_type_order_then_the_two_concept_ids() -> None:
    document = _built(
        [CUSTOMER, CHANNEL, MESSAGE, REPLY, SUMMARY],
        [
            _relation("rel:001", MESSAGE["id"], ["src_reply_id"], REPLY["id"], ["reply_id"]),
            _relation("rel:002", CUSTOMER["id"], ["parent_cust_no"], CUSTOMER["id"], ["cust_no"]),
            _relation("rel:003", SUMMARY["id"], ["owner_cust_no"], CUSTOMER["id"], ["cust_no"]),
            _relation("rel:004", MESSAGE["id"], ["sender_cust_no"], CUSTOMER["id"], ["cust_no"]),
            _relation("rel:005", CUSTOMER["id"], ["home_chan_no"], CHANNEL["id"], ["chan_no"]),
        ],
    )

    assert [
        (str(item["type"]), str(item["from"]), str(item["to"]))
        for item in document["concept_relations"]
    ] == [
        (TYPE_ASSOCIATION, "concept:cust", "concept:chan"),
        (TYPE_PARTICIPATION, "concept:msg", "concept:cust"),
        (TYPE_AGGREGATION, "concept:stat", "concept:cust"),
        (TYPE_DERIVATION, "concept:msg", "concept:reply"),
        (TYPE_SELF_REFERENCE, "concept:cust", "concept:cust"),
    ]
    assert [item["type"] for item in document["concept_relations"]] == sorted(
        (item["type"] for item in document["concept_relations"]),
        key=TYPE_ORDER.index,
    )


def test_the_same_inputs_build_byte_identical_concept_relations() -> None:
    entities = [CUSTOMER, CHANNEL, MESSAGE, REPLY, SUMMARY, SNAPSHOT]
    relations = [
        _relation("rel:001", MESSAGE["id"], ["sender_cust_no"], CUSTOMER["id"], ["cust_no"]),
        _relation("rel:002", CUSTOMER["id"], ["home_chan_no"], CHANNEL["id"], ["chan_no"]),
        _relation("rel:003", SUMMARY["id"], ["of_msg_id"], MESSAGE["id"], ["msg_id"]),
        _relation("rel:004", SNAPSHOT["id"], ["cust_no"], CUSTOMER["id"], ["cust_no"]),
    ]

    first = _built(entities, relations)
    second = _built(entities, relations)

    for key in ("concept_relations", "concept_representation_links"):
        assert json.dumps(first[key], ensure_ascii=False) == json.dumps(
            second[key], ensure_ascii=False
        )


def test_a_concept_relation_publishes_its_keys_in_one_order() -> None:
    built = _relations(
        [CUSTOMER, MESSAGE],
        [_relation("rel:001", MESSAGE["id"], ["sender_cust_no"], CUSTOMER["id"], ["cust_no"])],
    )

    assert list(built[("concept:msg", "concept:cust")]) == list(module.CONCEPT_RELATION_KEYS)


@pytest.mark.parametrize(
    "key",
    [
        "concept_relations",
        "concept_representation_links",
        "concept_relations_unmapped",
    ],
)
def test_the_document_carries_the_concept_relation_keys_even_when_empty(key: str) -> None:
    assert key in _built([CUSTOMER], [])


# ------------------------------------------------- the whole pipeline, from the SQL

#: A corpus small enough to read: one task builds the event table keyed by its own id,
#: one builds the customer snapshot keyed by the customer number, and one joins them on
#: the customer number -- the shape that used to fold 消息发送 into 客户.
SCHEMA = {
    "stg.message_raw": ["msg_no", "cust_no", "send_time"],
    "ods.message_send_di": ["msg_no", "cust_no", "send_time"],
    "ods.customer_base": ["cust_no", "cust_name"],
    "dwd.customer_df": ["cust_no", "cust_name"],
}

CORPUS = (
    (
        "task_message_build",
        "INSERT OVERWRITE TABLE ods.message_send_di "
        "SELECT msg_no, max(cust_no) AS cust_no, max(send_time) AS send_time "
        "FROM stg.message_raw GROUP BY msg_no",
    ),
    (
        "task_customer",
        "INSERT OVERWRITE TABLE dwd.customer_df "
        "SELECT cust_no, max(cust_name) AS cust_name FROM ods.customer_base GROUP BY cust_no",
    ),
    (
        "task_daily",
        "INSERT OVERWRITE TABLE mart.message_daily "
        "SELECT m.msg_no, c.cust_name FROM ods.message_send_di m "
        "JOIN dwd.customer_df c ON m.cust_no = c.cust_no",
    ),
)


def _ontology() -> dict:
    documents = []
    profiles = []
    for task, sql in CORPUS:
        document = to_lineage_dict(parse_scope_lineage(sql, task, schema=SCHEMA))
        documents.append(document)
        profiles.append(build_semantic_profile(document))
    cards = build_table_cards(profiles, artifact_root="corpus")
    return build_ontology(documents, profiles, tables=cards, artifact_root="corpus")


def test_an_event_joined_onto_a_customer_key_folds_to_a_participation() -> None:
    """The regression the endpoint rule exists for, driven from the SQL.

    The JOIN is written on `cust_no`, which makes the event a `reference` member of
    客户. Reading the `from` end off those columns would answer 客户 → 客户.
    """
    ontology = _ontology()

    assert [
        (str(item["from"]), str(item["to"]), str(item["type"]))
        for item in ontology["concept_relations"]
    ] == [("concept:msg", "concept:cust", TYPE_PARTICIPATION)]
    assert ontology["concept_representation_links"] == []
    assert ontology["concept_relations_unmapped"] == _unmapped({})


def test_the_whole_pipeline_is_byte_identical_across_two_builds() -> None:
    first = _ontology()
    second = _ontology()

    for key in ("concept_relations", "concept_representation_links"):
        assert json.dumps(first[key], ensure_ascii=False) == json.dumps(
            second[key], ensure_ascii=False
        )
    assert first["concept_relations_unmapped"] == second["concept_relations_unmapped"]
