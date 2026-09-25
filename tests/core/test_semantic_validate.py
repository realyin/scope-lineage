"""``semantic validate``: a table-semantics document held against its packet.

The example document is clean against the demo packet; each failing fixture is that
example (or its packet) with exactly one thing changed, and the test names the one
cross check that must catch it.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scope_lineage.semantics import CHECKS, validate_document

from .table_semantics_demo import (
    DEMO_TABLE,
    demo_packets,
    example,
    packet_of,
    run,
    write_json,
)


@pytest.fixture(scope="module")
def packets(tmp_path_factory) -> Path:
    return demo_packets(tmp_path_factory.mktemp("demo"))


@pytest.fixture(scope="module")
def packet(packets: Path) -> dict:
    return packet_of(packets)


@pytest.fixture
def document(packets: Path) -> dict:
    return example(packets)


def _problems(report: dict, check: str, status: str = "fail") -> list[dict]:
    return [f for f in report["failures"] if f["check"] == check and f["status"] == status]


def _column(document: dict, name: str) -> dict:
    return next(column for column in document["columns"] if column["column"] == name)


def test_the_example_passes_every_check(document: dict, packet: dict) -> None:
    report = validate_document(document, packet)
    assert report["failures"] == []
    assert report["pass_rate"] == 1.0
    assert set(report["checks"]) == set(CHECKS)
    assert all(counts["pass"] for counts in report["checks"].values())


# 1 ------------------------------------------------------------------- coverage


def test_a_missing_column_fails_coverage(document: dict, packet: dict) -> None:
    del document["columns"][1]
    (problem,) = _problems(validate_document(document, packet), "coverage")
    assert "verified_customer_no" in problem["message"]


def test_columns_out_of_table_order_fail_coverage(document: dict, packet: dict) -> None:
    columns = document["columns"]
    columns[0], columns[1] = columns[1], columns[0]
    problems = _problems(validate_document(document, packet), "coverage")
    assert {p["at"] for p in problems} == {"columns[0]", "columns[1]"}


def test_an_extra_column_fails_coverage(document: dict, packet: dict) -> None:
    document["columns"].append({**copy.deepcopy(document["columns"][0]), "column": "ghost"})
    (problem,) = _problems(validate_document(document, packet), "coverage")
    assert "ghost" in problem["message"]


# 2 ------------------------------------------------------------------- source columns


def test_a_source_column_outside_the_lineage_fails(document: dict, packet: dict) -> None:
    _column(document, "customer_id")["source_columns"] = ["demo_ods.ods_other_df.cust_no"]
    (problem,) = _problems(validate_document(document, packet), "source_columns")
    assert problem["at"] == "columns[0].source_columns[0]"


def test_a_source_column_only_in_input_metadata_warns(document: dict, packet: dict) -> None:
    _column(document, "customer_id")["source_columns"].append(
        "demo_ods.ods_core_customer_df.update_ts"
    )
    report = validate_document(document, packet)
    assert _problems(report, "source_columns") == []
    (warning,) = _problems(report, "source_columns", "warn")
    assert "update_ts" in warning["message"]


# 3 ------------------------------------------------------------------- code values


def test_a_code_value_neither_comment_nor_sql_mentions_fails(document: dict, packet: dict) -> None:
    _column(document, "gender_cd")["code_values"].append(
        {"value": "X", "meaning": "其他", "sources": ["inferred"]}
    )
    (problem,) = _problems(validate_document(document, packet), "code_values")
    assert "X" in problem["message"]


def test_an_unconfirmed_code_value_is_not_held_to_the_text(document: dict, packet: dict) -> None:
    _column(document, "gender_cd")["code_values"].append(
        {"value": "X", "meaning": "其他", "sources": ["inferred"], "unconfirmed": True}
    )
    assert _problems(validate_document(document, packet), "code_values") == []


# 4 ------------------------------------------------------------------- grain


def test_a_grain_column_the_table_does_not_have_fails(document: dict, packet: dict) -> None:
    document["summary"]["row"]["grain_columns"] = ["customer_no"]
    (problem,) = _problems(validate_document(document, packet), "grain")
    assert "customer_no" in problem["message"]


def test_a_proven_grain_without_a_proven_key_fails(document: dict, packet: dict) -> None:
    unproven = copy.deepcopy(packet)
    for key in unproven["lineage"]["keys"]:
        key.update(key_confidence="candidate", proven=False)
    (problem,) = _problems(validate_document(document, unproven), "grain")
    assert problem["at"] == "summary.row.grain_source"


def test_a_proven_grain_on_other_columns_than_the_proof_warns(document: dict, packet: dict) -> None:
    document["summary"]["row"]["grain_columns"] = ["customer_id", "gender_cd"]
    report = validate_document(document, packet)
    assert _problems(report, "grain") == []
    assert _problems(report, "grain", "warn")


# 5 ------------------------------------------------------------------- rules


def test_a_non_partition_filter_no_rule_cites_fails(document: dict, packet: dict) -> None:
    document["rules"] = [rule for rule in document["rules"] if rule["id"] != "r3"]
    for scope in document["summary"]["scope"]:
        scope["rule_refs"] = [ref for ref in scope.get("rule_refs", []) if ref != "r3"]
    (problem,) = _problems(validate_document(document, packet), "rules")
    assert "rn = 1" in problem["message"]


def test_rule_sql_that_is_not_in_the_task_sql_fails(document: dict, packet: dict) -> None:
    document["rules"][0]["sql"] = "WHERE dt >= '${bizdate}'"
    problems = _problems(validate_document(document, packet), "rules")
    assert [p["at"] for p in problems] == ["rules[0].sql"]


def test_a_scope_citing_an_unknown_rule_fails(document: dict, packet: dict) -> None:
    document["summary"]["scope"][0]["rule_refs"] = ["r9"]
    (problem,) = _problems(validate_document(document, packet), "rules")
    assert problem["at"] == "summary.scope[0].rule_refs[0]"


# 6 ------------------------------------------------------------------- neighbours


def test_an_upstream_table_the_lineage_never_reads_fails(document: dict, packet: dict) -> None:
    document["summary"]["upstream"][0]["table"] = "demo_ods.ods_app_account_df"
    (problem,) = _problems(validate_document(document, packet), "neighbours")
    assert problem["at"] == "summary.upstream[0].table"


def test_a_downstream_task_nobody_declared_fails(document: dict, packet: dict) -> None:
    document["summary"]["downstream"].append({"task": "ads_unknown_daily"})
    (problem,) = _problems(validate_document(document, packet), "neighbours")
    assert "ads_unknown_daily" in problem["message"]


def test_a_downstream_table_that_task_does_not_write_fails(document: dict, packet: dict) -> None:
    document["summary"]["downstream"][0]["table"] = "demo_dws.dws_lending_loan_summary_1d"
    (problem,) = _problems(validate_document(document, packet), "neighbours")
    assert problem["at"] == "summary.downstream[0].table"


# 7 ------------------------------------------------------------------- sources


def test_an_item_with_no_source_fails(document: dict, packet: dict) -> None:
    document["columns"][2]["sources"] = []
    document["rules"][1]["sources"] = []
    problems = _problems(validate_document(document, packet), "sources")
    assert [p["at"] for p in problems] == ["columns[2].sources", "rules[1].sources"]


def test_more_than_five_questions_fail(document: dict, packet: dict) -> None:
    document["summary"]["questions"] = [
        {"id": f"q{index}", "text": "?", "status": "open"} for index in range(1, 7)
    ]
    (problem,) = _problems(validate_document(document, packet), "sources")
    assert problem["at"] == "summary.questions"


# 8 ------------------------------------------------------------------- digest


def test_a_document_written_against_another_packet_is_stale(document: dict, packet: dict) -> None:
    document["packet_digest"] = "0000000000000000"
    (problem,) = _problems(validate_document(document, packet), "digest")
    assert "stale" in problem["message"]


# 9 ------------------------------------------------------------------- time


def test_incremental_over_full_snapshots_with_no_date_filter_fails(
    document: dict, packet: dict
) -> None:
    document["summary"]["refresh"]["time"] = "incremental"
    (problem,) = _problems(validate_document(document, packet), "time")
    assert problem["at"] == "summary.refresh.time"
    assert "demo_ods.ods_core_customer_df" in problem["message"]


def test_incremental_is_accepted_when_an_input_is_read_incrementally(
    document: dict, packets: Path
) -> None:
    loan = packet_of(packets, "demo_dwd.dwd_lending_loan_df")
    document["summary"]["refresh"]["time"] = "incremental"
    report = validate_document(document, loan)
    assert _problems(report, "time") == []


def test_snapshot_over_a_business_date_window_warns(document: dict, packet: dict) -> None:
    dated = copy.deepcopy(packet)
    dated["inputs"][0]["date_filters"] = [
        {"column": "register_ts", "expression": "register_ts >= '${bizdate}'"}
    ]
    report = validate_document(document, dated)
    assert _problems(report, "time") == []
    (warning,) = _problems(report, "time", "warn")
    assert "register_ts" in warning["message"]


# ------------------------------------------------------------------- the command


def _write_example(tmp_path: Path, document: dict) -> Path:
    directory = tmp_path / "semantics"
    write_json(directory / f"{DEMO_TABLE}.json", document)
    return directory


def test_the_command_passes_the_example_and_prints_a_summary(
    tmp_path: Path, packets: Path, document: dict, capsys
) -> None:
    directory = _write_example(tmp_path, document)
    assert run("semantic", "validate", directory, "--packets", packets) == 0
    out = capsys.readouterr().out
    assert f"{DEMO_TABLE}: " in out
    assert "100.0%" in out


def test_content_failures_are_reported_but_do_not_fail_the_command(
    tmp_path: Path, packets: Path, document: dict, capsys
) -> None:
    del document["columns"][1]
    directory = _write_example(tmp_path, document)
    assert run("semantic", "validate", directory, "--packets", packets, "--json") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["doc_format"] == "table-semantics-validation/1"
    (table,) = report["tables"]
    assert table["table"] == DEMO_TABLE
    assert table["schema_errors"] == []
    assert 0 < table["pass_rate"] < 1
    assert [f["check"] for f in table["failures"]] == ["coverage"]
    assert report["summary"]["tables_with_failures"] == 1


def test_a_schema_error_fails_the_command(
    tmp_path: Path, packets: Path, document: dict, capsys
) -> None:
    document["columns"][0]["category"] = "key"
    directory = _write_example(tmp_path, document)
    write_json(directory / "demo_dwd.other.json", {"doc_format": "something-else/1"})
    assert run("semantic", "validate", directory, "--packets", packets, "--json") == 1
    report = json.loads(capsys.readouterr().out)
    errors = {table["file"]: table["schema_errors"] for table in report["tables"]}
    assert [e["at"] for e in errors[f"{DEMO_TABLE}.json"]] == ["columns[0].category"]
    assert errors["demo_dwd.other.json"]


def test_confirmations_beside_the_documents_are_skipped_and_bad_json_is_reported(
    tmp_path: Path, packets: Path, document: dict, capsys
) -> None:
    from .table_semantics_demo import CONFIRMATIONS

    directory = _write_example(tmp_path, document)
    (directory / "confirmations.json").write_bytes(CONFIRMATIONS.read_bytes())
    (directory / "half.json").write_text("{", encoding="utf-8")
    assert run("semantic", "validate", directory, "--packets", packets, "--json") == 1
    tables = json.loads(capsys.readouterr().out)["tables"]
    assert [table["file"] for table in tables] == [f"{DEMO_TABLE}.json", "half.json"]
    assert "not a readable JSON document" in tables[1]["schema_errors"][0]["message"]


def test_a_document_without_a_packet_is_reported(
    tmp_path: Path, packets: Path, document: dict, capsys
) -> None:
    document["table"] = "demo_dwd.dwd_no_such_table"
    directory = _write_example(tmp_path, document)
    assert run("semantic", "validate", directory, "--packets", packets, "--json") == 0
    (table,) = json.loads(capsys.readouterr().out)["tables"]
    assert [f["check"] for f in table["failures"]] == ["digest"]
    assert "no packet" in table["failures"][0]["message"]


def test_missing_inputs_are_usage_errors(tmp_path: Path, packets: Path) -> None:
    assert run("semantic", "validate", tmp_path / "nope", "--packets", packets) == 2
    empty = tmp_path / "empty"
    empty.mkdir()
    assert run("semantic", "validate", empty, "--packets", tmp_path / "nope") == 2


def test_the_text_report_lists_failures_as_a_rewrite_prompt(
    tmp_path: Path, packets: Path, document: dict, capsys
) -> None:
    document["summary"]["refresh"]["time"] = "incremental"
    directory = _write_example(tmp_path, document)
    run("semantic", "validate", directory, "--packets", packets)
    out = capsys.readouterr().out
    assert "[9 time] summary.refresh.time" in out
