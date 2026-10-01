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

from .catalog_demo import DEMO, copy_demo, demo_tables, item, mutate, parse_demo_corpus


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


def test_a_table_the_catalog_spells_in_upper_case_still_gets_its_evidence(
    corpus: Path, tmp_path: Path
) -> None:
    root = copy_demo(tmp_path / "catalog")
    loan = "demo_dwd.dwd_lending_loan_df"
    mutate(root, "mapping/lending.yaml",
           lambda d: item(d["representations"], "table", loan).update(table=loan.upper()))
    out = tmp_path / "out"

    assert main(["catalog", "build", str(root), "--out", str(out), "--lineage", str(corpus)]) == 0

    document = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    assert _rep(document, loan)["producing_tasks"] == ["dwd_lending_loan_daily"]


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


def test_a_card_column_spelled_in_upper_case_is_the_bound_column(tables_json: Path) -> None:
    """Hive names ignore case: a card column ``LOAN_STATUS`` is the binding ``loan_status``."""
    tables = json.loads(tables_json.read_text(encoding="utf-8"))
    for card in tables["tables"]:
        for column in card.get("columns") or []:
            column["name"] = column["name"].upper()

    built = attach_evidence(build_ontology(load_catalog(DEMO)), tables=tables)

    bindings = built["evidence"]["bindings"]
    assert bindings["demo_dwd.dwd_lending_loan_status_his.loan_status"] == {"declared_only": True}


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


def test_a_self_join_counts_only_for_the_relation_its_column_names(tmp_path: Path) -> None:
    """``root_loan_no`` names the second self relation: its JOIN backs that one, not
    renews; ``orig_loan_no`` names none, so its JOIN still backs both."""
    from scope_lineage.render.catalog_evidence import JoinFact, LineageFacts, WriteStatement

    from .catalog_demo import SECOND_SELF_RELATION, add_second_self_relation

    loan = "demo_dwd.dwd_lending_loan_df"
    root = copy_demo(tmp_path)
    add_second_self_relation(root, root_loan_no=SECOND_SELF_RELATION)
    statement = WriteStatement(
        task="t",
        statement_id="stmt:001",
        target="demo_ads.ads_renewal_chain_df",
        joins=(
            JoinFact("b1", loan, loan, (("root_loan_no", "loan_no"),)),
            JoinFact("b2", loan, loan, (("orig_loan_no", "loan_no"),)),
        ),
    )
    document = build_ontology(load_catalog(root))

    merged = attach_evidence(document, lineage=LineageFacts(statements=(statement,), tasks=1))

    relations = merged["evidence"]["relations"]
    renews = relations["rel:loan_renews_loan"]["joins"]
    descends = relations[SECOND_SELF_RELATION]["joins"]
    assert renews["count"] == 1
    assert [s["on"] for s in renews["samples"]] == [f"{loan}.orig_loan_no = {loan}.loan_no"]
    assert descends["count"] == 2


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


# ------------------------------------------------ JOINs inside a producing task
#
# ``source_joins`` is a second kind of evidence, never added into ``joins``: a JOIN in a
# statement that writes one end's table, on the lineage source of a column that table
# binds as ``foreign_identifier`` to an identifier K of the other end, whose other key
# column holds K -- the JOIN the producing task made to fill that foreign key.

SOURCE = "demo_ods.ods_src_t"
SIDE = "demo_ods.ods_side_t"


def _producing(target: str, fields: dict, *joins, catalog: dict | None = None) -> dict:
    """``attach_evidence`` over one statement writing ``target``: ``fields`` maps a written
    column to its source columns, ``joins`` are ``(left, right, (lcol, rcol))``."""
    from scope_lineage.render.catalog_evidence import JoinFact, LineageFacts, WriteStatement

    statement = WriteStatement(
        task="t",
        statement_id="stmt:001",
        target=target,
        fields=tuple(
            {"column": column, "sources": list(sources), "expression": None}
            for column, sources in fields.items()
        ),
        joins=tuple(
            JoinFact(f"b{n}", left, right, (pair,)) for n, (left, right, pair) in enumerate(joins)
        ),
    )
    document = catalog if catalog is not None else _join_catalog()
    for rep in document["representations"]:
        rep.setdefault("grain", {"source": "declared", "identifiers": [], "extra": []})
    return attach_evidence(document, lineage=LineageFacts(statements=(statement,), tasks=1))


def _source_joins(merged: dict) -> dict:
    return {
        relation: entry["source_joins"]
        for relation, entry in merged["evidence"]["relations"].items()
        if "source_joins" in entry
    }


def test_a_join_that_fills_a_foreign_key_is_a_source_join(built: dict) -> None:
    """The repayment task joins its source to the loan table on the column that becomes
    the repayment's loan key; ``joins`` for the relation stays what it was."""
    relations = built["evidence"]["relations"]

    assert _source_joins(built) == {
        "rel:repayment.loan": {
            "count": 1,
            "samples": [
                {
                    "task": "dwd_lending_repayment_daily",
                    "statement_id": "stmt:001",
                    "column": "demo_dwd.dwd_lending_repayment_di.loan_no",
                    "on": "demo_ods.ods_repay_txn_di.loan_no = demo_dwd.dwd_lending_loan_df.loan_no",
                }
            ],
        }
    }
    assert relations["rel:repayment.loan"]["joins"]["count"] == 1
    assert built["evidence"]["inputs"]["lineage"]["relations_checked"] == 7


def test_a_source_join_is_counted_on_the_far_end_s_identifier() -> None:
    merged = _producing(
        CALL,
        {"cust_id": [f"{SOURCE}.cust_ref"]},
        (SOURCE, CUSTOMER, ("cust_ref", "cust_id")),
    )

    assert _source_joins(merged) == {
        "rel:customer_receives_call": {
            "count": 1,
            "samples": [
                {
                    "task": "t",
                    "statement_id": "stmt:001",
                    "column": f"{CALL}.cust_id",
                    "on": f"{SOURCE}.cust_ref = {CUSTOMER}.cust_id",
                }
            ],
        }
    }


def test_one_source_feeding_two_foreign_keys_anchors_both() -> None:
    """The source column feeds a foreign key on each of two identifiers of the far end;
    the JOIN that looks up the second one still counts, on the second column."""
    catalog = _join_catalog()
    item(catalog["concepts"], "concept:customer")["identifiers"].append("id:cust_alt")
    call = item(catalog["representations"], "table", CALL)
    call["bindings"].append(_binding("cust_alt", "foreign_identifier", "id:cust_alt"))
    catalog["identifiers"] = [{"id": "id:cust_alt", "spellings": [{"column": "alt_no"}]}]

    merged = _producing(
        CALL,
        {"cust_id": [f"{SOURCE}.cust_ref"], "cust_alt": [f"{SOURCE}.cust_ref"]},
        (SOURCE, SIDE, ("cust_ref", "alt_no")),
        catalog=catalog,
    )

    samples = _source_joins(merged)["rel:customer_receives_call"]["samples"]
    assert [(s["column"], s["on"]) for s in samples] == [
        (f"{CALL}.cust_alt", f"{SOURCE}.cust_ref = {SIDE}.alt_no")
    ]


def test_the_anchor_met_by_another_identifier_is_not_a_source_join() -> None:
    """Everything holds but the far side: it carries a phone number, not the customer id."""
    merged = _producing(
        CALL,
        {"cust_id": [f"{SOURCE}.cust_ref"]},
        (SOURCE, CONTACT, ("cust_ref", "phone_no")),
    )

    assert _source_joins(merged) == {}


def test_the_far_side_may_hold_the_identifier_by_its_spelling() -> None:
    """A table the catalog does not represent holds K when K is spelled there."""
    catalog = _join_catalog()
    catalog["identifiers"] = [
        {"id": "id:cust_id", "spellings": [{"column": "CUST_KEY", "table": SIDE}]},
        {"id": "id:phone_no", "spellings": [{"column": "tel"}]},
    ]

    merged = _producing(
        CALL,
        {"cust_id": [f"{SOURCE}.cust_ref"], "caller_phone": [f"{SOURCE}.dialed"]},
        (SOURCE, SIDE, ("cust_ref", "cust_key")),
        (SOURCE, SIDE, ("dialed", "tel")),
        (SOURCE, CONTACT, ("cust_ref", "tel")),
        catalog=catalog,
    )

    found = _source_joins(merged)
    assert found["rel:customer_receives_call"]["count"] == 1
    assert found["rel:call_reaches_contact"]["count"] == 1
    assert [s["on"] for s in found["rel:call_reaches_contact"]["samples"]] == [
        f"{SOURCE}.dialed = {SIDE}.tel"
    ]


def test_a_source_table_carrying_two_concepts_keys_proves_nothing_by_itself() -> None:
    """The source spells both a customer and a phone column; a JOIN of it on a third
    identifier fills no foreign key, so no relation gains a source join."""
    catalog = _join_catalog()
    catalog["identifiers"] = [
        {"id": "id:cust_id", "spellings": [{"column": "cust_id", "table": SOURCE}]},
        {"id": "id:phone_no", "spellings": [{"column": "phone_no", "table": SOURCE}]},
        {"id": "id:call_id", "spellings": [{"column": "call_id"}]},
    ]

    merged = _producing(
        CUSTOMER,
        {"cust_id": [f"{SOURCE}.cust_id"]},
        (SOURCE, CALL, ("call_id", "call_id")),
        (SOURCE, CONTACT, ("phone_no", "phone_no")),
        catalog=catalog,
    )

    assert _source_joins(merged) == {}


def test_an_identifier_column_is_never_an_anchor() -> None:
    """Only a ``foreign_identifier`` points at the other end; the table's own key does not,
    even when the other end is named by the same identifier (a role keyed by its player)."""
    catalog = _join_catalog()
    item(catalog["concepts"], "concept:contact")["identifiers"].append("id:cust_id")

    merged = _producing(
        CUSTOMER,
        {"cust_id": [f"{SOURCE}.cust_ref"]},
        (SOURCE, CONTACT, ("cust_ref", "cust_id")),
        catalog=catalog,
    )

    assert _source_joins(merged) == {}


def test_a_join_in_a_statement_writing_no_catalog_table_is_not_a_source_join() -> None:
    merged = _producing(
        "demo_ads.ads_t",
        {"cust_id": [f"{SOURCE}.cust_ref"]},
        (SOURCE, CUSTOMER, ("cust_ref", "cust_id")),
    )

    assert _source_joins(merged) == {}


def test_a_relation_with_one_end_untabled_still_gets_its_source_joins() -> None:
    """``joins`` needs a table at both ends; a source join needs only the written end's.
    The relation's entry then has no ``joins`` and is not counted as checked."""
    catalog = _join_catalog()
    catalog["representations"] = [
        rep for rep in catalog["representations"] if rep["concept"] != "concept:customer"
    ]

    catalog["identifiers"] = [{"id": "id:cust_id", "spellings": [{"column": "cust_id"}]}]

    merged = _producing(
        CALL,
        {"cust_id": [f"{SOURCE}.cust_ref"]},
        (SOURCE, SIDE, ("cust_ref", "cust_id")),
        catalog=catalog,
    )

    entry = merged["evidence"]["relations"]["rel:customer_receives_call"]
    assert set(entry) == {"source_joins"}
    assert entry["source_joins"]["count"] == 1
    assert merged["evidence"]["inputs"]["lineage"]["relations_checked"] == 1


def test_a_source_self_join_counts_only_on_a_self_referencing_column() -> None:
    """Writing the loan table: the source's parent column filling ``orig_loan_no`` joined
    to a loan number is a renewal; the loan's own number joined the same way is not."""
    loan = "demo_dwd.dwd_lending_loan_df"
    merged = _producing(
        loan,
        {"orig_loan_no": [f"{SOURCE}.parent_no"], "loan_no": [f"{SOURCE}.loan_no"]},
        (SOURCE, SOURCE, ("parent_no", "loan_no")),
        (SOURCE, loan, ("loan_no", "loan_no")),
        catalog=build_ontology(load_catalog(DEMO)),
    )

    renews = _source_joins(merged)["rel:loan_renews_loan"]
    assert renews["count"] == 1
    assert renews["samples"][0]["column"] == f"{loan}.orig_loan_no"
    assert renews["samples"][0]["on"] == f"{SOURCE}.parent_no = {SOURCE}.loan_no"


def test_a_self_relation_takes_no_anchor_the_build_did_not_mark_self_reference() -> None:
    """``session_id`` names the call only because its table binds it as ``identifier``;
    a column pointing at it is not another call, so filling it backs no self relation."""
    catalog = _join_catalog()
    catalog["relations"].append(
        {"id": "rel:call_follows_call", "from": "concept:call", "to": "concept:call"}
    )
    call = item(catalog["representations"], "table", CALL)
    call["bindings"] += [
        _binding("session_id", "identifier", "id:session_id"),
        _binding("parent_session", "foreign_identifier", "id:session_id"),
        _binding("prev_call_id", "foreign_identifier", "id:call_id", self_reference=True),
    ]

    merged = _producing(
        CALL,
        {"parent_session": [f"{SOURCE}.session_ref"], "prev_call_id": [f"{SOURCE}.prev_ref"]},
        (SOURCE, CALL, ("session_ref", "session_id")),
        (SOURCE, CALL, ("prev_ref", "call_id")),
        catalog=catalog,
    )

    follows = _source_joins(merged)["rel:call_follows_call"]
    assert [s["column"] for s in follows["samples"]] == [f"{CALL}.prev_call_id"]


def test_two_relations_between_the_same_ends_split_by_the_relation_a_column_names() -> None:
    catalog = _join_catalog()
    catalog["relations"].append(
        {"id": "rel:customer_disputes_call", "from": "concept:customer", "to": "concept:call"}
    )
    call = item(catalog["representations"], "table", CALL)
    item(call["bindings"], "column", "cust_id")["relation"] = "rel:customer_receives_call"

    merged = _producing(
        CALL,
        {"cust_id": [f"{SOURCE}.cust_ref"]},
        (SOURCE, CUSTOMER, ("cust_ref", "cust_id")),
        catalog=catalog,
    )

    assert set(_source_joins(merged)) == {"rel:customer_receives_call"}


def test_a_source_join_counts_only_for_the_relation_its_column_names(tmp_path: Path) -> None:
    from .catalog_demo import SECOND_SELF_RELATION, add_second_self_relation

    loan = "demo_dwd.dwd_lending_loan_df"
    root = copy_demo(tmp_path)
    add_second_self_relation(root, root_loan_no=SECOND_SELF_RELATION)

    merged = _producing(
        loan,
        {"root_loan_no": [f"{SOURCE}.first_no"]},
        (SOURCE, loan, ("first_no", "loan_no")),
        catalog=build_ontology(load_catalog(root)),
    )

    found = _source_joins(merged)
    assert found[SECOND_SELF_RELATION]["count"] == 1
    assert "rel:loan_renews_loan" not in found


def test_source_joins_validate_against_the_schema(built: dict) -> None:
    import copy

    import jsonschema

    validate_ontology_document(built)
    broken = copy.deepcopy(built)
    broken["evidence"]["relations"]["rel:repayment.loan"]["source_joins"]["samples"][0].pop(
        "column"
    )
    with pytest.raises(jsonschema.ValidationError):
        validate_ontology_document(broken)


# ----------------------------------------------------------------------- CLI


def test_build_reports_what_the_evidence_matched(corpus: Path, tmp_path: Path, capsys) -> None:
    out = tmp_path / "out"

    assert main(["catalog", "build", str(DEMO), "--out", str(out), "--lineage", str(corpus)]) == 0

    printed = capsys.readouterr().out
    assert "evidence: lineage 8 task(s), 7 of 9 representation(s) matched" in printed
    assert (
        "3 of 7 relation(s) backed by a JOIN between catalog tables, "
        "1 relation(s) by a JOIN inside a producing task"
    ) in printed
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
