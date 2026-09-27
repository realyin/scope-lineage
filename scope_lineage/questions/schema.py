"""The two packaged schemas, and every error of a document as ``{at, message}``.

Schema violations come first, then what a schema cannot say: ids repeat, a reference
answer is only whitespace. ``at`` is the path a reader looks for in the file.
"""

from __future__ import annotations

import json
import re
from importlib import resources

SET_FORMAT = "question-set/1"
GRADES_FORMAT = "question-grades/1"

_SCHEMA_FILES = {
    SET_FORMAT: "question-set.schema.json",
    GRADES_FORMAT: "question-grades.schema.json",
}
_loaded: dict[str, dict] = {}


def packaged_schema(doc_format: str) -> dict:
    """The schema shipped in ``scope_lineage/schemas`` for one document format."""
    if doc_format not in _loaded:
        resource = resources.files("scope_lineage.schemas").joinpath(_SCHEMA_FILES[doc_format])
        _loaded[doc_format] = json.loads(resource.read_text(encoding="utf-8"))
    return _loaded[doc_format]


def validate_document(document) -> list[dict]:
    """Every error of a ``question-set/1`` or ``question-grades/1`` document."""
    doc_format = document.get("doc_format") if isinstance(document, dict) else None
    if doc_format not in _SCHEMA_FILES:
        known = " or ".join(_SCHEMA_FILES)
        return [{"at": "doc_format", "message": f"doc_format must be {known}, got {doc_format!r}"}]
    errors = _schema_errors(document, doc_format)
    if errors:
        return errors
    items = "questions" if doc_format == SET_FORMAT else "grades"
    errors = _duplicate_ids(document[items], items)
    if doc_format == SET_FORMAT:
        errors += _blank_texts(document["questions"])
    return sorted(errors, key=lambda error: _order(error["at"]))


def _schema_errors(document, doc_format: str) -> list[dict]:
    from jsonschema import Draft7Validator

    validator = Draft7Validator(packaged_schema(doc_format))
    found = sorted(validator.iter_errors(document), key=lambda e: _order(_pointer(e.absolute_path)))
    return [{"at": _pointer(error.absolute_path), "message": error.message} for error in found]


def _duplicate_ids(items: list[dict], name: str) -> list[dict]:
    first: dict[str, int] = {}
    errors = []
    for index, item in enumerate(items):
        qid = item["id"]
        if qid in first:
            errors.append({
                "at": f"{name}[{index}].id",
                "message": f"id {qid!r} repeats {name}[{first[qid]}]",
            })
        else:
            first[qid] = index
    return errors


def _blank_texts(questions: list[dict]) -> list[dict]:
    return [
        {"at": f"questions[{index}].{key}", "message": f"{key} is blank"}
        for index, question in enumerate(questions)
        for key in ("text", "answer_key")
        if not question[key].strip()
    ]


def _pointer(path) -> str:
    text = ""
    for part in path:
        text += f"[{part}]" if isinstance(part, int) else (f".{part}" if text else str(part))
    return text


def _order(at: str) -> tuple:
    """Document order for a pointer: ``questions[10]`` after ``questions[2]``."""
    return tuple(
        (0, int(part), "") if part.isdigit() else (1, 0, part)
        for part in re.split(r"[.\[\]]+", at) if part
    )
