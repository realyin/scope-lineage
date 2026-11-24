"""``semantic validate``: schema first, then the fourteen checks, then one report.

A table's pass rate is the share of checked items that did not fail (a ``warn`` is
listed but does not count against it). The failure list -- every ``fail`` and ``warn``
with its path and a sentence saying what to change -- is written to be handed back to
the model as a rewrite prompt as it stands.
"""

from __future__ import annotations

from collections import Counter
from functools import partial

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
from .confirmed import TableConfirmed
from .checks_documented import QUALIFIER_TERMS, check_documented_meaning, check_header_facts
from .checks_meaning import check_derived_codes, check_fan_out
from .checks_text import check_placeholder
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
    check_fan_out,
    check_derived_codes,
    check_documented_meaning,
    check_header_facts,
    check_placeholder,
)
_STATUSES = ("pass", "warn", "fail")


def validate_document(
    document: dict, packet: dict | None, *, qualifier_terms: tuple[str, ...] = QUALIFIER_TERMS,
    confirmations=None,
) -> dict:
    """The cross-check report of one schema-valid document against its packet (or None).

    Every failure carries its check's ``number`` (1-14, as the text summary prints it);
    ``not_reported`` lists the checks that ran and found nothing to check -- they have no
    key in ``checks``. Without a packet no check runs but the digest one, so none is listed.
    ``qualifier_terms`` are the qualifiers check 12 looks for: the generic ones, plus any a
    caller's domain profile adds.

    ``confirmations`` (:class:`~scope_lineage.semantics.confirmed.Confirmations`, read
    from a run's confirmations files) gives checks 3, 4, 6 and 10 what the owner confirmed and
    the platform queries observed for the document's own table. Three cases differ only
    for a document or table with observations: None (no confirmations path: an observation
    slot cannot be checked and warns), confirmations with no entry for the table (each
    observation slot fails), entries for the table (each slot must be the confirmation's).
    Without observations the first two check what they always did.
    """
    if packet is None:
        results = [missing_packet(document)]
    else:
        confirmed = None if confirmations is None else (
            confirmations.for_table(document.get("table")) or TableConfirmed())
        checks = [_bound(check, qualifier_terms, confirmed) for check in _CHECK_FUNCTIONS]
        results = [item for check in checks for item in check(document, packet)]
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
        "not_reported": [] if packet is None else [
            {"number": number, "check": name}
            for number, name in enumerate(CHECKS, 1) if name not in checks
        ],
        "failures": [
            {**item, "number": CHECKS.index(item["check"]) + 1}
            for item in results if item["status"] != "pass"
        ],
    }


def _bound(check, qualifier_terms: tuple[str, ...], confirmed):
    if check is check_documented_meaning:
        return partial(check, terms=qualifier_terms)
    if confirmed is not None and check in (
        check_code_values, check_grain, check_neighbours, check_fan_out,
    ):
        return partial(check, confirmed=confirmed)
    return check


def check_file(
    document, packet: dict | None, file: str, *, unreadable: str | None = None,
    qualifier_terms: tuple[str, ...] = QUALIFIER_TERMS, confirmations=None,
) -> dict:
    """One file's entry in the report: its schema errors, or its cross-check report.

    Every caller -- ``semantic validate``, ``semantic status`` / ``fixed``, the unfit
    warning of ``semantic render`` and ``catalog digest`` -- hands over the same
    ``confirmations``, so one document gets one verdict."""
    errors = [{"at": "", "message": unreadable}] if unreadable else schema_errors(document, DOC_FORMAT)
    table = document.get("table") if isinstance(document, dict) else None
    if errors:
        return {"table": table, "file": file, "schema_errors": errors,
                "counts": dict.fromkeys(_STATUSES, 0), "pass_rate": None, "checks": {},
                "not_reported": [], "failures": []}
    report = validate_document(document, packet, qualifier_terms=qualifier_terms,
                               confirmations=confirmations)
    return {"table": table, "file": file, "schema_errors": [],
            **{key: value for key, value in report.items() if key != "table"}}


def validation_report(entries: list[dict], confirmations=None) -> dict:
    """The ``--json`` document: every file's entry and one summary line's numbers.

    With ``confirmations`` read, the report gains ``confirmations`` -- the path, the files
    and the number of entries the checks held the documents to; without, it has no such
    key, as before."""
    checked = [entry for entry in entries if not entry["schema_errors"]]
    total = sum(sum(entry["counts"].values()) for entry in checked)
    failed = sum(entry["counts"]["fail"] for entry in checked)
    report = {
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
    if confirmations is not None:
        report["confirmations"] = confirmations_summary(confirmations)
    return report


def confirmations_summary(confirmations) -> dict:
    """``{path, files, entries}``: which confirmations a report was checked against."""
    return {"path": confirmations.path, "files": list(confirmations.files),
            "entries": len(confirmations.entries)}


def report_flags(report: dict) -> dict[str, list[str]]:
    """``table -> flags`` for each table the report holds that is not fit to publish.

    The flags of ``semantic status``, read from the report instead of the packets: a
    digest failure is ``no_packet`` when the report found no packet, else
    ``packet_stale``; any other failure, or a schema error, is ``invalid``. The digest
    failure's ``reason_code`` decides; a report written before that field existed is read
    by its message's ``no packet`` prefix.
    """
    found: dict[str, list[str]] = {}
    for entry in report.get("tables") or []:
        failures = [item for item in entry.get("failures") or [] if item.get("status") == "fail"]
        flags = []
        for item in failures:
            if item.get("check") == "digest":
                flags.append("no_packet" if _digest_reason(item) == "no_packet" else "packet_stale")
        if entry.get("schema_errors") or any(item.get("check") != "digest" for item in failures):
            flags.append("invalid")
        if flags and entry.get("table"):
            found[entry["table"]] = flags
    return found


def _digest_reason(item: dict) -> str:
    reason = item.get("reason_code")
    if reason in ("no_packet", "stale"):
        return reason
    return "no_packet" if str(item.get("message", "")).startswith("no packet") else "stale"


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
    if entry.get("not_reported"):
        lines.append("  无可查条目：" + "、".join(
            f"{item['number']} {item['check']}" for item in entry["not_reported"]))
    return lines + [
        f"  {item['status'].upper()} [{item['number']} {item['check']}] "
        f"{item['at']}: {item['message']}"
        for item in entry["failures"]
    ]
