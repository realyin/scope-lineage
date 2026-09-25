"""Read a catalog directory: find its files, parse YAML or JSON, report what did not parse.

The layout is fixed (see ``FILE_KINDS``): one file per kind at the top level, and the two
kinds that grow per domain -- ``concepts/`` and ``mapping/`` -- as directories. Any file
may be ``.yaml``, ``.yml`` or ``.json``; files of the same kind are concatenated in path
order. A file the layout does not name is reported, never silently skipped, because a
misspelt ``domain.yaml`` would otherwise look like an empty catalog.
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

from .model import (
    FILE_KINDS,
    MANIFEST_STEM,
    Catalog,
    CatalogError,
    Document,
    Finding,
)

SUFFIXES = (".yaml", ".yml", ".json")
YAML_SUFFIXES = (".yaml", ".yml")


def load_catalog(root: str | Path) -> Catalog:
    """Load every catalog file under ``root``; raise ``CatalogError`` if it cannot be read."""
    root = Path(root)
    if not root.is_dir():
        raise CatalogError(f"{root}: not a directory")
    manifest_path = _manifest_path(root)
    kinds, unknown = _classify(root, manifest_path)
    _require_yaml_support([manifest_path, *kinds])
    catalog = Catalog(root=root, manifest=None, manifest_file=_relative(root, manifest_path))
    catalog.unknown_files = unknown
    manifest = _parse_into(catalog, manifest_path)
    catalog.manifest = None if manifest is _UNPARSED else manifest
    for path, kind in sorted(kinds.items(), key=lambda pair: _relative(root, pair[0])):
        data = _parse_into(catalog, path)
        if data is not _UNPARSED:
            catalog.documents.append(Document(kind, _relative(root, path), data))
    return catalog


_UNPARSED = object()


def _manifest_path(root: Path) -> Path:
    found = [root / f"{MANIFEST_STEM}{suffix}" for suffix in SUFFIXES]
    found = [path for path in found if path.is_file()]
    if not found:
        raise CatalogError(
            f"{root}: no catalog.yaml (or catalog.yml / catalog.json) -- "
            "every catalog directory needs its manifest"
        )
    if len(found) > 1:
        names = ", ".join(path.name for path in found)
        raise CatalogError(f"{root}: more than one manifest ({names}); keep one")
    return found[0]


def _classify(root: Path, manifest: Path) -> tuple[dict[Path, str], list[str]]:
    """Map every catalog file to its kind; list the files the layout does not name."""
    kinds: dict[Path, str] = {}
    unknown: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path == manifest or _hidden(root, path):
            continue
        kind = _kind_of(root, path)
        if kind is None:
            unknown.append(_relative(root, path))
        else:
            kinds[path] = kind
    return kinds, sorted(unknown)


def _kind_of(root: Path, path: Path) -> str | None:
    if path.suffix not in SUFFIXES:
        return None
    parts = path.relative_to(root).parts
    if len(parts) == 1:
        kind = FILE_KINDS.get(path.stem)
        return kind.name if kind and not kind.directory else None
    if len(parts) == 2:
        kind = FILE_KINDS.get(parts[0])
        return kind.name if kind and kind.directory else None
    return None


def _hidden(root: Path, path: Path) -> bool:
    return any(part.startswith(".") for part in path.relative_to(root).parts)


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _require_yaml_support(paths) -> None:
    yaml_files = sorted(path.name for path in paths if path.suffix in YAML_SUFFIXES)
    if not yaml_files:
        return
    try:
        import yaml  # noqa: F401
    except ImportError:
        raise CatalogError(
            f"reading {yaml_files[0]} needs PyYAML, which is not installed: "
            "pip install 'scope-lineage[catalog]' (or write the catalog files as .json)"
        ) from None


def _parse_into(catalog: Catalog, path: Path):
    """The file's data as plain JSON values, or ``_UNPARSED`` with a finding recorded."""
    try:
        text = path.read_text(encoding="utf-8")
        data = _parse_yaml(text) if path.suffix in YAML_SUFFIXES else json.loads(text)
    except (ValueError, UnicodeDecodeError) as error:
        catalog.problems.append(_parse_finding(catalog.root, path, error))
        return _UNPARSED
    return _plain(data)


def _parse_yaml(text: str):
    import yaml

    try:
        return yaml.load(text, Loader=yaml_loader())  # noqa: S506 - a SafeLoader subclass
    except yaml.YAMLError as error:
        raise ValueError(str(error)) from None


_LOADER = None


def yaml_loader():
    """``SafeLoader`` with YAML 1.2 booleans: only ``true`` / ``false``.

    YAML 1.1 also reads ``on``, ``off``, ``yes`` and ``no`` as booleans, which would turn
    a constraint's ``on:`` key into ``True`` and a code value ``no`` into ``False``.
    """
    global _LOADER
    if _LOADER is None:
        import yaml

        bool_tag = "tag:yaml.org,2002:bool"

        class CatalogLoader(yaml.SafeLoader):
            pass

        CatalogLoader.yaml_implicit_resolvers = {
            first: [(tag, rx) for tag, rx in resolvers if tag != bool_tag]
            for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
        }
        CatalogLoader.add_implicit_resolver(
            bool_tag, re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
        )
        _LOADER = CatalogLoader
    return _LOADER


def _parse_finding(root: Path, path: Path, error: Exception) -> Finding:
    message = " ".join(str(error).split())
    return Finding("parse_error", _relative(root, path), None, f"does not parse: {message}")


def _plain(value):
    """YAML's extra scalar types folded into JSON ones: dates as ISO text, keys as text."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value
