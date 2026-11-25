"""A platform result pasted back for a ``question-probes/1`` item: a draft observation or a
refusal (``scope_lineage.semantics.probe_results``). Nothing here runs SQL.

Only the result JSON the person running the queries hands back is read (``sql_id, status,
run_on, bizdate, sql_executed, columns, rows, note``, cells as the platform prints them:
strings, ``null`` for SQL NULL). A draft comes only from the two fixed shapes, with the
result's columns exactly the query's own top-level output columns; every other result is
refused with the reason. The results below are synthesised over the demo tables.
"""

from __future__ import annotations

import copy
import json

import pytest

from scope_lineage.semantics import probe_results as pr
from scope_lineage.semantics.schema import schema_errors

from .table_semantics_demo import DEMO_TABLE

INPUT = "demo_ods.ods_core_customer_df"
SHA = "a" * 64
ROW_UNIQUE = (
    "SELECT SUM(n) AS rows, COUNT(*) AS keys, "
    "SUM(CASE WHEN n > 1 THEN 1 ELSE 0 END) AS duplicate_keys "
    f"FROM (SELECT customer_id, COUNT(*) AS n FROM {DEMO_TABLE} "
    "WHERE dt = '${bizdate}' GROUP BY customer_id) g"
)
INPUT_UNIQUE = (
    "SELECT a.rows, a.keys, b.duplicate_keys FROM "
    f"(SELECT COUNT(*) AS rows, COUNT(DISTINCT cust_no) AS keys FROM {INPUT} "
    "WHERE dt = '${bizdate}') a CROSS JOIN "
    "(SELECT COUNT(*) AS duplicate_keys FROM "
    f"(SELECT cust_no FROM {INPUT} WHERE dt = '${{bizdate}}' "
    "GROUP BY cust_no HAVING COUNT(*) > 1) d) b"
)
VALUE_SET = (
    f"SELECT gender_cd AS value, COUNT(*) AS cnt FROM {DEMO_TABLE} "
    "WHERE dt = '${bizdate}' GROUP BY gender_cd ORDER BY cnt DESC LIMIT 51"
)
BLANKS = (
    "SELECT COUNT(*) AS rows, COUNT(CASE WHEN register_time IS NULL THEN 1 END) AS blank_rows "
    f"FROM {DEMO_TABLE} WHERE dt = '${{bizdate}}'"
)


def _item(id_, shape, sql, lands, table=DEMO_TABLE, **extra):
    item = {"id": id_, "table": DEMO_TABLE, "question": "q1", "asked": "问？", "part": 1,
            "ask": "子问题", "class": "data", "shape": shape, "sql": sql,
            "partitions": [{"table": table, "column": "dt", "want": "${bizdate}",
                            "fallback": "latest_available"}],
            "engine": "spark", "lands": lands, "how_to_read": "读法"}
    item.update(extra)
    return item


ROW_ITEM = _item("cust_q1_p1", "uniqueness", ROW_UNIQUE, "summary.row.observed")
INPUT_ITEM = _item("cust_q1_p2", "uniqueness", INPUT_UNIQUE, f"input:{INPUT}", table=INPUT)
VALUES_ITEM = _item("cust_q2_p1", "value_set", VALUE_SET, "column:gender_cd.observed_values")
BLANK_ITEM = _item("cust_q3_p1", "conditional_count", BLANKS, None)


def _result(item, columns, rows, bizdate="20261122", **extra):
    result = {"sql_id": item["id"], "status": "ok", "run_on": "2026-11-25", "bizdate": bizdate,
              "sql_executed": item["sql"].replace("${bizdate}", "20261122"),
              "columns": columns, "rows": rows, "note": ""}
    result.update(extra)
    return result


def _row(rows="1000", keys="1000", dup="0", **extra):
    return _result(ROW_ITEM, ["rows", "keys", "duplicate_keys"], [[rows, keys, dup]], **extra)


def _values(rows, **extra):
    return _result(VALUES_ITEM, ["value", "cnt"], rows, **extra)


def draft(item, result):
    return pr.draft_observation(item, result, SHA, "审核人甲", "2026-11-26")


def refused(item, result) -> str:
    entry, reason = draft(item, result)
    assert entry is None, entry
    assert reason
    return reason


# ------------------------------------------------------------------ good results


def test_a_uniqueness_result_drafts_the_row_observation() -> None:
    entry, reason = draft(ROW_ITEM, _row())
    assert reason is None
    assert entry == {
        "table": DEMO_TABLE, "target": "summary.row.observed",
        "value": {"query": "cust_q1_p1", "on": "2026-11-25", "rows": 1000,
                  "partition": {"column": "dt", "values": ["20261122"]}, "engine": "spark",
                  "grain_columns": ["customer_id"], "unique": "yes", "within": "each_partition",
                  "keys": 1000, "duplicate_keys": 0},
        "by": "审核人甲", "date": "2026-11-26",
        "evidence": {"probe": "cust_q1_p1", "partition": {"column": "dt", "values": ["20261122"]},
                     "on": "2026-11-25", "sha256": SHA},
    }
    assert schema_errors({"doc_format": "semantic-confirmations/1", "confirmations": [entry]},
                         "semantic-confirmations/1") == []


def test_duplicate_keys_draft_not_unique_and_an_input_names_its_columns() -> None:
    entry, reason = draft(INPUT_ITEM, _result(INPUT_ITEM, ["rows", "keys", "duplicate_keys"],
                                              [["120", "100", "15"]]))
    assert reason is None
    assert entry["target"] == f"input:{INPUT}"
    assert entry["value"] == {
        "query": "cust_q1_p2", "on": "2026-11-25", "rows": 120,
        "partition": {"column": "dt", "values": ["20261122"]}, "engine": "spark",
        "columns": ["cust_no"], "unique": "no", "within": "each_partition", "keys": 100,
        "duplicate_keys": 15}


def test_a_value_set_result_drafts_the_column_observation() -> None:
    entry, reason = draft(VALUES_ITEM, _values([["M", "600"], ["F", "380"], ["null", "20"]]))
    assert reason is None
    assert entry["target"] == "column:gender_cd.observed_values"
    assert entry["value"] == {
        "query": "cust_q2_p1", "on": "2026-11-25", "rows": 1000,
        "partition": {"column": "dt", "values": ["20261122"]}, "engine": "spark",
        "values": [{"value": "M", "count": 600}, {"value": "F", "count": 380}],
        "complete": True, "nulls": 20}


def test_fifty_one_rows_say_the_list_is_not_complete() -> None:
    rows = [[f"V{n:02d}", str(100 - n)] for n in range(51)]
    entry, reason = draft(VALUES_ITEM, _values(rows))
    assert reason is None
    assert entry["value"]["complete"] is False
    assert len(entry["value"]["values"]) == 50 and entry["value"]["values"][-1]["value"] == "V49"


def test_a_fallback_partition_records_the_one_requested_and_the_filter_is_carried() -> None:
    item = dict(ROW_ITEM, filter="customer_id IS NOT NULL")
    result = _result(item, ["rows", "keys", "duplicate_keys"], [["10", "10", "0"]],
                     bizdate="20261123")
    entry, reason = draft(item, result)
    assert reason is None
    value = entry["value"]
    assert value["partition"] == {"column": "dt", "values": ["20261122"]}
    assert value["requested"] == "20261123" and value["filter"] == "customer_id IS NOT NULL"


def test_whitespace_differences_in_sql_executed_are_not_a_change() -> None:
    result = _row()
    result["sql_executed"] = "  " + result["sql_executed"].replace(" FROM ", "\n  FROM ") + ";\n"
    assert draft(ROW_ITEM, result)[1] is None


def test_elapsed_sec_is_the_one_optional_key() -> None:
    assert draft(ROW_ITEM, _row(elapsed_sec=3.2))[1] is None
    assert "keys" in refused(ROW_ITEM, _row(engine="spark"))


# ------------------------------------------------------------------ refusals


@pytest.mark.parametrize("change, words", [
    (lambda r: r.update(status="error"), "status"),
    (lambda r: r.update(sql_id="other_id"), "sql_id"),
    (lambda r: r.update(sql_executed=r["sql_executed"].replace("customer_id", "cust_id")),
     "sql_executed"),
    (lambda r: r.update(sql_executed=r["sql_executed"].replace("'20261122'", "'2026112' OR 1=1 --'")),
     "sql_executed"),
    (lambda r: r.update(rows=[["null", "0", "null"]]), "null"),
    (lambda r: r.update(rows=[["0", "0", "0"]]), "rows"),
    (lambda r: r.update(rows=[]), "row"),
    (lambda r: r.update(rows=[["10", "10", "0"], ["10", "10", "0"]]), "one row"),
    (lambda r: r.update(rows=[["-1", "0", "0"]]), "negative"),
    (lambda r: r.update(rows=[["10", "1.5", "0"]]), "integer"),
    (lambda r: r.update(rows=[["10", "12", "0"]]), "keys"),
    (lambda r: r.update(rows=[["10", "8", "0"]]), "duplicate_keys"),
    (lambda r: r.update(rows=[["10", "10", "2"]]), "duplicate_keys"),
    (lambda r: r.update(columns=["rows", "keys", "dup_keys"]), "columns"),
    (lambda r: r.update(columns=["rows", "keys", "duplicate_keys", "nulls"],
                        rows=[["10", "10", "0", "0"]]), "columns"),
    (lambda r: r.update(columns=["keys", "rows", "duplicate_keys"]), "columns"),
    (lambda r: r.update(rows=[["10", "10"]]), "cells"),
])
def test_a_uniqueness_result_is_refused(change, words) -> None:
    result = _row()
    change(result)
    assert words in refused(ROW_ITEM, result)


@pytest.mark.parametrize("rows, words", [
    ([], "row"),
    ([["M", "1"]] * 2, "twice"),
    ([[f"V{n}", "1"] for n in range(52)], "51"),
    ([["13800138000", "5"]], "contact"),
    ([["M", "null"]], "null"),
    ([["M", "0"]], "rows"),
    ([["x" * 65, "1"]], "value"),
])
def test_a_value_set_result_is_refused(rows, words) -> None:
    assert words in refused(VALUES_ITEM, _values(rows))


def test_a_contact_shaped_cell_refuses_evidence_too_but_a_count_is_a_count() -> None:
    result = _result(BLANK_ITEM, ["rows", "blank_rows"], [["联系 13800138000", "1"]])
    assert "contact" in pr.evidence_reference(BLANK_ITEM, result, SHA)[1]
    # an integer cell is a count, whatever its digits look like
    entry, reason = draft(ROW_ITEM, _row("13800138000", "13800138000", "0"))
    assert reason is None and entry["value"]["rows"] == 13800138000


def test_a_renamed_or_extra_value_set_column_is_refused() -> None:
    assert "columns" in refused(VALUES_ITEM, _result(VALUES_ITEM, ["value", "count"], [["M", "1"]]))
    assert "columns" in refused(VALUES_ITEM, _result(
        VALUES_ITEM, ["value", "cnt", "dt"], [["M", "1", "20261122"]]))


def test_an_item_that_lands_nothing_gives_no_draft() -> None:
    result = _result(BLANK_ITEM, ["rows", "blank_rows"], [["10", "10"]])
    assert "lands" in refused(BLANK_ITEM, result)


def test_no_fallback_refuses_another_partition() -> None:
    item = copy.deepcopy(ROW_ITEM)
    item["partitions"][0]["fallback"] = "none"
    result = _row(bizdate="20261123")
    assert "fallback" in refused(item, result)


@pytest.mark.parametrize("text, words", [
    ("not json", "JSON"),
    ("[1, 2]", "object"),
    (json.dumps({"sql_id": "x"}), "keys"),
])
def test_only_the_result_json_object_is_read(text, words) -> None:
    with pytest.raises(pr.ResultRefused) as error:
        pr.read_result(text)
    assert words in str(error.value)


def test_a_tsv_paste_is_not_read() -> None:
    with pytest.raises(pr.ResultRefused):
        pr.read_result("rows\tkeys\tduplicate_keys\n10\t10\t0\n")


# ------------------------------------------------------------------ evidence of an answer


def test_a_non_landing_result_is_evidence_by_reference() -> None:
    result = _result(BLANK_ITEM, ["rows", "blank_rows"], [["10", "10"]])
    reference, reason = pr.evidence_reference(BLANK_ITEM, result, SHA)
    assert reason is None
    assert reference == {"probe": "cust_q3_p1",
                         "partition": {"column": "dt", "values": ["20261122"]},
                         "on": "2026-11-25", "sha256": SHA}


def test_evidence_is_refused_on_the_same_grounds_as_a_draft() -> None:
    result = _result(BLANK_ITEM, ["rows", "blank_rows"], [["10", "10"]], status="error")
    assert pr.evidence_reference(BLANK_ITEM, result, SHA)[0] is None
    result = _result(BLANK_ITEM, ["rows", "blank_count"], [["10", "10"]])
    assert "columns" in pr.evidence_reference(BLANK_ITEM, result, SHA)[1]


# ------------------------------------------------------------------ the confirmations schema


def _confirmations(**entry):
    base = {"table": DEMO_TABLE, "target": "question:q1", "value": "答", "by": "甲",
            "date": "2026-11-26"}
    return {"doc_format": "semantic-confirmations/1", "confirmations": [{**base, **entry}]}


def test_evidence_is_an_optional_reference_on_any_confirmation() -> None:
    ref = {"probe": "p1", "partition": {"column": "dt", "values": ["20261122"]},
           "on": "2026-11-25", "sha256": SHA}
    assert schema_errors(_confirmations(), "semantic-confirmations/1") == []
    assert schema_errors(_confirmations(evidence=ref), "semantic-confirmations/1") == []
    for bad in ({**ref, "rows": [["1"]]}, {k: v for k, v in ref.items() if k != "sha256"},
                {**ref, "sha256": "xyz"}):
        assert schema_errors(_confirmations(evidence=bad), "semantic-confirmations/1")


def test_semantic_confirm_applies_a_drafted_entry_and_keeps_nothing_of_its_evidence() -> None:
    from scope_lineage.semantics.confirm import apply_confirmations

    from .table_semantics_demo import example

    document = example()
    entry, _ = draft(VALUES_ITEM, _values([["M", "600"], ["F", "380"]]))
    bare = {key: value for key, value in entry.items() if key != "evidence"}
    with_evidence = apply_confirmations({DEMO_TABLE: document}, [entry])
    without = apply_confirmations({DEMO_TABLE: document}, [bare])
    assert with_evidence.unmatched == [] and with_evidence.applied == [entry]
    assert with_evidence.documents == without.documents
    assert SHA not in json.dumps(with_evidence.documents)
