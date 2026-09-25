"""``catalog query``: short answers from a built ontology.json, for a person or an agent.

Every query runs against the recorded demo document (built over the demo corpus, so the
evidence is there too) -- the same file ``test_catalog_pages`` pins byte for byte.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.cli import main
from scope_lineage.render.catalog_query import QUERY_KINDS, query_catalog, render_query_text

ONTOLOGY = Path(__file__).parent / "fixtures" / "catalog" / "ontology.json"


@pytest.fixture(scope="module")
def document() -> dict:
    return json.loads(ONTOLOGY.read_text(encoding="utf-8"))


def _one(document: dict, kind: str, term: str) -> dict:
    result = query_catalog(document, kind, term)
    assert result["query"] == {"kind": kind, "term": term}
    assert len(result["matches"]) == 1, result["matches"]
    return result["matches"][0]


def test_the_six_kinds() -> None:
    assert QUERY_KINDS == ("concept", "table", "column", "identifier", "attribute", "related")


# ---------------------------------------------------------------- concept


@pytest.mark.parametrize(
    ("term", "matched_by"),
    [
        ("concept:customer", "id"),
        ("客户", "name"),
        ("用户", "synonym"),
    ],
)
def test_a_concept_is_found_by_id_name_or_synonym(
    document: dict, term: str, matched_by: str
) -> None:
    match = _one(document, "concept", term)

    assert match["id"] == "concept:customer"
    assert match["matched_by"] == matched_by


def test_a_concept_is_found_by_a_term_too(document: dict) -> None:
    match = _one(document, "concept", "对客借据")

    assert match["id"] == "concept:loan"


def test_a_concept_answer_is_its_identity_attributes_and_tables(document: dict) -> None:
    match = _one(document, "concept", "客户")

    assert match["kind"] == "entity"
    assert match["domain"] == {"id": "domain:party", "name": "客户与账户"}
    assert match["identifiers"] == [
        {"id": "id:customer_id", "name": "客户号", "primary": True},
        {"id": "id:verified_customer_no", "name": "认证客户号", "primary": False},
    ]
    assert [a["id"] for a in match["attributes"]] == [
        "attr:customer.gender",
        "attr:customer.registered_at",
        "attr:customer.verification_status",
    ]
    assert match["states"] == ["未认证", "已认证"]
    assert match["tables"] == [
        {"table": "demo_dwd.dwd_party_customer_ext_df", "kind": "extension"},
        {"table": "demo_dwd.dwd_party_customer_info_df", "kind": "core"},
    ]
    assert match["page"] == "concepts/customer.md"


def test_nothing_matches_an_unknown_concept(document: dict) -> None:
    assert query_catalog(document, "concept", "供应商")["matches"] == []


# ------------------------------------------------------------------ table


def test_a_table_answer_says_what_it_carries_and_what_each_column_points_at(document: dict) -> None:
    match = _one(document, "table", "spark_catalog.demo_dwd.dwd_lending_loan_df")

    assert match["table"] == "demo_dwd.dwd_lending_loan_df"
    assert match["concept"] == {"id": "concept:loan", "name": "借据"}
    assert match["kind"] == "core"
    columns = {c["column"]: c for c in match["columns"]}
    assert {key: columns["loan_no"][key] for key in ("to", "ref", "ref_name")} == {
        "to": "identifier",
        "ref": "id:loan_no",
        "ref_name": "借据号",
    }
    assert columns["principal_amt"]["evidence"]["sources"] == [
        "demo_ods.ods_loan_contract_df.principal"
    ]
    assert columns["loan_status"]["code_map"] == {"1": "normal", "2": "overdue", "3": "settled"}
    assert columns["dt"] == {"column": "dt", "to": "technical"}
    assert match["evidence"]["producing_tasks"] == ["dwd_lending_loan_daily"]


def test_a_table_the_catalog_does_not_map_matches_nothing(document: dict) -> None:
    assert query_catalog(document, "table", "demo_ods.ods_loan_contract_df")["matches"] == []


# ----------------------------------------------------------------- column


def test_a_column_answer_names_the_attribute_and_its_concept(document: dict) -> None:
    match = _one(document, "column", "demo_dwd.dwd_party_customer_info_df.gender_cd")

    assert match["to"] == "attribute"
    assert match["ref"] == "attr:customer.gender"
    assert match["ref_name"] == "性别"
    assert match["concept"] == {"id": "concept:customer", "name": "客户"}
    assert match["code_map"] == {"F": "female", "M": "male", "U": "unknown"}


def test_a_column_bound_to_an_identifier(document: dict) -> None:
    match = _one(document, "column", "x.demo_dwd.dwd_lending_repayment_di.loan_no")

    assert match["table"] == "demo_dwd.dwd_lending_repayment_di"
    assert (match["to"], match["ref"]) == ("foreign_identifier", "id:loan_no")
    assert match["concept"] == {"id": "concept:loan", "name": "借据"}


def test_a_column_the_catalog_only_spells_is_answered_by_the_spelling(document: dict) -> None:
    match = _one(document, "column", "demo_ods.ods_core_customer_df.cust_no")

    assert match == {
        "table": "demo_ods.ods_core_customer_df",
        "column": "cust_no",
        "spelling_of": {"id": "id:customer_id", "name": "客户号"},
    }


# ------------------------------------------------------------- identifier


def test_an_identifier_by_name_lists_where_it_is_bound(document: dict) -> None:
    match = _one(document, "identifier", "借据号")

    assert match["id"] == "id:loan_no"
    assert match["identifies"] == {"id": "concept:loan", "name": "借据"}
    assert {
        "table": "demo_dwd.dwd_lending_repayment_di",
        "column": "loan_no",
        "to": "foreign_identifier",
    } in (match["bound_columns"])


def test_an_identifier_by_a_spelling(document: dict) -> None:
    match = _one(document, "identifier", "cust_no")

    assert match["id"] == "id:customer_id"
    assert match["matched_by"] == "spelling"


# -------------------------------------------------------------- attribute


def test_an_attribute_lists_the_table_columns_it_lands_in(document: dict) -> None:
    match = _one(document, "attribute", "性别")

    assert match["concept"] == {"id": "concept:customer", "name": "客户"}
    assert match["code_set"]["values"][0] == {"value": "F", "meaning": "female", "retired": False}
    assert [(c["table"], c["column"]) for c in match["columns"]] == [
        ("demo_dwd.dwd_lending_borrower_df", "gender_cd"),
        ("demo_dwd.dwd_party_customer_info_df", "gender_cd"),
    ]


def test_an_attribute_by_a_term(document: dict) -> None:
    match = _one(document, "attribute", "罚息")

    assert match["id"] == "attr:loan.overdue_penalty"
    assert match["columns"][0]["derivation"] == "sum of the daily penalty accruals up to dt"


# ---------------------------------------------------------------- related


def test_related_is_the_one_hop_neighbourhood(document: dict) -> None:
    match = _one(document, "related", "借据")

    relations = {r["id"]: r for r in match["relations"]}
    assert relations["rel:borrower_owes_loan"]["reading"] == "借据 is owed by 借款人"
    assert relations["rel:borrower_owes_loan"]["other"] == {
        "id": "concept:borrower",
        "name": "借款人",
    }
    assert relations["rel:borrower_owes_loan"]["joins"] == 1
    assert [e["event"]["id"] for e in match["events"]] == [
        "concept:disbursement",
        "concept:fee_waiver",
        "concept:repayment",
    ]
    assert match["roles"] == []
    assert [t["table"] for t in match["tables"]] == [
        "demo_dwd.dwd_lending_loan_df",
        "demo_dwd.dwd_lending_loan_status_his",
        "demo_dws.dws_lending_loan_summary_1d",
    ]


def test_related_of_a_player_and_of_a_role(document: dict) -> None:
    customer = _one(document, "related", "客户")
    borrower = _one(document, "related", "借款人")

    assert customer["roles"] == [
        {
            "id": "concept:borrower",
            "name": "借款人",
            "condition": "holds at least one loan whose status is not settled",
        }
    ]
    assert borrower["player"] == {"id": "concept:customer", "name": "客户"}


def test_related_of_an_event_names_its_participants(document: dict) -> None:
    match = _one(document, "related", "还款")

    assert [(p["role_name"], p["concept"]["id"]) for p in match["participants"]] == [
        ("loan", "concept:loan"),
        ("payer", "concept:customer"),
    ]


# ------------------------------------------------------------------- text


def test_the_text_answer_is_short(document: dict) -> None:
    text = render_query_text(query_catalog(document, "concept", "客户"))

    assert text.splitlines()[0] == "客户 concept:customer · 实体 · 客户与账户 · 已确认（owner）"
    assert "页面：concepts/customer.md" in text
    assert len(text.splitlines()) <= 8


def test_every_kind_has_a_text_answer(document: dict) -> None:
    terms = {
        "concept": "借据",
        "table": "demo_dwd.dwd_lending_loan_df",
        "column": "demo_dwd.dwd_lending_loan_df.loan_status",
        "identifier": "id:customer_id",
        "attribute": "attr:loan.principal",
        "related": "客户",
    }
    for kind, term in terms.items():
        text = render_query_text(query_catalog(document, kind, term))
        assert text.strip(), kind
        assert "无匹配" not in text, kind


# -------------------------------------------------------------------- CLI


def test_query_prints_text(capsys) -> None:
    assert main(["catalog", "query", str(ONTOLOGY), "table", "demo_dwd.dwd_lending_loan_df"]) == 0

    out = capsys.readouterr().out
    assert out.startswith("demo_dwd.dwd_lending_loan_df · 借据 concept:loan · 核心")


def test_query_json_is_the_structured_result(document: dict, capsys) -> None:
    assert main(["catalog", "query", str(ONTOLOGY), "attribute", "本金", "--json"]) == 0

    assert json.loads(capsys.readouterr().out) == query_catalog(document, "attribute", "本金")


def test_a_query_with_no_match_exits_one(capsys) -> None:
    assert main(["catalog", "query", str(ONTOLOGY), "concept", "供应商"]) == 1

    captured = capsys.readouterr()
    assert "无匹配" in captured.out


def test_an_unknown_kind_is_an_argument_error() -> None:
    with pytest.raises(SystemExit) as raised:
        main(["catalog", "query", str(ONTOLOGY), "domain", "x"])

    assert raised.value.code == 2


def test_a_missing_ontology_exits_two(tmp_path: Path, capsys) -> None:
    assert main(["catalog", "query", str(tmp_path / "none.json"), "concept", "客户"]) == 2
    assert "does not exist" in capsys.readouterr().err
