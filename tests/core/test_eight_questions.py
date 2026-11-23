"""Eight open questions, the most ``semantic validate`` accepts, reach every reader whole.

The cap went from five to eight. Nothing that shows a table's questions counts them against
a fixed number, and these tests keep it so: the table-semantics page, the brief context
pack and ``catalog pending`` list all eight.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from scope_lineage.cli_catalog_answers import pending_answer
from scope_lineage.render.catalog_context import context_pack, render_context_text
from scope_lineage.render.catalog_pending import pending_line
from scope_lineage.semantics import render_semantic_pages
from scope_lineage.semantics.checks import MAX_QUESTIONS

from .table_semantics_demo import DEMO_TABLE, example

ONTOLOGY = Path(__file__).parent / "fixtures" / "catalog" / "ontology.json"
COUNT = 8


def _with_questions() -> dict:
    document = copy.deepcopy(example())
    document["summary"]["questions"] = [
        {"id": f"q{index}", "text": f"第 {index} 个要业务回答的问题", "about": ["column:gender_cd"],
         "status": "open"}
        for index in range(1, COUNT + 1)
    ]
    return document


def _texts() -> list[str]:
    return [f"第 {index} 个要业务回答的问题" for index in range(1, COUNT + 1)]


def test_the_cap_is_eight() -> None:
    assert MAX_QUESTIONS == COUNT


def test_the_page_lists_all_eight() -> None:
    page = render_semantic_pages([_with_questions()])[f"{DEMO_TABLE}.md"]
    for text in _texts():
        assert text in page


def test_the_brief_pack_lists_all_eight() -> None:
    document = json.loads(ONTOLOGY.read_text(encoding="utf-8"))
    pack = context_pack(document, {DEMO_TABLE: _with_questions()}, tables=[DEMO_TABLE], brief=True)
    (table,) = pack["tables"]
    assert len(table["semantics"]["questions"]) == COUNT
    text = render_context_text(pack)
    for text_of in _texts():
        assert text_of in text


def test_pending_names_all_eight_recorded_for_its_column() -> None:
    line = pending_line(missing="性别码值的含义", question="按性别统计", date="2026-01-02",
                        columns=[f"{DEMO_TABLE}.gender_cd"])
    answer = pending_answer(json.dumps(line, ensure_ascii=False) + "\n",
                            None, {DEMO_TABLE: _with_questions()})
    (item,) = answer.result["items"]
    assert [question["id"] for question in item["recorded_questions"]] == [
        f"q{index}" for index in range(1, COUNT + 1)
    ]
    text = answer.text()
    for text_of in _texts():
        assert text_of in text
