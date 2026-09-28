"""The claim record: a conclusion, the object it is about, and what stands against it."""

from __future__ import annotations

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render import glossary_values
from scope_lineage.render.claims import (
    CONDITIONAL,
    CONFLICTED,
    HYPOTHESIS,
    PROVEN,
    STATUSES,
    SUBJECT_TABLE_STATE,
    SUBJECT_WRITE_BATCH,
    UNKNOWN,
    Claim,
    Subject,
)
from scope_lineage.render.semantic_profile import grouped_key_claim, ranking_key_claim
from scope_lineage.render.semantic_text import RANKING_WINDOW_FUNCTIONS
from scope_lineage.scope.scope_builder import parse_scope_lineage


def _claim(**overrides) -> Claim:
    fields = {
        "kind": "unique_by",
        "subject": Subject(SUBJECT_TABLE_STATE, ("mart.t",)),
        "content": ("id",),
        "status": PROVEN,
        "rule": "R-REPLACE-STATE",
    }
    fields.update(overrides)
    return Claim(**fields)


def test_a_claim_names_a_declared_rule() -> None:
    with pytest.raises(ValueError, match="R-NOT-A-RULE"):
        _claim(rule="R-NOT-A-RULE")


def test_a_claim_names_a_known_status() -> None:
    with pytest.raises(ValueError, match="certain"):
        _claim(status="certain")


def test_a_heuristic_rule_cannot_prove_anything() -> None:
    """``R-DIRECT-JOIN`` reads the author's assumption; it tops out at hypothesis."""
    with pytest.raises(ValueError, match="heuristic"):
        _claim(rule="R-DIRECT-JOIN", status=PROVEN)


def test_a_defeater_withdraws_a_proof() -> None:
    claim = _claim().defeated_by("appending_producer", "生产任务以追加方式写入")

    assert claim.status == UNKNOWN
    assert claim.defeaters == (("appending_producer", "生产任务以追加方式写入"),)


def test_a_claim_with_a_defeater_cannot_be_built_proven() -> None:
    with pytest.raises(ValueError, match="defeater"):
        _claim(defeaters=(("producer_key_conflict", "键不一致"),))


def test_weakening_never_strengthens() -> None:
    hypothesis = _claim(status=HYPOTHESIS, rule="R-DIRECT-JOIN")

    assert hypothesis.weakened_to(PROVEN).status == HYPOTHESIS
    assert _claim().weakened_to(CONDITIONAL).status == CONDITIONAL


def test_statuses_are_ordered_strongest_first() -> None:
    assert STATUSES.index(PROVEN) < STATUSES.index(CONDITIONAL) < STATUSES.index(
        HYPOTHESIS
    ) < STATUSES.index(UNKNOWN)
    assert CONFLICTED in STATUSES


def test_a_claim_is_about_one_subject() -> None:
    batch = _claim(subject=Subject(SUBJECT_WRITE_BATCH, ("task", "stmt:001", "mart.t")))

    assert batch.subject != _claim().subject
    assert batch.subject.kind == SUBJECT_WRITE_BATCH


# ------------------------------------------------ WP1c: one statement's uniqueness claims

SCHEMA = {"ods.e": ["id", "v", "ts", "dt"], "ods.base": ["id", "b"], "mart.dim": ["id", "v", "dt"]}


def _document(sql: str) -> dict:
    return to_lineage_dict(parse_scope_lineage(sql, "claims", schema=SCHEMA))


def _join(document: dict) -> tuple[str, dict]:
    block = next(
        block
        for block in document["scopes"]["ROOT"]["logic_blocks"]
        if block["logic_type"] == "join"
    )
    return block["logic_block_id"], block["join_relation_detail"]


def test_a_group_by_proves_its_scopes_rows_unique_by_the_free_keys() -> None:
    document = _document(
        "INSERT INTO mart.t WITH g AS (SELECT id, dt, MAX(v) AS v FROM ods.e "
        "WHERE dt = '1' GROUP BY id, dt) SELECT b.id, g.v FROM ods.base b "
        "LEFT JOIN g ON b.id = g.id"
    )

    claim = grouped_key_claim(document, "cte:g")

    assert claim.subject == ("query_rows", ("cte:g",))
    assert claim.rule == "R-PIN-DROP"
    assert claim.content == ("id",)
    assert claim.status == "proven"


def test_an_aggregate_without_group_by_is_one_row() -> None:
    document = _document(
        "INSERT INTO mart.t WITH g AS (SELECT MAX(v) AS v FROM ods.e) "
        "SELECT b.id, g.v FROM ods.base b CROSS JOIN g"
    )

    claim = grouped_key_claim(document, "cte:g")

    assert claim.rule == "R-EMPTY-GROUPING"
    assert claim.content == ()


def test_a_scope_that_does_not_aggregate_has_no_grouping_claim() -> None:
    document = _document("INSERT INTO mart.t SELECT id FROM ods.e")

    assert grouped_key_claim(document, "ROOT") is None


RANKED = (
    "INSERT INTO mart.t WITH r AS (SELECT id, v, {fn}() OVER (PARTITION BY id ORDER BY ts)"
    " AS rk FROM ods.e) SELECT b.id, r.v FROM ods.base b LEFT JOIN r ON b.id = r.id "
    "AND r.rk = 1"
)


def test_row_number_first_proves_at_most_one_row_per_partition() -> None:
    document = _document(RANKED.format(fn="ROW_NUMBER"))

    claim = ranking_key_claim(document, "cte:r", _join(document), ["id"])

    assert claim.rule == "R-ROWNUM-FIRST"
    assert claim.status == "proven"
    assert claim.content == ("id",)


def test_rank_first_is_an_intent_only_when_asked_for() -> None:
    document = _document(RANKED.format(fn="RANK"))

    assert ranking_key_claim(document, "cte:r", _join(document), ["id"]) is None
    intent = ranking_key_claim(
        document, "cte:r", _join(document), ["id"], RANKING_WINDOW_FUNCTIONS
    )
    assert intent.rule == "R-RANK-FIRST"
    assert intent.status == "hypothesis"


# ------------------------------------------------------------ WP2: value-set claims


def _entry(basis: str, *observations: tuple[str, str, str]) -> dict:
    return {
        "closed_set": {"values": ["1", "2"], "basis": basis},
        "observations": [
            {"task": task, "statement_id": statement, "context": context}
            for task, statement, context in observations
        ],
    }


def _reader(task: str, statement: str | None = "stmt:001") -> Subject:
    return Subject("query_rows", (task, statement))


def test_an_in_list_closes_the_rows_of_the_statement_that_filtered() -> None:
    entry = _entry("in_list", ("task_a", "stmt:001", "filter_in"))

    claim = glossary_values.column_closed_claim([(entry, "source")], _reader("task_a"))

    assert claim.rule == "R-IN-FILTER"
    assert claim.subject == ("query_rows", ("task_a", "stmt:001"))
    assert claim.status == "proven"


def test_an_in_list_does_not_close_another_statements_rows() -> None:
    entry = _entry("in_list", ("task_a", "stmt:001", "filter_in"))

    assert glossary_values.column_closed_claim([(entry, "source")], _reader("task_b")) is None


def test_an_exhaustive_case_closes_the_column_it_writes() -> None:
    entry = _entry("case_exhaustive", ("task_a", "stmt:001", "case_then"))

    claim = glossary_values.column_closed_claim([(entry, "output")], _reader("task_b"))

    assert claim.rule == "R-CASE-OUTPUT"
    assert claim.subject.kind == "write_batch"


def test_a_filter_is_only_a_hint_about_a_physical_column() -> None:
    from scope_lineage.render.ontology import value_set_claim

    claim = value_set_claim("ods.orders", "state", [_entry("in_list", ("t", "s", "filter_in"))])

    assert claim.subject == ("physical_column", ("ods.orders", "state"))
    assert claim.rule == "R-FILTER-HINT"
    assert claim.status == "hypothesis"


# ------------------------------------------------------ WP3: premises and conditions


def test_a_claim_cites_only_registered_premises() -> None:
    with pytest.raises(ValueError, match="A-NOT-A-PREMISE"):
        _claim(assumptions=("A-NOT-A-PREMISE",))


def test_every_standard_premise_is_registered() -> None:
    from scope_lineage.render.claims import ASSUMPTIONS, STANDARD_ASSUMPTIONS

    assert set(STANDARD_ASSUMPTIONS) <= set(ASSUMPTIONS)
    assert "A-WRITERS-CLOSED" in STANDARD_ASSUMPTIONS


def test_a_claim_resting_on_a_non_standard_premise_is_not_proven(monkeypatch) -> None:
    from scope_lineage.render import claims

    monkeypatch.setattr(claims, "STANDARD_ASSUMPTIONS", ("A-RUN-SUCCEEDED",))
    with pytest.raises(ValueError, match="A-WRITERS-CLOSED"):
        _claim(assumptions=("A-WRITERS-CLOSED",))


def _read(producer: str, consumer: str):
    from scope_lineage.render.semantic_profile import card_read_claim
    from scope_lineage.render.table_cards import build_table_cards

    cards = build_table_cards([_profile_of(producer, "producer")])
    document = _document(consumer)
    return card_read_claim(document, *_join(document), cards)


def _profile_of(sql: str, task: str) -> dict:
    from scope_lineage.render.semantic_profile import build_semantic_profile

    return build_semantic_profile(to_lineage_dict(parse_scope_lineage(sql, task, schema=SCHEMA)))


PARTITION_PRODUCER = (
    "INSERT OVERWRITE TABLE mart.dim PARTITION (dt = '1') "
    "SELECT id, MAX(v) AS v FROM ods.e GROUP BY id"
)


def test_a_read_pinning_the_partition_is_proven() -> None:
    claim = _read(
        PARTITION_PRODUCER,
        "INSERT INTO mart.t SELECT b.id, d.v FROM ods.base b LEFT JOIN mart.dim d "
        "ON b.id = d.id WHERE d.dt = '1'",
    )

    assert claim.rule == "R-READ-PIN"
    assert claim.status == "proven"
    assert claim.subject.kind == "read_view"


def test_a_read_across_partitions_is_conditional_on_pinning_them() -> None:
    claim = _read(
        PARTITION_PRODUCER,
        "INSERT INTO mart.t SELECT b.id, d.v FROM ods.base b LEFT JOIN mart.dim d "
        "ON b.id = d.id",
    )

    assert claim.status == "conditional"
    assert claim.conditions == (("partition_columns_pinned", ("dt",)),)


def test_a_partition_producers_claim_rests_on_the_metadata_too() -> None:
    from scope_lineage.render.semantic_profile import card_key_claim
    from scope_lineage.render.table_cards import build_table_cards

    cards = build_table_cards([_profile_of(PARTITION_PRODUCER, "producer")])
    claim = card_key_claim(next(item for item in cards["tables"] if item["table"] == "mart.dim"))

    assert claim.assumptions == ("A-WRITERS-CLOSED", "A-METADATA-AUTHORITATIVE")


def test_a_candidate_key_read_across_partitions_stays_a_hypothesis() -> None:
    """A condition only ever weakens: it cannot lift a candidate key to ``conditional``."""
    from scope_lineage.render.semantic_profile import card_read_claim
    from scope_lineage.render.table_cards import build_table_cards

    cards = build_table_cards([_profile_of(PARTITION_PRODUCER, "producer")])
    card = next(item for item in cards["tables"] if item["table"] == "mart.dim")
    card["produced_by"][0]["key_confidence"] = "candidate"
    document = _document(
        "INSERT INTO mart.t SELECT b.id, d.v FROM ods.base b LEFT JOIN mart.dim d "
        "ON b.id = d.id"
    )

    claim = card_read_claim(document, *_join(document), cards)

    assert claim.status == "hypothesis"
    assert claim.conditions == (("partition_columns_pinned", ("dt",)),)
