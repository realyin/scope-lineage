"""K4d: the six gaps a *third* concept-review round exposed.

K4b let a reviewer move a member and add one, K4c let a reviewer create a concept the
corpus never seeded and revive one a rule retired. Running the round a third time found
six more places where the layer said something the reviewer did not:

1. ``add_tables`` published every reviewed membership as ``override``, so a table a
   reviewer added as a ``reference`` -- "it merely carries this key" -- started
   answering *what that table is*, which is the one thing a reference never says;
2. the ``to`` end of an edge, asked about a table several concepts hold, refused to
   choose even when exactly one of those memberships was an identity;
3. a merge deduped a shared table into the survivor's row, quietly dropping the
   stronger role the folded side had read off it -- and folded two ``primary`` copies
   into one concept without saying so;
4. a created concept's ``key_columns`` never reached the stem index, so an edge written
   on the very column the reviewer named could not find the concept it named it for;
5. a revived stem stayed in ``retired_stems[]`` for the rest of the run, so the document
   both published the concept and said it had been refused;
6. a participation role fell back to the raw column identifier, publishing
   ``collection_unit_id`` as the name of a business role.

Rule 1 had a second half nobody checked: a ``reference`` member carries the key and is
not *described* by it, so it must lend the concept no attributes either. The seed path
honoured that; every reviewed path -- ``add_tables``, ``new_concepts`` and the merges --
folded the table's columns in anyway, so a concept ended up listing the columns of tables
that merely point at it. Those tests live in section 1 below.

Every table, column, concept, comment and name in this file is synthetic. No real
corpus, table or business name is reproduced here.
"""

from __future__ import annotations

from pathlib import Path

from scope_lineage.render.concept_relations import build_concept_relations
from scope_lineage.render.concepts import (
    BASIS_OVERRIDE,
    BASIS_REFERENCE,
    CONCEPT_ENTITY,
    CONCEPT_EVENT,
    CONCEPT_TABLE_PREFIX,
    ROLE_DETAIL,
    ROLE_PRIMARY,
    ROLE_REFERENCE,
    ROLE_SNAPSHOT,
    apply_concept_overrides,
    build_concepts,
    key_column_name,
)
from scope_lineage.render.ontology import render_ontology_appendix_markdown

from .test_concept_relations import _cards, _entity, _relation
from .test_concept_render_and_overrides import _ontology

REPO_ROOT = Path(__file__).resolve().parents[2]
REVIEW_PROMPT = (
    REPO_ROOT / "skills" / "scope-lineage" / "references" / "concept-review-prompt.md"
)

CONFIRMATION = {
    "confirmed_by": "agent:concept-review",
    "date": "2026-09-22",
    "basis": "合成语料里评审读过这张表",
}


def _built(entities, relations=(), overrides=None) -> dict:
    """The builder's own order: concepts, then the overrides, then the relation fold."""
    document = {
        "doc_format": "ontology-json/1",
        "tables": [dict(item) for item in entities],
        "table_relations": [dict(item) for item in relations],
    }
    document.update(build_concepts(document, _cards()))
    apply_concept_overrides(document, overrides or {})
    document.update(build_concept_relations(document))
    return document


def _by_id(document: dict) -> dict:
    return {str(concept["id"]): concept for concept in document["concepts"]}


def _members(concept) -> dict:
    return {str(item["table"]): item for item in concept["tables"]}


def _roles(concept) -> dict:
    return {table: str(item["role"]) for table, item in _members(concept).items()}


def _pairs(document: dict) -> list[tuple[str, str]]:
    return [
        (str(item["from"]), str(item["to"])) for item in document["relations"]
    ]


# The concepts every test below stands on, each seeded by its own business key, plus one
# table no key, no hint and no JOIN can place -- the reviewer's own case.
CUSTOMER = _entity(
    "ods.cust_base",
    keys=["cust_no"],
    columns=[("cust_no", "客户编号"), ("zone_no", "区域编码")],
    comment="客户信息表",
)
CHANNEL = _entity(
    "dim.chan_base", keys=["chan_no"], columns=[("chan_no", "渠道编码")]
)
PRODUCT = _entity(
    "dim.prod_base", keys=["prod_no"], columns=[("prod_no", "产品编码")]
)
WIDE = _entity(
    "ods.wide_rows",
    columns=[("zone_no", "区域编码"), ("prod_no", "产品编码")],
)


def _add(**adds) -> dict:
    """One ``concepts`` document that only adds tables, one entry per concept."""
    return {
        "concepts": {
            concept: {"add_tables": dict(tables), **CONFIRMATION}
            for concept, tables in adds.items()
        }
    }


# ------------------------------- 1. a reference add never says what a table IS


#: The reviewer's own reading: 宽表 *is* a copy of 客户, and it merely carries 渠道's key.
WIDE_ADDS = {
    "concept:cust": {WIDE["id"]: ROLE_DETAIL},
    "concept:chan": {WIDE["id"]: ROLE_REFERENCE},
}
#: The edge that asks what `ods.wide_rows` is.
FROM_WIDE = _relation("rel:001", WIDE["id"], ["prod_no"], PRODUCT["id"], ["prod_no"])


def test_a_reviewed_reference_add_is_published_as_a_reference_membership() -> None:
    document = _built([CUSTOMER, CHANNEL, PRODUCT, WIDE], overrides=_add(**WIDE_ADDS))

    member = _members(_by_id(document)["concept:chan"])[WIDE["id"]]
    assert member["role"] == ROLE_REFERENCE
    assert member["membership_basis"] == BASIS_REFERENCE
    # The basis is a machine token now, so who said so has to survive on the row itself.
    assert member["confirmed_by"] == CONFIRMATION["confirmed_by"]
    assert member["confirmed_basis"] == CONFIRMATION["basis"]


def test_a_reviewed_reference_add_leaves_the_tables_identity_where_it_was() -> None:
    """Added as a reference to 渠道, `ods.wide_rows` still resolves its edges to 客户."""
    document = _built(
        [CUSTOMER, CHANNEL, PRODUCT, WIDE], [FROM_WIDE], overrides=_add(**WIDE_ADDS)
    )

    assert _pairs(document) == [("concept:cust", "concept:prod")]


def test_any_other_reviewed_role_still_lends_the_table_its_identity() -> None:
    """The negative: only ``reference`` is the weak one -- ``detail`` is a membership."""
    document = _built(
        [CUSTOMER, CHANNEL, PRODUCT, WIDE],
        [FROM_WIDE],
        overrides=_add(**{**WIDE_ADDS, "concept:chan": {WIDE["id"]: ROLE_DETAIL}}),
    )

    member = _members(_by_id(document)["concept:chan"])[WIDE["id"]]
    assert member["membership_basis"] == BASIS_OVERRIDE
    # Two concepts now say what this table is, so the rule refuses to choose.
    assert _pairs(document) == []


# --- 1b. and it lends no attributes either: a reference carries the key, nothing else


#: Two keyless tables spelling the same two columns: one the reviewer reads as a copy of
#: the concept, one that merely carries its key.
DESCRIBED = _entity(
    "ods.zone_rows", columns=[("zone_no", "区域编码"), ("memo", "备注")]
)
CARRIER = _entity(
    "ods.zone_carry", columns=[("zone_no", "区域编码"), ("memo", "备注")]
)


def _attributes(concept) -> dict:
    """``{stem: {source tables}}`` for one concept's published attributes."""
    return {
        str(item["stem"]): {str(origin["table"]) for origin in item["sources"]}
        for item in concept["attributes"]
    }


def test_a_reviewed_reference_add_lends_the_concept_no_attributes() -> None:
    """The membership lands; the columns do not -- 宽表 is not what 渠道 is made of."""
    document = _built([CUSTOMER, CHANNEL, PRODUCT, WIDE], overrides=_add(**WIDE_ADDS))

    concept = _by_id(document)["concept:chan"]
    assert WIDE["id"] in _members(concept)
    assert WIDE["id"] not in {
        table for tables in _attributes(concept).values() for table in tables
    }


def test_any_other_reviewed_role_still_lends_the_concept_its_columns() -> None:
    """The negative: a ``detail`` add is a membership, and a membership describes."""
    document = _built(
        [CUSTOMER, CHANNEL, PRODUCT, WIDE],
        overrides=_add(**{"concept:chan": {WIDE["id"]: ROLE_DETAIL}}),
    )

    assert _attributes(_by_id(document)["concept:chan"])["prod"] == {WIDE["id"]}


def test_a_stem_two_members_carry_names_only_the_one_that_describes_it() -> None:
    """The reference member's column never joins ``sources[]`` of a shared stem."""
    document = _built(
        [CHANNEL, DESCRIBED, CARRIER],
        overrides=_add(
            **{
                "concept:chan": {
                    DESCRIBED["id"]: ROLE_DETAIL,
                    CARRIER["id"]: ROLE_REFERENCE,
                }
            }
        ),
    )

    attributes = _attributes(_by_id(document)["concept:chan"])
    assert attributes["zone"] == {DESCRIBED["id"]}
    assert attributes["memo"] == {DESCRIBED["id"]}


def test_a_created_concept_takes_no_columns_from_its_reference_members() -> None:
    """K4c reads the roles the same way K4b does."""
    document = _built(
        [CHANNEL, DESCRIBED, CARRIER],
        overrides={
            "new_concepts": [
                {
                    "id": "concept:zone",
                    "name": "区域",
                    "kind": CONCEPT_ENTITY,
                    "tables": {
                        DESCRIBED["id"]: ROLE_PRIMARY,
                        CARRIER["id"]: ROLE_REFERENCE,
                    },
                    **CONFIRMATION,
                }
            ]
        },
    )

    attributes = _attributes(_by_id(document)["concept:zone"])
    assert attributes["zone"] == {DESCRIBED["id"]}
    assert attributes["memo"] == {DESCRIBED["id"]}


def test_a_merge_that_upgrades_a_reference_member_makes_its_columns_count() -> None:
    """The stronger role wins the row (K4d), so the columns behind it count too."""
    document = _built(
        [CHANNEL, PRODUCT, CARRIER],
        overrides={
            "concepts": {
                "concept:chan": {"add_tables": {CARRIER["id"]: ROLE_REFERENCE}},
                "concept:prod": {
                    "add_tables": {CARRIER["id"]: ROLE_SNAPSHOT},
                    "merge_into": "concept:chan",
                    **CONFIRMATION,
                },
            }
        },
    )

    concept = _by_id(document)["concept:chan"]
    assert _roles(concept)[CARRIER["id"]] == ROLE_SNAPSHOT
    assert _attributes(concept)["memo"] == {CARRIER["id"]}


def test_a_merge_of_two_reference_memberships_still_lends_nothing() -> None:
    """The negative: only ever a reference in the survivor, so only ever the key."""
    document = _built(
        [CHANNEL, PRODUCT, CARRIER],
        overrides={
            "concepts": {
                "concept:chan": {"add_tables": {CARRIER["id"]: ROLE_REFERENCE}},
                "concept:prod": {
                    "add_tables": {CARRIER["id"]: ROLE_REFERENCE},
                    "merge_into": "concept:chan",
                    **CONFIRMATION,
                },
            }
        },
    )

    concept = _by_id(document)["concept:chan"]
    assert _roles(concept)[CARRIER["id"]] == ROLE_REFERENCE
    assert "memo" not in _attributes(concept)


# ------------------------- 2. the `to` end prefers the one identity membership


#: The edge that asks what `ods.wide_rows` is pointed *at*: the columns name nothing.
TO_WIDE = _relation("rel:002", CUSTOMER["id"], ["zone_no"], WIDE["id"], ["zone_no"])


def test_the_to_end_takes_the_one_identity_among_several_memberships() -> None:
    document = _built(
        [CUSTOMER, CHANNEL, PRODUCT, WIDE],
        [TO_WIDE],
        overrides=_add(
            **{
                "concept:prod": {WIDE["id"]: ROLE_DETAIL},
                "concept:chan": {WIDE["id"]: ROLE_REFERENCE},
            }
        ),
    )

    assert _pairs(document) == [("concept:cust", "concept:prod")]


def test_several_identity_memberships_leave_the_to_end_to_the_stem_rule() -> None:
    """The negative: the rule exists because there was nothing to choose between."""
    document = _built(
        [CUSTOMER, CHANNEL, PRODUCT, WIDE],
        [TO_WIDE],
        overrides=_add(
            **{
                "concept:prod": {WIDE["id"]: ROLE_DETAIL},
                "concept:chan": {WIDE["id"]: ROLE_DETAIL},
            }
        ),
    )

    # Two reviewed identities dissolved the table's provisional concept (M1), and left
    # nothing to choose between -- the one shape that can still leave a `to` end open.
    assert _pairs(document) == []
    assert document["concept_relations_unmapped"]["by_reason"]["to_table_unplaced"] == 1


def test_several_references_and_no_identity_leave_the_to_end_to_the_stem_rule() -> None:
    """The negative twin: carrying two keys says nothing about what the table is."""
    document = _built(
        [CUSTOMER, CHANNEL, PRODUCT, WIDE],
        [TO_WIDE],
        overrides=_add(
            **{
                "concept:prod": {WIDE["id"]: ROLE_REFERENCE},
                "concept:chan": {WIDE["id"]: ROLE_REFERENCE},
            }
        ),
    )

    # A reviewed `reference` add says nothing about what the table is, so M1's
    # provisional concept is still standing and is what the `to` end falls back to.
    assert _pairs(document) == [("concept:cust", f"{CONCEPT_TABLE_PREFIX}ods_wide_rows")]
    assert document["concept_relations_unmapped"]["by_reason"]["to_table_unplaced"] == 0


# ---------------------------------- 3. a merge keeps the stronger role, and warns


CLIENT = _entity(
    "ods.client_base", keys=["client_no"], columns=[("client_no", "往来方编号")]
)
#: A copy of 往来方 that also carries 客户's key: a member of one and a reference of the
#: other, which is exactly the table a merge has to read twice.
CLIENT_SNAPSHOT = _entity(
    "ods.client_ext_di",
    keys=["client_no"],
    columns=[("client_no", "往来方编号"), ("cust_no", "客户编号")],
)
SHARED_EDGE = _relation(
    "rel:003", CLIENT_SNAPSHOT["id"], ["cust_no"], CUSTOMER["id"], ["cust_no"]
)
MERGE_CORPUS = (CUSTOMER, CLIENT, CLIENT_SNAPSHOT)


def _merge(source: str, target: str, **extra) -> dict:
    return {"concepts": {source: {"merge_into": target, **CONFIRMATION, **extra}}}


def test_the_merge_corpus_reads_the_two_roles_the_rule_is_about() -> None:
    """A guard on the fixtures: the rule is only readable if these roles hold."""
    document = _built(MERGE_CORPUS, [SHARED_EDGE])

    assert _roles(_by_id(document)["concept:cust"]) == {
        CUSTOMER["id"]: ROLE_PRIMARY,
        CLIENT_SNAPSHOT["id"]: ROLE_REFERENCE,
    }
    assert _roles(_by_id(document)["concept:client"]) == {
        CLIENT["id"]: ROLE_PRIMARY,
        CLIENT_SNAPSHOT["id"]: ROLE_SNAPSHOT,
    }


def test_a_merge_keeps_the_stronger_role_a_shared_table_was_read_in() -> None:
    document = _built(
        MERGE_CORPUS, [SHARED_EDGE], overrides=_merge("concept:client", "concept:cust")
    )

    assert _roles(_by_id(document)["concept:cust"]) == {
        CUSTOMER["id"]: ROLE_PRIMARY,
        CLIENT["id"]: ROLE_PRIMARY,
        CLIENT_SNAPSHOT["id"]: ROLE_SNAPSHOT,
    }


def test_a_merge_never_weakens_a_role_the_survivor_already_read() -> None:
    """The negative, written the other way round: the survivor's snapshot survives."""
    document = _built(
        MERGE_CORPUS, [SHARED_EDGE], overrides=_merge("concept:cust", "concept:client")
    )

    assert _roles(_by_id(document)["concept:client"])[CLIENT_SNAPSHOT["id"]] == (
        ROLE_SNAPSHOT
    )


def test_a_merge_that_folds_two_primaries_says_so() -> None:
    """Both copies stay -- and the direction is the reviewer's to fix, so it is named."""
    document = _built(
        MERGE_CORPUS, [SHARED_EDGE], overrides=_merge("concept:client", "concept:cust")
    )

    assert document["concept_overrides_applied"]["warnings"] == [
        {
            "key": "concept:client",
            "warning": (
                f"merge_kept_two_primaries: {CLIENT['id']}, {CUSTOMER['id']}"
            ),
        }
    ]


def test_a_merge_whose_source_has_no_primary_left_warns_about_nothing() -> None:
    """The negative: the reviewer demoted the folded side's copy, so there is one."""
    document = _built(
        MERGE_CORPUS,
        [SHARED_EDGE],
        overrides=_merge(
            "concept:client", "concept:cust", roles={CLIENT["id"]: ROLE_DETAIL}
        ),
    )

    assert document["concept_overrides_applied"]["warnings"] == []
    assert document["concept_overrides_applied"]["merges"] == 1


# ------------------------------- 4. a created concept's key columns reach the index


SLOT = _entity("ods.slot_base", columns=[("ad_slot_code", "广告位编码")])
#: A table nothing identifies, reached on the very column the reviewer named.
SLOT_REF = _entity(
    "ods.slot_rows", columns=[("ad_slot_code", "广告位编码"), ("dt", None)]
)


def _slot(key_columns) -> dict:
    return {
        "new_concepts": [
            {
                "id": "concept:slot",
                "name": "广告位",
                "kind": CONCEPT_ENTITY,
                "tables": {SLOT["id"]: ROLE_PRIMARY},
                "key_columns": list(key_columns),
                **CONFIRMATION,
            }
        ]
    }


def _on(column: str) -> list:
    return [_relation("rel:004", CUSTOMER["id"], [column], SLOT_REF["id"], [column])]


def test_a_created_concepts_key_columns_answer_for_an_edge_written_on_them() -> None:
    """``concept:slot`` is not the stem of ``ad_slot_code`` -- the entry said it is."""
    document = _built(
        [CUSTOMER, SLOT, SLOT_REF],
        _on("ad_slot_code"),
        overrides=_slot(["ad_slot_code"]),
    )

    assert _pairs(document) == [("concept:cust", "concept:slot")]
    assert _by_id(document)["concept:slot"]["identity"]["merged_stems"] == ["ad_slot"]


def test_a_column_the_created_entry_never_named_reaches_nothing() -> None:
    """The negative: only the columns the reviewer wrote down join the index."""
    document = _built(
        [CUSTOMER, SLOT, SLOT_REF], _on("ad_slot_code"), overrides=_slot(["slot_id"])
    )

    # M1: nothing named the far table, so the edge reaches its provisional concept.
    assert _pairs(document) == [("concept:cust", f"{CONCEPT_TABLE_PREFIX}ods_slot_rows")]
    assert _by_id(document)["concept:slot"]["identity"]["merged_stems"] == []


def test_a_created_entrys_generic_key_column_never_joins_the_index() -> None:
    """The negative twin: ``dt`` identifies a row without naming a thing, here too."""
    document = _built(
        [CUSTOMER, SLOT, SLOT_REF], _on("dt"), overrides=_slot(["ad_slot_code", "dt"])
    )

    # M1: `dt` reaches nothing, so the edge folds onto the far table's own concept.
    assert _pairs(document) == [("concept:cust", f"{CONCEPT_TABLE_PREFIX}ods_slot_rows")]
    assert _by_id(document)["concept:slot"]["identity"]["merged_stems"] == ["ad_slot"]


# --------------------------------- 5. a revived stem stops being a retired one


ROW_A = _entity("ods.rows_a", keys=["rowkey"], columns=[("rowkey", "行键")])
ROW_B = _entity("ods.rows_b", keys=["rowkey"], columns=[("rowkey", "行键")])
REQ_A = _entity("ods.req_a", keys=["req_id"], columns=[("req_id", "请求标识")])
REVIVE = {
    "concepts": {"concept:rowkey": {"name": "行记录", "kind": CONCEPT_EVENT, **CONFIRMATION}}
}


def test_a_revived_stem_is_no_longer_a_retired_one() -> None:
    """One run cannot both publish the concept and say the stem was refused."""
    document = _built([CUSTOMER, ROW_A, ROW_B, REQ_A], overrides=REVIVE)

    assert [str(item["stem"]) for item in document["retired_stems"]] == ["req"]
    assert document["concept_overrides_applied"]["created"] == [
        {"id": "concept:rowkey", "tables": [ROW_A["id"], ROW_B["id"]], "revived": True}
    ]


def test_a_stem_nobody_revived_stays_retired() -> None:
    """The negative: the other refused stem is still a question for the next round."""
    document = _built([CUSTOMER, ROW_A, ROW_B, REQ_A])

    assert [str(item["stem"]) for item in document["retired_stems"]] == [
        "req",
        "rowkey",
    ]


def test_the_appendix_stops_naming_a_stem_that_came_back() -> None:
    document = _built([CUSTOMER, ROW_A, ROW_B, REQ_A], overrides=REVIVE)

    text = render_ontology_appendix_markdown(
        {
            **_ontology(concepts=document["concepts"]),
            "retired_stems": document["retired_stems"],
        }
    )

    retired = text.split("### 退役键词根")[1].split("\n### ")[0]
    assert "`req`" in retired
    assert "`rowkey`" not in retired


# --------------------------- 6. a participation role is never a raw column name


EVENT = _entity(
    "dwd.msg_send_di",
    keys=["msg_id"],
    columns=[
        ("msg_id", None),
        ("send_party_no", "发送方编号"),
        ("collection_unit_id", None),
        ("collectionUnit", None),
        ("回收单位", None),
        ("openId", "openId"),
        ("trace_node_code", "ID"),
    ],
    comment="消息发送流水表",
)


def _participation_roles(column: str) -> list[str]:
    document = _built(
        [CUSTOMER, EVENT],
        [_relation("rel:005", EVENT["id"], [column], CUSTOMER["id"], ["cust_no"])],
    )
    relation = document["relations"][0]
    assert (str(relation["from"]), str(relation["to"])) == (
        "concept:msg",
        "concept:cust",
    )
    return list(relation["roles"])


def test_a_role_is_read_off_the_column_comment_when_there_is_one() -> None:
    assert _participation_roles("send_party_no") == ["发送方"]


def test_a_role_falls_back_to_the_column_name_as_words_never_the_identifier() -> None:
    assert _participation_roles("collection_unit_id") == ["collection unit"]


def test_a_camel_case_column_name_is_split_into_words() -> None:
    assert _participation_roles("collectionUnit") == ["collection unit"]


def test_a_cjk_column_name_is_used_as_it_stands() -> None:
    assert _participation_roles("回收单位") == ["回收单位"]


def test_the_column_name_reading_never_publishes_a_raw_identifier() -> None:
    """The negative, spelled on the helper: nothing it returns is an identifier."""
    assert key_column_name("collection_unit_id") == "collection unit"
    assert key_column_name("cust_no") == "cust"
    assert key_column_name("") == ""


def test_a_camel_hump_is_a_word_and_never_a_key_marker() -> None:
    """The markers come off the segments `_` marked, exactly as ``key_stem`` reads them.

    A camelCase hump is not a segment the warehouse marked, so `openId` is one word the
    warehouse wrote and reading it as `open` would throw half of it away.
    """
    assert key_column_name("openId") == "open id"
    assert key_column_name("collectionUnit") == "collection unit"
    assert key_column_name("trace_node_code") == "trace node"
    assert key_column_name("senderPartyNo") == "sender party no"


def test_a_comment_that_only_repeats_the_column_falls_through_to_the_name() -> None:
    """A catalog that fills every comment with the identifier answers nothing."""
    assert _participation_roles("openId") == ["open id"]


def test_a_comment_that_is_only_a_key_marker_falls_through_to_the_name() -> None:
    """The other half of the same gap: 「ID」 says the comment named nothing."""
    assert _participation_roles("trace_node_code") == ["trace node"]


# -------------------------------------------- the prompt says which way to merge


def test_the_prompt_says_to_merge_the_side_with_fewer_primaries() -> None:
    """The warning is only actionable if the prompt says what to do about it."""
    text = REVIEW_PROMPT.read_text(encoding="utf-8")

    assert "merge_kept_two_primaries" in text
