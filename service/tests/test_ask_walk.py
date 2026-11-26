"""The ask panel's system prompt: the skill's walk, one source, and a preamble that only maps."""

from __future__ import annotations

import json
import re

import pytest
from service_paths import REPO

from scope_lineage_service.ask import walk
from scope_lineage_service.ask.tools import CHECK_SQL, CONTEXT, QUERY, RECALL, SEARCH

SOURCES = {
    "catalog-answers.md": REPO / "skills" / "scope-lineage" / "workflows" / "catalog-answers.md",
    "catalog-questions.md": REPO / "skills" / "scope-lineage" / "references" / "catalog-questions.md",
}


@pytest.mark.parametrize("name", walk.WALK_FILES)
def test_the_packaged_walk_is_the_skill_file_byte_for_byte(name) -> None:
    source = SOURCES[name]
    assert walk.walk_text(name) == source.read_text(encoding="utf-8"), (
        f"service/scope_lineage_service/ask/{name} differs from {source.relative_to(REPO)}: "
        "the skill file is the source; copy it over the packaged one"
    )


@pytest.mark.parametrize("pending", [True, False])
def test_the_system_prompt_is_preamble_then_the_walk_whole(pending) -> None:
    blocks = walk.system_blocks(pending)

    assert [block["type"] for block in blocks] == ["text", "text", "text"]
    assert blocks[1]["text"] == walk.walk_text("catalog-answers.md")
    assert blocks[2]["text"].endswith(walk.walk_text("catalog-questions.md"))
    # one breakpoint, on the last block: tools and the whole system prompt cache together
    assert [("cache_control" in block) for block in blocks] == [False, False, True]


def test_the_preamble_maps_commands_and_states_limits_without_restating_steps() -> None:
    text = walk.preamble(pending=True)
    steps = re.findall(r"^\*\*\d\. ", walk.walk_text("catalog-answers.md"), flags=re.M)

    assert len(text) < len(walk.walk_text("catalog-answers.md")) / 2
    assert len(steps) == 7 and not re.search(r"^\*\*\d\. ", text, flags=re.M)
    for limit in ("不执行 SQL", "读不到任何文件", "提问者的语言"):
        assert limit in text
    named = set(re.findall(r"`([a-z_]+)\(", text))
    offered = {tool["name"] for tool in (SEARCH, CONTEXT, QUERY, CHECK_SQL, RECALL)}
    assert named == offered


def test_with_a_pending_file_the_asker_records_gaps_with_the_page_button() -> None:
    text = walk.preamble(pending=True)

    # no tool stands for `catalog pending add`: the model cannot record, nor say it did
    assert "add_pending" not in text and "没有这个工具" in text
    assert "「记入待确认」按钮" in text and "提问者点了服务才写" in text
    assert "未记入" in text and "不要说已记入" in text


def test_without_a_pending_file_the_preamble_offers_no_pending_tool() -> None:
    text = walk.preamble(pending=False)

    assert "add_pending" not in text and "未记入" in text and "没有待确认文件" in text


def test_the_walk_records_a_gap_only_when_the_asker_agrees() -> None:
    answers = walk.walk_text("catalog-answers.md")
    step6 = answers.split("**6. ", 1)[1].split("**7. ", 1)[0]

    assert step6.startswith("列出缺口，问提问者记不记。")
    assert "提问者同意了才记" in step6 and "没同意就不记" in step6
    assert "未记入 / 已按提问者同意记入 `<P>`" in answers
    assert "待确认：<占位文字> — <列>；<表 q 号 / 无>；未记入 / 已按提问者同意记入 <P>" in answers
    assert "已记入 <P>" not in answers.replace("已按提问者同意记入 <P>", "")


def test_the_prompt_has_nothing_that_varies_between_requests() -> None:
    first = json.dumps(walk.system_blocks(True), ensure_ascii=False, sort_keys=True)
    walk.walk_text.cache_clear()
    second = json.dumps(walk.system_blocks(True), ensure_ascii=False, sort_keys=True)

    assert first == second
    for pending in (True, False):
        preamble = walk.preamble(pending)
        assert not re.search(r"\d{4}-\d{2}-\d{2}|\d{2}:\d{2}", preamble)
        assert "/" + "Users" + "/" not in preamble and "/home/" not in preamble


def test_the_walk_resolves_relative_time_against_todays_date() -> None:
    answers = walk.walk_text("catalog-answers.md")

    assert "今天的日期以消息开头的「今天：YYYY-MM-DD」为准" in answers
    assert "今天的日期是假设" in answers  # no date given (Claude Code): say it is assumed
    assert "（上个月，按今天 2026-11-25 解析）" in answers
    assert "不是「最新」「上个月」" in answers


def test_the_walk_brief_is_the_increment_block_of_both_paths() -> None:
    answers = walk.walk_text("catalog-answers.md")
    brief = answers.split("## 多轮问数", 1)[1].split("```text\n", 1)[1].split("```", 1)[0]
    keys = [line.split("：", 1)[0] for line in brief.splitlines()]

    assert keys == ["话题", "问题", "结论", "SQL角色", "SQL", "表", "关联", "条件", "假设", "说法",
                    "提议缺口", "待确认", "check-sql"]
    for optional in ("撤销说法：", "名字映射：", "偏好：", "未决问题："):
        assert optional in answers


def test_the_preamble_explains_the_card_and_recall() -> None:
    text = walk.preamble(pending=True)

    assert "【对话状态卡】" in text and "今天：YYYY-MM-DD" in text
    assert "`recall(turn, topic, version)`" in text and "没调 `recall` 之前" in text
    assert "第一行以\"话题：\"开头" in text
