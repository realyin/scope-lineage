"""Check 10 and the observations of a join's right side (D16 3.3).

The requirement stays: a join whose right side is not proven unique on its keys is named.
An observation relaxes one thing only: a sentence calling such a join harmless to the row
count stops warning when

- the join's right side is a single table T (``right_tables == [T]``: a physical table or a
  subquery reading one table);
- the confirmations hold an observation of T (``input:T``) that found it unique on columns
  among the join's keys on T; and
- the sentence says it as an observation (观测) and names the observed partition.

Every join the sentence names needs its own observation; a claim about every join (都,
所有 ...) is no observation of one; a sentence in the prescribed observation form
(「观测（查询 …」) about a join the confirmations hold no observation of warns. Without a
confirmations path nothing changes; ``_safe_names`` is untouched.
"""

from __future__ import annotations

from pathlib import Path

from scope_lineage.semantics import validate_document
from scope_lineage.semantics.checks_meaning import check_fan_out
from scope_lineage.semantics.confirmed import TableConfirmed, confirmed_state, read_confirmations

from .table_semantics_demo import DEMO_TABLE, demo_packets, example, packet_of
from .test_semantic_observed import _entry, _file, _input

USER = "demo_dwd.dwd_probe_user_df"
OTHER = "demo_ods.ods_probe_other_df"
CALL = "demo_ods.ods_probe_call_df"
PARTITION = "分区 dt=20261119"
WARNING = "LEFT JOIN"
UNBACKED = "确认文件里没有"


def _join(rule_id: str, alias: str, key: str, tables=(USER,), status: str = "risk") -> dict:
    return {"id": rule_id, "kind": "join", "join_type": "LEFT_OUTER",
            "expression": f"a.{key} = {alias}.{key}", "task": "t0", "right": f"subq:{alias}",
            "right_tables": list(tables), "right_aliases": [alias],
            "columns": [f"{CALL}.{key}"] + [f"{table}.{key}" for table in tables],
            "fan_out": {"status": status, "reason": "右侧未被证明按连接键唯一", "path": "grain"}}


def _packet(*rules: dict) -> dict:
    return {"lineage": {"rules": list(rules)}}


def _observed(*entries: dict) -> TableConfirmed:
    return confirmed_state(list(entries)).get(DEMO_TABLE) or TableConfirmed()


def _of(table: str, *columns: str, **extra) -> dict:
    return _entry(f"input:{table}", _input(columns=columns, **extra))


def _said(rule_id: str, partition: str = PARTITION, claim: str = "在该分区内不放大") -> str:
    return (f"观测（查询 probe_1，{partition}，2026-11-20 执行）：{USER} 按 (open_id) 无重复，"
            f"{rule_id} {claim}；别的分区未观测，若出现重复会放大行数。")


def _problems(packet: dict, sentence: str, confirmed=None, kind: str = "risk") -> list[dict]:
    document = {"summary": {"row": {"note": "每个 id 一行。"},
                            "watch": [{"kind": kind, "text": sentence}]}}
    return [item for item in check_fan_out(document, packet, confirmed)
            if item["status"] != "pass"]


ONE = _packet(_join("p1", "b", "open_id"))
OPEN_ID = _of(USER, "open_id")


# ------------------------------------------------------------------ the relaxation


def test_an_observation_sentence_backed_by_the_confirmations_does_not_warn() -> None:
    (warning,) = _problems(ONE, _said("p1"))
    assert warning["status"] == "warn" and WARNING in warning["message"]
    assert _problems(ONE, _said("p1"), _observed(OPEN_ID)) == []


def test_the_join_must_still_be_named_in_the_note_or_a_risk() -> None:
    (problem,) = _problems(ONE, _said("p1"), _observed(OPEN_ID), kind="other")
    assert problem["status"] == "fail" and problem["at"] == "summary.row.note"


def test_an_observation_on_a_subset_of_the_keys_matches_one_on_more_does_not() -> None:
    packet = _packet({**_join("p1", "b", "open_id"),
                      "columns": [f"{CALL}.open_id", f"{USER}.open_id",
                                  f"{CALL}.app", f"{USER}.app"]})
    assert _problems(packet, _said("p1"), _observed(OPEN_ID)) == []
    wider = _observed(_of(USER, "open_id", "region"))
    assert any(WARNING in w["message"] for w in _problems(ONE, _said("p1"), wider))


def test_a_range_of_partitions_is_named_by_its_ends() -> None:
    ranged = _observed(_of(USER, "open_id", partition={
        "column": "dt", "from": "20261113", "to": "20261119", "count": 7}))
    assert _problems(ONE, _said("p1", "分区 dt 20261113–20261119"), ranged) == []


def test_an_observation_that_found_duplicates_relaxes_nothing_and_says_so() -> None:
    duplicated = _observed(_of(USER, "open_id", unique="no", duplicate_keys=3))
    (warning,) = _problems(ONE, _said("p1"), duplicated)
    assert WARNING in warning["message"]
    (problem,) = _problems(ONE, "每个 id 一行。", duplicated, kind="other")
    assert problem["status"] == "fail"
    assert problem["message"].endswith("；观测到 3 个重复键（分区 dt=20261119）")


# ------------------------------------------------------------------ guards


def test_a_right_side_reading_two_tables_does_not_match() -> None:
    packet = _packet(_join("p1", "b", "open_id", tables=(USER, OTHER)))
    confirmed = _observed(OPEN_ID, _of(OTHER, "open_id"))
    warnings = _problems(packet, _said("p1"), confirmed)
    assert any(WARNING in w["message"] for w in warnings)
    assert any(UNBACKED in w["message"] for w in warnings)


def test_one_table_joined_on_two_keys_needs_each_key_observed() -> None:
    packet = _packet(_join("p1", "b", "open_id"), _join("p2", "h", "user_id"))
    confirmed = _observed(OPEN_ID)
    assert _problems(packet, _said("p1"), confirmed) == []
    warnings = _problems(packet, _said("p2"), confirmed)
    assert any(WARNING in w["message"] for w in warnings)
    assert any(UNBACKED in w["message"] and "p2" in w["message"] for w in warnings)


def test_a_claim_about_every_join_is_no_observation_of_one() -> None:
    packet = _packet(_join("p1", "b", "open_id"), _join("p2", "h", "user_id"))
    confirmed = _observed(OPEN_ID, _of(USER, "user_id"))
    for claim in ("与 p2 都在该分区内不放大", "与 p2 在该分区内所有关联不放大"):
        (warning,) = _problems(packet, _said("p1", claim=claim), confirmed)
        assert WARNING in warning["message"]


def test_every_join_the_sentence_names_needs_its_own_observation() -> None:
    packet = _packet(_join("p1", "b", "open_id"), _join("p2", "h", "user_id"))
    sentence = _said("p1", claim="在该分区内不放大，p2 在该分区内不放大")
    assert any(WARNING in w["message"] for w in _problems(packet, sentence, _observed(OPEN_ID)))
    both = _observed(OPEN_ID, _of(USER, "user_id"))
    assert _problems(packet, sentence, both) == []


def test_a_rule_number_picks_among_joins_of_its_table_not_other_tables() -> None:
    # pN only says which join onto T the sentence means; another right table it names, by
    # table or by alias, is spoken of too and needs an observation of its own.
    packet = _packet(_join("p1", "b", "open_id"), _join("p2", "h", "open_id", tables=(OTHER,)))
    for claim in (f"在该分区内不放大，{OTHER} 的关联也在该分区内不放大",
                  "在该分区内不放大，h 也在该分区内不放大"):
        sentence = _said("p1", claim=claim)
        warnings = _problems(packet, sentence, _observed(OPEN_ID))
        assert any(WARNING in w["message"] for w in warnings), claim
        assert _problems(packet, sentence, _observed(OPEN_ID, _of(OTHER, "open_id"))) == []


def test_every_no_fan_out_clause_carries_the_observed_partition() -> None:
    for claim in ("在该分区内不放大，别的分区同样不放大", "在该分区内不放大，其余日期也不放大"):
        (warning,) = _problems(ONE, _said("p1", claim=claim), _observed(OPEN_ID))
        assert WARNING in warning["message"], claim
    # the partition's value, 这些分区 or 全表 in the clause says it as well as 该分区
    for claim in ("在 dt=20261119 内不放大", "在这些分区内不放大"):
        assert _problems(ONE, _said("p1", claim=claim), _observed(OPEN_ID)) == [], claim


def test_a_sentence_claiming_proof_is_no_observation() -> None:
    for sentence in (
        f"观测（查询 probe_1，{PARTITION}，2026-11-20 执行）：{USER} 按 open_id 唯一，已证明 p1 不放大",
        _said("p1", claim="在该分区内保证不放大"),
        _said("p1", claim="在该分区内一定不放大"),
        _said("p1", claim="在该分区内必然不放大"),
    ):
        (warning,) = _problems(ONE, sentence, _observed(OPEN_ID))
        assert WARNING in warning["message"], sentence
    # saying what the observation does not guarantee is no claim of proof
    hedged = _said("p1", claim="在该分区内不放大，不保证别的分区")
    assert _problems(ONE, hedged, _observed(OPEN_ID)) == []


def test_a_sentence_without_the_partition_still_warns() -> None:
    sentence = _said("p1").replace(f"{PARTITION}，", "")
    (warning,) = _problems(ONE, sentence, _observed(OPEN_ID))
    assert WARNING in warning["message"]
    other_day = _said("p1", "分区 dt=20261118")
    (warning,) = _problems(ONE, other_day, _observed(OPEN_ID))
    assert WARNING in warning["message"]


def test_a_sentence_not_saying_observed_still_warns() -> None:
    (warning,) = _problems(ONE, f"{USER} 在 {PARTITION} 内按 open_id 无重复，p1 不放大",
                           _observed(OPEN_ID))
    assert WARNING in warning["message"]


def test_the_observation_form_without_an_observation_in_the_files_warns() -> None:
    for confirmed in (TableConfirmed(), _observed(_of(OTHER, "open_id"))):
        warnings = _problems(ONE, _said("p1"), confirmed)
        (unbacked,) = [w for w in warnings if UNBACKED in w["message"]]
        assert unbacked["status"] == "warn" and unbacked["at"] == "summary.watch[0]"
        assert f"input:{USER}" in unbacked["message"] and "p1" in unbacked["message"]


def test_without_a_confirmations_path_the_check_is_as_before() -> None:
    for sentence in (_said("p1"), "p1 不放大。", "p1 未证明唯一，会放大行数。"):
        document = {"summary": {"row": {"note": "每个 id 一行。"},
                                "watch": [{"kind": "risk", "text": sentence}]}}
        before = check_fan_out(document, ONE)
        assert check_fan_out(document, ONE, None) == before
        unrelated = _observed(_of(OTHER, "open_id"))
        if "观测（" not in sentence:
            assert check_fan_out(document, ONE, unrelated) == before
            assert check_fan_out(document, ONE, TableConfirmed()) == before


# ------------------------------------------------------------------ through validation


def test_validation_hands_the_confirmations_to_check_10(tmp_path: Path) -> None:
    packets = demo_packets(tmp_path / "packets")
    borrower = packet_of(packets, "demo_dwd.dwd_lending_borrower_df")
    document = example(packets)
    document["summary"]["row"]["note"] = "每个客户可能有多笔贷款（dwd_lending_loan_df），关联后行数放大。"
    document["summary"]["watch"].append({"kind": "risk", "text": (
        "观测（查询 probe_1，分区 dt=20261119，2026-11-20 执行）：ods_credit_limit_df 按 (cust_no) "
        "无重复，p4 在该分区内不放大；别的分区未观测，若出现重复会放大行数。")})

    def warnings(confirmations) -> list[dict]:
        report = validate_document(document, borrower, confirmations=confirmations)
        return [item for item in report["failures"]
                if item["check"] == "fan_out" and item["status"] == "warn"]

    entry = _entry("input:demo_ods.ods_credit_limit_df", _input(columns=("cust_no",)))
    assert warnings(read_confirmations(_file(tmp_path / "c.json", entry))) == []
    assert [WARNING in w["message"] for w in warnings(None)] == [True]
