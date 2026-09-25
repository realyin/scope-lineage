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
