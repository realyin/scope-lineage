"""Freeze current layer violations so extraction can only improve the graph."""

from __future__ import annotations

from pathlib import Path

from tests.architecture.core_boundary_scan import (
    ImportRef,
    core_to_upper,
    pipeline_private_core_imports,
    scan_imports,
)


REPO_ROOT = Path(__file__).resolve().parents[2]

# CP4 eliminated every Core→Upper dependency. This remains explicit and empty so any regression
# fails without allowing a broad path or glob exemption.
KNOWN_CORE_TO_UPPER: dict[tuple[str, str, tuple[str, ...]], str] = {}

KNOWN_PIPELINE_PRIVATE_IMPORTS: dict[tuple[str, str, str], str] = {}


def _production_imports() -> list[ImportRef]:
    files = list((REPO_ROOT / "lineage_parser").rglob("*.py"))
    files.extend((REPO_ROOT / "pipeline").rglob("*.py"))
    return scan_imports(REPO_ROOT, files)


def _key(ref: ImportRef) -> tuple[str, str, str]:
    return ref.source, ref.target, ref.symbol


def _grouped_keys(refs: set[ImportRef]) -> set[tuple[str, str, tuple[str, ...]]]:
    groups: dict[tuple[str, str], set[str]] = {}
    for ref in refs:
        groups.setdefault((ref.source, ref.target), set()).add(ref.symbol)
    return {
        (source, target, tuple(sorted(symbols)))
        for (source, target), symbols in groups.items()
    }


def test_core_does_not_gain_upper_layer_dependencies() -> None:
    actual = _grouped_keys(core_to_upper(_production_imports()))
    assert actual == set(KNOWN_CORE_TO_UPPER), (
        "Core→Upper import set changed. New entries are forbidden; removed entries must be "
        f"deleted from KNOWN_CORE_TO_UPPER. actual={sorted(actual)}"
    )


def test_pipeline_does_not_gain_private_core_imports() -> None:
    actual = {_key(ref) for ref in pipeline_private_core_imports(_production_imports())}
    assert actual == set(KNOWN_PIPELINE_PRIVATE_IMPORTS), (
        "Pipeline private-import set changed. Prefer a public Core API and remove the matching "
        f"exception. actual={sorted(actual)}"
    )


def test_pipeline_uses_only_the_public_core_facade() -> None:
    deep_imports = {
        _key(ref)
        for ref in _production_imports()
        if ref.source.startswith("pipeline.")
        and ref.target.startswith("lineage_parser.")
    }
    assert deep_imports == set()


def test_core_tree_contains_no_upper_layer_source_packages() -> None:
    forbidden = {
        "assets",
        "insight",
        "presets",
        "refactor",
        "skill_entry.py",
        "scope/scope_views.py",
        "serialize/_shared.py",
        "serialize/llm_profile_index.py",
        "serialize/profile_compaction.py",
        "serialize/scope_serializer.py",
    }
    actual = {
        path.relative_to(REPO_ROOT / "lineage_parser").as_posix()
        for path in (REPO_ROOT / "lineage_parser").rglob("*.py")
    }
    assert not (actual & forbidden)


def test_scanner_finds_relative_absolute_delayed_and_private_imports(tmp_path: Path) -> None:
    package = tmp_path / "lineage_parser" / "scope"
    package.mkdir(parents=True)
    source = package / "sample.py"
    source.write_text(
        "from ..insight import x\n"
        "from . import sibling\n"
        "import pipeline.x as y\n"
        "def delayed():\n"
        "    from ..refactor import z\n",
        encoding="utf-8",
    )
    pipeline = tmp_path / "pipeline"
    pipeline.mkdir()
    consumer = pipeline / "consumer.py"
    consumer.write_text(
        "from lineage_parser.scope._shared import _private\n",
        encoding="utf-8",
    )

    refs = scan_imports(tmp_path, [source, consumer])
    keys = {_key(ref) for ref in refs}
    assert ("lineage_parser.scope.sample", "lineage_parser.insight", "x") in keys
    assert ("lineage_parser.scope.sample", "lineage_parser.scope", "sibling") in keys
    assert ("lineage_parser.scope.sample", "pipeline.x", "pipeline.x") in keys
    assert ("lineage_parser.scope.sample", "lineage_parser.refactor", "z") in keys
    assert (
        "pipeline.consumer",
        "lineage_parser.scope._shared",
        "_private",
    ) in {_key(ref) for ref in pipeline_private_core_imports(refs)}
