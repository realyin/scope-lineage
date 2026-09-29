"""``digest_tables``: table-semantics documents condensed into catalog-drafting material.

A drafter deciding which concepts, identifiers and attributes a catalog needs reads the
same few facts of every table: what one row is, its grain and time semantics, which
columns identify it or another object, which carry states, times and amounts, which
tables it is built from, and what is still open. The digest (``catalog-digest/1``) is
those facts and nothing else, one entry per table in table order. Given a catalog it
also says what the catalog does not cover yet: tables with no representation, and
columns of represented tables with no binding. A table a code set's ``lookup`` names is
a code-set source, not a gap: a dictionary table holds code values, not a concept.

The documents are read as plain JSON (legal ``table-semantics/1`` documents, checked by
the caller); this package imports nothing from the table-semantics package.
"""

from __future__ import annotations

from typing import Optional

from .model import Catalog

DIGEST_FORMAT = "catalog-digest/1"

# Column categories the digest lists with their meanings; ``technical`` by name only.
_LISTED = {
    "identifier": "identifier_columns",
    "foreign_identifier": "foreign_identifier_columns",
    "state": "state_columns",
    "time": "time_columns",
    "measure": "measure_columns",
    "descriptive": "descriptive_columns",
}


def bare_table(name: object) -> str:
    """``db.table`` in lower case: a leading catalog and identifier quotes dropped."""
    parts = [part.strip("`") for part in str(name or "").strip().split(".") if part]
    return ".".join(parts[-2:]).lower()


def digest_tables(documents: list[dict], catalog: Optional[Catalog] = None) -> dict:
    """The digest of ``documents`` in table order; with ``catalog``, what it does not cover."""
    pairs = sorted(
        ((_table(document), [column["column"] for column in document["columns"]])
         for document in documents),
        key=lambda pair: pair[0]["table"],
    )
    digest: dict = {"doc_format": DIGEST_FORMAT, "tables": [entry for entry, _ in pairs]}
    if catalog is not None:
        digest["catalog"] = _catalog_gaps(catalog, pairs)
    return digest


def _table(document: dict) -> dict:
    summary = document["summary"]
    row, refresh = summary["row"], summary["refresh"]
    concept = document.get("concept") or {}
    entry: dict = {
        "table": bare_table(document["table"]),
        "what": summary["what"],
        "concept": concept.get("concept"),
        "representation_kind": concept.get("representation_kind"),
        "row": row["text"],
        "grain": {
            "columns": row["grain_columns"],
            "source": row["grain_source"],
            "unique": row["unique"],
        },
        "time": {
            "kind": refresh["time"],
            "cycle": refresh["cycle"],
            "how_to_read": refresh["how_to_read"],
        },
        "scope": [scope["text"] for scope in summary["scope"]],
    }
    columns = document["columns"]
    for category, key in _LISTED.items():
        entry[key] = [_column(column) for column in columns if column["category"] == category]
    entry["technical_columns"] = [c["column"] for c in columns if c["category"] == "technical"]
    entry["columns"] = len(columns)
    entry["related"] = {
        "upstream": [{"table": up["table"], "role": up["role"]} for up in summary["upstream"]],
        "downstream": sorted({down["table"] for down in summary["downstream"] if down.get("table")}),
    }
    entry["watch"] = [{"kind": watch["kind"], "text": watch["text"]} for watch in summary["watch"]]
    entry["open_questions"] = [
        {"id": question["id"], "text": question["text"]}
        for question in summary["questions"]
        if question["status"] == "open"
    ]
    return entry


def _column(column: dict) -> dict:
    result = {"column": column["column"], "meaning": column["meaning"]}
    if column.get("unit"):
        result["unit"] = column["unit"]
    if column.get("code_values"):
        result["code_values"] = [_code_value(value) for value in column["code_values"]]
    return result


def _code_value(value: dict) -> dict:
    result = {"value": value["value"], "meaning": value["meaning"]}
    if value.get("unconfirmed"):
        result["unconfirmed"] = True
    return result


def _catalog_gaps(catalog: Catalog, tables: list[tuple[dict, list[str]]]) -> dict:
    """What the catalog lacks for these tables; each table entry gains its own ``catalog``."""
    representations: dict[str, dict] = {}
    for _file, representation in catalog.records("mapping"):
        representations.setdefault(bare_table(representation.get("table")), representation)
    lookups = _lookup_tables(catalog)
    missing, unbound, sources = [], {}, {}
    for entry, columns in tables:
        representation = representations.get(entry["table"])
        code_sets = lookups.get(entry["table"])
        if code_sets:
            sources[entry["table"]] = code_sets
        if representation is None:
            entry["catalog"] = {"represented": False}
            if code_sets:
                entry["catalog"]["code_sets"] = code_sets
            else:
                missing.append(entry["table"])
            continue
        bound = {
            str(binding.get("column")).lower()
            for binding in representation.get("bindings") or []
            if isinstance(binding, dict)
        }
        loose = [column for column in columns if column.lower() not in bound]
        entry["catalog"] = {
            "represented": True,
            "concept": representation.get("concept"),
            "kind": representation.get("kind"),
            "unbound_columns": loose,
        }
        if code_sets:
            entry["catalog"]["code_sets"] = code_sets
        if loose:
            unbound[entry["table"]] = loose
    return {
        "name": catalog.name,
        "tables_without_representation": missing,
        "columns_without_binding": unbound,
        "code_set_sources": sources,
    }


def _lookup_tables(catalog: Catalog) -> dict[str, list[str]]:
    """``db.table -> the ids of the code sets whose values it holds``, ids sorted."""
    found: dict[str, list[str]] = {}
    for _file, code_set in catalog.records("code_sets"):
        lookup = code_set.get("lookup")
        if isinstance(lookup, dict) and lookup.get("table"):
            found.setdefault(bare_table(lookup["table"]), []).append(str(code_set.get("id")))
    return {table: sorted(ids) for table, ids in found.items()}


# ------------------------------------------------------------------ markdown


def render_digest_markdown(digest: dict) -> str:
    lines = [
        "# Catalog digest",
        "",
        f"{len(digest['tables'])} table(s), condensed from their table-semantics documents "
        "as material for drafting concepts, identifiers, attributes and representations.",
        "",
    ]
    if "catalog" in digest:
        lines += _catalog_section(digest["catalog"])
    for entry in digest["tables"]:
        lines += _table_section(entry)
    return "\n".join(lines).rstrip() + "\n"


def _catalog_section(gaps: dict) -> list[str]:
    lines = [f"## Catalog coverage ({gaps['name']})", ""]
    missing = gaps["tables_without_representation"]
    lines.append(f"- Tables without a representation ({len(missing)}): "
                 + (", ".join(missing) if missing else "none"))
    unbound = gaps["columns_without_binding"]
    lines.append(f"- Represented tables with unbound columns ({len(unbound)}):"
                 + ("" if unbound else " none"))
    lines += [f"  - {table}: {', '.join(columns)}" for table, columns in unbound.items()]
    sources = gaps["code_set_sources"]
    if sources:
        lines.append(f"- Code-set sources ({len(sources)}):")
        lines += [f"  - {table}: {', '.join(ids)}" for table, ids in sources.items()]
    return lines + [""]


def _table_section(entry: dict) -> list[str]:
    grain, time = entry["grain"], entry["time"]
    concept = entry["concept"] or "(no concept)"
    kind = f" / {entry['representation_kind']}" if entry["representation_kind"] else ""
    lines = [
        f"## {entry['table']}",
        "",
        f"- What: {entry['what']}",
        f"- Concept: {concept}{kind}",
        f"- Row: {entry['row']}",
        f"- Grain: {', '.join(grain['columns']) or '(none)'} "
        f"({grain['source']}, unique: {grain['unique']})",
        f"- Time: {time['kind']}, {time['cycle']} -- {time['how_to_read']}",
    ]
    lines += [f"- Scope: {text}" for text in entry["scope"]]
    labels = (
        ("identifier_columns", "Identifiers"),
        ("foreign_identifier_columns", "Foreign identifiers"),
        ("state_columns", "States"),
        ("time_columns", "Times"),
        ("measure_columns", "Measures"),
        ("descriptive_columns", "Descriptive"),
    )
    for key, label in labels:
        if entry[key]:
            lines.append(f"- {label}: " + "; ".join(_column_text(c) for c in entry[key]))
    if entry["technical_columns"]:
        lines.append(f"- Technical: {', '.join(entry['technical_columns'])}")
    lines.append(f"- Columns: {entry['columns']}")
    upstream = [f"{up['table']} ({up['role']})" for up in entry["related"]["upstream"]]
    if upstream:
        lines.append(f"- Built from: {', '.join(upstream)}")
    if entry["related"]["downstream"]:
        lines.append(f"- Read by: {', '.join(entry['related']['downstream'])}")
    lines += [f"- Watch ({watch['kind']}): {watch['text']}" for watch in entry["watch"]]
    lines += [f"- Open {q['id']}: {q['text']}" for q in entry["open_questions"]]
    if "catalog" in entry:
        lines.append(f"- Catalog: {_coverage_text(entry['catalog'])}")
    return lines + [""]


def _column_text(column: dict) -> str:
    text = f"{column['column']} {column['meaning']}"
    if column.get("unit"):
        text += f" [{column['unit']}]"
    if column.get("code_values"):
        values = ", ".join(
            f"{value['value']}={value['meaning']}" + ("?" if value.get("unconfirmed") else "")
            for value in column["code_values"]
        )
        text += f" ({values})"
    return text


def _coverage_text(coverage: dict) -> str:
    codes = coverage.get("code_sets")
    source = f"code-set source of {', '.join(codes)}" if codes else ""
    if not coverage["represented"]:
        return source or "no representation"
    text = f"{coverage['concept']} / {coverage['kind']}"
    loose = coverage["unbound_columns"]
    text += f"; unbound: {', '.join(loose)}" if loose else "; every column bound"
    return text + (f"; {source}" if source else "")
