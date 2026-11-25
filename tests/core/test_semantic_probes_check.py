"""``semantic probes check``: static checks of a ``question-probes/1`` file. No SQL is run.

A probes file lists, per open question of a table, its sub-questions; a sub-question the
data can answer carries one SELECT for a person to run on the platform. The check holds
each query to C1-C9 (parse, one read-only SELECT, tables and columns from the packet,
partition filters, no sensitive column in the output, bounded value lists, the question
as the document asks it now, a query for every data item, and the fixed output columns
of a query whose result may land in an observation slot). Every fixture is the good file
below with one thing changed, so each test names the one check it is about.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
from pathlib import Path

import pytest

from .table_semantics_demo import DEMO_TABLE, demo_packets, example, run, write_json

INPUT = "demo_ods.ods_core_customer_df"
OTHER = "demo_dwd.dwd_lending_loan_df"
ASKED = "性别码值除了 F、M、U 以外，还会不会出现其他值？"

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


def _part(table: str = DEMO_TABLE) -> list[dict]:
    return [{"table": table, "column": "dt", "want": "${bizdate}",
             "fallback": "latest_available"}]


def _data(id_: str, part: int, shape: str, sql: str, lands=None, table=DEMO_TABLE,
          partitions=None) -> dict:
    item = {
        "id": id_, "table": DEMO_TABLE, "question": "q1", "asked": ASKED, "part": part,
        "ask": "sub-question text", "class": "data", "shape": shape, "sql": sql,
        "partitions": _part(table) if partitions is None else partitions,
        "engine": "spark", "how_to_read": "duplicate_keys 0 means no key repeats",
    }
    if lands is not None:
        item["lands"] = lands
    return item


GOOD = {
    "doc_format": "question-probes/1",
    "placeholders": {"${bizdate}": "20260101"},
    "items": [
        _data("p1", 1, "uniqueness", ROW_UNIQUE, "summary.row.observed"),
        _data("p2", 2, "uniqueness", INPUT_UNIQUE, f"input:{INPUT}", table=INPUT),
        _data("p3", 3, "value_set", VALUE_SET, "column:gender_cd.observed_values"),
        _data("p4", 4, "conditional_count", BLANKS),
        {"id": "p5", "table": DEMO_TABLE, "question": "q1", "asked": ASKED, "part": 5,
         "ask": "what an unexpected value means", "class": "human",
         "note": "only the table's owner knows"},
    ],
}


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory) -> Path:
    """A run directory: packets/ of the demo corpus, docs/ with the example document."""
    root = tmp_path_factory.mktemp("run")
    packets = demo_packets(root)
    write_json(root / "docs" / f"{DEMO_TABLE}.json", example(packets))
    return root


def _probes(tmp_path: Path, document: dict) -> Path:
    return write_json(tmp_path / "probes" / "question-probes.json", document)


def _good() -> dict:
    return copy.deepcopy(GOOD)


def _sensitive(tmp_path: Path, *lines: str) -> Path:
    path = tmp_path / "sensitive.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _check(tmp_path: Path, run_dir: Path, document: dict, *extra, docs=True,
           sensitive: tuple[str, ...] | None = ("# blocked names", "verified_customer_no")):
    args = ["semantic", "probes", "check", _probes(tmp_path, document),
            "--packets", run_dir / "packets", "--json"]
    if docs:
        args += ["--docs", run_dir / "docs"]
    if sensitive is not None:
        args += ["--sensitive", _sensitive(tmp_path, *sensitive)]
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = run(*args, *extra)
    report = json.loads(out.getvalue()) if out.getvalue().strip() else None
    return code, report, err.getvalue()


def _findings(report: dict, level: str = "FAIL") -> list[tuple[str, str, str]]:
    return [(item["id"], f["check"], f["message"])
            for item in report["items"] for f in item["findings"] if f["level"] == level]


def _checks(report: dict, item_id: str, level: str = "FAIL") -> set[str]:
    return {check for id_, check, _ in _findings(report, level) if id_ == item_id}


def _with(item_id: str, **changes) -> dict:
    document = _good()
    for item in document["items"]:
        if item["id"] == item_id:
            for key, value in changes.items():
                if value is None:
                    item.pop(key, None)
                else:
                    item[key] = value
    return document


# ------------------------------------------------------------------ the good file


def test_the_good_file_passes_every_check(tmp_path: Path, run_dir: Path) -> None:
    code, report, _ = _check(tmp_path, run_dir, _good())
    assert _findings(report) == []
    assert _findings(report, "WARN") == []
    assert report["warnings"] == []
    assert code == 0
    assert report["doc_format"] == "question-probes-check/1"
    assert report["summary"] == {
        "items": 5, "data": 4, "human": 1, "corpus": 0, "failures": 0, "warnings": 0,
        "full_scans": 0, "checks": ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9"],
    }


def test_the_text_report_ends_with_the_result(tmp_path: Path, run_dir: Path) -> None:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = run("semantic", "probes", "check", _probes(tmp_path, _good()),
                   "--packets", run_dir / "packets", "--docs", run_dir / "docs",
                   "--sensitive", _sensitive(tmp_path, "verified_customer_no"))
    lines = out.getvalue().splitlines()
    assert code == 0
    assert lines[0].startswith("question-probes check: ")
    assert "items: 5 (data 4, human 1, corpus 0)" in lines
    assert lines[-1] == "RESULT: PASS (0 failure(s), 0 warning(s))"


# ------------------------------------------------------------------ C1 / C2


def test_c1_a_query_that_does_not_parse_fails(tmp_path: Path, run_dir: Path) -> None:
    code, report, _ = _check(tmp_path, run_dir, _with("p4", sql="SELECT COUNT(* FROM x"))
    assert _checks(report, "p4") == {"C1"}
    assert code == 1


def test_c1_a_placeholder_without_an_example_value_fails(tmp_path: Path, run_dir: Path) -> None:
    document = _with("p4", sql=BLANKS.replace("${bizdate}", "${run_day}"))
    code, report, _ = _check(tmp_path, run_dir, document)
    assert _checks(report, "p4") == {"C1"}
    assert "${run_day}" in _findings(report)[0][2]


@pytest.mark.parametrize("sql", [
    f"DELETE FROM {DEMO_TABLE} WHERE dt = '20260101'",
    f"{BLANKS}; {BLANKS}",
    f"INSERT OVERWRITE TABLE {DEMO_TABLE} {BLANKS}",
])
def test_c2_anything_but_one_select_fails(tmp_path: Path, run_dir: Path, sql: str) -> None:
    code, report, _ = _check(tmp_path, run_dir, _with("p4", sql=sql))
    assert "C2" in _checks(report, "p4")
    assert code == 1


# ------------------------------------------------------------------ C3


def test_c3_a_column_the_packet_does_not_have_fails(tmp_path: Path, run_dir: Path) -> None:
    sql = BLANKS.replace("register_time", "registered_on")
    code, report, _ = _check(tmp_path, run_dir, _with("p4", sql=sql))
    assert _checks(report, "p4") == {"C3"}
    assert "registered_on" in _findings(report)[0][2]


def test_c3_a_table_outside_the_packet_fails(tmp_path: Path, run_dir: Path) -> None:
    sql = f"SELECT COUNT(*) AS n FROM {OTHER} WHERE dt = '${{bizdate}}'"
    code, report, _ = _check(tmp_path, run_dir, _with("p4", sql=sql, partitions=_part(OTHER)))
    assert "C3" in _checks(report, "p4")
    assert OTHER in " ".join(m for _, c, m in _findings(report) if c == "C3")


def test_c3_a_catalog_prefix_is_ignored(tmp_path: Path, run_dir: Path) -> None:
    sql = BLANKS.replace(f"FROM {DEMO_TABLE}", f"FROM some_catalog.{DEMO_TABLE}")
    code, report, _ = _check(tmp_path, run_dir, _with("p4", sql=sql))
    assert _findings(report) == []


# ------------------------------------------------------------------ C4


def test_c4_a_partitioned_table_read_without_a_partition_filter_fails(
    tmp_path: Path, run_dir: Path,
) -> None:
    sql = BLANKS.replace(" WHERE dt = '${bizdate}'", "")
    code, report, _ = _check(tmp_path, run_dir, _with("p4", sql=sql, partitions=[]))
    assert _checks(report, "p4") == {"C4"}


def test_c4_a_flagged_full_scan_passes_and_is_counted(tmp_path: Path, run_dir: Path) -> None:
    sql = BLANKS.replace(" WHERE dt = '${bizdate}'", "")
    document = _with("p4", sql=sql, partitions=[], full_scan="the task reads every partition")
    code, report, _ = _check(tmp_path, run_dir, document)
    assert _findings(report) == []
    assert report["summary"]["full_scans"] == 1
    assert code == 0


def test_c4_a_full_scan_flag_with_every_table_filtered_warns(tmp_path: Path, run_dir: Path) -> None:
    code, report, _ = _check(tmp_path, run_dir, _with("p4", full_scan="not needed"))
    assert _checks(report, "p4", "WARN") == {"C4"}
    assert code == 0


def test_c4_a_filtered_table_must_be_named_in_partitions(tmp_path: Path, run_dir: Path) -> None:
    code, report, _ = _check(tmp_path, run_dir, _with("p4", partitions=[]))
    assert _checks(report, "p4") == {"C4"}


def test_c4_partitions_must_name_a_partition_column_of_a_table_read(
    tmp_path: Path, run_dir: Path,
) -> None:
    partitions = _part() + [{"table": DEMO_TABLE, "column": "etl_time", "want": "x",
                             "fallback": "none"}]
    code, report, _ = _check(tmp_path, run_dir, _with("p4", partitions=partitions))
    assert _checks(report, "p4") == {"C4"}


# ------------------------------------------------------------------ C5


def test_c5_a_listed_sensitive_column_in_the_output_fails(tmp_path: Path, run_dir: Path) -> None:
    sql = (f"SELECT verify_status, COUNT(*) AS n FROM {DEMO_TABLE} WHERE dt = '${{bizdate}}' "
           "GROUP BY verify_status LIMIT 10")
    code, report, _ = _check(tmp_path, run_dir, _with("p4", sql=sql),
                             sensitive=("verify_status",))
    assert _checks(report, "p4") == {"C5"}


def test_c5_counting_a_sensitive_column_passes(tmp_path: Path, run_dir: Path) -> None:
    sql = (f"SELECT COUNT(DISTINCT verified_customer_no) AS n, "
           f"COUNT(CASE WHEN verified_customer_no IS NULL THEN 1 END) AS blank "
           f"FROM {DEMO_TABLE} WHERE dt = '${{bizdate}}'")
    code, report, _ = _check(tmp_path, run_dir, _with("p4", sql=sql))
    assert _findings(report) == []


def test_c5_a_qualified_name_in_the_list_blocks_the_input_column(
    tmp_path: Path, run_dir: Path,
) -> None:
    sql = (f"SELECT gender, COUNT(*) AS n FROM {INPUT} WHERE dt = '${{bizdate}}' "
           "GROUP BY gender LIMIT 10")
    code, report, _ = _check(tmp_path, run_dir,
                             _with("p4", sql=sql, partitions=_part(INPUT)),
                             sensitive=(f"some_catalog.{INPUT}.gender",))
    assert _checks(report, "p4") == {"C5"}


def test_c5_a_sensitive_column_renamed_in_a_subquery_still_fails(
    tmp_path: Path, run_dir: Path,
) -> None:
    sql = (f"SELECT x AS label FROM (SELECT verified_customer_no AS x FROM {DEMO_TABLE} "
           "WHERE dt = '${bizdate}') s LIMIT 5")
    code, report, _ = _check(tmp_path, run_dir, _with("p4", sql=sql))
    assert _checks(report, "p4") == {"C5"}


def test_c5_select_star_fails(tmp_path: Path, run_dir: Path) -> None:
    sql = f"SELECT * FROM {DEMO_TABLE} WHERE dt = '${{bizdate}}' LIMIT 5"
    code, report, _ = _check(tmp_path, run_dir, _with("p4", sql=sql))
    assert "C5" in _checks(report, "p4")


def test_c5_without_a_list_identifier_columns_are_blocked_and_one_warning_says_so(
    tmp_path: Path, run_dir: Path,
) -> None:
    sql = (f"SELECT customer_id, register_time FROM {DEMO_TABLE} WHERE dt = '${{bizdate}}' "
           "LIMIT 5")
    code, report, err = _check(tmp_path, run_dir, _with("p4", sql=sql), sensitive=None)
    assert _checks(report, "p4") == {"C5"}
    assert "customer_id" in _findings(report)[0][2]
    assert len(report["warnings"]) == 1
    assert "sensitive-columns.txt" in report["warnings"][0]
    assert report["sensitive"] is None


def test_c5_an_identifier_column_s_source_column_is_blocked_too(
    tmp_path: Path, run_dir: Path,
) -> None:
    sql = f"SELECT cust_no FROM {INPUT} WHERE dt = '${{bizdate}}' LIMIT 5"
    code, report, _ = _check(tmp_path, run_dir, _with("p4", sql=sql, partitions=_part(INPUT)),
                             sensitive=None)
    assert _checks(report, "p4") == {"C5"}


def test_c5_the_list_in_the_run_directory_is_read_by_default(tmp_path: Path, run_dir: Path) -> None:
    sql = (f"SELECT verify_status, COUNT(*) AS n FROM {DEMO_TABLE} WHERE dt = '${{bizdate}}' "
           "GROUP BY verify_status LIMIT 10")
    default = run_dir / "sensitive-columns.txt"
    default.write_text("verify_status\n", encoding="utf-8")
    try:
        code, report, err = _check(tmp_path, run_dir, _with("p4", sql=sql), sensitive=None)
    finally:
        default.unlink()
    assert _checks(report, "p4") == {"C5"}
    assert report["warnings"] == []
    assert report["sensitive"]["source"] == "default"
    assert "sensitive columns: " in err


# ------------------------------------------------------------------ C6


@pytest.mark.parametrize("sql", [
    (f"SELECT verify_status, COUNT(*) AS n FROM {DEMO_TABLE} WHERE dt = '${{bizdate}}' "
     "GROUP BY verify_status"),
    (f"SELECT verify_status, COUNT(*) AS n FROM {DEMO_TABLE} WHERE dt = '${{bizdate}}' "
     "GROUP BY verify_status LIMIT 60"),
    f"SELECT DISTINCT verify_status FROM {DEMO_TABLE} WHERE dt = '${{bizdate}}'",
    f"SELECT register_time FROM {DEMO_TABLE} WHERE dt = '${{bizdate}}'",
])
def test_c6_an_unbounded_list_fails(tmp_path: Path, run_dir: Path, sql: str) -> None:
    code, report, _ = _check(tmp_path, run_dir, _with("p4", sql=sql))
    assert _checks(report, "p4") == {"C6"}
    assert code == 1


def test_c6_a_value_set_may_take_51_rows_and_others_50(tmp_path: Path, run_dir: Path) -> None:
    sql = (f"SELECT verify_status, COUNT(*) AS n FROM {DEMO_TABLE} WHERE dt = '${{bizdate}}' "
           "GROUP BY verify_status LIMIT 51")
    code, report, _ = _check(tmp_path, run_dir, _with("p4", sql=sql))
    assert _checks(report, "p4") == {"C6"}
    code, report, _ = _check(tmp_path, run_dir, _with("p4", sql=sql, shape="value_set"))
    assert _findings(report) == []


# ------------------------------------------------------------------ C7


def test_c7_a_question_rewritten_since_fails(tmp_path: Path, run_dir: Path) -> None:
    code, report, _ = _check(tmp_path, run_dir, _with("p5", asked="an older wording"))
    assert _checks(report, "p5") == {"C7"}


def test_c7_whitespace_and_width_do_not_count(tmp_path: Path, run_dir: Path) -> None:
    code, report, _ = _check(tmp_path, run_dir, _with("p5", asked="  " + ASKED.replace("？", "?")))
    assert _findings(report) == []


def test_c7_a_question_the_document_does_not_have_fails(tmp_path: Path, run_dir: Path) -> None:
    code, report, _ = _check(tmp_path, run_dir, _with("p5", question="q9"))
    assert _checks(report, "p5") == {"C7"}


def test_c7_is_not_run_without_docs(tmp_path: Path, run_dir: Path) -> None:
    code, report, _ = _check(tmp_path, run_dir, _with("p5", asked="an older wording"), docs=False)
    assert _findings(report) == []
    assert "C7" not in report["summary"]["checks"]


# ------------------------------------------------------------------ C8


@pytest.mark.parametrize(("item_id", "changes"), [
    ("p4", {"sql": None}),
    ("p4", {"how_to_read": None}),
    ("p4", {"shape": None}),
    ("p5", {"note": None}),
    ("p5", {"sql": BLANKS}),
    ("p5", {"lands": "summary.row.observed"}),
])
def test_c8_an_item_missing_what_its_class_needs_fails(
    tmp_path: Path, run_dir: Path, item_id: str, changes: dict,
) -> None:
    code, report, _ = _check(tmp_path, run_dir, _with(item_id, **changes))
    assert _checks(report, item_id) == {"C8"}
    assert code == 1


def test_c8_two_items_with_one_id_fail(tmp_path: Path, run_dir: Path) -> None:
    code, report, _ = _check(tmp_path, run_dir, _with("p5", id="p4"))
    assert "C8" in {c for _, c, _ in _findings(report)}


def test_a_data_item_without_an_engine_warns(tmp_path: Path, run_dir: Path) -> None:
    code, report, _ = _check(tmp_path, run_dir, _with("p4", engine=None))
    assert _checks(report, "p4", "WARN") == {"engine"}
    assert code == 0


# ------------------------------------------------------------------ C9


@pytest.mark.parametrize("sql", [
    # the flat form, duplicate keys from a HAVING subquery as a scalar subquery
    (f"SELECT COUNT(*) AS rows, COUNT(DISTINCT customer_id) AS keys, "
     f"(SELECT COUNT(*) FROM (SELECT customer_id FROM {DEMO_TABLE} WHERE dt = '${{bizdate}}' "
     f"GROUP BY customer_id HAVING COUNT(*) > 1) d) AS duplicate_keys "
     f"FROM {DEMO_TABLE} WHERE dt = '${{bizdate}}'"),
    # the grouped form with COUNT_IF / FILTER / COUNT(CASE) / SUM(IF) / >= 2
    ("SELECT SUM(n) AS rows, COUNT(1) AS keys, COUNT_IF(n > 1) AS duplicate_keys FROM "
     f"(SELECT customer_id, COUNT(*) AS n FROM {DEMO_TABLE} WHERE dt = '${{bizdate}}' "
     "GROUP BY customer_id) g"),
    ("SELECT SUM(n) AS rows, COUNT(*) AS keys, COUNT(*) FILTER (WHERE n > 1) AS duplicate_keys "
     f"FROM (SELECT customer_id, COUNT(1) AS n FROM {DEMO_TABLE} WHERE dt = '${{bizdate}}' "
     "GROUP BY customer_id) g"),
    ("SELECT SUM(n) AS rows, COUNT(*) AS keys, "
     "COUNT(CASE WHEN n >= 2 THEN 1 END) AS duplicate_keys "
     f"FROM (SELECT customer_id, COUNT(*) AS n FROM {DEMO_TABLE} WHERE dt = '${{bizdate}}' "
     "GROUP BY customer_id) g"),
    ("SELECT SUM(n) AS rows, COUNT(*) AS keys, SUM(IF(1 < n, 1, 0)) AS duplicate_keys "
     f"FROM (SELECT customer_id, COUNT(*) AS n FROM {DEMO_TABLE} WHERE dt = '${{bizdate}}' "
     "GROUP BY customer_id) g"),
])
def test_c9_the_documented_uniqueness_forms_pass(tmp_path: Path, run_dir: Path, sql: str) -> None:
    code, report, _ = _check(tmp_path, run_dir, _with("p1", sql=sql))
    assert _findings(report) == []
    assert code == 0


@pytest.mark.parametrize("sql", [
    # renaming: the distinct count called rows, the row count called keys
    ("SELECT COUNT(DISTINCT customer_id) AS rows, COUNT(*) AS keys, "
     f"0 AS duplicate_keys FROM {DEMO_TABLE} WHERE dt = '${{bizdate}}'"),
    ROW_UNIQUE.replace("SUM(n) AS rows, COUNT(*) AS keys", "SUM(n) AS keys, COUNT(*) AS rows"),
    # surplus rows are not keys with more than one row
    ("SELECT COUNT(*) AS rows, COUNT(DISTINCT customer_id) AS keys, "
     "COUNT(*) - COUNT(DISTINCT customer_id) AS duplicate_keys "
     f"FROM {DEMO_TABLE} WHERE dt = '${{bizdate}}'"),
    # keys counted by one column, duplicates by another
    ("SELECT a.rows, a.keys, b.duplicate_keys FROM "
     f"(SELECT COUNT(*) AS rows, COUNT(DISTINCT customer_id) AS keys FROM {DEMO_TABLE} "
     "WHERE dt = '${bizdate}') a CROSS JOIN (SELECT COUNT(*) AS duplicate_keys FROM "
     f"(SELECT gender_cd FROM {DEMO_TABLE} WHERE dt = '${{bizdate}}' GROUP BY gender_cd "
     "HAVING COUNT(*) > 1) d) b"),
])
def test_c9_a_wrong_expression_under_a_fixed_name_fails(
    tmp_path: Path, run_dir: Path, sql: str,
) -> None:
    code, report, _ = _check(tmp_path, run_dir, _with("p1", sql=sql))
    assert _checks(report, "p1") == {"C9"}
    assert code == 1


def test_c9_other_output_names_fail(tmp_path: Path, run_dir: Path) -> None:
    sql = ROW_UNIQUE.replace("AS duplicate_keys", "AS dup_keys")
    code, report, _ = _check(tmp_path, run_dir, _with("p1", sql=sql))
    assert _checks(report, "p1") == {"C9"}
    assert "dup_keys" in _findings(report)[0][2]


def test_c9_an_extra_output_column_fails(tmp_path: Path, run_dir: Path) -> None:
    sql = VALUE_SET.replace("COUNT(*) AS cnt", "COUNT(*) AS cnt, MAX(dt) AS last_dt")
    code, report, _ = _check(tmp_path, run_dir, _with("p3", sql=sql))
    assert _checks(report, "p3") == {"C9"}


@pytest.mark.parametrize("sql", [
    VALUE_SET.replace("COUNT(*) AS cnt", "COUNT(DISTINCT verify_status) AS cnt"),
    VALUE_SET.replace("GROUP BY gender_cd", "GROUP BY gender_cd, verify_status"),
    VALUE_SET.replace("LIMIT 51", "LIMIT 50"),
    VALUE_SET.replace("ORDER BY", "HAVING COUNT(*) > 1 ORDER BY"),
    VALUE_SET.replace("gender_cd AS value", "verify_status AS value")
             .replace("GROUP BY gender_cd", "GROUP BY verify_status"),
])
def test_c9_a_value_set_off_its_form_fails(tmp_path: Path, run_dir: Path, sql: str) -> None:
    code, report, _ = _check(tmp_path, run_dir, _with("p3", sql=sql))
    assert _checks(report, "p3") == {"C9"}


def test_c9_a_value_set_may_read_the_column_s_source_column(tmp_path: Path, run_dir: Path) -> None:
    sql = (f"SELECT gender AS value, COUNT(*) AS cnt FROM {INPUT} WHERE dt = '${{bizdate}}' "
           "GROUP BY gender LIMIT 51")
    code, report, _ = _check(tmp_path, run_dir, _with("p3", sql=sql, partitions=_part(INPUT)))
    assert _findings(report) == []
    other = sql.replace("gender", "verify_flag")
    code, report, _ = _check(tmp_path, run_dir, _with("p3", sql=other, partitions=_part(INPUT)))
    assert _checks(report, "p3") == {"C9"}


@pytest.mark.parametrize(("item_id", "lands"), [
    ("p2", f"input:{OTHER}"),
    ("p3", "column:no_such_column.observed_values"),
    ("p4", "summary.row.observed"),  # a conditional count lands nowhere
    ("p1", f"input:{INPUT}"),  # it counts the table itself, not the input
])
def test_c9_a_target_the_query_cannot_land_on_fails(
    tmp_path: Path, run_dir: Path, item_id: str, lands: str,
) -> None:
    code, report, _ = _check(tmp_path, run_dir, _with(item_id, lands=lands))
    assert "C9" in _checks(report, item_id)
    assert code == 1


# ------------------------------------------------------------------ schema and exit codes


def test_a_file_off_the_schema_fails_with_its_errors(tmp_path: Path, run_dir: Path) -> None:
    document = _with("p4", outputs={"rows": "n"})
    code, report, _ = _check(tmp_path, run_dir, document)
    assert code == 1
    assert report["schema_errors"]
    assert report["schema_errors"][0]["at"] == "items[3]"


def test_inputs_that_cannot_be_read_exit_2(tmp_path: Path, run_dir: Path) -> None:
    probes = _probes(tmp_path, _good())
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        assert run("semantic", "probes", "check", tmp_path / "missing.json",
                   "--packets", run_dir / "packets") == 2
        assert run("semantic", "probes", "check", probes, "--packets", tmp_path / "nope") == 2
        assert run("semantic", "probes", "check", probes, "--packets", run_dir / "packets",
                   "--sensitive", tmp_path / "nope.txt") == 2
        assert run("semantic", "probes", "check", probes, "--packets", run_dir / "packets",
                   "--docs", tmp_path / "nope") == 2


def test_the_schema_is_a_valid_draft_7_schema() -> None:
    from jsonschema import Draft7Validator

    from scope_lineage.semantics.schema import PROBES_FORMAT, packaged_schema

    Draft7Validator.check_schema(packaged_schema(PROBES_FORMAT))


def test_the_documented_example_passes(tmp_path: Path, run_dir: Path) -> None:
    import re

    from .table_semantics_demo import ROOT

    text = (ROOT / "docs" / "en" / "table-semantics.md").read_text(encoding="utf-8")
    section = text[text.index("## `semantic probes check`"):]
    document = json.loads(re.search(r"```json\n(.*?)```", section, re.S).group(1))
    code, report, _ = _check(tmp_path, run_dir, document)
    assert _findings(report) == []
    assert code == 0


# ------------------------------------------------------------------ C9: what a landing query may stand for
#
# A value set read on an input column lands on the target column only when the target
# passes that one column through (one producer, that source alone, no CASE output, nothing
# computed, every step a direct projection) -- the rule check 3 compares observed values
# by. A column that only feeds a condition, or is recoded or computed, holds other values.

SOURCE_VALUES = (f"SELECT gender AS value, COUNT(*) AS cnt FROM {INPUT} WHERE dt = '${{bizdate}}' "
                 "GROUP BY gender LIMIT 51")


def _run_copy(tmp_path: Path, run_dir: Path, packet_edit=None, doc_edit=None) -> Path:
    """A copy of the run directory with the demo table's packet or document edited."""
    import shutil

    root = tmp_path / "edited-run"
    shutil.copytree(run_dir, root)
    for edit, path in ((packet_edit, root / "packets" / DEMO_TABLE / "packet.json"),
                       (doc_edit, root / "docs" / f"{DEMO_TABLE}.json")):
        if edit is not None:
            data = json.loads(path.read_text(encoding="utf-8"))
            edit(data)
            write_json(path, data)
    return root


def _producers(packet: dict, column: str) -> list[dict]:
    return next(entry["producers"] for entry in packet["lineage"]["columns"] if entry["column"] == column)


def _value_set_on(tmp_path: Path, run_dir: Path, sql: str, **edits):
    root = _run_copy(tmp_path, run_dir, **edits) if edits else run_dir
    return _check(tmp_path, root, _with("p3", sql=sql, partitions=_part(INPUT)))


def test_c9_a_direct_pass_through_source_still_lands(tmp_path: Path, run_dir: Path) -> None:
    code, report, _ = _value_set_on(tmp_path, run_dir, SOURCE_VALUES)
    assert _findings(report) == []
    assert code == 0


def test_c9_a_value_set_needs_no_docs_to_check_its_source(tmp_path: Path, run_dir: Path) -> None:
    item = _with("p3", sql=SOURCE_VALUES, partitions=_part(INPUT))
    code, report, _ = _check(tmp_path, run_dir, item, docs=False)
    assert _checks(report, "p3") == set() and _checks(report, "p3", "WARN") == set()


def test_c9_a_condition_column_listed_as_a_source_does_not_land(tmp_path: Path, run_dir: Path) -> None:
    def also_condition(document: dict) -> None:
        column = next(c for c in document["columns"] if c["column"] == "gender_cd")
        column["source_columns"] = [*column["source_columns"], f"{INPUT}.verify_flag"]

    sql = SOURCE_VALUES.replace("gender", "verify_flag")
    code, report, _ = _value_set_on(tmp_path, run_dir, sql, doc_edit=also_condition)
    assert _checks(report, "p3") == {"C9"}
    assert "condition column or a computed source" in _findings(report)[0][2]
    assert code == 1


def _second_producer(packet: dict) -> None:
    producers = _producers(packet, "gender_cd")
    producers.append(copy.deepcopy(producers[0]))


def _case_output(packet: dict) -> None:
    _producers(packet, "gender_cd")[0]["case_outputs"] = ["'U'"]


def _computed(packet: dict) -> None:
    _producers(packet, "gender_cd")[0]["computed_by"] = ["expression"]


@pytest.mark.parametrize("edit", [_second_producer, _case_output, _computed])
def test_c9_a_source_the_column_recodes_or_shares_does_not_land(
    tmp_path: Path, run_dir: Path, edit,
) -> None:
    code, report, _ = _value_set_on(tmp_path, run_dir, SOURCE_VALUES, packet_edit=edit)
    assert _checks(report, "p3") == {"C9"}
    assert "condition column or a computed source" in _findings(report)[0][2]


def test_check_3_and_c9_share_one_pass_through_rule() -> None:
    from scope_lineage.semantics import checks_observed, probes

    assert probes.passes_through is checks_observed.passes_through


# ------------------------------------------------------------------ C9: the task's own read conditions


DEDUP = ("SELECT SUM(n) AS rows, COUNT(*) AS keys, SUM(CASE WHEN n > 1 THEN 1 ELSE 0 END) AS duplicate_keys "
         "FROM (SELECT customer_id, COUNT(*) AS n FROM (SELECT customer_id, ROW_NUMBER() OVER "
         f"(PARTITION BY customer_id ORDER BY register_time DESC) AS rn FROM {DEMO_TABLE} "
         "WHERE dt = '${bizdate}') r WHERE rn = 1 GROUP BY customer_id) g")


@pytest.mark.parametrize("sql", [
    ROW_UNIQUE.replace("WHERE dt = '${bizdate}'", "WHERE dt = '${bizdate}' AND customer_id IS NOT NULL"),
    DEDUP,
])
def test_c9_a_landing_query_with_its_own_read_conditions_names_them_in_filter(
    tmp_path: Path, run_dir: Path, sql: str,
) -> None:
    code, report, _ = _check(tmp_path, run_dir, _with("p1", sql=sql))
    assert _checks(report, "p1") == {"C9"}
    assert "filter" in _findings(report)[0][2]
    code, report, _ = _check(tmp_path, run_dir, _with("p1", sql=sql, filter="customer_id IS NOT NULL"))
    assert _checks(report, "p1") == set()
    assert code == 0


def test_c9_a_conditioned_query_that_lands_nowhere_needs_no_filter(tmp_path: Path, run_dir: Path) -> None:
    sql = BLANKS.replace("WHERE dt", "WHERE gender_cd = 'F' AND dt")
    code, report, _ = _check(tmp_path, run_dir, _with("p4", sql=sql))
    assert _checks(report, "p4") == set()


def test_filter_is_one_line(tmp_path: Path, run_dir: Path) -> None:
    code, report, _ = _check(tmp_path, run_dir, _with("p1", filter="a IS NOT NULL\nAND b = 1"))
    assert report["schema_errors"] and code == 1


# ------------------------------------------------------------------ C9: fewer columns than the grain


def test_c9_counting_fewer_columns_than_the_grain_warns(tmp_path: Path, run_dir: Path) -> None:
    def wider_grain(document: dict) -> None:
        document["summary"]["row"]["grain_columns"] = ["customer_id", "gender_cd"]

    root = _run_copy(tmp_path, run_dir, doc_edit=wider_grain)
    code, report, _ = _check(tmp_path, root, _good())
    assert _checks(report, "p1") == set()
    warnings = [message for id_, check, message in _findings(report, "WARN") if id_ == "p1"]
    assert len(warnings) == 1 and "customer_id, gender_cd" in warnings[0]
    assert "says nothing" in warnings[0]
    assert code == 0
    code, report, _ = _check(tmp_path, run_dir, _good())
    assert _findings(report, "WARN") == []
