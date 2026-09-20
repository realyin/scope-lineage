"""O9: the column comment that names another table's column is a relation hint.

H3 read the column comments for one question -- "is this column the key" -- and walked
past the other half of what a catalog writes in them: 「关联 <表>.<列>」. That sentence is
the foreign key the warehouse never declared, and the corpus cannot derive it: a table
pair no task ever joined leaves no JOIN behind to read.

So the comment is read, resolved against the corpus's own entities, and published as a
*hint* -- never as a proof. It does three things and nothing more: it corroborates a
cardinality some task assumed (``hypothesis`` -> ``implied``), it proposes an edge no
task wrote (``kind: hinted``, which lands in the open list for a person to confirm), and
it contradicts a proven edge out loud (``relation_hint_conflict``).

Every table, column and comment below is synthetic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.ontology import (
    BASIS_COLUMN_COMMENT,
    CARDINALITY_MANY_TO_ONE_ASSUMED,
    EVIDENCE_COLUMN_COMMENT,
    FINDING_RELATION_HINT_CONFLICT,
    RELATION_HINTED,
    TIER_HYPOTHESIS,
    TIER_IMPLIED,
    TIER_PROVEN,
    build_ontology,
    mermaid_entity_ids,
    render_ontology_index_markdown,
    render_ontology_table_card_markdown,
)
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.render.table_cards import build_table_cards
from scope_lineage.scope.scope_builder import parse_scope_lineage

FIXTURES = Path(__file__).resolve().parent / "fixtures"

PARTY = "ods.demo_party"
ORDER = "ods.demo_order"

# The eight phrasings the rule recognises, each pointing at the same column.
POINTERS = (
    "关联 ods.demo_party.party_id",
    "对应 ods.demo_party 的 party_id",
    "引用 ods.demo_party.party_id",
    "见 ods.demo_party.party_id",
    "外键 ods.demo_party.party_id",
    "FK ods.demo_party.party_id",
    "references ods.demo_party.party_id",
    "-> ods.demo_party.party_id",
)


def _schema(
    order_party_comment: str,
    *,
    order_dt_comment: str = "合成分区日",
    extra: dict | None = None,
) -> dict:
    """The two-table corpus, with one comment under test on ``demo_order.party_id``."""
    return {
        PARTY: {
            "column_details": [
                {"name": "party_id", "type": "bigint", "comment": "合成客户号"},
                {"name": "party_name", "type": "string", "comment": "合成名称"},
                {"name": "dt", "type": "string", "comment": "合成分区日"},
            ]
        },
        ORDER: {
            "column_details": [
                {"name": "order_id", "type": "bigint", "comment": "合成订单号"},
                {"name": "party_id", "type": "bigint", "comment": order_party_comment},
                {"name": "amount", "type": "decimal(18,2)", "comment": "合成金额"},
                {"name": "dt", "type": "string", "comment": order_dt_comment},
            ]
        },
        "mart.demo_wide": {
            "column_details": [
                {"name": "order_id", "type": "bigint", "comment": "合成订单号"},
                {"name": "party_name", "type": "string", "comment": "合成名称"},
            ]
        },
        **(extra or {}),
    }


JOIN_ON_ID = (
    "INSERT OVERWRITE TABLE mart.demo_wide "
    "SELECT o.order_id AS order_id, p.party_name AS party_name "
    "FROM ods.demo_order o LEFT JOIN ods.demo_party p ON o.party_id = p.party_id"
)
# The corpus joins the two tables on `party_id` and never on `dt`, so a pointer written
# on `dt` is a column pair no task ever related: nothing but the comment speaks for it.
UNJOINED_POINTER = "合成分区日，关联 ods.demo_party.dt"


def _corpus(*cases, schema) -> tuple[dict, dict]:
    documents = [
        to_lineage_dict(parse_scope_lineage(sql, task, schema=schema))
        for task, sql in cases
    ]
    profiles = [build_semantic_profile(document) for document in documents]
    cards = build_table_cards(profiles, artifact_root="corpus")
    ontology = build_ontology(
        documents, profiles, tables=cards, artifact_root="corpus"
    )
    return ontology, cards


def _ontology(comment: str) -> dict:
    return _corpus(("demo_task_a", JOIN_ON_ID), schema=_schema(comment))[0]


def _unjoined() -> tuple[dict, dict]:
    """The same corpus with the pointer on a column pair no JOIN relates."""
    return _corpus(
        ("demo_task_a", JOIN_ON_ID),
        schema=_schema("合成客户号", order_dt_comment=UNJOINED_POINTER),
    )


def _entity(ontology: dict, name: str) -> dict:
    return next(item for item in ontology["entities"] if item["id"] == name)


def _hints(ontology: dict, name: str = ORDER) -> list[dict]:
    return _entity(ontology, name).get("relation_hints") or []


def _relation(ontology: dict, from_column: str, to_column: str) -> dict | None:
    return next(
        (
            item
            for item in ontology["relations"]
            if item["from"]["columns"] == [from_column]
            and item["to"]["columns"] == [to_column]
        ),
        None,
    )


def _section(markdown: str, title: str) -> str:
    _head, marker, tail = markdown.partition(f"\n## {title}")
    assert marker, title
    body, _, _rest = tail.partition("\n## ")
    return body


# ------------------------------------------------------------------ O9: recognition


@pytest.mark.parametrize("pointer", POINTERS)
def test_every_phrasing_resolves_to_the_entity_and_column_it_names(pointer: str) -> None:
    text = f"合成客户号，{pointer}"

    assert _hints(_ontology(text)) == [
        {
            "from_column": "party_id",
            "to": {"entity": PARTY, "column": "party_id"},
            "evidence": EVIDENCE_COLUMN_COMMENT,
            "text": text,
        }
    ]


def test_the_table_name_may_be_written_bare_when_only_one_entity_could_be_it() -> None:
    hints = _hints(_ontology("合成客户号，关联 demo_party.party_id"))

    assert [hint["to"] for hint in hints] == [{"entity": PARTY, "column": "party_id"}]


def test_the_table_name_is_matched_case_insensitively() -> None:
    hints = _hints(_ontology("合成客户号，REFERENCES ODS.DEMO_PARTY.PARTY_ID"))

    assert [hint["to"]["entity"] for hint in hints] == [PARTY]


def test_a_comment_that_points_at_nothing_is_not_a_hint() -> None:
    ontology = _ontology("合成客户号")

    assert "relation_hints" not in _entity(ontology, ORDER)
    assert "relation_hints" not in _entity(ontology, PARTY)
    assert all(item["kind"] != RELATION_HINTED for item in ontology["relations"])


# ------------------------------------------------------------------ O9: unresolved


AMBIGUOUS_SCHEMA_EXTRA = {
    "dim.demo_party": {
        "column_details": [
            {"name": "party_id", "type": "bigint", "comment": "合成客户号"},
            {"name": "party_grade", "type": "string", "comment": "合成等级"},
        ]
    },
    "mart.demo_grade": {
        "column_details": [
            {"name": "order_id", "type": "bigint", "comment": "合成订单号"},
            {"name": "party_grade", "type": "string", "comment": "合成等级"},
        ]
    },
}
JOIN_ON_GRADE = (
    "INSERT OVERWRITE TABLE mart.demo_grade "
    "SELECT o.order_id AS order_id, g.party_grade AS party_grade "
    "FROM ods.demo_order o LEFT JOIN dim.demo_party g ON o.party_id = g.party_id"
)


def test_a_bare_table_name_two_entities_could_be_is_reported_unresolved() -> None:
    """Two qualified entities share the bare name: picking one would be a guess."""
    schema = _schema("合成客户号，关联 demo_party.party_id", extra=AMBIGUOUS_SCHEMA_EXTRA)
    ontology = _corpus(
        ("demo_task_a", JOIN_ON_ID), ("demo_task_b", JOIN_ON_GRADE), schema=schema
    )[0]
    hints = _hints(ontology)

    assert [hint["unresolved"] for hint in hints] == ["ambiguous_entity: demo_party"]
    assert [hint["to"] for hint in hints] == [
        {"entity": "demo_party", "column": "party_id"}
    ]


def test_a_table_the_corpus_does_not_hold_is_reported_unresolved() -> None:
    hints = _hints(_ontology("合成客户号，关联 ods.demo_absent.party_id"))

    assert [hint["unresolved"] for hint in hints] == [
        "unknown_entity: ods.demo_absent"
    ]


def test_a_column_the_named_entity_does_not_carry_is_reported_unresolved() -> None:
    ontology = _ontology("合成客户号，关联 ods.demo_party.party_idd")
    hints = _hints(ontology)

    assert [hint["unresolved"] for hint in hints] == ["unknown_column: party_idd"]
    assert hints[0]["to"] == {"entity": PARTY, "column": "party_idd"}


def test_an_unresolved_hint_does_not_act_on_any_relation() -> None:
    ontology = _ontology("合成客户号，关联 ods.demo_absent.party_id")
    relation = _relation(ontology, "party_id", "party_id")

    assert relation is not None
    assert relation["cardinality"]["tier"] == TIER_HYPOTHESIS
    assert all(item["kind"] != RELATION_HINTED for item in ontology["relations"])


# ------------------------------------------------------- O9: the hint that lifts


def test_a_hint_that_agrees_with_an_assumed_relation_lifts_it_to_implied() -> None:
    """Comment and JOIN are two independent sources saying the same thing."""
    text = "合成客户号，关联 ods.demo_party.party_id"
    ontology = _ontology(text)
    relation = _relation(ontology, "party_id", "party_id")

    assert relation["from"]["entity"] == ORDER and relation["to"]["entity"] == PARTY
    assert relation["cardinality"]["tier"] == TIER_IMPLIED
    assert {"kind": EVIDENCE_COLUMN_COMMENT, "column": "party_id"} in relation["evidence"]


def test_a_lifted_relation_stops_being_asked_about() -> None:
    ontology = _ontology("合成客户号，关联 ods.demo_party.party_id")

    assert not [
        item for item in ontology["open_items"] if item["kind"] == "relation"
    ]


# ------------------------------------------------- O9: the hint that adds an edge


def test_a_hint_no_task_ever_joined_publishes_a_hinted_relation() -> None:
    relation = _relation(_unjoined()[0], "dt", "dt")

    assert relation["kind"] == RELATION_HINTED
    assert relation["from"]["entity"] == ORDER and relation["to"]["entity"] == PARTY
    assert relation["cardinality"] == {
        "claim": CARDINALITY_MANY_TO_ONE_ASSUMED,
        "tier": TIER_HYPOTHESIS,
        "basis": BASIS_COLUMN_COMMENT,
    }
    assert relation["task_count"] == 0
    assert relation["join_types"] == []
    assert relation["evidence"] == [
        {"kind": EVIDENCE_COLUMN_COMMENT, "column": "dt", "text": UNJOINED_POINTER}
    ]


def test_a_hinted_relation_is_a_question_with_a_write_back_target() -> None:
    items = [
        item for item in _unjoined()[0]["open_items"] if item["kind"] == "relation"
    ]

    assert f"关系:{ORDER}.dt->{PARTY}.dt" in [item["write_back"] for item in items]
    assert f"open:rel:{ORDER}.dt->{PARTY}.dt" in [item["id"] for item in items]


def test_a_hinted_relation_is_drawn_as_a_hypothesis_in_the_er_diagram() -> None:
    ontology = _unjoined()[0]
    identifiers = mermaid_entity_ids(ontology["entities"])
    markdown = render_ontology_index_markdown(ontology)

    assert (
        f"    {identifiers[ORDER]} }}o--|| {identifiers[PARTY]} : \"dt = dt ?\""
        in markdown
    )


def test_the_card_lists_the_comment_hints_in_the_relations_section() -> None:
    ontology, cards = _unjoined()
    card = next(item for item in cards["tables"] if item["table"] == ORDER)
    body = _section(render_ontology_table_card_markdown(card, ontology), "8. 关系")

    assert "**注释线索**" in body
    assert f"`dt` → `{PARTY}`.`dt`" in body
    assert UNJOINED_POINTER in body


def test_a_table_without_hints_keeps_the_relations_section_it_always_had() -> None:
    ontology, cards = _corpus(("demo_task_a", JOIN_ON_ID), schema=_schema("合成客户号"))
    card = next(item for item in cards["tables"] if item["table"] == ORDER)
    body = _section(render_ontology_table_card_markdown(card, ontology), "8. 关系")

    assert "**注释线索**" not in body


# --------------------------------------------------------------- O9: the conflict


AGGREGATE = (
    "INSERT OVERWRITE TABLE dim.demo_party_agg "
    "SELECT p.party_id AS party_id, count(1) AS order_count "
    "FROM ods.demo_party p GROUP BY p.party_id"
)
JOIN_ON_AGG = (
    "INSERT OVERWRITE TABLE mart.demo_count "
    "SELECT o.order_id AS order_id, a.order_count AS order_count "
    "FROM ods.demo_order o LEFT JOIN dim.demo_party_agg a ON o.party_id = a.party_id"
)
PROVEN_SCHEMA_EXTRA = {
    "dim.demo_party_agg": {
        "column_details": [
            {"name": "party_id", "type": "bigint", "comment": "合成客户号"},
            {"name": "order_count", "type": "bigint", "comment": "合成单量"},
        ]
    },
    "mart.demo_count": {
        "column_details": [
            {"name": "order_id", "type": "bigint", "comment": "合成订单号"},
            {"name": "order_count", "type": "bigint", "comment": "合成单量"},
        ]
    },
}


def _proven_corpus(comment: str) -> dict:
    schema = _schema(comment, extra=PROVEN_SCHEMA_EXTRA)
    return _corpus(
        ("demo_task_p", AGGREGATE), ("demo_task_q", JOIN_ON_AGG), schema=schema
    )[0]


def test_the_proven_relation_the_conflict_case_rests_on_is_really_proven() -> None:
    relation = _relation(_proven_corpus("合成客户号"), "party_id", "party_id")

    assert relation["to"]["entity"] == "dim.demo_party_agg"
    assert relation["cardinality"]["tier"] == TIER_PROVEN


def test_a_hint_pointing_at_another_table_than_the_proven_one_is_a_finding() -> None:
    ontology = _proven_corpus("合成客户号，关联 ods.demo_party.party_id")
    findings = [
        item
        for item in ontology["findings"]
        if item["kind"] == FINDING_RELATION_HINT_CONFLICT
    ]

    assert [item["entity"] for item in findings] == [ORDER]
    assert findings[0]["columns"] == ["party_id"]
    assert PARTY in findings[0]["text"]
    assert "dim.demo_party_agg" in findings[0]["text"]
    assert findings[0]["tasks"] == {"proven_by": ["demo_task_q"]}


def test_a_hint_agreeing_with_the_proven_relation_is_not_a_finding() -> None:
    ontology = _proven_corpus("合成客户号，关联 dim.demo_party_agg.party_id")

    assert not [
        item
        for item in ontology["findings"]
        if item["kind"] == FINDING_RELATION_HINT_CONFLICT
    ]


# ------------------------------------------------------------------ golden bytes


def test_no_fixture_comment_names_a_table_so_the_golden_does_not_move() -> None:
    """The recorded corpus has no pointer in any comment: O9 adds nothing to it."""
    body = json.loads(
        (FIXTURES / "ontology" / "ontology.json").read_text(encoding="utf-8")
    )

    assert all("relation_hints" not in entity for entity in body["entities"])
    assert all(item["kind"] != RELATION_HINTED for item in body["relations"])
