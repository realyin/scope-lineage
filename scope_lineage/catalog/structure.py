"""Stage one: every catalog file against its packaged JSON Schema."""

from __future__ import annotations

import json
from importlib import resources

from .model import FILE_KINDS, MANIFEST_SCHEMA, Catalog, Finding

_schemas: dict[str, dict] = {}


def packaged_schema(name: str) -> dict:
    """One of the catalog schemas shipped in ``scope_lineage/schemas``."""
    if name not in _schemas:
        resource = resources.files("scope_lineage.schemas").joinpath(f"{name}.schema.json")
        _schemas[name] = json.loads(resource.read_text(encoding="utf-8"))
    return _schemas[name]


def check_structure(catalog: Catalog) -> list[Finding]:
    findings: list[Finding] = []
    if catalog.manifest is not None or not _manifest_failed(catalog):
        findings += schema_findings(MANIFEST_SCHEMA, catalog.manifest, catalog.manifest_file)
    for document in catalog.documents:
        schema = FILE_KINDS[document.kind].schema
        findings += schema_findings(schema, document.data, document.file)
    return findings


def _manifest_failed(catalog: Catalog) -> bool:
    return any(problem.file == catalog.manifest_file for problem in catalog.problems)


def schema_findings(schema_name: str, data, file: str | None) -> list[Finding]:
    """Every schema violation in ``data``, in document order, one finding each."""
    from jsonschema import Draft7Validator

    validator = Draft7Validator(packaged_schema(schema_name))
    errors = sorted(validator.iter_errors(data), key=lambda e: _sort_key(e.absolute_path))
    return [Finding("schema", file, _pointer(error.absolute_path), _message(error)) for error in errors]


def _sort_key(path) -> tuple:
    return tuple((0, part, "") if isinstance(part, int) else (1, 0, part) for part in path)


def _pointer(path) -> str | None:
    """``concepts[2].attributes[0].category`` -- the path a reader looks for in the file."""
    text = ""
    for part in path:
        text += f"[{part}]" if isinstance(part, int) else (f".{part}" if text else str(part))
    return text or None


def _message(error) -> str:
    if error.validator is None or error.schema is False:
        return f"{_leaf(error.absolute_path)} is not allowed here"
    if error.validator == "additionalProperties":
        return error.message.replace("Additional properties", "unknown key(s)")
    if error.validator in ("oneOf", "anyOf"):
        return f"{error.instance!r} matches none of the allowed shapes"
    return error.message


def _leaf(path) -> str:
    parts = list(path)
    return repr(parts[-1]) if parts else "this value"
