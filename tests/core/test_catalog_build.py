"""``build_ontology``: the catalog normalised into one ``ontology-json/3`` document."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.catalog import (
    CatalogError,
    build_ontology,
    load_catalog,
    validate_ontology_document,
)

from .catalog_demo import DEMO, copy_demo, item, mutate, read_file, write_file

LISTS = (
    "domains",
    "identifiers",
    "code_sets",
    "concepts",
    "relations",
    "constraints",
    "terms",
    "representations",
)


@pytest.fixture(scope="module")
def demo() -> dict:
    return build_ontology(load_catalog(DEMO))


def test_the_document_names_its_format_and_its_catalog(demo: dict) -> None:
    assert demo["doc_format"] == "ontology-json/3"
    assert demo["catalog"] == {
        "name": "demo-lending",
        "description": load_catalog(DEMO).manifest["description"],
        "format": "catalog-yaml/1",
    }
    validate_ontology_document(demo)


def test_counts_match_the_lists(demo: dict) -> None:
    for key in LISTS:
        assert demo["counts"][key] == len(demo[key]), key
    assert demo["counts"]["derived_relations"] == 7
    assert demo["counts"]["attributes"] == sum(
        len(concept["attributes"]) for concept in demo["concepts"]
    )


def test_lists_are_sorted_by_their_key(demo: dict) -> None:
    for key in LISTS:
        if key in ("terms", "representations"):
            continue
        ids = [entry["id"] for entry in demo[key]]
        assert ids == sorted(ids), key
    assert [r["table"] for r in demo["representations"]] == sorted(
        r["table"] for r in demo["representations"]
    )
    terms = [(t["term"], t["refers_to"]) for t in demo["terms"]]
    assert terms == sorted(terms)


def test_event_participants_become_participation_relations(demo: dict) -> None:
    derived = [r for r in demo["relations"] if r.get("derived_from")]

    assert len(derived) == 7
    loan = item(demo["relations"], "rel:repayment.loan")
    assert loan == {
        "id": "rel:repayment.loan",
        "kind": "participation",
        "from": "concept:repayment",
        "to": "concept:loan",
        "name": "loan",
        "cardinality": {"from": "0..*", "to": "1..*"},
        "derived_from": {"event": "concept:repayment", "role_name": "loan"},
        "status": "confirmed",
        "source": "sql",
        "evidence": [],
    }
    assert item(demo["relations"], "rel:repayment.payer")["cardinality"]["to"] == "1"


def test_defaults_are_filled_so_every_object_has_the_same_keys(demo: dict) -> None:
    term = item(demo["terms"], "term", "借据")
    assert term["status"] == "drafted"
    assert term["source"] is None
    assert term["evidence"] == []
    customer = item(demo["concepts"], "concept:customer")
    assert customer["synonyms"] == ["用户"]
    assert item(demo["concepts"], "concept:channel")["synonyms"] == []
    gender = item(customer["attributes"], "attr:customer.gender")
    assert (gender["status"], gender["source"]) == ("confirmed", "owner")


def test_arises_when_scope_and_code_values_are_normalised(demo: dict) -> None:
    verified = item(demo["identifiers"], "id:verified_customer_no")
    assert verified["arises_when"] == {
        "condition": "assigned when the customer passes identity verification",
        "state": "concept:customer#verified",
    }
    assert item(demo["identifiers"], "id:app_account_id")["scope"] == {
        "per": ["concept:channel"]
    }
    assert item(demo["identifiers"], "id:loan_no")["scope"] == "global"
    values = item(demo["code_sets"], "code:verification_status")["values"]
    assert [v["value"] for v in values] == ["0", "1"]
    assert [v["retired"] for v in values] == [False, False]


def test_a_text_arises_when_becomes_a_condition(tmp_path: Path) -> None:
    root = copy_demo(tmp_path)
    mutate(
        root,
        "identifiers.yaml",
        lambda d: item(d["identifiers"], "id:loan_no").update(
            arises_when="assigned at contract signing"
        ),
    )

    document = build_ontology(load_catalog(root))

    loan_no = item(document["identifiers"], "id:loan_no")
    assert loan_no["arises_when"] == {"condition": "assigned at contract signing"}


def test_bindings_keep_their_column_order(demo: dict) -> None:
    info = item(demo["representations"], "table", "demo_dwd.dwd_party_customer_info_df")
    assert [b["column"] for b in info["bindings"]][:3] == [
        "customer_id",
        "verified_customer_no",
        "gender_cd",
    ]
    gender = info["bindings"][2]
    assert gender["code_map"] == {"F": "female", "M": "male", "U": "unknown"}


def _loan_binding(document: dict, column: str) -> dict:
    loan = item(document["representations"], "table", "demo_dwd.dwd_lending_loan_df")
    return item(loan["bindings"], "column", column)


def test_a_foreign_attribute_carries_its_via(demo: dict) -> None:
    assert _loan_binding(demo, "customer_gender_cd") == {
        "column": "customer_gender_cd",
        "to": "foreign_attribute",
        "ref": "attr:customer.gender",
        "via": "customer_id",
        "status": "confirmed",
        "source": "sql",
        "evidence": [],
    }


def test_a_foreign_identifier_of_the_tables_own_concept_is_a_self_reference(demo: dict) -> None:
    assert _loan_binding(demo, "orig_loan_no")["self_reference"] is True
    assert "self_reference" not in _loan_binding(demo, "customer_id")


def test_the_schema_requires_via_on_a_foreign_attribute(demo: dict) -> None:
    import copy

    import jsonschema

    broken = copy.deepcopy(demo)
    loan = item(broken["representations"], "table", "demo_dwd.dwd_lending_loan_df")
    del item(loan["bindings"], "column", "customer_gender_cd")["via"]

    with pytest.raises(jsonschema.ValidationError):
        validate_ontology_document(broken)


def test_the_build_does_not_depend_on_file_layout(tmp_path: Path, demo: dict) -> None:
    """Same objects, other files and order: the same bytes."""
    root = copy_demo(tmp_path)
    merged: list = []
    for path in sorted((root / "concepts").glob("*.yaml"), reverse=True):
        merged.extend(read_file(path)["concepts"])
        path.unlink()
    write_file(root / "concepts" / "all.json", {"concepts": merged})

    rebuilt = build_ontology(load_catalog(root))

    assert json.dumps(rebuilt, ensure_ascii=False) == json.dumps(demo, ensure_ascii=False)


def test_two_builds_are_identical() -> None:
    first = build_ontology(load_catalog(DEMO))
    second = build_ontology(load_catalog(DEMO))
    assert json.dumps(first) == json.dumps(second)


def test_an_invalid_catalog_is_not_built(tmp_path: Path) -> None:
    root = copy_demo(tmp_path)
    mutate(root, "terms.yaml", lambda d: d["terms"][0].update(refers_to="concept:ghost"))

    with pytest.raises(CatalogError, match="term_refers_to"):
        build_ontology(load_catalog(root))


def test_a_derived_id_that_collides_with_a_declared_one_is_an_error(tmp_path: Path) -> None:
    root = copy_demo(tmp_path)
    mutate(
        root,
        "relations.yaml",
        lambda d: d["relations"][0].update(id="rel:repayment.loan"),
    )

    with pytest.raises(CatalogError, match="duplicate_id"):
        build_ontology(load_catalog(root))
