"""What a first real review round exposed in the corpus ontology (H1-H5).

Round one of a human review is the only test that matters for this artifact, and it
found five holes. Each one gets a case here, and each case is the shape of the mistake
rather than a re-statement of the code:

* H1 an override that names a column no entity carries was published as ``confirmed``,
  so a typo in a reviewed file became the strongest tier in the document;
* H2 a snapshot table is unique *within one partition*, and the overrides format had no
  way to say so -- nor to record why a person believed the answer;
* H3 the metadata already says which column is the key, in the column comment, and the
  ontology read past it;
* H4 two competing hypotheses about one table's identity were published side by side
  with nothing saying they compete;
* H5 the open questions were scattered over the cards, so round two could not tell what
  round one bought.

Every table, column and comment below is synthetic.
"""

from __future__ import annotations

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.ontology import (
    EVIDENCE_COLUMN_COMMENT,
    FINDING_COMPETING_CANDIDATE_KEYS,
    FINDING_KEY_HINT_CONFLICT,
    KEY_HINT_PHRASES,
    OPEN_ITEM_FINDING,
    OPEN_ITEM_KEY,
    OPEN_ITEM_RELATION,
    TIER_CONFIRMED,
    TIER_HYPOTHESIS,
    TIER_IMPLIED,
    build_ontology,
    render_ontology_index_markdown,
    render_ontology_table_card_markdown,
)
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.render.table_cards import build_table_cards
from scope_lineage.scope.scope_builder import parse_scope_lineage


# A two-table corpus with no key wording in any comment: every identity claim below is
# the author's assumption and nothing else, which is what H1/H2/H4/H5 are about.
PLAIN_SCHEMA = {
    "ods.demo_party": {
        "table_alias": "合成客户表",
        "column_details": [
            {"name": "party_id", "type": "bigint", "comment": "合成客户号"},
            {"name": "party_name", "type": "string", "comment": "合成名称"},
            {"name": "dt", "type": "string", "comment": "合成分区日"},
        ],
    },
    "ods.demo_order": {
        "column_details": [
            {"name": "order_id", "type": "bigint", "comment": "合成订单号"},
            {"name": "party_id", "type": "bigint", "comment": "合成客户号"},
            {"name": "amount", "type": "decimal(18,2)", "comment": "合成金额"},
            {"name": "dt", "type": "string", "comment": "合成分区日"},
        ]
    },
    "mart.demo_wide": {
        "column_details": [
            {"name": "order_id", "type": "bigint", "comment": "合成订单号"},
            {"name": "party_name", "type": "string", "comment": "合成名称"},
        ]
    },
}

JOIN_ON_ID = (
    "INSERT OVERWRITE TABLE mart.demo_wide "
    "SELECT o.order_id AS order_id, p.party_name AS party_name "
    "FROM ods.demo_order o LEFT JOIN ods.demo_party p ON o.party_id = p.party_id"
)
JOIN_ON_ID_AND_DT = (
    "INSERT OVERWRITE TABLE mart.demo_wide2 "
    "SELECT o.order_id AS order_id, p.party_name AS party_name "
    "FROM ods.demo_order o LEFT JOIN ods.demo_party p "
    "ON o.party_id = p.party_id AND o.dt = p.dt"
)
JOIN_ON_NAME = (
    "INSERT OVERWRITE TABLE mart.demo_wide3 "
    "SELECT o.order_id AS order_id, p.party_name AS party_name "
    "FROM ods.demo_order o LEFT JOIN ods.demo_party p ON o.party_name = p.party_name"
)

PARTY_KEY = "ods.demo_party"
PARTY_RELATION = "ods.demo_order.party_id->ods.demo_party.party_id"


def _ontology(*cases, schema=None, overrides=None) -> dict:
    documents = [
        to_lineage_dict(
            parse_scope_lineage(sql, task, schema=schema or PLAIN_SCHEMA)
        )
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


def _one(overrides=None, schema=None) -> dict:
    return _ontology(("demo_task_a", JOIN_ON_ID), schema=schema, overrides=overrides)


def _entity(ontology: dict, name: str) -> dict:
    return next(item for item in ontology["tables"] if item["id"] == name)


def _keys(ontology: dict, name: str) -> list[dict]:
    return _entity(ontology, name)["identity"]["candidate_keys"]


def _findings(ontology: dict, kind: str) -> list[dict]:
    return [item for item in ontology["findings"] if item["kind"] == kind]


def _card(ontology: dict, name: str, schema=None, cases=None) -> str:
    """The markdown of one entity's card, rebuilt over the same corpus."""
    documents = [
        to_lineage_dict(parse_scope_lineage(sql, task, schema=schema or PLAIN_SCHEMA))
        for task, sql in (cases or (("demo_task_a", JOIN_ON_ID),))
    ]
    cards = build_table_cards(
        [build_semantic_profile(document) for document in documents],
        artifact_root="corpus",
    )
    card = next(item for item in cards["tables"] if str(item["table"]) == name)
    return render_ontology_table_card_markdown(card, ontology)


def _section(markdown: str, title: str) -> str:
    """One `##` or `###` section's body. M3 demoted the table-level ones to `###`."""
    for level in ("## ", "### "):
        _head, marker, tail = markdown.partition(f"\n{level}{title}")
        if marker:
            body, _, _rest = tail.partition("\n## ")
            return body.partition("\n### ")[0]
    raise AssertionError(title)


# --------------------------------------------- H1: an override names something real


def test_an_override_naming_a_column_the_entity_does_not_carry_is_not_confirmed() -> None:
    """The failure round one found: a typo published at the strongest tier."""
    ontology = _one(overrides={"keys": {PARTY_KEY: {"columns": ["party_idd"]}}})

    assert ontology["overrides_applied"]["keys"] == 0
    assert ontology["overrides_applied"]["unmatched"] == [
        {"key": PARTY_KEY, "reason": "unknown_column: party_idd"}
    ]
    assert [item["columns"] for item in _keys(ontology, PARTY_KEY)] == [["party_id"]]
    assert _keys(ontology, PARTY_KEY)[0]["tier"] == TIER_HYPOTHESIS


def test_an_override_naming_a_column_the_entity_carries_is_confirmed() -> None:
    ontology = _one(overrides={"keys": {PARTY_KEY: {"columns": ["party_id"]}}})

    assert ontology["overrides_applied"]["keys"] == 1
    assert ontology["overrides_applied"]["unmatched"] == []
    assert _keys(ontology, PARTY_KEY)[0]["tier"] == TIER_CONFIRMED


def test_a_key_override_may_name_a_declared_column_no_task_ever_read() -> None:
    """``used`` is not the bar -- ``declared`` is. The metadata is evidence too."""
    ontology = _one(overrides={"keys": {PARTY_KEY: {"columns": ["party_name"]}}})

    assert ontology["overrides_applied"]["keys"] == 1
    assert ["party_name"] in [item["columns"] for item in _keys(ontology, PARTY_KEY)]


def test_an_override_for_an_entity_the_corpus_never_saw_says_which_one() -> None:
    ontology = _one(overrides={"keys": {"ods.demo_absent": {"columns": ["party_id"]}}})

    assert ontology["overrides_applied"]["unmatched"] == [
        {"key": "ods.demo_absent", "reason": "unknown_entity: ods.demo_absent"}
    ]


def test_a_relation_override_naming_a_column_neither_entity_carries_says_so() -> None:
    ontology = _one(
        overrides={
            "relations": {
                "ods.demo_order.party_idd->ods.demo_party.party_id": {
                    "cardinality": "many_to_one"
                }
            }
        }
    )

    assert ontology["overrides_applied"]["unmatched"] == [
        {
            "key": "ods.demo_order.party_idd->ods.demo_party.party_id",
            "reason": "unknown_column: party_idd",
        }
    ]


def test_a_relation_override_whose_columns_exist_but_whose_edge_does_not() -> None:
    """Both columns are real and the corpus never joined on them: a different mistake."""
    ontology = _one(
        overrides={
            "relations": {"ods.demo_order.amount->ods.demo_party.party_name": {}}
        }
    )

    assert ontology["overrides_applied"]["unmatched"] == [
        {
            "key": "ods.demo_order.amount->ods.demo_party.party_name",
            "reason": "unknown_relation",
        }
    ]


def test_a_key_override_with_no_columns_is_reported_rather_than_applied() -> None:
    ontology = _one(overrides={"keys": {PARTY_KEY: {"confirmed_by": "合成复核人"}}})

    assert ontology["overrides_applied"]["unmatched"] == [
        {"key": PARTY_KEY, "reason": "missing_columns"}
    ]


# ----------------------------------- H2: scoped uniqueness and the basis of an answer


SCOPED = {
    "keys": {
        PARTY_KEY: {
            "columns": ["party_id"],
            "scope_columns": ["dt"],
            "bassis": "合成拼错的字段名",
            "basis": "合成列注释写明它是主键",
            "note": "合成快照表，每个分区一份全量",
            "confirmed_by": "合成复核人",
            "date": "2026-09-20",
        }
    }
}


def test_a_key_may_be_confirmed_unique_only_within_a_scope() -> None:
    """The normal shape of a snapshot table, and the format had no way to say it."""
    ontology = _ontology(("demo_task_a", JOIN_ON_ID), overrides=SCOPED)
    key = _keys(ontology, PARTY_KEY)[0]

    assert key["columns"] == ["party_id"]
    assert key["scope_columns"] == ["dt"]
    assert key["tier"] == TIER_CONFIRMED


def test_a_confirmation_carries_the_basis_a_person_gave_for_it() -> None:
    ontology = _ontology(("demo_task_a", JOIN_ON_ID), overrides=SCOPED)
    stamp = next(
        item
        for item in _keys(ontology, PARTY_KEY)[0]["evidence"]
        if item["kind"] == "human_confirmation"
    )

    assert stamp["confirmed_by"] == "合成复核人"
    assert stamp["date"] == "2026-09-20"
    assert stamp["confirmed_basis"] == "合成列注释写明它是主键"
    assert stamp["note"] == "合成快照表，每个分区一份全量"


def test_a_scoped_confirmed_key_reads_as_unique_within_that_scope_on_the_card() -> None:
    ontology = _ontology(("demo_task_a", JOIN_ON_ID), overrides=SCOPED)
    body = _section(_card(ontology, PARTY_KEY), "7. 身份（本体）")

    assert "在 `dt` 内唯一" in body
    assert "合成复核人" in body
    assert "2026-09-20" in body
    assert "合成列注释写明它是主键" in body


def test_an_unknown_field_in_an_override_is_reported_rather_than_dropped() -> None:
    """``basis``/``bassis``: the reviewer cannot see which one the tool understood."""
    ontology = _ontology(("demo_task_a", JOIN_ON_ID), overrides=SCOPED)

    assert ontology["overrides_applied"]["ignored_fields"] == [
        {"key": PARTY_KEY, "fields": ["bassis"]}
    ]
    assert ontology["overrides_applied"]["keys"] == 1


def test_a_relation_confirmation_carries_its_basis_and_note_too() -> None:
    ontology = _one(
        overrides={
            "relations": {
                PARTY_RELATION: {
                    "cardinality": "many_to_one",
                    "basis": "合成业务方口头确认",
                    "note": "合成备注",
                    "confirmed_by": "合成复核人",
                }
            }
        }
    )
    cardinality = ontology["table_relations"][0]["cardinality"]

    assert cardinality["tier"] == TIER_CONFIRMED
    assert cardinality["basis"] == "human_confirmation"
    assert cardinality["confirmed_basis"] == "合成业务方口头确认"
    assert cardinality["note"] == "合成备注"


def test_a_scope_column_the_entity_does_not_carry_is_unmatched() -> None:
    ontology = _one(
        overrides={
            "keys": {PARTY_KEY: {"columns": ["party_id"], "scope_columns": ["dtt"]}}
        }
    )

    assert ontology["overrides_applied"]["unmatched"] == [
        {"key": PARTY_KEY, "reason": "unknown_column: dtt"}
    ]
    assert ontology["overrides_applied"]["keys"] == 0


# --------------------------------------------------- H3: the key hint in the metadata


HINTED_SCHEMA = {
    "ods.demo_party": {
        "column_details": [
            {"name": "party_id", "type": "bigint", "comment": "合成客户主键"},
            {"name": "party_name", "type": "string", "comment": "合成名称"},
            {"name": "dt", "type": "string", "comment": "合成分区日"},
        ]
    },
    "ods.demo_order": PLAIN_SCHEMA["ods.demo_order"],
    "mart.demo_wide": PLAIN_SCHEMA["mart.demo_wide"],
    "mart.demo_wide3": PLAIN_SCHEMA["mart.demo_wide"],
}


def test_a_column_comment_that_names_a_key_is_published_as_a_declared_hint() -> None:
    ontology = _one(schema=HINTED_SCHEMA)

    assert _entity(ontology, PARTY_KEY)["identity"]["declared_hints"] == [
        {"columns": ["party_id"], "evidence": "column_comment", "text": "合成客户主键"}
    ]


@pytest.mark.parametrize("phrase", KEY_HINT_PHRASES)
def test_every_phrase_in_the_list_is_read_as_a_hint(phrase: str) -> None:
    schema = {
        **HINTED_SCHEMA,
        "ods.demo_party": {
            "column_details": [
                {"name": "party_id", "type": "bigint", "comment": f"合成 {phrase.upper()} 列"},
                {"name": "party_name", "type": "string", "comment": "合成名称"},
                {"name": "dt", "type": "string", "comment": "合成分区日"},
            ]
        },
    }

    hints = _entity(_one(schema=schema), PARTY_KEY)["identity"]["declared_hints"]

    assert [item["columns"] for item in hints] == [["party_id"]]


def test_a_comment_that_says_nothing_about_a_key_is_not_a_hint() -> None:
    hints = _entity(_one(), PARTY_KEY)["identity"]["declared_hints"]

    assert hints == []


def test_a_hint_that_agrees_with_an_assumed_key_raises_it_to_implied() -> None:
    """Comment and structure agree: two independent sources, one conclusion."""
    ontology = _one(schema=HINTED_SCHEMA)
    key = _keys(ontology, PARTY_KEY)[0]

    assert key["columns"] == ["party_id"]
    assert key["tier"] == TIER_IMPLIED
    assert {"kind": EVIDENCE_COLUMN_COMMENT, "column": "party_id"} in key["evidence"]


def test_a_hint_the_corpus_candidate_keys_contradict_is_a_finding() -> None:
    ontology = _ontology(("demo_task_c", JOIN_ON_NAME), schema=HINTED_SCHEMA)
    findings = _findings(ontology, FINDING_KEY_HINT_CONFLICT)

    assert [item["entity"] for item in findings] == [PARTY_KEY]
    assert findings[0]["columns"] == ["party_id"]
    assert "party_id" in findings[0]["text"] and "party_name" in findings[0]["text"]
    assert _keys(ontology, PARTY_KEY)[0]["tier"] == TIER_HYPOTHESIS


def test_the_hint_section_of_the_card_lists_what_the_metadata_declared() -> None:
    ontology = _one(schema=HINTED_SCHEMA)
    body = _section(_card(ontology, PARTY_KEY, schema=HINTED_SCHEMA), "7. 身份（本体）")

    assert "**元数据键线索**" in body
    assert "合成客户主键" in body


# ------------------------------------------------- H4: two hypotheses that compete


SUBSET_CASES = (("demo_task_a", JOIN_ON_ID), ("demo_task_b", JOIN_ON_ID_AND_DT))
DISJOINT_CASES = (("demo_task_a", JOIN_ON_ID), ("demo_task_c", JOIN_ON_NAME))


def test_a_key_set_that_is_a_strict_subset_of_another_is_a_finding() -> None:
    ontology = _ontology(*SUBSET_CASES)
    findings = _findings(ontology, FINDING_COMPETING_CANDIDATE_KEYS)

    assert [item["entity"] for item in findings] == [PARTY_KEY]
    assert [item["columns"] for item in findings[0]["keys"]] == [
        ["party_id"],
        ["party_id", "dt"],
    ]
    assert all(item["evidence"] for item in findings[0]["keys"])


def test_two_disjoint_assumed_key_sets_are_a_finding_too() -> None:
    findings = _findings(_ontology(*DISJOINT_CASES), FINDING_COMPETING_CANDIDATE_KEYS)

    assert [item["columns"] for item in findings[0]["keys"]] == [
        ["party_id"],
        ["party_name"],
    ]


def test_one_assumed_key_on_its_own_competes_with_nothing() -> None:
    assert _findings(_one(), FINDING_COMPETING_CANDIDATE_KEYS) == []


def test_competing_keys_reach_the_index_and_the_card() -> None:
    ontology = _ontology(*SUBSET_CASES)
    index = render_ontology_index_markdown(ontology)
    card = _card(ontology, PARTY_KEY, cases=SUBSET_CASES)

    assert FINDING_COMPETING_CANDIDATE_KEYS in _section(
        index, f"矛盾发现（{len(ontology['findings'])} 条，"
    )
    assert FINDING_COMPETING_CANDIDATE_KEYS in _section(card, "11. 待人工判定")


# ------------------------------------------ H5: one list, one counter, stable ids


def _open_items(ontology: dict) -> list[dict]:
    return ontology["open_items"]


def test_every_open_question_appears_exactly_once_in_the_consolidated_list() -> None:
    ontology = _ontology(*SUBSET_CASES)
    items = _open_items(ontology)

    hypothesis_keys = [
        key
        for entity in ontology["tables"]
        for key in entity["identity"]["candidate_keys"]
        if key["tier"] == TIER_HYPOTHESIS
    ]
    hypothesis_relations = [
        item
        for item in ontology["table_relations"]
        if item["cardinality"]["tier"] == TIER_HYPOTHESIS
    ]
    assert len(items) == (
        len(hypothesis_keys) + len(hypothesis_relations) + len(ontology["findings"])
    )
    assert len({item["id"] for item in items}) == len(items)


def test_a_relation_is_one_open_item_and_not_one_per_side() -> None:
    ontology = _ontology(("demo_task_a", JOIN_ON_ID))
    relations = [item for item in _open_items(ontology) if item["kind"] == OPEN_ITEM_RELATION]

    assert [item["write_back"] for item in relations] == [f"关系:{PARTY_RELATION}"]


def test_every_open_item_carries_the_write_back_key_its_answer_goes_under() -> None:
    items = _open_items(_ontology(("demo_task_a", JOIN_ON_ID)))
    keys = [item for item in items if item["kind"] == OPEN_ITEM_KEY]

    assert [item["write_back"] for item in keys] == [f"键:{PARTY_KEY}=party_id"]
    assert all(item["tier"] == TIER_HYPOTHESIS for item in keys)


def test_findings_come_first_in_the_ranking() -> None:
    items = _open_items(_ontology(*SUBSET_CASES))

    assert items[0]["kind"] == OPEN_ITEM_FINDING


def test_the_ids_are_the_same_in_two_builds_of_the_same_corpus() -> None:
    first = [item["id"] for item in _open_items(_ontology(*SUBSET_CASES))]
    second = [item["id"] for item in _open_items(_ontology(*reversed(SUBSET_CASES)))]

    assert first == second
    assert all(item.startswith("open:") for item in first)


def test_confirming_one_hypothesis_takes_it_off_the_list() -> None:
    before = _open_items(_ontology(("demo_task_a", JOIN_ON_ID)))
    after = _open_items(
        _ontology(
            ("demo_task_a", JOIN_ON_ID),
            overrides={"keys": {PARTY_KEY: {"columns": ["party_id"]}}},
        )
    )

    assert len(after) == len(before) - 1


def test_the_index_headline_counts_what_is_open_and_what_was_confirmed() -> None:
    ontology = _ontology(
        ("demo_task_a", JOIN_ON_ID),
        overrides={"keys": {PARTY_KEY: {"columns": ["party_id"]}}},
    )
    markdown = render_ontology_index_markdown(ontology)

    assert (
        f"待人工判定 {len(ontology['open_items'])} 条 / "
        f"{len(ontology['open_item_groups'])} 组（已确认 1 条）"
    ) in markdown


def test_the_index_carries_the_consolidated_list_with_its_count() -> None:
    """Q3: the list is folded, so what the index carries is one row per group."""
    ontology = _ontology(*SUBSET_CASES)
    markdown = render_ontology_index_markdown(ontology)
    body = _section(
        markdown,
        f"待人工判定清单（{len(ontology['open_items'])} 条，"
        f"折叠为 {len(ontology['open_item_groups'])} 组）",
    )

    for group in ontology["open_item_groups"]:
        assert group["group_id"] in body
        assert group["representative"] in body


def test_an_empty_corpus_list_says_so_rather_than_printing_an_empty_table() -> None:
    ontology = _ontology(
        ("demo_task_a", JOIN_ON_ID),
        overrides={
            "keys": {PARTY_KEY: {"columns": ["party_id"]}},
            "relations": {PARTY_RELATION: {"cardinality": "many_to_one"}},
        },
    )

    assert ontology["open_items"] == []
    assert "本语料没有待人工判定项。" in render_ontology_index_markdown(ontology)


def test_the_card_open_items_cite_the_list_id() -> None:
    ontology = _ontology(("demo_task_a", JOIN_ON_ID))
    body = _section(_card(ontology, PARTY_KEY), "11. 待人工判定")
    item = next(
        item
        for item in ontology["open_items"]
        if item["kind"] == OPEN_ITEM_KEY and item["entity"] == PARTY_KEY
    )

    assert item["id"] in body
