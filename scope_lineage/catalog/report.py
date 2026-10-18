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
    "metrics",
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
        "  density: " + density_text(counts["density"]),
    ]
    lines += [f"error   {finding.render()}" for finding in report.errors]
    if not report.references_checked:
        lines.append("note    reference checks and warnings wait until the structure errors are fixed")
    lines += [f"warning {finding.render()}" for finding in report.warnings]
    return "\n".join(lines)


_RATIOS = (
    ("attribute_unit", "unit"),
    ("attribute_derivation", "derivation"),
    ("code_set_values", "code values"),
    ("relation_definition", "relation definition"),
)
_DENSITY_COUNTS = ("states", "roles", "metrics", "constraints", "constraints_with_rules")


def density_text(density: dict) -> str:
    """``unit 3/4 (75%), ..., states=1, ...`` -- the density counts on one line."""
    parts = []
    for key, label in _RATIOS:
        ratio = density[key]
        share = "-" if ratio["ratio"] is None else f"{round(100 * ratio['ratio'])}%"
        parts.append(f"{label} {ratio['count']}/{ratio['total']} ({share})")
    parts += [f"{key}={density[key]}" for key in _DENSITY_COUNTS]
    return ", ".join(parts)
