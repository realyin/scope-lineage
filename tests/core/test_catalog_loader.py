"""Loading a catalog directory: which files count, which formats, and what may be missing."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scope_lineage.catalog import CatalogError, load_catalog, validate_catalog

from .catalog_demo import DEMO, copy_demo, rules, write_file

MANIFEST = {"doc_format": "catalog-yaml/1", "name": "tiny"}


def test_the_demo_loads_yaml_and_json_side_by_side() -> None:
    catalog = load_catalog(DEMO)

    assert catalog.name == "demo-lending"
    files = {document.file for document in catalog.documents}
    assert "mapping/collection.json" in files
    assert "concepts/party.yaml" in files
    assert "catalog.yaml" not in files  # the manifest is not an object file


def test_only_the_manifest_is_required(tmp_path: Path) -> None:
    write_file(tmp_path / "catalog.yaml", MANIFEST)

    report = validate_catalog(load_catalog(tmp_path))

    assert report.errors == []
    assert report.counts["concepts"] == 0
    assert report.counts["representations"] == 0


def test_a_directory_without_catalog_yaml_is_refused(tmp_path: Path) -> None:
    write_file(tmp_path / "domains.yaml", {"domains": []})

    with pytest.raises(CatalogError, match="catalog.yaml"):
        load_catalog(tmp_path)


def test_a_missing_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="not a directory"):
        load_catalog(tmp_path / "nowhere")


def test_two_manifests_are_refused(tmp_path: Path) -> None:
    write_file(tmp_path / "catalog.yaml", MANIFEST)
    write_file(tmp_path / "catalog.json", MANIFEST)

    with pytest.raises(CatalogError, match="more than one manifest"):
        load_catalog(tmp_path)


def test_yml_and_json_spellings_are_read(tmp_path: Path) -> None:
    write_file(tmp_path / "catalog.json", MANIFEST)
    write_file(
        tmp_path / "domains.yml",
        {"domains": [{"id": "domain:a", "name": "A", "description": "a"}]},
    )
    write_file(
        tmp_path / "domains.json",
        {"domains": [{"id": "domain:b", "name": "B", "description": "b"}]},
    )

    report = validate_catalog(load_catalog(tmp_path))

    assert report.errors == []
    assert report.counts["domains"] == 2


def test_a_json_only_catalog_needs_no_pyyaml(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "yaml", None)
    write_file(tmp_path / "catalog.json", MANIFEST)
    write_file(tmp_path / "terms.json", {"terms": []})

    assert load_catalog(tmp_path).name == "tiny"


def test_a_yaml_file_without_pyyaml_names_the_extra(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "yaml", None)

    with pytest.raises(CatalogError, match=r"PyYAML.*scope-lineage\[catalog\]"):
        load_catalog(DEMO)


def test_a_file_that_does_not_parse_is_an_error_not_a_crash(tmp_path: Path) -> None:
    root = copy_demo(tmp_path)
    (root / "terms.yaml").write_text("terms: [unclosed\n", encoding="utf-8")
    (root / "relations.yaml").unlink()
    (root / "relations.json").write_text("{not json", encoding="utf-8")

    report = validate_catalog(load_catalog(root))

    parse_errors = [error for error in report.errors if error.rule == "parse_error"]
    assert sorted(error.file for error in parse_errors) == ["relations.json", "terms.yaml"]


def test_an_unrecognised_file_is_a_warning(tmp_path: Path) -> None:
    root = copy_demo(tmp_path)
    write_file(root / "domain.yaml", {"domains": []})
    (root / "concepts" / "notes.txt").write_text("scratch", encoding="utf-8")

    report = validate_catalog(load_catalog(root))

    assert report.errors == []
    unknown = [w.file for w in report.warnings if w.rule == "unknown_file"]
    assert unknown == ["concepts/notes.txt", "domain.yaml"]


def test_yaml_dates_arrive_as_text(tmp_path: Path) -> None:
    root = copy_demo(tmp_path)
    path = root / "domains.yaml"
    path.write_text(
        path.read_text(encoding="utf-8") + "    notes: 2026-01-31\n", encoding="utf-8"
    )

    catalog = load_catalog(root)

    domains = next(d.data for d in catalog.documents if d.file == "domains.yaml")
    assert domains["domains"][-1]["notes"] == "2026-01-31"
    json.dumps(domains)  # everything loaded is plain JSON data
    assert rules(validate_catalog(catalog).errors) == []


def test_yaml_is_read_with_yaml_1_2_booleans(tmp_path: Path) -> None:
    """``on:`` is a constraint key and ``no`` is a code; YAML 1.1 reads both as booleans."""
    write_file(tmp_path / "catalog.yaml", MANIFEST)
    (tmp_path / "code_sets.yaml").write_text(
        "code_sets:\n"
        "  - id: code:answer\n"
        "    name: answer\n"
        "    values:\n"
        "      - {value: yes, meaning: agreed}\n"
        "      - {value: no, meaning: refused}\n"
        "      - {value: off, meaning: not asked, retired: true}\n",
        encoding="utf-8",
    )

    catalog = load_catalog(tmp_path)

    values = catalog.documents[0].data["code_sets"][0]["values"]
    assert [v["value"] for v in values] == ["yes", "no", "off"]
    assert values[2]["retired"] is True
    assert validate_catalog(catalog).errors == []
