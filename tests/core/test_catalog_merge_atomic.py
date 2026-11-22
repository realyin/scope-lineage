"""D4: ``catalog merge --atomic`` writes nothing unless the merged catalog is clean.

Without the flag the documented contract holds: a merge whose result has validation
errors is still written, so the errors can be read in place. ``--atomic`` merges into a
staging copy first, validates it there, and only then puts the changed files in place;
on conflicts, unknown concepts or validation errors nothing is written.
"""

from __future__ import annotations

from pathlib import Path

from scope_lineage.cli import main

from .catalog_demo import DEMO, copy_demo
from .test_catalog_fragment import EXAMPLE, _example
from .test_catalog_merge import _snapshot, _write


def _merge(*argv) -> int:
    return main(["catalog", "merge", *[str(arg) for arg in argv]])


def _broken(tmp_path: Path) -> Path:
    fragment = _example()
    fragment["representations"][0]["bindings"][3]["ref"] = "attr:disbursement.missing"
    return _write(tmp_path / "broken.json", fragment)


def _leftovers(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.iterdir() if path.name.startswith("."))


def test_an_atomic_in_place_merge_with_errors_leaves_the_base_untouched(
    tmp_path: Path, capsys
) -> None:
    base = copy_demo(tmp_path)
    before = _snapshot(base)

    assert _merge(base, _broken(tmp_path), "--in-place", "--atomic") == 1

    captured = capsys.readouterr()
    assert "attr:disbursement.missing" in captured.out
    assert "--atomic" in captured.err and "nothing written" in captured.err
    assert _snapshot(base) == before
    assert _leftovers(tmp_path) == []


def test_an_atomic_merge_into_out_with_errors_creates_nothing(tmp_path: Path) -> None:
    out = tmp_path / "merged"

    assert _merge(DEMO, _broken(tmp_path), "--out", out, "--atomic") == 1

    assert not out.exists()
    assert _leftovers(tmp_path) == []


def test_an_atomic_merge_into_an_empty_out_keeps_it_empty_on_errors(tmp_path: Path) -> None:
    out = tmp_path / "merged"
    out.mkdir()

    assert _merge(DEMO, _broken(tmp_path), "--out", out, "--atomic") == 1

    assert out.is_dir() and not any(out.iterdir())


def test_a_clean_atomic_merge_writes_what_a_plain_merge_writes(tmp_path: Path) -> None:
    plain, atomic_out = tmp_path / "plain", tmp_path / "atomic"
    base = copy_demo(tmp_path)

    assert _merge(DEMO, EXAMPLE, "--out", plain) == 0
    assert _merge(DEMO, EXAMPLE, "--out", atomic_out, "--atomic") == 0
    assert _merge(base, EXAMPLE, "--in-place", "--atomic") == 0

    assert _snapshot(atomic_out) == _snapshot(plain)
    assert _snapshot(base) == _snapshot(plain)
    assert _leftovers(tmp_path) == []


def test_without_atomic_a_merge_with_errors_is_still_written(tmp_path: Path) -> None:
    """Sentinel: the documented default -- written, so the errors can be read in place."""
    base = copy_demo(tmp_path)
    before = _snapshot(base)

    assert _merge(base, _broken(tmp_path), "--in-place") == 1

    assert _snapshot(base) != before
