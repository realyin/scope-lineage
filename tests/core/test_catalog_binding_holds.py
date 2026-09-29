"""What a coded column stores (``holds``): the code, the meaning, or the dictionary's key.

A binding's ``code_sets`` names the code sets its values relate to, in lookup order; with
none, the bound attribute's ``code_set`` is the one. ``holds`` lists, in order of
preference, the forms of those code sets a value of the column can take; absent, it is
``[code]``. ``lang`` says which language the stored meaning is in.

The fixture is the dictionary-table demo of ``test_catalog_code_lookup`` with three more
columns beside the code column ``reason_cd``: one storing the meaning, one the key, one
the meaning or else the code.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scope_lineage.catalog import (
    build_ontology,
    check_fragment,
    load_catalog,
    merge_fragments,
    ontology_findings,
    validate_catalog,
)
from scope_lineage.cli import main
from scope_lineage.render.catalog_pages import render_catalog_pages
from scope_lineage.render.catalog_query import query_catalog, render_query_text

from .catalog_demo import copy_demo, item, mutate, rules
from .test_catalog_code_lookup import WAIVER_TABLE, _add_lookups, _binding, _waiver
from .test_catalog_fragment import _example

ATTRIBUTE = "attr:fee_waiver.reason"
MEANING = {"column": "reason_desc", "to": "attribute", "ref": ATTRIBUTE, "holds": ["meaning"], "lang": "zh"}
KEY = {
    "column": "reason_key", "to": "attribute", "ref": ATTRIBUTE,
    "code_sets": ["code:waiver_reason"], "holds": ["key"],
}
MIXED = {
    "column": "reason_label", "to": "attribute", "ref": ATTRIBUTE,
    "code_sets": ["code:waiver_reason", "code:waiver_channel"],
    "holds": ["meaning", "code"], "lang": "zh",
}


def _add_holds(root: Path) -> Path:
    _add_lookups(root)

    def add(mapping: dict) -> None:
        bindings = _waiver(mapping)["bindings"]
        at = bindings.index(item(bindings, "column", "reason_cd")) + 1
        bindings[at:at] = copy.deepcopy([MEANING, KEY, MIXED])

    mutate(root, "mapping/collection.json", add)
    return root


def _set(root: Path, column: str, **fields) -> None:
    def change(mapping: dict) -> None:
        binding = _binding(mapping, column)
        for key, value in fields.items():
            if value is None:
                binding.pop(key, None)
            else:
                binding[key] = value

    mutate(root, "mapping/collection.json", change)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return _add_holds(copy_demo(tmp_path))


@pytest.fixture(scope="module")
def document(tmp_path_factory) -> dict:
    return build_ontology(load_catalog(_add_holds(copy_demo(tmp_path_factory.mktemp("holds")))))


def _column(document: dict, column: str) -> tuple[dict, str]:
    result = query_catalog(document, "column", f"{WAIVER_TABLE}.{column}")
    (match,) = result["matches"]
    return match, render_query_text(result)


# ------------------------------------------------------------------ schema and checks


def test_holds_and_lang_are_legal(root: Path) -> None:
    report = validate_catalog(load_catalog(root))

    assert report.errors == []
    assert not {"binding_key_without_key_column", "binding_lang_unknown"} & set(rules(report.warnings))


@pytest.mark.parametrize("holds", [[], ["label"], ["code", "code"]])
def test_holds_must_be_a_non_empty_list_of_distinct_forms(root: Path, holds) -> None:
    _set(root, "reason_label", holds=holds)

    errors = validate_catalog(load_catalog(root)).errors

    assert [e.rule for e in errors] == ["schema"]
    assert errors[0].at.startswith("representations[0].bindings[6].holds"), "the list itself, not an unknown key"


@pytest.mark.parametrize("holds", [[], ["label"], ["code", "code"]])
def test_a_fragment_binding_follows_the_same_holds_rules(holds) -> None:
    good, bad = _example(), _example()
    item(good["representations"][0]["bindings"], "column", "pay_method").update(holds=["meaning", "code"], lang="zh")
    item(bad["representations"][0]["bindings"], "column", "pay_method")["holds"] = holds

    assert check_fragment(good, "f.json") == []
    (finding,) = check_fragment(bad, "f.json")
    assert finding.rule == "schema" and finding.at.startswith("representations[0].bindings[5].holds")


def test_holds_meaning_needs_a_code_set_on_the_binding_or_the_attribute(root: Path) -> None:
    mutate(
        root, "concepts/collection.yaml",
        lambda d: item(item(d["concepts"], "concept:fee_waiver")["attributes"], ATTRIBUTE).pop("code_set"),
    )

    errors = validate_catalog(load_catalog(root)).errors

    assert [(e.rule, e.at) for e in errors] == [("binding_holds_code_set", f"{WAIVER_TABLE}.reason_desc")]


def test_the_attributes_code_set_is_enough_for_holds(root: Path) -> None:
    """reason_desc names no code_sets: the attribute's code set is the one it holds."""
    binding = item(_waiver(json.loads((root / "mapping/collection.json").read_text()))["bindings"], "column", "reason_desc")
    assert "code_sets" not in binding

    assert validate_catalog(load_catalog(root)).errors == []


def test_lang_without_meaning_is_an_error(root: Path) -> None:
    _set(root, "reason_key", holds=["code"], lang="zh")

    errors = validate_catalog(load_catalog(root)).errors

    assert [(e.rule, e.at) for e in errors] == [("binding_lang", f"{WAIVER_TABLE}.reason_key")]


def test_a_key_needs_a_code_set_with_a_key_column(root: Path) -> None:
    _set(root, "reason_key", code_sets=["code:waiver_channel"])

    warnings = validate_catalog(load_catalog(root)).warnings

    found = [w for w in warnings if w.rule == "binding_key_without_key_column"]
    assert [w.at for w in found] == [f"{WAIVER_TABLE}.reason_key"]


def test_a_key_into_a_code_set_listing_values_is_a_warning(root: Path) -> None:
    """code:gender lists its values, so the catalog cannot translate a key: the warning."""
    _set(root, "reason_key", code_sets=["code:gender"])

    found = [w.at for w in validate_catalog(load_catalog(root)).warnings if w.rule == "binding_key_without_key_column"]

    assert found == [f"{WAIVER_TABLE}.reason_key"]


def test_a_lang_the_dictionary_lacks_is_a_warning(root: Path) -> None:
    _set(root, "reason_label", code_sets=["code:waiver_channel"], lang="en")

    warnings = validate_catalog(load_catalog(root)).warnings

    found = [w for w in warnings if w.rule == "binding_lang_unknown"]
    assert [w.at for w in found] == [f"{WAIVER_TABLE}.reason_label"]
    assert "'en'" in found[0].message


def test_a_lang_the_dictionary_has_is_not_a_warning(root: Path) -> None:
    _set(root, "reason_desc", lang="en")  # code:waiver_reason has an en meaning column

    report = validate_catalog(load_catalog(root))

    assert report.errors == []
    assert "binding_lang_unknown" not in rules(report.warnings)


def test_a_lang_is_not_checked_against_code_sets_listing_values(root: Path) -> None:
    _set(root, "reason_label", code_sets=["code:gender"], lang="en")

    report = validate_catalog(load_catalog(root))

    assert report.errors == []
    assert "binding_lang_unknown" not in rules(report.warnings)


# ------------------------------------------------------------------------------ build


def test_build_carries_holds_and_lang_after_code_sets(document: dict) -> None:
    bindings = item(document["representations"], "table", WAIVER_TABLE)["bindings"]
    mixed = item(bindings, "column", "reason_label")

    assert mixed["holds"] == ["meaning", "code"] and mixed["lang"] == "zh"
    keys = list(mixed)
    assert keys.index("code_sets") + 1 == keys.index("holds") == keys.index("lang") - 1
    assert item(bindings, "column", "reason_desc")["holds"] == ["meaning"]
    assert "holds" not in item(bindings, "column", "reason_cd")
    assert ontology_findings(document) == []


def test_holds_code_written_out_builds_the_same_bytes(tmp_path: Path, root: Path) -> None:
    plain, spelled = tmp_path / "plain", tmp_path / "spelled"
    assert main(["catalog", "build", str(root), "--out", str(plain)]) == 0
    _set(root, "reason_cd", holds=["code"])
    assert main(["catalog", "build", str(root), "--out", str(spelled)]) == 0

    assert (spelled / "ontology.json").read_bytes() == (plain / "ontology.json").read_bytes()


# ------------------------------------------------------------------------------ query


def test_query_column_says_what_each_column_stores(document: dict) -> None:
    desc, desc_text = _column(document, "reason_desc")
    key, key_text = _column(document, "reason_key")
    mixed, mixed_text = _column(document, "reason_label")

    assert (desc["holds"], desc["lang"]) == (["meaning"], "zh")
    assert "（存含义（zh））" in desc_text
    assert key["holds"] == ["key"] and "lang" not in key
    assert "（码值：查 豁免原因；存代理键）" in key_text
    assert "（码值：先查 豁免原因，查不到查 豁免渠道；存含义（zh）或码）" in mixed_text
    keys = list(mixed)
    assert keys.index("code_sets") + 1 == keys.index("holds") == keys.index("lang") - 1


def test_a_code_column_answers_as_before(document: dict) -> None:
    match, text = _column(document, "reason_cd")

    assert "holds" not in match and "lang" not in match
    head = text.splitlines()[0]
    assert head == (
        f"{WAIVER_TABLE}.reason_cd → 属性 豁免原因 {ATTRIBUTE}（概念 豁免）"
        "（码值：先查 豁免原因，查不到查 豁免渠道）"
    )


# ------------------------------------------------------------------------------ pages


def test_the_concept_page_says_what_each_column_stores(document: dict) -> None:
    page = render_catalog_pages(document)["concepts/fee_waiver.md"]
    row = next(line for line in page.splitlines() if line.startswith("| 豁免原因 "))

    assert f"`{WAIVER_TABLE}.reason_cd`（码值：先查 豁免原因，查不到查 豁免渠道）；" in row
    assert f"`{WAIVER_TABLE}.reason_desc`（存含义（zh））" in row
    assert f"`{WAIVER_TABLE}.reason_key`（码值：查 豁免原因；存代理键）" in row
    assert f"`{WAIVER_TABLE}.reason_label`（码值：先查 豁免原因，查不到查 豁免渠道；存含义（zh）或码）" in row


def test_the_code_sets_page_says_what_each_column_stores(document: dict) -> None:
    page = render_catalog_pages(document)["code_sets.md"]
    reason = page.split("## 豁免原因")[1].split("\n## ")[0]

    assert f"`{WAIVER_TABLE}.reason_cd`（先查 豁免原因，查不到查 豁免渠道）；" in reason
    assert f"`{WAIVER_TABLE}.reason_key`（查 豁免原因；存代理键）" in reason
    assert f"`{WAIVER_TABLE}.reason_label`（先查 豁免原因，查不到查 豁免渠道；存含义（zh）或码）" in reason


# ------------------------------------------------------------------------------ merge


def test_a_fragment_with_holds_merges_and_builds(tmp_path: Path) -> None:
    fragment = _example()
    item(fragment["representations"][0]["bindings"], "column", "pay_method").update(holds=["meaning", "code"])
    root = copy_demo(tmp_path)

    result = merge_fragments(load_catalog(root), [("f.json", fragment)])
    assert result.errors == [] and result.conflicts == []
    out = tmp_path / "merged"
    assert main(["catalog", "merge", str(root), str(_write(tmp_path / "f.json", fragment)), "--out", str(out)]) == 0

    built = build_ontology(load_catalog(out))
    rep = item(built["representations"], "table", "demo_dwd.dwd_lending_disbursement_di")
    assert item(rep["bindings"], "column", "pay_method")["holds"] == ["meaning", "code"]


def _write(path: Path, fragment: dict) -> Path:
    path.write_text(json.dumps(fragment, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
