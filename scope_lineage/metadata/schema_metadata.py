"""Schema metadata helpers for expanding physical-table ``SELECT *``.

The parser consumes a lightweight ``{table_name: [column_names...]}`` mapping.
This module keeps loading and normalization in one place so local mock metadata
and the target environment's metadata provider can feed the same contract.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Protocol


def _raise_csv_field_size_limit() -> None:
    """Business metadata CSVs can carry very long field values (a huge column comment or a
    pasted expression). Python's default 131072-char field limit raises
    `_csv.Error: field larger than field limit`, aborting the whole load. Raise it to the
    platform max (guarded: sys.maxsize overflows the C long on some platforms)."""
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit = int(limit // 2)


_raise_csv_field_size_limit()


def _sniff_delimiter(f) -> str:
    """Detect tab vs comma from the header without consuming the stream. Business metadata is
    sometimes tab-separated; a comma DictReader on a tab file loads 0 usable rows silently."""
    position = f.tell()
    header = f.readline()
    f.seek(position)
    return "\t" if header.count("\t") > header.count(",") else ","


def _dict_reader(f) -> csv.DictReader:
    return csv.DictReader(f, delimiter=_sniff_delimiter(f))


def metadata_dict_reader(f) -> csv.DictReader:
    """Return a public delimiter-sniffing reader for generic metadata CSV/TSV files."""
    return _dict_reader(f)


class SchemaMap(dict):
    """Parser-ready table -> column names map with optional column details."""

    def __init__(
        self,
        *args,
        column_details: Mapping[str, list[dict]] | None = None,
        table_details: Mapping[str, dict] | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.column_details = {
            normalize_table_name(table): [_normalize_column_detail(item) for item in details]
            for table, details in (column_details or {}).items()
        }
        self.table_details = {
            normalize_table_name(table): _normalize_table_detail(table, detail, include_table_name=False)
            for table, detail in (table_details or {}).items()
        }
        self.table_detail_provider = None
        self.metadata_conflicts: list[dict] = []
        self.metadata_source_count = 1


class SchemaProvider(Protocol):
    """Minimal interface for runtime metadata providers."""

    def get_columns(self, table_name: str) -> list[str] | None:
        """Return column names for ``table_name`` or ``None`` when unknown."""


class DictSchemaProvider:
    """Schema provider backed by an in-memory mapping.

    Useful for tests, mock metadata, and adapters that have already fetched all
    needed table schemas from an external catalog.
    """

    def __init__(self, schema: Mapping[str, Iterable[str]] | None = None):
        self.schema = normalize_schema_map(schema or {})

    def get_columns(self, table_name: str) -> list[str] | None:
        return lookup_columns(self.schema, table_name)


# Catalog stripping is deployment-specific. Public Core has no built-in catalog vocabulary;
# callers opt in through the environment variable below.
DEFAULT_CATALOG_PREFIXES: tuple[str, ...] = ()


def catalog_prefixes() -> frozenset:
    """Catalog segments to strip from qualified names.

    3-segment strings are ambiguous (catalog.db.table vs db.table.field), so
    stripping must be vocabulary-conditioned, never unconditional. Configure
    SCOPE_LINEAGE_CATALOG_PREFIXES with a comma-separated allowlist when needed.
    """
    env = os.environ.get("SCOPE_LINEAGE_CATALOG_PREFIXES")
    if env is not None:
        return frozenset(part.strip().lower() for part in env.split(",") if part.strip())
    return frozenset(DEFAULT_CATALOG_PREFIXES)


def strip_catalog_prefix(value: str) -> str:
    """Drop a LEADING known-catalog segment (safe for db.table.field refs)."""
    parts = [part for part in str(value or "").split(".") if part]
    if len(parts) >= 3 and parts[0] in catalog_prefixes():
        parts = parts[1:]
    return ".".join(parts)


def normalize_table_name(name: str) -> str:
    """Normalize table names for metadata lookup.

    Current SQL output usually uses two-part names (``db.table``). When a
    three-part name looks like ``catalog.db.table``, we strip the catalog for
    lookup. We also lower-case because sqlglot normalizes many unquoted
    identifiers to lower-case.
    """

    name = (name or "").strip().strip("`")
    parts = [part.strip("`") for part in name.split(".") if part]
    if len(parts) >= 3:
        parts = parts[-2:]
    return ".".join(parts).lower()


def normalize_schema_map(schema: Mapping[str, Iterable[str]]) -> SchemaMap:
    normalized: SchemaMap = SchemaMap()
    for table, columns in schema.items():
        key = normalize_table_name(table)
        if not key:
            continue
        details = _column_details_from_columns(columns)
        normalized[key] = _dedupe_columns(detail["name"] for detail in details)
        _merge_column_details(normalized, key, details)
    return normalized


def lookup_columns(schema: Mapping[str, Iterable[str]], table_name: str) -> list[str] | None:
    """Lookup columns with both exact and normalized table names."""

    if table_name in schema:
        return list(schema[table_name])
    normalized = normalize_table_name(table_name)
    cols = schema.get(normalized)
    return list(cols) if cols is not None else None



class MetadataFileError(ValueError):
    """A metadata file cannot be read as the loaders expect.

    Its own class because the caller's response differs from a normal ValueError: metadata is
    loaded once, before any task is parsed and outside the per-task error boundary, so a bad
    file fails the whole batch at once. The message has to say which file, where, and what to
    do — `_csv.Error: line contains NUL` says none of those (META-001).
    """


# NUL bytes in a metadata export are the failure we have actually seen. Python's csv module
# raised "line contains NUL" up to 3.10 and stopped in 3.11, so the same file crashes the batch
# on 3.9/3.10 and silently admits \x00 into column names and types on 3.11+. Neither is
# acceptable, and neither is discoverable from the default error, so the check is explicit and
# version-independent.
def _describe_nul_bytes(raw: bytes, limit: int = 5) -> list[str]:
    positions = [index for index, byte in enumerate(raw) if byte == 0]
    described = [
        f"byte {offset:,} (~line {raw[:offset].count(10) + 1:,})"
        for offset in positions[:limit]
    ]
    if len(positions) > limit:
        described.append(f"... and {len(positions) - limit:,} more")
    return described


@dataclass(frozen=True)
class MetadataReadResult:
    text: str
    provenance: dict[str, object]


def _read_metadata_file(
    path: str | Path,
    *,
    sanitize_nul: bool,
    role: str,
    require_header: bool,
) -> MetadataReadResult:
    path = Path(path)
    if not path.exists():
        raise MetadataFileError(f"元数据文件不存在: {path}")
    original = path.read_bytes()
    if not original.strip():
        raise MetadataFileError(f"元数据文件为空: {path}")
    positions = [index for index, byte in enumerate(original) if byte == 0]
    described_positions = _describe_nul_bytes(original)
    if positions and not sanitize_nul:
        raise MetadataFileError(
            f"元数据文件含 NUL 字节,无法安全读取: {path}\n"
            f"  位置: {'; '.join(described_positions)}\n"
            f"  说明: Python ≤3.10 会在此直接报 'line contains NUL';3.11+ 不报错,"
            f"但会把 \\x00 混进列名/类型/注释,更难发现。两种情况都不该继续。\n"
            f"  处理: 修复导出流程或源文件(推荐);确需临时容忍时显式加 "
            f"--sanitize-metadata-nul,该选项会记入运行命令与 provenance。"
        )
    raw = original.replace(b"\x00", b"") if positions else original
    if positions:
        print(
            f"警告: 已从元数据文件剔除 {len(positions):,} 个 NUL 字节: {path}"
            f" (位置: {'; '.join(described_positions)});这是显式容错,不代表源文件已修复",
            file=sys.stderr,
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise MetadataFileError(
            f"元数据文件不是合法 UTF-8: {path}\n  位置: byte {exc.start:,}\n"
            f"  处理: 按 UTF-8 重新导出,或先转码后再传入"
        ) from exc
    if require_header and not text.splitlines()[0].strip():
        raise MetadataFileError(f"元数据文件缺少表头: {path}")
    return MetadataReadResult(
        text=text,
        provenance={
            "role": role,
            "path": str(path.resolve()),
            "file_name": path.name,
            "format": path.suffix.lower().lstrip("."),
            "size_bytes": len(original),
            "sha256": hashlib.sha256(original).hexdigest(),
            "sanitize_nul_requested": sanitize_nul,
            "nul_count_detected": len(positions),
            "nul_byte_offsets": positions,
            "nul_count_removed": len(positions) if sanitize_nul else 0,
            "sanitized_in_memory": bool(positions and sanitize_nul),
        },
    )


def check_metadata_file(
    path: str | Path,
    *,
    sanitize_nul: bool = False,
    provenance: list[dict] | None = None,
    role: str = "metadata",
) -> str:
    """Read a metadata file and return its text, failing loudly on what CSV cannot represent.

    Runs before the CSV reader so the diagnosis names the file and the offending offsets rather
    than surfacing a parser-internal error from somewhere inside a 3 MB file.
    """
    result = _read_metadata_file(
        path,
        sanitize_nul=sanitize_nul,
        role=role,
        require_header=True,
    )
    if provenance is not None:
        provenance.append(dict(result.provenance))
    return result.text


def _open_metadata_csv(
    path: str | Path,
    *,
    sanitize_nul: bool = False,
    provenance: list[dict] | None = None,
    role: str = "metadata",
) -> io.StringIO:
    """The single reading path for every metadata CSV, so the diagnosis cannot vary by loader."""
    return io.StringIO(
        check_metadata_file(
            path,
            sanitize_nul=sanitize_nul,
            provenance=provenance,
            role=role,
        ),
        newline="",
    )


def load_schema(
    path: str | Path,
    *,
    sanitize_nul: bool = False,
    provenance: list[dict] | None = None,
) -> SchemaMap:
    """Load source-table schema metadata from CSV, JSON, or a rich-JSON directory.

    Supported CSV shape:
      - rows with ``table_name`` and ``column_name``
      - optional ``type``/``column_type`` and ``comment``/``column_comment`` columns

    Supported JSON shapes:
      - rich table metadata with ``table_name``, ``schema[]``, and optional ``ddl``
      - a directory containing one rich table-metadata JSON document per table
      - ``{"db.table": ["c1", "c2"]}``
      - ``{"db.table": [{"name": "c1", "type": "string", "comment": "..."}]}``
      - ``{"db.table": {"column_details": [{"name": "c1"}]}}``
      - ``[{"table_name": "db.table", "column_name": "c1"}]``
      - ``{"tables": [{"table_name": "db.table", "columns": ["c1"]}]}``
    """

    path = Path(path)
    if path.is_dir():
        return _raise_if_nothing_loaded(
            _load_schema_metadata_directory(
                path, sanitize_nul=sanitize_nul, provenance=provenance
            )
        )
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return load_schema_csv(
            path, sanitize_nul=sanitize_nul, provenance=provenance
        )
    if suffix == ".json":
        return load_schema_json(
            path, sanitize_nul=sanitize_nul, provenance=provenance
        )
    raise ValueError(f"Unsupported schema metadata file type: {path}")


def load_schema_sources(
    paths: Iterable[str | Path],
    *,
    sanitize_nul: bool = False,
    provenance: list[dict] | None = None,
) -> SchemaMap:
    """Load ordered schema sources, keeping the first table definition as authoritative.

    Later sources fill tables missing from earlier sources. A conflicting definition for an
    already-covered table is recorded instead of being silently merged or overwriting DDL order.
    """
    loaded: list[SchemaMap] = []
    for path in paths:
        try:
            loaded.append(
                load_schema(path, sanitize_nul=sanitize_nul, provenance=provenance)
            )
        except MetadataFileError as exc:
            # One source yielding nothing costs that source. On-demand loading passes a
            # computed list of paths, so raising here would put the original failure back:
            # one unusable file among the fifty a task needs would leave it with nothing
            # (METADATA-001). A batch that produced no table at all still raises, below.
            rejected = SchemaMap()
            rejected.metadata_conflicts.append({
                "table": "",
                "source_file": Path(path).name,
                "reason": "metadata_rejected",
                "issues": [str(exc).splitlines()[-1].strip()],
            })
            loaded.append(rejected)
    if not loaded:
        return SchemaMap()
    result = SchemaMap(
        loaded[0],
        column_details=getattr(loaded[0], "column_details", {}),
        table_details=getattr(loaded[0], "table_details", {}),
    )
    result.table_detail_provider = getattr(
        loaded[0],
        "table_detail_provider",
        None,
    )
    # Rejected tables are carried across every source: a table whose metadata was supplied
    # and refused is a different problem from one nobody supplied, and only this list can
    # tell the two apart downstream.
    for source in loaded:
        for conflict in getattr(source, "metadata_conflicts", []):
            if conflict not in result.metadata_conflicts:
                result.metadata_conflicts.append(dict(conflict))
    for source_index, fallback in enumerate(loaded[1:], start=1):
        for table, columns in fallback.items():
            if table not in result:
                result[table] = list(columns)
                details = getattr(fallback, "column_details", {}).get(table)
                if details is not None:
                    result.column_details[table] = [
                        dict(item) for item in details
                    ]
                table_detail = getattr(fallback, "table_details", {}).get(table)
                if table_detail is not None:
                    result.table_details[table] = dict(table_detail)
                continue
            if list(result[table]) != list(columns):
                result.metadata_conflicts.append({
                    "table": table,
                    "authoritative_columns": list(result[table]),
                    "fallback_columns": list(columns),
                    "fallback_source_index": source_index,
                    "resolution": "kept_authoritative",
                })
    result.metadata_source_count = len(loaded)
    return _raise_if_nothing_loaded(result)


def _raise_if_nothing_loaded(schema: SchemaMap) -> SchemaMap:
    """Partial success is normal; producing no table at all is not.

    An empty schema returned quietly reads the same as "these tables have no metadata",
    so the one case that still raises is the one where nothing could be loaded.
    """
    if schema or not schema.metadata_conflicts:
        return schema
    # Name why each one was refused: "nothing loaded" alone tells an operator to look,
    # not what to fix.
    rejected = "; ".join(
        f"{item.get('source_file') or item.get('table')}: "
        f"{', '.join(item.get('issues') or ['unknown_validation_error'])}"
        for item in schema.metadata_conflicts[:3]
    )
    raise MetadataFileError(
        f"源表权威 JSON 元数据全部无效，未能加载任何表\n  {rejected}"
    )


def load_schema_csv(
    path: str | Path,
    *,
    sanitize_nul: bool = False,
    provenance: list[dict] | None = None,
) -> SchemaMap:
    schema: SchemaMap = SchemaMap()
    with _open_metadata_csv(
        path,
        sanitize_nul=sanitize_nul,
        provenance=provenance,
        role="schema",
    ) as f:
        for row in _dict_reader(f):
            table = row.get("table_name") or row.get("table") or ""
            column = row.get("column_name") or row.get("column") or row.get("name") or ""
            detail = {
                "name": column,
                "type": row.get("type") or row.get("data_type") or row.get("column_type"),
                "comment": row.get("comment") or row.get("column_comment"),
            }
            _append_schema_column(schema, table, detail)
    return schema


def load_schema_json(
    path: str | Path,
    *,
    sanitize_nul: bool = False,
    provenance: list[dict] | None = None,
) -> SchemaMap:
    result = _read_metadata_file(
        path,
        sanitize_nul=sanitize_nul,
        role="schema",
        require_header=False,
    )
    data = json.loads(result.text)
    if provenance is not None:
        provenance.append(dict(result.provenance))
    return _raise_if_nothing_loaded(_schema_from_json_value(data, source_path=path))


def materialize_schema(provider: SchemaProvider, tables: Iterable[str]) -> SchemaMap:
    """Fetch a parser-ready schema map from a provider for selected tables."""

    schema: SchemaMap = SchemaMap()
    for table in tables:
        columns = provider.get_columns(table)
        if columns:
            key = normalize_table_name(table)
            details = _column_details_from_columns(columns)
            schema[key] = _dedupe_columns(detail["name"] for detail in details)
            _merge_column_details(schema, key, details)
    return schema


def _schema_from_json_value(
    data,
    *,
    source_path: str | Path = "<schema-json>",
) -> SchemaMap:
    schema: SchemaMap = SchemaMap()

    if _is_rich_table_metadata_document(data):
        _append_rich_table_schema(schema, data, Path(source_path))
        return schema

    if isinstance(data, dict) and isinstance(data.get("tables"), list):
        for item in data["tables"]:
            if not isinstance(item, dict):
                continue
            if _is_rich_table_metadata_document(item):
                _append_rich_table_schema(schema, item, Path(source_path))
                continue
            table = item.get("table_name") or item.get("table") or item.get("name") or ""
            columns = item.get("column_details") or item.get("columns") or []
            for column in _iter_column_details(columns):
                _append_schema_column(schema, table, column)
        return schema

    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            table = item.get("table_name") or item.get("table") or ""
            column = {
                "name": item.get("column_name") or item.get("column") or item.get("name") or "",
                "type": item.get("type") or item.get("data_type") or item.get("column_type"),
                "comment": item.get("comment") or item.get("column_comment"),
            }
            _append_schema_column(schema, table, column)
        return schema

    if isinstance(data, dict):
        for table, columns in data.items():
            if table == "tables":
                continue
            if isinstance(columns, dict):
                columns = columns.get("column_details") or columns.get("columns") or columns.get("fields") or []
            for column in _iter_column_details(columns):
                _append_schema_column(schema, table, column)
        return schema

    raise ValueError("Unsupported JSON schema metadata shape")


def _load_schema_metadata_directory(
    path: Path,
    *,
    sanitize_nul: bool,
    provenance: list[dict] | None,
) -> SchemaMap:
    # Import lazily because the target metadata module uses the shared file-reading
    # helpers above. Rich table metadata is deliberately one contract for source
    # star expansion and target positional binding.
    from .target_table_metadata import load_target_table_metadata

    metadata = load_target_table_metadata(
        path,
        sanitize_nul=sanitize_nul,
        provenance=provenance,
        provenance_role="schema",
    )
    schema = SchemaMap()
    for item in metadata.values():
        _append_loaded_table_schema(schema, item, path / item.source_file)
    return schema


def _is_rich_table_metadata_document(data: object) -> bool:
    return (
        isinstance(data, dict)
        and bool(data.get("table_name") or data.get("full_table_name"))
        and ("schema" in data or "ddl" in data)
    )


def _append_rich_table_schema(
    schema: SchemaMap,
    document: dict,
    source_path: Path,
) -> None:
    from .target_table_metadata import _target_table_metadata_from_document

    item = _target_table_metadata_from_document(document, source_path)
    _append_loaded_table_schema(schema, item, source_path)


def _append_loaded_table_schema(schema: SchemaMap, item, source_path: Path) -> None:
    """Record one table's columns, or record why it could not be used.

    Rejection costs this table and nothing else, whether the caller named a directory or a
    list of files. On-demand loading passes a computed list of paths, so a rule that raised
    for named files would put the original failure straight back: one unusable file among
    the fifty a task needs would again leave that task with no metadata at all
    (METADATA-001).
    """
    if not item.usable:
        schema.metadata_conflicts.append({
            "table": item.table_name or item.full_table_name,
            "source_file": source_path.name,
            "reason": "metadata_rejected",
            "issues": list(item.validation_issues) or ["unknown_validation_error"],
        })
        return
    table = item.table_name or item.full_table_name
    for column in item.columns:
        _append_schema_column(
            schema,
            table,
            {
                "name": column.name,
                "type": column.data_type,
                "comment": column.comment,
            },
        )


def _iter_column_names(columns) -> Iterable[str]:
    return [detail["name"] for detail in _iter_column_details(columns)]


def _iter_column_details(columns) -> Iterable[dict]:
    if isinstance(columns, dict):
        columns = columns.get("column_details") or columns.get("columns") or columns.get("fields") or []
    if not isinstance(columns, list):
        return []

    details = []
    for column in columns:
        if isinstance(column, str):
            details.append(_normalize_column_detail({"name": column}))
        elif isinstance(column, dict):
            details.append(_normalize_column_detail(column))
    return details


def _append_schema_column(schema: SchemaMap, table: str, column: str | dict) -> None:
    table_key = normalize_table_name(table)
    detail = _normalize_column_detail(column)
    column_name = detail["name"]
    if not table_key or not column_name:
        return
    cols = schema.setdefault(table_key, [])
    if column_name not in cols:
        cols.append(column_name)
    _merge_column_details(schema, table_key, [detail])


def _column_details_from_columns(columns) -> list[dict]:
    return list(_iter_column_details(columns))


def _normalize_column_detail(column: str | Mapping | None) -> dict:
    if isinstance(column, str):
        raw = {"name": column}
    elif isinstance(column, Mapping):
        raw = dict(column)
    else:
        raw = {}

    name = (
        raw.get("column_name")
        or raw.get("columnName")
        or raw.get("name")
        or raw.get("column")
        or ""
    )
    col_type = (
        raw.get("type") or raw.get("data_type") or raw.get("column_type")
        or raw.get("columnType")
    )
    comment = raw.get("comment") or raw.get("column_comment") or raw.get("columnComment")
    return {
        "name": (name or "").strip().strip("`"),
        "type": _blank_to_none(col_type),
        "comment": _blank_to_none(comment),
    }


def _normalize_table_detail(
    table: str,
    detail: Mapping | None,
    *,
    include_table_name: bool = True,
) -> dict:
    raw = dict(detail or {})
    result = {
        "table_name_cn": _blank_to_none(
            raw.get("table_name_cn")
            or raw.get("name_cn")
            or raw.get("table_comment")
            or raw.get("comment")
        ),
        "table_desc": _blank_to_none(
            raw.get("table_desc")
            or raw.get("description")
            or raw.get("desc")
            or raw.get("comment")
        ),
        "table_label_layer": _blank_to_none(
            raw.get("table_label_layer")
            or raw.get("layer")
            or raw.get("data_layer")
        ),
        "domain": _blank_to_none(raw.get("domain") or raw.get("业务域")),
    }
    result = {key: value for key, value in result.items() if value is not None}
    if include_table_name:
        result["table_name"] = (table or raw.get("table_name") or raw.get("table") or "").strip().strip("`")
    return result


def _merge_column_details(schema: SchemaMap, table_key: str, details: Iterable[dict]) -> None:
    existing = {item["name"]: item for item in schema.column_details.get(table_key, [])}
    ordered_names = [item["name"] for item in schema.column_details.get(table_key, [])]
    for detail in details:
        name = detail.get("name")
        if not name:
            continue
        if name not in existing:
            ordered_names.append(name)
            existing[name] = {"name": name, "type": None, "comment": None}
        existing[name] = {
            "name": name,
            "type": detail.get("type"),
            "comment": detail.get("comment"),
        }
    schema.column_details[table_key] = [existing[name] for name in ordered_names]


def column_details_for_table(schema: Mapping[str, Iterable[str]], table_name: str) -> list[dict]:
    """Return column metadata details for a table, defaulting type/comment to null."""
    key = normalize_table_name(table_name)
    details_by_table = getattr(schema, "column_details", {})
    details = details_by_table.get(key)
    if details is not None:
        return [dict(item) for item in details]

    cols = lookup_columns(schema, table_name) or []
    return [{"name": col, "type": None, "comment": None} for col in cols]


def table_details_for_table(schema: Mapping[str, Iterable[str]], table_name: str) -> dict:
    """Return table-level metadata for a table, if attached to the schema."""
    key = normalize_table_name(table_name)
    details_by_table = getattr(schema, "table_details", {})
    detail = details_by_table.get(key)
    if detail is not None:
        return dict(detail)
    provider = getattr(schema, "table_detail_provider", None)
    provided = provider(table_name) if callable(provider) else None
    return dict(provided) if isinstance(provided, Mapping) else {}


def _blank_to_none(value) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _dedupe_columns(columns: Iterable[str]) -> list[str]:
    result = []
    seen = set()
    for column in columns:
        name = (column or "").strip().strip("`")
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result
