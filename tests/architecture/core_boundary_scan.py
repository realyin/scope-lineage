"""AST-based import boundary scanner used by the extraction safety net."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, order=True)
class ImportRef:
    source: str
    target: str
    symbol: str
    line: int


def module_name(path: Path, root: Path) -> str:
    relative = path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_from(source: str, is_package: bool, level: int, module: str | None) -> str:
    if not level:
        return module or ""
    package = source if is_package else source.rpartition(".")[0]
    parts = package.split(".") if package else []
    keep = max(0, len(parts) - (level - 1))
    base = parts[:keep]
    if module:
        base.extend(module.split("."))
    return ".".join(base)


def scan_imports(root: Path, paths: list[Path]) -> list[ImportRef]:
    refs: list[ImportRef] = []
    for path in sorted(paths):
        source = module_name(path, root)
        is_package = path.name == "__init__.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    refs.append(ImportRef(source, alias.name, alias.name, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                target = _resolve_from(source, is_package, node.level, node.module)
                for alias in node.names:
                    refs.append(ImportRef(source, target, alias.name, node.lineno))
    return sorted(refs)


def is_upper_module(module: str) -> bool:
    upper_prefixes = (
        "lineage_parser.insight",
        "lineage_parser.refactor",
        "lineage_parser.presets",
        "lineage_parser.skill_entry",
        "lineage_parser.scope.scope_views",
        "lineage_parser.serialize._shared",
        "lineage_parser.serialize.llm_profile_index",
        "lineage_parser.serialize.profile_compaction",
        "lineage_parser.serialize.scope_serializer",
        "pipeline",
    )
    return module.startswith(upper_prefixes)


def is_core_module(module: str) -> bool:
    if module in {"lineage_parser", "lineage_parser.cli"}:
        return True
    if module.startswith("lineage_parser.metadata"):
        return True
    if module.startswith("lineage_parser.scope"):
        return not module.startswith("lineage_parser.scope.scope_views")
    return module == "lineage_parser.serialize.scope_profile"


def core_to_upper(refs: list[ImportRef]) -> set[ImportRef]:
    return {ref for ref in refs if is_core_module(ref.source) and is_upper_module(ref.target)}


def pipeline_private_core_imports(refs: list[ImportRef]) -> set[ImportRef]:
    return {
        ref
        for ref in refs
        if ref.source.startswith("pipeline.")
        and ref.target.startswith("lineage_parser.")
        and not is_upper_module(ref.target)
        and (ref.symbol.startswith("_") or ref.target.rpartition(".")[2].startswith("_"))
    }
