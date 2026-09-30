"""An attribute's code sets (rule R1): its own ``code_set``; when it has none, the
``code_sets`` its columns name, de-duplicated in the order first seen.

Every reader that decides "this attribute's codes" -- the missing-codes gap, the concept
page's 「码值」 cell, ``catalog query attribute`` and the attributes ``code_sets.md`` lists
under a code set -- reads that one answer. The fixture is the demo with two synthetic code
sets; the demo's state attribute and its two columns are rewired per test.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scope_lineage.catalog import build_ontology, load_catalog, validate_catalog
from scope_lineage.catalog.index import build_index
from scope_lineage.render.catalog_gaps import concept_gaps
from scope_lineage.render.catalog_pages import render_catalog_pages
from scope_lineage.render.catalog_query import query_catalog, render_query_text
from scope_lineage.render.catalog_view import CatalogView

from .catalog_demo import copy_demo, item, mutate

STATE = "attr:loan.loan_status"
MEASURE = "attr:loan.principal"
MAIN_TABLE = "demo_dwd.dwd_lending_loan_df"
HISTORY_TABLE = "demo_dwd.dwd_lending_loan_status_his"
SET_A = {
    "id": "code:set_a",
    "name": "码值集甲",
    "values": [{"value": "1", "meaning": "alpha"}, {"value": "2", "meaning": "beta"}],
}
SET_B = {
    "id": "code:set_b",
    "name": "码值集乙",
    "values": [{"value": "0", "meaning": "alpha"}, {"value": "1", "meaning": "beta"}],
}
A_TEXT = "1=alpha；2=beta"
B_TEXT = "0=alpha；1=beta"


def _rewire(
    root: Path,
    *,
    own: str | None,
    main: list[str] | None,
    history: list[str] | None,
    sets: tuple[dict, ...] = (SET_A, SET_B),
) -> dict:
    """Add ``sets``; give the state attribute ``own`` as its code set (none when None) and
    its two columns ``main`` / ``history`` as their ``code_sets``; return the build."""
    mutate(root, "code_sets.yaml", lambda d: d["code_sets"].extend(copy.deepcopy(sets)))

    def concept(data: dict) -> None:
        attribute = item(item(data["concepts"], "concept:loan")["attributes"], STATE)
        attribute.pop("code_set", None)
        if own:
            attribute["code_set"] = own

    def mapping(data: dict) -> None:
        for table, code_sets in ((MAIN_TABLE, main), (HISTORY_TABLE, history)):
            rep = item(data["representations"], "table", table)
            binding = item(rep["bindings"], "column", "loan_status")
            if code_sets:
                binding["code_sets"] = list(code_sets)

    mutate(root, "concepts/lending.yaml", concept)
    mutate(root, "mapping/lending.yaml", mapping)
    return build_ontology(load_catalog(root))


def _codes_cell(pages: dict, attribute_id: str) -> str:
    """The A4 「码值」 cell: the fourth column of the row that starts with the attribute."""
    (row,) = [
        line for line in pages["concepts/loan.md"].splitlines()
        if line.startswith("| ") and line.split(" | ")[0].endswith(f"`{attribute_id}`")
    ]
    return row.split(" | ")[3]


def _block(page: str, name: str) -> str:
    return page.split(f"## {name}")[1].split("\n## ")[0]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return copy_demo(tmp_path)


# --------------------------------------------------------------------- the rule


def test_the_attributes_own_code_set_wins() -> None:
    from scope_lineage.catalog.index import attribute_code_set_ids

    attribute = {"id": "attr:x.y", "code_set": "code:own"}
    bindings = [{"to": "attribute", "ref": "attr:x.y", "code_sets": ["code:other"]}]

    assert attribute_code_set_ids(attribute, bindings) == ["code:own"]


def test_without_one_the_columns_code_sets_count_once_in_first_seen_order() -> None:
    from scope_lineage.catalog.index import attribute_code_set_ids

    attribute = {"id": "attr:x.y"}
    bindings = [
        {"to": "attribute", "ref": "attr:x.y", "code_sets": ["code:b", "code:a"]},
        {"to": "foreign_attribute", "ref": "attr:x.y", "code_sets": ["code:a", "code:c"]},
        {"to": "attribute", "ref": "attr:x.other", "code_sets": ["code:d"]},
        {"to": "foreign_identifier", "ref": "attr:x.y", "code_sets": ["code:e"]},
        {"to": "attribute", "ref": "attr:x.y"},
    ]

    assert attribute_code_set_ids(attribute, bindings) == ["code:b", "code:a", "code:c"]
    assert attribute_code_set_ids(attribute, []) == []


def test_the_index_gives_the_same_answer(root: Path) -> None:
    _rewire(root, own=None, main=["code:set_a"], history=["code:set_b", "code:set_a"])
    index = build_index(load_catalog(root))

    assert index.attribute_code_set_ids(STATE) == ["code:set_a", "code:set_b"]
    assert index.attribute_code_set_ids("attr:customer.gender") == ["code:gender"]
    assert index.attribute_code_set_ids(MEASURE) == []


# ------------------------------------------------- per-source sets, attribute names none


@pytest.fixture
def per_source(root: Path) -> dict:
    return _rewire(root, own=None, main=["code:set_a"], history=["code:set_b"])


def test_per_source_sets_are_not_a_missing_codes_gap(per_source: dict) -> None:
    gaps = concept_gaps(CatalogView(per_source), "concept:loan")

    assert STATE not in gaps.missing_codes
    assert f"`{STATE}`" not in render_catalog_pages(per_source)["governance.md"].split(
        "缺码值的状态/码值类属性"
    )[-1]


def test_the_concept_page_lists_each_set_by_name(per_source: dict) -> None:
    pages = render_catalog_pages(per_source)

    assert _codes_cell(pages, STATE) == f"码值集甲：{A_TEXT}；码值集乙：{B_TEXT}"
    assert "按来源" not in pages["concepts/loan.md"]


def test_query_attribute_answers_with_every_set(per_source: dict) -> None:
    result = query_catalog(per_source, "attribute", STATE)
    (match,) = result["matches"]

    assert "code_set" not in match
    built_sets = {s["id"]: s for s in per_source["code_sets"]}
    assert match["code_sets"] == [
        {"id": key, "name": built_sets[key]["name"], "values": built_sets[key]["values"]}
        for key in ("code:set_a", "code:set_b")
    ]
    lines = render_query_text(result).splitlines()
    assert f"  码值（码值集甲 code:set_a）：{A_TEXT}" in lines
    assert f"  码值（码值集乙 code:set_b）：{B_TEXT}" in lines


def test_code_sets_page_names_the_attribute_under_each_set(per_source: dict) -> None:
    page = render_catalog_pages(per_source)["code_sets.md"]

    for name in ("码值集甲", "码值集乙"):
        assert f"| 使用它的属性 | 借据状态 `{STATE}`（" in _block(page, name)


# ------------------------------------------------------------------------ guards


def test_sets_with_neither_values_nor_lookup_still_lack_codes(root: Path) -> None:
    empty = tuple({**s, "values": []} for s in (SET_A, SET_B))
    built = _rewire(root, own=None, main=["code:set_a"], history=["code:set_b"], sets=empty)

    assert STATE in concept_gaps(CatalogView(built), "concept:loan").missing_codes


def test_a_lookup_chain_on_one_column_lists_both_sets_without_saying_by_source(
    root: Path,
) -> None:
    built = _rewire(root, own=None, main=["code:set_a", "code:set_b"], history=None)
    pages = render_catalog_pages(built)

    assert STATE not in concept_gaps(CatalogView(built), "concept:loan").missing_codes
    assert _codes_cell(pages, STATE) == f"码值集甲：{A_TEXT}；码值集乙：{B_TEXT}"
    assert "按来源" not in pages["concepts/loan.md"]
    column = render_query_text(query_catalog(built, "column", f"{MAIN_TABLE}.loan_status"))
    assert "先查 码值集甲，查不到查 码值集乙" in column


def test_an_attributes_own_code_set_is_not_widened_by_its_columns(root: Path) -> None:
    built = _rewire(root, own="code:set_a", main=["code:set_a"], history=["code:set_b"])
    pages = render_catalog_pages(built)
    (match,) = query_catalog(built, "attribute", STATE)["matches"]

    assert _codes_cell(pages, STATE) == A_TEXT
    built_a = item(built["code_sets"], "code:set_a")
    assert match["code_set"] == {"id": "code:set_a", "values": built_a["values"]}
    assert "code_sets" not in match
    assert "| 使用它的属性 | （无） |" in _block(pages["code_sets.md"], "码值集乙")
    assert STATE not in concept_gaps(CatalogView(built), "concept:loan").missing_codes
    warnings = [
        w.at for w in validate_catalog(load_catalog(root)).warnings
        if w.rule == "binding_code_sets_miss_attribute"
    ]
    assert warnings == [f"{HISTORY_TABLE}.loan_status"]


def test_a_column_naming_a_set_does_not_make_an_uncoded_attribute_lack_codes(
    root: Path,
) -> None:
    empty = {"id": "code:set_empty", "name": "空码值集", "values": []}
    mutate(root, "code_sets.yaml", lambda d: d["code_sets"].append(empty))
    mutate(
        root, "mapping/lending.yaml",
        lambda d: item(
            item(d["representations"], "table", MAIN_TABLE)["bindings"], "column", "principal_amt"
        ).update(code_sets=["code:set_empty"]),
    )
    built = build_ontology(load_catalog(root))

    assert MEASURE not in concept_gaps(CatalogView(built), "concept:loan").missing_codes


def test_a_state_attribute_with_no_code_set_anywhere_still_lacks_codes(root: Path) -> None:
    built = _rewire(root, own=None, main=None, history=None)

    assert STATE in concept_gaps(CatalogView(built), "concept:loan").missing_codes
    assert _codes_cell(render_catalog_pages(built), STATE) == "—"
