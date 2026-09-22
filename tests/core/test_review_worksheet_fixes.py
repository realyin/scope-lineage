"""N1b: the six gaps one batched concept review opened.

A reviewer worked the batches N1b writes and came back with six places where the
worksheet -- or the merge behind it -- asked for a judgement it had already made
impossible, or hid the one fact the judgement rests on.

1. **Where is this table already a member?** The worksheet asked "merge this
   provisional concept into which one" without ever saying which concepts already
   claim its table, so the reviewer could not see that the merge would collide with a
   membership (``already_a_member``) or which of the two roles would survive.
2. **Merging a provisional warned about two primaries.** A provisional concept is one
   table standing alone, so its member is a ``primary`` by construction. Folding it into
   a concept that has its own primary raised ``merge_kept_two_primaries`` on every
   single answer -- a warning about the shape of M1 rather than about the merge.
3. **The kind and the duplicate flag were not on the worksheet**, so "is this an event"
   and "did something else already claim this name" both meant leaving the batch.
4. **A table with neither a comment nor a key printed an empty evidence row** -- which
   is the M1 case itself, and its column comments were the only thing left to read.
5. **Two tables differing only in case folded into one concept id**, so one of them
   silently had no slot to answer in.
6. **The candidate merge targets were ranked by relations first**, which ranks "some
   task joined them" above "they are called the same thing".

Every table, column, concept, comment and name in this file is synthetic. No real
corpus, table, domain or business name is reproduced here.
"""

from __future__ import annotations

import pytest

from scope_lineage.render.concept_relations import (
    build_concept_relations,
    provisional_concept_ids,
)
from scope_lineage.render.concepts import (
    BASIS_OVERRIDE,
    CONCEPT_OVERRIDES_DOC_FORMAT,
    CONCEPT_TABLE_PREFIX,
    ROLE_PRIMARY,
    ROLE_SNAPSHOT,
    TIER_CONFIRMED,
    apply_concept_overrides,
    build_concepts,
    table_concept_id,
)
from scope_lineage.render.review_batches import (
    ATTRIBUTE_CLUES_SHOWN,
    ATTRIBUTE_CLUE_LABEL,
    MEMBER_OF_HEADING,
    batch_overrides_skeleton,
    build_review_batches,
    render_batch_markdown,
)

from .test_concept_relations import _cards, _entity, _relation


STAMP = {"confirmed_by": "agent:concept-review", "date": "2026-09-23"}


# ------------------------------------------------------------- synthetic corpora


def _table_concepts(table: str, concepts) -> list[dict]:
    """``ontology.py``'s own M2 back-link, spelled here so the test needs no builder."""
    return [
        {
            "id": str(concept.get("id")),
            "role": str(member.get("role")),
            "membership_basis": str(member.get("membership_basis")),
        }
        for concept in concepts
        for member in concept.get("tables") or []
        if str(member.get("table")) == table
    ]


def _built(entities, relations=(), overrides=None) -> dict:
    """The builder's order: concepts, the overrides, the relation fold, the back-links."""
    document = {
        "doc_format": "ontology-json/2",
        "tables": [dict(item) for item in entities],
        "table_relations": [dict(item) for item in relations],
    }
    document.update(build_concepts(document, _cards()))
    apply_concept_overrides(document, overrides if overrides is not None else {})
    document.update(build_concept_relations(document))
    for table in document["tables"]:
        table["concepts"] = _table_concepts(str(table["id"]), document["concepts"])
    return document


def _overrides(**concepts) -> dict:
    return {"doc_format": CONCEPT_OVERRIDES_DOC_FORMAT, "concepts": dict(concepts)}


def _by_id(document) -> dict:
    return {str(concept["id"]): concept for concept in document["concepts"]}


def _members(concept) -> dict:
    return {str(item["table"]): item for item in concept["tables"]}


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


def _evidence_row(text: str, table: str) -> str:
    """The evidence row of one table -- the one the table's own name opens."""
    rows = [line for line in text.splitlines() if line.startswith(f"| `{table}` ")]
    assert rows, f"no evidence row for {table}"
    return rows[0]


# --------------------------------------------- 1: the memberships the table already has


CARRIED = [
    _entity("dim.omega", keys=["omega_code"], comment="欧米伽维表（合成）"),
    _entity("ods.carrier_di", columns={"omega_code": None}),
    _entity("ods.lonely_di", columns={"note_text": None}),
]
CARRIED_RELATIONS = [
    _relation("rel:101", "ods.carrier_di", ["omega_code"], "dim.omega", ["omega_code"])
]


def test_the_worksheet_says_which_folded_concepts_already_claim_the_table() -> None:
    document = _built(CARRIED, CARRIED_RELATIONS)
    concept = _by_id(document)["concept:omega"]
    member = _members(concept)["ods.carrier_di"]

    row = _row(_worksheet(document), table_concept_id("ods.carrier_di"))

    assert MEMBER_OF_HEADING in _worksheet(document)
    assert "concept:omega" in row
    assert str(concept["name"]) in row
    assert str(member["role"]) in row
    assert str(member["membership_basis"]) in row


def test_a_table_no_folded_concept_claims_never_lists_its_own_provisional() -> None:
    """The column answers "would a merge collide", and standing alone is not a collision."""
    document = _built(CARRIED, CARRIED_RELATIONS)
    identifier = table_concept_id("ods.lonely_di")

    row = _row(_worksheet(document), identifier)

    assert row.count(identifier) == 1  # the write-back key, and nothing else
    assert "concept:omega" not in row


# ----------------------------------------- 2: folding a provisional is not two primaries


HAS_PRIMARY = [
    _entity("dim.alpha", keys=["alpha_code"], comment="阿尔法维表（合成）"),
    _entity("ods.spare_df", comment="备用全量（合成）"),
]
NO_PRIMARY = [
    _entity("dim.beta_di", keys=["beta_code"]),
    _entity("ods.spare_df", comment="备用全量（合成）"),
]
TWO_PRIMARIES = [
    _entity("dim.alpha", keys=["alpha_code"], comment="阿尔法维表（合成）"),
    _entity("dim.gamma", keys=["gamma_code"], comment="伽马维表（合成）"),
]


def test_a_provisional_folded_into_a_concept_that_has_a_primary_is_re_roled() -> None:
    spare = table_concept_id("ods.spare_df")
    document = _built(
        HAS_PRIMARY, overrides=_overrides(**{spare: {"merge_into": "concept:alpha", **STAMP}})
    )

    member = _members(_by_id(document)["concept:alpha"])["ods.spare_df"]

    assert member["role"] == ROLE_SNAPSHOT
    assert member["membership_basis"] == BASIS_OVERRIDE
    assert member["role_tier"] == TIER_CONFIRMED
    assert document["concept_overrides_applied"]["warnings"] == []


def test_a_provisional_folded_into_a_concept_with_no_primary_becomes_the_primary() -> None:
    spare = table_concept_id("ods.spare_df")
    document = _built(
        NO_PRIMARY, overrides=_overrides(**{spare: {"merge_into": "concept:beta", **STAMP}})
    )

    members = _members(_by_id(document)["concept:beta"])

    assert members["dim.beta_di"]["role"] == ROLE_SNAPSHOT
    assert members["ods.spare_df"]["role"] == ROLE_PRIMARY
    assert members["ods.spare_df"]["membership_basis"] == BASIS_OVERRIDE
    assert document["concept_overrides_applied"]["warnings"] == []


def test_two_folded_concepts_that_each_have_a_primary_still_warn() -> None:
    document = _built(
        TWO_PRIMARIES,
        overrides=_overrides(**{"concept:alpha": {"merge_into": "concept:gamma", **STAMP}}),
    )

    warnings = document["concept_overrides_applied"]["warnings"]

    assert [item["key"] for item in warnings] == ["concept:alpha"]
    assert warnings[0]["warning"].startswith("merge_kept_two_primaries:")
    assert "dim.alpha" in warnings[0]["warning"] and "dim.gamma" in warnings[0]["warning"]


# ------------------------------------------ 3: the kind evidence and the duplicate flag


DUPLICATES = [
    _entity("ods.twin_one", comment="双生台账（合成）"),
    _entity("ods.twin_two", comment="双生台账（合成）"),
    _entity("ods.single_one", comment="独一台账（合成）"),
]


def test_the_concept_table_compacts_the_kind_evidence_of_every_concept() -> None:
    document = _built(DUPLICATES)
    identifier = table_concept_id("ods.single_one")
    concept = _by_id(document)[identifier]

    row = _row(_worksheet(document), identifier)

    assert str(concept["kind"]) in row
    for vote in concept["kind_evidence"]:
        assert f"{vote['signal']}×" in row


def test_two_concepts_claiming_one_name_point_at_each_other_on_the_worksheet() -> None:
    document = _built(DUPLICATES)
    text = _worksheet(document)
    one, two = table_concept_id("ods.twin_one"), table_concept_id("ods.twin_two")

    assert two in _row(text, one)
    assert one in _row(text, two)


def test_a_concept_nothing_else_claims_names_no_duplicate() -> None:
    document = _built(DUPLICATES)

    row = _row(_worksheet(document), table_concept_id("ods.single_one"))

    assert table_concept_id("ods.twin_one") not in row
    assert table_concept_id("ods.twin_two") not in row


# ------------------------------------------------ 4: the attribute clues of a bare table


CLUE_COLUMNS = {f"clue_{index}": f"线索{index}（合成）" for index in range(1, 11)}
BARE = [
    _entity("dim.omega", keys=["omega_code"], comment="欧米伽维表（合成）"),
    _entity("ods.bare_di", columns=CLUE_COLUMNS),
    _entity("ods.commented_di", columns=CLUE_COLUMNS, comment="已注释台账（合成）"),
]


def test_a_table_with_neither_comment_nor_key_shows_its_column_comments() -> None:
    text = _worksheet(_built(BARE))

    row = _evidence_row(text, "ods.bare_di")

    assert ATTRIBUTE_CLUE_LABEL in row
    shown = [name for name, comment in CLUE_COLUMNS.items() if comment in row]
    assert len(shown) == ATTRIBUTE_CLUES_SHOWN
    # The table's own column order, cut at the cap: the first few are evidence, the
    # whole list would be its DDL.
    assert shown == list(CLUE_COLUMNS)[:ATTRIBUTE_CLUES_SHOWN]


def test_a_table_that_carries_its_own_comment_needs_no_attribute_clues() -> None:
    text = _worksheet(_built(BARE))

    row = _evidence_row(text, "ods.commented_di")

    assert "已注释台账（合成）" in row
    assert ATTRIBUTE_CLUE_LABEL not in row


# ----------------------------------------- 5: two tables that differ only in case


CASED = [
    _entity("ods.widget_a_b", columns={"note_text": None}),
    _entity("ods.widget_A_B", columns={"note_text": None}),
]


def test_two_table_names_that_differ_only_in_case_keep_two_concept_ids() -> None:
    lower, upper = table_concept_id("ods.widget_a_b"), table_concept_id("ods.widget_A_B")
    document = _built(CASED)

    assert lower != upper
    assert {lower, upper} <= set(provisional_concept_ids(document["concepts"]))
    batch = build_review_batches(document, by="size", batch_size=30)["batches"][0]
    assert sorted(batch_overrides_skeleton(batch, document)["concepts"]) == sorted(
        [lower, upper]
    )


def test_a_lowercase_table_keeps_the_id_every_earlier_round_wrote() -> None:
    """The id a reviewer already typed into an overrides file does not move."""
    assert table_concept_id("ods.widget_a_b") == f"{CONCEPT_TABLE_PREFIX}ods_widget_a_b"
    assert table_concept_id("ods.gadget_feed_a") == f"{CONCEPT_TABLE_PREFIX}ods_gadget_feed_a"


# --------------------------------------------- 6: candidate targets ranked by the name


RANKED = [
    _entity("dim.named", keys=["named_code"], comment="甲乙台账（合成）"),
    _entity("dim.joined", keys=["joined_code"], comment="丙丁维表（合成）"),
    _entity("dim.surrogate", keys=["surr_code"], comment="戊己维表（合成）"),
    _entity(
        "ods.subject_di",
        columns={"joined_code": None, "id": None},
        comment="甲乙流水（合成）",
    ),
]
RANKED_RELATIONS = [
    _relation("rel:201", "ods.subject_di", ["joined_code"], "dim.joined", ["joined_code"])
]


def _targets(document) -> list[dict]:
    batch = build_review_batches(document, by="size", batch_size=30)["batches"][0]
    return batch["merge_targets"]


def test_a_target_that_shares_the_name_outranks_one_that_shares_only_a_join() -> None:
    document = _built(RANKED, RANKED_RELATIONS)

    ranked = _targets(document)

    assert [item["id"] for item in ranked][:2] == ["concept:named", "concept:joined"]
    assert ranked[0]["score"] > ranked[1]["score"]
    assert ranked[0]["name_overlap"] >= 1
    assert ranked[1]["relations"] >= 1


def test_the_worksheet_prints_the_score_and_how_it_was_reached() -> None:
    document = _built(RANKED, RANKED_RELATIONS)
    ranked = _targets(document)

    text = _worksheet(document)

    for item in ranked:
        row = _row(text, f'merge_into: "{item["id"]}"')
        assert str(item["score"]) in row
        assert str(item["name_overlap"]) in row and str(item["relations"]) in row


def test_a_concept_that_shares_only_a_generic_stem_is_never_a_candidate() -> None:
    document = _built(RANKED, RANKED_RELATIONS)

    listed = {item["id"] for item in _targets(document)}

    # `id` is on both sides and is a GENERIC_STEMS surrogate: it names nothing.
    assert "concept:surrogate" not in listed
    assert all(item["score"] > 0 for item in _targets(document))


@pytest.mark.parametrize("by", ("family", "domain", "size"))
def test_the_ranked_targets_are_deterministic(by: str) -> None:
    document = _built(RANKED, RANKED_RELATIONS)

    first = build_review_batches(document, by=by, batch_size=30)
    second = build_review_batches(document, by=by, batch_size=30)

    assert first == second
