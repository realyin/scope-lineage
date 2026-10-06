"""``digest_tables``: table-semantics documents condensed into catalog-drafting material.

A drafter deciding which concepts, identifiers and attributes a catalog needs reads the
same few facts of every table: what one row is, its grain and time semantics, which
columns identify it or another object, which carry states, times and amounts, which
tables it is built from, and what is still open. The digest (``catalog-digest/1``) is
those facts and nothing else, one entry per table in table order. Given a catalog it
also says what the catalog does not cover yet: tables with no representation, and
columns of represented tables with no binding. A table a code set's ``lookup`` names is
a code-set source, not a gap: a dictionary table holds code values, not a concept. Given
the lookup facts ``render.value_lookups`` read from a lineage corpus (``--lineage``), a
column also says which joined inputs its value is read through; without them the digest
is byte for byte what it was.

The documents are read as plain JSON (legal ``table-semantics/1`` documents, checked by
the caller); this package imports nothing from the table-semantics package.
"""

from __future__ import annotations

from typing import Optional

from .model import Catalog

DIGEST_FORMAT = "catalog-digest/1"

# ``keyed_by`` of a read whose join key is the table's own row identifier.
ROW_IDENTIFIER = "row_identifier"

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


def digest_tables(
    documents: list[dict], catalog: Optional[Catalog] = None, lookups: Optional[dict] = None
) -> dict:
    """The digest of ``documents`` in table order; with ``catalog``, what it does not cover.

    ``lookups`` is what ``render.value_lookups.column_lookups`` read from a lineage corpus
    (``{"tables": {db.table: {column: facts}}}``): each listed column of a table it names
    gains those facts, tagged with the catalog's matching code set when a catalog is given.
    Without it the digest is exactly what it was.
    """
    facts = (lookups or {}).get("tables") or {}
    code_sets = _code_set_lookups(catalog) if catalog is not None and facts else []
    pairs = sorted(
        (
            (_table(document, facts, code_sets), [column["column"] for column in document["columns"]])
            for document in documents
        ),
        key=lambda pair: pair[0]["table"],
    )
    digest: dict = {"doc_format": DIGEST_FORMAT, "tables": [entry for entry, _ in pairs]}
    if catalog is not None:
        digest["catalog"] = _catalog_gaps(catalog, pairs)
    return digest


def _table(document: dict, facts: dict, code_sets: list[dict]) -> dict:
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
    read = {name.lower(): value for name, value in (facts.get(entry["table"]) or {}).items()}
    for category, key in _LISTED.items():
        entry[key] = [
            _column(column, read.get(column["column"].lower()), code_sets)
            for column in columns
            if column["category"] == category
        ]
    if read:
        _mark_row_reads(entry)
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


def _mark_row_reads(entry: dict) -> None:
    """``keyed_by: "row_identifier"`` on a read keyed by this table's own row identifier.

    A join key that is one of the table's grain columns, or a column the document calls an
    identifier, picks rows describing the same record (an attribute row of this entity, a
    participant of this call), not a code's translation. The mark goes on the ``key_of``
    entry of that column and on the same read (rule and table) in each column reading it.
    """
    identifiers = {str(name).lower() for name in entry["grain"]["columns"]}
    identifiers |= {column["column"].lower() for column in entry["identifier_columns"]}
    columns = {column["column"].lower(): column for key in _LISTED.values() for column in entry[key]}
    for name, column in columns.items():
        if name not in identifiers:
            continue
        for read in column.get("key_of") or []:
            read["keyed_by"] = ROW_IDENTIFIER
            for reader in read["read_by"]:
                for other in (columns.get(str(reader).lower()) or {}).get("lookups") or []:
                    if (other["rule"], other["table"]) == (read["rule"], read["table"]):
                        other["keyed_by"] = ROW_IDENTIFIER


def _column(column: dict, facts: Optional[dict] = None, code_sets: Optional[list] = None) -> dict:
    result = {"column": column["column"], "meaning": column["meaning"]}
    if column.get("unit"):
        result["unit"] = column["unit"]
    if column.get("code_values"):
        result["code_values"] = [_code_value(value) for value in column["code_values"]]
    if facts:
        result.update(_lookup_facts(facts, code_sets or []))
    return result


def _lookup_facts(facts: dict, code_sets: list[dict]) -> dict:
    """A column's lookup facts, each read tagged with the code set it matches, if any."""
    result: dict = {}
    for key in ("lookups_by", "lookups", "fallback", "other_sources", "key_of", "key_of_order"):
        if key not in facts:
            continue
        value = facts[key]
        if key in ("lookups", "key_of"):
            value = [_tagged(dict(read), code_sets) for read in value]
        result[key] = value
    return result


def _tagged(read: dict, code_sets: list[dict]) -> dict:
    """``code_set`` when a code set's lookup has this table and exactly this filter, and the
    read's join columns (``key``, when the lineage names them) include its code column;
    ``reads_as`` when the column read is that code set's meaning or key column.

    A read that matches the table and filter but joins on other columns -- a stored
    meaning looked up back to its code -- is not that code set's translation: it gets
    ``code_set_mismatch`` (the code set and the code column it looks up by) instead."""
    where = {str(column).lower(): str(value) for column, value in read["where"].items()}
    for code_set in code_sets:
        if code_set["table"] != read["table"] or code_set["filter"] != where:
            continue
        keys = {str(column).lower() for column in read.get("key") or []}
        if keys and code_set["code_column"] and code_set["code_column"] not in keys:
            read["code_set_mismatch"] = {
                "code_set": code_set["id"], "code_column": code_set["code_column"],
            }
            break
        read["code_set"] = code_set["id"]
        reads = str(read.get("reads") or "").lower()
        if reads and reads in code_set["meaning"]:
            read["reads_as"] = "meaning"
        elif reads and reads == code_set["key"]:
            read["reads_as"] = "key"
        break
    return read


def _code_set_lookups(catalog: Catalog) -> list[dict]:
    """Every code set with a filtered ``lookup``, in id order, in comparable form."""
    found = []
    for _file, code_set in catalog.records("code_sets"):
        lookup = code_set.get("lookup")
        if not isinstance(lookup, dict) or not lookup.get("table") or not lookup.get("filter"):
            continue
        found.append({
            "id": str(code_set.get("id")),
            "table": bare_table(lookup["table"]),
            "filter": {str(k).lower(): str(v) for k, v in (lookup.get("filter") or {}).items()},
            "meaning": {
                str(column.get("column")).lower()
                for column in lookup.get("meaning_columns") or []
                if isinstance(column, dict)
            },
            "key": str(lookup.get("key_column") or "").lower() or None,
            "code_column": str(lookup.get("code_column") or "").lower() or None,
        })
    return sorted(found, key=lambda item: item["id"])


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
    lines += _lookup_lines(entry)
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


def _lookup_lines(entry: dict) -> list[str]:
    """One line per column the lineage says is read through, or keys, a joined input."""
    lines = []
    rows = {
        (read["rule"], read["table"]): column["column"]
        for key in _LISTED.values() for column in entry[key]
        for read in column.get("key_of") or [] if read.get("keyed_by")
    }
    for key in _LISTED.values():
        for column in entry[key]:
            parts = []
            if column.get("lookups_by") == "source":
                parts.append(_by_source_text(column, rows))
            elif column.get("lookups"):
                parts.append("reads " + _reads_text(column["lookups"], rows))
            if column.get("fallback"):
                parts.append("falls back to " + ", ".join(column["fallback"]))
            if column.get("key_of"):
                order = "; order unknown" if column.get("key_of_order") else ""
                parts.append("join key of " + ", ".join(
                    _read_text(read) + f" ({_read_note(read, _readers_text(read), rows)})"
                    for read in column["key_of"]
                ) + order)
            if parts:
                lines.append(f"  - {column['column']}: " + "; ".join(parts))
    return ["- Joined inputs read (from the lineage):", *lines] if lines else []


def _reads_text(reads: list[dict], rows: dict) -> str:
    """Reads in the order one value falls back through them: ``A, then B``."""
    return ", then ".join(
        _read_text(read) + f" ({_read_note(read, read['reads'], rows)})" for read in reads
    )


def _by_source_text(column: dict, rows: dict) -> str:
    """``by source: <s1> reads A; <s2> stores t.c directly`` -- or ``every source reads A``
    when every source reads the same rows the same way and none stores a column directly."""
    by_source: dict[str, list[dict]] = {}
    for read in column["lookups"]:
        by_source.setdefault(read["source"], []).append(read)
    others = column.get("other_sources") or {}
    shapes = {
        tuple((read["table"], tuple(read["where"].items()), read["reads"]) for read in reads)
        for reads in by_source.values()
    }
    if len(by_source) > 1 and len(shapes) == 1 and not others:
        return "every source reads " + _reads_text(next(iter(by_source.values())), rows)
    parts = [f"{source} reads {_reads_text(reads, rows)}" for source, reads in by_source.items()]
    parts += [f"{source} stores {', '.join(stored)} directly" for source, stored in others.items()]
    return "by source: " + "; ".join(parts)


def _readers_text(read: dict) -> str:
    return "read by " + (", ".join(read["read_by"]) or "no column")


def _read_text(read: dict) -> str:
    where = " and ".join(f"{column} = '{value}'" for column, value in read["where"].items())
    return f"rows of {read['table']} where {where}"


def _read_note(read: dict, first: str, rows: dict) -> str:
    notes = [first]
    if read.get("key"):
        notes.append(f"keyed on {', '.join(read['key'])}")
    if read.get("keyed_by") == ROW_IDENTIFIER:
        identifier = rows.get((read["rule"], read["table"]))
        notes.append(
            "keyed by this table's row identifier" + (f" {identifier}" if identifier else "")
            + ": reads rows describing the same record, not a code translation"
        )
    mismatch = read.get("code_set_mismatch")
    if mismatch:
        notes.append(f"code set {mismatch['code_set']} looks up by {mismatch['code_column']} "
                     "(reverse lookup?)")
    if read.get("code_set"):
        notes.append(f"code set {read['code_set']}" + (
            f", {read['reads_as']}" if read.get("reads_as") else ""
        ))
    return "; ".join(notes)


def _coverage_text(coverage: dict) -> str:
    codes = coverage.get("code_sets")
    source = f"code-set source of {', '.join(codes)}" if codes else ""
    if not coverage["represented"]:
        return source or "no representation"
    text = f"{coverage['concept']} / {coverage['kind']}"
    loose = coverage["unbound_columns"]
    text += f"; unbound: {', '.join(loose)}" if loose else "; every column bound"
    return text + (f"; {source}" if source else "")
