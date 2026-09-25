"""Shared helpers for the catalog tests: the demo catalog and ways to break one copy of it.

Every failing fixture is the demo with exactly one thing changed, so a test names the one
rule it is about and a green demo run proves the fixture broke nothing else.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable

import yaml

from scope_lineage.catalog.loader import yaml_loader

DEMO = Path(__file__).resolve().parents[2] / "examples" / "catalog-demo"
# The demo's lineage corpus: eight synthetic scheduler tasks that write and read the
# demo's tables, and the schema metadata they are parsed with.
CORPUS = Path(__file__).resolve().parents[2] / "examples" / "catalog-demo-corpus"


def parse_demo_corpus(target: Path) -> Path:
    """Parse the demo's tasks into ``target`` exactly as the docs tell a reader to."""
    from scope_lineage.cli import main

    code = main([
        "parse",
        "--input-dir", str(CORPUS / "tasks"),
        "--schema", str(CORPUS / "schema_info.json"),
        "--out", str(target),
    ])
    assert code == 0, "the demo corpus must parse"
    return target


def demo_tables(lineage: Path, target: Path) -> Path:
    """``scope-lineage tables`` over the parsed corpus: the file ``--tables`` reads."""
    from scope_lineage.cli import main

    assert main(["tables", "--lineage", str(lineage), "--out", str(target)]) == 0
    return target / "tables.json"


def copy_demo(tmp_path: Path) -> Path:
    target = tmp_path / "catalog"
    shutil.copytree(DEMO, target)
    return target


def read_file(path: Path):
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    # The catalog's own YAML reading (1.2 booleans): ``on:`` stays a key, not True.
    return yaml.load(text, Loader=yaml_loader())  # noqa: S506 - a SafeLoader subclass


def write_file(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".json":
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def mutate(root: Path, relative: str, change: Callable[[dict], None]) -> None:
    """Load one catalog file, let ``change`` edit it in place, write it back."""
    path = root / relative
    data = read_file(path)
    change(data)
    write_file(path, data)


def item(items: list, key: str, value: str | None = None) -> dict:
    """The one entry of ``items`` whose ``key`` (``id`` by default) is ``value``."""
    if value is None:
        key, value = "id", key
    matches = [entry for entry in items if entry.get(key) == value]
    assert len(matches) == 1, f"expected one {key}={value!r}, got {len(matches)}"
    return matches[0]


def rules(findings) -> list[str]:
    return sorted({finding.rule for finding in findings})
