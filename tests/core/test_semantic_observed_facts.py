"""``semantic facts`` prints what platform queries observed, after what people confirmed.

Each observation is one line that says it is an observation, where it was made and by
which query: 「观测：<对象>在分区 … 内（查询 …，… 执行，N 行）…」. A row or an input
table's uniqueness names the columns the query counted and never says 「唯一」 outright;
when those columns are not the document's grain columns the line says so. A column's
observation lists its values with their counts, whether that is all of them, and the
values asked about and not seen. Without any observation the text is what it always was.
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

from scope_lineage.semantics.confirmed import read_confirmations, render_facts

from .table_semantics_demo import CONFIRMATIONS, DEMO_TABLE, example, read_json, run, write_json
from .test_semantic_observed import ALL, INPUT, _entry, _file, _grain, _input, _values


def _facts(tmp_path: Path, *entries: dict, grains=None) -> list[str]:
    confirmations = read_confirmations(_file(tmp_path / "c.json", *entries))
    return render_facts(confirmations, [DEMO_TABLE], grains=grains).splitlines()


def _observed(lines: list[str]) -> list[str]:
    return [line for line in lines if line.startswith("- 观测：")]


def test_facts_print_the_three_kinds_of_observation_after_the_confirmed_facts(
    tmp_path: Path,
) -> None:
    entries = read_json(CONFIRMATIONS)["confirmations"]
    plain = render_facts(read_confirmations(CONFIRMATIONS), [DEMO_TABLE]).splitlines()
    lines = _facts(tmp_path, *entries, *ALL)
    assert lines[:len(plain)] == plain
    row, column, first, second = lines[len(plain):]
    assert row == (
        "- 观测：本表在分区 dt=20261119 内（查询 probe_1，2026-11-20 执行，120 行）"
        "按 (customer_id) 计数无重复（120 个键）；只说明这些分区，不是定义"
        "（demo-reviewer 于 2026-11-21 记录）")
    assert column == (
        "- 观测：列 gender_cd 在分区 dt=20261119 内（查询 probe_1，2026-11-20 执行，120 行，"
        f"取自 {INPUT}.gender）出现 F（60 行）、M（50 行）、X（10 行），已列全；"
        "没有出现 U；去重 3 个、空值 0 个；观测不给含义，不是码值表"
        "（demo-reviewer 于 2026-11-21 记录）")
    assert first == (
        f"- 观测：输入表 {INPUT} 在分区 dt=20261119 内（查询 probe_1，2026-11-20 执行，120 行）"
        "按 (cust_no) 计数无重复（120 个键）；按这几列关联它时在该分区内不放大，"
        "别的分区没观测（demo-reviewer 于 2026-11-21 记录）")
    assert "按 (verified_no) 计数无重复" in second
    for line in (row, column, first, second):
        assert "唯一" not in line


def test_a_table_with_observations_only_has_facts(tmp_path: Path) -> None:
    lines = _facts(tmp_path, *ALL)
    assert lines[0] == f"表 {DEMO_TABLE} 已确认的事实："
    assert len(_observed(lines)) == 4 and "无" not in lines


def test_counted_columns_other_than_the_grain_are_said(tmp_path: Path) -> None:
    entry = _entry("summary.row.observed", _grain())
    (same,) = _observed(_facts(tmp_path, entry, grains={DEMO_TABLE: ["customer_id"]}))
    assert "行粒度列" not in same
    (wider,) = _observed(_facts(tmp_path, entry, grains={DEMO_TABLE: ["customer_id", "dt"]}))
    assert "按 (customer_id) 计数无重复（120 个键）；计数列 (customer_id) 不是文档的行粒度列 " \
           "(customer_id, dt)；只说明这些分区" in wider


def test_duplicates_ranges_fallbacks_and_filters_are_said(tmp_path: Path) -> None:
    ranged = {"partition": {"column": "dt", "from": "20261116", "to": "20261122", "count": 7},
              "requested": "20261123", "filter": "status = '1'", "within": "all_observed"}
    (row,) = _observed(_facts(tmp_path, _entry(
        "summary.row.observed", _grain(unique="no", duplicate_keys=3, **ranged))))
    assert row.startswith(
        "- 观测：本表在分区 dt 20261116–20261122 共 7 个分区内（查询 probe_1，原定 20261123，"
        "回退到最近可用分区，条件 status = '1'，2026-11-20 执行，120 行）"
        "按 (customer_id) 计数有重复（120 个键里 3 个重复），所有观测分区合起来计数；")
    (whole,) = _observed(_facts(tmp_path, _entry(
        f"input:{INPUT}", _input(unique="no", duplicate_keys=2,
                                 partition={"column": None}))))
    assert "在全表内（" in whole and "按这几列关联它时会放大行数" in whole


def test_an_identifier_or_partial_observation_gives_what_it_has(tmp_path: Path) -> None:
    counts = {"query": "probe_1", "on": "2026-11-20", "rows": 120,
              "partition": {"column": "dt", "values": ["20261118", "20261119"]},
              "complete": False, "distinct": 120, "nulls": 0}
    (line,) = _observed(_facts(tmp_path, _entry("column:customer_id.observed_values", counts)))
    assert line == (
        "- 观测：列 customer_id 在分区 dt 20261118、20261119 内（查询 probe_1，2026-11-20 执行，"
        "120 行）只给计数：去重 120 个、空值 0 个；观测不给含义，不是码值表"
        "（demo-reviewer 于 2026-11-21 记录）")
    (partial,) = _observed(_facts(tmp_path, _entry(
        "column:gender_cd.observed_values", _values(complete=False, absent=[]))))
    assert "，未列全；" in partial and "没有出现" not in partial


def test_facts_read_the_grain_from_the_documents(tmp_path: Path) -> None:
    document = example()
    document["summary"]["row"]["grain_columns"] = ["customer_id", "dt"]
    write_json(tmp_path / "semantics" / f"{DEMO_TABLE}.json", document)
    file = _file(tmp_path / "c.json", _entry("summary.row.observed", _grain()))
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert run("semantic", "facts", "--confirmations", file, "--table", DEMO_TABLE,
                   "--documents", tmp_path / "semantics") == 0
    assert "不是文档的行粒度列 (customer_id, dt)" in buffer.getvalue()


def test_without_observations_facts_are_byte_identical(tmp_path: Path) -> None:
    entries = read_json(CONFIRMATIONS)["confirmations"]
    copy = _file(tmp_path / "c.json", *entries)
    for grains in (None, {DEMO_TABLE: ["customer_id", "dt"]}):
        assert render_facts(read_confirmations(copy), [DEMO_TABLE], grains=grains) == \
            render_facts(read_confirmations(CONFIRMATIONS), [DEMO_TABLE])
    assert render_facts(None, [DEMO_TABLE], grains={DEMO_TABLE: ["x"]}) == "无\n"
