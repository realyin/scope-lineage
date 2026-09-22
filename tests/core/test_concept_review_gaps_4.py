"""N8b: the six gaps a *batched* concept review opened on a wide corpus.

N1b cut the provisional pile into worksheets and N1a let a reviewer answer them one
file per batch. An Agent reviewer then worked three of those batches end to end and
came back with six places where the tool refused a judgement it had already made, or
hid the one fact that judgement rests on:

1. ``add_tables`` on a table the concept merely **referenced** was refused as
   ``already_a_member`` -- yet naming a stronger role for a table the concept already
   points at is the single most common answer a reviewer writes;
2. ``merge_into`` could not say **which role** the folded tables take in the survivor,
   so an answer that knew the table was a snapshot had to be written twice;
3. a provisional concept the reviewer confirmed **standalone** ("it really is its own
   thing") stayed at ``tier: "provisional"``, so the next batch run asked about it
   again and the counters said the round had achieved nothing;
4. the worksheet printed the kind's evidence but not the resulting ``kind_tier``, which
   is the one thing the rules read to decide whether the kind may be self-answered;
5. a real concept whose stem is a whole token of the provisional table's own name did
   not reach the candidate list at all when nothing else scored;
6. "not now, because" had nowhere to go: a reviewer who decided to leave a concept open
   could only delete the entry, and the reason died with it.

Every table, column, concept, comment and name in this file is synthetic. No real
corpus, table, column, task, domain or business name is reproduced here.
"""

from __future__ import annotations

from scope_lineage.render.concept_relations import (
    build_concept_relations,
    provisional_concept_ids,
)
from scope_lineage.render.concepts import (
    BASIS_OVERRIDE,
    BASIS_REFERENCE,
    CONCEPT_EVENT,
    CONCEPT_OVERRIDES_DOC_FORMAT,
    ROLE_DETAIL,
    ROLE_PRIMARY,
    ROLE_REFERENCE,
    ROLE_SNAPSHOT,
    TIER_CONFIRMED,
    TIER_HYPOTHESIS,
    TIER_IMPLIED,
    TIER_PROVISIONAL,
    apply_concept_overrides,
    build_concepts,
    table_concept_id,
)
from scope_lineage.render.glossary import PROVISIONAL_TIER as GLOSSARY_PROVISIONAL_TIER
from scope_lineage.render.ontology import (
    PROVISIONAL_TITLE,
    render_ontology_appendix_markdown,
)
from scope_lineage.render.review_batches import (
    KIND_EVIDENCE_HEADING,
    KIND_TIER_HEADING,
    MERGE_TARGETS_SHOWN,
    REVIEW_NOTE_HEADING,
    SCORE_NAME_ROOT,
    build_review_batches,
    render_batch_markdown,
)

from .test_concept_relations import _cards, _entity, _relation
from .test_concept_render_and_overrides import _ontology

STAMP = {
    "confirmed_by": "agent:concept-review",
    "date": "2026-09-23",
    "basis": "合成语料里评审读过这张表",
}


# ------------------------------------------------------------- the synthetic corpus


#: The one concept a business key seeded: a dimension keyed by its own code column.
ANCHOR = _entity("dim.omega", keys=["omega_code"], comment="欧米伽维表（合成）")
#: A table no key places, which merely *carries* the anchor's key -- so the corpus makes
#: it a ``reference`` member of the anchor and a provisional concept of its own.
CARRIER = _entity(
    "ods.carrier_di", columns={"omega_code": None, "memo_text": "备注（合成）"}
)
#: A table nothing at all places, whose *name* carries the anchor's stem as a token.
EXTRA = _entity("ods.omega_extra_di", columns={"note_text": "说明（合成）"})

CORPUS = [ANCHOR, CARRIER, EXTRA]
JOINS = [
    _relation("rel:901", "ods.carrier_di", ["omega_code"], "dim.omega", ["omega_code"])
]

ANCHOR_ID = "concept:omega"
CARRIER_ID = table_concept_id("ods.carrier_di")
EXTRA_ID = table_concept_id("ods.omega_extra_di")


def _built(entities=CORPUS, relations=JOINS, overrides=None) -> dict:
    """The builder's own order: concepts, then the overrides, then the relation fold."""
    document = {
        "doc_format": "ontology-json/2",
        "tables": [dict(item) for item in entities],
        "table_relations": [dict(item) for item in relations],
    }
    document.update(build_concepts(document, _cards()))
    apply_concept_overrides(document, overrides if overrides is not None else {})
    document.update(build_concept_relations(document))
    return document


def _overrides(**concepts) -> dict:
    return {"doc_format": CONCEPT_OVERRIDES_DOC_FORMAT, "concepts": dict(concepts)}


def _by_id(document) -> dict:
    return {str(concept["id"]): concept for concept in document["concepts"]}


def _members(concept) -> dict:
    return {str(item["table"]): item for item in concept["tables"]}


def _stems(concept) -> set:
    return {str(item["stem"]) for item in concept["attributes"]}


def _worksheet(document, *, by: str = "size", batch_size: int = 30) -> str:
    """Every batch of this document's worksheets, as one text to read rows out of."""
    batches = build_review_batches(document, by=by, batch_size=batch_size)
    return "\n".join(
        render_batch_markdown(batch, document) for batch in batches["batches"]
    )


def _row(text: str, marker: str) -> str:
    """The one worksheet row that names ``marker`` -- the concept table's row for it."""
    rows = [line for line in text.splitlines() if marker in line and line.startswith("|")]
    assert rows, f"no worksheet row names {marker}"
    return rows[0]


# ----------------------- 1. add_tables upgrades a membership that was only a reference


#: The reviewer's answer: the table the corpus could only call a carrier is a detail of
#: the concept whose key it carries.
UPGRADE = _overrides(**{ANCHOR_ID: {"add_tables": {CARRIER["id"]: ROLE_DETAIL}, **STAMP}})


def test_add_tables_upgrades_a_reference_membership_rather_than_refusing_it() -> None:
    document = _built(overrides=UPGRADE)

    member = _members(_by_id(document)[ANCHOR_ID])[CARRIER["id"]]
    assert member["role"] == ROLE_DETAIL
    assert member["membership_basis"] == BASIS_OVERRIDE
    assert member["role_tier"] == TIER_CONFIRMED
    assert member["confirmed_by"] == STAMP["confirmed_by"]
    assert document["concept_overrides_applied"]["unmatched"] == []


def test_the_upgraded_member_lends_the_concept_its_columns() -> None:
    """N9a read forwards: a reference lends nothing, and a detail lends everything."""
    plain = _by_id(_built())[ANCHOR_ID]
    upgraded = _by_id(_built(overrides=UPGRADE))[ANCHOR_ID]

    assert "memo_text" not in _stems(plain)
    assert "memo_text" in _stems(upgraded)


def test_the_upgrade_is_reported_as_an_upgrade_and_not_as_an_added_table() -> None:
    applied = _built(overrides=UPGRADE)["concept_overrides_applied"]

    assert applied["roles_upgraded"] == 1
    assert applied["tables_added"] == 0


def test_the_upgrade_dissolves_the_tables_own_provisional_concept() -> None:
    document = _built(overrides=UPGRADE)

    assert CARRIER_ID not in _by_id(document)
    assert [item["id"] for item in document["concept_overrides_applied"]["dissolved"]] == [
        CARRIER_ID
    ]


def test_a_table_already_holding_a_stronger_role_is_still_already_a_member() -> None:
    """The refusal is about a role a reviewer would be overwriting, not about the table."""
    document = _built(
        overrides=_overrides(**{ANCHOR_ID: {"add_tables": {ANCHOR["id"]: ROLE_DETAIL}}})
    )

    applied = document["concept_overrides_applied"]
    assert applied["unmatched"] == [
        {"key": ANCHOR_ID, "reason": f"already_a_member: {ANCHOR['id']}"}
    ]
    assert applied["roles_upgraded"] == 0
    assert _members(_by_id(document)[ANCHOR_ID])[ANCHOR["id"]]["role"] == ROLE_PRIMARY


def test_adding_a_reference_over_a_reference_changes_nothing_and_says_so() -> None:
    """``reference`` is what it already was: there is no stronger role to move it to."""
    document = _built(
        overrides=_overrides(
            **{ANCHOR_ID: {"add_tables": {CARRIER["id"]: ROLE_REFERENCE}}}
        )
    )

    applied = document["concept_overrides_applied"]
    assert applied["unmatched"] == [
        {"key": ANCHOR_ID, "reason": f"already_a_member: {CARRIER['id']}"}
    ]
    assert applied["roles_upgraded"] == 0
    member = _members(_by_id(document)[ANCHOR_ID])[CARRIER["id"]]
    assert member["membership_basis"] == BASIS_REFERENCE


# --------------------------- 2. merge_into may say which role the folded tables take


def _merge(role=None) -> dict:
    """Fold the unplaced table's provisional concept into the anchor, with a role or not."""
    entry = {"merge_into": ANCHOR_ID, **STAMP}
    return _overrides(
        **{EXTRA_ID: entry if role is None else {**entry, "merge_role": role}}
    )


def test_a_merge_without_a_role_re_roles_the_folded_member_as_it_always_did() -> None:
    """The negative first: nothing said, nothing changes about how a merge lands."""
    member = _members(_by_id(_built(overrides=_merge()))[ANCHOR_ID])[EXTRA["id"]]

    assert member["role"] == ROLE_SNAPSHOT
    assert member["membership_basis"] == BASIS_OVERRIDE
    assert member["role_tier"] == TIER_CONFIRMED


def test_a_merge_role_string_is_applied_to_every_folded_member() -> None:
    document = _built(overrides=_merge(ROLE_DETAIL))

    member = _members(_by_id(document)[ANCHOR_ID])[EXTRA["id"]]
    assert member["role"] == ROLE_DETAIL
    assert member["membership_basis"] == BASIS_OVERRIDE
    assert member["role_tier"] == TIER_CONFIRMED


def test_a_merge_role_map_names_the_table_it_is_about() -> None:
    document = _built(overrides=_merge({EXTRA["id"]: ROLE_DETAIL}))

    assert _members(_by_id(document)[ANCHOR_ID])[EXTRA["id"]]["role"] == ROLE_DETAIL
    assert document["concept_overrides_applied"]["unmatched"] == []


def test_a_merge_role_map_leaves_the_members_it_does_not_name_alone() -> None:
    document = _built(overrides=_merge({CARRIER["id"]: ROLE_DETAIL}))

    assert _members(_by_id(document)[ANCHOR_ID])[EXTRA["id"]]["role"] == ROLE_SNAPSHOT


def test_an_unknown_merge_role_is_reported_and_the_merge_lands_anyway() -> None:
    document = _built(overrides=_merge("not_a_role"))

    applied = document["concept_overrides_applied"]
    assert {"key": EXTRA_ID, "reason": "unknown_role: not_a_role"} in applied["unmatched"]
    assert applied["merges"] == 1
    assert _members(_by_id(document)[ANCHOR_ID])[EXTRA["id"]]["role"] == ROLE_SNAPSHOT


def test_a_reviewed_merge_role_lifts_the_folded_table_out_of_reference() -> None:
    """A reviewer may fold a concept *and* say its table is more than a carrier."""
    document = _built(
        overrides=_overrides(
            **{
                CARRIER_ID: {
                    "merge_into": ANCHOR_ID,
                    "merge_role": ROLE_DETAIL,
                    **STAMP,
                }
            }
        )
    )

    concept = _by_id(document)[ANCHOR_ID]
    assert _members(concept)[CARRIER["id"]]["role"] == ROLE_DETAIL
    assert "memo_text" in _stems(concept)


# ------------------- 3. a provisional concept confirmed standalone leaves the pile


#: The third way out of M1: neither a merge nor a new concept -- the reviewer recognises
#: this one table as a thing of its own and names it.
STANDALONE = _overrides(**{EXTRA_ID: {"name": "欧米伽补录", **STAMP}})
#: The same answer with the kind said too.
STANDALONE_KIND = _overrides(
    **{EXTRA_ID: {"name": "欧米伽补录", "kind": CONCEPT_EVENT, **STAMP}}
)


def _provisional(document) -> set:
    return set(provisional_concept_ids(document["concepts"]))


def test_a_named_provisional_concept_leaves_the_provisional_tier() -> None:
    document = _built(overrides=STANDALONE)

    concept = _by_id(document)[EXTRA_ID]
    assert concept["tier"] == TIER_HYPOTHESIS
    assert concept["name"] == "欧米伽补录"
    assert EXTRA_ID not in _provisional(document)


def test_the_confirmed_concept_keeps_the_id_every_other_document_spells_it_as() -> None:
    """A rename is not a re-identification: the write-back key has to stay answerable."""
    document = _built(overrides=STANDALONE)

    assert EXTRA_ID in _by_id(document)
    assert document["concept_overrides_applied"]["unmatched"] == []


def test_its_one_table_is_a_membership_somebody_placed_rather_than_an_open_question() -> None:
    member = _members(_by_id(_built(overrides=STANDALONE))[EXTRA_ID])[EXTRA["id"]]

    assert member["membership_basis"] == BASIS_OVERRIDE
    assert member["role_tier"] == TIER_CONFIRMED


def test_a_confirmed_kind_carries_the_concept_to_implied() -> None:
    """``implied`` is as strong as an inference over the corpus gets, and the kind is one."""
    document = _built(overrides=STANDALONE_KIND)

    concept = _by_id(document)[EXTRA_ID]
    assert concept["kind"] == CONCEPT_EVENT
    assert concept["kind_tier"] == TIER_CONFIRMED
    assert concept["tier"] == TIER_IMPLIED


def test_a_kind_the_corpus_already_agreed_on_carries_it_to_implied_too() -> None:
    """The reviewer named it and left the kind alone; the votes were unanimous already."""
    logged = _entity(
        "ods.omega_log_di",
        columns={"note_text": "说明（合成）"},
        comment="欧米伽发送日志（合成）",
    )
    identifier = table_concept_id(logged["id"])
    document = _built(
        entities=[ANCHOR, logged],
        relations=[],
        overrides=_overrides(**{identifier: {"name": "欧米伽发送", **STAMP}}),
    )

    concept = _by_id(document)[identifier]
    assert concept["kind_tier"] == TIER_IMPLIED
    assert concept["tier"] == TIER_IMPLIED


def test_the_counters_and_the_next_batch_run_both_stop_asking_about_it() -> None:
    before, after = _built(), _built(overrides=STANDALONE)

    assert before["provisional_count"] - after["provisional_count"] == 1
    listed = build_review_batches(after, by="size")
    assert EXTRA_ID not in {
        identifier for batch in listed["batches"] for identifier in batch["concepts"]
    }
    assert listed["provisional_count"] == after["provisional_count"]


def test_the_appendix_stops_listing_a_concept_the_reviewer_answered() -> None:
    document = _built(overrides=STANDALONE)

    text = render_ontology_appendix_markdown(_ontology(concepts=document["concepts"]))

    listed = text.split(PROVISIONAL_TITLE)[1].split("\n### ")[0]
    assert CARRIER_ID in listed
    assert EXTRA_ID not in listed


def test_a_merge_or_a_role_alone_is_not_an_answer_about_what_the_table_is() -> None:
    """Only a name or a kind says "it really is its own thing"; a role says nothing."""
    document = _built(
        overrides=_overrides(**{EXTRA_ID: {"roles": {EXTRA["id"]: ROLE_DETAIL}, **STAMP}})
    )

    assert _by_id(document)[EXTRA_ID]["tier"] == TIER_PROVISIONAL
    assert EXTRA_ID in _provisional(document)


def test_the_value_dictionary_needs_no_rule_of_its_own_to_pick_the_answer_up() -> None:
    """N6 keys ``concept_terms[]`` on the tier, so leaving the pile is the whole change."""
    document = _built(overrides=STANDALONE)

    assert GLOSSARY_PROVISIONAL_TIER == TIER_PROVISIONAL
    assert _by_id(document)[EXTRA_ID]["tier"] != GLOSSARY_PROVISIONAL_TIER


# --------------------------------- 4. the worksheet prints the kind's own tier


def test_the_worksheet_prints_the_kind_tier_beside_the_kind_evidence() -> None:
    """The rules read the tier, not the votes, to say whether the kind may be self-answered."""
    document = _built()

    text = _worksheet(document)

    assert f"| {KIND_EVIDENCE_HEADING} | {KIND_TIER_HEADING} |" in text
    assert TIER_HYPOTHESIS in _row(text, EXTRA_ID)


def test_the_kind_tier_the_worksheet_prints_is_the_one_the_document_publishes() -> None:
    logged = _entity(
        "ods.omega_log_di",
        columns={"note_text": "说明（合成）"},
        comment="欧米伽发送日志（合成）",
    )
    document = _built(entities=[ANCHOR, logged], relations=[])
    identifier = table_concept_id(logged["id"])

    row = _row(_worksheet(document), identifier)

    assert _by_id(document)[identifier]["kind_tier"] == TIER_IMPLIED
    assert f" {TIER_IMPLIED} " in row


def test_every_worksheet_row_still_has_one_cell_per_heading() -> None:
    text = _worksheet(_built())
    header = next(line for line in text.splitlines() if KIND_TIER_HEADING in line)
    row = _row(text, EXTRA_ID)

    assert row.count("|") == header.count("|")


# ------------- 5. a concept whose stem is a whole token of the table's own name


def _alone(document, identifier: str) -> dict:
    """The batch holding exactly this one concept, so nothing else can score a target."""
    batches = build_review_batches(document, by="size", batch_size=1)
    return next(
        batch for batch in batches["batches"] if batch["concepts"] == [identifier]
    )


def _targets(batch) -> dict:
    return {str(item["id"]): item for item in batch["merge_targets"]}


def test_a_concept_whose_stem_is_a_token_of_the_table_name_is_a_candidate() -> None:
    """`ods.omega_extra_di` shares no key and no join with 欧米伽 -- only its own name."""
    batch = _alone(_built(), EXTRA_ID)

    target = _targets(batch)[ANCHOR_ID]
    assert target["name_root"] == "omega"
    assert target["relations"] == 0
    assert target["shared_stems"] == []
    assert target["score"] == SCORE_NAME_ROOT


def test_the_worksheet_prints_the_name_token_the_candidate_matched_on() -> None:
    text = render_batch_markdown(_alone(_built(), EXTRA_ID), _built())

    assert "`omega`" in text.split("## 候选归并目标")[1]


def test_a_stem_that_is_only_part_of_a_token_is_not_a_match() -> None:
    """A whole ``_``-delimited token, not a prefix: `omegax` is a different word."""
    unrelated = _entity("ods.omegax_rows", columns={"note_text": "说明（合成）"})
    document = _built(entities=[ANCHOR, unrelated], relations=[])

    batch = _alone(document, table_concept_id(unrelated["id"]))

    assert _targets(batch) == {}


def test_the_candidate_list_is_still_bounded() -> None:
    document = _built()

    batch = _alone(document, EXTRA_ID)

    assert len(batch["merge_targets"]) <= MERGE_TARGETS_SHOWN


# --------------------------------- 6. "not now, because" is a thing you can write


REASON = "两张表的粒度对不上，等下一轮拿到调度元数据再判（合成）"
LEFT = _overrides(**{EXTRA_ID: {"leave": REASON, **STAMP}})


def test_leaving_a_concept_open_is_recorded_with_its_reason() -> None:
    applied = _built(overrides=LEFT)["concept_overrides_applied"]

    assert applied["left"] == [{"id": EXTRA_ID, "reason": REASON}]
    assert applied["ignored_fields"] == []
    assert applied["unmatched"] == []


def test_leaving_a_concept_open_changes_nothing_about_the_concept() -> None:
    plain, left = _by_id(_built())[EXTRA_ID], _by_id(_built(overrides=LEFT))[EXTRA_ID]

    assert left["tier"] == TIER_PROVISIONAL
    assert left["name"] == plain["name"]
    assert left["kind"] == plain["kind"]
    assert _built(overrides=LEFT)["concept_overrides_applied"]["concepts"] == 0


def test_the_reason_rides_on_the_concept_so_the_next_worksheet_can_print_it() -> None:
    document = _built(overrides=LEFT)

    assert _by_id(document)[EXTRA_ID]["review_note"] == REASON
    assert REASON in _row(_worksheet(document), EXTRA_ID)


def test_the_worksheet_heading_says_what_that_column_is() -> None:
    text = _worksheet(_built(overrides=LEFT))
    header = next(line for line in text.splitlines() if REVIEW_NOTE_HEADING in line)

    assert _row(text, EXTRA_ID).count("|") == header.count("|")


def test_a_concept_nobody_left_carries_no_note_at_all() -> None:
    """The key is absent rather than empty, so the document is the one it always was."""
    assert "review_note" not in _by_id(_built())[EXTRA_ID]
    assert _built()["concept_overrides_applied"]["left"] == []
