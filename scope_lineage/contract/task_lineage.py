"""Conversion and writing for the task-level Lineage 2.0 contract."""

from __future__ import annotations

import copy
import json
import shutil
import uuid
from pathlib import Path

from ..scope.task_lineage import TaskLineageResult
from .lineage import _diagnostics_summary
from .validation import (
    validate_cross_references,
    validate_diagnostics_document,
    validate_lineage_document,
)


def to_task_lineage_dict(result: TaskLineageResult) -> dict:
    state_graph = copy.deepcopy(result.table_state_graph)
    state_graph.pop("nodes_by_id", None)
    return {
        "schema_version": "2.0",
        "artifact_kind": "task_lineage",
        "task_id": result.task_id,
        "parse_status": result.parse_status,
        "syntax_status": result.syntax_status,
        "syntax_errors": copy.deepcopy(result.syntax_errors),
        "analysis_status": copy.deepcopy(result.analysis_status),
        "statement_sequence": copy.deepcopy(result.statements),
        "table_state_graph": state_graph,
        "final_table_states": copy.deepcopy(result.final_table_states),
        "statement_lineage": copy.deepcopy(result.statement_lineage),
        "end_to_end_lineage": copy.deepcopy(result.end_to_end_lineage),
        "task_dependencies": copy.deepcopy(result.task_dependencies),
        "diagnostics": copy.deepcopy(result.diagnostics),
    }


def to_task_lineage_json(result: TaskLineageResult, indent: int = 2) -> str:
    return json.dumps(
        to_task_lineage_dict(result),
        ensure_ascii=False,
        indent=indent,
        default=str,
    )


def write_task_lineage(
    result: TaskLineageResult,
    output_dir: str | Path,
    *,
    compact: bool = False,
) -> Path:
    requested_output_dir = Path(output_dir)
    if not requested_output_dir.name:
        raise ValueError("task output directory must name one owned directory")
    if requested_output_dir.is_symlink():
        raise ValueError("task output directory cannot be a symbolic link")
    resolved_output_dir = requested_output_dir.resolve(strict=False)
    resolved_output_dir.parent.mkdir(parents=True, exist_ok=True)
    _recover_interrupted_generation(resolved_output_dir)
    _validate_owned_output_directory(resolved_output_dir)

    lineage_data, diagnostics_data = _build_task_documents(result)
    documents = _serialize_task_documents(
        lineage_data,
        diagnostics_data,
        compact=compact,
    )
    token = uuid.uuid4().hex
    staging_dir = resolved_output_dir.parent / (
        f".{resolved_output_dir.name}.next-{token}"
    )
    previous_dir = resolved_output_dir.parent / (
        f".{resolved_output_dir.name}.previous-{token}"
    )
    try:
        staging_dir.mkdir()
        for name in ("lineage.json", "diagnostics.json"):
            _write_generation_file(staging_dir / name, documents[name])
        _publish_generation(staging_dir, resolved_output_dir, previous_dir)
    finally:
        _remove_generation_directory(staging_dir, ignore_errors=True)
    return requested_output_dir


def _build_task_documents(result: TaskLineageResult) -> tuple[dict, dict]:
    """Build and validate both documents before a new generation reaches disk."""
    data = to_task_lineage_dict(result)
    xref_errors = validate_cross_references(data)
    if xref_errors:
        raise ValueError(
            f"Cross-reference validation failed ({len(xref_errors)} errors):\n"
            + "\n".join(xref_errors[:5])
        )

    diagnostics_full = _canonical_diagnostics(data["diagnostics"])
    statement_diagnostics = {}
    lineage_data = copy.deepcopy(data)
    for statement_id, statement in lineage_data["statement_lineage"].items():
        full = _canonical_diagnostics(statement.get("diagnostics") or {})
        statement_diagnostics[statement_id] = full
        statement["diagnostics"] = _diagnostics_summary(full)
        # The v2 schema types statement_lineage values as bare objects, so the outer
        # validation below never looks inside them. Each nested document claims the v1
        # contract; hold it to that here, in the exact form it is about to be published
        # (i.e. with its diagnostics already summarized), or a drifted nested document
        # ships without complaint (NESTEDVAL-001).
        validate_lineage_document(statement)
    lineage_data["diagnostics"] = _diagnostics_summary(diagnostics_full)
    diagnostics_data = {
        "schema_version": "2.0",
        "task_id": result.task_id,
        "analysis_status": copy.deepcopy(result.analysis_status),
        **diagnostics_full,
        "statement_diagnostics": statement_diagnostics,
    }
    validate_lineage_document(lineage_data)
    validate_diagnostics_document(diagnostics_data)
    return lineage_data, diagnostics_data


def _serialize_task_documents(
    lineage_data: dict,
    diagnostics_data: dict,
    *,
    compact: bool,
) -> dict[str, str]:
    """Serialize the complete pair before creating a staging generation."""
    dump_options = {
        "ensure_ascii": False,
        "indent": None if compact else 2,
        "separators": (",", ":") if compact else None,
        "default": str,
    }
    return {
        "lineage.json": json.dumps(lineage_data, **dump_options),
        "diagnostics.json": json.dumps(diagnostics_data, **dump_options),
    }


def _write_generation_file(path: Path, content: str) -> None:
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(content)


def _replace_path(source: Path, target: Path) -> None:
    source.replace(target)


def _publish_generation(staging: Path, output: Path, previous: Path) -> None:
    """Switch directory generations, restoring the prior one if publication fails."""
    moved_previous = False
    try:
        if output.exists():
            _replace_path(output, previous)
            moved_previous = True
        _replace_path(staging, output)
    except Exception:  # noqa: BLE001 - rollback must cover injected and OS-level rename failures
        if moved_previous and previous.exists() and not output.exists():
            _replace_path(previous, output)
        raise
    _remove_generation_directory(previous, ignore_errors=True)


def _validate_owned_output_directory(output: Path) -> None:
    """Refuse to replace a directory containing files this writer does not own."""
    if not output.exists():
        return
    if output.is_symlink() or not output.is_dir():
        raise ValueError(f"task output path is not an owned directory: {output}")
    owned_names = {
        "lineage.json",
        "diagnostics.json",
        "mapping.md",
        "warnings.md",
    }
    unknown = sorted(path.name for path in output.iterdir() if path.name not in owned_names)
    if unknown:
        raise ValueError(
            f"task output directory contains entries not owned by the task writer: {unknown}"
        )


def _generation_directories(output: Path, kind: str) -> list[Path]:
    prefix = f".{output.name}.{kind}-"
    paths = []
    for path in output.parent.glob(f"{prefix}*"):
        suffix = path.name[len(prefix):]
        if len(suffix) == 32 and all(char in "0123456789abcdef" for char in suffix):
            paths.append(path)
    return sorted(paths, key=lambda path: path.stat().st_mtime_ns, reverse=True)


def _recover_interrupted_generation(output: Path) -> None:
    """Restore a prior complete generation after a process stopped between renames."""
    previous_dirs = _generation_directories(output, "previous")
    staging_dirs = _generation_directories(output, "next")
    if not output.exists() and previous_dirs:
        _replace_path(previous_dirs.pop(0), output)
    for path in [*previous_dirs, *staging_dirs]:
        _remove_generation_directory(path, ignore_errors=True)


def _remove_generation_directory(path: Path, *, ignore_errors: bool) -> None:
    if path.is_symlink():
        try:
            path.unlink()
        except OSError:
            if not ignore_errors:
                raise
        return
    if path.exists():
        shutil.rmtree(path, ignore_errors=ignore_errors)


def _canonical_diagnostics(diagnostics: dict) -> dict:
    result = copy.deepcopy(diagnostics)
    result["warnings"] = sorted(
        result.get("warnings") or [],
        key=lambda item: (
            str(item.get("statement_id") or ""),
            str(item.get("scope") or ""),
            str(item.get("type") or ""),
            str(item.get("msg") or ""),
        ),
    )
    result["lineage_fact_gaps"] = sorted(
        result.get("lineage_fact_gaps") or [],
        key=lambda item: (
            str(item.get("statement_id") or ""),
            str(item.get("evidence_path") or ""),
            str(item.get("gap_type") or ""),
            str(item.get("target_table") or ""),
        ),
    )
    return result
