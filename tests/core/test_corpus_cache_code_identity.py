"""The corpus cache is keyed on the code that derived it, not only on its version string.

A source checkout keeps whatever version its install metadata last recorded, so a
version-only key let a run after a code change reuse facts derived by the old code. The
options digest therefore also carries a digest of the package's own files.
"""

from __future__ import annotations

from pathlib import Path

from scope_lineage import corpus_cache
from scope_lineage.corpus_cache import options_digest, source_digest


def _tree(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def test_editing_one_module_moves_the_source_digest(tmp_path: Path) -> None:
    before = source_digest(_tree(tmp_path / "a", {"x.py": "A = 1\n", "s/y.json": "{}"}))
    after = source_digest(_tree(tmp_path / "b", {"x.py": "A = 2\n", "s/y.json": "{}"}))

    assert before != after


def test_the_source_digest_ignores_where_the_package_lives(tmp_path: Path) -> None:
    files = {"x.py": "A = 1\n", "s/y.json": "{}"}

    assert source_digest(_tree(tmp_path / "a", files)) == source_digest(
        _tree(tmp_path / "b", files)
    )


def test_bytecode_caches_do_not_move_the_source_digest(tmp_path: Path) -> None:
    clean = source_digest(_tree(tmp_path / "a", {"x.py": "A = 1\n"}))
    compiled = source_digest(
        _tree(tmp_path / "b", {"x.py": "A = 1\n", "__pycache__/x.cpython-312.pyc": "junk"})
    )

    assert clean == compiled


def test_the_options_digest_moves_with_the_code(monkeypatch) -> None:
    before = options_digest(["same", "options"])
    monkeypatch.setattr(corpus_cache, "_code_digest", lambda: "another-code-digest")

    assert options_digest(["same", "options"]) != before
