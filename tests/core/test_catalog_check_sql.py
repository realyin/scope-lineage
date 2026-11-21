"""``catalog check-sql``: compare a query an agent wrote against what the catalog records.

The agent reads the catalog, then writes SQL. Each rule below fires only on what the catalog
and the query together settle, and stays silent (or says ``info``) when they do not: every
rule has a case that fires and a case that must not.

Every case runs on the recorded demo ontology. Of its nine tables, seven carry a table card
(``evidence.representations[t].declared_columns``) whose count equals the bound columns, so
their column list is complete; the event table of fee waivers and the customer extension
table have none, so an unbound column there cannot be called absent.
"""

from __future__ import annotations

import copy
import io
import json
from pathlib import Path

import pytest

from scope_lineage.cli import main
from scope_lineage.render.catalog_sql_check import (
    CHECK_FORMAT,
    check_sql,
    render_check_sql_text,
)
from scope_lineage.scope.query_facts import QueryFactsError, query_facts

ONTOLOGY = Path(__file__).parent / "fixtures" / "catalog" / "ontology.json"
LOAN = "demo_dwd.dwd_lending_loan_df"
REPAYMENT = "demo_dwd.dwd_lending_repayment_di"
HISTORY = "demo_dwd.dwd_lending_loan_status_his"
CUSTOMER = "demo_dwd.dwd_party_customer_info_df"
WAIVER = "demo_dwd.dwd_collection_fee_waiver_di"


@pytest.fixture(scope="module")
def document() -> dict:
    return json.loads(ONTOLOGY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def partitioned(document: dict) -> dict:
    """The demo ontology with the loan snapshot's ``dt`` marked as its load partition."""
    changed = copy.deepcopy(document)
    (rep,) = [r for r in changed["representations"] if r["table"] == LOAN]
    (binding,) = [b for b in rep["bindings"] if b["column"] == "dt"]
    binding["time_role"] = "partition"
    return changed


def _check(document: dict, sql: str) -> dict:
    return check_sql(document, query_facts(sql))


def _rule(result: dict, rule: str) -> list[dict]:
    return [f for f in result["findings"] if f["rule"] == rule]


# ------------------------------------------------------------------ shape


def test_the_result_names_its_format_tables_and_findings(document: dict) -> None:
    result = _check(document, f"SELECT l.loan_no FROM {LOAN} l WHERE l.dt = '2024-01-01'")
    assert result["doc_format"] == CHECK_FORMAT == "catalog-sql-check/1"
    (table,) = result["tables"]
    assert table["table"] == LOAN
    assert table["in_catalog"] is True
    assert table["columns_complete"] is True
    assert result["findings"] == []


def test_sql_that_does_not_parse_is_refused() -> None:
    with pytest.raises(QueryFactsError):
        query_facts("SELECT FROM WHERE (")


def test_a_parse_failure_says_where_and_shows_the_text() -> None:
    with pytest.raises(QueryFactsError) as caught:
        query_facts("SELECT a\nFROM t\nWHERE x IN () AND y = ... AND z = 1")
    message = str(caught.value)
    assert "第 3 行第 23 列" in message
    assert "y = " in message and "..." in message


def test_the_query_inside_an_insert_is_checked_and_its_target_is_not_a_read(
    document: dict,
) -> None:
    result = _check(
        document,
        f"INSERT OVERWRITE TABLE demo_tmp.out_t PARTITION (dt = '1') "
        f"SELECT l.loan_amount FROM {LOAN} l",
    )
    assert [f["column"] for f in _rule(result, "unknown_column")] == ["loan_amount"]
    assert [t["table"] for t in result["tables"]] == [LOAN]


def test_the_query_inside_an_insert_keeps_its_leading_with(document: dict) -> None:
    result = _check(
        document,
        f"WITH x AS (SELECT * FROM {LOAN}) INSERT OVERWRITE TABLE demo_tmp.out_t "
        "SELECT x.loan_amount FROM x",
    )
    assert [f["column"] for f in _rule(result, "unknown_column")] == ["loan_amount"]


def test_the_query_inside_a_ctas_is_checked(document: dict) -> None:
    result = _check(
        document, f"CREATE TABLE demo_tmp.out_t AS SELECT l.loan_amount FROM {LOAN} l"
    )
    assert [f["column"] for f in _rule(result, "unknown_column")] == ["loan_amount"]
    assert [t["table"] for t in result["tables"]] == [LOAN]


def test_a_script_with_no_query_is_refused() -> None:
    with pytest.raises(QueryFactsError):
        query_facts("SET spark.sql.shuffle.partitions = 10")


# ------------------------------------------- rule 1: table_not_in_catalog


def test_a_table_the_catalog_does_not_represent_is_reported_as_info(document: dict) -> None:
    result = _check(document, "SELECT x.a FROM demo_ods.ods_unknown_df x")
    (finding,) = _rule(result, "table_not_in_catalog")
    assert finding["severity"] == "info"
    assert finding["table"] == "demo_ods.ods_unknown_df"
    assert "目录" in finding["message"]
    assert _rule(result, "unknown_column") == []


def test_a_catalog_table_is_not_reported_missing(document: dict) -> None:
    result = _check(document, f"SELECT l.loan_no FROM {LOAN} l")
    assert _rule(result, "table_not_in_catalog") == []


def test_a_cte_name_is_not_taken_for_a_table(document: dict) -> None:
    result = _check(
        document,
        f"WITH loans AS (SELECT loan_no FROM {LOAN}) SELECT loans.loan_no FROM loans",
    )
    assert _rule(result, "table_not_in_catalog") == []
    assert [t["table"] for t in result["tables"]] == [LOAN]


# ------------------------------------------------- rule 2: unknown_column


def test_a_column_a_complete_table_does_not_have_is_an_error(document: dict) -> None:
    result = _check(document, f"SELECT l.loan_amount FROM {LOAN} l")
    (finding,) = _rule(result, "unknown_column")
    assert finding["severity"] == "error"
    assert (finding["table"], finding["column"]) == (LOAN, "loan_amount")
    assert finding["alias"] == "l"
    assert "principal_amt" in finding["catalog"]["columns"]


def test_a_column_the_catalog_records_is_silent(document: dict) -> None:
    result = _check(document, f"SELECT l.principal_amt, l.loan_status FROM {LOAN} l")
    assert _rule(result, "unknown_column") == []


def test_a_column_name_ignores_case(document: dict) -> None:
    result = _check(document, f"SELECT L.Principal_Amt FROM {LOAN} L")
    assert _rule(result, "unknown_column") == []


def test_an_unbound_column_of_a_partly_recorded_table_is_only_info(document: dict) -> None:
    result = _check(document, f"SELECT w.reviewer FROM {WAIVER} w")
    assert _rule(result, "unknown_column") == []
    (finding,) = _rule(result, "column_unchecked")
    assert finding["severity"] == "info"
    assert (finding["table"], finding["column"]) == (WAIVER, "reviewer")


def test_a_column_read_through_a_cte_star_is_checked_against_the_table(document: dict) -> None:
    result = _check(
        document,
        f"WITH x AS (SELECT * FROM {LOAN}) SELECT x.loan_amount FROM x",
    )
    (finding,) = _rule(result, "unknown_column")
    assert (finding["table"], finding["column"]) == (LOAN, "loan_amount")


def test_an_unqualified_column_of_a_single_table_is_checked(document: dict) -> None:
    result = _check(document, f"SELECT loan_amount FROM {LOAN}")
    assert [f["column"] for f in _rule(result, "unknown_column")] == ["loan_amount"]


def test_an_unqualified_column_beside_two_tables_is_not_guessed(document: dict) -> None:
    result = _check(
        document,
        f"SELECT nothing_here FROM {LOAN} l JOIN {REPAYMENT} r ON l.loan_no = r.loan_no",
    )
    assert _rule(result, "unknown_column") == []


def test_a_projection_alias_used_in_order_by_is_not_a_column(document: dict) -> None:
    result = _check(
        document, f"SELECT l.principal_amt AS amount FROM {LOAN} l ORDER BY amount"
    )
    assert _rule(result, "unknown_column") == []


# ----------------------------------------------- rule 3: join_not_recorded


def test_a_join_on_columns_the_catalog_does_not_relate_is_a_warning(document: dict) -> None:
    result = _check(
        document,
        f"SELECT l.loan_no FROM {LOAN} l JOIN {REPAYMENT} r ON l.customer_id = r.loan_no",
    )
    (finding,) = _rule(result, "join_not_recorded")
    assert finding["severity"] == "warning"
    assert finding["left"] == {"table": LOAN, "alias": "l"}
    assert finding["right"] == {"table": REPAYMENT, "alias": "r"}
    assert finding["pairs"] == [{
        "left": {"table": LOAN, "column": "customer_id", "alias": "l"},
        "right": {"table": REPAYMENT, "column": "loan_no", "alias": "r"},
    }]
    recorded = {(p["left"], p["right"]) for p in finding["catalog"]["recorded"]}
    assert (f"{LOAN}.loan_no", f"{REPAYMENT}.loan_no") in recorded
    assert (f"{LOAN}.customer_id", f"{REPAYMENT}.customer_id") in recorded


def test_pairs_narrowing_a_recorded_join_are_silent(document: dict) -> None:
    result = _check(
        document,
        f"SELECT l.loan_no FROM {LOAN} l JOIN {REPAYMENT} r "
        "ON l.loan_no = r.loan_no AND l.dt = r.dt AND l.customer_id = r.customer_id",
    )
    assert _rule(result, "join_not_recorded") == []


def test_a_join_with_no_recorded_pair_is_one_finding_listing_every_pair(document: dict) -> None:
    result = _check(
        document,
        f"SELECT l.loan_no FROM {LOAN} l JOIN {REPAYMENT} r "
        "ON l.customer_id = r.loan_no AND l.dt = r.dt",
    )
    (finding,) = _rule(result, "join_not_recorded")
    asked = [(p["left"]["column"], p["right"]["column"]) for p in finding["pairs"]]
    assert asked == [("customer_id", "loan_no"), ("dt", "dt")]
    assert f"{LOAN}.customer_id = {REPAYMENT}.loan_no" in finding["message"]
    assert f"{LOAN}.dt = {REPAYMENT}.dt" in finding["message"]


def test_narrowing_pairs_in_where_follow_the_same_rule(document: dict) -> None:
    result = _check(
        document,
        f"SELECT l.loan_no FROM {LOAN} l, {REPAYMENT} r "
        "WHERE l.loan_no = r.loan_no AND l.dt = r.dt",
    )
    assert _rule(result, "join_not_recorded") == []


def test_a_join_the_catalog_records_is_silent(document: dict) -> None:
    result = _check(
        document,
        f"SELECT l.loan_no FROM {LOAN} l JOIN {REPAYMENT} r ON l.loan_no = r.loan_no",
    )
    assert _rule(result, "join_not_recorded") == []


def test_a_self_join_on_a_self_reference_is_recorded(document: dict) -> None:
    result = _check(
        document,
        f"SELECT a.loan_no FROM {LOAN} a JOIN {LOAN} b ON a.orig_loan_no = b.loan_no",
    )
    assert _rule(result, "join_not_recorded") == []


def test_a_join_through_a_cte_is_resolved_to_its_table(document: dict) -> None:
    result = _check(
        document,
        f"WITH x AS (SELECT customer_id FROM {LOAN}) "
        f"SELECT r.loan_no FROM x JOIN {REPAYMENT} r ON x.customer_id = r.loan_no",
    )
    (finding,) = _rule(result, "join_not_recorded")
    assert finding["left"]["table"] == LOAN


def test_a_join_on_a_column_of_a_partly_recorded_table_is_not_judged(document: dict) -> None:
    result = _check(
        document,
        f"SELECT w.loan_no FROM {WAIVER} w JOIN {LOAN} l ON w.case_ref = l.loan_no",
    )
    assert _rule(result, "join_not_recorded") == []


def test_an_equality_in_where_between_two_tables_is_a_join_too(document: dict) -> None:
    result = _check(
        document,
        f"SELECT l.loan_no FROM {LOAN} l, {REPAYMENT} r WHERE l.customer_id = r.loan_no",
    )
    assert len(_rule(result, "join_not_recorded")) == 1


# ---------------------------------------- rule 4: missing_partition_filter


def test_a_partitioned_table_read_with_no_partition_predicate_is_a_warning(
    partitioned: dict,
) -> None:
    result = _check(partitioned, f"SELECT l.loan_no FROM {LOAN} l")
    (finding,) = _rule(result, "missing_partition_filter")
    assert finding["severity"] == "warning"
    assert (finding["table"], finding["alias"]) == (LOAN, "l")
    assert finding["catalog"]["columns"] == [{"column": "dt", "role": "partition"}]


def test_a_partition_predicate_in_where_is_silent(partitioned: dict) -> None:
    result = _check(partitioned, f"SELECT l.loan_no FROM {LOAN} l WHERE l.dt = '2024-01-01'")
    assert _rule(result, "missing_partition_filter") == []


def test_a_partition_predicate_in_join_on_is_silent(partitioned: dict) -> None:
    result = _check(
        partitioned,
        f"SELECT r.loan_no FROM {REPAYMENT} r JOIN {LOAN} l "
        "ON l.loan_no = r.loan_no AND l.dt = '2024-01-01'",
    )
    assert _rule(result, "missing_partition_filter") == []


def test_a_partition_predicate_outside_a_star_cte_still_reaches_the_read(
    partitioned: dict,
) -> None:
    result = _check(
        partitioned,
        f"WITH x AS (SELECT * FROM {LOAN}) SELECT x.loan_no FROM x WHERE x.dt = '2024-01-01'",
    )
    assert _rule(result, "missing_partition_filter") == []


def test_each_read_of_a_table_needs_its_own_predicate(partitioned: dict) -> None:
    result = _check(
        partitioned,
        f"SELECT a.loan_no FROM {LOAN} a JOIN {LOAN} b ON a.orig_loan_no = b.loan_no "
        "WHERE a.dt = '2024-01-01'",
    )
    (finding,) = _rule(result, "missing_partition_filter")
    assert finding["alias"] == "b"


def test_a_table_with_no_time_role_is_not_judged(document: dict) -> None:
    result = _check(document, f"SELECT l.loan_no FROM {LOAN} l")
    assert _rule(result, "missing_partition_filter") == []


def test_a_zipper_read_with_no_window_predicate_is_a_warning(document: dict) -> None:
    result = _check(document, f"SELECT h.loan_no, h.loan_status FROM {HISTORY} h")
    (finding,) = _rule(result, "missing_partition_filter")
    assert finding["table"] == HISTORY
    assert {c["column"] for c in finding["catalog"]["columns"]} == {"start_date", "end_date"}


def test_a_zipper_read_pinned_on_one_window_end_is_silent(document: dict) -> None:
    result = _check(
        document, f"SELECT h.loan_no FROM {HISTORY} h WHERE h.end_date = '9999-12-31'"
    )
    assert _rule(result, "missing_partition_filter") == []


# ---------------------------------------- rule 5: fan_out_unaggregated


FAN_OUT = (
    f"SELECT SUM(l.principal_amt) FROM {LOAN} l JOIN {REPAYMENT} r ON l.loan_no = r.loan_no"
)


def test_summing_the_one_side_of_a_one_to_many_join_is_a_warning(document: dict) -> None:
    result = _check(document, FAN_OUT)
    (finding,) = _rule(result, "fan_out_unaggregated")
    assert finding["severity"] == "warning"
    assert finding["table"] == LOAN
    assert finding["column"] == "principal_amt"
    assert finding["catalog"]["many_side"] == {
        "table": REPAYMENT, "alias": "r", "grain": ["repay_txn_no"], "join_columns": ["loan_no"],
    }


def test_a_fact_summed_over_a_dimension_whose_grain_the_join_leaves_open_is_a_warning(
    document: dict,
) -> None:
    # the repayment's own grain is not covered either; only the other side decides
    result = _check(
        document,
        f"SELECT SUM(r.repay_amt) FROM {REPAYMENT} r JOIN {HISTORY} h ON r.loan_no = h.loan_no",
    )
    (finding,) = _rule(result, "fan_out_unaggregated")
    assert (finding["table"], finding["column"]) == (REPAYMENT, "repay_amt")
    assert finding["catalog"]["many_side"]["table"] == HISTORY
    assert finding["catalog"]["many_side"]["grain"] == ["loan_no", "start_date"]


def test_the_same_fact_with_the_dimension_pinned_to_one_version_is_silent(
    document: dict,
) -> None:
    result = _check(
        document,
        f"SELECT SUM(r.repay_amt) FROM {REPAYMENT} r JOIN {HISTORY} h ON r.loan_no = h.loan_no "
        "AND h.end_date = '9999-12-31'",
    )
    assert _rule(result, "fan_out_unaggregated") == []


def test_a_one_to_one_join_stays_silent(document: dict) -> None:
    result = _check(
        document,
        f"SELECT SUM(l.principal_amt) FROM {LOAN} l JOIN {LOAN} o ON l.loan_no = o.loan_no",
    )
    assert _rule(result, "fan_out_unaggregated") == []


def test_counting_a_column_of_the_one_side_is_a_warning_too(document: dict) -> None:
    result = _check(
        document,
        f"SELECT COUNT(l.loan_no) FROM {LOAN} l JOIN {REPAYMENT} r ON l.loan_no = r.loan_no",
    )
    assert len(_rule(result, "fan_out_unaggregated")) == 1


def test_summing_the_many_side_is_silent(document: dict) -> None:
    result = _check(
        document,
        f"SELECT SUM(r.repay_amt) FROM {LOAN} l JOIN {REPAYMENT} r ON l.loan_no = r.loan_no",
    )
    assert _rule(result, "fan_out_unaggregated") == []


def test_a_distinct_count_is_silent(document: dict) -> None:
    result = _check(
        document,
        f"SELECT COUNT(DISTINCT l.loan_no) FROM {LOAN} l "
        f"JOIN {REPAYMENT} r ON l.loan_no = r.loan_no",
    )
    assert _rule(result, "fan_out_unaggregated") == []


def test_a_many_side_reduced_in_a_subquery_first_is_silent(document: dict) -> None:
    result = _check(
        document,
        f"SELECT SUM(l.principal_amt) FROM {LOAN} l JOIN "
        f"(SELECT loan_no, SUM(repay_amt) AS paid FROM {REPAYMENT} GROUP BY loan_no) r "
        "ON l.loan_no = r.loan_no",
    )
    assert _rule(result, "fan_out_unaggregated") == []


def test_grouping_by_the_many_sides_grain_is_silent(document: dict) -> None:
    result = _check(
        document,
        f"SELECT r.repay_txn_no, SUM(l.principal_amt) FROM {LOAN} l "
        f"JOIN {REPAYMENT} r ON l.loan_no = r.loan_no GROUP BY r.repay_txn_no",
    )
    assert _rule(result, "fan_out_unaggregated") == []


def test_a_many_side_pinned_on_the_rest_of_its_grain_is_silent(document: dict) -> None:
    result = _check(
        document,
        f"SELECT SUM(l.principal_amt) FROM {LOAN} l JOIN {HISTORY} h ON l.loan_no = h.loan_no "
        "WHERE h.end_date = '9999-12-31'",
    )
    assert _rule(result, "fan_out_unaggregated") == []


def test_a_window_sum_is_not_an_aggregation(document: dict) -> None:
    result = _check(
        document,
        f"SELECT SUM(l.principal_amt) OVER (PARTITION BY l.loan_no) FROM {LOAN} l "
        f"JOIN {REPAYMENT} r ON l.loan_no = r.loan_no",
    )
    assert _rule(result, "fan_out_unaggregated") == []


def test_a_semi_join_does_not_fan_out(document: dict) -> None:
    result = _check(
        document,
        f"SELECT SUM(l.principal_amt) FROM {LOAN} l "
        f"LEFT SEMI JOIN {REPAYMENT} r ON l.loan_no = r.loan_no",
    )
    assert _rule(result, "fan_out_unaggregated") == []


# ------------------------------------------- rule 6: code_value_unknown


def test_a_literal_outside_the_code_set_is_a_warning(document: dict) -> None:
    result = _check(document, f"SELECT l.loan_no FROM {LOAN} l WHERE l.loan_status = '5'")
    (finding,) = _rule(result, "code_value_unknown")
    assert finding["severity"] == "warning"
    assert (finding["table"], finding["column"], finding["value"]) == (LOAN, "loan_status", "5")
    assert [v["value"] for v in finding["catalog"]["values"]] == ["1", "2", "3", "9"]


def test_a_literal_in_the_code_set_is_silent(document: dict) -> None:
    result = _check(
        document,
        f"SELECT l.loan_no FROM {LOAN} l WHERE l.loan_status = '2' OR l.loan_status IN (1, '3')",
    )
    assert _rule(result, "code_value_unknown") == []


def test_only_the_unknown_members_of_an_in_list_are_reported(document: dict) -> None:
    result = _check(
        document, f"SELECT c.customer_id FROM {CUSTOMER} c WHERE c.gender_cd IN ('F', 'X')"
    )
    assert [f["value"] for f in _rule(result, "code_value_unknown")] == ["X"]


def test_a_code_compared_through_a_cte_is_checked(document: dict) -> None:
    result = _check(
        document,
        f"WITH x AS (SELECT loan_no, loan_status FROM {LOAN}) "
        "SELECT x.loan_no FROM x WHERE x.loan_status = '7'",
    )
    assert [f["value"] for f in _rule(result, "code_value_unknown")] == ["7"]


def test_a_column_with_no_code_set_is_not_judged(document: dict) -> None:
    result = _check(document, f"SELECT l.loan_no FROM {LOAN} l WHERE l.loan_no = 'L-1'")
    assert _rule(result, "code_value_unknown") == []


# ---------------------------------------------------- statements and text


def test_each_statement_is_checked_and_named(document: dict) -> None:
    result = _check(
        document,
        f"SELECT l.loan_no FROM {LOAN} l;\nSELECT l.loan_amount FROM {LOAN} l;",
    )
    (finding,) = _rule(result, "unknown_column")
    assert finding["statement"] == 2


def test_the_text_names_each_finding_in_chinese(document: dict) -> None:
    result = _check(document, f"SELECT l.loan_amount FROM {LOAN} l WHERE l.loan_status = '5'")
    text = render_check_sql_text(result)
    assert "错误" in text and "警告" in text
    assert "loan_amount" in text and "'5'" in text


def test_the_text_says_when_nothing_was_found(document: dict) -> None:
    result = _check(document, f"SELECT l.loan_no FROM {LOAN} l")
    assert "没有发现问题" in render_check_sql_text(result)


# ---------------------------------------------------------------- command


def test_the_command_exits_0_when_the_query_is_clean(tmp_path: Path, capsys) -> None:
    sql = tmp_path / "q.sql"
    sql.write_text(f"SELECT l.loan_no FROM {LOAN} l", encoding="utf-8")
    assert main(["catalog", "check-sql", str(ONTOLOGY), str(sql)]) == 0
    assert "没有发现问题" in capsys.readouterr().out


def test_the_command_exits_0_when_findings_are_only_info(tmp_path: Path, capsys) -> None:
    sql = tmp_path / "q.sql"
    sql.write_text("SELECT x.a FROM demo_ods.ods_unknown_df x", encoding="utf-8")
    assert main(["catalog", "check-sql", str(ONTOLOGY), str(sql), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert [f["rule"] for f in result["findings"]] == ["table_not_in_catalog"]


def test_the_command_exits_1_on_findings_and_reads_stdin(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(f"SELECT l.loan_amount FROM {LOAN} l"))
    assert main(["catalog", "check-sql", str(ONTOLOGY), "-", "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["doc_format"] == "catalog-sql-check/1"
    assert [f["rule"] for f in result["findings"]] == ["unknown_column"]


def test_the_command_exits_2_for_sql_that_does_not_parse(tmp_path: Path, capsys) -> None:
    sql = tmp_path / "q.sql"
    sql.write_text("SELECT FROM WHERE (", encoding="utf-8")
    assert main(["catalog", "check-sql", str(ONTOLOGY), str(sql)]) == 2
    assert "check-sql" in capsys.readouterr().err


def test_the_command_exits_2_for_a_file_that_is_not_there(tmp_path: Path, capsys) -> None:
    assert main(["catalog", "check-sql", str(ONTOLOGY), str(tmp_path / "none.sql")]) == 2
    assert "none.sql" in capsys.readouterr().err


# ------------------------------------------------------------ placeholders
#
# A definition the catalog does not give is written as a comment ``/* 待确认：<what> */``
# beside a neutral predicate or value. check-sql lists each one, never as a blocking
# finding, and ties it to a column only when it sits right after ``<column> =`` (or another
# comparison, or ``<column> IN (``).


def _placeholders(sql: str) -> list[dict]:
    return [p for s in query_facts(sql) for p in s["placeholders"]]


def test_a_placeholder_beside_a_neutral_predicate_is_listed_with_no_column(
    document: dict,
) -> None:
    result = _check(
        document,
        f"SELECT l.loan_no FROM {LOAN} l WHERE l.dt = '2024-01-01' AND /* 待确认：结清的判定 */ 1 = 1",
    )
    assert result["placeholders"] == [
        {"statement": 1, "text": "结清的判定", "written": None, "table": None, "column": None}
    ]
    (finding,) = _rule(result, "pending_definition")
    assert finding["severity"] == "info"
    assert finding["statement"] == 1
    assert finding["text"] == "结清的判定"
    assert "结清的判定" in finding["message"]


def test_the_marker_takes_either_colon_and_a_line_comment(document: dict) -> None:
    found = _placeholders(
        f"SELECT l.loan_no -- 待确认: 一行算不算一笔\n"
        f"FROM {LOAN} l WHERE /* 待确认：哪些状态算正常 */ 1 = 1"
    )
    assert [p["text"] for p in found] == ["一行算不算一笔", "哪些状态算正常"]


def test_comments_without_the_marker_and_marker_text_in_strings_are_not_placeholders() -> None:
    found = _placeholders(
        f"SELECT '待确认：不是注释' AS a, l.loan_no -- 近30天，是否含今天待确认\n"
        f"FROM {LOAN} l /* 待确认 没有冒号 */ WHERE l.dt = '1'"
    )
    assert found == []


def test_a_placeholder_right_after_a_comparison_is_tied_to_that_column(document: dict) -> None:
    result = _check(
        document,
        f"SELECT l.loan_no FROM {LOAN} l WHERE l.loan_status = /* 待确认：哪个码算结清 */ '1'"
        f" OR l.loan_status IN (/* 待确认：哪些码算逾期 */ '2')",
    )
    assert [(p["text"], p["written"], p["table"], p["column"]) for p in result["placeholders"]] == [
        ("哪个码算结清", "l.loan_status", LOAN, "loan_status"),
        ("哪些码算逾期", "l.loan_status", LOAN, "loan_status"),
    ]


def test_a_placeholder_through_a_subquery_reaches_the_physical_column(document: dict) -> None:
    result = _check(
        document,
        f"SELECT s.st FROM (SELECT loan_status AS st FROM {LOAN}) s"
        f" WHERE s.st = /* 待确认：哪个码算结清 */ '1'",
    )
    (placeholder,) = result["placeholders"]
    assert (placeholder["written"], placeholder["table"], placeholder["column"]) == (
        "s.st", LOAN, "loan_status",
    )


def test_a_placeholder_not_right_after_a_comparison_is_not_tied_to_a_column() -> None:
    found = _placeholders(
        f"SELECT l.loan_no FROM {LOAN} l WHERE /* 待确认：甲 */ l.loan_status = '1'"
        f" AND l.dt = '1' /* 待确认：乙 */ AND l.principal_amt + 1 = /* 待确认：丙 */ 2"
    )
    assert [(p["text"], p["written"], p["targets"]) for p in found] == [
        ("甲", None, []), ("乙", None, []), ("丙", None, []),
    ]


def test_a_bare_column_of_two_sources_is_written_but_not_attributed(document: dict) -> None:
    result = _check(
        document,
        f"SELECT l.loan_no FROM {LOAN} l JOIN {CUSTOMER} c ON l.customer_id = c.customer_id"
        f" WHERE gender_cd = /* 待确认：未知性别怎么算 */ 'U'",
    )
    (placeholder,) = result["placeholders"]
    assert (placeholder["written"], placeholder["table"], placeholder["column"]) == (
        "gender_cd", None, None,
    )


def test_placeholders_belong_to_the_statement_they_are_written_in() -> None:
    """A comment after a semicolon opens the next statement; one before it closes its own."""
    statements = query_facts(
        f"SELECT l.loan_no FROM {LOAN} l WHERE /* 待确认：甲 */ 1 = 1 /* 待确认：乙 */;\n"
        f"/* 待确认：丙 */\n"
        f"SELECT c.customer_id FROM {CUSTOMER} c WHERE /* 待确认：丁 */ 1 = 1;"
    )
    first, second = statements
    assert [p["text"] for p in first["placeholders"]] == ["甲", "乙"]
    assert [p["text"] for p in second["placeholders"]] == ["丙", "丁"]
    assert second["statement"] > first["statement"]


def test_the_text_lists_placeholders(document: dict) -> None:
    result = _check(document, f"SELECT l.loan_no FROM {LOAN} l WHERE /* 待确认：结清的判定 */ 1 = 1")
    text = render_check_sql_text(result)
    assert "pending_definition" in text and "结清的判定" in text


def test_the_command_exits_0_when_the_only_findings_are_placeholders(
    tmp_path: Path, capsys,
) -> None:
    sql = tmp_path / "q.sql"
    sql.write_text(
        f"SELECT l.loan_no FROM {LOAN} l WHERE /* 待确认：结清的判定 */ 1 = 1", encoding="utf-8"
    )
    assert main(["catalog", "check-sql", str(ONTOLOGY), str(sql), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert [p["text"] for p in result["placeholders"]] == ["结清的判定"]
