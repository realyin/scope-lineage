"""A packet built from a task's template shows its scheduling parameters, and reads the SQL
the lineage was read from.

``semantic packet --tasks`` reads each task JSON again. It does not decide on its own
which SQL to take: the task's lineage says whether ``parse`` read the template (the
``task_template_sql_used`` warning), so the packet's SQL is the text the lineage was built
from -- the template with its table-name parameters bound. A lineage without that warning
(parsed before templates were read, or with ``parse --instance-sql``) gets the run instance,
exactly as before.

Section 2 then lists each parameter the SQL still holds with its definition as given,
how many times it appears, the user's own description when there is one, the bound
table-name parameters apart, and "no definition given" for a parameter the list lacks. A
parameter left only in a comment is not listed. All names are synthetic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .table_semantics_demo import read_json, run, write_json

TEMPLATE = """-- reads ${db}.src_known and ${only_in_comment}
INSERT OVERWRITE TABLE ${db}.out PARTITION (dt = '${dt}')
SELECT a.id, b.name, '${run_hour}' AS hour_tag, '${dt}' AS biz_dt
FROM ${db}.src_known a
JOIN (SELECT id, name FROM demo_ods.src_unknown
      WHERE dt = '${dt}' AND status = 1) b ON a.id = b.id
WHERE a.dt = '${dt}' AND a.order_date >= '2026-01-01'"""
VALUES = {"${db}": "demo_mart", "${dt}": "20260102", "${run_hour}": "08",
          "${only_in_comment}": "x"}
PARAMETERS = [
    {"paramKey": "dt", "paramValue": "[yyyyMMdd-1D]", "description": "the business day"},
    {"paramKey": "db", "paramValue": "demo_mart"},
    {"paramKey": "only_in_comment", "paramValue": "[HH]"},
]


def _instance() -> str:
    sql = TEMPLATE
    for slot, value in VALUES.items():
        sql = sql.replace(slot, value)
    return sql


def _column(name: str, index: int, partition: int = 0) -> dict:
    return {"columnName": name, "columnType": "string", "columnComment": name,
            "columnIndex": index, "isPartition": partition}


SCHEMA = {"tables": [
    {"table_name": "demo_mart.src_known", "table_desc": "known", "is_partition": 1,
     "schema": [_column("id", 0), _column("order_date", 1), _column("dt", 2, partition=1)]},
    {"table_name": "demo_mart.out", "table_desc": "out", "is_partition": 1,
     "schema": [_column("id", 0), _column("name", 1), _column("hour_tag", 2),
                _column("biz_dt", 3), _column("dt", 4, partition=1)]},
]}
TABLE = "demo_mart.out"


def _build(work: Path, meta: dict, *parse_flags: str, tasks_meta: dict | None = None) -> Path:
    """Parse the task described by ``meta`` and pack it, with ``--tasks`` holding
    ``tasks_meta`` (``meta`` when not given); the packet directory."""
    corpus, packed_tasks = work / "corpus", work / "packed_tasks"
    task = {"task_name": "out_daily", "expect_date": "2026-01-03"}
    write_json(corpus / "out_daily.json", {"meta": {**task, **meta}})
    write_json(packed_tasks / "out_daily.json", {"meta": {**task, **(tasks_meta or meta)}})
    write_json(work / "schema.json", SCHEMA)
    assert run("parse", "--input-dir", corpus, "--schema", work / "schema.json",
               "--out", work / "lineage", "--allow-partial", *parse_flags) == 0
    assert run("semantic", "packet", "--lineage", work / "lineage", "--tasks", packed_tasks,
               "--schema", work / "schema.json", "--out", work / "packets") == 0
    return work / "packets"


TEMPLATE_META = {"sql": _instance(), "task_sql": TEMPLATE, "task_parameters": PARAMETERS}


@pytest.fixture(scope="module")
def templated(tmp_path_factory) -> Path:
    return _build(tmp_path_factory.mktemp("templated"), TEMPLATE_META)


def _task(packets: Path) -> dict:
    [task] = read_json(packets / TABLE / "packet.json")["tasks"]
    return task


def _markdown(packets: Path) -> str:
    return (packets / TABLE / "packet.md").read_text(encoding="utf-8")


def _files(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*")) if path.is_file()}


def test_the_packet_quotes_the_sql_the_lineage_was_read_from(templated: Path) -> None:
    sql = _task(templated)["sql"]

    assert "demo_mart.out PARTITION (dt = '${dt}')" in sql
    assert "FROM demo_mart.src_known a" in sql
    assert "-- reads ${db}.src_known" in sql  # the comment is left as written


def test_the_packet_lists_the_scheduling_parameters(templated: Path) -> None:
    assert _task(templated)["scheduling_parameters"] == {
        "in_sql": [
            {"name": "dt", "definition": "[yyyyMMdd-1D]", "count": 4,
             "description": "the business day"},
            {"name": "run_hour", "definition": None, "count": 1},
        ],
        "bound": [{"name": "db", "definition": "demo_mart", "count": 2}],
    }


def test_the_markdown_says_them_after_the_expected_date(templated: Path) -> None:
    lines = _markdown(templated).splitlines()
    at = next(i for i, line in enumerate(lines) if line.startswith("- 期望日期："))

    assert lines[at + 1] == (
        "- 调度参数（定义照参数表原样）：`${dt}` = `[yyyyMMdd-1D]`（说明：the business day） ×4；"
        "`${run_hour}`（参数表未给定义） ×1；"
        "已代入表名的参数：`${db}` = `demo_mart` ×2"
    )
    assert "only_in_comment" not in lines[at + 1]


def test_a_parameter_equality_on_an_input_of_unknown_partitioning_is_its_own_shape(
    templated: Path,
) -> None:
    packet = read_json(templated / TABLE / "packet.json")
    [unknown] = [item for item in packet["inputs"] if item["table"] == "demo_ods.src_unknown"]

    assert [(f["column"], f["shape"]) for f in unknown["date_filters"]] == [
        ("dt", "parameter_equality")]
    assert "（等于调度参数" in _markdown(templated)


def test_an_input_with_metadata_keeps_its_shapes(templated: Path) -> None:
    packet = read_json(templated / TABLE / "packet.json")
    [known] = [item for item in packet["inputs"] if item["table"] == "demo_mart.src_known"]

    assert known["partition_filters"] == ["`a`.`dt` = '${dt}'"]
    assert [(f["column"], f["shape"]) for f in known["date_filters"]] == [("order_date", "cutoff")]


def test_the_instance_switch_packs_what_a_task_json_without_a_template_packs(tmp_path) -> None:
    switched = _build(tmp_path / "switched", TEMPLATE_META, "--instance-sql")
    plain = _build(tmp_path / "plain", {"sql": _instance()})

    assert _files(switched) == _files(plain)


def test_a_lineage_without_the_template_warning_packs_the_instance(tmp_path) -> None:
    old_lineage = _build(tmp_path / "old", {"sql": _instance()}, tasks_meta=TEMPLATE_META)
    plain = _build(tmp_path / "plain", {"sql": _instance()})

    assert _files(old_lineage) == _files(plain)


def test_with_the_instance_there_is_no_parameter_line(tmp_path) -> None:
    plain = _build(tmp_path / "plain", {"sql": _instance()})

    assert "scheduling_parameters" not in _task(plain)
    assert "调度参数" not in _markdown(plain)
    assert json.dumps(_task(plain)).count("${") == 0


# ----------------------------------------------- a template's literals are fixed values
#
# A date literal in a run instance may be a parameter the scheduler replaced, so its offset
# from the expected run date is a clue. In a template nothing was replaced: a literal there
# is a fixed value, so the packet says so and gives no offset. The run instance is unchanged.

OFFSET_WORDS = ("期望日期 −", "期望日期 +", "期望日期当天", "不在期望日期前后一个月内")
FAR = TEMPLATE.replace("'2026-01-01'", "'2026-01-01' AND a.order_date < '2030-06-30'")


def test_a_templates_date_literals_carry_no_offset(templated: Path) -> None:
    assert _task(templated)["date_literals"] == [{"literal": "'2026-01-01'", "count": 1}]
    assert _task(templated)["sql_from_template"] is True


def test_the_markdown_calls_a_templates_literal_fixed_with_no_offset(templated: Path) -> None:
    text = _markdown(templated)
    assert ("- 期望日期：2026-01-03；写死的日期字面量（模板里没有被参数替换，不随运行日变化）："
            "`'2026-01-01'` ×1") in text
    assert "写死的日期字面量 '2026-01-01'" in text  # the note beside the rule
    for words in OFFSET_WORDS:
        assert words not in text
    assert "SQL 里没有 `${…}` 参数" not in text


def test_a_literal_far_from_the_expected_date_is_fixed_too(tmp_path) -> None:
    packets = _build(tmp_path, {**TEMPLATE_META, "task_sql": FAR})
    assert _task(packets)["date_literals"] == [
        {"literal": "'2026-01-01'", "count": 1}, {"literal": "'2030-06-30'", "count": 1},
    ]
    for words in OFFSET_WORDS:
        assert words not in _markdown(packets)


def test_the_same_sql_as_a_run_instance_keeps_its_offsets(tmp_path) -> None:
    plain = _build(tmp_path, {"sql": _instance()})
    assert {item["literal"]: item["days_from_expect_date"]
            for item in _task(plain)["date_literals"]} == {"'20260102'": -1, "'2026-01-01'": -2}
    assert "sql_from_template" not in _task(plain)
    assert "（期望日期 −2 天）" in _markdown(plain)


def test_a_template_without_an_expected_date_adds_no_empty_line(tmp_path) -> None:
    packets = _build(tmp_path, {**TEMPLATE_META, "expect_date": None})
    lines = _markdown(packets).splitlines()
    assert "-" not in [line.strip() for line in lines]
    assert not any(line.startswith("- 期望日期") for line in lines)
    assert any(line.startswith("- 调度参数") for line in lines)


def test_a_template_with_no_parameter_left_says_it_is_a_template(tmp_path) -> None:
    """No ``${…}`` left and none bound: still the template, not a run instance."""
    fixed = _instance()
    packets = _build(tmp_path, {"sql": fixed, "task_sql": fixed, "task_parameters": PARAMETERS})
    task = _task(packets)
    assert task["sql_from_template"] is True and "scheduling_parameters" not in task
    text = _markdown(packets)
    assert "- 期望日期：2026-01-03；SQL 取自调度模板，没有参数；写死的日期字面量" in text
    assert "SQL 里没有 `${…}` 参数" not in text
    for words in OFFSET_WORDS:
        assert words not in text
