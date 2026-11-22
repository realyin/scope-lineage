"""The synthetic corpora of ``tests/core/fixtures/domain_profile_evidence``, parsed once.

Each corpus is a directory of task JSON files (``tasks/``) and the metadata they were
written against (``schema.json``). The table-name suffixes are the test's own data:
the package knows none of them.
"""

from __future__ import annotations

import json
from pathlib import Path

from scope_lineage.cli import main

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "domain_profile_evidence"


class Corpora:
    """Parses a corpus the first time a test asks for it, under one temporary root."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._parsed: dict[str, Path] = {}

    def lineage(self, name: str) -> Path:
        if name not in self._parsed:
            out = self.root / name / "out"
            code = main([
                "parse", "--input-dir", str(FIXTURES / name / "tasks"),
                "--schema", str(self.schema(name)), "--out", str(out),
            ])
            assert code == 0, f"parse of fixture {name} exited {code}"
            self._parsed[name] = out
        return self._parsed[name]

    @staticmethod
    def schema(name: str) -> Path:
        return FIXTURES / name / "schema.json"

    def evidence(self, name: str, *extra: str) -> dict:
        """``domain-profile evidence`` over one corpus; the evidence.json it wrote."""
        out = self.root / name / ("evidence" + "_".join(extra).replace("-", ""))
        code = main([
            "domain-profile", "evidence", "--lineage", str(self.lineage(name)),
            "--schema", str(self.schema(name)), "--out", str(out), *extra,
        ])
        assert code == 0, f"evidence over fixture {name} exited {code}"
        return json.loads((out / "evidence.json").read_text(encoding="utf-8"))


def suffix(evidence: dict, name: str) -> dict:
    found = [item for item in evidence["suffixes"] if item["suffix"] == name]
    assert found, f"no suffix {name!r} in {[item['suffix'] for item in evidence['suffixes']]}"
    return found[0]
