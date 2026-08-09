"""Schema and referential validation for Lineage contract documents."""

from __future__ import annotations

import json
from importlib import resources

from ..scope.scope_types import CONSTANT_SCOPE_ID, SYSTEM_SCOPE_ID


_schema_cache: dict[str, dict] = {}


def _load_schema() -> dict:
    return _load_packaged_schema("lineage.schema.json")


def _load_packaged_schema(name: str) -> dict:
    if name not in _schema_cache:
        schema_resource = resources.files("lineage_parser.schemas").joinpath(name)
        _schema_cache[name] = json.loads(schema_resource.read_text(encoding="utf-8"))
    # Validation libraries do not mutate schemas, and callers that need a modified test copy
    # already use copy.deepcopy. Returning a JSON round-trip keeps the old isolation contract.
    return json.loads(json.dumps(_schema_cache[name]))


def validate_lineage_document(document: dict) -> dict:
    """Validate an already-built Lineage document and return it unchanged."""
    import jsonschema

    jsonschema.validate(document, _load_schema())
    return document


def validate_diagnostics_document(document: dict) -> dict:
    """Validate an already-built diagnostics companion document."""
    import jsonschema

    jsonschema.validate(document, _load_packaged_schema("diagnostics.schema.json"))
    return document


def validate_cross_references(data: dict) -> list[str]:
    """Return references to scope IDs that do not exist in the document graph."""
    errors: list[str] = []
    known_scopes: set[str] = set(data.get("scopes", {}).keys())
    all_nodes: set[str] = set(data.get("scope_graph", {}).get("nodes", []))
    valid_ids = known_scopes | all_nodes | {CONSTANT_SCOPE_ID, SYSTEM_SCOPE_ID}

    for edge in data.get("scope_graph", {}).get("edges", []):
        for key in ("from", "to"):
            scope_id = edge.get(key)
            if scope_id and scope_id not in valid_ids:
                errors.append(
                    f"scope_graph edge {key}={scope_id!r} not in known scopes/nodes"
                )

    for scope_id, scope_data in data.get("scopes", {}).items():
        for column in scope_data.get("columns", []):
            for source in column.get("sources", []):
                source_id = source.get("scope")
                if source_id and source_id not in valid_ids and source_id != "UNKNOWN":
                    errors.append(
                        f"scope={scope_id!r} col={column.get('name')!r} "
                        f"source scope={source_id!r} not in known scopes/nodes"
                    )
    return errors
