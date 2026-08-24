#!/usr/bin/env python3
"""Targeted extraction from scope-lineage artifacts.

A lineage.json can be large; an agent that reads the whole file into its context wastes
it and still has to find the needle. This script pulls only the answer out. Three
subcommands, stdlib only, Python 3.9+:

  summary <task_dir | lineage.json>          one task's status, statements, targets, gaps
  chain   [--expanded] <db.table.column> <path...>
                                             how one written field is derived, step by step
  impact  <db.table[.column]> <root>         who reads this table/column, across artifacts

Paths may be task artifact directories (containing lineage.json), lineage.json files,
or (for impact) a root directory that is scanned recursively. Exit 0 on success (even
when the answer is "not found" -- that IS the answer), 2 on usage/IO errors.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path


_EXPRESSION_PREVIEW_CHARS = 500


def _candidate_lineage_paths(paths: list[str]) -> Iterator[Path]:
    for raw in paths:
        path = Path(raw)
        candidates: list[Path]
        if path.is_file():
            candidates = [path]
        elif path.is_dir():
            direct = path / "lineage.json"
            candidates = [direct] if direct.is_file() else sorted(path.rglob("lineage.json"))
        else:
            print(f"path does not exist: {path}", file=sys.stderr)
            raise SystemExit(2)
        for candidate in candidates:
            yield candidate


def _iter_task_docs(
    paths: list[str],
    stats: dict[str, int],
) -> Iterator[tuple[Path, dict]]:
    """Yield one document at a time so corpus scans do not retain prior artifacts."""
    for candidate in _candidate_lineage_paths(paths):
        try:
            document = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"cannot read {candidate}: {exc}", file=sys.stderr)
            continue
        if document.get("artifact_kind") == "task_lineage":
            stats["documents"] = stats.get("documents", 0) + 1
            yield candidate, document
        elif document.get("schema_version") == "1.0":
            stats["stale"] = stats.get("stale", 0) + 1


class _JsonByteReader:
    """Small JSON scanner used to skip large top-level values without decoding them."""

    def __init__(self, path: Path):
        self._handle = path.open("rb")
        self._buffer = b""
        self._position = 0

    def close(self) -> None:
        self._handle.close()

    def _fill(self) -> bool:
        if self._position < len(self._buffer):
            return True
        self._buffer = self._handle.read(64 * 1024)
        self._position = 0
        return bool(self._buffer)

    def peek(self) -> int | None:
        return self._buffer[self._position] if self._fill() else None

    def get(self) -> int:
        value = self.peek()
        if value is None:
            raise ValueError("unexpected end of JSON")
        self._position += 1
        return value

    def skip_whitespace(self) -> None:
        while self.peek() in {9, 10, 13, 32}:
            self.get()

    def expect(self, value: int) -> None:
        self.skip_whitespace()
        actual = self.get()
        if actual != value:
            raise ValueError(f"expected {chr(value)!r}, found {chr(actual)!r}")

    def read_string(self) -> str:
        self.skip_whitespace()
        if self.peek() != 34:
            raise ValueError("expected JSON string")
        return json.loads(self.read_value(store=True).decode("utf-8"))

    def read_value(self, *, store: bool) -> bytes:
        self.skip_whitespace()
        first = self.peek()
        if first is None:
            raise ValueError("missing JSON value")
        captured = bytearray()

        def take() -> int:
            value = self.get()
            if store:
                captured.append(value)
            return value

        if first == 34:
            escaped = False
            take()
            while True:
                value = take()
                if escaped:
                    escaped = False
                elif value == 92:
                    escaped = True
                elif value == 34:
                    return bytes(captured)

        if first in {91, 123}:
            closing = {91: 93, 123: 125}
            stack: list[int] = []
            in_string = False
            escaped = False
            while True:
                value = take()
                if in_string:
                    if escaped:
                        escaped = False
                    elif value == 92:
                        escaped = True
                    elif value == 34:
                        in_string = False
                    continue
                if value == 34:
                    in_string = True
                elif value in closing:
                    stack.append(closing[value])
                elif stack and value == stack[-1]:
                    stack.pop()
                    if not stack:
                        return bytes(captured)

        while self.peek() not in {44, 125, None}:
            take()
        return bytes(captured).rstrip()


_SUMMARY_TOP_LEVEL_FIELDS = {
    "analysis_status",
    "artifact_kind",
    "diagnostics",
    "final_table_states",
    "parse_status",
    "schema_version",
    "statement_sequence",
    "syntax_status",
    "task_id",
}


def _read_selected_top_level(path: Path, fields: set[str]) -> dict:
    reader = _JsonByteReader(path)
    selected: dict[str, object] = {}
    try:
        reader.expect(123)
        reader.skip_whitespace()
        if reader.peek() == 125:
            reader.get()
            return selected
        while True:
            key = reader.read_string()
            reader.expect(58)
            raw = reader.read_value(store=key in fields)
            if key in fields:
                selected[key] = json.loads(raw.decode("utf-8"))
            reader.skip_whitespace()
            delimiter = reader.get()
            if delimiter == 125:
                return selected
            if delimiter != 44:
                raise ValueError("expected ',' or '}' in top-level object")
    finally:
        reader.close()


def _iter_task_summaries(
    paths: list[str],
    stats: dict[str, int],
) -> Iterator[tuple[Path, dict]]:
    for candidate in _candidate_lineage_paths(paths):
        try:
            document = _read_selected_top_level(
                candidate,
                _SUMMARY_TOP_LEVEL_FIELDS,
            )
        except (OSError, ValueError) as exc:
            print(f"cannot read {candidate}: {exc}", file=sys.stderr)
            continue
        if document.get("artifact_kind") == "task_lineage":
            stats["documents"] = stats.get("documents", 0) + 1
            yield candidate, document
        elif document.get("schema_version") == "1.0":
            stats["stale"] = stats.get("stale", 0) + 1


def _report_stale(stale: int) -> None:
    if stale:
        print(f"note: skipped {stale} statement document(s) (schema_version 1.0) -- "
              "these look like artifacts from scope-lineage < 0.2.0; re-parse with the "
              "current version to get task documents")


def _split_column_ref(ref: str) -> tuple[str, str]:
    table, _, column = ref.rpartition(".")
    return table, column


def _full_diagnostics(path: Path, summary: dict) -> dict | None:
    name = summary.get("full_diagnostics_file") or "diagnostics.json"
    candidate = path.parent / str(name)
    try:
        document = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return document if isinstance(document, dict) else None


# ---------------------------------------------------------------- summary


def cmd_summary(args: list[str]) -> int:
    stats: dict[str, int] = {}
    for path, doc in _iter_task_summaries(args or ["."], stats):
        print(f"task: {doc.get('task_id')}  ({path})")
        print(f"  parse_status: {doc.get('parse_status')}  syntax_status: {doc.get('syntax_status')}")
        analysis = doc.get("analysis_status") or {}
        blocking_reasons = analysis.get("blocking_reasons") or []
        print(f"  analysis_status: {analysis.get('status')}"
              + (f"  blocking_reasons: {', '.join(blocking_reasons)}" if blocking_reasons else ""))
        for statement in doc.get("statement_sequence") or []:
            print(
                f"  {statement.get('statement_id')}: {statement.get('stmt_kind')}"
                f" [{statement.get('category')}] -> {statement.get('model_status')}"
            )
        finals = doc.get("final_table_states") or {}
        if finals:
            print(f"  final tables: {', '.join(sorted(finals))}")
        diagnostics = doc.get("diagnostics") or {}
        warning_types = diagnostics.get("warning_types") or {}
        warning_count = int(diagnostics.get("warning_count") or 0)
        gap_types = diagnostics.get("lineage_fact_gap_types") or {}
        gap_count = int(diagnostics.get("lineage_fact_gap_count") or 0)
        print(f"  warnings: {warning_count}"
              + (f"  ({', '.join(f'{k}x{v}' for k, v in sorted(warning_types.items()))})" if warning_types else ""))
        gap_suffix = (
            f"  ({', '.join(f'{k}x{v}' for k, v in sorted(gap_types.items()))})"
            if gap_types
            else ""
        )
        if gap_count:
            full = _full_diagnostics(path, diagnostics)
            root_gap_count = None if full is None else sum(
                gap.get("root_impact") is True
                for gap in full.get("lineage_fact_gaps") or []
                if isinstance(gap, dict)
            )
            root_text = "unknown (diagnostics.json unavailable)" if root_gap_count is None else str(root_gap_count)
            gap_suffix += f"  root_impact: {root_text}"
        print(f"  fact_gaps: {gap_count}{gap_suffix}")
    _report_stale(stats.get("stale", 0))
    if not stats.get("documents"):
        print("no task lineage.json found")
    return 0


# ---------------------------------------------------------------- chain


def _render_expression(value: object, *, expanded: bool) -> str:
    text = str(value or "")
    if expanded or len(text) <= _EXPRESSION_PREVIEW_CHARS:
        return text
    return (
        text[:_EXPRESSION_PREVIEW_CHARS]
        + "... [truncated; rerun chain with --expanded]"
    )


def _print_chain(entry: dict, column: str, *, expanded: bool) -> bool:
    found = False
    for chain in entry.get("field_mapping_chains") or []:
        if chain.get("target_field") != column:
            continue
        found = True
        print(f"  chain -> {chain.get('target_field')}  "
              f"[{chain.get('chain_type')}, trace: {chain.get('trace_status')}]")
        if chain.get("missing_reasons"):
            print(f"    incomplete because: {', '.join(chain['missing_reasons'])}")
        for step in chain.get("ordered_steps") or []:
            print(f"    step {step.get('step_no')} @{step.get('scope_id')} "
                  f"[{step.get('step_type')}/{step.get('transform')}]: "
                  f"{_render_expression(step.get('expression_sql'), expanded=expanded)}")
        roots = chain.get("root_source_fields") or []
        if roots:
            rendered = ", ".join(
                r if isinstance(r, str)
                else f"{r.get('table')}.{r.get('field') or r.get('column')}"
                for r in roots
            )
            print(f"    physical roots: {rendered}")
        print(
            "    expanded: "
            + _render_expression(chain.get("expanded_expression"), expanded=expanded)
        )
    for item in entry.get("end_to_end_lineage") or []:
        if item.get("column") != column:
            continue
        found = True
        sources = item.get("physical_sources") or []
        rendered = ", ".join(f"{s.get('table')}.{s.get('column')} ({s.get('transform')})" for s in sources)
        print(f"  e2e: {column} [{item.get('transform')}, source_kind: {item.get('source_kind')}, "
              f"trace_complete: {item.get('trace_complete')}]")
        print(
            "    expression: "
            + _render_expression(item.get("expression"), expanded=expanded)
        )
        print(f"    physical sources: {rendered or '(none - generated/rowset)'}")
        for generated in item.get("generated_sources") or []:
            print(f"    generated: {generated.get('source_type')} {generated.get('value') or ''}")
    return found


def cmd_chain(args: list[str]) -> int:
    expanded = "--expanded" in args
    args = [arg for arg in args if arg != "--expanded"]
    if len(args) < 2:
        print(
            "usage: query.py chain [--expanded] <db.table.column> <artifact path...>",
            file=sys.stderr,
        )
        return 2
    table, column = _split_column_ref(args[0])
    found = False
    stats: dict[str, int] = {}
    for path, doc in _iter_task_docs(args[1:], stats):
        task_hits = [
            item for item in doc.get("end_to_end_lineage") or []
            if item.get("table") == table and item.get("column") == column
        ]
        entry_hits = [
            (sid, entry) for sid, entry in (doc.get("statement_lineage") or {}).items()
            if entry.get("target_table") == table
        ]
        if not task_hits and not entry_hits:
            continue
        print(f"task: {doc.get('task_id')}  ({path})")
        for item in task_hits:
            found = True
            print(f"  final state {item.get('target_state')} "
                  f"[trace_complete: {item.get('trace_complete')}]")
            if item.get("missing_reasons"):
                print(f"    incomplete because: {', '.join(item['missing_reasons'])}")
            for source in item.get("value_sources") or []:
                print(f"    <- {source.get('table')}.{source.get('column')} "
                      f"[{source.get('source_kind')}, state: {source.get('state_id')}]")
        for sid, entry in entry_hits:
            if _print_chain(entry, column, expanded=expanded):
                found = True
    _report_stale(stats.get("stale", 0))
    if not found:
        print(f"{table}.{column}: not found in the given artifacts "
              "(check the table name is fully qualified and the artifacts cover this task)")
    return 0


# ---------------------------------------------------------------- impact


def cmd_impact(args: list[str]) -> int:
    if len(args) < 2:
        print("usage: query.py impact <db.table[.column]> <artifacts root>", file=sys.stderr)
        return 2
    ref = args[0]
    hits: list[str] = []
    stats: dict[str, int] = {}
    for path, doc in _iter_task_docs(args[1:], stats):
        for sid, entry in (doc.get("statement_lineage") or {}).items():
            # try table-only first; fall back to table.column
            table_ref, column_ref = ref, None
            if table_ref not in (entry.get("source_tables") or []):
                table_ref, column_ref = _split_column_ref(ref)
                if table_ref not in (entry.get("source_tables") or []):
                    continue
            for item in entry.get("end_to_end_lineage") or []:
                for source in item.get("physical_sources") or []:
                    if source.get("table") != table_ref:
                        continue
                    if column_ref and source.get("column") != column_ref:
                        continue
                    hits.append(
                        f"{doc.get('task_id')} {sid}: "
                        f"{entry.get('target_table')}.{item.get('column')} "
                        f"<- {source.get('table')}.{source.get('column')} ({source.get('transform')})"
                    )
    _report_stale(stats.get("stale", 0))
    document_count = stats.get("documents", 0)
    if hits:
        print(f"consumers of {ref}: {len(hits)} edge(s) across {document_count} task doc(s)")
        for line in sorted(set(hits)):
            print(f"  {line}")
    else:
        print(f"no consumers found for {ref} across {document_count} task doc(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    commands = {"summary": cmd_summary, "chain": cmd_chain, "impact": cmd_impact}
    if not argv or argv[0] not in commands:
        print(__doc__, file=sys.stderr)
        return 2
    return commands[argv[0]](argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
