"""The human-readable form of a validation report."""

from __future__ import annotations

from .model import CATALOG_FORMAT, ValidationReport

_COUNTED = (
    "domains",
    "identifiers",
    "code_sets",
    "concepts",
    "attributes",
    "relations",
    "constraints",
    "terms",
    "representations",
    "bindings",
)


def render_summary(report: ValidationReport) -> str:
    counts = report.counts
    lines = [
        f"Catalog {report.catalog} ({CATALOG_FORMAT}): "
        f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)",
        "  " + ", ".join(f"{key}={counts[key]}" for key in _COUNTED),
        "  status: " + ", ".join(f"{key}={value}" for key, value in counts["status"].items()),
    ]
    lines += [f"error   {finding.render()}" for finding in report.errors]
    if not report.references_checked:
        lines.append("note    reference checks and warnings wait until the structure errors are fixed")
    lines += [f"warning {finding.render()}" for finding in report.warnings]
    return "\n".join(lines)
