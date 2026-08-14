"""Minimal command line interface for the public Lineage Core."""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .contract import write_lineage
from .metadata.schema_metadata import load_schema
from .metadata.target_table_metadata import load_target_table_metadata
from .scope.scope_builder import parse_all_scope_lineage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scope-lineage")
    subcommands = parser.add_subparsers(dest="command", required=True)
    parse_cmd = subcommands.add_parser(
        "parse",
        help="Parse SQL or exported task JSON into Core artifacts",
    )
    input_group = parse_cmd.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--sql-file", help="Path to one SQL file")
    input_group.add_argument(
        "--task-file",
        help="Path to one task JSON (meta/sql wrapper or legacy task_name/sql object)",
    )
    input_group.add_argument(
        "--input-dir",
        help="Directory of task JSON files; files are discovered recursively",
    )
    parse_cmd.add_argument(
        "--task-name",
        help="Override the task name for --sql-file or --task-file",
    )
    parse_cmd.add_argument("--out", required=True, help="Output directory")
    parse_cmd.add_argument(
        "--schema",
        help="Optional source-table schema file or rich-JSON directory (JSON preferred; CSV fallback)",
    )
    parse_cmd.add_argument(
        "--target-ddl-metadata",
        help="Optional authoritative target-table DDL/Schema JSON file or directory",
    )
    parse_cmd.add_argument(
        "--catalog-prefixes",
        help=(
            "Comma-separated leading catalog names to remove from table identities. "
            "Overrides SCOPE_LINEAGE_CATALOG_PREFIXES; by default catalogs are preserved."
        ),
    )
    parse_cmd.add_argument(
        "--sanitize-metadata-nul",
        action="store_true",
        help="Remove NUL bytes from metadata inputs and report provenance",
    )
    parse_cmd.add_argument(
        "--allow-partial",
        action="store_true",
        help="Return zero even when a statement produced parse_status=failed",
    )

    args = parser.parse_args(argv)
    if args.command == "parse":
        if args.input_dir and args.task_name:
            parser.error("--task-name cannot be used with --input-dir")
        with _catalog_prefix_override(args.catalog_prefixes):
            return _parse_inputs(args)
    parser.error(f"unknown command: {args.command}")
    return 2


@dataclass(frozen=True)
class _TaskInput:
    source_path: Path
    relative_parent: Path
    task_name: str
    sql: str
    task_dependencies: dict


@contextmanager
def _catalog_prefix_override(value: str | None):
    """Apply a CLI-only catalog policy without leaking it to later in-process calls."""
    if value is None:
        yield
        return
    key = "SCOPE_LINEAGE_CATALOG_PREFIXES"
    previous = os.environ.get(key)
    os.environ[key] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def _parse_inputs(args: argparse.Namespace) -> int:
    schema = (
        load_schema(args.schema, sanitize_nul=args.sanitize_metadata_nul)
        if args.schema
        else None
    )
    target_metadata = (
        load_target_table_metadata(
            args.target_ddl_metadata,
            sanitize_nul=args.sanitize_metadata_nul,
        )
        if args.target_ddl_metadata
        else None
    )
    out_root = Path(args.out)
    source_paths, input_root = _source_paths(args)
    result_count = 0
    failed_count = 0
    input_failed_count = 0
    claimed_output_dirs: dict[Path, Path] = {}

    for source_path in source_paths:
        try:
            task = _load_task_input(source_path, input_root, args.task_name)
            results = parse_all_scope_lineage(
                task.sql,
                task_name=task.task_name,
                schema=schema,
                target_metadata=target_metadata,
            )
            for result in results:
                result.task_dependencies = task.task_dependencies
                task_out = (
                    out_root
                    / task.relative_parent
                    / result.task_id.replace("#", "_")
                )
                claimed_by = claimed_output_dirs.get(task_out)
                if claimed_by is not None and claimed_by != source_path:
                    raise ValueError(
                        f"output directory collision: {task_out} is already used by "
                        f"{claimed_by}"
                    )
                claimed_output_dirs[task_out] = source_path
                write_lineage(result, task_out)
                result_count += 1
                if result.parse_status == "failed":
                    failed_count += 1
                    _print_parse_failure(result)
        except Exception as exc:
            input_failed_count += 1
            print(f"  FAILED {source_path}: {type(exc).__name__}: {exc}", file=sys.stderr)

    print(
        f"Parsed {result_count} statement(s) from {len(source_paths)} input(s) "
        f"into {out_root} "
        f"(ok={result_count - failed_count}, failed={failed_count}, "
        f"input_failed={input_failed_count})"
    )
    if not failed_count and not input_failed_count:
        return 0
    return 0 if args.allow_partial else 1


def _source_paths(args: argparse.Namespace) -> tuple[list[Path], Path | None]:
    if args.sql_file:
        return [Path(args.sql_file)], None
    if args.task_file:
        return [Path(args.task_file)], None
    input_root = Path(args.input_dir)
    if not input_root.is_dir():
        raise ValueError(f"task input directory does not exist: {input_root}")
    paths = sorted(input_root.rglob("*.json"))
    if not paths:
        raise ValueError(f"task input directory contains no JSON files: {input_root}")
    return paths, input_root


def _load_task_input(
    source_path: Path,
    input_root: Path | None,
    task_name_override: str | None,
) -> _TaskInput:
    relative_parent = (
        source_path.parent.relative_to(input_root)
        if input_root is not None
        else Path()
    )
    if source_path.suffix.lower() == ".sql":
        return _TaskInput(
            source_path=source_path,
            relative_parent=relative_parent,
            task_name=task_name_override or source_path.stem,
            sql=source_path.read_text(encoding="utf-8"),
            task_dependencies=_empty_task_dependencies("sql_file"),
        )

    document = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("task JSON top level must be an object")
    meta = document.get("meta")
    payload = meta if isinstance(meta, dict) else document
    sql = payload.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("task JSON must contain a non-empty string at meta.sql or sql")
    task_name = (
        task_name_override
        or _clean_value(payload.get("task_name"))
        or _clean_value(payload.get("task_id"))
        or source_path.stem
    )
    return _TaskInput(
        source_path=source_path,
        relative_parent=relative_parent,
        task_name=task_name,
        sql=sql,
        task_dependencies=_task_dependencies(document, source_path),
    )


def _task_dependencies(document: dict, source_path: Path) -> dict:
    meta = document.get("meta")
    if not isinstance(meta, dict):
        return _empty_task_dependencies("task_json_legacy")
    upstream = _dependency_items(
        meta.get("upstream_tasks"), "upstream", source_path
    )
    downstream = _dependency_items(
        meta.get("downstream_tasks"), "downstream", source_path
    )
    return {
        "upstream_tasks": upstream,
        "downstream_tasks": downstream,
        "source_summary": {
            "source_format": "task_info_meta",
            "upstream_count": len(upstream),
            "downstream_count": len(downstream),
            "has_declared_task_dependencies": bool(upstream or downstream),
        },
    }


def _dependency_items(records, direction: str, source_path: Path) -> list[dict]:
    items = []
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        task_name = _clean_value(record.get("task_name") or record.get("task_id"))
        if not task_name:
            continue
        items.append(
            {
                "dependency_id": f"taskdep:{direction}:{len(items) + 1:03d}",
                "direction": direction,
                "task_id": _clean_value(record.get("task_id")),
                "task_name": task_name,
                "task_group": _clean_value(record.get("task_group")),
                "project_name": _clean_value(record.get("project_name")),
                "dependency_type": "declared",
                "dependency_table": _clean_value(
                    record.get("dependency_table") or record.get("table")
                ),
                "source": f"task_info.meta.{direction}_tasks",
                "source_file": source_path.as_posix(),
                "raw_record": record,
            }
        )
    return items


def _empty_task_dependencies(source_format: str) -> dict:
    return {
        "upstream_tasks": [],
        "downstream_tasks": [],
        "source_summary": {
            "source_format": source_format,
            "upstream_count": 0,
            "downstream_count": 0,
            "has_declared_task_dependencies": False,
        },
    }


def _clean_value(value) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _print_parse_failure(result) -> None:
    reasons = [
        warning.msg
        for warning in result.diagnostics.warnings
        if warning.type == "LINEAGE_ERROR"
    ]
    print(
        f"  FAILED {result.task_id}: "
        f"{reasons[0] if reasons else 'scope build failed'}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    raise SystemExit(main())
