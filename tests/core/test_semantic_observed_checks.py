"""Checks 3, 4 and 6 hold a document's observations to the run's confirmations files.

Validation takes observations from the confirmations files only: a document's
``observed*`` slots are what ``semantic confirm`` wrote there, and a document that carries
one the files do not is held to the files. Three states are kept apart -- no
confirmations path at all, a path with nothing for this table, entries for this table --
and without any observation every report is what it always was.

- Check 4: a ``declared`` grain the observation agrees with passes, one it contradicts
  warns (a comment's word is no writer's to change); an ``inferred`` grain with an
  observation fails (the replay writes ``observed``); a document claiming ``observed``
  fails when the files have no such observation and warns when there are no files; the
  ``observed`` slot is the confirmation's. ``proven`` is judged as before.
- Check 3: an observed value is never a code: written as one without ``unconfirmed`` it
  still fails. Observed values off the code list warn once per column; a value asked
  about and not seen that the document lists as a code warns. Only a column that passes
  its single source column through is compared with an observation of that source.
- Check 6: an observed input table must be one of the lineage's input tables.

Failures the writer cannot fix say 「拿回确认文件改」.

Every fixture is the example document, its observations replayed by ``semantic confirm``,
with one thing changed.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scope_lineage.semantics import apply_confirmations, validate_document
from scope_lineage.semantics.confirmed import read_confirmations

from .table_semantics_demo import CONFIRMATIONS, DEMO_TABLE, demo_packets, example, packet_of, read_json
from .test_semantic_observed import INPUT, OTHER_TABLE, _entry, _file, _grain, _input, _values

GIVE_BACK = "拿回确认文件改"


@pytest.fixture(scope="module")
def packets(tmp_path_factory) -> Path:
    return demo_packets(tmp_path_factory.mktemp("observed"))


@pytest.fixture(scope="module")
def packet(packets: Path) -> dict:
    return packet_of(packets)


@pytest.fixture
def document(packets: Path) -> dict:
    return example(packets)


def _column(document: dict, name: str) -> dict:
    return next(column for column in document["columns"] if column["column"] == name)


def _index(document: dict, name: str) -> int:
    return next(i for i, column in enumerate(document["columns"]) if column["column"] == name)


def _replayed(document: dict, *entries: dict) -> dict:
    result = apply_confirmations({DEMO_TABLE: document}, list(entries))
    assert result.unmatched == []
    return result.documents[DEMO_TABLE]


def _validate(tmp_path: Path, document: dict, packet: dict, *entries: dict, path: bool = True):
    confirmations = read_confirmations(_file(tmp_path / "c.json", *entries)) if path else None
    return validate_document(document, packet, confirmations=confirmations)


def _found(report: dict, check: str, status: str) -> list[dict]:
    return [item for item in report["failures"]
            if item["check"] == check and item["status"] == status]


def _row(document: dict, **row) -> dict:
    document["summary"]["row"].update(row)
    return document


ROW = _entry("summary.row.observed", _grain())
ELSEWHERE = _entry("column:x.meaning", "别的表的列", table=OTHER_TABLE)


# ------------------------------------------------------------------- check 4


def test_a_declared_grain_the_observation_agrees_with_passes(tmp_path, document, packet) -> None:
    document = _replayed(_row(document, grain_source="declared"), ROW)
    report = _validate(tmp_path, document, packet, ROW)
    assert _found(report, "grain", "fail") == [] and _found(report, "grain", "warn") == []


def test_a_declared_grain_the_observation_contradicts_warns(tmp_path, document, packet) -> None:
    entry = _entry("summary.row.observed", _grain(unique="no", duplicate_keys=4))
    document = _replayed(_row(document, grain_source="declared"), entry)
    report = _validate(tmp_path, document, packet, entry)
    assert _found(report, "grain", "fail") == []
    (warn,) = _found(report, "grain", "warn")
    assert warn["at"] == "summary.row.grain_source" and "声明与观测不一致" in warn["message"]


def test_an_inferred_grain_with_an_observation_fails(tmp_path, document, packet) -> None:
    document = _replayed(_row(document, grain_source="declared"), ROW)
    _row(document, grain_source="inferred")
    report = _validate(tmp_path, document, packet, ROW)
    (fail,) = _found(report, "grain", "fail")
    assert fail["at"] == "summary.row.grain_source" and "inferred" in fail["message"]
    assert "semantic confirm" in fail["message"]


def _claims_observed(document: dict) -> dict:
    """A document whose row says ``observed`` with the slot ROW would write."""
    return _replayed(_row(document, grain_source="inferred"), ROW)


@pytest.mark.parametrize("entries", [(ELSEWHERE,), (_entry("column:gender_cd.meaning", "性别"),)],
                         ids=["no-entry-for-the-table", "entries-but-no-observation"])
def test_observed_without_the_observation_in_the_files_fails(
    tmp_path, document, packet, entries
) -> None:
    report = _validate(tmp_path, _claims_observed(document), packet, *entries)
    (fail,) = _found(report, "grain", "fail")
    assert fail["at"] == "summary.row.grain_source"
    assert "summary.row.observed" in fail["message"] and GIVE_BACK in fail["message"]


def test_observed_without_any_confirmations_path_warns(tmp_path, document, packet) -> None:
    report = _validate(tmp_path, _claims_observed(document), packet, path=False)
    assert _found(report, "grain", "fail") == []
    (warn,) = [item for item in _found(report, "grain", "warn") if "无法核对观测来源" in item["message"]]
    assert warn["at"] == "summary.row.grain_source"


def test_the_observed_slot_is_the_confirmation_s(tmp_path, document, packet) -> None:
    document = _claims_observed(document)
    document["summary"]["row"]["observed"]["query"] = "probe_9"
    report = _validate(tmp_path, document, packet, ROW)
    (fail,) = _found(report, "grain", "fail")
    assert fail["at"] == "summary.row.observed" and GIVE_BACK in fail["message"]


@pytest.mark.parametrize("change, at", [
    ({"unique": "no"}, "summary.row.unique"),
    ({"grain_columns": ["verified_customer_no"]}, "summary.row.grain_columns"),
])
def test_an_observed_grain_says_what_was_observed(tmp_path, document, packet, change, at) -> None:
    document = _row(_claims_observed(document), **change)
    report = _validate(tmp_path, document, packet, ROW)
    assert [item["at"] for item in _found(report, "grain", "fail")] == [at]


def test_an_observed_grain_without_the_slot_fails(tmp_path, document, packet) -> None:
    document = _claims_observed(document)
    del document["summary"]["row"]["observed"]
    report = _validate(tmp_path, document, packet, path=False)
    (fail,) = _found(report, "grain", "fail")
    assert "row.observed" in fail["message"]


def test_an_observed_grain_whose_prose_does_not_say_so_warns(tmp_path, document, packet) -> None:
    document = _claims_observed(document)
    assert [item["at"] for item in _found(_validate(tmp_path, document, packet, ROW),
                                          "grain", "warn")] == ["summary.row.text"]
    _row(document, note="观测：在分区 dt=20261119 内（查询 probe_1，2026-11-20 执行）按 "
                        "(customer_id) 无重复。")
    assert _found(_validate(tmp_path, document, packet, ROW), "grain", "warn") == []


def test_a_proven_grain_is_judged_as_before(tmp_path, document, packet) -> None:
    entry = _entry("summary.row.observed", _grain(unique="no", duplicate_keys=1))
    replayed = _replayed(copy.deepcopy(document), entry)
    assert replayed["summary"]["row"]["grain_source"] == "proven"
    report = _validate(tmp_path, replayed, packet, entry)
    assert _found(report, "grain", "fail") == [] and _found(report, "grain", "warn") == []
    no_key = copy.deepcopy(packet)
    for key in no_key["lineage"]["keys"]:
        key["proven"] = False
    (fail,) = _found(_validate(tmp_path, replayed, no_key, entry), "grain", "fail")
    assert "proven" in fail["message"]


# ------------------------------------------------------------------- check 3


def _values_entry(column: str = "gender_cd", **extra) -> dict:
    return _entry(f"column:{column}.observed_values", _values(**extra))


def test_a_value_only_seen_in_the_data_written_as_a_code_still_fails(
    tmp_path, document, packet
) -> None:
    entry = _values_entry()
    document = _replayed(document, entry)
    _column(document, "gender_cd")["code_values"].append(
        {"value": "X", "meaning": "其他", "sources": ["inferred"]})
    report = _validate(tmp_path, document, packet, entry)
    (fail,) = _found(report, "code_values", "fail")
    assert fail["at"] == f"columns[{_index(document, 'gender_cd')}].code_values[3]"
    assert "观测到它，但含义没有依据" in fail["message"]


def test_values_off_the_code_list_warn_once_per_column(tmp_path, document, packet) -> None:
    entry = _values_entry(values=[{"value": "F", "count": 60}, {"value": "X", "count": 10},
                                  {"value": "Y", "count": 2}], absent=[], distinct=3)
    document = _replayed(document, entry)
    report = _validate(tmp_path, document, packet, entry)
    (warn,) = _found(report, "code_values", "warn")
    assert warn["at"] == f"columns[{_index(document, 'gender_cd')}].code_values"
    assert "X（10 行）、Y（2 行）" in warn["message"] and "dt=20261119" in warn["message"]
    assert "unconfirmed" in warn["message"]
    assert _found(report, "code_values", "fail") == []
    # written as unconfirmed, the value is on the list and the warning goes
    _column(document, "gender_cd")["code_values"] += [
        {"value": value, "meaning": "含义未知（只在观测里出现）", "unconfirmed": True,
         "sources": ["inferred"]} for value in ("X", "Y")]
    assert _found(_validate(tmp_path, document, packet, entry), "code_values", "warn") == []


def test_observed_values_without_a_code_list_say_so_once(tmp_path, document, packet) -> None:
    value = _values(absent=[])
    del value["observed_on"]  # the column itself was read
    entry = _entry("column:etl_time.observed_values", value)
    document = _replayed(document, entry)
    (warn,) = _found(_validate(tmp_path, document, packet, entry), "code_values", "warn")
    assert "有观测取值、没有码值表" in warn["message"]


def test_a_derived_column_is_not_compared_with_its_source(tmp_path, document, packet) -> None:
    entry = _entry("column:register_time.observed_values",
                   _values(observed_on=f"{INPUT}.register_ts", absent=[]))
    document = _replayed(document, entry)
    assert _found(_validate(tmp_path, document, packet, entry), "code_values", "warn") == []


def test_a_case_column_is_not_compared_with_its_source(tmp_path, document, packet) -> None:
    entry = _values_entry(values=[{"value": "1", "count": 60}, {"value": "2", "count": 60}])
    document = _replayed(document, entry)
    recoded = copy.deepcopy(packet)
    for item in recoded["lineage"]["columns"]:
        if item["column"] == "gender_cd":
            item["producers"][0]["case_outputs"] = [
                {"value": code, "when": [f"gender = '{source}'"], "source_values": [source],
                 "catch_all": False} for code, source in (("F", "1"), ("M", "2"))]
    assert _found(_validate(tmp_path, document, recoded, entry), "code_values", "warn") == []
    # the same observation on a pass-through column is compared
    assert _found(_validate(tmp_path, document, packet, entry), "code_values", "warn")


def test_a_code_the_observation_did_not_see_warns(tmp_path, document, packet) -> None:
    entry = _values_entry()  # U asked about, not seen
    document = _replayed(document, entry)
    _column(document, "gender_cd")["code_values"].append(
        {"value": "X", "meaning": "其他", "unconfirmed": True, "sources": ["inferred"]})
    report = _validate(tmp_path, document, packet, entry)
    (warn,) = _found(report, "code_values", "warn")
    assert warn["at"] == f"columns[{_index(document, 'gender_cd')}].code_values[2]"
    assert "'U'" in warn["message"] and "probe_1" in warn["message"]


def test_values_on_an_identifier_column_fail(tmp_path, document, packet) -> None:
    value = _values(observed_on=f"{INPUT}.cust_no")
    entry = _entry("column:customer_id.observed_values", value)
    _column(document, "customer_id")["observed_values"] = value
    report = _validate(tmp_path, document, packet, entry)
    (fail,) = _found(report, "code_values", "fail")
    assert fail["at"] == f"columns[{_index(document, 'customer_id')}].observed_values"
    assert "标识" in fail["message"] and GIVE_BACK in fail["message"]


def test_the_observed_values_slot_is_the_confirmation_s(tmp_path, document, packet) -> None:
    entry = _values_entry()
    replayed = _replayed(copy.deepcopy(document), entry)
    at = f"columns[{_index(document, 'gender_cd')}].observed_values"
    _column(replayed, "gender_cd")["observed_values"]["rows"] = 999
    (fail,) = _found(_validate(tmp_path, replayed, packet, entry), "code_values", "fail")
    assert fail["at"] == at and GIVE_BACK in fail["message"]
    (fail,) = _found(_validate(tmp_path, replayed, packet, ELSEWHERE), "code_values", "fail")
    assert fail["at"] == at
    (warn,) = _found(_validate(tmp_path, replayed, packet, path=False), "code_values", "warn")
    assert warn["at"] == at and "无法核对观测来源" in warn["message"]
    # a confirmation the document has not been replayed with
    (fail,) = _found(_validate(tmp_path, document, packet, entry), "code_values", "fail")
    assert fail["at"] == at and "semantic confirm" in fail["message"]


# ------------------------------------------------------------------- check 6


def test_an_observed_input_must_be_an_input_of_the_table(tmp_path, document, packet) -> None:
    entry = _entry("input:demo_ods.ods_unrelated_df", _input())
    document = _replayed(document, entry)
    report = _validate(tmp_path, document, packet, entry)
    (fail,) = _found(report, "neighbours", "fail")
    assert fail["at"] == "observed_inputs[0].table" and GIVE_BACK in fail["message"]


def test_the_observed_inputs_are_the_confirmations(tmp_path, document, packet) -> None:
    entry = _entry(f"input:{INPUT}", _input())
    replayed = _replayed(copy.deepcopy(document), entry)
    assert _found(_validate(tmp_path, replayed, packet, entry), "neighbours", "fail") == []
    (fail,) = _found(_validate(tmp_path, replayed, packet, ELSEWHERE), "neighbours", "fail")
    assert fail["at"] == "observed_inputs[0]" and GIVE_BACK in fail["message"]
    (warn,) = _found(_validate(tmp_path, replayed, packet, path=False), "neighbours", "warn")
    assert "无法核对观测来源" in warn["message"]
    (fail,) = _found(_validate(tmp_path, document, packet, entry), "neighbours", "fail")
    assert fail["at"] == "observed_inputs"


# ------------------------------------------------------------------- guards


def test_without_observations_the_three_states_give_one_report(tmp_path, document, packet) -> None:
    none = validate_document(document, packet)
    elsewhere = _validate(tmp_path, document, packet, ELSEWHERE)
    assert elsewhere == none
    confirmed = validate_document(document, packet,
                                  confirmations=read_confirmations(CONFIRMATIONS))
    entries = read_json(CONFIRMATIONS)["confirmations"]
    assert _validate(tmp_path, document, packet, *entries, ELSEWHERE) == confirmed


def test_a_clean_replay_of_every_observation_adds_no_failure(tmp_path, document, packet) -> None:
    entries = (_entry("summary.row.observed", _grain()),
               _values_entry(values=[{"value": "F", "count": 60}, {"value": "M", "count": 60}],
                             absent=[], distinct=2),
               _entry(f"input:{INPUT}", _input()))
    document = _replayed(document, *entries)
    report = _validate(tmp_path, document, packet, *entries)
    assert report["counts"]["fail"] == 0 and report["counts"]["warn"] == 0
