"""K4c: the five gaps a *second* concept-review round exposed.

K4b gave the review round a way to move a member, to stop a log id seeding a concept,
to read a name's tier off the page and to prefer what a table *is* over what one edge's
columns spell. Running the round again found five more things it could not say:

1. a reviewer who knows the corpus holds a concept **no key could seed** had no way to
   publish it -- ``add_tables`` needs a concept to add to;
2. a stem a generic rule refuses is forgotten, so a reviewer's earlier answers about it
   stop being addressable the moment that rule changes;
3. an edge that never travels on the concept's key -- a table joined to itself on
   something else, or a table that merely *carries* the key -- folded into a relation
   the business does not have;
4. the prompt had no evidence row for the table comment that names the concept *and*
   its grain, which is exactly what a role or a membership is read off;
5. ``concept_relations_unmapped`` counted reasons with no denominator, so two runs of
   one corpus could not be compared.

Every table, column, concept and name in this file is synthetic. No real corpus, table
or business name is reproduced here.
"""

from __future__ import annotations

import json
from pathlib import Path

from scope_lineage.cli import main
from scope_lineage.render.concept_relations import (
    UNMAPPED_REFERENCE_ONLY,
    TYPE_PARTICIPATION,
    TYPE_SELF_REFERENCE,
    build_concept_relations,
)
from scope_lineage.render.concepts import (
    BASIS_OVERRIDE,
    CONCEPT_ENTITY,
    CONCEPT_EVENT,
    CONCEPT_OVERRIDES_DOC_FORMAT,
    CONCEPT_TABLE_PREFIX,
    NAME_FROM_OVERRIDE,
    ROLE_DETAIL,
    ROLE_PRIMARY,
    ROLE_REFERENCE,
    TIER_CONFIRMED,
    apply_concept_overrides,
    build_concepts,
)

from scope_lineage.render.ontology import render_ontology_index_markdown

from .test_concept_relations import _cards, _entity, _relation
from .test_concept_render_and_overrides import _cli_corpus, _ontology

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
        "entities": [dict(item) for item in entities],
        "relations": [dict(item) for item in relations],
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
        (str(item["from"]), str(item["to"])) for item in document["concept_relations"]
    ]


def _reasons(document: dict) -> dict:
    return dict(document["concept_relations_unmapped"]["by_reason"])


# The concepts the tests below stand on, each seeded by its own business key.
CUSTOMER = _entity(
    "ods.cust_base",
    keys=["cust_no"],
    columns=[("cust_no", "客户编号"), ("zone_no", "区域编码")],
)
CONTRACT = _entity(
    "ods.contr_base",
    keys=["contr_no"],
    columns=[("contr_no", "合同编号"), ("cust_no", "客户编号")],
)
# A table no key, no hint and no JOIN can place: the reviewer's own case.
PARTY = _entity("ods.party_base", columns=[("party_name", "往来方名称")])


def _new_entry(identifier: str, tables: dict, **extra) -> dict:
    return {
        "new_concepts": [
            {
                "id": identifier,
                "name": extra.pop("name", "往来方"),
                "kind": extra.pop("kind", CONCEPT_ENTITY),
                "tables": dict(tables),
                **CONFIRMATION,
                **extra,
            }
        ]
    }


# ------------------------------------------- 1. a concept the overrides created


def test_a_reviewed_new_concept_is_published_with_its_members() -> None:
    """No key seeded it, no JOIN reached it -- a person said it is there."""
    document = _built(
        [CUSTOMER, PARTY],
        overrides=_new_entry("concept:party", {PARTY["id"]: ROLE_PRIMARY}),
    )

    concept = _by_id(document)["concept:party"]
    assert concept["name"] == "往来方" and concept["name_tier"] == TIER_CONFIRMED
    assert concept["name_candidates"][0]["source"] == NAME_FROM_OVERRIDE
    assert concept["kind"] == CONCEPT_ENTITY and concept["kind_tier"] == TIER_CONFIRMED
    assert concept["identity"]["stem"] == "party"
    assert concept["tier"] == TIER_CONFIRMED
    assert concept["origin"] == BASIS_OVERRIDE
    assert concept["confirmation"]["confirmed_by"] == CONFIRMATION["confirmed_by"]
    member = _members(concept)[PARTY["id"]]
    assert member["role"] == ROLE_PRIMARY
    assert member["membership_basis"] == BASIS_OVERRIDE
    assert member["role_tier"] == TIER_CONFIRMED


def test_a_created_concept_is_reported_and_leaves_its_tables_placed() -> None:
    document = _built(
        [CUSTOMER, PARTY],
        overrides=_new_entry("concept:party", {PARTY["id"]: ROLE_PRIMARY}),
    )

    applied = document["concept_overrides_applied"]
    assert applied["created"] == [{"id": "concept:party", "tables": [PARTY["id"]]}]
    assert applied["unmatched"] == []
    assert PARTY["id"] not in {
        str(item["table"]) for item in document["unassigned_tables"]
    }


def test_a_created_concept_takes_the_key_columns_the_reviewer_named() -> None:
    document = _built(
        [CUSTOMER, PARTY],
        overrides=_new_entry(
            "concept:party", {PARTY["id"]: ROLE_PRIMARY}, key_columns=["party_name"]
        ),
    )

    assert _by_id(document)["concept:party"]["identity"]["columns_seen"] == [
        "party_name"
    ]


def test_a_created_concept_falls_back_to_the_key_columns_its_tables_share() -> None:
    """Nobody named the columns, so the concept is identified by what the tables are."""
    first = _entity("ods.rows_x", keys=["rowkey"], columns=[("rowkey", "行键")])
    second = _entity(
        "ods.rows_y", keys=["rowkey", "dt"], columns=[("rowkey", "行键"), ("dt", None)]
    )

    document = _built(
        [first, second],
        overrides=_new_entry(
            "concept:trade_party",
            {first["id"]: ROLE_PRIMARY, second["id"]: ROLE_DETAIL},
        ),
    )

    assert _by_id(document)["concept:trade_party"]["identity"]["columns_seen"] == [
        "rowkey"
    ]


def test_a_created_concept_carries_its_members_attributes() -> None:
    document = _built(
        [CUSTOMER, PARTY],
        overrides=_new_entry("concept:party", {PARTY["id"]: ROLE_PRIMARY}),
    )

    attributes = {
        str(item["stem"]): item
        for item in _by_id(document)["concept:party"]["attributes"]
    }
    assert {"table": PARTY["id"], "column": "party_name"} in attributes["party_name"][
        "sources"
    ]


def test_a_created_concept_lands_before_the_relations_fold() -> None:
    """The edge that starts at the created concept's table has to reach the fold."""
    edge = _relation("rel:001", PARTY["id"], ["cust_no"], CUSTOMER["id"], ["cust_no"])
    carrier = _entity(
        "ods.party_base",
        columns=[("party_name", "往来方名称"), ("cust_no", "客户编号")],
    )

    without = _built([CUSTOMER, carrier], [edge])
    created = _built(
        [CUSTOMER, carrier],
        [edge],
        overrides=_new_entry("concept:party", {carrier["id"]: ROLE_PRIMARY}),
    )

    # M1: without the entry the edge folds onto the table's own provisional concept --
    # the corpus saying it could not read the table. The entry is what names the thing.
    assert _pairs(without) == [(f"{CONCEPT_TABLE_PREFIX}ods_party_base", "concept:cust")]
    assert _pairs(created) == [("concept:party", "concept:cust")]


def test_a_new_concept_reusing_a_published_id_is_reported() -> None:
    document = _built(
        [CUSTOMER, PARTY],
        overrides=_new_entry("concept:cust", {PARTY["id"]: ROLE_PRIMARY}),
    )

    applied = document["concept_overrides_applied"]
    assert applied["created"] == []
    assert applied["unmatched"] == [
        {"key": "concept:cust", "reason": "already_a_concept: concept:cust"}
    ]


def test_a_new_concept_id_that_is_not_slug_shaped_is_reported() -> None:
    document = _built(
        [CUSTOMER, PARTY],
        overrides=_new_entry("concept:Party Base", {PARTY["id"]: ROLE_PRIMARY}),
    )

    applied = document["concept_overrides_applied"]
    assert applied["created"] == []
    assert applied["unmatched"] == [
        {"key": "concept:Party Base", "reason": "invalid_concept_id: concept:Party Base"}
    ]


def test_a_new_concept_never_takes_a_table_another_concept_identifies() -> None:
    document = _built(
        [CUSTOMER, PARTY],
        overrides=_new_entry(
            "concept:party",
            {PARTY["id"]: ROLE_PRIMARY, CUSTOMER["id"]: ROLE_DETAIL},
        ),
    )

    applied = document["concept_overrides_applied"]
    assert applied["unmatched"] == [
        {"key": "concept:party", "reason": f"already_a_member: {CUSTOMER['id']}"}
    ]
    assert list(_members(_by_id(document)["concept:party"])) == [PARTY["id"]]


def test_a_reference_role_may_name_a_table_another_concept_identifies() -> None:
    """The negative: carrying a key is not being identified by it, so it is allowed."""
    document = _built(
        [CUSTOMER, PARTY],
        overrides=_new_entry(
            "concept:party",
            {PARTY["id"]: ROLE_PRIMARY, CUSTOMER["id"]: ROLE_REFERENCE},
        ),
    )

    assert document["concept_overrides_applied"]["unmatched"] == []
    assert set(_members(_by_id(document)["concept:party"])) == {
        PARTY["id"],
        CUSTOMER["id"],
    }
    # 客户 is still what `ods.cust_base` *is*.
    assert CUSTOMER["id"] in _members(_by_id(document)["concept:cust"])


def test_a_new_concept_naming_a_table_the_corpus_lacks_is_reported() -> None:
    document = _built(
        [CUSTOMER],
        overrides=_new_entry("concept:party", {"ods.absent": ROLE_PRIMARY}),
    )

    assert document["concept_overrides_applied"]["unmatched"] == [
        {"key": "concept:party", "reason": "unknown_table: ods.absent"}
    ]
    assert "concept:party" not in _by_id(document)


# --------------------------------------- 2. a retired stem stays addressable


ROW_A = _entity("ods.rows_a", keys=["rowkey"], columns=[("rowkey", "行键")])
ROW_B = _entity("ods.rows_b", keys=["rowkey"], columns=[("rowkey", "行键")])


def test_a_stem_a_generic_rule_refused_is_published_as_retired() -> None:
    """It really is a candidate key here: only the rule says it names nothing."""
    document = _built([CUSTOMER, ROW_A, ROW_B])

    assert document["retired_stems"] == [
        {
            "stem": "rowkey",
            "tables": [
                {"table": ROW_A["id"], "role": ROLE_PRIMARY, "key_columns": ["rowkey"]},
                {"table": ROW_B["id"], "role": ROLE_PRIMARY, "key_columns": ["rowkey"]},
            ],
        }
    ]


def test_a_stem_that_still_seeds_a_concept_is_never_retired() -> None:
    """The negative: 客户 seeds, so nothing about it was retired."""
    document = _built([CUSTOMER, ROW_A])

    assert [str(item["stem"]) for item in document["retired_stems"]] == ["rowkey"]


def test_an_override_addressed_to_a_retired_stem_revives_the_concept() -> None:
    """This is how a reviewer's earlier answer survives a generic-rule change."""
    document = _built(
        [CUSTOMER, ROW_A, ROW_B],
        overrides={
            "concepts": {
                "concept:rowkey": {
                    "name": "行记录",
                    "kind": CONCEPT_EVENT,
                    **CONFIRMATION,
                }
            }
        },
    )

    applied = document["concept_overrides_applied"]
    assert applied["created"] == [
        {
            "id": "concept:rowkey",
            "tables": [ROW_A["id"], ROW_B["id"]],
            "revived": True,
        }
    ]
    assert applied["unmatched"] == []
    concept = _by_id(document)["concept:rowkey"]
    assert concept["name"] == "行记录" and concept["kind"] == CONCEPT_EVENT
    assert concept["identity"]["columns_seen"] == ["rowkey"]
    assert set(_members(concept)) == {ROW_A["id"], ROW_B["id"]}
    assert {str(item["table"]) for item in document["unassigned_tables"]}.isdisjoint(
        {ROW_A["id"], ROW_B["id"]}
    )


def test_the_concept_section_says_a_retired_stem_can_be_named_again() -> None:
    """A reviewer who lost a concept to a rule change has to read how to get it back."""
    document = _built([CUSTOMER, ROW_A, ROW_B])

    text = render_ontology_index_markdown(
        {
            **_ontology(concepts=document["concepts"]),
            "retired_stems": document["retired_stems"],
        }
    )

    assert "`rowkey`" in text and "revived" in text


def test_a_corpus_with_no_retired_stem_says_nothing_about_them() -> None:
    """The negative: the section only appears when the corpus really retired one."""
    document = _built([CUSTOMER])

    assert document["retired_stems"] == []
    assert "retired_stems" not in render_ontology_index_markdown(
        _ontology(concepts=document["concepts"])
    )


def test_an_override_naming_a_concept_no_rule_ever_retired_is_unknown() -> None:
    """The negative: a typo is still a typo, and it is still reported as one."""
    document = _built(
        [CUSTOMER, ROW_A],
        overrides={"concepts": {"concept:absent": {"name": "无", **CONFIRMATION}}},
    )

    applied = document["concept_overrides_applied"]
    assert applied["created"] == []
    assert applied["unmatched"] == [
        {"key": "concept:absent", "reason": "unknown_concept"}
    ]


# ------------------------------- 3. an edge that never travels on the key


SELF_JOINED = _entity(
    "ods.cust_base",
    keys=["cust_no"],
    columns=[
        ("cust_no", "客户编号"),
        ("node_no", "节点编码"),
        ("up_node_no", "上级节点编码"),
    ],
)


def test_an_intra_table_join_off_the_concept_key_is_not_a_relation() -> None:
    """客户 does not relate to 客户 because one task joined the table to itself."""
    document = _built(
        [SELF_JOINED],
        [
            _relation(
                "rel:001",
                SELF_JOINED["id"],
                ["up_node_no"],
                SELF_JOINED["id"],
                ["node_no"],
            )
        ],
    )

    assert document["concept_relations"] == []
    assert _reasons(document)[UNMAPPED_REFERENCE_ONLY] == 1


def test_an_intra_table_join_on_the_concept_key_stays_a_self_reference() -> None:
    """The negative: 上级客户 → 客户 is a relation the business really has."""
    parented = _entity(
        "ods.cust_base",
        keys=["cust_no"],
        columns=[("cust_no", "客户编号"), ("parent_cust_no", "上级客户编号")],
    )

    document = _built(
        [parented],
        [
            _relation(
                "rel:001", parented["id"], ["parent_cust_no"], parented["id"], ["cust_no"]
            )
        ],
    )

    assert [str(item["type"]) for item in document["concept_relations"]] == [
        TYPE_SELF_REFERENCE
    ]
    assert _reasons(document)[UNMAPPED_REFERENCE_ONLY] == 0


# An event table keyed by its own id, carrying 客户's key and a region code.
EVENT = _entity(
    "dwd.evt_di",
    keys=["evt_no"],
    columns=[
        ("evt_no", "事件编号"),
        ("cust_no", "客户编号"),
        ("zone_no", "区域编码"),
    ],
    comment="事件流水表",
)
CUSTOMER_SNAP = _entity(
    "dwd.cust_df",
    keys=["cust_no"],
    columns=[("cust_no", "客户编号"), ("zone_no", "区域编码")],
)


def test_a_reference_members_edge_off_the_key_is_not_a_relation() -> None:
    """``dwd.evt_di`` only *carries* 客户's key, and this edge does not travel on it."""
    document = _built(
        [CUSTOMER, EVENT, CUSTOMER_SNAP],
        [
            _relation("rel:001", EVENT["id"], ["cust_no"], CUSTOMER["id"], ["cust_no"]),
            _relation(
                "rel:002", EVENT["id"], ["zone_no"], CUSTOMER_SNAP["id"], ["zone_no"]
            ),
        ],
    )

    assert _pairs(document) == [("concept:evt", "concept:cust")]
    relation = document["concept_relations"][0]
    assert relation["type"] == TYPE_PARTICIPATION and relation["evidence"] == ["rel:001"]
    assert _reasons(document)[UNMAPPED_REFERENCE_ONLY] == 1


def test_a_reference_members_edge_on_the_key_is_kept() -> None:
    """The negative: the same two tables, joined on 客户's key, is a participation."""
    document = _built(
        [CUSTOMER, EVENT, CUSTOMER_SNAP],
        [
            _relation("rel:001", EVENT["id"], ["cust_no"], CUSTOMER["id"], ["cust_no"]),
            _relation(
                "rel:002", EVENT["id"], ["cust_no"], CUSTOMER_SNAP["id"], ["cust_no"]
            ),
        ],
    )

    assert _pairs(document) == [("concept:evt", "concept:cust")]
    assert document["concept_relations"][0]["evidence"] == ["rel:001", "rel:002"]
    assert _reasons(document)[UNMAPPED_REFERENCE_ONLY] == 0


# --------------------------------- 4. the prompt's evidence row for the grain


def _prompt() -> str:
    return REVIEW_PROMPT.read_text(encoding="utf-8")


def test_the_prompt_can_confirm_a_membership_from_a_table_comment() -> None:
    rows = [
        line
        for line in _prompt().splitlines()
        if line.startswith("| 6 ") and "表注释命名了概念与粒度" in line
    ]

    assert len(rows) == 1
    assert "add_tables" in rows[0]


def test_the_prompt_self_check_counts_the_evidence_rows_it_allows() -> None:
    check = [
        line
        for line in _prompt().splitlines()
        if line.startswith("| 7 ") and "basis" in line
    ]

    assert check and "六类" in check[0]


# ------------------------- 5. the unmapped counter reads against a denominator


def test_the_unmapped_counter_carries_the_edges_it_counted_against() -> None:
    document = _built(
        [CUSTOMER, EVENT, CUSTOMER_SNAP],
        [
            _relation("rel:001", EVENT["id"], ["cust_no"], CUSTOMER["id"], ["cust_no"]),
            _relation(
                "rel:002", EVENT["id"], ["zone_no"], CUSTOMER_SNAP["id"], ["zone_no"]
            ),
        ],
    )

    unmapped = document["concept_relations_unmapped"]
    assert unmapped["edges_total"] == 2
    assert unmapped["mapped"] == 1
    assert unmapped["total"] == 1
    assert unmapped["mapped"] + unmapped["total"] == unmapped["edges_total"]


def test_a_corpus_whose_every_edge_folds_reports_a_full_denominator() -> None:
    """The negative: nothing unmapped, and the denominator still says how many."""
    document = _built(
        [CUSTOMER, CONTRACT],
        [_relation("rel:001", CONTRACT["id"], ["cust_no"], CUSTOMER["id"], ["cust_no"])],
    )

    unmapped = document["concept_relations_unmapped"]
    assert unmapped == {
        "edges_total": 1,
        "mapped": 1,
        "total": 0,
        "by_reason": dict.fromkeys(unmapped["by_reason"], 0),
    }


# ----------------------------------------- 6. the summary line the CLI prints


def test_the_cli_summary_counts_created_concepts_and_added_tables(
    tmp_path: Path, capsys
) -> None:
    out = tmp_path / "out"
    reviewed = tmp_path / "concepts.overrides.json"
    reviewed.write_text(
        json.dumps(
            {
                "doc_format": CONCEPT_OVERRIDES_DOC_FORMAT,
                "new_concepts": [
                    {
                        "id": "concept:party",
                        "name": "往来方",
                        "kind": CONCEPT_ENTITY,
                        "tables": {"mart.cust_daily": ROLE_REFERENCE},
                        **CONFIRMATION,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert (
        main(
            [
                "ontology",
                "--lineage",
                str(_cli_corpus(tmp_path / "corpus")),
                "--out",
                str(out),
                "--concept-overrides",
                str(reviewed),
            ]
        )
        == 0
    )

    assert "created 1, tables_added 0" in capsys.readouterr().out
    ontology = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    assert ontology["concept_overrides_applied"]["unmatched"] == []
    assert "concept:party" in {str(item["id"]) for item in ontology["concepts"]}
