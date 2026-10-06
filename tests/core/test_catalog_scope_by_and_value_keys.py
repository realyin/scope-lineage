"""Two optional catalog fields: an identifier unique per value of a column, a code's key.

An identifier's ``scope`` says where its values are unique: ``global``, or ``{per: [concept
ids]}``. Some identifiers are unique only within one value of a physical column that names no
business concept -- a source system, an environment -- so the scope object also takes
``by: [{column, table?}]`` (the shape of ``spellings``), with ``per`` optional and at least one
of the two present.

A code set listing ``values`` (an inline dictionary) has no ``lookup.key_column``, so a column
storing the dictionary's surrogate key could not be translated. Each value may now carry its
``key``; ``holds: [key]`` on such a set no longer warns.

Both are additive: the format versions do not move, and a catalog without them builds the
same bytes.
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
from .test_catalog_binding_holds import WAIVER_TABLE, _add_holds, _set
from .test_catalog_fragment import _example

APP_ACCOUNT = "id:app_account_id"


def _scope(root: Path, scope) -> Path:
    mutate(root, "identifiers.yaml", lambda d: item(d["identifiers"], APP_ACCOUNT).__setitem__("scope", scope))
    return root


def _identifier_text(document: dict) -> str:
    return render_query_text(query_catalog(document, "identifier", APP_ACCOUNT))


# ------------------------------------------------------------------ #34 scope.by


@pytest.mark.parametrize("scope, query_words, page_words", [
    ({"by": [{"column": "src_sys"}]}, "按 src_sys 的每个取值唯一", "按 src_sys 的每个取值唯一"),
    (
        {"per": ["concept:channel"], "by": [{"column": "src_sys", "table": "demo_ods.ods_app_df"}]},
        "每个 concept:channel 内、按 demo_ods.ods_app_df.src_sys 的每个取值唯一",
        "每个渠道内、按 demo_ods.ods_app_df.src_sys 的每个取值唯一",
    ),
])
def test_an_identifier_unique_per_value_of_a_column(
    tmp_path: Path, scope, query_words, page_words
) -> None:
    root = _scope(copy_demo(tmp_path), scope)

    assert validate_catalog(load_catalog(root)).errors == []
    document = build_ontology(load_catalog(root))
    assert ontology_findings(document) == []
    assert item(document["identifiers"], APP_ACCOUNT)["scope"] == scope
    assert query_words in _identifier_text(document)
    assert page_words in render_catalog_pages(document)["concepts/app_account.md"]


def test_the_overview_says_which_column_scopes_the_identifier(tmp_path: Path) -> None:
    root = _scope(copy_demo(tmp_path), {"per": ["concept:channel"], "by": [{"column": "src_sys"}]})
    pages = render_catalog_pages(build_ontology(load_catalog(root)))

    assert any("每个渠道内按 src_sys 的每个取值一个" in text for text in pages.values())


def test_an_empty_scope_object_is_a_schema_error(tmp_path: Path) -> None:
    root = _scope(copy_demo(tmp_path), {})

    errors = validate_catalog(load_catalog(root)).errors

    assert [e.rule for e in errors] == ["schema"]
    assert errors[0].at.startswith("identifiers[")


def test_per_still_names_concepts(tmp_path: Path) -> None:
    root = _scope(copy_demo(tmp_path), {"per": ["attr:customer.gender"], "by": [{"column": "src_sys"}]})

    errors = validate_catalog(load_catalog(root)).errors

    assert [e.rule for e in errors] == ["identifier_scope"]


def test_a_global_or_per_scope_builds_the_same_bytes(tmp_path: Path) -> None:
    root = copy_demo(tmp_path)
    assert main(["catalog", "build", str(root), "--out", str(tmp_path / "a")]) == 0
    _scope(root, {"per": ["concept:channel"]})  # what the demo already says
    assert main(["catalog", "build", str(root), "--out", str(tmp_path / "b")]) == 0

    assert (tmp_path / "a" / "ontology.json").read_bytes() == (tmp_path / "b" / "ontology.json").read_bytes()


def test_a_fragment_identifier_takes_the_same_scope() -> None:
    fragment = _example()
    fragment["identifiers"] = [{
        "id": "id:disbursement_no", "name": "放款流水号", "identifies": "concept:disbursement",
        "scope": {"by": [{"column": "src_sys"}]},
    }]
    bad = copy.deepcopy(fragment)
    bad["identifiers"][0]["scope"] = {}

    assert [f for f in check_fragment(fragment, "f.json") if f.rule == "schema"] == []
    assert [f.rule for f in check_fragment(bad, "f.json")] == ["schema"]


# ------------------------------------------------------------------ #35 values[].key

GENDER_KEYS = {"F": "k_f", "M": "k_m", "U": "k_u"}


def _keyed_gender(root: Path) -> Path:
    def add(d: dict) -> None:
        for value in item(d["code_sets"], "code:gender")["values"]:
            value["key"] = GENDER_KEYS[str(value["value"])]

    mutate(root, "code_sets.yaml", add)
    return root


@pytest.fixture
def keyed(tmp_path: Path) -> Path:
    root = _keyed_gender(_add_holds(copy_demo(tmp_path)))
    _set(root, "reason_key", code_sets=["code:gender"])
    return root


def test_a_key_into_a_code_set_whose_values_carry_keys_is_not_a_warning(keyed: Path) -> None:
    report = validate_catalog(load_catalog(keyed))

    assert report.errors == []
    assert "binding_key_without_key_column" not in rules(report.warnings)


def test_build_carries_each_values_key(keyed: Path) -> None:
    document = build_ontology(load_catalog(keyed))

    values = item(document["code_sets"], "code:gender")["values"]
    assert [(v["value"], v.get("key")) for v in values] == [("F", "k_f"), ("M", "k_m"), ("U", "k_u")]
    assert ontology_findings(document) == []
    other = item(document["code_sets"], "code:verification_status")["values"]
    assert all("key" not in value for value in other)


def test_the_query_and_pages_translate_a_key(keyed: Path) -> None:
    document = build_ontology(load_catalog(keyed))

    column = render_query_text(query_catalog(document, "column", f"{WAIVER_TABLE}.reason_key"))
    assert "k_f→F=female" in column
    attribute = render_query_text(query_catalog(document, "attribute", "attr:customer.gender"))
    assert "F=female（代理键 k_f）" in attribute
    assert "F=female（代理键 k_f）" in render_catalog_pages(document)["code_sets.md"]


def test_an_integer_key_is_legal_and_built_as_text(tmp_path: Path) -> None:
    root = copy_demo(tmp_path)
    mutate(root, "code_sets.yaml",
           lambda d: item(d["code_sets"], "code:gender")["values"][0].__setitem__("key", 7))

    assert validate_catalog(load_catalog(root)).errors == []
    values = item(build_ontology(load_catalog(root))["code_sets"], "code:gender")["values"]
    assert values[0]["key"] == "7"


def test_a_fragment_code_set_value_takes_a_key() -> None:
    fragment = _example()
    fragment["code_sets"][0]["values"][0]["key"] = "k_bank"

    assert check_fragment(fragment, "f.json") == []


def test_a_catalog_without_keys_builds_the_same_bytes(tmp_path: Path) -> None:
    root = copy_demo(tmp_path)
    assert main(["catalog", "build", str(root), "--out", str(tmp_path / "a")]) == 0
    text = (tmp_path / "a" / "ontology.json").read_text(encoding="utf-8")

    assert '"key":' not in text
