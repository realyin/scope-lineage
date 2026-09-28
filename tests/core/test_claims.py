"""The claim record: a conclusion, the object it is about, and what stands against it."""

from __future__ import annotations

import pytest

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
