"""Annotations that Python 3.9 evaluates at runtime must not use `X | Y`.

The CI matrix starts at 3.9, where `str | None` is a TypeError unless the module has
`from __future__ import annotations`. Most modules here have it; the ones that do not
have simply avoided the syntax, which is invisible until a 3.9 job fails minutes into
a CI run. A dataclass field is the easy way to trip it, because its annotation is
evaluated when the class is built.
"""
from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "scope_lineage"


def _evaluated_union_annotations(source: str) -> list[tuple[int, str]]:
    """`X | Y` annotations in a module that does not defer annotation evaluation."""
    tree = ast.parse(source)
    for node in tree.body:
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "__future__"
            and any(alias.name == "annotations" for alias in node.names)
        ):
            return []
    return [
        (node.lineno, ast.unparse(node.annotation))
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign) and isinstance(node.annotation, ast.BinOp)
    ]


def test_no_runtime_evaluated_union_annotations():
    offenders = {
        str(path.relative_to(PACKAGE)): found
        for path in sorted(PACKAGE.rglob("*.py"))
        if (found := _evaluated_union_annotations(path.read_text(encoding="utf-8")))
    }
    assert not offenders, (
        "these annotations are evaluated at runtime and break on Python 3.9; "
        "add `from __future__ import annotations` to the module or quote the "
        f"annotation: {offenders}"
    )
