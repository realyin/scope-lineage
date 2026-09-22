"""M1: every table gets a concept, so every table-level relation can be lifted.

K1 seeds a concept on a business key, and a table whose only key is a surrogate --
or which has no key at all -- reached no concept and was published in
``unassigned_tables[]`` with the reason. That is an honest answer about the *table* and
a hole in the *concept layer*: an edge that starts at such a table cannot be folded, so
``concept_relations_unmapped.by_reason`` filled up with ``from_table_unplaced`` and the
business reading lost exactly the edges a warehouse writes most of.

M1 closes the hole from the other side. A table nothing placed becomes its **own**
concept, marked ``provisional``: one member, the table itself, named off its own
comment. Nothing about it is a claim -- it is the review round's first question
(「这张表是不是某个已有概念的一份」) written down where the review can answer it with a
``merge_into``. With every table placed, ``_fold`` lifts every edge there is.

Every table, column and comment in this file is synthetic. No real corpus is named.
"""

from __future__ import annotations

import json

from scope_lineage.render.concept_relations import (
    UNMAPPED_FROM_TABLE,
    UNMAPPED_REFERENCE_ONLY,
    UNMAPPED_TO_TABLE,
    build_concept_relations,
)
from scope_lineage.render.concepts import (
    BASIS_OVERRIDE,
    BASIS_PROVISIONAL,
    CONCEPT_ENTITY,
    CONCEPT_EVENT,
    CONCEPT_OVERRIDES_DOC_FORMAT,
    CONCEPT_TABLE_PREFIX,
    ORIGIN_PROVISIONAL,
    ROLE_DETAIL,
    ROLE_PRIMARY,
    ROLE_REFERENCE,
    TIER_CONFIRMED,
    TIER_HYPOTHESIS,
    TIER_PROVISIONAL,
    TIER_STEM_ONLY,
    apply_concept_overrides,
    build_concepts,
    table_concept_id,
)
from scope_lineage.render.ontology import (
    TIER_PROVEN,
    render_ontology_index_markdown,
    render_ontology_table_card_markdown,
    table_family,
)
from scope_lineage.render.ontology_export import render_linkml, render_shacl


# ------------------------------------------------------------------ synthetic inputs


def _attribute(column: str, *, type_=None, comment=None) -> dict:
    return {
        "column": column,
        "type": type_,
        "comment": comment,
        "observed_roles": [],
        "used_in_corpus": True,
        "not_null_observed": False,
        "synonyms": [],
    }


def _entity(table: str, *, keys=(), columns=(), comment=None, tier=TIER_PROVEN) -> dict:
    """One ontology entity, shaped exactly as ``ontology.py`` publishes it."""
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
    identifier: str, source: str, columns, target: str, target_columns
) -> dict:
    return {
        "id": identifier,
        "from": {"entity": source, "columns": [str(item) for item in columns]},
        "to": {"entity": target, "columns": [str(item) for item in target_columns]},
        "kind": "join_association",
        "cardinality": {
            "claim": "many_to_one_assumed",
            "tier": "hypothesis",
            "basis": "no_uniqueness_evidence",
        },
        "join_types": ["INNER"],
        "task_count": 1,
        "evidence": [{"task": "task_a", "statement_id": "stmt:001"}],
    }


def _card(table: str, *, comment=None) -> dict:
    return {
        "table": table,
        "comment": comment,
        "columns": [],
        "produced_by": [],
        "consumed_by": [],
    }


def _cards(*cards: dict) -> dict:
    return {"doc_format": "tables-json/1", "tables": list(cards)}


def _document(entities, relations=(), cards=None) -> dict:
    """The ontology document the concept builders publish, exactly as `ontology.py` does."""
    document = {
        "doc_format": "ontology-json/1",
        "entities": list(entities),
        "relations": list(relations),
    }
    document.update(build_concepts(document, cards or _cards()))
    return document


def _folded(entities, relations=(), cards=None) -> dict:
    document = _document(entities, relations, cards)
    document.update(build_concept_relations(document))
    return document


def _index(document) -> dict:
    return {str(concept["id"]): concept for concept in document["concepts"]}


#: A table nothing can key: no candidate key, no hint, and no JOIN reaches it.
KEYLESS = "ods.gadget_feed_a"
#: A table whose only key is a surrogate the generic rule refuses.
GENERIC = "ods.gadget_rows"


# ------------------------------------------------- M1: one provisional concept per table


def test_a_keyless_table_becomes_its_own_provisional_concept() -> None:
    concepts = _index(_document([_entity(KEYLESS)]))

    concept = concepts[f"{CONCEPT_TABLE_PREFIX}ods_gadget_feed_a"]
    assert concept["tier"] == TIER_PROVISIONAL
    assert concept["origin"] == ORIGIN_PROVISIONAL
    assert concept["identity"] == {"stem": "ods_gadget_feed_a", "columns_seen": []}
    assert concept["tables"] == [
        {
            "table": KEYLESS,
            "role": ROLE_PRIMARY,
            "membership_basis": BASIS_PROVISIONAL,
            "key_columns": [],
            "grain": None,
        }
    ]


def test_the_id_is_the_table_key_the_cards_spell_with_dots_folded() -> None:
    assert table_concept_id("ODS.Gadget_Feed_A") == f"{CONCEPT_TABLE_PREFIX}ods_gadget_feed_a"
    assert table_concept_id(KEYLESS) == f"{CONCEPT_TABLE_PREFIX}ods_gadget_feed_a"


def test_a_generic_key_does_not_block_a_provisional_concept() -> None:
    """A provisional concept is the table itself, never a key family."""
    document = _document([_entity(GENERIC, keys=["id"])])
    concept = _index(document)[table_concept_id(GENERIC)]

    assert concept["tier"] == TIER_PROVISIONAL
    # The generic key still says which columns were seen -- it just seeded nothing.
    assert concept["identity"]["columns_seen"] == ["id"]
    # The generic rule still retires the stem, so an earlier round's answer for
    # `concept:id` stays addressable: a provisional concept is not a key family.
    assert [item["stem"] for item in document["retired_stems"]] == ["id"]


def test_a_table_comment_names_the_provisional_concept_by_the_usual_rules() -> None:
    document = _document(
        [_entity(KEYLESS)], cards=_cards(_card(KEYLESS, comment="小工具流水表"))
    )
    concept = _index(document)[table_concept_id(KEYLESS)]

    # 流水表 is a storage suffix, off by the same rule a folded concept's name loses it.
    assert concept["name"] == "小工具"
    assert concept["name_tier"] == TIER_HYPOTHESIS
    assert concept["name_candidates"][0]["source"] == "table_comment"


def test_without_a_comment_the_name_is_the_short_name_with_storage_suffixes_off() -> None:
    document = _document([_entity("ods.gadget_df")])
    concept = _index(document)[table_concept_id("ods.gadget_df")]

    assert concept["name"] == "gadget"
    assert concept["name_tier"] == TIER_STEM_ONLY


def test_the_kind_is_read_by_the_existing_signals_over_its_one_member() -> None:
    document = _document(
        [_entity(KEYLESS)], cards=_cards(_card(KEYLESS, comment="小工具日志表"))
    )
    assert _index(document)[table_concept_id(KEYLESS)]["kind"] == CONCEPT_EVENT


def test_a_kind_nothing_voted_on_is_an_entity_at_hypothesis() -> None:
    concept = _index(_document([_entity(KEYLESS)]))[table_concept_id(KEYLESS)]

    assert concept["kind"] == CONCEPT_ENTITY
    assert concept["kind_tier"] == TIER_HYPOTHESIS


def test_the_provisional_concept_carries_the_tables_attributes() -> None:
    document = _document(
        [_entity(GENERIC, keys=["id"], columns={"gadget_size": "尺寸"})]
    )
    concept = _index(document)[table_concept_id(GENERIC)]

    assert [item["stem"] for item in concept["attributes"]] == ["gadget_size", "id"]


def test_unassigned_tables_is_empty_by_construction_and_still_published() -> None:
    document = _document([_entity(KEYLESS), _entity(GENERIC, keys=["id"])])

    assert document["unassigned_tables"] == []
    assert document["provisional_count"] == 2


def test_a_table_only_a_join_reached_still_gets_its_own_provisional_concept() -> None:
    """A `reference` membership never said what the table is, so it is not placed."""
    entities = [
        _entity("ods.gadget_base", keys=["gadget_no"]),
        _entity(KEYLESS, columns={"gadget_no": None}),
    ]
    relations = [_relation("rel:001", KEYLESS, ["gadget_no"], "ods.gadget_base", ["gadget_no"])]
    concepts = _index(_document(entities, relations))

    assert table_concept_id(KEYLESS) in concepts
    assert [item["role"] for item in concepts["concept:gadget"]["tables"]] == [
        ROLE_PRIMARY,
        ROLE_REFERENCE,
    ]


def test_a_table_its_own_key_placed_gets_no_provisional_concept() -> None:
    document = _document([_entity("ods.gadget_base", keys=["gadget_no"])])

    assert document["provisional_count"] == 0
    assert list(_index(document)) == ["concept:gadget"]


def test_provisional_concepts_are_published_after_the_concepts_a_key_seeded() -> None:
    document = _document([_entity(KEYLESS), _entity("ods.gadget_base", keys=["gadget_no"])])

    assert [concept["id"] for concept in document["concepts"]] == [
        "concept:gadget",
        table_concept_id(KEYLESS),
    ]


def test_the_concept_layer_is_byte_identical_for_the_same_corpus() -> None:
    entities = [_entity(KEYLESS), _entity(GENERIC, keys=["id"])]
    keys = ("concepts", "provisional_count", "unassigned_tables", "retired_stems")
    first = _document(entities)
    second = _document(list(reversed(entities)))

    assert json.dumps({key: first[key] for key in keys}, ensure_ascii=False) == json.dumps(
        {key: second[key] for key in keys}, ensure_ascii=False
    )


# ------------------------------------------------------------------- M1: the relations


def _two_provisional_tables() -> tuple[list, list]:
    entities = [
        _entity(KEYLESS, columns={"gadget_no": None}),
        _entity(GENERIC, keys=["id"], columns={"gadget_no": None}),
    ]
    relations = [_relation("rel:001", KEYLESS, ["gadget_no"], GENERIC, ["gadget_no"])]
    return entities, relations


def test_every_table_level_relation_folds_once_every_table_is_placed() -> None:
    document = _folded(*_two_provisional_tables())
    unmapped = document["concept_relations_unmapped"]

    assert unmapped["by_reason"][UNMAPPED_FROM_TABLE] == 0
    assert unmapped["by_reason"][UNMAPPED_TO_TABLE] == 0
    assert unmapped["mapped"] == unmapped["edges_total"] == 1


def test_a_relation_between_two_provisional_concepts_is_folded_like_any_other() -> None:
    document = _folded(*_two_provisional_tables())

    assert [(item["from"], item["to"]) for item in document["concept_relations"]] == [
        (table_concept_id(KEYLESS), table_concept_id(GENERIC))
    ]


def test_provisional_relations_counts_the_edges_touching_a_provisional_concept() -> None:
    entities = [
        _entity("ods.gadget_base", keys=["gadget_no"]),
        _entity("ods.widget_base", keys=["widget_no"], columns={"gadget_no": None}),
        _entity(KEYLESS, columns={"gadget_no": None}),
    ]
    relations = [
        _relation("rel:001", "ods.widget_base", ["gadget_no"], "ods.gadget_base", ["gadget_no"]),
        _relation("rel:002", KEYLESS, ["gadget_no"], "ods.gadget_base", ["gadget_no"]),
    ]
    document = _folded(entities, relations)

    assert len(document["concept_relations"]) == 2
    assert document["provisional_relations"] == 1


def test_a_reference_only_edge_is_still_refused() -> None:
    """Both ends answered and the edge never travelled on the concept's key."""
    entities = [
        _entity("ods.gadget_base", keys=["gadget_no"], columns={"batch_no": None}),
        _entity(KEYLESS, columns={"gadget_no": None, "batch_no": None}),
    ]
    relations = [
        _relation("rel:001", KEYLESS, ["gadget_no"], "ods.gadget_base", ["gadget_no"]),
        _relation("rel:002", KEYLESS, ["batch_no"], "ods.gadget_base", ["batch_no"]),
    ]
    document = _folded(entities, relations)

    assert document["concept_relations_unmapped"]["by_reason"][UNMAPPED_REFERENCE_ONLY] == 1


def test_no_edge_of_the_golden_corpus_is_left_unplaced() -> None:
    """The counter's two `*_unplaced` reasons are impossible once every table is placed."""
    ontology = _golden_ontology()
    unmapped = ontology["concept_relations_unmapped"]

    assert unmapped["by_reason"][UNMAPPED_FROM_TABLE] == 0
    assert unmapped["by_reason"][UNMAPPED_TO_TABLE] == 0
    assert ontology["unassigned_tables"] == []
    assert ontology["provisional_count"] > 0


# ------------------------------------------------------------------- M1: the overrides


def _reviewed(document: dict, overrides: dict) -> dict:
    apply_concept_overrides(document, {"doc_format": CONCEPT_OVERRIDES_DOC_FORMAT, **overrides})
    return document


def test_a_merge_from_a_provisional_concept_into_a_real_one_moves_the_member() -> None:
    document = _document(
        [_entity("ods.gadget_base", keys=["gadget_no"]), _entity(KEYLESS)]
    )
    _reviewed(
        document,
        {
            "concepts": {
                table_concept_id(KEYLESS): {
                    "merge_into": "concept:gadget",
                    "basis": "评审判定：这张表是小工具的一份明细",
                    "confirmed_by": "agent:concept-review",
                }
            }
        },
    )

    concepts = _index(document)
    assert table_concept_id(KEYLESS) not in concepts
    assert document["concept_overrides_applied"]["merges"] == 1
    assert document["provisional_count"] == 0
    member = next(
        item for item in concepts["concept:gadget"]["tables"] if item["table"] == KEYLESS
    )
    # A person vouched for the membership, so it stops calling itself provisional.
    assert member["membership_basis"] == BASIS_OVERRIDE
    assert member["role_tier"] == TIER_CONFIRMED


def test_add_tables_dissolves_the_provisional_concept_and_reports_it() -> None:
    document = _document(
        [_entity("ods.gadget_base", keys=["gadget_no"]), _entity(KEYLESS)]
    )
    _reviewed(
        document,
        {"concepts": {"concept:gadget": {"add_tables": {KEYLESS: ROLE_DETAIL}}}},
    )

    applied = document["concept_overrides_applied"]
    assert applied["dissolved"] == [
        {"id": table_concept_id(KEYLESS), "table": KEYLESS, "into": "concept:gadget"}
    ]
    assert table_concept_id(KEYLESS) not in _index(document)
    assert document["provisional_count"] == 0


def test_a_reviewed_reference_add_leaves_the_provisional_concept_standing() -> None:
    """`reference` means "it merely carries the key" -- it never says what a table is."""
    document = _document(
        [_entity("ods.gadget_base", keys=["gadget_no"]), _entity(KEYLESS)]
    )
    _reviewed(
        document,
        {"concepts": {"concept:gadget": {"add_tables": {KEYLESS: ROLE_REFERENCE}}}},
    )

    assert document["concept_overrides_applied"]["dissolved"] == []
    assert table_concept_id(KEYLESS) in _index(document)


def test_new_concepts_dissolves_the_provisional_concepts_of_the_tables_it_claims() -> None:
    document = _document([_entity(KEYLESS), _entity(GENERIC, keys=["id"])])
    _reviewed(
        document,
        {
            "new_concepts": [
                {
                    "id": "concept:gadget",
                    "name": "小工具",
                    "kind": CONCEPT_ENTITY,
                    "tables": {KEYLESS: ROLE_PRIMARY, GENERIC: ROLE_DETAIL},
                    "confirmed_by": "reviewer",
                }
            ]
        },
    )

    applied = document["concept_overrides_applied"]
    assert applied["unmatched"] == []
    assert [item["id"] for item in applied["dissolved"]] == [
        table_concept_id(KEYLESS),
        table_concept_id(GENERIC),
    ]
    assert list(_index(document)) == ["concept:gadget"]


def test_an_override_addressed_to_a_provisional_concept_renames_and_confirms_it() -> None:
    document = _document([_entity(KEYLESS)])
    _reviewed(
        document,
        {
            "concepts": {
                table_concept_id(KEYLESS): {
                    "name": "小工具投喂",
                    "kind": CONCEPT_EVENT,
                    "basis": "业务方确认这张表自成一件事",
                    "confirmed_by": "reviewer",
                }
            }
        },
    )

    concept = _index(document)[table_concept_id(KEYLESS)]
    assert concept["name"] == "小工具投喂"
    assert concept["name_tier"] == TIER_CONFIRMED
    assert concept["kind_tier"] == TIER_CONFIRMED
    assert document["concept_overrides_applied"]["unmatched"] == []


# ------------------------------------------------------------------ M1: the rendering


def _rendered(entities, relations=(), cards=None) -> str:
    document = _folded(entities, relations, cards)
    document.setdefault("corpus", {"task_count": 1})
    document.setdefault("families", [])
    document.setdefault("constraints", [])
    document.setdefault("findings", [])
    document.setdefault("finding_groups", [])
    document.setdefault("open_items", [])
    document.setdefault("open_item_groups", [])
    return render_ontology_index_markdown(document)


def test_the_diagram_omits_the_provisional_concepts_and_says_how_many() -> None:
    rendered = _rendered([_entity("ods.gadget_base", keys=["gadget_no"]), _entity(KEYLESS)])
    diagram = rendered.split("```mermaid")[1].split("```")[0]

    assert "小工具" not in diagram or table_concept_id(KEYLESS) not in diagram
    assert "gadget_feed_a" not in diagram
    assert "另有 1 个临时概念未画" in rendered


def test_the_concept_table_gets_a_second_section_for_the_provisional_ones() -> None:
    rendered = _rendered([_entity("ods.gadget_base", keys=["gadget_no"]), _entity(KEYLESS)])

    assert "临时概念（每表一个，待归并）" in rendered
    row = next(
        line for line in rendered.split("\n") if line.startswith("| gadget_feed_a")
    )
    assert KEYLESS in row
    assert "merge_into" in row
    assert table_concept_id(KEYLESS) in row


def test_a_concept_relation_touching_a_provisional_concept_is_marked() -> None:
    rendered = _rendered(*_two_provisional_tables())

    row = next(
        line
        for line in rendered.split("\n")
        if line.startswith("| ") and "（临时）" in line
    )
    assert "gadget_feed_a" in row


def test_the_card_says_the_table_is_its_own_provisional_concept() -> None:
    ontology, cards = _golden_corpus()
    concept = next(
        item for item in ontology["concepts"] if str(item.get("tier")) == TIER_PROVISIONAL
    )
    table = str(concept["tables"][0]["table"])
    card = next(item for item in cards["tables"] if str(item["table"]) == table)

    rendered = render_ontology_table_card_markdown(card, ontology)

    assert f"本表暂自成概念「{concept['name']}」（provisional），待评审归并" in rendered
    assert str(concept["id"]) in rendered


# ------------------------------------------------------------------- M1: the exports


def test_the_exports_annotate_a_provisional_concept_so_a_consumer_can_filter() -> None:
    ontology = _golden_ontology()

    assert "provisional: true" in render_linkml(ontology)
    assert "sl:provisional true" in render_shacl(ontology)


# ------------------------------------------------------------------ the golden corpus


def _golden_corpus() -> tuple[dict, dict]:
    from .test_ontology import _golden_corpus as built

    return built()


def _golden_ontology() -> dict:
    return _golden_corpus()[0]


def test_the_golden_corpus_publishes_one_provisional_concept_per_unplaced_table() -> None:
    ontology = _golden_ontology()
    provisional = [
        concept
        for concept in ontology["concepts"]
        if str(concept.get("tier")) == TIER_PROVISIONAL
    ]

    assert len(provisional) == ontology["provisional_count"]
    assert all(len(concept["tables"]) == 1 for concept in provisional)
    assert all(str(concept["id"]).startswith(CONCEPT_TABLE_PREFIX) for concept in provisional)
