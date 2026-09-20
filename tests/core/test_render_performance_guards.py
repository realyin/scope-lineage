"""Structural guards for the Q5 render caches.

Q5 removed four hotspots by making the *unit of work* the thing being asked about
rather than the question asking: one expression text is parsed once however many
questions the profile asks of it, one parsed node is restated once, one document is
digested once, and one scope's output-name index is built once.

These are guards, not benchmarks. A wall-clock assertion would fail on a loaded machine
and pass on a fast one; what actually has to hold is that the second identical question
does not do the work again. Every assertion here counts *work done*, so it means the
same thing on any machine. Byte-identity of the outputs is guarded where it belongs --
by the golden corpus, which these caches left untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.render import semantic_profile, semantic_text
from scope_lineage.render.mapping_markdown import lineage_document_digest
from scope_lineage.render.semantic_profile import build_semantic_profile


FIXTURES = Path(__file__).parent / "fixtures" / "lineage_contract"
CASE = FIXTURES / "grouped_dedup_join"


@pytest.fixture
def document() -> dict:
    return json.loads((CASE / "lineage.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _clear_caches():
    semantic_text._parse_expression_cached.cache_clear()
    semantic_text._plain_sql.cache_clear()
    semantic_profile._index_memo.clear()
    yield


def test_repeated_expression_text_is_parsed_once() -> None:
    """The same text asked twice is one parse: the second call is a cache hit."""
    expression = "sum(case when a.status = 'paid' then a.amount else 0 end)"
    first = semantic_text.parse_expression(expression)
    before = semantic_text._parse_expression_cached.cache_info()
    second = semantic_text.parse_expression(expression)
    after = semantic_text._parse_expression_cached.cache_info()

    assert first is second
    assert after.hits == before.hits + 1
    assert after.misses == before.misses


def test_unparsable_text_is_not_reparsed() -> None:
    """A text sqlglot cannot parse is a cached ``None``, not a retried parse."""
    garbage = "))) not sql at all ((("
    assert semantic_text.parse_expression(garbage) is None
    before = semantic_text._parse_expression_cached.cache_info()
    assert semantic_text.parse_expression(garbage) is None
    assert semantic_text._parse_expression_cached.cache_info().hits == before.hits + 1


def test_restating_one_node_twice_renders_it_once() -> None:
    """``expression_text`` of the same node object is rendered once, not re-deepcopied."""
    node = semantic_text.parse_expression("coalesce(t.`amount`, 0)")
    first = semantic_text.expression_text(node)
    before = semantic_text._plain_sql.cache_info()
    second = semantic_text.expression_text(node)
    after = semantic_text._plain_sql.cache_info()

    assert first == second
    assert after.hits == before.hits + 1
    assert after.misses == before.misses


def test_one_profile_build_parses_far_fewer_texts_than_it_asks_for(
    document: dict,
) -> None:
    """The profile asks the same expression many questions; it pays for one parse each."""
    calls = {"n": 0}
    original = semantic_text.parse_expression

    def counting(expression):
        calls["n"] += 1
        return original(expression)

    semantic_text.parse_expression = counting
    try:
        build_semantic_profile(document)
    finally:
        semantic_text.parse_expression = original
    info = semantic_text._parse_expression_cached.cache_info()

    assert calls["n"] > 0
    assert info.misses < calls["n"]


def test_document_digest_is_computed_once_per_document(document: dict) -> None:
    """Two digests of one document object are one serialisation."""
    import scope_lineage.render.mapping_markdown as mapping_markdown

    mapping_markdown._digest_memo.clear()
    first = lineage_document_digest(document)
    assert len(mapping_markdown._digest_memo) == 1
    second = lineage_document_digest(document)

    assert first == second
    assert len(mapping_markdown._digest_memo) == 1


def test_a_different_document_still_gets_its_own_digest(document: dict) -> None:
    """The memo keys on the object, so it can never answer for another document."""
    other = json.loads(json.dumps(document))
    other["task_id"] = f"{document.get('task_id')}_variant"

    assert lineage_document_digest(other) != lineage_document_digest(document)


def test_output_name_index_is_built_once_per_scope(document: dict) -> None:
    """Five call sites, one index: the second ask returns the same dict object."""
    scopes = semantic_profile._scopes(document)
    scope_id = next(sid for sid, scope in scopes.items() if scope.get("outputs"))

    first = semantic_profile._output_name_index(document, scope_id)
    second = semantic_profile._output_name_index(document, scope_id)

    assert first
    assert first is second


def test_column_details_are_looked_up_by_name_not_by_scan(document: dict) -> None:
    """The per-table index is built once and answers by key, first spelling winning."""
    item = {
        "column_details": [
            {"name": "amount", "comment": "first"},
            {"name": "amount", "comment": "second"},
            {"name": "status", "comment": "other"},
        ]
    }
    semantic_profile._index_memo.clear()

    assert semantic_profile._column_detail(item, "amount")["comment"] == "first"
    assert len(semantic_profile._index_memo) == 1
    assert semantic_profile._column_detail(item, "status")["comment"] == "other"
    assert len(semantic_profile._index_memo) == 1
    assert semantic_profile._column_detail(item, "absent") == {}
    assert semantic_profile._column_detail({}, "amount") == {}


def test_index_memo_stays_bounded() -> None:
    """A corpus walk holds a fixed number of indexes, not one per document seen."""
    semantic_profile._index_memo.clear()
    items = [{"column_details": [{"name": f"c{n}"}]} for n in range(400)]
    for item in items:
        semantic_profile._column_detail(item, "c0")

    assert len(semantic_profile._index_memo) <= semantic_profile._INDEX_MEMO_SIZE
