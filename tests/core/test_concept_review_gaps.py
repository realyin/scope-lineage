"""K4b: the five gaps a real concept-review round exposed.

K4 shipped the concept layer's render and its ``concepts.overrides.json`` round trip.
Running one review round over a real corpus found five things the round could not say:

1. a reviewer who knows a table belongs to a concept had no way to put it there --
   ``roles`` moves a member, nothing *added* one;
2. a key column that is a log id (``rowkey``, a digest, a snowflake) seeded a concept
   per spelling, so three unrelated tables grew one "concept" out of their row ids;
3. the 概念 table printed the name without its tier, so a confirmed name and an
   author's guess read the same;
4. the ``to`` end of an edge read the join column's stem even when the corpus had
   already placed that table on a concept of its own;
5. the review prompt said a word-hint-only kind was both worth asking a person and
   not worth asking.

Every table, column, concept and name in this file is synthetic. No real corpus, table
or business name is reproduced here.
"""

from __future__ import annotations

from pathlib import Path

from scope_lineage.render.concept_relations import build_concept_relations
from scope_lineage.render.concepts import (
    BASIS_OVERRIDE,
    BASIS_REFERENCE,
    CONCEPT_TABLE_PREFIX,
    GENERIC_STEMS,
    NAME_FROM_OVERRIDE,
    ROLE_DETAIL,
    TIER_CONFIRMED,
    TIER_HYPOTHESIS,
    TIER_PROVISIONAL,
    apply_concept_overrides,
    build_concepts,
    table_concept_id,
)
from scope_lineage.render.ontology import render_ontology_index_markdown

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


def _pairs(document: dict) -> list[tuple[str, str]]:
    return [
        (str(item["from"]), str(item["to"]))
        for item in document["relations"]
    ]


# The concepts the tests below stand on, each seeded by its own business key.
CUSTOMER = _entity(
    "ods.cust_base", keys=["cust_no"], columns=[("cust_no", "客户编号")]
)
CONTRACT = _entity(
    "ods.contr_base",
    keys=["contr_no"],
    columns=[("contr_no", "合同编号"), ("cust_no", "客户编号")],
)
APPLICATION = _entity(
    "ods.appl_base",
    keys=["appl_no"],
    columns=[("appl_no", "申请编号"), ("cust_no", "客户编号")],
)


# --------------------------------------------------- 1. add a member by override


def test_a_reviewed_add_tables_puts_an_unplaced_table_on_the_concept() -> None:
    """The reviewer knows what the corpus could not read, and now has a way to say so."""
    extra = _entity(
        "ods.cust_extra", columns=[("cust_level", "客户等级"), ("open_dt", None)]
    )

    document = _built(
        [CUSTOMER, extra],
        overrides={
            "concepts": {
                "concept:cust": {
                    "add_tables": {extra["id"]: ROLE_DETAIL},
                    **CONFIRMATION,
                }
            }
        },
    )

    member = _members(_by_id(document)["concept:cust"])[extra["id"]]
    assert member["role"] == ROLE_DETAIL
    assert member["role_tier"] == TIER_CONFIRMED
    assert member["membership_basis"] == BASIS_OVERRIDE
    assert document["concept_overrides_applied"]["tables_added"] == 1
    assert table_concept_id(extra["id"]) not in _by_id(document)


def test_an_added_table_lends_the_concept_its_own_attributes() -> None:
    extra = _entity("ods.cust_extra", columns=[("cust_level", "客户等级")])

    document = _built(
        [CUSTOMER, extra],
        overrides={
            "concepts": {"concept:cust": {"add_tables": {extra["id"]: ROLE_DETAIL}}}
        },
    )

    attributes = {
        str(item["stem"]): item for item in _by_id(document)["concept:cust"]["attributes"]
    }
    assert "cust_level" in attributes
    assert {"table": extra["id"], "column": "cust_level"} in attributes["cust_level"][
        "sources"
    ]


def test_an_added_table_is_placed_before_the_fold_so_its_joins_resolve() -> None:
    """A table only a JOIN reached has no identity, so its own edges say nothing.

    ``ods.contr_ext`` carries ``cust_no`` and nothing else the corpus can key it by, so
    K1 publishes it as a ``reference`` member of 客户 and the `from` end of its edges
    falls back to M1's provisional concept -- the corpus saying it cannot read the
    table. The reviewer knows it is a 合同 detail table; saying so has to land *before*
    the fold, or the edge stays on that provisional id.
    """
    detail = _entity("ods.contr_ext", columns=[("cust_no", "客户编号")])
    edge = _relation("rel:001", detail["id"], ["cust_no"], CUSTOMER["id"], ["cust_no"])

    without = _built([CUSTOMER, CONTRACT, detail], [edge])
    with_override = _built(
        [CUSTOMER, CONTRACT, detail],
        [edge],
        overrides={
            "concepts": {"concept:contr": {"add_tables": {detail["id"]: ROLE_DETAIL}}}
        },
    )

    assert _pairs(without) == [(f"{CONCEPT_TABLE_PREFIX}ods_contr_ext", "concept:cust")]
    assert without["concept_relations_unmapped"]["total"] == 0
    assert _pairs(with_override) == [("concept:contr", "concept:cust")]


def test_adding_a_table_that_is_already_identified_elsewhere_never_steals_it() -> None:
    """One identity membership at most: the second addition only carries the key."""
    edge = _relation(
        "rel:001", CUSTOMER["id"], ["appl_no"], APPLICATION["id"], ["appl_no"]
    )

    document = _built(
        [CUSTOMER, CONTRACT, APPLICATION],
        [edge],
        overrides={
            "concepts": {
                "concept:contr": {"add_tables": {CUSTOMER["id"]: ROLE_DETAIL}}
            }
        },
    )

    assert _members(_by_id(document)["concept:contr"])[CUSTOMER["id"]][
        "membership_basis"
    ] == BASIS_OVERRIDE
    # 客户 is still what `ods.cust_base` *is*, so its own edge still starts there.
    assert _pairs(document) == [("concept:cust", "concept:appl")]


def test_an_add_tables_entry_naming_nothing_the_corpus_holds_is_reported() -> None:
    document = _built(
        [CUSTOMER],
        overrides={
            "concepts": {
                "concept:cust": {
                    "add_tables": {"ods.absent": ROLE_DETAIL, CUSTOMER["id"]: "主表"}
                }
            }
        },
    )

    applied = document["concept_overrides_applied"]
    assert applied["tables_added"] == 0
    assert applied["unmatched"] == [
        {"key": "concept:cust", "reason": "unknown_role: 主表"},
        {"key": "concept:cust", "reason": "unknown_table: ods.absent"},
    ]
    assert len(_by_id(document)["concept:cust"]["tables"]) == 1


# ------------------------------------------------------ 2. log ids are generic


def test_three_tables_sharing_only_a_rowkey_grow_no_concept() -> None:
    """A row id is how a log identifies a row, never what the rows are *of*."""
    entities = [
        _entity(f"ods.rows_{name}", keys=["rowkey"]) for name in ("a", "b", "c")
    ]

    document = _built(entities)

    # M1: each table is published as a concept of its own instead, which is a question
    # about that one table -- never a `rowkey` concept the three of them share.
    assert [str(item["tier"]) for item in document["concepts"]] == [TIER_PROVISIONAL] * 3
    assert [str(item["id"]) for item in document["concepts"]] == [
        f"{CONCEPT_TABLE_PREFIX}ods_rows_{name}" for name in ("a", "b", "c")
    ]


def test_a_key_column_whose_comment_says_it_is_a_log_id_seeds_nothing() -> None:
    generated = _entity(
        "ods.trace_base", keys=["biz_no"], columns=[("biz_no", "日志ID（md5 摘要）")]
    )

    document = _built([generated])

    assert [str(item["id"]) for item in document["concepts"]] == [
        f"{CONCEPT_TABLE_PREFIX}ods_trace_base"
    ]
    assert str(document["concepts"][0]["tier"]) == TIER_PROVISIONAL


def test_a_log_id_beside_a_business_key_still_identifies_the_event() -> None:
    """The negative: ``rowkey`` never seeds, and it never stops a real key seeding."""
    event = _entity(
        "dwd.cust_evt_di",
        keys=["cust_no", "rowkey"],
        columns=[("cust_no", "客户编号"), ("rowkey", "行键")],
    )

    document = _built([event])

    concept = _by_id(document)["concept:cust"]
    assert concept["identity"]["stem"] == "cust"
    assert _members(concept)[event["id"]]["key_columns"] == ["cust_no", "rowkey"]


def test_a_business_key_comment_is_not_read_as_a_log_id() -> None:
    document = _built([CUSTOMER])

    assert list(_by_id(document)) == ["concept:cust"]
    assert "cust" not in GENERIC_STEMS


def test_a_comment_saying_only_that_the_value_is_a_uuid_still_seeds() -> None:
    """The negative on the comment rule: how a key *looks* is not what it identifies.

    ``UUID`` is already a name stoplist word -- the comment names nothing, so the
    concept is named after its stem -- and a ``cust_no`` whose values happen to be
    uuids is still 客户's key.
    """
    formatted = _entity("ods.cust_uid", keys=["cust_no"], columns=[("cust_no", "UUID")])

    document = _built([formatted])

    assert list(_by_id(document)) == ["concept:cust"]


# ------------------------------------------------------- 3. the name's tier shows


def test_the_concept_table_prints_the_name_with_its_tier() -> None:
    document = _built([CONTRACT])

    text = render_ontology_index_markdown(_ontology(concepts=document["concepts"]))

    assert f"| 合同（`{TIER_HYPOTHESIS}`） |" in text


def test_a_confirmed_name_leads_the_candidates_and_prints_its_tier() -> None:
    document = _built(
        [CONTRACT],
        overrides={
            "concepts": {"concept:contr": {"name": "授信合同", **CONFIRMATION}}
        },
    )

    concept = _by_id(document)["concept:contr"]
    assert concept["name_candidates"][0] == {
        "text": "授信合同",
        "source": NAME_FROM_OVERRIDE,
        "count": 1,
        "name_evidence": [],
    }
    text = render_ontology_index_markdown(_ontology(concepts=[concept]))
    assert f"| 授信合同（`{TIER_CONFIRMED}`） |" in text


def test_an_unconfirmed_name_gains_no_override_candidate() -> None:
    document = _built([CONTRACT])

    sources = {
        str(item["source"])
        for item in _by_id(document)["concept:contr"]["name_candidates"]
    }
    assert NAME_FROM_OVERRIDE not in sources


# ------------------------------------------- 4. the `to` end prefers a membership


def test_the_to_end_prefers_what_the_corpus_placed_that_table_on() -> None:
    """申请 JOIN 合同 on ``cust_no`` points at 合同, not at 客户.

    The join columns name 客户 -- both tables carry that key, which is why the JOIN
    could be written -- but the corpus already placed the ``to`` table on 合同, and
    what a table *is* outranks what one edge's columns are spelled.
    """
    document = _built(
        [CUSTOMER, CONTRACT, APPLICATION],
        [
            _relation(
                "rel:001", APPLICATION["id"], ["cust_no"], CONTRACT["id"], ["cust_no"]
            )
        ],
    )

    assert _pairs(document) == [("concept:appl", "concept:contr")]


def test_the_stem_still_answers_for_a_to_table_no_concept_holds() -> None:
    """The negative: no membership, so the join columns are all there is to read."""
    orphan = _entity("ods.rows_a", columns=[("cust_no", "客户编号")])

    document = _built(
        [CUSTOMER, CONTRACT, orphan],
        [
            _relation(
                "rel:001", CONTRACT["id"], ["cust_no"], orphan["id"], ["cust_no"]
            )
        ],
    )

    assert _pairs(document) == [("concept:contr", "concept:cust")]


def test_a_reference_membership_also_answers_the_to_end() -> None:
    """A table only a JOIN reached is still spoken for, once the stem says nothing new.

    The columns name 客户, which is what the ``from`` table already is -- so the one
    membership a JOIN lent the ``to`` table answers instead of publishing 客户 → 客户.
    """
    carrier = _entity("ods.contr_ext", columns=[("contr_no", "合同编号")])

    document = _built(
        [CUSTOMER, CONTRACT, carrier],
        [
            _relation(
                "rel:001", carrier["id"], ["contr_no"], CONTRACT["id"], ["contr_no"]
            ),
            _relation(
                "rel:002", CUSTOMER["id"], ["cust_no"], carrier["id"], ["cust_no"]
            ),
        ],
    )

    assert _members(_by_id(document)["concept:contr"])[carrier["id"]][
        "membership_basis"
    ] == BASIS_REFERENCE
    assert ("concept:cust", "concept:contr") in _pairs(document)


# ------------------------------------------------ 5. the prompt's rule collision


def _prompt() -> str:
    return REVIEW_PROMPT.read_text(encoding="utf-8")


def test_the_prompt_makes_a_word_hint_only_kind_confirmable_when_the_hints_agree() -> None:
    text = _prompt()

    assert "仅词汇线索一致" in text
    assert "全部证据只有 `word_hint`" not in text


def test_the_prompt_self_check_carries_a_row_for_the_word_hint_rule() -> None:
    rows = [
        line
        for line in _prompt().splitlines()
        if line.startswith("| ") and "word_hint" in line
    ]

    assert any("仅词汇线索一致" in row for row in rows)
