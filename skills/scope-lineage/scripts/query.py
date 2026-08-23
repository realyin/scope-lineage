#!/usr/bin/env python3
"""Targeted extraction from scope-lineage artifacts.

A lineage.json can be large; an agent that reads the whole file into its context wastes
it and still has to find the needle. This script pulls only the answer out. Three
subcommands, stdlib only, Python 3.9+:

  summary <task_dir | lineage.json>          one task's status, statements, targets, gaps
  chain   <db.table.column> <path...>        how one written field is derived, step by step
  impact  <db.table[.column]> <root>         who reads this table/column, across artifacts

Paths may be task artifact directories (containing lineage.json), lineage.json files,
or (for impact) a root directory that is scanned recursively. Exit 0 on success (even
when the answer is "not found" -- that IS the answer), 2 on usage/IO errors.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _load_task_docs(paths: list[str]) -> "tuple[list[tuple[Path, dict]], int]":
    docs: list[tuple[Path, dict]] = []
    stale = 0
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
            try:
                document = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                print(f"cannot read {candidate}: {exc}", file=sys.stderr)
                continue
            if document.get("artifact_kind") == "task_lineage":
                docs.append((candidate, document))
            elif document.get("schema_version") == "1.0":
                stale += 1
    return docs, stale


def _report_stale(stale: int) -> None:
    if stale:
        print(f"note: skipped {stale} statement document(s) (schema_version 1.0) -- "
              "these look like artifacts from scope-lineage < 0.2.0; re-parse with the "
              "current version to get task documents")


def _split_column_ref(ref: str) -> tuple[str, str]:
    table, _, column = ref.rpartition(".")
    return table, column


# ---------------------------------------------------------------- summary


def cmd_summary(args: list[str]) -> int:
    docs, stale = _load_task_docs(args or ["."])
    _report_stale(stale)
    if not docs:
        print("no task lineage.json found")
        return 0
    for path, doc in docs:
        print(f"task: {doc.get('task_id')}  ({path})")
        print(f"  parse_status: {doc.get('parse_status')}  syntax_status: {doc.get('syntax_status')}")
        for statement in doc.get("statement_sequence") or []:
            print(
                f"  {statement.get('statement_id')}: {statement.get('stmt_kind')}"
                f" [{statement.get('category')}] -> {statement.get('model_status')}"
            )
        finals = doc.get("final_table_states") or {}
        if finals:
            print(f"  final tables: {', '.join(sorted(finals))}")
        sources = sorted({
            table
            for entry in (doc.get("statement_lineage") or {}).values()
            for table in entry.get("source_tables") or []
        })
        if sources:
            print(f"  source tables: {', '.join(sources)}")
        diagnostics = doc.get("diagnostics") or {}
        warning_types: dict[str, int] = {}
        for warning in diagnostics.get("warnings") or []:
            key = warning.get("type") or "UNKNOWN"
            warning_types[key] = warning_types.get(key, 0) + 1
        gaps = diagnostics.get("lineage_fact_gaps") or []
        print(f"  warnings: {sum(warning_types.values())}"
              + (f"  ({', '.join(f'{k}x{v}' for k, v in sorted(warning_types.items()))})" if warning_types else ""))
        print(f"  fact_gaps: {len(gaps)}"
              + (f"  root_impact: {sum(1 for g in gaps if g.get('root_impact'))}" if gaps else ""))
    return 0


# ---------------------------------------------------------------- chain


def _print_chain(entry: dict, column: str) -> bool:
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
                  f"{step.get('expression_sql')}")
        roots = chain.get("root_source_fields") or []
        if roots:
            rendered = ", ".join(
                r if isinstance(r, str)
                else f"{r.get('table')}.{r.get('field') or r.get('column')}"
                for r in roots
            )
            print(f"    physical roots: {rendered}")
        print(f"    expanded: {chain.get('expanded_expression')}")
    for item in entry.get("end_to_end_lineage") or []:
        if item.get("column") != column:
            continue
        found = True
        sources = item.get("physical_sources") or []
        rendered = ", ".join(f"{s.get('table')}.{s.get('column')} ({s.get('transform')})" for s in sources)
        print(f"  e2e: {column} [{item.get('transform')}, source_kind: {item.get('source_kind')}, "
              f"trace_complete: {item.get('trace_complete')}]")
        print(f"    expression: {item.get('expression')}")
        print(f"    physical sources: {rendered or '(none - generated/rowset)'}")
        for generated in item.get("generated_sources") or []:
            print(f"    generated: {generated.get('source_type')} {generated.get('value') or ''}")
    return found


def cmd_chain(args: list[str]) -> int:
    if len(args) < 2:
        print("usage: query.py chain <db.table.column> <artifact path...>", file=sys.stderr)
        return 2
    table, column = _split_column_ref(args[0])
    found = False
    docs, stale = _load_task_docs(args[1:])
    _report_stale(stale)
    for path, doc in docs:
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
            if _print_chain(entry, column):
                found = True
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
    docs, stale = _load_task_docs(args[1:])
    _report_stale(stale)
    for path, doc in docs:
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
    if hits:
        print(f"consumers of {ref}: {len(hits)} edge(s) across {len(docs)} task doc(s)")
        for line in sorted(set(hits)):
            print(f"  {line}")
    else:
        print(f"no consumers found for {ref} across {len(docs)} task doc(s)")
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
