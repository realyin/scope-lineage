"""``catalog build --lineage/--tables``: corpus evidence merged beside the catalog.

The demo catalog is built over the demo corpus (``examples/catalog-demo-corpus``): eight
synthetic tasks writing and reading the demo's tables, one of them spelling its target
with a catalog prefix. Every assertion here names a fact that corpus was written to
produce, so a red test says which reader stopped reaching the catalog.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.catalog import build_ontology, load_catalog, validate_ontology_document
from scope_lineage.cli import main
from scope_lineage.render.catalog_evidence import (
    EXPRESSION_LIMIT,
    attach_evidence,
    catalog_table_name,
)

from .catalog_demo import DEMO, demo_tables, parse_demo_corpus


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> Path:
    return parse_demo_corpus(tmp_path_factory.mktemp("corpus") / "lineage")


@pytest.fixture(scope="module")
def tables_json(corpus: Path, tmp_path_factory) -> Path:
    return demo_tables(corpus, tmp_path_factory.mktemp("tables"))


@pytest.fixture(scope="module")
def built(corpus: Path, tables_json: Path, tmp_path_factory) -> dict:
    out = tmp_path_factory.mktemp("built")
    args = ["catalog", "build", str(DEMO), "--out", str(out)]
    assert main([*args, "--lineage", str(corpus), "--tables", str(tables_json)]) == 0
    return json.loads((out / "ontology.json").read_text(encoding="utf-8"))


def _rep(document: dict, table: str) -> dict:
    return document["evidence"]["representations"][table]


# --------------------------------------------------------------------- the shape


def test_without_inputs_the_document_has_no_evidence_block() -> None:
    document = build_ontology(load_catalog(DEMO))

    assert "evidence" not in document
    assert attach_evidence(document) == document


def test_the_merged_document_still_validates_and_keeps_the_catalog(built: dict) -> None:
    plain = build_ontology(load_catalog(DEMO))

    validate_ontology_document(built)
    assert {key: value for key, value in built.items() if key != "evidence"} == plain


def test_the_schema_checks_the_evidence_block(built: dict) -> None:
    import copy

    import jsonschema

    broken = copy.deepcopy(built)
    loan = broken["evidence"]["representations"]["demo_dwd.dwd_lending_loan_df"]
    loan["grain_proof"]["confidence"] = "certain"

    with pytest.raises(jsonschema.ValidationError):
        validate_ontology_document(broken)


def test_the_evidence_block_names_its_inputs(built: dict) -> None:
    inputs = built["evidence"]["inputs"]

    assert inputs["lineage"]["tasks"] == 8
    assert inputs["lineage"]["statements"] == 8
    assert inputs["lineage"]["representations_matched"] == 7
    assert inputs["tables"]["representations_matched"] == 7


def test_table_names_are_matched_on_their_last_two_segments() -> None:
    assert catalog_table_name("spark_catalog.demo_dwd.t") == "demo_dwd.t"
    assert catalog_table_name("demo_dwd.t") == "demo_dwd.t"
    assert catalog_table_name("t") == "t"


# ----------------------------------------------------------- representations


def test_a_prefixed_target_still_reaches_its_representation(built: dict) -> None:
    loan = _rep(built, "demo_dwd.dwd_lending_loan_df")

    assert loan["producing_tasks"] == ["dwd_lending_loan_daily"]
    assert loan["refresh"] == ["day"]
    assert loan["upstream_tables"] == [
        "demo_ods.ods_loan_contract_df",
        "demo_ods.ods_loan_penalty_di",
    ]
    assert loan["downstream_tables"] == [
        "demo_ads.ads_collection_overdue_loan_df",
        "demo_dwd.dwd_lending_borrower_df",
        "demo_dwd.dwd_lending_repayment_di",
        "demo_dws.dws_lending_loan_summary_1d",
    ]


def test_grain_proof_comes_from_the_producing_task(built: dict) -> None:
    customer = _rep(built, "demo_dwd.dwd_party_customer_info_df")["grain_proof"]
    account = _rep(built, "demo_dwd.dwd_party_account_map_df")["grain_proof"]

    assert customer == {
        "confidence": "proven",
        "keys": ["customer_id"],
        "basis": "window_partition",
        "task": "dwd_party_customer_info_daily",
    }
    assert account["confidence"] == "proven"
    assert account["keys"] == ["account_id", "channel_code"]


def test_a_grain_the_catalog_calls_proven_and_lineage_cannot_prove_is_a_conflict(
    built: dict,
) -> None:
    loan = _rep(built, "demo_dwd.dwd_lending_loan_df")

    assert loan["grain_proof"]["confidence"] == "candidate"
    assert loan["conflicts"] == [
        {"rule": "grain_not_proven", "declared_source": "proven", "confidence": "candidate"}
    ]


def test_partition_columns_do_not_make_a_grain_mismatch(built: dict) -> None:
    summary = _rep(built, "demo_dws.dws_lending_loan_summary_1d")

    assert summary["grain_proof"]["keys"] == ["channel_code"]
    assert "conflicts" not in summary


def test_a_table_nobody_writes_has_no_lineage_facts_but_keeps_its_card(built: dict) -> None:
    history = _rep(built, "demo_dwd.dwd_lending_loan_status_his")

    assert "producing_tasks" not in history
    assert history["downstream_tables"] == ["demo_ads.ads_loan_status_span_df"]
    assert history["declared_columns"] == 4
    assert history["used_columns"] == 3


def test_a_table_card_brings_the_table_comment(built: dict) -> None:
    assert _rep(built, "demo_dwd.dwd_lending_loan_status_his")["table_comment"] == (
        "Loan status history (zipper)"
    )


def test_a_table_outside_the_corpus_gets_no_entry(built: dict) -> None:
    assert "demo_dwd.dwd_party_customer_ext_df" not in built["evidence"]["representations"]


# ------------------------------------------------------------------ bindings


def test_a_binding_gains_its_physical_sources_and_expression(built: dict) -> None:
    principal = built["evidence"]["bindings"]["demo_dwd.dwd_lending_loan_df.principal_amt"]

    assert principal == {
        "sources": ["demo_ods.ods_loan_contract_df.principal"],
        "expression": "`l`.`principal`",
    }


def test_a_hand_written_derivation_is_never_supplemented(built: dict) -> None:
    bindings = built["evidence"]["bindings"]

    assert "demo_dwd.dwd_party_customer_info_df.register_time" not in bindings
    assert "demo_dwd.dwd_lending_loan_df.penalty_amt" not in bindings


def test_a_declared_column_nobody_uses_is_marked(built: dict) -> None:
    bindings = built["evidence"]["bindings"]

    assert bindings["demo_dwd.dwd_lending_loan_status_his.loan_status"] == {"declared_only": True}
    assert "declared_only" not in bindings["demo_dwd.dwd_lending_loan_df.principal_amt"]


def test_a_long_expression_is_cut_to_the_limit() -> None:
    document = build_ontology(load_catalog(DEMO))
    long_sql = "concat(" + ", ".join(["`l`.`principal`"] * 40) + ")"
    facts = _one_field_facts(long_sql)

    merged = attach_evidence(document, lineage=facts)
    expression = merged["evidence"]["bindings"]["demo_dwd.dwd_lending_loan_df.principal_amt"][
        "expression"
    ]

    assert len(expression) == EXPRESSION_LIMIT
    assert expression.endswith("…")


def _one_field_facts(expression: str):
    from scope_lineage.render.catalog_evidence import LineageFacts, WriteStatement

    statement = WriteStatement(
        task="t",
        statement_id="stmt:001",
        target="demo_dwd.dwd_lending_loan_df",
        inputs=("demo_ods.ods_loan_contract_df",),
        fields=({"column": "principal_amt", "sources": [], "expression": expression},),
        joins=(),
    )
    return LineageFacts(statements=(statement,), tasks=1)


# ----------------------------------------------------------------- relations


def test_joins_between_two_concepts_tables_are_counted(built: dict) -> None:
    relations = built["evidence"]["relations"]

    borrower = relations["rel:borrower_owes_loan"]["joins"]
    assert borrower["count"] == 1
    assert borrower["samples"] == [
        {
            "task": "ads_collection_overdue_borrower_daily",
            "statement_id": "stmt:001",
            "on": "demo_dwd.dwd_lending_borrower_df.customer_id = "
            "demo_dwd.dwd_lending_loan_df.customer_id",
        }
    ]
    assert relations["rel:customer_holds_app_account"]["joins"]["count"] == 1


def test_participation_relations_are_counted_too(built: dict) -> None:
    relations = built["evidence"]["relations"]

    assert relations["rel:repayment.loan"]["joins"]["count"] == 1
    assert relations["rel:fee_waiver.loan"]["joins"] == {"count": 0, "samples": []}


def test_a_self_relation_counts_only_joins_on_its_self_referencing_column() -> None:
    """``loan.orig_loan_no = loan.loan_no`` is a renewal; loan_no = loan_no across two
    loan tables is the same loan twice and says nothing about the relation."""
    from scope_lineage.render.catalog_evidence import JoinFact, LineageFacts, WriteStatement

    loan, history = "demo_dwd.dwd_lending_loan_df", "demo_dwd.dwd_lending_loan_status_his"
    statement = WriteStatement(
        task="t",
        statement_id="stmt:001",
        target="demo_ads.ads_renewal_chain_df",
        joins=(
            JoinFact("b1", loan, loan, (("orig_loan_no", "loan_no"),)),
            JoinFact("b2", loan, history, (("loan_no", "loan_no"),)),
        ),
    )
    document = build_ontology(load_catalog(DEMO))

    merged = attach_evidence(document, lineage=LineageFacts(statements=(statement,), tasks=1))

    assert merged["evidence"]["relations"]["rel:loan_renews_loan"]["joins"] == {
        "count": 1,
        "samples": [
            {"task": "t", "statement_id": "stmt:001", "on": f"{loan}.orig_loan_no = {loan}.loan_no"}
        ],
    }


# ------------------------------------------------ JOIN keys on the physical column
#
# A contact subquery ``b`` is joined to a call subquery ``a`` that renames the call's
# phone column, on three conditions; an outer IF picks the contact's customer only when
# ``b.phone_no`` matched, and a third table -- the customer's own -- is joined on the
# column name all three tables share. The phone column feeds that IF only as a
# condition, so it must never be reported as a customer key.

CALL = "demo_dwd.dwd_call_outbound_di"
CONTACT = "demo_dwd.dwd_contact_phone_df"
CUSTOMER = "demo_dwd.dwd_party_customer_df"
JOIN_SCHEMA = {
    CALL: ["call_id", "cust_id", "caller_phone", "channel_code", "dt"],
    CONTACT: ["cust_id", "phone_no", "channel_code", "dt"],
    CUSTOMER: ["cust_id", "channel_code", "dt"],
}
RENAMED_KEY_SQL = f"""
INSERT OVERWRITE TABLE demo_ads.ads_contact_call_stat_di
SELECT cu.cust_id, f.call_cnt
FROM {CUSTOMER} cu
LEFT JOIN (
  SELECT m.cust_id, COUNT(1) AS call_cnt
  FROM (
    SELECT IF(a.cust_id = '' AND b.phone_no IS NOT NULL, b.cust_id, a.cust_id) AS cust_id,
           a.dt
    FROM (SELECT call_id, cust_id, caller_phone AS dialed_no, channel_code, dt FROM {CALL}) a
    LEFT JOIN (SELECT cust_id, phone_no, channel_code, dt FROM {CONTACT}) b
      ON a.dialed_no = b.phone_no AND a.channel_code = b.channel_code AND a.dt = b.dt
  ) m
  GROUP BY m.cust_id
) f ON cu.cust_id = f.cust_id
"""


def _binding(column: str, to: str, ref: str, **extra) -> dict:
    return {"column": column, "to": to, "ref": ref, **extra}


def _join_catalog() -> dict:
    """The smallest document the relation merge reads: three concepts, one table each."""
    return {
        "concepts": [
            {"id": "concept:customer", "identifiers": ["id:cust_id"]},
            {"id": "concept:contact", "identifiers": ["id:phone_no"]},
            {"id": "concept:call", "identifiers": ["id:call_id"]},
        ],
        "relations": [
            {"id": "rel:customer_has_contact", "from": "concept:customer", "to": "concept:contact"},
            {"id": "rel:call_reaches_contact", "from": "concept:call", "to": "concept:contact"},
            {"id": "rel:customer_receives_call", "from": "concept:customer", "to": "concept:call"},
        ],
        "representations": [
            {
                "table": CUSTOMER,
                "concept": "concept:customer",
                "bindings": [_binding("cust_id", "identifier", "id:cust_id")],
            },
            {
                "table": CONTACT,
                "concept": "concept:contact",
                "bindings": [
                    _binding("phone_no", "identifier", "id:phone_no"),
                    _binding("cust_id", "foreign_identifier", "id:cust_id"),
                ],
            },
            {
                "table": CALL,
                "concept": "concept:call",
                "bindings": [
                    _binding("call_id", "identifier", "id:call_id"),
                    _binding("caller_phone", "foreign_identifier", "id:phone_no"),
                    _binding("cust_id", "foreign_identifier", "id:cust_id"),
                ],
            },
        ],
    }


def _sql_facts(sql: str):
    from scope_lineage.contract import to_lineage_dict
    from scope_lineage.render.catalog_evidence import lineage_facts
    from scope_lineage.scope.scope_builder import parse_scope_lineage

    document = to_lineage_dict(parse_scope_lineage(sql, "t", schema=JOIN_SCHEMA))
    return lineage_facts([(document, None)])


def _samples(merged: dict, relation: str) -> list[str]:
    joins = merged["evidence"]["relations"][relation]["joins"]
    return [sample["on"] for sample in joins["samples"]]


def test_a_renamed_join_key_is_reported_on_the_physical_column_behind_it() -> None:
    merged = attach_evidence(_join_catalog(), lineage=_sql_facts(RENAMED_KEY_SQL))

    assert _samples(merged, "rel:call_reaches_contact") == [
        f"{CALL}.caller_phone = {CONTACT}.phone_no"
    ]


def test_a_column_that_only_conditions_a_computed_key_is_never_that_key() -> None:
    """``f.cust_id`` is an IF over both sides; ``phone_no`` is only its condition."""
    merged = attach_evidence(_join_catalog(), lineage=_sql_facts(RENAMED_KEY_SQL))

    reported = [
        sample
        for relation in merged["evidence"]["relations"].values()
        for sample in relation["joins"]["samples"]
    ]
    assert not [s for s in reported if f"{CUSTOMER}.cust_id = {CONTACT}.phone_no" in s["on"]]
    assert merged["evidence"]["relations"]["rel:customer_has_contact"]["joins"]["count"] == 0
    assert _samples(merged, "rel:customer_receives_call") == [
        f"{CUSTOMER}.cust_id = {CALL}.cust_id"
    ]


def _key_pairs(sql: str) -> dict:
    from scope_lineage.contract import to_lineage_dict
    from scope_lineage.render.ontology import join_key_pairs
    from scope_lineage.scope.scope_builder import parse_scope_lineage

    document = to_lineage_dict(parse_scope_lineage(sql, "t", schema=JOIN_SCHEMA))
    return {
        table_pair: columns
        for _, _, found in join_key_pairs(document)
        for table_pair, columns in found.items()
    }


def test_a_key_computed_from_several_columns_is_carried_by_its_own_scopes_table() -> None:
    """``u.cust_id`` reads two columns, so it is neither; it is ``u``'s key, and the second
    ON names ``u`` -- not the JOIN's left input ``l`` -- so it is never ``l``'s table's."""
    pairs = _key_pairs(f"""
    INSERT OVERWRITE TABLE demo_ads.ads_t
    SELECT l.call_id
    FROM {CALL} l
    JOIN (SELECT COALESCE(cust_id, channel_code) AS cust_id, dt FROM {CUSTOMER}) u ON l.dt = u.dt
    JOIN {CONTACT} c ON u.cust_id = c.cust_id
    """)

    assert pairs[(CUSTOMER, CONTACT)] == [("cust_id", "cust_id")]
    assert (CALL, CONTACT) not in pairs


def test_a_key_computed_from_one_column_is_still_that_column() -> None:
    pairs = _key_pairs(f"""
    INSERT OVERWRITE TABLE demo_ads.ads_t
    SELECT a.call_id
    FROM (SELECT call_id, TRIM(caller_phone) AS dialed_no FROM {CALL}) a
    JOIN {CONTACT} b ON a.dialed_no = b.phone_no
    """)

    assert pairs == {(CALL, CONTACT): [("caller_phone", "phone_no")]}


def _one_join(left: str, right: str, *columns: tuple):
    from scope_lineage.render.catalog_evidence import JoinFact, LineageFacts, WriteStatement

    statement = WriteStatement(
        task="t",
        statement_id="stmt:001",
        target="demo_ads.ads_t",
        joins=(JoinFact("b1", left, right, tuple(columns)),),
    )
    return LineageFacts(statements=(statement,), tasks=1)


@pytest.mark.parametrize(
    ("left", "right", "columns"),
    [
        # one side is an identifier, the other is not bound as one at all
        (CUSTOMER, CONTACT, ("cust_id", "channel_code")),
        # both are identifying, but of two different identifiers
        (CUSTOMER, CONTACT, ("cust_id", "phone_no")),
        # both carry the same identifier -- of a third concept, not of these two
        (CALL, CONTACT, ("cust_id", "cust_id")),
    ],
)
def test_a_join_sample_needs_both_keys_bound_to_one_identifier_of_the_relation(
    left: str, right: str, columns: tuple
) -> None:
    catalog = _join_catalog()
    for rep in catalog["representations"]:
        rep["bindings"].append(_binding("channel_code", "attribute", "attr:channel_code"))

    merged = attach_evidence(catalog, lineage=_one_join(left, right, columns))

    assert all(
        entry["joins"] == {"count": 0, "samples": []}
        for entry in merged["evidence"]["relations"].values()
    )


def test_a_join_on_the_shared_identifier_is_counted() -> None:
    facts = _one_join(CONTACT, CUSTOMER, ("phone_no", "cust_id"), ("cust_id", "cust_id"))

    merged = attach_evidence(_join_catalog(), lineage=facts)

    assert _samples(merged, "rel:customer_has_contact") == [
        f"{CONTACT}.cust_id = {CUSTOMER}.cust_id"
    ]


def test_a_relation_with_an_end_that_has_no_table_is_not_counted(built: dict) -> None:
    relations = built["evidence"]["relations"]

    assert "rel:installment_loan_is_a_loan" not in relations
    assert "rel:app_account_opened_in_channel" not in relations
    assert "rel:disbursement.loan" not in relations


# ----------------------------------------------------------------------- CLI


def test_build_reports_what_the_evidence_matched(corpus: Path, tmp_path: Path, capsys) -> None:
    out = tmp_path / "out"

    assert main(["catalog", "build", str(DEMO), "--out", str(out), "--lineage", str(corpus)]) == 0

    printed = capsys.readouterr().out
    assert "evidence: lineage 8 task(s), 7 of 9 representation(s) matched" in printed
    document = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    assert "tables" not in document["evidence"]["inputs"]
    assert "declared_columns" not in _rep(document, "demo_dwd.dwd_lending_loan_df")


def test_build_with_tables_only_carries_the_card_counts(tables_json: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"

    assert (
        main(["catalog", "build", str(DEMO), "--out", str(out), "--tables", str(tables_json)]) == 0
    )

    document = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    loan = _rep(document, "demo_dwd.dwd_lending_loan_df")
    assert loan == {"table_comment": "Loan snapshot", "declared_columns": 8, "used_columns": 8}
    assert "lineage" not in document["evidence"]["inputs"]


def test_a_missing_lineage_path_exits_two(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "catalog",
            "build",
            str(DEMO),
            "--out",
            str(tmp_path / "out"),
            "--lineage",
            str(tmp_path / "nowhere"),
        ]
    )

    assert code == 2
    assert "does not exist" in capsys.readouterr().err
    assert not (tmp_path / "out" / "ontology.json").exists()


def test_a_tables_file_of_the_wrong_format_exits_one(tmp_path: Path, capsys) -> None:
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"doc_format": "glossary-json/1"}), encoding="utf-8")

    code = main(
        ["catalog", "build", str(DEMO), "--out", str(tmp_path / "out"), "--tables", str(wrong)]
    )

    assert code == 1
    assert "tables-json/1" in capsys.readouterr().err


def test_merging_twice_writes_the_same_bytes(corpus: Path, tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    for out in (first, second):
        assert (
            main(["catalog", "build", str(DEMO), "--out", str(out), "--lineage", str(corpus)]) == 0
        )

    assert (first / "ontology.json").read_bytes() == (second / "ontology.json").read_bytes()
