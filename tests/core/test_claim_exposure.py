"""The claims reach the published documents as optional fields (assertion model WP6).

A consumer -- an Agent reading ``semantic.json``, a catalog loading ``tables.json`` --
used to see ``key_confidence: proven`` with no way to ask *proven about what, under what
premise*. Each strong conclusion now carries its claim beside the field it always had:
the subject it is about, the rule, the conditions still open, the premises and the
evidence against it. The existing fields are unchanged.
"""

from __future__ import annotations

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.claims import Claim, Subject, claim_json
from scope_lineage.render.glossary import apply_glossary, build_glossary
from scope_lineage.render.ontology import build_ontology
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.render.table_cards import build_table_cards
from scope_lineage.scope.scope_builder import parse_scope_lineage

from .claim_witness import schema_map


def _document(sql: str, task: str = "task") -> dict:
    return to_lineage_dict(parse_scope_lineage(sql, task, schema=schema_map()))


def test_a_claim_serialises_every_part_as_plain_json() -> None:
    claim = Claim(
        "unique_by",
        Subject("table_state", ("mart.dim",)),
        ("id", "dt"),
        "proven",
        "R-PARTITION-STATE",
        ("producer",),
        assumptions=("A-WRITERS-CLOSED",),
    )

    assert claim_json(claim) == {
        "kind": "unique_by",
        "subject": {"kind": "table_state", "ref": ["mart.dim"]},
        "content": ["id", "dt"],
        "status": "proven",
        "rule": "R-PARTITION-STATE",
        "evidence": ["producer"],
        "conditions": [],
        "assumptions": ["A-WRITERS-CLOSED"],
        "defeaters": [],
    }


def test_a_proven_output_key_names_its_rule_and_the_batch_it_is_about() -> None:
    shape = build_semantic_profile(
        _document("INSERT OVERWRITE TABLE mart.t SELECT id, MAX(v) AS v FROM ods.e GROUP BY id")
    )["output_shape"]

    claim = shape["key_claim"]
    assert claim["status"] == "proven"
    assert claim["rule"] == "R-GROUPBY-KEY"
    assert claim["content"] == ["id"]
    assert claim["subject"] == {"kind": "write_batch", "ref": ["task", "stmt:001", "mart.t"]}
    assert list(shape)[-1] == "key_claim"


def test_no_key_means_no_key_claim() -> None:
    shape = build_semantic_profile(
        _document("INSERT OVERWRITE TABLE mart.t SELECT id, v FROM ods.e")
    )["output_shape"]

    assert shape["key_claim"] is None


def test_a_safe_join_carries_the_claim_that_made_it_safe() -> None:
    shape = build_semantic_profile(
        _document(
            "INSERT OVERWRITE TABLE mart.t SELECT b.rid, g.v FROM ods.base b LEFT JOIN "
            "(SELECT id, MAX(v) AS v FROM ods.e GROUP BY id) g ON b.id = g.id"
        )
    )["output_shape"]

    risk = shape["fan_out_risks"][0]
    assert risk["status"] == "safe"
    assert risk["claim"]["rule"] == "R-GROUPBY-KEY"
    assert risk["claim"]["subject"]["kind"] == "query_rows"


def test_a_card_carries_its_table_claim_with_the_evidence_against_it() -> None:
    profiles = [
        build_semantic_profile(_document(sql, task))
        for task, sql in (
            ("p1", "CREATE TABLE mart.dim AS SELECT id, MAX(v) AS v, 1 AS dt FROM ods.e GROUP BY id"),
            ("p2", "INSERT INTO mart.dim SELECT id, v, dt FROM ods.e"),
        )
    ]
    card = next(item for item in build_table_cards(profiles)["tables"] if item["table"] == "mart.dim")

    claim = card["key_claim"]
    assert claim["subject"] == {"kind": "table_state", "ref": ["mart.dim"]}
    assert [code for code, _text in claim["defeaters"]] == [
        "appending_producer",
        "producer_key_conflict",
    ]
    assert claim["status"] != "proven"


def test_a_proven_relation_carries_the_read_claim_behind_it() -> None:
    documents = [
        _document("CREATE TABLE mart.dim AS SELECT id, MAX(v) AS v, 1 AS dt FROM ods.e GROUP BY id", "p"),
        _document(
            "INSERT OVERWRITE TABLE mart.t SELECT b.rid, d.v FROM ods.base b "
            "LEFT JOIN mart.dim d ON b.id = d.id",
            "c",
        ),
    ]
    profiles = [build_semantic_profile(document) for document in documents]
    ontology = build_ontology(
        documents, profiles, tables=build_table_cards(profiles), artifact_root="corpus"
    )
    relation = next(item for item in ontology["table_relations"] if item["to"]["entity"] == "mart.dim")

    assert relation["cardinality"]["tier"] == "proven"
    assert relation["cardinality"]["validity"]["rule"] == "R-REPLACE-STATE"
    assert relation["cardinality"]["validity"]["assumptions"] == ["A-WRITERS-CLOSED"]


def test_a_closed_value_names_the_statement_it_is_closed_for() -> None:
    sql = "INSERT OVERWRITE TABLE mart.r SELECT e.id FROM ods.e e WHERE e.id IN (1, 2)"
    document = _document(sql, "reader")
    profile = apply_glossary(
        build_semantic_profile(document), build_glossary([document], artifact_root="corpus")
    )
    domain = next(item for item in profile["fields"] if item["column"] == "id")["value_domain"]

    assert all(item["closed_set"] for item in domain)
    assert {item["closed_for"]["rule"] for item in domain} == {"R-IN-FILTER"}
    assert domain[0]["closed_for"]["subject"]["kind"] == "query_rows"
