"""The ask panel's system prompt: the skill's walk, one source, and a preamble that only maps."""

from __future__ import annotations

import json
import re

import pytest
from service_paths import REPO

from scope_lineage_service.ask import walk
from scope_lineage_service.ask.tools import ADD_PENDING, CHECK_SQL, CONTEXT, QUERY, SEARCH

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
    offered = {tool["name"] for tool in (SEARCH, CONTEXT, QUERY, CHECK_SQL, ADD_PENDING)}
    assert named == offered


def test_without_a_pending_file_the_preamble_offers_no_pending_tool() -> None:
    text = walk.preamble(pending=False)

    assert "add_pending" not in text and "未记入" in text


def test_the_prompt_has_nothing_that_varies_between_requests() -> None:
    first = json.dumps(walk.system_blocks(True), ensure_ascii=False, sort_keys=True)
    walk.walk_text.cache_clear()
    second = json.dumps(walk.system_blocks(True), ensure_ascii=False, sort_keys=True)

    assert first == second
    for pending in (True, False):
        preamble = walk.preamble(pending)
        assert not re.search(r"\d{4}-\d{2}-\d{2}|\d{2}:\d{2}", preamble)
        assert "/" + "Users" + "/" not in preamble and "/home/" not in preamble
