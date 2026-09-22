"""K4: the concept layer rendered, and the review round that answers it.

K1--K3 publish the concept layer into ``ontology.json`` and nowhere else, which makes it
a layer only a program can read. K4 renders it -- a diagram the business recognises, the
two tables behind it, and the tables no key could place -- and gives it the same round
trip the table-level ontology already has: a reviewed ``concepts.overrides.json`` whose
answers land at tier ``confirmed``.

Every table, concept and name in this file is synthetic. No real corpus is named.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.cli import main
from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.concept_relations import build_concept_relations
from scope_lineage.render.concepts import (
    CONCEPT_ENTITY,
    CONCEPT_EVENT,
    CONCEPT_OVERRIDES_DOC_FORMAT,
    CONCEPT_SUMMARY,
    ROLE_PRIMARY,
    ROLE_REFERENCE,
    ROLE_SNAPSHOT,
    TIER_CONFIRMED,
    apply_concept_overrides,
    build_concepts,
)
from scope_lineage.render.ontology import (
    CONCEPT_KIND_TEXT,
    CONCEPT_MERMAID_LIMIT,
    CONCEPT_ROLE_TEXT,
    build_ontology,
    mermaid_entity_ids,
    render_ontology_index_markdown,
    render_ontology_table_card_markdown,
)
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.render.table_cards import build_table_cards
from scope_lineage.scope.scope_builder import parse_scope_lineage

from .statement_document import write_statement_documents


# ------------------------------------------------------------- synthetic documents


def _member(table: str, role: str = ROLE_PRIMARY, basis: str = "key:proven") -> dict:
    return {
        "table": table,
        "role": role,
        "membership_basis": basis,
        "key_columns": ["cust_no"],
        "grain": None,
    }


def _concept(
    stem: str,
    name: str,
    kind: str = CONCEPT_ENTITY,
    *,
    tables=(),
    candidates=(),
    duplicate=(),
    attributes=(),
) -> dict:
    built = {
        "id": f"concept:{stem}",
        "name": name,
        "name_tier": "hypothesis",
        "name_candidates": [
            {"text": str(text), "source": "key_stem", "count": 1, "name_evidence": []}
            for text in (candidates or (name,))
        ],
        "kind": kind,
        "kind_tier": "implied",
        "kind_evidence": [],
        "identity": {"stem": stem, "columns_seen": []},
        "tables": [
            item if isinstance(item, dict) else _member(str(item)) for item in tables
        ],
        "attributes": [dict(item) for item in attributes],
        "tier": "hypothesis",
    }
    if duplicate:
        built["possible_duplicate_of"] = [str(item) for item in duplicate]
    return built


def _concept_relation(
    source: str, target: str, kind: str, *, roles=(), tier="hypothesis", evidence=("rel:001",)
) -> dict:
    built = {
        "from": f"concept:{source}",
        "to": f"concept:{target}",
        "type": kind,
        "cardinality": {
            "claim": "many_to_one_assumed",
            "tier": tier,
            "basis": list(evidence),
        },
        "task_count": 1,
        "evidence": [str(item) for item in evidence],
    }
    if roles:
        built["roles"] = [str(item) for item in roles]
    return built


def _ontology(*, concepts=(), relations=(), unassigned=(), entities=()) -> dict:
    """One ontology document with only the fields the index markdown reads."""
    return {
        "doc_format": "ontology-json/1",
        "corpus": {"task_count": 1},
        "entities": [dict(item) for item in entities],
        "families": [],
        "concepts": [dict(item) for item in concepts],
        "unassigned_tables": [dict(item) for item in unassigned],
        "relations": [],
        "concept_relations": [dict(item) for item in relations],
        "concept_representation_links": [],
        "concept_relations_unmapped": {"total": 0, "by_reason": {}},
        "constraints": [],
        "findings": [],
        "finding_groups": [],
        "open_items": [],
        "open_item_groups": [],
        "overrides_applied": {
            "relations": 0,
            "keys": 0,
            "unmatched": [],
            "ignored_fields": [],
        },
    }


def _two_concept_ontology() -> dict:
    return _ontology(
        concepts=[
            _concept(
                "cust",
                "客户",
                CONCEPT_ENTITY,
                tables=[
                    _member("ods.cust_base"),
                    _member("ods.cust_snap", ROLE_SNAPSHOT, "key:hypothesis"),
                    _member("ods.msg_send_log", ROLE_REFERENCE, "reference"),
                ],
                candidates=("客户", "客户号", "cust"),
                duplicate=("concept:party",),
            ),
            _concept("msg", "消息发送", CONCEPT_EVENT, tables=["ods.msg_send_log"]),
            _concept("daily", "客户日汇总", CONCEPT_SUMMARY, tables=["mart.cust_daily"]),
        ],
        relations=[
            _concept_relation("msg", "cust", "participation", roles=["发送方", "接收方"]),
            _concept_relation("daily", "cust", "aggregation", tier="proven"),
        ],
        unassigned=[
            {"table": "ods.log_a", "reason": "no_candidate_key"},
            {"table": "ods.log_b", "reason": "no_candidate_key"},
            {"table": "mart.wide", "reason": "key_spans_several_stems"},
        ],
    )


# ---------------------------------------------------------- K4a: the concept layer


def test_the_index_opens_with_the_concept_layer_before_the_table_level_er() -> None:
    """A business reads the concepts; the table-level ER is the evidence under them."""
    rendered = render_ontology_index_markdown(_two_concept_ontology())

    assert "## 概念层" in rendered
    assert rendered.index("## 概念层") < rendered.index("## 实体关系总览")


def test_every_concept_is_one_box_labelled_with_its_kind_and_styled_by_it() -> None:
    rendered = render_ontology_index_markdown(_two_concept_ontology())

    assert "```mermaid" in rendered and "flowchart LR" in rendered
    for stem, name, kind in (
        ("cust", "客户", CONCEPT_ENTITY),
        ("msg", "消息发送", CONCEPT_EVENT),
        ("daily", "客户日汇总", CONCEPT_SUMMARY),
    ):
        node = mermaid_entity_ids([{"id": f"concept:{stem}"}])[f"concept:{stem}"]
        assert f'{node}["{name}（{CONCEPT_KIND_TEXT[kind]}）"]:::{kind}' in rendered
    for kind in (CONCEPT_ENTITY, CONCEPT_EVENT, CONCEPT_SUMMARY):
        assert f"classDef {kind} " in rendered


def test_the_diagram_edges_carry_the_type_the_cardinality_and_the_roles() -> None:
    rendered = render_ontology_index_markdown(_two_concept_ontology())

    assert "参与" in rendered and "发送方、接收方" in rendered
    # `?` marks a cardinality that is only the author's assumption; the proven edge
    # beside it carries no marker.
    participation = next(
        line for line in rendered.split("\n") if "-->" in line and "参与" in line
    )
    aggregation = next(
        line for line in rendered.split("\n") if "-->" in line and "汇总" in line
    )
    assert "?" in participation
    assert "?" not in aggregation


def test_representation_links_never_reach_the_diagram() -> None:
    """A snapshot joined onto its own primary is a seam in the fold, not a relation."""
    ontology = _two_concept_ontology()
    ontology["concept_representation_links"] = [
        {
            "concept": "concept:cust",
            "from_table": "ods.cust_snap",
            "to_table": "ods.cust_base",
            "evidence": ["rel:009"],
        }
    ]

    rendered = render_ontology_index_markdown(ontology)
    diagram = rendered.split("```mermaid")[1].split("```")[0]

    assert "ods.cust_snap" not in diagram


def test_over_forty_concepts_the_diagram_keeps_the_best_connected_and_says_so() -> None:
    concepts = [_concept(f"c{index:03d}", f"概念{index}") for index in range(45)]
    # The first five carry an edge each, so the cap has something to rank on.
    relations = [
        _concept_relation(f"c{index:03d}", f"c{index + 1:03d}", "association")
        for index in range(5)
    ]
    rendered = render_ontology_index_markdown(
        _ontology(concepts=concepts, relations=relations)
    )
    diagram = rendered.split("```mermaid")[1].split("```")[0]

    assert diagram.count(":::") == CONCEPT_MERMAID_LIMIT
    assert f"省略 {45 - CONCEPT_MERMAID_LIMIT} 个" in rendered
    assert 'concept_c000["概念0' in diagram


def test_the_concept_table_carries_the_kind_the_tables_the_candidates_and_the_flag() -> None:
    rendered = render_ontology_index_markdown(_two_concept_ontology())

    assert "| 概念 | 种类 | 表数 | 命名候选 | 疑似重复 |" in rendered
    row = next(line for line in rendered.split("\n") if line.startswith("| 客户（"))
    assert "实体" in row and "implied" in row
    # Three tables, and the roles are counted rather than listed.
    assert "3" in row and "主表" in row and "引用" in row
    assert "客户号" in row
    assert "concept:party" in row


def test_the_concept_relation_table_carries_the_claim_and_the_evidence_count() -> None:
    rendered = render_ontology_index_markdown(_two_concept_ontology())

    assert "| 类型 | 从 | 到 | 角色 | 基数 | 层级 | 证据数 |" in rendered
    row = next(line for line in rendered.split("\n") if line.startswith("| 参与 |"))
    assert "消息发送" in row and "客户" in row and "发送方" in row
    assert "多对一，作者假设" in row and "hypothesis" in row


def test_the_provisional_concepts_get_their_own_section_under_the_concept_table() -> None:
    """M1 replaced 「未归入概念的表」: a table nothing placed is now a concept of its own."""
    rendered = render_ontology_index_markdown(_two_concept_ontology())

    assert "### 未归入概念的表" not in rendered
    assert "### 临时概念（每表一个，待归并）" in rendered
    section = rendered.split("### 临时概念（每表一个，待归并）")[1]
    assert "每张表都归到了某个业务键长出来的概念上。" in section


def test_a_corpus_without_concepts_says_so_rather_than_drawing_nothing() -> None:
    rendered = render_ontology_index_markdown(_ontology())

    assert "## 概念层" in rendered
    assert "本语料没有可发布的概念" in rendered
    assert "```mermaid\nflowchart LR" not in rendered


def test_the_concept_layer_renders_the_same_twice() -> None:
    ontology = _two_concept_ontology()

    assert render_ontology_index_markdown(ontology) == render_ontology_index_markdown(
        ontology
    )


# ------------------------------------------------------------ K4a: the table cards

SCHEMA = {
    "ods.cust_base": ["cust_no", "cust_name", "dt"],
    "ods.msg_send_log": ["msg_no", "cust_no", "send_at", "dt"],
    "mart.cust_daily": ["cust_no", "msg_cnt", "dt"],
}

CASES = (
    (
        "build_cust_daily",
        "INSERT INTO mart.cust_daily SELECT c.cust_no, count(1) AS msg_cnt "
        "FROM ods.msg_send_log m JOIN ods.cust_base c ON m.cust_no = c.cust_no "
        "GROUP BY c.cust_no",
    ),
)


def _corpus() -> tuple[dict, dict]:
    documents = [
        to_lineage_dict(parse_scope_lineage(sql, task, schema=SCHEMA))
        for task, sql in CASES
    ]
    profiles = [build_semantic_profile(document) for document in documents]
    cards = build_table_cards(profiles, artifact_root="corpus")
    ontology = build_ontology(documents, profiles, tables=cards, artifact_root="corpus")
    return ontology, cards


def _card_markdown(table: str) -> str:
    ontology, cards = _corpus()
    card = next(item for item in cards["tables"] if str(item["table"]) == table)
    return render_ontology_table_card_markdown(card, ontology)


def test_the_card_opens_the_identity_section_with_the_concept_it_represents() -> None:
    rendered = _card_markdown("ods.cust_base")
    section = rendered.split("## 7. 身份（本体）")[1].split("## 8.")[0]

    assert "本表是" in section
    assert CONCEPT_ROLE_TEXT[ROLE_PRIMARY] in section
    assert "membership_basis" not in section  # the value, never the field name
    assert "key:hypothesis" in section


def test_a_reference_membership_is_named_as_one_on_the_card() -> None:
    rendered = _card_markdown("ods.msg_send_log")
    section = rendered.split("## 7. 身份（本体）")[1].split("## 8.")[0]

    assert CONCEPT_ROLE_TEXT[ROLE_REFERENCE] in section


def test_a_table_no_key_could_place_says_it_is_its_own_provisional_concept() -> None:
    """M1: the card's answer is a concept and a next step, not a reason code."""
    ontology, cards = _corpus()
    card = next(item for item in cards["tables"] if str(item["table"]) == "ods.cust_base")
    ontology = dict(ontology)
    ontology["concepts"] = [
        {
            "id": "concept:table:ods_cust_base",
            "name": "cust_base",
            "kind": CONCEPT_ENTITY,
            "tables": [
                {
                    "table": "ods.cust_base",
                    "role": ROLE_PRIMARY,
                    "membership_basis": "provisional",
                }
            ],
            "tier": "provisional",
            "origin": "provisional",
        }
    ]

    section = render_ontology_table_card_markdown(card, ontology)
    section = section.split("## 7. 身份（本体）")[1].split("## 8.")[0]

    assert "本表暂自成概念「cust_base」（provisional），待评审归并" in section
    assert "concept:table:ods_cust_base" in section


# -------------------------------------------------------- K4b: concept overrides


def _entity(table: str, *, keys=(), tier="proven", attributes=()) -> dict:
    return {
        "id": table,
        "kind": "physical_table",
        "family": table.split(".")[-1],
        "comment": None,
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
            {
                "column": str(column),
                "type": None,
                "comment": None,
                "observed_roles": [],
                "used_in_corpus": True,
                "not_null_observed": False,
                "synonyms": [],
            }
            for column in (attributes or keys)
        ],
        "naming_hints": {
            "table_comment": None,
            "domain": None,
            "project": None,
            "owner": None,
        },
    }


def _relation(source: str, columns, target: str, target_columns) -> dict:
    return {
        "id": "rel:001",
        "from": {"entity": source, "columns": [str(item) for item in columns]},
        "to": {"entity": target, "columns": [str(item) for item in target_columns]},
        "kind": "join_association",
        "cardinality": {"claim": "many_to_one_assumed", "tier": "hypothesis"},
        "join_types": ["INNER"],
        "task_count": 1,
        "evidence": [],
    }


def _cards(*tables: str) -> dict:
    return {
        "doc_format": "tables-json/1",
        "tables": [
            {
                "table": table,
                "comment": None,
                "columns": [],
                "produced_by": [],
                "consumed_by": [],
            }
            for table in tables
        ],
    }


def _built(entities, relations=(), overrides=None) -> dict:
    """The builder's own order: concepts, then the overrides, then the relation fold."""
    ontology = {
        "doc_format": "ontology-json/1",
        "entities": [dict(item) for item in entities],
        "relations": [dict(item) for item in relations],
    }
    ontology.update(
        build_concepts(ontology, _cards(*(str(item["id"]) for item in entities)))
    )
    apply_concept_overrides(ontology, overrides or {})
    ontology.update(build_concept_relations(ontology))
    return ontology


def _by_id(ontology: dict) -> dict:
    return {str(concept["id"]): concept for concept in ontology["concepts"]}


def _two_stems() -> list[dict]:
    return [
        _entity("ods.cust_base", keys=["cust_no"]),
        _entity("ods.party_ref", keys=["party_no"]),
    ]


CONFIRMATION = {
    "confirmed_by": "agent:concept-review",
    "date": "2026-09-22",
    "basis": "合成语料里两张表共用同一业务键",
}


def test_a_reviewed_name_lands_at_confirmed_with_who_said_so_and_why() -> None:
    ontology = _built(
        _two_stems(),
        overrides={"concepts": {"concept:cust": {"name": "客户", **CONFIRMATION}}},
    )
    concept = _by_id(ontology)["concept:cust"]

    assert concept["name"] == "客户"
    assert concept["name_tier"] == TIER_CONFIRMED
    assert concept["confirmation"]["confirmed_by"] == "agent:concept-review"
    assert concept["confirmation"]["date"] == "2026-09-22"
    assert concept["confirmation"]["confirmed_basis"] == CONFIRMATION["basis"]
    assert ontology["concept_overrides_applied"]["concepts"] == 1


def test_a_reviewed_kind_lands_at_confirmed() -> None:
    ontology = _built(
        _two_stems(),
        overrides={"concepts": {"concept:cust": {"kind": CONCEPT_EVENT, **CONFIRMATION}}},
    )
    concept = _by_id(ontology)["concept:cust"]

    assert concept["kind"] == CONCEPT_EVENT
    assert concept["kind_tier"] == TIER_CONFIRMED


def test_a_reviewed_role_lands_at_confirmed_on_that_member_only() -> None:
    ontology = _built(
        _two_stems(),
        overrides={
            "concepts": {
                "concept:cust": {
                    "roles": {"ods.cust_base": ROLE_SNAPSHOT},
                    **CONFIRMATION,
                }
            }
        },
    )
    member = _by_id(ontology)["concept:cust"]["tables"][0]

    assert member["table"] == "ods.cust_base"
    assert member["role"] == ROLE_SNAPSHOT
    assert member["role_tier"] == TIER_CONFIRMED


def test_a_merge_folds_the_tables_and_records_where_they_came_from() -> None:
    ontology = _built(
        _two_stems(),
        overrides={
            "concepts": {
                "concept:party": {"merge_into": "concept:cust", **CONFIRMATION}
            }
        },
    )
    concepts = _by_id(ontology)

    assert "concept:party" not in concepts
    assert concepts["concept:cust"]["merged_from"] == ["concept:party"]
    assert [item["table"] for item in concepts["concept:cust"]["tables"]] == [
        "ods.cust_base",
        "ods.party_ref",
    ]
    assert ontology["concept_overrides_applied"]["merges"] == 1


def test_a_merge_takes_effect_before_the_relations_are_folded() -> None:
    """The endpoint a merged concept's table carried moves with it, not beside it."""
    entities = [
        _entity("ods.cust_base", keys=["cust_no"]),
        _entity("ods.party_ref", keys=["party_no"]),
        _entity("ods.order_head", keys=["order_no"], attributes=["order_no", "party_no"]),
    ]
    relations = [_relation("ods.order_head", ["party_no"], "ods.party_ref", ["party_no"])]

    before = _built(entities, relations)
    after = _built(
        entities,
        relations,
        overrides={
            "concepts": {
                "concept:party": {"merge_into": "concept:cust", **CONFIRMATION}
            }
        },
    )

    assert [item["to"] for item in before["concept_relations"]] == ["concept:party"]
    assert [item["to"] for item in after["concept_relations"]] == ["concept:cust"]


def test_a_split_publishes_one_numbered_concept_per_named_group() -> None:
    entities = [
        _entity("ods.cust_base", keys=["cust_no"]),
        _entity("ods.cust_prospect", keys=["cust_no"]),
        _entity("ods.party_ref", keys=["party_no"]),
    ]
    ontology = _built(
        entities,
        overrides={
            "splits": [
                {
                    "from": "concept:cust",
                    "into": [
                        {"name": "签约客户", "tables": ["ods.cust_base"]},
                        {"name": "潜在客户", "tables": ["ods.cust_prospect"]},
                    ],
                }
            ]
        },
    )
    concepts = _by_id(ontology)

    assert "concept:cust" not in concepts
    assert concepts["concept:cust-1"]["name"] == "签约客户"
    assert concepts["concept:cust-1"]["name_tier"] == TIER_CONFIRMED
    assert [item["table"] for item in concepts["concept:cust-1"]["tables"]] == [
        "ods.cust_base"
    ]
    assert concepts["concept:cust-2"]["name"] == "潜在客户"
    assert ontology["concept_overrides_applied"]["splits"] == 1


def test_a_split_that_leaves_tables_behind_keeps_the_concept_they_are_on() -> None:
    entities = [
        _entity("ods.cust_base", keys=["cust_no"]),
        _entity("ods.cust_prospect", keys=["cust_no"]),
    ]
    ontology = _built(
        entities,
        overrides={
            "splits": [
                {
                    "from": "concept:cust",
                    "into": [{"name": "签约客户", "tables": ["ods.cust_base"]}],
                }
            ]
        },
    )
    concepts = _by_id(ontology)

    assert [item["table"] for item in concepts["concept:cust"]["tables"]] == [
        "ods.cust_prospect"
    ]
    assert [item["table"] for item in concepts["concept:cust-1"]["tables"]] == [
        "ods.cust_base"
    ]


@pytest.mark.parametrize(
    ("overrides", "key", "reason"),
    [
        (
            {"concepts": {"concept:nope": {"name": "x"}}},
            "concept:nope",
            "unknown_concept",
        ),
        (
            {"concepts": {"concept:cust": {"merge_into": "concept:nope"}}},
            "concept:cust",
            "unknown_concept: concept:nope",
        ),
        (
            {"concepts": {"concept:cust": {"merge_into": "concept:cust"}}},
            "concept:cust",
            "merge_into_self",
        ),
        (
            {"concepts": {"concept:cust": {"roles": {"ods.nope": "primary"}}}},
            "concept:cust",
            "unknown_table: ods.nope",
        ),
        (
            {"concepts": {"concept:cust": {"kind": "thing"}}},
            "concept:cust",
            "unknown_kind: thing",
        ),
        (
            {"concepts": {"concept:cust": {"roles": {"ods.cust_base": "chief"}}}},
            "concept:cust",
            "unknown_role: chief",
        ),
        (
            {"splits": [{"from": "concept:nope", "into": [{"name": "a", "tables": []}]}]},
            "concept:nope",
            "unknown_concept",
        ),
        (
            {
                "splits": [
                    {"from": "concept:cust", "into": [{"name": "a", "tables": ["ods.x"]}]}
                ]
            },
            "concept:cust",
            "unknown_table: ods.x",
        ),
    ],
)
def test_an_override_that_matches_nothing_is_reported_rather_than_dropped(
    overrides: dict, key: str, reason: str
) -> None:
    ontology = _built(_two_stems(), overrides=overrides)

    assert {"key": key, "reason": reason} in ontology["concept_overrides_applied"][
        "unmatched"
    ]


def test_a_field_this_release_does_not_read_is_reported_rather_than_ignored() -> None:
    ontology = _built(
        _two_stems(),
        overrides={"concepts": {"concept:cust": {"name": "客户", "kindd": "entity"}}},
    )

    assert ontology["concept_overrides_applied"]["ignored_fields"] == [
        {"key": "concept:cust", "fields": ["kindd"]}
    ]
    assert _by_id(ontology)["concept:cust"]["name"] == "客户"


def test_the_overrides_report_is_present_even_when_nothing_was_reviewed() -> None:
    ontology = _built(_two_stems())

    assert ontology["concept_overrides_applied"] == {
        "concepts": 0,
        "created": [],
        "tables_added": 0,
        "merges": 0,
        "splits": 0,
        "dissolved": [],
        "unmatched": [],
        "warnings": [],
        "ignored_fields": [],
    }


def test_applying_the_same_overrides_twice_publishes_the_same_document() -> None:
    overrides = {
        "doc_format": CONCEPT_OVERRIDES_DOC_FORMAT,
        "concepts": {
            "concept:party": {"merge_into": "concept:cust", **CONFIRMATION},
            "concept:cust": {"name": "客户", "kind": CONCEPT_ENTITY, **CONFIRMATION},
        },
    }
    entities = _two_stems()

    first = _built(entities, overrides=overrides)
    second = _built(entities, overrides=overrides)

    assert json.dumps(first, ensure_ascii=False) == json.dumps(second, ensure_ascii=False)


def test_the_document_format_marker_is_not_reported_as_an_unknown_field() -> None:
    ontology = _built(
        _two_stems(),
        overrides={"doc_format": CONCEPT_OVERRIDES_DOC_FORMAT, "concepts": {}},
    )

    assert ontology["concept_overrides_applied"]["ignored_fields"] == []


# ------------------------------------------------ K4b: the flag that reads the file


CLI_SCHEMA = {
    "ods.cust_base": ["cust_no", "country_code", "state", "dt"],
    "mart.cust_daily": ["cust_no", "country_code", "dt"],
}

CLI_SQL = (
    "INSERT OVERWRITE TABLE mart.cust_daily PARTITION (dt = '20250101') "
    "SELECT cust_no, max(country_code) AS country_code FROM ods.cust_base "
    "GROUP BY cust_no"
)


def _cli_corpus(root: Path) -> Path:
    write_statement_documents(
        parse_scope_lineage(CLI_SQL, "build_cust_daily", schema=CLI_SCHEMA), root / "task"
    )
    return root


def test_the_cli_applies_a_reviewed_concept_overrides_file(tmp_path: Path, capsys) -> None:
    out = tmp_path / "out"
    reviewed = tmp_path / "concepts.overrides.json"
    reviewed.write_text(
        json.dumps(
            {
                "doc_format": CONCEPT_OVERRIDES_DOC_FORMAT,
                "concepts": {"concept:cust": {"name": "客户", **CONFIRMATION}},
            }
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

    ontology = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    concept = next(item for item in ontology["concepts"] if item["id"] == "concept:cust")
    assert concept["name"] == "客户" and concept["name_tier"] == TIER_CONFIRMED
    assert ontology["concept_overrides_applied"]["concepts"] == 1
    assert (
        "reviewed 1 concept(s), created 0, tables_added 0, 0 merge(s) and 0 split(s)"
        in capsys.readouterr().out
    )
    assert f"| 客户（`{TIER_CONFIRMED}`） |" in (out / "ontology.md").read_text(
        encoding="utf-8"
    )
    card = (out / "tables" / "mart.cust_daily.md").read_text(encoding="utf-8")
    assert "本表是「客户」" in card


def test_the_cli_reports_a_concept_overrides_path_that_is_not_there(
    tmp_path: Path, capsys
) -> None:
    assert (
        main(
            [
                "ontology",
                "--lineage",
                str(_cli_corpus(tmp_path / "corpus")),
                "--out",
                str(tmp_path / "out"),
                "--concept-overrides",
                str(tmp_path / "missing.json"),
            ]
        )
        == 2
    )
    assert "--concept-overrides file does not exist" in capsys.readouterr().err
