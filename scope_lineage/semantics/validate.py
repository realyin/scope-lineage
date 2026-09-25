"""``semantic validate``: schema first, then the nine cross checks, then one report.

A table's pass rate is the share of checked items that did not fail (a ``warn`` is
listed but does not count against it). The failure list -- every ``fail`` and ``warn``
with its path and a sentence saying what to change -- is written to be handed back to
the model as a rewrite prompt as it stands.
"""

from __future__ import annotations

from collections import Counter

from .checks import (
    CHECKS,
    check_code_values,
    check_coverage,
    check_grain,
    check_source_columns,
)
from .checks_context import (
    check_digest,
    check_neighbours,
    check_rules,
    check_sources,
    check_time,
    missing_packet,
)
from .schema import DOC_FORMAT, schema_errors

REPORT_FORMAT = "table-semantics-validation/1"

_CHECK_FUNCTIONS = (
    check_coverage,
    check_source_columns,
    check_code_values,
    check_grain,
    check_rules,
    check_neighbours,
    check_sources,
    check_digest,
    check_time,
)
_STATUSES = ("pass", "warn", "fail")


def validate_document(document: dict, packet: dict | None) -> dict:
    """The cross-check report of one schema-valid document against its packet (or None)."""
    if packet is None:
        results = [missing_packet(document)]
    else:
        results = [item for check in _CHECK_FUNCTIONS for item in check(document, packet)]
    counts = Counter(item["status"] for item in results)
    checks: dict[str, dict[str, int]] = {}
    for item in results:
        checks.setdefault(item["check"], dict.fromkeys(_STATUSES, 0))[item["status"]] += 1
    total = len(results)
    return {
        "table": document.get("table"),
        "counts": {status: counts.get(status, 0) for status in _STATUSES},
        "pass_rate": round((total - counts.get("fail", 0)) / total, 4) if total else 1.0,
        "checks": {name: checks[name] for name in CHECKS if name in checks},
        "failures": [item for item in results if item["status"] != "pass"],
    }


def check_file(
    document, packet: dict | None, file: str, *, unreadable: str | None = None
) -> dict:
    """One file's entry in the report: its schema errors, or its cross-check report."""
    errors = [{"at": "", "message": unreadable}] if unreadable else schema_errors(document, DOC_FORMAT)
    table = document.get("table") if isinstance(document, dict) else None
    if errors:
        return {"table": table, "file": file, "schema_errors": errors,
                "counts": dict.fromkeys(_STATUSES, 0), "pass_rate": None, "checks": {},
                "failures": []}
    report = validate_document(document, packet)
    return {"table": table, "file": file, "schema_errors": [],
            **{key: value for key, value in report.items() if key != "table"}}


def validation_report(entries: list[dict]) -> dict:
    """The ``--json`` document: every file's entry and one summary line's numbers."""
    checked = [entry for entry in entries if not entry["schema_errors"]]
    total = sum(sum(entry["counts"].values()) for entry in checked)
    failed = sum(entry["counts"]["fail"] for entry in checked)
    return {
        "doc_format": REPORT_FORMAT,
        "tables": entries,
        "summary": {
            "documents": len(entries),
            "clean": sum(1 for entry in checked if not entry["failures"]),
            "tables_with_failures": sum(1 for entry in checked if entry["counts"]["fail"]),
            "tables_with_warnings_only": sum(
                1 for entry in checked if entry["failures"] and not entry["counts"]["fail"]
            ),
            "tables_with_schema_errors": len(entries) - len(checked),
            "pass_rate": round((total - failed) / total, 4) if total else None,
        },
    }


def render_validation_text(report: dict) -> str:
    """The human summary: one line per table, then its failures, then the totals."""
    lines: list[str] = []
    for entry in report["tables"]:
        lines += _entry_lines(entry)
    summary = report["summary"]
    lines.append(
        f"Validated {summary['documents']} document(s): {summary['clean']} clean, "
        f"{summary['tables_with_failures']} with failures, "
        f"{summary['tables_with_warnings_only']} with warnings only, "
        f"{summary['tables_with_schema_errors']} with schema errors"
    )
    return "\n".join(lines) + "\n"


def _entry_lines(entry: dict) -> list[str]:
    name = entry["table"] or entry["file"]
    if entry["schema_errors"]:
        return [f"{name} ({entry['file']}): {len(entry['schema_errors'])} schema error(s)"] + [
            f"  SCHEMA {error['at'] or '(document)'}: {error['message']}"
            for error in entry["schema_errors"]
        ]
    counts = entry["counts"]
    total = sum(counts.values())
    lines = [
        f"{name}: {total - counts['fail']}/{total} checks passed "
        f"({entry['pass_rate'] * 100:.1f}%), {counts['fail']} fail, {counts['warn']} warn"
    ]
    return lines + [
        f"  {item['status'].upper()} [{CHECKS.index(item['check']) + 1} {item['check']}] "
        f"{item['at']}: {item['message']}"
        for item in entry["failures"]
    ]
