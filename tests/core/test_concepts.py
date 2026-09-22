"""K1 / K2: the concept layer above the table-level ontology.

``entities[]`` answer "what is this *table*". A concept answers the question the owner
actually asks -- 实体应该是「客户」而不是「用户信息表」，「消息发送」这类事件与实体并列 --
so the layer here folds the tables that share one business key into one concept, decides
whether that concept is an entity, an event or a summary, and proposes a name for it.

Every table in these tests is synthetic. The corpus they stand in for is never named.
"""

from __future__ import annotations

import json

import pytest

from scope_lineage.render import concepts as concepts_module
from scope_lineage.render.concepts import (
    CONCEPT_ENTITY,
    CONCEPT_EVENT,
    CONCEPT_SUMMARY,
    GENERIC_STEMS,
    BASIS_DECLARED_HINT,
    BASIS_REFERENCE,
    NAME_FROM_KEY_COMMENT,
    NAME_FROM_STEM,
    NAME_FROM_TABLE_COMMENT,
    REASON_GENERIC_KEY,
    REASON_NO_CANDIDATE_KEY,
    REASON_SPLIT_KEY,
    ROLE_DETAIL,
    ROLE_INTERMEDIATE,
    ROLE_PRIMARY,
    ROLE_REFERENCE,
    ROLE_SNAPSHOT,
    ROLE_SUMMARY,
    build_concepts,
    key_basis,
    is_generic_stem,
    key_stem,
)
from scope_lineage.render.ontology import (
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


def _attribute(column: str, *, type_=None, comment=None, synonyms=()) -> dict:
    return {
        "column": column,
        "type": type_,
        "comment": comment,
        "observed_roles": [],
        "used_in_corpus": True,
        "not_null_observed": False,
        "synonyms": [dict(item) for item in synonyms],
    }


def _entity(
    table: str,
    *,
    keys=(),
    tier: str = TIER_PROVEN,
    partitions=(),
    attributes=None,
    comment=None,
    hints=(),
) -> dict:
    """One ontology entity, shaped exactly as ``ontology.py`` publishes it."""
    candidate_keys = (
        [{"columns": [str(key) for key in keys], "tier": tier, "evidence": []}]
        if keys
        else []
    )
    return {
        "id": table,
        "kind": "physical_table",
        "family": table_family(table),
        "comment": comment,
        "identity": {
            "candidate_keys": candidate_keys,
            "declared_hints": [
                {"columns": [str(column)], "evidence": "column_comment", "text": "主键"}
                for column in hints
            ],
            "multiplicity": [],
            "partition_columns": [str(column) for column in partitions],
        },
        "attributes": (
            list(attributes)
            if attributes is not None
            else [_attribute(column) for column in keys]
        ),
        "naming_hints": {
            "table_comment": comment,
            "domain": None,
            "project": None,
            "owner": None,
        },
    }


def _ontology(*entities: dict, relations=()) -> dict:
    return {
        "doc_format": "ontology-json/1",
        "entities": list(entities),
        "relations": list(relations),
    }


def _relation(source: str, columns, target: str, target_columns, kind="join_association") -> dict:
    return {
        "id": "rel:001",
        "from": {"entity": source, "columns": [str(item) for item in columns]},
        "to": {"entity": target, "columns": [str(item) for item in target_columns]},
        "kind": kind,
        "cardinality": {"claim": "many_to_one_assumed", "tier": TIER_HYPOTHESIS},
        "join_types": ["INNER"],
        "task_count": 1,
        "evidence": [],
    }


def _producer(task: str, *, basis=None, keys=(), statement_id="stmt:001") -> dict:
    return {
        "task": task,
        "statement_id": statement_id,
        "grain": {"basis": basis, "keys": [str(key) for key in keys]},
        "candidate_keys": [str(key) for key in keys],
        "key_confidence": "proven",
    }


def _consumer(task: str, *, role="enrich", statement_id="stmt:001") -> dict:
    return {
        "task": task,
        "statement_id": statement_id,
        "role_in_task": role,
        "roles": [role],
        "columns": [],
        "read_by_scopes": [],
    }


def _card(table: str, *, comment=None, columns=(), produced=(), consumed=()) -> dict:
    return {
        "table": table,
        "comment": comment,
        "columns": [
            column if isinstance(column, dict) else {"name": str(column)}
            for column in columns
        ],
        "produced_by": list(produced),
        "consumed_by": list(consumed),
    }


def _cards(*cards: dict) -> dict:
    return {"doc_format": "tables-json/1", "tables": list(cards)}


def _concepts(ontology: dict, cards: dict) -> dict:
    return {
        str(concept["id"]): concept
        for concept in build_concepts(ontology, cards)["concepts"]
    }


def _unassigned(ontology: dict, cards: dict) -> dict:
    return {
        str(item["table"]): str(item["reason"])
        for item in build_concepts(ontology, cards)["unassigned_tables"]
    }


# ------------------------------------------------------- K1: the key stem


@pytest.mark.parametrize(
    ("column", "expected"),
    [
        ("cust_no", "cust"),
        ("CUST_ID", "cust"),
        ("customer_id", "customer"),
        ("channel_code", "channel"),
        ("order_cd", "order"),
        ("item_num", "item"),
        ("party_key", "party"),
        ("id_cust", "cust"),
        # Whole segments only, and never the last one left.
        ("channel_name", "channel_name"),
        ("id", "id"),
    ],
)
def test_the_key_stem_strips_the_key_affixes_only(column: str, expected: str) -> None:
    assert key_stem(column) == expected


def test_a_synonym_folds_two_spellings_onto_one_stem() -> None:
    """O5 already proved the two columns hold the same value; the stem follows it."""
    assert key_stem("customer_id", {"customer_id": "cust_no"}) == "cust"


def test_the_concept_tiers_are_the_ontology_tiers() -> None:
    """`concepts` spells the two tiers itself, because `ontology` imports it."""
    assert concepts_module.TIER_IMPLIED == TIER_IMPLIED
    assert concepts_module.TIER_HYPOTHESIS == TIER_HYPOTHESIS
    assert set(concepts_module.SEED_TIERS) <= set(TIERS)


def test_the_generic_stem_list_is_not_a_business_key() -> None:
    assert all(is_generic_stem(stem) for stem in GENERIC_STEMS)
    assert not is_generic_stem("cust")


def test_a_stem_whose_comments_share_no_cjk_bigram_is_generic() -> None:
    """Three tables calling the same stem three unrelated things is not one concept."""
    assert is_generic_stem("code", ["渠道编码", "省份编码", "状态编码"])
    assert not is_generic_stem("code", ["客户编码", "客户编号", "客户代码"])
    # Two comments are not enough evidence to call a stem generic.
    assert not is_generic_stem("code", ["渠道编码", "省份编码"])


# ------------------------------------------------------- K1: seeding


def test_two_tables_sharing_one_business_key_seed_one_concept() -> None:
    ontology = _ontology(
        _entity(
            "ods.customer_base",
            keys=["cust_no"],
            comment="客户信息表",
            attributes=[
                _attribute(
                    "cust_no",
                    comment="客户编号",
                    synonyms=[
                        {
                            "entity": "dwd.customer_ext_df",
                            "column": "customer_id",
                            "tier": TIER_PROVEN,
                            "via": "direct_rename",
                        }
                    ],
                ),
                _attribute("cust_name", comment="客户名称"),
            ],
        ),
        _entity(
            "dwd.customer_ext_df",
            keys=["customer_id"],
            comment="客户扩展信息表",
            attributes=[
                _attribute(
                    "customer_id",
                    comment="客户编号",
                    synonyms=[
                        {
                            "entity": "ods.customer_base",
                            "column": "cust_no",
                            "tier": TIER_PROVEN,
                            "via": "direct_rename",
                        }
                    ],
                ),
                _attribute("risk_level", comment="风险等级"),
            ],
        ),
    )
    cards = _cards(
        _card("ods.customer_base", comment="客户信息表", columns=["cust_no", "cust_name"]),
        _card(
            "dwd.customer_ext_df",
            comment="客户扩展信息表",
            columns=["customer_id", "risk_level"],
        ),
    )

    concepts = _concepts(ontology, cards)

    assert list(concepts) == ["concept:cust"]
    concept = concepts["concept:cust"]
    assert [item["table"] for item in concept["tables"]] == [
        "dwd.customer_ext_df",
        "ods.customer_base",
    ]
    assert concept["identity"] == {
        "stem": "cust",
        "columns_seen": ["cust_no", "customer_id"],
    }
    assert not _unassigned(ontology, cards)


def test_a_key_the_corpus_only_assumed_still_seeds_a_hypothesis_concept() -> None:
    """A warehouse rarely proves its keys; refusing to read them models nothing."""
    ontology = _ontology(_entity("ods.customer_base", keys=["cust_no"], tier=TIER_HYPOTHESIS))
    cards = _cards(_card("ods.customer_base", columns=["cust_no"]))

    concept = _concepts(ontology, cards)["concept:cust"]

    assert concept["tier"] == TIER_HYPOTHESIS
    assert concept["tables"][0]["membership_basis"] == key_basis(TIER_HYPOTHESIS)
    assert not _unassigned(ontology, cards)


def test_a_proven_key_raises_the_concept_to_implied() -> None:
    ontology = _ontology(_entity("ods.customer_base", keys=["cust_no"], tier=TIER_PROVEN))
    cards = _cards(_card("ods.customer_base", columns=["cust_no"]))

    concept = _concepts(ontology, cards)["concept:cust"]

    assert concept["tier"] == TIER_IMPLIED
    assert concept["tables"][0]["membership_basis"] == key_basis(TIER_PROVEN)


def test_a_declared_key_hint_seeds_a_concept_when_no_key_was_read() -> None:
    """The catalog calling a column the primary key is evidence the corpus never wrote."""
    ontology = _ontology(
        _entity(
            "ods.customer_base",
            hints=["cust_no"],
            attributes=[_attribute("cust_no", comment="客户编号")],
        )
    )
    cards = _cards(_card("ods.customer_base", columns=["cust_no"]))

    concept = _concepts(ontology, cards)["concept:cust"]

    assert concept["tier"] == TIER_HYPOTHESIS
    assert concept["tables"][0]["membership_basis"] == BASIS_DECLARED_HINT
    assert concept["tables"][0]["key_columns"] == ["cust_no"]


def test_a_join_onto_the_concepts_key_joins_the_source_as_a_reference() -> None:
    """An event table carries 客户 as a foreign key; that is how it takes part in 客户."""
    ontology = _ontology(
        _entity("ods.customer_base", keys=["cust_no"], comment="客户信息表"),
        _entity("dwd.message_send_di", keys=["msg_no"], comment="消息发送明细表"),
        relations=[
            _relation("dwd.message_send_di", ["cust_no"], "ods.customer_base", ["cust_no"])
        ],
    )
    cards = _cards(
        _card("ods.customer_base", comment="客户信息表", columns=["cust_no"]),
        _card("dwd.message_send_di", comment="消息发送明细表", columns=["msg_no", "cust_no"]),
    )

    concepts = _concepts(ontology, cards)
    member = {
        str(item["table"]): item for item in concepts["concept:cust"]["tables"]
    }["dwd.message_send_di"]

    assert member["role"] == ROLE_REFERENCE
    assert member["membership_basis"] == BASIS_REFERENCE
    assert member["key_columns"] == ["cust_no"]
    assert not _unassigned(ontology, cards)


def test_a_reference_member_never_votes_on_the_kind_or_lends_attributes() -> None:
    """消息发送 joining 客户 does not make 客户 an event, nor 客户 wider."""
    ontology = _ontology(
        _entity("ods.customer_base", keys=["cust_no"], comment="客户信息表"),
        _entity(
            "dwd.message_send_di",
            keys=["msg_no"],
            comment="消息发送明细表",
            attributes=[_attribute("msg_no"), _attribute("cust_no"), _attribute("body")],
        ),
        relations=[
            _relation("dwd.message_send_di", ["cust_no"], "ods.customer_base", ["cust_no"])
        ],
    )
    cards = _cards(
        _card("ods.customer_base", comment="客户信息表", columns=["cust_no"]),
        _card("dwd.message_send_di", comment="消息发送明细表", columns=["msg_no", "cust_no", "body"]),
    )

    concept = _concepts(ontology, cards)["concept:cust"]

    assert concept["kind"] == CONCEPT_ENTITY
    assert [str(item["stem"]) for item in concept["attributes"]] == ["cust"]


def test_a_table_no_key_hint_or_join_places_is_unassigned() -> None:
    ontology = _ontology(_entity("ods.orphan_rows"))
    cards = _cards(_card("ods.orphan_rows", columns=["value"]))

    assert not _concepts(ontology, cards)
    assert _unassigned(ontology, cards) == {"ods.orphan_rows": REASON_NO_CANDIDATE_KEY}


def test_a_table_keyed_only_by_a_generic_column_is_unassigned() -> None:
    ontology = _ontology(
        _entity("ods.staging_rows", keys=["id"], attributes=[_attribute("id")])
    )
    cards = _cards(_card("ods.staging_rows", columns=["id"]))

    assert not _concepts(ontology, cards)
    assert _unassigned(ontology, cards) == {"ods.staging_rows": REASON_GENERIC_KEY}


def test_a_composite_key_spanning_two_stems_is_unassigned() -> None:
    ontology = _ontology(
        _entity("mart.cust_channel_sum", keys=["cust_no", "channel_code"])
    )
    cards = _cards(_card("mart.cust_channel_sum", columns=["cust_no", "channel_code"]))

    assert not _concepts(ontology, cards)
    assert _unassigned(ontology, cards) == {"mart.cust_channel_sum": REASON_SPLIT_KEY}


def test_a_composite_key_reduces_over_its_time_and_partition_columns() -> None:
    """``(cust_no, dt)`` is still the customer; ``dt`` says which day's copy it is."""
    ontology = _ontology(
        _entity("dwd.customer_di", keys=["cust_no", "dt"], partitions=["dt"])
    )
    cards = _cards(_card("dwd.customer_di", columns=["cust_no", "dt"]))

    assert list(_concepts(ontology, cards)) == ["concept:cust"]


# ------------------------------------------------------- K1: member roles


def _role_of(entity: dict, card: dict) -> str:
    concepts = _concepts(_ontology(entity), _cards(card))
    return str(concepts["concept:cust"]["tables"][0]["role"])


def test_a_full_snapshot_keyed_by_the_stem_is_the_primary_member() -> None:
    assert (
        _role_of(
            _entity("dwd.customer_df", keys=["cust_no"]),
            _card("dwd.customer_df", columns=["cust_no"]),
        )
        == ROLE_PRIMARY
    )


def test_a_physical_table_with_no_period_suffix_is_the_primary_member() -> None:
    assert (
        _role_of(
            _entity("ods.customer_base", keys=["cust_no"]),
            _card("ods.customer_base", columns=["cust_no"]),
        )
        == ROLE_PRIMARY
    )


def test_an_increment_keyed_by_the_stem_alone_is_a_snapshot_member() -> None:
    assert (
        _role_of(
            _entity("dwd.customer_di", keys=["cust_no", "dt"], partitions=["dt"]),
            _card("dwd.customer_di", columns=["cust_no", "dt"]),
        )
        == ROLE_SNAPSHOT
    )


def test_a_key_carrying_an_event_time_is_a_detail_member() -> None:
    assert (
        _role_of(
            _entity(
                "dwd.cust_message_di",
                keys=["cust_no", "send_time"],
                partitions=["dt"],
                attributes=[
                    _attribute("cust_no"),
                    _attribute("send_time", type_="timestamp"),
                ],
            ),
            _card("dwd.cust_message_di", columns=["cust_no", "send_time"]),
        )
        == ROLE_DETAIL
    )


def test_a_group_by_product_is_a_summary_member() -> None:
    assert (
        _role_of(
            _entity("dws.cust_amount_sum_di", keys=["cust_no", "dt"], partitions=["dt"]),
            _card(
                "dws.cust_amount_sum_di",
                columns=["cust_no", "dt"],
                produced=[_producer("task_a", basis="group_by", keys=["cust_no"])],
            ),
        )
        == ROLE_SUMMARY
    )


def test_a_stage_suffix_is_an_intermediate_member() -> None:
    assert (
        _role_of(
            _entity("dwd.customer_mid01", keys=["cust_no"]),
            _card("dwd.customer_mid01", columns=["cust_no"]),
        )
        == ROLE_INTERMEDIATE
    )


def test_a_table_one_task_both_writes_and_reads_is_an_intermediate_member() -> None:
    assert (
        _role_of(
            _entity("dwd.customer_work", keys=["cust_no"]),
            _card(
                "dwd.customer_work",
                columns=["cust_no"],
                produced=[_producer("task_a")],
                consumed=[_consumer("task_a", statement_id="stmt:002")],
            ),
        )
        == ROLE_INTERMEDIATE
    )


# ------------------------------------------------------- K1: the concept kind


def test_an_increment_keyed_by_an_event_time_is_an_event() -> None:
    ontology = _ontology(
        _entity(
            "dwd.message_send_di",
            keys=["msg_no", "send_time"],
            partitions=["dt"],
            comment="消息发送明细表",
            attributes=[
                _attribute("msg_no", comment="消息编号"),
                _attribute("send_time", type_="timestamp", comment="发送时间"),
            ],
        )
    )
    cards = _cards(
        _card("dwd.message_send_di", comment="消息发送明细表", columns=["msg_no", "send_time"])
    )

    concept = _concepts(ontology, cards)["concept:msg"]

    assert concept["kind"] == CONCEPT_EVENT
    assert concept["kind_tier"] == TIER_IMPLIED
    assert {str(item["vote"]) for item in concept["kind_evidence"]} == {CONCEPT_EVENT}


def test_a_group_by_product_is_a_summary_concept() -> None:
    ontology = _ontology(
        _entity(
            "dws.cust_amount_sum_di",
            keys=["cust_no", "dt"],
            partitions=["dt"],
            comment="客户金额汇总表",
        )
    )
    cards = _cards(
        _card(
            "dws.cust_amount_sum_di",
            comment="客户金额汇总表",
            columns=["cust_no", "dt"],
            produced=[_producer("task_a", basis="group_by", keys=["cust_no"])],
        )
    )

    concept = _concepts(ontology, cards)["concept:cust"]

    assert concept["kind"] == CONCEPT_SUMMARY
    assert concept["kind_tier"] == TIER_IMPLIED


def test_a_bare_date_column_is_not_an_event_time() -> None:
    """`dt` says which day's copy this is. It names no event, declared partition or not."""
    ontology = _ontology(
        _entity(
            "dws.cust_order_sum_di",
            keys=["cust_no"],
            comment="客户订单表",
            attributes=[
                _attribute("cust_no"),
                _attribute("dt", type_="string"),
                _attribute("etl_time", type_="timestamp"),
            ],
        )
    )
    cards = _cards(
        _card(
            "dws.cust_order_sum_di",
            comment="客户订单表",
            columns=["cust_no", "dt", "etl_time"],
        )
    )

    concept = _concepts(ontology, cards)["concept:cust"]

    assert concept["kind"] == CONCEPT_ENTITY
    assert not [
        item for item in concept["kind_evidence"] if str(item["vote"]) == CONCEPT_EVENT
    ]


def test_a_full_snapshot_with_a_business_key_is_an_entity() -> None:
    ontology = _ontology(
        _entity("dwd.customer_df", keys=["cust_no"], comment="客户信息表")
    )
    cards = _cards(_card("dwd.customer_df", comment="客户信息表", columns=["cust_no"]))

    concept = _concepts(ontology, cards)["concept:cust"]

    assert concept["kind"] == CONCEPT_ENTITY
    assert concept["kind_tier"] == TIER_IMPLIED


def test_driving_rows_over_a_log_source_votes_event() -> None:
    ontology = _ontology(_entity("dwd.trade_detail_df", keys=["trade_no"]))
    cards = _cards(
        _card(
            "dwd.trade_detail_df",
            columns=["trade_no"],
            produced=[_producer("task_a", basis="driving_table_rows")],
        ),
        _card(
            "ods.gateway_log",
            columns=["trade_no"],
            consumed=[_consumer("task_a", role="driving")],
        ),
    )

    concept = _concepts(ontology, cards)["concept:trade"]

    assert concept["kind"] == CONCEPT_EVENT
    assert [
        str(item["signal"])
        for item in concept["kind_evidence"]
        if str(item.get("detail") or "") == "ods.gateway_log"
    ]


def test_disagreeing_signals_drop_the_kind_to_a_hypothesis_and_say_why() -> None:
    """The key says event, the comment says entity; a reviewer sees both votes."""
    ontology = _ontology(
        _entity(
            "dwd.customer_di",
            keys=["cust_no", "send_time"],
            partitions=["dt"],
            comment="客户信息表",
            attributes=[
                _attribute("cust_no"),
                _attribute("send_time", type_="timestamp"),
            ],
        )
    )
    cards = _cards(
        _card("dwd.customer_di", comment="客户信息表", columns=["cust_no", "send_time"])
    )

    concept = _concepts(ontology, cards)["concept:cust"]

    assert concept["kind"] == CONCEPT_EVENT
    assert concept["kind_tier"] == TIER_HYPOTHESIS
    votes = {str(item["vote"]) for item in concept["kind_evidence"]}
    assert votes == {CONCEPT_EVENT, CONCEPT_ENTITY}


# ------------------------------------------------------- K1: attributes


def test_the_attributes_are_the_members_columns_folded_by_stem() -> None:
    ontology = _ontology(
        _entity(
            "ods.customer_base",
            keys=["cust_no"],
            attributes=[
                _attribute("cust_no", type_="string", comment="客户编号"),
                _attribute("cust_name", comment="客户名称"),
            ],
        ),
        _entity(
            "dwd.cust_ext_df",
            keys=["cust_no"],
            attributes=[
                _attribute("cust_no", type_="string", comment="客户编号"),
                _attribute("risk_level", comment="风险等级"),
            ],
        ),
    )
    cards = _cards(
        _card("ods.customer_base", columns=["cust_no", "cust_name"]),
        _card("dwd.cust_ext_df", columns=["cust_no", "risk_level"]),
    )

    attributes = {
        str(item["stem"]): item
        for item in _concepts(ontology, cards)["concept:cust"]["attributes"]
    }

    assert set(attributes) == {"cust", "cust_name", "risk_level"}
    assert attributes["cust"]["sources"] == [
        {"table": "dwd.cust_ext_df", "column": "cust_no"},
        {"table": "ods.customer_base", "column": "cust_no"},
    ]
    assert attributes["risk_level"]["sources"] == [
        {"table": "dwd.cust_ext_df", "column": "risk_level"}
    ]


# ------------------------------------------------------- K2: naming candidates


def _names(ontology: dict, cards: dict, concept_id: str = "concept:cust") -> list[tuple]:
    concept = _concepts(ontology, cards)[concept_id]
    return [(str(item["text"]), str(item["source"])) for item in concept["name_candidates"]]


def test_the_key_column_comment_is_the_first_naming_candidate() -> None:
    ontology = _ontology(
        _entity(
            "ods.customer_base",
            keys=["cust_no"],
            comment="客户信息表",
            attributes=[_attribute("cust_no", comment="客户编号")],
        )
    )
    cards = _cards(_card("ods.customer_base", comment="客户信息表", columns=["cust_no"]))

    concept = _concepts(ontology, cards)["concept:cust"]

    assert concept["name"] == "客户"
    assert concept["name_tier"] == TIER_HYPOTHESIS
    assert _names(ontology, cards) == [
        ("客户", NAME_FROM_KEY_COMMENT),
        ("客户", NAME_FROM_TABLE_COMMENT),
        ("cust", NAME_FROM_STEM),
    ]
    assert concept["name_candidates"][0]["name_evidence"] == [
        {"table": "ods.customer_base", "column": "cust_no"}
    ]


def test_the_table_comments_keep_their_longest_common_prefix() -> None:
    ontology = _ontology(
        _entity("ods.customer_base", keys=["cust_no"], comment="客户基础信息表"),
        _entity("dwd.customer_df", keys=["cust_no"], comment="客户扩展信息表"),
    )
    cards = _cards(
        _card("ods.customer_base", comment="客户基础信息表", columns=["cust_no"]),
        _card("dwd.customer_df", comment="客户扩展信息表", columns=["cust_no"]),
    )

    assert _names(ontology, cards) == [
        ("客户", NAME_FROM_TABLE_COMMENT),
        ("cust", NAME_FROM_STEM),
    ]


def test_the_key_stem_is_the_last_resort_name() -> None:
    ontology = _ontology(_entity("ods.cust_base", keys=["cust_no"]))
    cards = _cards(_card("ods.cust_base", columns=["cust_no"]))

    assert _names(ontology, cards) == [("cust", NAME_FROM_STEM)]
    assert _concepts(ontology, cards)["concept:cust"]["name"] == "cust"


def test_a_comment_that_is_only_a_suffix_names_nothing() -> None:
    ontology = _ontology(_entity("ods.cust_base", keys=["cust_no"], comment="信息表"))
    cards = _cards(_card("ods.cust_base", comment="信息表", columns=["cust_no"]))

    assert _names(ontology, cards) == [("cust", NAME_FROM_STEM)]


def test_a_comment_that_is_only_the_generic_key_word_names_nothing() -> None:
    ontology = _ontology(
        _entity(
            "ods.cust_base",
            keys=["cust_no"],
            attributes=[_attribute("cust_no", comment="编号")],
        )
    )
    cards = _cards(_card("ods.cust_base", columns=["cust_no"]))

    assert _names(ontology, cards) == [("cust", NAME_FROM_STEM)]


def test_an_english_snake_case_comment_is_kept_as_is_but_ranks_last() -> None:
    """Never mangled -- and never the name either, because it reads as a column."""
    ontology = _ontology(
        _entity(
            "ods.cust_base",
            keys=["cust_no"],
            comment="customer base table",
            attributes=[_attribute("cust_no", comment="customer_number")],
        )
    )
    cards = _cards(_card("ods.cust_base", comment="customer base table", columns=["cust_no"]))

    assert _names(ontology, cards) == [
        ("customer base table", NAME_FROM_TABLE_COMMENT),
        ("cust", NAME_FROM_STEM),
        ("customer_number", NAME_FROM_KEY_COMMENT),
    ]


@pytest.mark.parametrize(
    "comment",
    # The last three are the ones substring matching exists for: the stoplist word
    # opens the comment and something meaningless follows it.
    ["唯一标识", "主键", "unique", "UUID", "编号", "唯一键", "唯一主键", "主键id"],
)
def test_a_key_comment_that_only_says_key_names_nothing(comment: str) -> None:
    """「唯一」 and `unique` were named concepts once. They name nothing."""
    ontology = _ontology(
        _entity(
            "ods.cust_base",
            keys=["cust_no"],
            attributes=[_attribute("cust_no", comment=comment)],
        )
    )
    cards = _cards(_card("ods.cust_base", columns=["cust_no"]))

    assert _names(ontology, cards) == [("cust", NAME_FROM_STEM)]


def _key_named(comment: str, table: str = "ods.cust_base", column: str = "cust_no"):
    """The name a single key column's comment proposes, or ``None``."""
    ontology = _ontology(
        _entity(table, keys=[column], attributes=[_attribute(column, comment=comment)])
    )
    cards = _cards(_card(table, columns=[column]))
    found = [
        text
        for text, source in _names(ontology, cards, f"concept:{key_stem(column)}")
        if source == NAME_FROM_KEY_COMMENT
    ]
    return found[0] if found else None


def test_annotation_tags_come_out_of_a_comment_before_anything_is_derived() -> None:
    """A catalog stamps its own bookkeeping into the comment; none of it is a name."""
    assert _key_named("合同号 【updt:n】【Sec:D】【STD:varchar】") == "合同"
    assert _key_named("客户编号 [PII] [len:32]") == "客户"
    assert _key_named("客户编号（脱敏）") == "客户"


def test_a_tagged_table_comment_still_names_the_concept() -> None:
    ontology = _ontology(
        _entity("ods.cust_base", keys=["cust_no"], comment="客户信息表【owner:x】（合成）")
    )
    cards = _cards(
        _card("ods.cust_base", comment="客户信息表【owner:x】（合成）", columns=["cust_no"])
    )

    assert _names(ontology, cards) == [
        ("客户", NAME_FROM_TABLE_COMMENT),
        ("cust", NAME_FROM_STEM),
    ]


@pytest.mark.parametrize(
    ("comment", "expected"),
    [
        ("合同号", "合同"),
        ("客户编号", "客户"),
        ("交易流水号", "交易流水"),
        ("合同号码", "合同"),
        ("客户标识", "客户"),
        # 账号 is a word, not a thing plus a key marker.
        ("贷款账号", "贷款账号"),
        ("银行卡号", "银行卡号"),
    ],
)
def test_the_trailing_key_marker_comes_off_only_when_a_name_is_left(
    comment: str, expected: str
) -> None:
    assert _key_named(comment) == expected


def test_a_one_character_chinese_comment_is_too_short_to_be_a_name() -> None:
    ontology = _ontology(
        _entity(
            "ods.cust_base",
            keys=["cust_no"],
            attributes=[_attribute("cust_no", comment="客编号")],
        )
    )
    cards = _cards(_card("ods.cust_base", columns=["cust_no"]))

    assert _names(ontology, cards) == [("cust", NAME_FROM_STEM)]


def test_the_staging_words_come_off_a_table_comment_before_its_suffix() -> None:
    """「客户backup表_中间过程」 is 客户; the rest says where the table sits in a pipeline."""
    ontology = _ontology(_entity("ods.cust_base", keys=["cust_no"], comment="客户backup表_中间过程"))
    cards = _cards(_card("ods.cust_base", comment="客户backup表_中间过程", columns=["cust_no"]))

    assert _names(ontology, cards) == [
        ("客户", NAME_FROM_TABLE_COMMENT),
        ("cust", NAME_FROM_STEM),
    ]


def test_a_trailing_aside_comes_off_before_the_storage_suffix() -> None:
    """「渠道维表（合成）」 is 渠道: the aside hides the 维表 the suffix rule looks for."""
    ontology = _ontology(_entity("dim.channel", keys=["channel_code"], comment="渠道维表（合成）"))
    cards = _cards(_card("dim.channel", comment="渠道维表（合成）", columns=["channel_code"]))

    assert _names(ontology, cards, "concept:channel") == [
        ("渠道", NAME_FROM_TABLE_COMMENT),
        ("channel", NAME_FROM_STEM),
    ]


def test_the_table_comments_come_from_the_most_representative_members() -> None:
    """A build step's comment never competes with the snapshot's."""
    ontology = _ontology(
        _entity("dwd.cust_df", keys=["cust_no"], comment="客户信息表"),
        _entity("dwd.cust_mid01", keys=["cust_no"], comment="中间过程表"),
        _entity("dwd.cust_tmp", keys=["cust_no"], comment="跑批中间结果"),
    )
    cards = _cards(
        _card("dwd.cust_df", comment="客户信息表", columns=["cust_no"]),
        _card("dwd.cust_mid01", comment="中间过程表", columns=["cust_no"]),
        _card("dwd.cust_tmp", comment="跑批中间结果", columns=["cust_no"]),
    )

    assert _names(ontology, cards) == [
        ("客户", NAME_FROM_TABLE_COMMENT),
        ("cust", NAME_FROM_STEM),
    ]


def test_a_candidate_that_still_reads_as_a_table_name_ranks_last() -> None:
    ontology = _ontology(
        _entity(
            "ods.cust_base",
            keys=["cust_no"],
            comment="ods_cust_base",
            attributes=[_attribute("cust_no", comment="客户编号")],
        )
    )
    cards = _cards(_card("ods.cust_base", comment="ods_cust_base", columns=["cust_no"]))

    assert _names(ontology, cards)[0] == ("客户", NAME_FROM_KEY_COMMENT)
    assert _names(ontology, cards)[-1][1] == NAME_FROM_TABLE_COMMENT


def test_two_concepts_that_land_on_one_name_point_at_each_other() -> None:
    """Two stems, one proposed name: a question for the review round, not a merge.

    Merging them would take the decision away from the only party that can make it --
    the corpus proved two distinct keys, and only a person knows whether they are one
    thing spelled twice.
    """
    ontology = _ontology(
        _entity(
            "ods.contr_base",
            keys=["contr_no"],
            attributes=[_attribute("contr_no", comment="合同号")],
        ),
        _entity(
            "ods.contra_base",
            keys=["contra_no"],
            attributes=[_attribute("contra_no", comment="合同编号")],
        ),
    )
    cards = _cards(
        _card("ods.contr_base", columns=["contr_no"]),
        _card("ods.contra_base", columns=["contra_no"]),
    )

    concepts = _concepts(ontology, cards)

    assert concepts["concept:contr"]["name"] == "合同"
    assert concepts["concept:contra"]["name"] == "合同"
    assert concepts["concept:contr"]["possible_duplicate_of"] == ["concept:contra"]
    assert concepts["concept:contra"]["possible_duplicate_of"] == ["concept:contr"]


def test_a_concept_whose_name_nothing_else_claims_says_nothing_about_duplicates() -> None:
    ontology = _ontology(
        _entity(
            "ods.cust_base",
            keys=["cust_no"],
            attributes=[_attribute("cust_no", comment="客户编号")],
        )
    )
    cards = _cards(_card("ods.cust_base", columns=["cust_no"]))

    assert "possible_duplicate_of" not in _concepts(ontology, cards)["concept:cust"]


# ------------------------------------------------------- ordering and determinism


def test_concepts_are_ordered_by_member_count_then_id() -> None:
    ontology = _ontology(
        _entity("ods.alpha_base", keys=["alpha_no"]),
        _entity("ods.beta_base", keys=["beta_no"]),
        _entity("dwd.beta_df", keys=["beta_no"]),
    )
    cards = _cards(
        _card("ods.alpha_base", columns=["alpha_no"]),
        _card("ods.beta_base", columns=["beta_no"]),
        _card("dwd.beta_df", columns=["beta_no"]),
    )

    assert list(_concepts(ontology, cards)) == ["concept:beta", "concept:alpha"]


SCHEMA = {
    "ods.customer_base": ["cust_no", "cust_name", "dt"],
    "dwd.customer_df": ["cust_no", "cust_name"],
    "ods.message_send_di": ["msg_no", "cust_no", "send_time"],
}

CORPUS = (
    (
        "task_customer",
        "INSERT OVERWRITE TABLE dwd.customer_df "
        "SELECT cust_no, max(cust_name) AS cust_name FROM ods.customer_base GROUP BY cust_no",
    ),
    (
        "task_message",
        "INSERT OVERWRITE TABLE mart.message_daily "
        "SELECT m.cust_no, count(1) AS n FROM ods.message_send_di m GROUP BY m.cust_no",
    ),
)


def _built() -> dict:
    documents = []
    profiles = []
    for task, sql in CORPUS:
        document = to_lineage_dict(parse_scope_lineage(sql, task, schema=SCHEMA))
        documents.append(document)
        profiles.append(build_semantic_profile(document))
    cards = build_table_cards(profiles, artifact_root="corpus")
    return build_ontology(documents, profiles, tables=cards, artifact_root="corpus")


def test_the_ontology_document_carries_the_concept_layer() -> None:
    ontology = _built()

    assert "concepts" in ontology
    assert "unassigned_tables" in ontology
    assert [str(concept["id"]) for concept in ontology["concepts"]] == ["concept:cust"]


def test_the_concept_layer_is_byte_identical_across_two_builds() -> None:
    first = _built()
    second = _built()

    assert json.dumps(first["concepts"], ensure_ascii=False) == json.dumps(
        second["concepts"], ensure_ascii=False
    )
    assert first["unassigned_tables"] == second["unassigned_tables"]
