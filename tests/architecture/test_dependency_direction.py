"""Lock the package-level dependency direction: cli -> contract -> (serialize, scope) -> metadata.

Same spirit as verify_distribution.py: the boundary is a product decision, so a new
cross-package import edge must show up as a red test naming the exact import, not as
silent architecture drift.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "scope_lineage"
PACKAGE_NAME = "scope_lineage"

# First-level subpackages/modules whose edges are governed (`cli` also covers the cli_*
# command modules). Other package-root leaf modules
# (sqlglot_config, and any future ones) are usable from anywhere and not listed.
GOVERNED = {
    "catalog", "cli", "contract", "metadata", "questions", "render", "scope", "semantics",
    "serialize",
}

ALLOWED_EDGES: dict[str, set[str]] = {
    # The command layer: cli.py and every cli_*.py beside it. It routes each subcommand to
    # the package that does the work, so it reaches the derived views and the knowledge
    # workflow packages too; what it may not reach is `serialize` (writing goes through
    # `contract`), and nothing below may import it back.
    "cli": {"catalog", "contract", "metadata", "questions", "render", "scope", "semantics"},
    "contract": {"scope", "serialize"},
    "serialize": {"scope"},
    "scope": {"metadata"},
    "metadata": set(),
    "render": set(),  # contract-derived: consumes the JSON documents only
    "catalog": set(),  # the concept catalog: a person's files in, ontology-json/3 out
    # Table semantics sits one step above the derived views: its packet is built from the
    # semantic profile and the table cards (`render`), and nothing else. Lineage, task
    # JSON and schema metadata are loaded by `cli_semantic` and handed over as plain data,
    # so the parser and the metadata loaders stay out of this package.
    "semantics": {"render"},
    # Acceptance questions: question sets, grades and answers in, sheets and scores out.
    # `cli_questions` reads the files and hands them over as plain data.
    "questions": set(),
}


def _layer(name: str) -> str:
    """``cli.py`` and the ``cli_*`` command modules beside it are one routing layer."""
    return "cli" if name.startswith("cli_") else name


def _package_of(module_path: Path, package_root: Path = PACKAGE_ROOT) -> str:
    relative = module_path.relative_to(package_root)
    return _layer(relative.parts[0].removesuffix(".py"))


def _imported_packages(
    node: ast.Import | ast.ImportFrom, importer_pkg: str, *, at_root: bool
) -> list[str]:
    """The first-level scope_lineage packages an import statement targets."""
    if isinstance(node, ast.Import):
        modules = [alias.name.split(".") for alias in node.names]
        targets = [parts[1] for parts in modules if parts[0] == PACKAGE_NAME and len(parts) > 1]
    else:
        target = _imported_package(node, importer_pkg, at_root=at_root)
        targets = [target] if target else []
    return [_layer(target) for target in targets]


def _imported_package(node: ast.ImportFrom, importer_pkg: str, *, at_root: bool) -> str | None:
    """Return the first-level scope_lineage package a `from ... import` targets, if any."""
    if node.level == 0:
        if not node.module or not node.module.startswith(PACKAGE_NAME):
            return None
        parts = node.module.split(".")
        return parts[1] if len(parts) > 1 else None
    if node.level == 1:
        # Relative to the importer's own package: internal edge, not governed here --
        # except at the package root (cli.py, cli_*.py), where `from .x import` targets
        # first-level x.
        if not at_root:
            return importer_pkg
        return (node.module or "").split(".")[0] or None
    # level >= 2 from inside a subpackage reaches the package root: `from ..x import`.
    return (node.module or "").split(".")[0] or None


# One known inverted edge, evaluated at the v1 retirement (governance plan WI-12, 0.3.0)
# and KEPT: statement_lineage entries are the task contract's own payload, so the task
# builder legitimately assembles them through the statement converter; re-homing the
# converter would only trade this documented edge for a scope<->serialize package cycle.
WHITELISTED_EDGES = {
    ("scope/task_lineage.py", "contract"),
}


def collect_violations(package_root: Path = PACKAGE_ROOT) -> list[str]:
    violations: list[str] = []
    for module_path in sorted(package_root.rglob("*.py")):
        importer_pkg = _package_of(module_path, package_root)
        if importer_pkg not in GOVERNED:
            continue
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            at_root = module_path.parent == package_root
            for target in _imported_packages(node, importer_pkg, at_root=at_root):
                if target not in GOVERNED or target == importer_pkg:
                    continue
                if target in ALLOWED_EDGES[importer_pkg]:
                    continue
                in_package = module_path.relative_to(package_root).as_posix()
                if (in_package, target) in WHITELISTED_EDGES:
                    continue
                relative = module_path.relative_to(package_root.parent)
                violations.append(
                    f"{relative}:{node.lineno} imports {PACKAGE_NAME}.{target} "
                    f"({importer_pkg} -> {target} is not an allowed edge)"
                )
    return violations


def test_package_dependency_direction_is_locked() -> None:
    violations = collect_violations()
    assert not violations, "forbidden cross-package imports:\n" + "\n".join(violations)


def _package(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / PACKAGE_NAME
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def test_plain_import_statements_are_governed_too(tmp_path: Path) -> None:
    root = _package(tmp_path, {"render/view.py": "import scope_lineage.scope.facts\n"})

    violations = collect_violations(root)

    assert violations == [
        f"{PACKAGE_NAME}/render/view.py:1 imports {PACKAGE_NAME}.scope "
        "(render -> scope is not an allowed edge)"
    ]


def test_command_routing_modules_cannot_be_imported_from_below(tmp_path: Path) -> None:
    root = _package(
        tmp_path, {"render/view.py": "from ..cli_glossary import load_overrides\n"}
    )

    violations = collect_violations(root)

    assert violations == [
        f"{PACKAGE_NAME}/render/view.py:1 imports {PACKAGE_NAME}.cli "
        "(render -> cli is not an allowed edge)"
    ]


def test_relative_imports_from_root_level_modules_reach_their_target(tmp_path: Path) -> None:
    root = _package(tmp_path, {"cli_tables.py": "from .serialize import write\n"})

    violations = collect_violations(root)

    assert violations == [
        f"{PACKAGE_NAME}/cli_tables.py:1 imports {PACKAGE_NAME}.serialize "
        "(cli -> serialize is not an allowed edge)"
    ]
