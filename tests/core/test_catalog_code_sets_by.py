"""How a column's ``code_sets`` list is read (``code_sets_by``).

Absent (or ``lookup``), the list is a lookup order: look a value up in the first set, then
the next. ``source`` says each source or branch writing the column uses one of the sets,
its own: the order means nothing and no value is ever looked up in a second set. Pages and
queries say 「按来源分别查 A、B」 for it instead of 「先查 A，查不到查 B」.

The fixture is the demo with two synthetic code sets whose codes clash (``1`` means a
different thing in each); the demo's state column on the main loan table names both.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from scope_lineage.catalog import (
    build_ontology,
    check_fragment,
    load_catalog,
    ontology_findings,
    validate_catalog,
)
from scope_lineage.cli import main
from scope_lineage.render.catalog_pages import render_catalog_pages
from scope_lineage.render.catalog_query import query_catalog, render_query_text

from .catalog_demo import copy_demo, item, mutate, rules
from .test_catalog_attribute_code_sets import MAIN_TABLE, SET_A, SET_B, STATE, _block
from .test_catalog_fragment import _example

SET_C = {"id": "code:set_c", "name": "码值集丙", "values": [{"value": "9", "meaning": "gamma"}]}
COLUMN = f"{MAIN_TABLE}.loan_status"
BY_SOURCE = "按来源分别查 码值集甲、码值集乙"


def _state_column(root: Path, **fields) -> Path:
    """Set ``fields`` on the main table's state column (a ``None`` value removes the key)."""

    def change(mapping: dict) -> None:
        rep = item(mapping["representations"], "table", MAIN_TABLE)
        binding = item(rep["bindings"], "column", "loan_status")
        for key, value in fields.items():
            if value is None:
                binding.pop(key, None)
            else:
                binding[key] = value

    mutate(root, "mapping/lending.yaml", change)
    return root


def _attribute_code_set(root: Path, code_set: str | None) -> None:
    def change(data: dict) -> None:
        attribute = item(item(data["concepts"], "concept:loan")["attributes"], STATE)
        attribute.pop("code_set", None)
        if code_set:
            attribute["code_set"] = code_set

    mutate(root, "concepts/lending.yaml", change)


def _binding(document: dict) -> dict:
    return item(item(document["representations"], "table", MAIN_TABLE)["bindings"], "column", "loan_status")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """The demo plus the three synthetic code sets."""
    root = copy_demo(tmp_path)
    mutate(root, "code_sets.yaml", lambda d: d["code_sets"].extend(copy.deepcopy([SET_A, SET_B, SET_C])))
    return root


@pytest.fixture
def by_source(root: Path) -> dict:
    _state_column(root, code_sets=["code:set_a", "code:set_b"], code_sets_by="source")
    return build_ontology(load_catalog(root))


# ----------------------------------------------------------------------------- schema


def test_code_sets_by_source_is_legal(root: Path) -> None:
    _state_column(root, code_sets=["code:set_a", "code:set_b"], code_sets_by="source")

    assert validate_catalog(load_catalog(root)).errors == []


def test_code_sets_by_takes_lookup_or_source_only(root: Path) -> None:
    _state_column(root, code_sets=["code:set_a", "code:set_b"], code_sets_by="other")

    errors = validate_catalog(load_catalog(root)).errors

    assert [e.rule for e in errors] == ["schema"]
    assert errors[0].at.endswith(".code_sets_by"), "the value, not an unknown key"


@pytest.mark.parametrize("value", ["lookup", "source"])
def test_a_fragment_binding_takes_code_sets_by(value: str) -> None:
    fragment = _example()
    item(fragment["representations"][0]["bindings"], "column", "pay_method").update(
        code_sets=["code:a", "code:b"], code_sets_by=value
    )

    assert check_fragment(fragment, "f.json") == []


def test_a_fragment_binding_rejects_another_reading() -> None:
    fragment = _example()
    item(fragment["representations"][0]["bindings"], "column", "pay_method").update(
        code_sets=["code:a", "code:b"], code_sets_by="other"
    )

    (finding,) = check_fragment(fragment, "f.json")
    assert finding.rule == "schema" and finding.at.endswith(".code_sets_by")


# ------------------------------------------------------------------------- references


@pytest.mark.parametrize("code_sets", [["code:set_a"], None])
def test_by_source_needs_two_code_sets(root: Path, code_sets) -> None:
    _state_column(root, code_sets=code_sets, code_sets_by="source")

    errors = validate_catalog(load_catalog(root)).errors

    assert [(e.rule, e.at) for e in errors] == [("binding_code_sets_by", COLUMN)]


def test_code_sets_by_needs_code_sets(root: Path) -> None:
    _state_column(root, code_sets=None, code_sets_by="lookup")

    errors = validate_catalog(load_catalog(root)).errors

    assert [(e.rule, e.at) for e in errors] == [("binding_code_sets_by", COLUMN)]


def test_lookup_over_one_code_set_is_not_an_error(root: Path) -> None:
    _state_column(root, code_sets=["code:set_a"], code_sets_by="lookup")

    assert validate_catalog(load_catalog(root)).errors == []


# ------------------------------------------------------------------------------ build


def test_build_carries_code_sets_by_after_code_sets(root: Path) -> None:
    _state_column(root, code_sets=["code:set_a", "code:set_b"], code_sets_by="source", holds=["meaning", "code"])
    document = build_ontology(load_catalog(root))
    binding = _binding(document)

    assert binding["code_sets_by"] == "source"
    keys = list(binding)
    assert keys.index("code_sets") + 1 == keys.index("code_sets_by") == keys.index("holds") - 1
    assert ontology_findings(document) == []


def test_code_sets_by_lookup_written_out_builds_the_same_bytes(tmp_path: Path, root: Path) -> None:
    _state_column(root, code_sets=["code:set_a", "code:set_b"])
    plain, spelled = tmp_path / "plain", tmp_path / "spelled"
    assert main(["catalog", "build", str(root), "--out", str(plain)]) == 0
    _state_column(root, code_sets_by="lookup")
    assert main(["catalog", "build", str(root), "--out", str(spelled)]) == 0

    assert (spelled / "ontology.json").read_bytes() == (plain / "ontology.json").read_bytes()


# ------------------------------------------------------------------------------ query


def test_query_column_says_each_source_looks_up_its_own_set(by_source: dict) -> None:
    result = query_catalog(by_source, "column", COLUMN)
    (match,) = result["matches"]
    head = render_query_text(result).splitlines()[0]

    assert match["code_sets_by"] == "source"
    keys = list(match)
    assert keys.index("code_sets") + 1 == keys.index("code_sets_by")
    assert head.endswith(f"（码值：{BY_SOURCE}）")
    assert "先查" not in head and "查不到" not in head


def test_query_column_without_the_key_answers_as_before(root: Path) -> None:
    _state_column(root, code_sets=["code:set_a", "code:set_b"])
    result = query_catalog(build_ontology(load_catalog(root)), "column", COLUMN)
    (match,) = result["matches"]

    assert "code_sets_by" not in match
    assert render_query_text(result).splitlines()[0].endswith("（码值：先查 码值集甲，查不到查 码值集乙）")


# ------------------------------------------------------------------------------ pages


def test_the_pages_say_each_source_looks_up_its_own_set(root: Path) -> None:
    _state_column(
        root, code_sets=["code:set_a", "code:set_b"], code_sets_by="source", holds=["meaning", "code"], lang="zh"
    )
    document = build_ontology(load_catalog(root))
    pages = render_catalog_pages(document)
    (row,) = [line for line in pages["concepts/loan.md"].splitlines() if line.startswith("| 借据状态 ")]

    # the demo's code_map sits between the column and what it looks up
    assert f"`{COLUMN}`（码值映射 " in row
    assert f"（码值：{BY_SOURCE}；存含义（zh）或码）；" in row
    for name in ("码值集甲", "码值集乙"):
        block = _block(pages["code_sets.md"], name)
        assert f"| 查它的列 | `{COLUMN}`（{BY_SOURCE}；存含义（zh）或码）" in block
    text = render_query_text(query_catalog(document, "column", COLUMN))
    assert f"（码值：{BY_SOURCE}；存含义（zh）或码）" in text.splitlines()[0]
    for page in (pages["concepts/loan.md"], pages["code_sets.md"]):
        assert "查不到查 码值集乙" not in page


def test_the_code_sets_page_row_names_the_columns_without_an_order(root: Path) -> None:
    _state_column(root, code_sets=["code:set_a", "code:set_b"])
    page = render_catalog_pages(build_ontology(load_catalog(root)))["code_sets.md"]

    assert "按顺序查它的列" not in page
    assert f"| 查它的列 | `{COLUMN}`（先查 码值集甲，查不到查 码值集乙）" in _block(page, "码值集甲")


# ------------------------------------------------------------------------ guards


def test_the_attributes_set_in_a_by_source_list_is_not_a_miss(root: Path) -> None:
    _attribute_code_set(root, "code:set_a")
    _state_column(root, code_sets=["code:set_a", "code:set_b"], code_sets_by="source")

    report = validate_catalog(load_catalog(root))

    assert report.errors == []
    assert "binding_code_sets_miss_attribute" not in rules(report.warnings)


def test_a_by_source_list_without_the_attributes_set_is_still_a_miss(root: Path) -> None:
    _attribute_code_set(root, "code:set_c")
    _state_column(root, code_sets=["code:set_a", "code:set_b"], code_sets_by="source")

    report = validate_catalog(load_catalog(root))

    assert report.errors == []
    found = [w.at for w in report.warnings if w.rule == "binding_code_sets_miss_attribute"]
    assert found == [COLUMN]
