"""M2: the concept-first vocabulary of ``ontology-json/2``.

The owner's reading of the corpus, spelled as keys: 实体/事件/汇总 are **concepts**,
``relations[]`` are between concepts, a table is a **representation** of a concept, and a
table-to-table JOIN is **evidence** for a concept relation. This file pins the rename and
the three things it has to buy to be worth a breaking change:

1. a consumer that reads only ``concepts[]`` / ``relations[]`` / ``tables[]`` sees a
   *complete* graph -- every table is in a concept, every table relation either folded
   into a concept relation or was counted as reference-only evidence;
2. every subordinate list says which concept it belongs to, so the document can be read
   concept-first without a join;
3. ``--legacy-keys`` publishes the ``ontology-json/1`` spellings beside the new ones for
   exactly one release, so a consumer migrates instead of breaking.
"""

from __future__ import annotations

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.ontology import (
    DOC_FORMAT,
    LEGACY_KEY_ALIASES,
    build_ontology,
)
from scope_lineage.render.ontology import _ONTOLOGY_KEYS as ONTOLOGY_KEYS
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {
    "ods.orders": ["order_id", "cust_no", "amount", "state", "dt"],
    "ods.customer": ["cust_no", "cust_name", "country"],
    "ods.customer_snap": ["cust_no", "cust_name", "dt"],
}

CORPUS = (
    (
        "task_join",
        "INSERT INTO mart.order_wide SELECT o.order_id, o.cust_no, c.cust_name "
        "FROM ods.orders o LEFT JOIN ods.customer c ON o.cust_no = c.cust_no",
    ),
    (
        "task_daily",
        "INSERT INTO mart.cust_daily SELECT c.cust_no, count(1) AS n FROM ods.customer c "
        "JOIN ods.customer_snap s ON c.cust_no = s.cust_no GROUP BY c.cust_no",
    ),
)


def _ontology(*, legacy_keys: bool = False) -> dict:
    documents = [
        to_lineage_dict(parse_scope_lineage(sql, task, schema=SCHEMA))
        for task, sql in CORPUS
    ]
    return build_ontology(
        documents, artifact_root="corpus", legacy_keys=legacy_keys
    )


# ------------------------------------------------------------------- the key set


def test_the_document_publishes_the_concept_first_key_set() -> None:
    ontology = _ontology()

    assert list(ontology) == list(ONTOLOGY_KEYS)
    assert ontology["doc_format"] == DOC_FORMAT == "ontology-json/2"


@pytest.mark.parametrize(
    "key",
    ["entities", "concept_relations", "concept_representation_links", "unassigned_tables"],
)
def test_the_ontology_json_1_keys_are_gone(key: str) -> None:
    assert key not in _ontology()


@pytest.mark.parametrize(
    "key",
    [
        "concepts",
        "relations",
        "representation_links",
        "tables",
        "table_relations",
        "constraints",
        "findings",
        "open_items",
        "open_item_groups",
        "families",
        "retired_stems",
        "overrides_applied",
        "concept_overrides_applied",
        "corpus",
    ],
)
def test_the_concept_first_keys_are_all_there(key: str) -> None:
    assert key in _ontology()


def test_relations_are_the_concept_relations_and_table_relations_the_evidence() -> None:
    """The rename is the whole point: ``relations`` is no longer table-to-table."""
    ontology = _ontology()

    assert all(
        isinstance(relation["from"], str) and isinstance(relation["to"], str)
        for relation in ontology["relations"]
    )
    assert all(
        set(relation["from"]) >= {"entity", "columns"}
        for relation in ontology["table_relations"]
    )


# -------------------------------------------------------------------- back-links


def test_every_table_back_links_to_the_concepts_it_represents() -> None:
    ontology = _ontology()
    memberships = {
        (str(member["table"]), str(concept["id"]))
        for concept in ontology["concepts"]
        for member in concept["tables"]
    }

    for table in ontology["tables"]:
        back = table["concepts"]
        assert back, table["id"]
        assert all(
            set(item) == {"id", "role", "membership_basis"} for item in back
        )
        assert {(str(table["id"]), str(item["id"])) for item in back} <= memberships


def test_a_table_that_carries_another_concepts_key_back_links_to_both() -> None:
    """One identity plus its references -- the reason the back-link is a list."""
    ontology = _ontology()
    several = [table for table in ontology["tables"] if len(table["concepts"]) > 1]

    assert several, "this corpus is supposed to have a table carrying a foreign key"


def test_every_table_relation_says_which_concept_relation_it_folded_into() -> None:
    ontology = _ontology()
    published = {str(relation["id"]) for relation in ontology["relations"]}

    for relation in ontology["table_relations"]:
        assert "concept_relation" in relation
        folded = relation["concept_relation"]
        assert folded is None or folded in published


def test_a_concept_relations_evidence_is_exactly_the_edges_that_name_it() -> None:
    ontology = _ontology()
    folded: dict[str, set[str]] = {}
    for relation in ontology["table_relations"]:
        if relation["concept_relation"]:
            folded.setdefault(str(relation["concept_relation"]), set()).add(
                str(relation["id"])
            )

    for relation in ontology["relations"]:
        assert folded.get(str(relation["id"]), set()) == set(relation["evidence"])


@pytest.mark.parametrize("slot", ["constraints", "findings", "open_items"])
def test_every_subordinate_entry_names_the_concept_of_its_subject_table(slot: str) -> None:
    ontology = _ontology()
    identity = {
        str(member["table"]): str(concept["id"])
        for concept in ontology["concepts"]
        for member in concept["tables"]
        if member["membership_basis"] not in ("reference",)
    }
    assert ontology[slot], f"this corpus is supposed to publish a {slot} entry"

    for item in ontology[slot]:
        assert "concept" in item
        if item["concept"] is not None:
            assert item["concept"] in {str(c["id"]) for c in ontology["concepts"]}
            assert item["concept"] == identity.get(_subject(slot, item), item["concept"])


def _subject(slot: str, item: dict) -> str:
    if slot == "constraints":
        return str((item.get("target") or {}).get("entity"))
    return str(item.get("entity"))


def test_every_open_item_group_names_a_concept() -> None:
    ontology = _ontology()
    assert ontology["open_item_groups"]

    for group in ontology["open_item_groups"]:
        assert "concept" in group


# ----------------------------------------------------- the graph is complete


def test_a_consumer_reading_only_the_concept_layer_sees_every_table() -> None:
    ontology = _ontology()
    represented = {
        str(member["table"])
        for concept in ontology["concepts"]
        for member in concept["tables"]
    }

    assert represented == {str(table["id"]) for table in ontology["tables"]}


def test_every_table_relation_is_folded_a_seam_or_reference_only() -> None:
    """Nothing falls out of the fold now that every table has a concept (M1)."""
    ontology = _ontology()
    unmapped = ontology["concept_relations_unmapped"]
    seams = sum(len(link["evidence"]) for link in ontology["representation_links"])
    loose = [
        relation
        for relation in ontology["table_relations"]
        if relation["concept_relation"] is None
    ]

    assert unmapped["by_reason"]["from_table_unplaced"] == 0
    assert unmapped["by_reason"]["to_table_unplaced"] == 0
    assert len(loose) == unmapped["by_reason"]["reference_only_edge"] + seams


# ------------------------------------------------------------------ --legacy-keys


def test_legacy_keys_publishes_the_ontology_json_1_spellings_as_aliases() -> None:
    ontology = _ontology(legacy_keys=True)

    for legacy, current in LEGACY_KEY_ALIASES.items():
        assert ontology[legacy] == (ontology[current] if current else []), legacy
    assert ontology["entities"] is ontology["tables"]
    assert ontology["concept_relations"] is ontology["relations"]


def test_the_aliases_are_off_by_default() -> None:
    assert not set(LEGACY_KEY_ALIASES) & set(_ontology())


def test_the_aliases_sit_behind_the_current_keys() -> None:
    """A reader of the file meets the vocabulary before its deprecated spellings."""
    keys = list(_ontology(legacy_keys=True))

    assert keys[: len(ONTOLOGY_KEYS)] == list(ONTOLOGY_KEYS)
    assert keys[len(ONTOLOGY_KEYS) :] == list(LEGACY_KEY_ALIASES)
