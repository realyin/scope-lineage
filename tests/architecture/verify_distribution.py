"""Verify that public Core archives contain no upper-layer source or tests."""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath


FORBIDDEN_PARTS = {".claude", "docs", "pipeline", "tests", "__pycache__"}
FORBIDDEN_CORE_PATHS = {
    "lineage_parser/assets",
    "lineage_parser/insight",
    "lineage_parser/presets",
    "lineage_parser/refactor",
    "lineage_parser/skill_entry.py",
    "lineage_parser/scope/scope_views.py",
    "lineage_parser/serialize/_shared.py",
    "lineage_parser/serialize/llm_profile_index.py",
    "lineage_parser/serialize/profile_compaction.py",
    "lineage_parser/serialize/scope_serializer.py",
}
REQUIRED_CORE_PATHS = {
    "lineage_parser/schemas/diagnostics.schema.json",
    "lineage_parser/schemas/lineage.schema.json",
}


def _archive_names(path: Path) -> list[str]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return [name for name in archive.namelist() if not name.endswith("/")]
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path) as archive:
            return [member.name for member in archive.getmembers() if member.isfile()]
    raise ValueError(f"unsupported distribution archive: {path}")


def _without_sdist_root(name: str, *, is_sdist: bool) -> str:
    parts = PurePosixPath(name).parts
    if is_sdist and len(parts) > 1:
        return PurePosixPath(*parts[1:]).as_posix()
    return PurePosixPath(*parts).as_posix()


def verify_archive(path: Path) -> None:
    is_sdist = path.name.endswith(".tar.gz")
    names = {
        _without_sdist_root(name, is_sdist=is_sdist)
        for name in _archive_names(path)
    }
    forbidden = sorted(
        name
        for name in names
        if FORBIDDEN_PARTS.intersection(PurePosixPath(name).parts)
        or any(name == item or name.startswith(f"{item}/") for item in FORBIDDEN_CORE_PATHS)
    )
    missing = sorted(REQUIRED_CORE_PATHS - names)
    if forbidden or missing:
        raise AssertionError(
            f"invalid distribution {path}: forbidden={forbidden}, missing={missing}"
        )


def main(argv: list[str] | None = None) -> int:
    paths = [Path(value) for value in (argv if argv is not None else sys.argv[1:])]
    if not paths:
        raise SystemExit("usage: verify_distribution.py DIST [DIST ...]")
    for path in paths:
        verify_archive(path)
        print(f"distribution boundary ok: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
