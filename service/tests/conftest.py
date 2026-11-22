"""Shared inputs: the demo ontology and table-semantics document from the repository."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from service_paths import ONTOLOGY, SEMANTICS


@pytest.fixture
def inputs(tmp_path: Path) -> dict[str, Path]:
    """Copies the server may watch change: an ontology, a semantics directory, a pending path."""
    ontology = tmp_path / "ontology.json"
    shutil.copyfile(ONTOLOGY, ontology)
    semantics = tmp_path / "semantics"
    shutil.copytree(SEMANTICS, semantics)
    return {"ontology": ontology, "semantics": semantics, "pending": tmp_path / "pending.jsonl"}
