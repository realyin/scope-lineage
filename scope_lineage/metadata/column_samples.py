"""A6: supplied sample values for a column (``samples/1``), never sampled from a database.

Core reads SQL and metadata; it does not connect to a warehouse, so the one question a
table card could never answer is "what does a value of this column look like". A team
that *can* export a few values per column can hand them over as a file -- a CSV with
``table,column,value[,count]``, a directory of such CSVs, or the JSON form -- and this
module turns that file into the lookup :mod:`scope_lineage.render.table_cards` uses.

Three rules make the file safe to publish from.

1. **Redaction is not optional.** A samples file is the most PII-prone input the tool
   ever reads, so every value passes through :func:`~scope_lineage.redaction.redact` on
   the way in and there is no flag that turns it off. A long value is cut as well: a
   card publishes what a value *looks like*, not a whole record.
2. **The table name is normalized the way the cards normalize it.** ``mart.t`` in the
   export and ``spark_catalog.mart.t`` on the card are one table, which is the same
   dotted-suffix reading ``table_cards.same_table`` and ``glossary_values.table_key``
   give, and case is ignored for the same reason ``normalize_table_name`` ignores it.
3. **A row nobody claimed is reported, not dropped.** :meth:`ColumnSamples.unmatched`
   names every ``table.column`` the corpus never asked for, in the file's own spelling:
   a typo in a hand-made export is exactly what its author cannot see.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from ..redaction import redact


DOC_FORMAT = "samples/1"

#: How many distinct values a column publishes unless ``--samples-top`` says otherwise.
SAMPLES_TOP_DEFAULT = 5

#: Beyond this many characters a value stops being a sample and becomes a record.
VALUE_MAX_CHARS = 64
VALUE_CUT_MARK = "…"

CSV_HEADER = ("table", "column", "value")
CSV_COUNT = "count"

_READABLE_SUFFIXES = (".csv", ".json")


class ColumnSamplesError(ValueError):
    """A samples file that cannot be read, or whose shape is not one this release knows."""


class ColumnSamples:
    """The supplied values, keyed the way a card looks a column up.

    ``top`` is applied at lookup time rather than at load time, so the same loaded file
    can answer for two different limits in one process and the ordering rule stays in
    one place.
    """

    def __init__(self, top: int = SAMPLES_TOP_DEFAULT) -> None:
        self.top = max(int(top), 0)
        self.sources: list[str] = []
        self._rows: dict[tuple, list[tuple[str, int | None]]] = {}
        # The file's own spelling of each key, so an unmatched report quotes the line
        # its author wrote rather than the normalization of it.
        self._spellings: dict[tuple, str] = {}
        self._matched: set[tuple] = set()

    def __bool__(self) -> bool:
        return bool(self._rows)

    def add(self, table, column, value, count: int | None = None) -> None:
        key = (table_key(table), str(column).strip().lower())
        self._rows.setdefault(key, []).append((str(value), count))
        self._spellings.setdefault(key, f"{str(table).strip()}.{str(column).strip()}")

    def values(self, tables: Iterable[str], column) -> list[str]:
        """The published values for one column of one table, under any of its spellings."""
        name = str(column).strip().lower()
        for table in tables:
            key = (table_key(table), name)
            rows = self._rows.get(key)
            if rows is None:
                continue
            self._matched.add(key)
            return _published(rows, self.top)
        return []

    def unmatched(self) -> list[str]:
        """Every ``table.column`` of the file no card asked about, in the file's spelling."""
        return sorted(
            spelling
            for key, spelling in self._spellings.items()
            if key not in self._matched
        )


def table_key(name) -> tuple[str, ...]:
    """The last two dotted segments, lower-cased: what makes ``hive.ods.t`` and ``ods.t`` one.

    The same suffix reading ``table_cards.same_table`` applies between qualified names,
    expressed as a key so a lookup is a dict hit rather than a scan. Case is folded
    because an export is written by hand and sqlglot lower-cases unquoted identifiers.
    """
    parts = [part.strip().strip("`") for part in str(name or "").split(".")]
    kept = [part for part in parts if part]
    return tuple(part.lower() for part in kept[-2:])


def load_column_samples(
    path: str | None, *, top: int = SAMPLES_TOP_DEFAULT
) -> ColumnSamples | None:
    """Read one ``--samples`` file or directory; ``None`` when no path was supplied."""
    if not path:
        return None
    source = Path(path)
    samples = ColumnSamples(top=top)
    for item in _files(source):
        _merge_file(samples, item)
        samples.sources.append(str(item))
    return samples


def _files(source: Path) -> list[Path]:
    if source.is_dir():
        found = sorted(
            item
            for item in source.rglob("*")
            if item.is_file() and item.suffix.lower() in _READABLE_SUFFIXES
        )
        if not found:
            raise ColumnSamplesError(
                f"--samples directory holds no .csv or .json file: {source}"
            )
        return found
    if not source.is_file():
        raise ColumnSamplesError(f"--samples file does not exist: {source}")
    return [source]


def _merge_file(samples: ColumnSamples, path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise ColumnSamplesError(f"{path}: not a readable file ({error})")
    if text.lstrip()[:1] in ("{", "["):
        _merge_json(samples, path, text)
        return
    _merge_csv(samples, path, text)


# ------------------------------------------------------------------------------- CSV


def _merge_csv(samples: ColumnSamples, path: Path, text: str) -> None:
    reader = csv.DictReader(text.splitlines())
    spelled = list(reader.fieldnames or [])
    fields = [str(name or "").strip().lower() for name in spelled]
    if tuple(fields[: len(CSV_HEADER)]) != CSV_HEADER:
        raise ColumnSamplesError(
            f"{path}: a samples CSV needs the header table,column,value[,count]; "
            f"this file starts with {','.join(fields) or '(no header)'}"
        )
    # The header was written by hand, so the row is read through the caller's own
    # spelling of each column rather than through a spelling this module assumed.
    named = dict(zip(fields, spelled))
    for number, row in enumerate(reader, start=2):
        table = str(row.get(named["table"]) or "").strip()
        column = str(row.get(named["column"]) or "").strip()
        if not table or not column:
            raise ColumnSamplesError(
                f"{path}:{number}: a samples row needs a table and a column"
            )
        value = row.get(named["value"]) or ""
        samples.add(table, column, value, _count(path, number, row, named))


def _count(path: Path, number: int, row: Mapping, named: Mapping) -> int | None:
    raw = str(row.get(named.get(CSV_COUNT, CSV_COUNT)) or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise ColumnSamplesError(
            f"{path}:{number}: count must be a whole number, not {raw!r}"
        )


# ------------------------------------------------------------------------------ JSON


def _merge_json(samples: ColumnSamples, path: Path, text: str) -> None:
    try:
        document = json.loads(text)
    except ValueError as error:
        raise ColumnSamplesError(f"{path}: not a readable JSON document ({error})")
    entries = document.get("samples") if isinstance(document, Mapping) else None
    declared = document.get("doc_format") if isinstance(document, Mapping) else None
    # A top-level list reaches here too (it starts with "["), and it is told the same
    # thing as a JSON object of the wrong shape: what a samples document looks like.
    if declared not in (None, DOC_FORMAT) or not isinstance(entries, Sequence):
        raise ColumnSamplesError(
            f"{path}: --samples expects a {DOC_FORMAT} document "
            '({"doc_format": "samples/1", "samples": [{"table", "column", "values"}]}) '
            "or a table,column,value[,count] CSV"
        )
    for index, entry in enumerate(entries):
        _merge_entry(samples, path, index, entry)


def _merge_entry(samples: ColumnSamples, path: Path, index: int, entry) -> None:
    values = entry.get("values") if isinstance(entry, Mapping) else None
    table = str((entry or {}).get("table") or "").strip() if isinstance(entry, Mapping) else ""
    column = str(entry.get("column") or "").strip() if isinstance(entry, Mapping) else ""
    if not table or not column or not isinstance(values, Sequence) or isinstance(values, str):
        raise ColumnSamplesError(
            f"{path}: samples[{index}] needs a table, a column and a values list"
        )
    for value in values:
        if isinstance(value, (Mapping, Sequence)) and not isinstance(value, str):
            raise ColumnSamplesError(
                f"{path}: samples[{index}].values[] holds a {type(value).__name__}; "
                "a sample value is a scalar"
            )
        samples.add(table, column, value if value is not None else "")


# ------------------------------------------------------------------ what gets published


def _published(rows: Sequence[tuple[str, int | None]], top: int) -> list[str]:
    """Distinct, masked, cut values -- by ``count`` where the file gave one, else in order."""
    merged: dict[str, list] = {}
    for order, (raw, count) in enumerate(rows):
        value = _value_text(raw)
        if not value:
            continue
        entry = merged.setdefault(value, [None, order])
        if count is not None:
            entry[0] = (entry[0] or 0) + count
    counted = any(entry[0] is not None for entry in merged.values())
    ordered = sorted(
        merged.items(),
        key=lambda item: (-(item[1][0] or 0), item[1][1]) if counted else (0, item[1][1]),
    )
    return [value for value, _ in ordered[:top]] if top else []


def _value_text(raw) -> str:
    """Trim, mask the contact shapes, then cut: a sample is a shape, not a record."""
    value = redact(str(raw).strip())
    if len(value) > VALUE_MAX_CHARS:
        return value[:VALUE_MAX_CHARS] + VALUE_CUT_MARK
    return value
