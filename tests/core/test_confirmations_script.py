"""The skill's write-back script must turn answers into files the tools read back.

``skills/scope-lineage/scripts/confirmations.py`` is the human half of WI-2.6: the
business owner answers the 待确认清单 in place, and this script routes each answer into
``glossary.overrides.json`` or ``metadata-patch.json`` by the item's own 回写目标 line.
The tests run it the way a person would -- as a subprocess over a real profile file --
and pin what must not go wrong: an unanswered item is not an empty answer, an answer must
land in the file that owns its kind, and merging must never overwrite what somebody else
already confirmed.

The profile fragments here are synthetic (`mart.orders`, `pay_status`), for the same
reason every other fixture in this repository is.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "skills" / "scope-lineage" / "scripts" / "confirmations.py"

PROFILE = """# 业务画像

## 三、待确认清单

共 4 条（≤ 15），按影响排序。

Q1.（优先）`pay_status = 'PAID'` 里的 PAID 指什么状态？
- 证据：semantic.json fields[1].value_domain[0]
- 候选答案：已支付 / 已结算
- 回写目标：值域:pay_status='PAID'
- 影响：影响口径理解
- 答案：已支付并已入账

Q2. 目标表 `mart.orders` 的 `pay_status` 列表示什么？
- 证据：output_tables 无列注释
- 候选答案：无候选
- 回写目标：字段注释:mart.orders.pay_status
- 影响：影响数值正确性
- 答案：订单的支付状态

Q3. `mart.orders` 这张表业务上叫什么？
- 证据：table_metadata 为空
- 候选答案：无候选
- 回写目标：表注释:mart.orders
- 影响：影响命名
- 答案：订单结果表

Q4. 「核销」在本任务里指什么？
- 证据：SQL 注释
- 候选答案：无候选
- 回写目标：术语:核销
- 影响：影响口径理解
- 答案：（待填）

## 附录：证据与生成记录

| 文件 | 是否读取 |
| --- | --- |
"""


def _profile(tmp_path: Path, body: str = PROFILE) -> Path:
    path = tmp_path / "business_profile.md"
    path.write_text(body, encoding="utf-8")
    return path


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True
    )


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_apply_routes_each_answer_into_the_file_that_owns_it(tmp_path: Path) -> None:
    profile = _profile(tmp_path)

    result = _run("apply", str(profile), "--by", "owner", "--date", "2026-09-19")

    assert result.returncode == 0, result.stderr
    overrides = _json(tmp_path / "glossary.overrides.json")
    assert overrides["values"]["pay_status='PAID'"] == {
        "meaning": "已支付并已入账",
        "confirmed_by": "owner",
        "date": "2026-09-19",
    }
    assert overrides["terms"] == {}
    patch = _json(tmp_path / "metadata-patch.json")
    assert patch["doc_format"] == "metadata-patch/1"
    assert patch["columns"]["mart.orders.pay_status"]["comment"] == "订单的支付状态"
    assert patch["tables"]["mart.orders"]["table_name_cn"] == "订单结果表"
    assert patch["tables"]["mart.orders"]["confirmed_by"] == "owner"


def test_an_unanswered_item_is_skipped_and_counted(tmp_path: Path) -> None:
    """The placeholder is not an answer, and a question nobody answered is not a blank."""
    result = _run("apply", str(_profile(tmp_path)), "--by", "owner")

    assert "unanswered=1" in result.stdout
    assert "核销" not in (tmp_path / "glossary.overrides.json").read_text(encoding="utf-8")


def test_the_five_line_format_without_an_answer_line_writes_nothing(
    tmp_path: Path,
) -> None:
    body = (
        "Q1. 这个 code 是什么？\n"
        "- 证据：semantic.json\n"
        "- 候选答案：无候选\n"
        "- 回写目标：术语:核销\n"
        "- 影响：影响口径理解\n"
    )

    result = _run("apply", str(_profile(tmp_path, body)), "--by", "owner")

    assert result.returncode == 0
    assert "unanswered=1" in result.stdout
    assert not (tmp_path / "glossary.overrides.json").exists()
    assert not (tmp_path / "metadata-patch.json").exists()


def test_merging_keeps_an_entry_somebody_else_already_confirmed(tmp_path: Path) -> None:
    overrides = tmp_path / "glossary.overrides.json"
    overrides.write_text(
        json.dumps(
            {
                "terms": {"核销": {"meaning": "第一轮答案"}},
                "values": {"pay_status='PAID'": {"meaning": "第一轮答案"}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = _run("apply", str(_profile(tmp_path)), "--by", "owner")

    assert result.returncode == 0
    assert _json(overrides)["values"]["pay_status='PAID'"]["meaning"] == "第一轮答案"
    assert _json(overrides)["terms"]["核销"]["meaning"] == "第一轮答案"
    assert "kept_existing=1" in result.stdout


def test_dry_run_prints_both_documents_and_writes_nothing(tmp_path: Path) -> None:
    result = _run("apply", str(_profile(tmp_path)), "--by", "owner", "--dry-run")

    assert result.returncode == 0
    assert "glossary.overrides.json (dry run)" in result.stdout
    assert "metadata-patch.json (dry run)" in result.stdout
    assert "订单结果表" in result.stdout
    assert not (tmp_path / "glossary.overrides.json").exists()
    assert not (tmp_path / "metadata-patch.json").exists()


def test_output_paths_can_be_named(tmp_path: Path) -> None:
    overrides = tmp_path / "dict" / "my.overrides.json"
    patch = tmp_path / "dict" / "my.patch.json"

    result = _run(
        "apply",
        str(_profile(tmp_path)),
        "--by",
        "owner",
        "--overrides",
        str(overrides),
        "--patch",
        str(patch),
    )

    assert result.returncode == 0
    assert overrides.is_file() and patch.is_file()


def test_a_target_line_still_carrying_the_template_placeholder_is_refused(
    tmp_path: Path,
) -> None:
    """Four kinds separated by `|` is the blank template -- guessing would misfile it."""
    body = (
        "Q1. 这个 code 是什么？\n"
        "- 证据：semantic.json\n"
        "- 回写目标：{字段注释:<表.列> | 术语:<词> | 值域:<列>=<值> | 表注释:<表>}\n"
        "- 影响：影响口径理解\n"
        "- 答案：核销指回款后冲抵应收\n"
    )

    result = _run("apply", str(_profile(tmp_path, body)), "--by", "owner")

    assert "no_target=1" in result.stdout
    assert not (tmp_path / "glossary.overrides.json").exists()


def test_a_missing_profile_is_a_usage_error(tmp_path: Path) -> None:
    result = _run("apply", str(tmp_path / "nope.md"), "--by", "owner")

    assert result.returncode == 2


def test_no_subcommand_prints_the_usage_doc(tmp_path: Path) -> None:
    result = _run()

    assert result.returncode == 2
    assert "apply <business_profile.md>" in result.stderr


# --------------------------------------------------------------- unit-level parsing


@pytest.fixture()
def module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("confirmations", SCRIPT)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_parse_items_reads_both_the_five_and_the_six_line_format(module) -> None:
    items = module.parse_items(PROFILE)

    assert [item["number"] for item in items] == [1, 2, 3, 4]
    assert items[0]["回写目标"] == "值域:pay_status='PAID'"
    assert module.answer_of(items[0]) == "已支付并已入账"
    assert module.answer_of(items[3]) is None


def test_a_target_accepts_either_colon_and_strips_backticks(module) -> None:
    assert module.target_of({"回写目标": "术语：核销"}) == ("术语", "核销")
    assert module.target_of({"回写目标": "`字段注释:mart.orders.pay_status`"}) == (
        "字段注释",
        "mart.orders.pay_status",
    )
    assert module.target_of({"回写目标": "无"}) is None


def test_the_appendix_table_after_a_block_does_not_leak_into_it(module) -> None:
    items = module.parse_items(PROFILE)

    assert set(items[3]) == {"number", "question", "证据", "候选答案", "回写目标", "影响", "答案"}
