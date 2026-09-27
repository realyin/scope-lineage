"""How far the catalog covers a list of tables: a representation each, its columns bound how."""

from __future__ import annotations

from collections import Counter

from .model import Catalog

# The binding targets in the order the mapping schema lists them.
BINDING_KINDS = (
    "identifier",
    "foreign_identifier",
    "attribute",
    "foreign_attribute",
    "technical",
    "unmapped",
)


def table_coverage(catalog: Catalog, tables: list[str]) -> list[dict]:
    """One row per table: represented or not; if so its concept, kind and binding counts."""
    representations = {}
    for _file, representation in catalog.records("mapping"):
        representations.setdefault(str(representation.get("table")).lower(), representation)
    rows = []
    for table in tables:
        representation = representations.get(table.lower())
        if representation is None:
            rows.append({"table": table, "represented": False})
            continue
        bindings = representation.get("bindings")
        targets = Counter(
            str(binding.get("to"))
            for binding in (bindings if isinstance(bindings, list) else [])
            if isinstance(binding, dict)
        )
        rows.append({
            "table": table,
            "represented": True,
            "concept": representation.get("concept"),
            "kind": representation.get("kind"),
            "columns": sum(targets.values()),
            "bindings": {kind: targets[kind] for kind in BINDING_KINDS if targets[kind]},
            "unmapped": targets["unmapped"],
        })
    return rows


def render_coverage(rows: list[dict]) -> str:
    represented = sum(1 for row in rows if row["represented"])
    unmapped = sum(row.get("unmapped", 0) for row in rows)
    lines = [
        f"Coverage: {len(rows)} table(s) in the fragments, {represented} with a "
        f"representation, {unmapped} unmapped column(s)"
    ]
    for row in rows:
        if not row["represented"]:
            lines.append(f"  {row['table']}  no representation")
            continue
        counts = " ".join(f"{kind}={count}" for kind, count in row["bindings"].items())
        lines.append(
            f"  {row['table']}  {row['concept']}  {row['kind']}  "
            f"{row['columns']} column(s): {counts or 'none bound'}"
        )
    return "\n".join(lines)
