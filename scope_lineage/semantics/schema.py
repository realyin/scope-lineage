"""The two packaged JSON Schemas of this package, and violations as ``{at, message}``."""

from __future__ import annotations

import json
from importlib import resources

DOC_FORMAT = "table-semantics/1"
CONFIRMATIONS_FORMAT = "semantic-confirmations/1"

_SCHEMA_FILES = {
    DOC_FORMAT: "table-semantics.schema.json",
    CONFIRMATIONS_FORMAT: "semantic-confirmations.schema.json",
}
_loaded: dict[str, dict] = {}


def packaged_schema(doc_format: str) -> dict:
    """The schema shipped in ``scope_lineage/schemas`` for one document format."""
    if doc_format not in _loaded:
        resource = resources.files("scope_lineage.schemas").joinpath(_SCHEMA_FILES[doc_format])
        _loaded[doc_format] = json.loads(resource.read_text(encoding="utf-8"))
    return _loaded[doc_format]


def schema_errors(document, doc_format: str) -> list[dict]:
    """Every violation of ``doc_format``'s schema, in document order.

    ``at`` is the path a reader looks for in the file (``columns[2].category``), empty
    for the document itself; ``message`` says what is wrong there.
    """
    from jsonschema import Draft7Validator

    validator = Draft7Validator(packaged_schema(doc_format))
    errors = sorted(validator.iter_errors(document), key=lambda e: _sort_key(e.absolute_path))
    return [{"at": _pointer(error.absolute_path), "message": _message(error)} for error in errors]


def _sort_key(path) -> tuple:
    return tuple((0, part, "") if isinstance(part, int) else (1, 0, part) for part in path)


def _pointer(path) -> str:
    text = ""
    for part in path:
        text += f"[{part}]" if isinstance(part, int) else (f".{part}" if text else str(part))
    return text


def _message(error) -> str:
    if error.validator == "additionalProperties":
        return error.message.replace("Additional properties", "unknown key(s)")
    if error.validator == "oneOf":
        return "exactly one of `task` or `tasks` is required"
    return error.message
