"""Observed facts: what a platform query found, kept apart from what a table means.

Three confirmation targets carry an observation -- the query, the date it ran, the
partitions it read and how many rows they held -- and ``semantic confirm`` replays each
into a slot of its own:

- ``summary.row.observed`` -> ``summary.row.observed``; an ``inferred`` (or earlier
  ``observed``) grain becomes ``observed``, a ``declared`` or ``proven`` one only gains the
  observation;
- ``column:<c>.observed_values`` -> the column's ``observed_values``, beside its code
  values and never one of them; an identifier column gets counts only;
- ``input:<db.table>`` -> one item of ``observed_inputs``, per input table and set of
  columns.

An observation over no rows says nothing, so ``rows`` is at least 1. The old
``summary.row`` target cannot write an observation in by the side door. Without any
observation every output is what it always was.

Every fixture is the example document with one thing changed.
"""

from __future__ import annotations

import contextlib
import copy
import io
from pathlib import Path

import pytest

from scope_lineage.semantics import DOC_FORMAT, apply_confirmations, schema_errors, validate_document
from scope_lineage.semantics.confirmed import read_confirmations, render_facts
from scope_lineage.semantics.page import render_semantic_pages

from .table_semantics_demo import (
    CONFIRMATIONS,
    DEMO_TABLE,
    demo_packets,
    example,
    packet_of,
    read_json,
    run,
    write_json,
)

INPUT = "demo_ods.ods_core_customer_df"
OTHER_TABLE = "demo_dwd.dwd_party_customer_other_df"
EVIDENCE = {"query": "probe_1", "on": "2026-11-20", "rows": 120,
            "partition": {"column": "dt", "values": ["20261119"]}}


def _grain(**extra) -> dict:
    return {**EVIDENCE, "grain_columns": ["customer_id"], "unique": "yes",
            "within": "each_partition", "keys": 120, "duplicate_keys": 0, **extra}


def _values(**extra) -> dict:
    return {**EVIDENCE, "values": [{"value": "F", "count": 60}, {"value": "M", "count": 50},
                                   {"value": "X", "count": 10}],
            "complete": True, "absent": ["U"], "distinct": 3, "nulls": 0,
            "observed_on": f"{INPUT}.gender", **extra}


def _input(columns=("cust_no",), **extra) -> dict:
    return {**EVIDENCE, "columns": list(columns), "unique": "yes", "within": "each_partition",
            "keys": 120, "duplicate_keys": 0, **extra}


def _entry(target: str, value, table: str = DEMO_TABLE, **extra) -> dict:
    return {"table": table, "target": target, "value": value, "by": "demo-reviewer",
            "date": "2026-11-21", **extra}


def _file(path: Path, *entries: dict) -> Path:
    return write_json(path, {"doc_format": "semantic-confirmations/1",
                             "confirmations": list(entries)})


def _with_row(**row) -> dict:
    document = example()
    document["summary"]["row"].update(row)
    return document


def _apply(document: dict, *entries: dict):
    result = apply_confirmations({DEMO_TABLE: document}, list(entries))
    return result.documents[DEMO_TABLE], result


def _column(document: dict, name: str) -> dict:
    return next(column for column in document["columns"] if column["column"] == name)


# ------------------------------------------------------------------- reading


def test_the_three_targets_are_read_and_build_the_state(tmp_path: Path) -> None:
    confirmations = read_confirmations(_file(
        tmp_path / "c.json",
        _entry("summary.row.observed", _grain()),
        _entry("column:gender_cd.observed_values", _values()),
        _entry(f"input:spark_catalog.{INPUT.upper()}", _input()),
    ))
    state = confirmations.for_table(DEMO_TABLE)
    assert state.observed_row.value == _grain()
    assert state.observed_values["gender_cd"].value == _values()
    ((key, fact),) = state.observed_inputs.items()
    assert key == (INPUT, ("cust_no",))
    assert fact.value == {"table": INPUT, **_input()}
    assert (fact.by, fact.date) == ("demo-reviewer", "2026-11-21")
    assert state  # a table with observations only has entries


@pytest.mark.parametrize("target", ["input:x", "input:a.b.c.d", "column:c.observed",
                                    "summary.row.observed.x", "summary.row.seen"])
def test_the_schema_refuses_other_spellings(target: str) -> None:
    document = {"doc_format": "semantic-confirmations/1",
                "confirmations": [_entry(target, {})]}
    assert schema_errors(document, "semantic-confirmations/1")


def test_the_old_row_target_cannot_carry_an_observation_into_the_state(tmp_path: Path) -> None:
    state = read_confirmations(_file(
        tmp_path / "c.json",
        _entry("summary.row", {"grain_source": "observed", "unique": "yes"}),
        _entry("summary.row", {"observed": _grain()}),
        _entry("summary.row", {"note": "业务方确认"}),
    )).for_table(DEMO_TABLE)
    assert state.row_fields() == {"note": "业务方确认"}
    assert state.observed_row is None


@pytest.mark.parametrize("target, value", [
    ("summary.row.observed", _grain(rows=0)),
    ("column:gender_cd.observed_values", _values(rows=0)),
    (f"input:{INPUT}", _input(rows=0)),
    ("summary.row.observed", _grain(duplicate_keys=3)),
    ("column:gender_cd.observed_values", _values(values=[{"value": str(n), "count": 1}
                                                         for n in range(51)])),
    ("column:gender_cd.observed_values", {**_values(), "rows_seen": [{"a": 1}]}),
    (f"input:{INPUT}", {**_input(), "table": INPUT}),
])
def test_an_observation_confirm_refuses_whatever_the_document_adds_nothing(
    tmp_path: Path, target: str, value: dict
) -> None:
    confirmations = read_confirmations(_file(tmp_path / "c.json", _entry(target, value)))
    assert confirmations.for_table(DEMO_TABLE) is None


# ------------------------------------------------------------------- the row


def test_an_observation_replaces_an_inferred_grain() -> None:
    document, result = _apply(_with_row(grain_source="inferred", unique="unknown"),
                              _entry("summary.row.observed", _grain()))
    row = document["summary"]["row"]
    assert (row["grain_source"], row["unique"], row["grain_columns"]) == (
        "observed", "yes", ["customer_id"])
    assert row["observed"] == _grain()
    assert "confirmed" not in row["sources"]
    assert document["confirmed"] == [{"target": "summary.row.observed", "by": "demo-reviewer",
                                      "date": "2026-11-21"}]
    assert result.unmatched == [] and schema_errors(document, DOC_FORMAT) == []


def test_unique_on_fewer_columns_keeps_the_documents_wider_grain() -> None:
    document, _ = _apply(_with_row(grain_source="inferred", grain_columns=["customer_id", "dt"]),
                         _entry("summary.row.observed", _grain()))
    assert document["summary"]["row"]["grain_columns"] == ["customer_id", "dt"]


@pytest.mark.parametrize("grain, observed, written", [
    (["customer_id"], _grain(grain_columns=["verified_customer_no"]), ["verified_customer_no"]),
    (["customer_id", "dt"], _grain(unique="no", duplicate_keys=2), ["customer_id"]),
    ([], _grain(), ["customer_id"]),
])
def test_otherwise_the_grain_is_the_columns_the_query_counted(grain, observed, written) -> None:
    document, _ = _apply(_with_row(grain_source="inferred", grain_columns=grain),
                         _entry("summary.row.observed", observed))
    row = document["summary"]["row"]
    assert (row["grain_columns"], row["unique"]) == (written, observed["unique"])


@pytest.mark.parametrize("source", ["declared", "proven"])
def test_a_declared_or_proven_grain_only_gains_the_observation(source: str) -> None:
    before = _with_row(grain_source=source)
    document, _ = _apply(copy.deepcopy(before),
                         _entry("summary.row.observed", _grain(unique="no", duplicate_keys=1)))
    row, old = document["summary"]["row"], before["summary"]["row"]
    assert row.pop("observed")["unique"] == "no"
    assert row == old


def test_the_owner_s_word_on_the_row_turns_observed_into_declared() -> None:
    document, _ = _apply(_with_row(grain_source="inferred"),
                         _entry("summary.row.observed", _grain()),
                         _entry("summary.row", {"unique": "yes"}))
    row = document["summary"]["row"]
    assert row["grain_source"] == "declared" and row["observed"] == _grain()
    # and once declared, a later observation leaves the source alone
    again, _ = _apply(document, _entry("summary.row.observed", _grain(query="probe_2")))
    assert again["summary"]["row"]["grain_source"] == "declared"


@pytest.mark.parametrize("value", [{"grain_source": "observed"}, {"observed": _grain()},
                                   {"unique": "yes", "grain_source": "observed"}])
def test_the_old_row_target_refuses_an_observation(value: dict) -> None:
    document, result = _apply(_with_row(grain_source="inferred"), _entry("summary.row", value))
    assert document == _with_row(grain_source="inferred")
    (unmatched,) = result.unmatched
    assert "summary.row.observed" in unmatched["reason"]


# ------------------------------------------------------------------- the columns


def test_observed_values_sit_beside_the_code_values() -> None:
    document, result = _apply(example(), _entry("column:gender_cd.observed_values", _values()))
    column = _column(document, "gender_cd")
    assert column["observed_values"] == _values()
    assert column["code_values"] == _column(example(), "gender_cd")["code_values"]
    assert result.unmatched == [] and schema_errors(document, DOC_FORMAT) == []


def test_an_identifier_column_takes_counts_only() -> None:
    counts = {**EVIDENCE, "complete": False, "distinct": 120, "nulls": 0}
    document, result = _apply(example(), _entry("column:customer_id.observed_values", counts))
    assert _column(document, "customer_id")["observed_values"] == counts
    for value in ({**counts, "values": [{"value": "c001", "count": 1}]},
                  {**counts, "absent": ["c001"]}):
        document, result = _apply(example(), _entry("column:customer_id.observed_values", value))
        assert document == example()
        assert "identifier" in result.unmatched[0]["reason"]


@pytest.mark.parametrize("value, word", [
    (_values(observed_on=f"{INPUT}.verify_flag"), "source column"),
    (_values(observed_on="demo_ods.other_df.gender"), "source column"),
    (_values(rows=0), "rows"),
    (_values(values=[{"value": "13800138000", "count": 1}]), "contact"),
])
def test_an_observation_the_column_cannot_take_is_unmatched(value: dict, word: str) -> None:
    document, result = _apply(example(), _entry("column:gender_cd.observed_values", value))
    assert document == example()
    assert word in result.unmatched[0]["reason"]


def test_observed_on_matches_a_source_column_whatever_the_catalog() -> None:
    value = _values(observed_on=f"spark_catalog.{INPUT}.GENDER")
    document, result = _apply(example(), _entry("column:gender_cd.observed_values", value))
    assert result.unmatched == []


# ------------------------------------------------------------------- the inputs


def test_an_input_observation_lands_under_its_bare_table_and_later_wins() -> None:
    document, _ = _apply(
        example(),
        _entry(f"input:spark_catalog.{INPUT}", _input()),
        _entry(f"input:{INPUT.upper()}", _input(columns=("CUST_NO",), query="probe_2")),
    )
    (item,) = document["observed_inputs"]
    assert item == {"table": INPUT, **_input(columns=("CUST_NO",), query="probe_2")}
    assert schema_errors(document, DOC_FORMAT) == []


def test_two_column_sets_on_one_input_are_two_items_and_two_log_lines() -> None:
    document, _ = _apply(example(),
                         _entry(f"input:{INPUT}", _input(columns=("cust_no",))),
                         _entry(f"input:{INPUT}", _input(columns=("verified_no", "cust_no"))))
    assert [item["columns"] for item in document["observed_inputs"]] == [
        ["cust_no"], ["verified_no", "cust_no"]]
    assert document["confirmed"] == [
        {"target": f"input:{INPUT}", "by": "demo-reviewer", "date": "2026-11-21",
         "columns": ["cust_no"]},
        {"target": f"input:{INPUT}", "by": "demo-reviewer", "date": "2026-11-21",
         "columns": ["cust_no", "verified_no"]},
    ]
    assert schema_errors(document, DOC_FORMAT) == []


def test_an_input_observation_over_no_rows_is_unmatched() -> None:
    document, result = _apply(example(), _entry(f"input:{INPUT}", _input(rows=0)))
    assert document == example()
    assert "rows" in result.unmatched[0]["reason"]


# ------------------------------------------------------------------- guards


ALL = (
    _entry("summary.row.observed", _grain()),
    _entry("column:gender_cd.observed_values", _values()),
    _entry(f"input:{INPUT}", _input()),
    _entry(f"input:{INPUT}", _input(columns=("verified_no",))),
)


def test_replaying_observations_twice_changes_nothing_the_second_time() -> None:
    once, _ = _apply(_with_row(grain_source="inferred"), *ALL)
    result = apply_confirmations({DEMO_TABLE: copy.deepcopy(once)}, list(ALL))
    assert result.changed == set()
    assert result.documents[DEMO_TABLE] == once


def test_only_keeps_that_table_s_observations(tmp_path: Path, capsys) -> None:
    directory = tmp_path / "semantics"
    write_json(directory / f"{DEMO_TABLE}.json", example())
    other = example()
    other["table"] = OTHER_TABLE
    write_json(directory / f"{OTHER_TABLE}.json", other)
    file = _file(tmp_path / "c.json", *ALL, _entry(f"input:{INPUT}", _input(), table=OTHER_TABLE))
    assert run("semantic", "confirm", directory, "--confirmations", file, "--only", DEMO_TABLE) == 0
    assert "unmatched=0" in capsys.readouterr().out
    assert len(read_json(directory / f"{DEMO_TABLE}.json")["observed_inputs"]) == 2
    assert read_json(directory / f"{OTHER_TABLE}.json") == other


def test_a_document_with_observations_renders_and_validates(tmp_path: Path) -> None:
    document, _ = _apply(_with_row(grain_source="inferred"), *ALL)
    page = render_semantic_pages([document])[f"{DEMO_TABLE}.md"]
    (line,) = [line for line in page.splitlines() if line.startswith("**一行是什么**")]
    assert "观测" in line and "全表唯一" not in line
    packets = demo_packets(tmp_path)
    document["packet_digest"] = packet_of(packets)["packet_digest"]
    confirmations = read_confirmations(_file(tmp_path / "c.json", *ALL))
    report = validate_document(document, packet_of(packets), confirmations=confirmations)
    assert report["table"] == DEMO_TABLE


def test_facts_do_not_break_on_observations(tmp_path: Path) -> None:
    plain = read_confirmations(CONFIRMATIONS)
    entries = read_json(CONFIRMATIONS)["confirmations"]
    mixed = read_confirmations(_file(tmp_path / "c.json", *entries, *ALL))
    assert render_facts(mixed, [DEMO_TABLE]) == render_facts(plain, [DEMO_TABLE])
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert run("semantic", "facts", "--confirmations", tmp_path / "c.json",
                   "--table", DEMO_TABLE) == 0
