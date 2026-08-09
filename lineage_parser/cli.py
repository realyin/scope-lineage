"""Minimal command line interface for the public Lineage Core."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .contract import write_lineage
from .metadata.schema_metadata import load_schema
from .metadata.target_table_metadata import load_target_table_metadata
from .scope.scope_builder import parse_all_scope_lineage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scope-lineage")
    subcommands = parser.add_subparsers(dest="command", required=True)
    parse_cmd = subcommands.add_parser("parse", help="Parse one SQL file into Core artifacts")
    parse_cmd.add_argument("--sql-file", required=True, help="Path to a SQL file")
    parse_cmd.add_argument("--task-name", help="Task name. Defaults to SQL file stem.")
    parse_cmd.add_argument("--out", required=True, help="Output directory")
    parse_cmd.add_argument("--schema", help="Optional CSV/JSON schema metadata")
    parse_cmd.add_argument(
        "--target-ddl-metadata",
        help="Optional target-table DDL/Schema metadata JSON file or directory",
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
        return _parse_file(args)
    parser.error(f"unknown command: {args.command}")
    return 2


def _parse_file(args: argparse.Namespace) -> int:
    sql_path = Path(args.sql_file)
    sql = sql_path.read_text(encoding="utf-8")
    task_name = args.task_name or sql_path.stem
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
    results = parse_all_scope_lineage(
        sql,
        task_name=task_name,
        schema=schema,
        target_metadata=target_metadata,
    )

    out_root = Path(args.out)
    for result in results:
        write_lineage(result, out_root / result.task_id.replace("#", "_"))

    failed = [result for result in results if result.parse_status == "failed"]
    print(
        f"Parsed {len(results)} statement(s) into {out_root} "
        f"(ok={len(results) - len(failed)}, failed={len(failed)})"
    )
    if not failed:
        return 0
    for result in failed:
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
    return 0 if args.allow_partial else 1


if __name__ == "__main__":
    raise SystemExit(main())
