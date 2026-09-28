"""The claim record: a conclusion, the object it is about, and what stands against it."""

from __future__ import annotations

import pytest

from scope_lineage.contract import to_lineage_dict
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

SCHEMA = {"ods.e": ["id", "v", "ts", "dt"], "ods.base": ["id", "b"]}


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
