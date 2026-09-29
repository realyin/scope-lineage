"""``scope-lineage catalog merge``: fragments into a copy of a catalog, conflicts reported."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scope_lineage.catalog import load_catalog, merge_fragments
from scope_lineage.cli import main

from .catalog_demo import DEMO, copy_demo, item, read_file
from .test_catalog_fragment import EXAMPLE, _example

TABLE = "demo_dwd.dwd_lending_disbursement_di"


def _write(path: Path, fragment: dict) -> Path:
    path.write_text(json.dumps(fragment, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _merge(*argv) -> int:
    return main(["catalog", "merge", *[str(arg) for arg in argv]])


# ------------------------------------------------------------------ the happy path


def test_the_example_merges_into_a_copy_and_validates(tmp_path: Path, capsys) -> None:
    before = _snapshot(DEMO)
    out = tmp_path / "merged"

    assert _merge(DEMO, EXAMPLE, "--out", out) == 0

    assert _snapshot(DEMO) == before, "the base catalog is never written"
    printed = capsys.readouterr().out
    assert "0 error(s)" in printed
    assert "0 conflict(s), 0 unknown concept(s)" in printed
    mapping = read_file(out / "mapping" / "disbursement.yaml")
    assert [rep["table"] for rep in mapping["representations"]] == [TABLE]
    lending = read_file(out / "concepts" / "lending.yaml")
    attributes = item(lending["concepts"], "concept:disbursement")["attributes"]
    assert [attr["id"] for attr in attributes] == [
        "attr:disbursement.disbursed_at",
        "attr:disbursement.amount",
        "attr:disbursement.pay_method",
    ]
    assert item(read_file(out / "code_sets.yaml")["code_sets"], "code:pay_method")
    assert item(read_file(out / "constraints.yaml")["constraints"], "cons:disbursed_amount_positive")
    terms = read_file(out / "terms.yaml")["terms"]
    assert [t["term"] for t in terms if t["refers_to"] == "concept:disbursement"] == ["放款", "出款"]


def test_untouched_files_are_copied_byte_for_byte(tmp_path: Path) -> None:
    out = tmp_path / "merged"
    assert _merge(DEMO, EXAMPLE, "--out", out) == 0

    for name in ("identifiers.yaml", "relations.yaml", "concepts/party.yaml", "mapping/party.yaml"):
        assert (out / name).read_bytes() == (DEMO / name).read_bytes(), name


def test_the_report_counts_what_was_added_and_prints_the_notes(tmp_path: Path, capsys) -> None:
    assert _merge(DEMO, EXAMPLE, "--out", tmp_path / "merged") == 0

    printed = capsys.readouterr().out
    assert "attribute=1" in printed  # disbursement.amount is already there, identical
    assert "code_set=1" in printed
    assert "representation=1" in printed
    assert "1 unchanged" in printed
    assert "remark holds free text" in printed


def test_the_coverage_report_counts_bindings_per_table(tmp_path: Path, capsys) -> None:
    assert _merge(DEMO, EXAMPLE, "--out", tmp_path / "merged") == 0

    printed = capsys.readouterr().out
    line = next(line for line in printed.splitlines() if TABLE in line and "concept:" in line)
    assert "concept:disbursement" in line
    assert "event_detail" in line
    assert "8 column(s)" in line
    assert "attribute=3" in line
    assert "foreign_identifier=2" in line
    assert "identifier=1" in line
    assert "technical=1" in line
    assert "unmapped=1" in line


def test_merging_the_same_fragment_twice_changes_nothing_more(tmp_path: Path, capsys) -> None:
    once, twice = tmp_path / "once", tmp_path / "twice"
    assert _merge(DEMO, EXAMPLE, "--out", once) == 0
    assert _merge(DEMO, EXAMPLE, EXAMPLE, "--out", twice) == 0

    assert _snapshot(once) == _snapshot(twice)
    assert _merge(once, EXAMPLE, "--out", tmp_path / "third") == 0
    assert _snapshot(tmp_path / "third") == _snapshot(once)


def test_the_merge_is_deterministic(tmp_path: Path) -> None:
    assert _merge(DEMO, EXAMPLE, "--out", tmp_path / "a") == 0
    assert _merge(DEMO, EXAMPLE, "--out", tmp_path / "b") == 0

    assert _snapshot(tmp_path / "a") == _snapshot(tmp_path / "b")


# ------------------------------------------------------------------ conflicts and errors


def test_same_id_different_content_is_a_conflict_and_the_later_is_not_applied(
    tmp_path: Path, capsys
) -> None:
    later = _example()
    later["group"] = "other"
    later["code_sets"][0]["values"].append({"value": "CASH", "meaning": "cash"})
    later_path = _write(tmp_path / "later.json", later)
    out = tmp_path / "merged"

    assert _merge(DEMO, EXAMPLE, later_path, "--out", out) == 1

    printed = capsys.readouterr().out
    conflict = next(line for line in printed.splitlines() if "code:pay_method" in line)
    assert "conflict" in conflict
    assert "later.json" in conflict
    values = item(read_file(out / "code_sets.yaml")["code_sets"], "code:pay_method")["values"]
    assert [value["value"] for value in values] == ["BANK", "WALLET"]


def test_a_conflict_with_the_base_catalog_is_reported(tmp_path: Path, capsys) -> None:
    fragment = _example()
    fragment["attributes"]["concept:disbursement"][0]["unit"] = "USD"
    fragment["representations"][0]["table"] = "demo_dwd.dwd_lending_loan_df"
    fragment["representations"][0]["bindings"] = []
    out = tmp_path / "merged"

    assert _merge(DEMO, _write(tmp_path / "f.json", fragment), "--out", out) == 1

    printed = capsys.readouterr().out
    assert any("attr:disbursement.amount" in l and "conflict" in l for l in printed.splitlines())
    assert any(
        "demo_dwd.dwd_lending_loan_df" in l and "conflict" in l for l in printed.splitlines()
    )
    assert not (out / "mapping" / "disbursement.yaml").exists()
    lending = read_file(out / "concepts" / "lending.yaml")
    amount = item(item(lending["concepts"], "concept:disbursement")["attributes"], "attr:disbursement.amount")
    assert amount["unit"] == "CNY"


def test_an_attribute_id_declared_on_another_concept_is_a_conflict(tmp_path: Path, capsys) -> None:
    fragment = {
        "doc_format": "catalog-fragment/1",
        "group": "g",
        "attributes": {"concept:repayment": [_example()["attributes"]["concept:disbursement"][0]]},
    }

    assert _merge(DEMO, _write(tmp_path / "f.json", fragment), "--out", tmp_path / "m") == 1

    printed = capsys.readouterr().out
    line = next(l for l in printed.splitlines() if "attr:disbursement.amount" in l)
    assert "concept:disbursement" in line


def test_attributes_for_an_unknown_concept_are_an_error(tmp_path: Path, capsys) -> None:
    fragment = _example()
    fragment["attributes"] = {"concept:ghost": fragment["attributes"]["concept:disbursement"]}
    fragment["representations"] = []
    out = tmp_path / "merged"

    assert _merge(DEMO, _write(tmp_path / "f.json", fragment), "--out", out) == 1

    printed = capsys.readouterr().out
    assert any("concept:ghost" in l and "unknown_concept" in l for l in printed.splitlines())
    assert "concept:ghost" not in (out / "concepts" / "lending.yaml").read_text(encoding="utf-8")


def test_terms_are_deduplicated_by_term_and_target(tmp_path: Path, capsys) -> None:
    fragment = {
        "doc_format": "catalog-fragment/1",
        "group": "g",
        "terms": [
            {"term": "客户", "refers_to": "concept:customer", "preferred": True},
            {"term": "用户", "refers_to": "concept:customer", "preferred": True},
        ],
    }
    out = tmp_path / "merged"

    assert _merge(DEMO, _write(tmp_path / "f.json", fragment), "--out", out) == 1

    printed = capsys.readouterr().out
    assert any("用户" in l and "conflict" in l for l in printed.splitlines())
    assert (out / "terms.yaml").read_bytes() == (DEMO / "terms.yaml").read_bytes()


def test_validation_errors_after_the_merge_exit_one(tmp_path: Path, capsys) -> None:
    fragment = _example()
    fragment["representations"][0]["bindings"][3]["ref"] = "attr:disbursement.missing"

    assert _merge(DEMO, _write(tmp_path / "f.json", fragment), "--out", tmp_path / "m") == 1

    printed = capsys.readouterr().out
    assert "1 error(s)" in printed
    assert "attr:disbursement.missing" in printed


# ------------------------------------------------------------------ inputs and outputs


def test_out_equal_to_base_is_refused_without_in_place(tmp_path: Path, capsys) -> None:
    base = copy_demo(tmp_path)
    before = _snapshot(base)

    assert _merge(base, EXAMPLE, "--out", base) == 2

    assert "--in-place" in capsys.readouterr().err
    assert _snapshot(base) == before


def test_in_place_writes_into_the_base(tmp_path: Path) -> None:
    base = copy_demo(tmp_path)

    assert _merge(base, EXAMPLE, "--in-place") == 0

    assert (base / "mapping" / "disbursement.yaml").is_file()


def test_a_non_empty_out_directory_is_refused(tmp_path: Path, capsys) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "keep.txt").write_text("x", encoding="utf-8")

    assert _merge(DEMO, EXAMPLE, "--out", out) == 2

    assert "not empty" in capsys.readouterr().err
    assert [path.name for path in out.iterdir()] == ["keep.txt"]


def test_an_out_directory_inside_the_base_is_refused(tmp_path: Path) -> None:
    base = copy_demo(tmp_path)

    assert _merge(base, EXAMPLE, "--out", base / "merged") == 2
    assert not (base / "merged").exists()


def test_a_fragment_that_fails_its_schema_writes_nothing(tmp_path: Path, capsys) -> None:
    fragment = _example()
    del fragment["representations"][0]["grain"]
    out = tmp_path / "merged"

    assert _merge(DEMO, _write(tmp_path / "f.json", fragment), "--out", out) == 1

    assert "representations[0]" in capsys.readouterr().err
    assert not out.exists()


def test_an_unreadable_fragment_exits_two(tmp_path: Path, capsys) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")

    assert _merge(DEMO, bad, "--out", tmp_path / "m") == 2
    assert _merge(DEMO, tmp_path / "missing.json", "--out", tmp_path / "m") == 2
    assert not (tmp_path / "m").exists()


def test_an_unreadable_base_exits_two(tmp_path: Path) -> None:
    assert _merge(tmp_path / "nowhere", EXAMPLE, "--out", tmp_path / "m") == 2


def test_a_base_whose_files_fail_their_schemas_is_not_merged(tmp_path: Path, capsys) -> None:
    base = copy_demo(tmp_path)
    (base / "terms.yaml").write_text("terms:\n  - {term: x}\n", encoding="utf-8")

    assert _merge(base, EXAMPLE, "--out", tmp_path / "m") == 1

    assert "terms.yaml" in capsys.readouterr().err
    assert not (tmp_path / "m").exists()


# ------------------------------------------------------------------ file forms


def test_yaml_1_2_booleans_survive_a_rewrite(tmp_path: Path) -> None:
    base = copy_demo(tmp_path)
    codes = base / "code_sets.yaml"
    codes.write_text(
        codes.read_text(encoding="utf-8")
        + "\n  - id: code:switch\n    name: 开关\n    values:\n"
        + "      - {value: on, meaning: switched on}\n      - {value: no, meaning: none}\n",
        encoding="utf-8",
    )
    out = tmp_path / "merged"

    assert _merge(base, EXAMPLE, "--out", out) == 0

    switch = item(read_file(out / "code_sets.yaml")["code_sets"], "code:switch")
    assert [value["value"] for value in switch["values"]] == ["on", "no"]
    constraint = item(read_file(out / "constraints.yaml")["constraints"], "cons:principal_positive")
    assert constraint["on"] == "attr:loan.principal"


def test_a_representation_joins_an_existing_json_mapping_file(tmp_path: Path) -> None:
    fragment = _example()
    fragment["group"] = "collection"
    out = tmp_path / "merged"

    assert _merge(DEMO, _write(tmp_path / "f.json", fragment), "--out", out) == 0

    mapping = json.loads((out / "mapping" / "collection.json").read_text(encoding="utf-8"))
    assert [rep["table"] for rep in mapping["representations"]] == [
        "demo_dwd.dwd_collection_fee_waiver_di",
        TABLE,
    ]
    assert not (out / "mapping" / "collection.yaml").exists()


def test_a_missing_top_level_file_is_created(tmp_path: Path) -> None:
    base = copy_demo(tmp_path)
    (base / "constraints.yaml").unlink()
    out = tmp_path / "merged"

    assert _merge(base, EXAMPLE, "--out", out) == 0

    constraints = read_file(out / "constraints.yaml")["constraints"]
    assert [c["id"] for c in constraints] == ["cons:disbursed_amount_positive"]


def _json_demo(tmp_path: Path) -> Path:
    """The demo catalog with every file rewritten as JSON, the manifest included."""
    base = copy_demo(tmp_path)
    for path in sorted(base.rglob("*.yaml")):
        path.with_suffix(".json").write_text(
            json.dumps(read_file(path), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        path.unlink()
    return base


def test_a_json_catalog_gets_json_files_and_never_needs_pyyaml(
    tmp_path: Path, monkeypatch
) -> None:
    base = _json_demo(tmp_path)
    (base / "constraints.json").unlink()
    out = tmp_path / "merged"
    monkeypatch.setitem(sys.modules, "yaml", None)

    assert _merge(base, EXAMPLE, "--out", out) == 0

    constraints = json.loads((out / "constraints.json").read_text(encoding="utf-8"))
    assert [c["id"] for c in constraints["constraints"]] == ["cons:disbursed_amount_positive"]
    mapping = json.loads((out / "mapping" / "disbursement.json").read_text(encoding="utf-8"))
    assert [rep["table"] for rep in mapping["representations"]] == [TABLE]
    assert not list(out.rglob("*.yaml"))


def test_new_files_follow_the_manifest_not_the_mapping_files_beside_them(tmp_path: Path) -> None:
    # the demo's manifest is YAML while one mapping file is JSON: the manifest decides
    result = merge_fragments(load_catalog(DEMO), [("f.json", _example())])

    assert "mapping/disbursement.yaml" in result.changed


def test_merge_fragments_reports_without_writing(tmp_path: Path) -> None:
    catalog = load_catalog(DEMO)

    result = merge_fragments(catalog, [("f.json", _example())])

    assert result.conflicts == [] and result.errors == []
    assert result.added["attribute"] == 1
    assert result.unchanged == 1
    assert sorted(result.changed) == [
        "code_sets.yaml",
        "concepts/lending.yaml",
        "constraints.yaml",
        "mapping/disbursement.yaml",
        "terms.yaml",
    ]
    assert result.tables == [TABLE]
