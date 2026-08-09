"""Public versioning and mandatory-validation behavior for Core artifacts."""

from __future__ import annotations

import copy
import json
from importlib import resources

import jsonschema
import pytest

from lineage_parser.contract import (
    to_lineage_dict,
    validate_diagnostics_document,
    validate_lineage_document,
    write_lineage,
)
from lineage_parser.scope.scope_builder import parse_scope_lineage


def _lineage() -> dict:
    return to_lineage_dict(
        parse_scope_lineage(
            "INSERT INTO mart.t SELECT id FROM ods.source",
            "contract_version",
            schema={"ods.source": ["id"]},
        )
    )


@pytest.mark.parametrize("version", [None, "2.0", "unknown"])
def test_lineage_rejects_missing_or_unknown_contract_version(version: str | None) -> None:
    document = _lineage()
    if version is None:
        document.pop("schema_version")
    else:
        document["schema_version"] = version
    with pytest.raises(jsonschema.ValidationError):
        validate_lineage_document(document)


def test_lineage_one_x_accepts_additive_optional_fields() -> None:
    document = _lineage()
    document["future_optional_observation"] = {"available": True}
    assert validate_lineage_document(document) is document


def test_diagnostics_contract_requires_version_and_accepts_additions() -> None:
    document = {
        "schema_version": "1.0",
        "warnings": [],
        "future_optional_observation": 1,
    }
    assert validate_diagnostics_document(document) is document
    invalid = copy.deepcopy(document)
    invalid.pop("schema_version")
    with pytest.raises(jsonschema.ValidationError):
        validate_diagnostics_document(invalid)


def test_writer_validates_the_documents_that_are_actually_written(tmp_path) -> None:
    result = parse_scope_lineage(
        "INSERT INTO mart.t SELECT id FROM ods.source",
        "written_contract",
        schema={"ods.source": ["id"]},
    )
    output = write_lineage(result, tmp_path)
    lineage = json.loads((output / "lineage.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((output / "diagnostics.json").read_text(encoding="utf-8"))

    assert lineage["schema_version"] == "1.0"
    assert diagnostics["schema_version"] == "1.0"
    validate_lineage_document(lineage)
    validate_diagnostics_document(diagnostics)


@pytest.mark.parametrize("name", ["lineage.schema.json", "diagnostics.schema.json"])
def test_contract_schemas_are_loadable_as_package_resources(name: str) -> None:
    schema = json.loads(
        resources.files("lineage_parser.schemas").joinpath(name).read_text(encoding="utf-8")
    )
    assert schema["type"] == "object"
