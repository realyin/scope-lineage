"""Check 5 compares a quoted rule, a lineage filter and the task SQL in one space.

A document quotes the script as written; the lineage renders each predicate through
SQLGlot (``nvl`` -> ``COALESCE``, ``substr`` -> ``SUBSTRING``, ``is not null`` ->
``NOT … IS NULL``) and may resolve a derived table's column to the expression behind it.
Each case below is one such rewrite: before the shared comparison, either the filter went
uncited or the quoted SQL was not found. All names are synthetic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.semantics.checks_context import check_rules

from .table_semantics_demo import run

SCRIPT = """INSERT OVERWRITE TABLE demo_dwd.dwd_probe_order_df PARTITION (dt = '${bizdate}')
SELECT a.order_id, a.amount, b.shop_name
FROM (
    SELECT order_id, amount, order_status, shop_id, order_name,
           DATE_FORMAT(time_inst, 'yyyyMMdd') AS dt
    FROM demo_ods.ods_probe_order_di
) a
LEFT JOIN demo_ods.ods_probe_shop_df b
  ON nvl(a.shop_id, '') = b.shop_id AND b.dt = '${bizdate}'
WHERE nvl(a.order_status, 0) = 1
  AND substr(a.order_name, 1, 2) = 'AB'
  AND a.amount is not null
  AND a.dt = '${bizdate}'
"""


def _packet(*filters: str) -> dict:
    return {
        "tasks": [{"sql": SCRIPT}],
        "lineage": {
            "rules": [
                {"kind": "filter", "partition_filter": False, "expression": text,
                 "task": "dwd_probe_order_daily"}
                for text in filters
            ]
        },
    }


def _document(*quoted: str) -> dict:
    rules = [
        {"id": f"r{n}", "kind": "filter", "text": "…", "sql": text, "sources": ["sql"]}
        for n, text in enumerate(quoted, 1)
    ]
    return {"rules": rules, "summary": {"scope": []}}


def _failures(document: dict, packet: dict) -> list[dict]:
    return [r for r in check_rules(document, packet) if r["status"] != "pass"]


@pytest.mark.parametrize(
    ("lineage", "quoted"),
    [
        ("COALESCE(`a`.`order_status`, 0) = 1", "nvl(a.order_status, 0) = 1"),
        ("SUBSTRING(`a`.`order_name`, 1, 2) = 'AB'", "AND substr(a.order_name, 1, 2) = 'AB'"),
        ("NOT `a`.`amount` IS NULL", "a.amount is not null"),
        ("DATE_FORMAT(`time_inst`, 'yyyyMMdd') = '${bizdate}'", "WHERE a.dt = '${bizdate}'"),
    ],
    ids=["nvl-coalesce", "substr-substring", "is-not-null", "aliased-partition-column"],
)
def test_a_filter_rendered_by_the_lineage_is_cited_by_the_raw_quote(lineage, quoted) -> None:
    assert _failures(_document(quoted), _packet(lineage)) == []


@pytest.mark.parametrize(
    "quoted",
    [
        "COALESCE(a.order_status, 0) = 1",
        "SUBSTRING(a.order_name, 1, 2) = 'AB'",
        "NOT a.amount IS NULL",
        "ON COALESCE(a.shop_id, '') = b.shop_id",
    ],
)
def test_a_quote_in_the_lineage_spelling_is_found_in_the_script(quoted) -> None:
    assert _failures(_document(quoted), _packet()) == []


def test_an_aliased_column_quoted_as_its_expression_is_found() -> None:
    document = _document("DATE_FORMAT(time_inst, 'yyyyMMdd') = '${bizdate}'")
    assert _failures(document, _packet()) == []


def test_a_quote_that_is_not_in_the_script_still_fails() -> None:
    (problem,) = _failures(_document("nvl(a.order_status, 0) = 2"), _packet())
    assert problem["at"] == "rules[0].sql"


def test_an_uncited_filter_still_fails() -> None:
    packet = _packet("COALESCE(`a`.`order_status`, 0) = 1", "NOT `a`.`amount` IS NULL")
    (problem,) = _failures(_document("a.amount is not null"), packet)
    assert problem["at"] == "rules"
    assert "COALESCE(a.order_status, 0) = 1" in problem["message"]


def test_a_quote_citing_one_conjunct_does_not_cite_its_neighbours() -> None:
    packet = _packet("SUBSTRING(`a`.`order_name`, 1, 2) = 'AB'")
    (problem,) = _failures(_document("WHERE a.dt = '${bizdate}'"), packet)
    assert problem["at"] == "rules"


def test_a_fragment_sqlglot_cannot_parse_falls_back_to_the_text() -> None:
    assert _failures(_document("AND a.amount is not null AND a.dt ="), _packet()) == []
    (problem,) = _failures(_document("AND a.amount is not nul AND"), _packet())
    assert problem["at"] == "rules[0].sql"


def test_a_script_sqlglot_cannot_parse_keeps_the_text_match() -> None:
    packet = _packet("COALESCE(`a`.`order_status`, 0) = 1")
    packet["tasks"][0]["sql"] = "SELECT FROM WHERE nvl(a.order_status, 0) = 1 ((("
    assert _failures(_document("nvl(a.order_status, 0) = 1"), packet) == []


# ------------------------------------------------------------------ citing is equality (B-V3)

# The same predicate text in a CASE branch, a MERGE condition and a WHERE: a quote of one
# place cites only a filter equal to the quote or to one of its conjuncts, never a filter
# that merely occurs inside the longer quote.
ELSEWHERE = """INSERT OVERWRITE TABLE demo_dwd.dwd_probe_order_df PARTITION (dt = '${bizdate}')
SELECT a.order_id, case when a.order_status = 9 then 1 end AS closed
FROM demo_ods.ods_probe_order_di a
WHERE a.order_status = 9;
MERGE INTO demo_dwd.dwd_probe_flag_df t
USING (SELECT order_id, flag FROM demo_ods.ods_probe_flag_di x WHERE x.flag = 'Y') s
ON t.order_id = s.order_id
WHEN MATCHED AND t.flag = 'Y' THEN UPDATE SET t.flag = s.flag
"""


def _elsewhere(*filters: str) -> dict:
    packet = _packet(*filters)
    packet["tasks"][0]["sql"] = ELSEWHERE
    return packet


def test_a_case_branch_quote_does_not_cite_the_where_filter_it_contains() -> None:
    packet = _elsewhere("`a`.`order_status` = 9")
    (problem,) = _failures(_document("case when a.order_status = 9 then 1 end"), packet)
    assert problem["at"] == "rules"
    assert _failures(_document("WHERE a.order_status = 9"), packet) == []


def test_a_merge_condition_quote_does_not_cite_the_where_filter_it_contains() -> None:
    packet = _elsewhere("`x`.`flag` = 'Y'")
    (problem,) = _failures(_document("when matched and t.flag = 'Y' then update set"), packet)
    assert problem["at"] == "rules"


def test_a_quote_of_two_conjuncts_cites_each_of_them() -> None:
    packet = _packet("NOT `a`.`amount` IS NULL", "DATE_FORMAT(`time_inst`, 'yyyyMMdd') = '${bizdate}'")
    document = _document("where a.amount is not null and a.dt = '${bizdate}'")
    assert _failures(document, packet) == []


def test_a_conjunct_s_trailing_comment_does_not_stop_it_citing() -> None:
    packet = _packet("NOT `a`.`amount` IS NULL")
    document = _document("a.amount is not null -- 金额非空\n and a.dt = '${bizdate}'")
    assert not [p for p in _failures(document, packet) if p["at"] == "rules"]


def test_a_quote_sqlglot_cannot_parse_whole_cites_by_its_top_level_conjuncts() -> None:
    packet = _packet("NOT `a`.`amount` IS NULL")
    document = _document("a.amount is not null AND a.dt = ((")
    assert not [p for p in _failures(document, packet) if p["at"] == "rules"]


# ------------------------------------------------------------------ whole-statement quotes

# A quote may copy a whole statement -- ``select … where a and b``, a FROM-led query, an
# INSERT … SELECT. The predicates in its own WHERE / HAVING / ON, nested subqueries
# included, are in the quote as written, so each conjunct cites the filter it equals; a
# CASE branch in its select list is still no WHERE and cites nothing.
STATEMENTS = """INSERT OVERWRITE TABLE demo_dwd.dwd_probe_order_df PARTITION (dt = '${bizdate}')
SELECT a.order_id FROM (
    SELECT * FROM demo_tmp.tmp_probe_step WHERE dt = '${bizdate}' AND src_kind = 'K1'
) a
LEFT JOIN (
    SELECT * FROM (SELECT * FROM demo_ods.ods_probe_role_df WHERE role_kind = 'R2') x
    WHERE x.lvl = 3
) b ON a.order_id = b.order_id
"""


def _statements(*filters: str) -> dict:
    packet = _packet(*filters)
    packet["tasks"][0]["sql"] = STATEMENTS
    return packet


def _rule_failures(quote: str, packet: dict) -> list[dict]:
    return [p for p in _failures(_document(quote), packet) if p["at"] == "rules"]


@pytest.mark.parametrize(
    ("lineage", "quoted"),
    [
        ("`tmp_probe_step`.`src_kind` = 'K1'",
         "select * from demo_tmp.tmp_probe_step where dt = '${bizdate}' and src_kind = 'K1'"),
        ("`tmp_probe_step`.`src_kind` = 'K1'",
         "FROM demo_tmp.tmp_probe_step WHERE src_kind = 'K1'"),
        ("`ods_probe_role_df`.`role_kind` = 'R2'",
         "SELECT * FROM (SELECT * FROM demo_ods.ods_probe_role_df WHERE role_kind = 'R2') x"
         " WHERE x.lvl = 3"),
        ("`tmp_probe_step`.`src_kind` = 'K1'",
         "insert overwrite table demo_dwd.dwd_probe_order_df"
         " select * from demo_tmp.tmp_probe_step where src_kind = 'K1'"),
    ],
    ids=["whole-select", "from-led", "nested-where", "insert-select"],
)
def test_a_whole_statement_quote_cites_the_conjuncts_of_its_own_where(lineage, quoted) -> None:
    assert _rule_failures(quoted, _statements(lineage)) == []


def test_a_whole_statement_quote_cites_its_join_condition() -> None:
    packet = _statements("`x`.`lvl` = 3")
    quote = ("select * from demo_tmp.tmp_probe_step a left join demo_ods.ods_probe_role_df x"
             " on a.order_id = x.order_id and x.lvl = 3")
    assert _rule_failures(quote, packet) == []


def test_a_case_branch_in_a_quoted_select_list_cites_nothing() -> None:
    packet = _statements("`tmp_probe_step`.`src_kind` = 'K1'")
    quote = "select case when src_kind = 'K1' then 1 end from demo_tmp.tmp_probe_step"
    (problem,) = _rule_failures(quote, packet)
    assert "src_kind" in problem["message"]


# ------------------------------------------------------------------ end to end


def _columns(names, partitions=("dt",)):
    return [
        {"columnName": name, "columnType": "string", "columnComment": name,
         "columnIndex": index, "isPartition": int(name in partitions)}
        for index, name in enumerate(names)
    ]


def test_validate_passes_raw_quotes_against_a_parsed_corpus(tmp_path: Path, capsys) -> None:
    tasks, schema = tmp_path / "tasks", tmp_path / "schema.json"
    tasks.mkdir()
    (tasks / "probe.json").write_text(json.dumps({"meta": {
        "task_id": "probe-1", "task_name": "dwd_probe_order_daily", "task_type": "Spark SQL",
        "schedule_cycle": "day", "description": "Synthetic probe.", "sql": SCRIPT,
    }}), encoding="utf-8")
    schema.write_text(json.dumps({"tables": [
        {"table_name": "demo_ods.ods_probe_order_di", "is_partition": 1, "schema": _columns(
            ["order_id", "amount", "order_status", "shop_id", "order_name", "time_inst", "dt"])},
        {"table_name": "demo_ods.ods_probe_shop_df", "is_partition": 1,
         "schema": _columns(["shop_id", "shop_name", "dt"])},
        {"table_name": "demo_dwd.dwd_probe_order_df", "is_partition": 1,
         "schema": _columns(["order_id", "amount", "shop_name", "dt"])},
    ]}), encoding="utf-8")
    assert run("parse", "--input-dir", tasks, "--schema", schema, "--out", tmp_path / "lin") == 0
    packets = tmp_path / "packets"
    assert run("semantic", "packet", "--lineage", tmp_path / "lin", "--tasks", tasks,
               "--schema", schema, "--out", packets) == 0
    packet = json.loads(
        (packets / "demo_dwd.dwd_probe_order_df" / "packet.json").read_text(encoding="utf-8")
    )
    document = _document(
        "nvl(a.order_status, 0) = 1",
        "substr(a.order_name, 1, 2) = 'AB'",
        "a.amount is not null",
        "a.dt = '${bizdate}'",
        "ON nvl(a.shop_id, '') = b.shop_id AND b.dt = '${bizdate}'",
    )

    assert _failures(document, packet) == []
