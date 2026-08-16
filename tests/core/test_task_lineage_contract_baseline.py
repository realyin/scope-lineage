"""Byte-exact baseline for the task-level 2.0 contract."""

from __future__ import annotations

import json
from pathlib import Path

from scope_lineage import parse_task_lineage, write_task_lineage


FIXTURES = Path(__file__).parent / "fixtures" / "task_lineage_contract"
CASES = tuple(sorted(path.parent for path in FIXTURES.glob("*/case.json")))


def _golden_bytes(path: Path) -> bytes:
    content = path.read_bytes()
    return content[:-1] if content.endswith(b"\n") else content


def test_baseline_covers_the_required_task_contract_shapes() -> None:
    # An emptied table and a MERGE whose row-membership sources have to be traced
    # through a query block are the two shapes whose task-level output is derived
    # rather than copied from the statement.
    assert [case.name for case in CASES] == ["delete_all", "merge_cte_source"]


def test_task_lineage_contract_matches_golden_bytes(tmp_path: Path) -> None:
    for case_dir in CASES:
        case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
        result = parse_task_lineage(
            case["sql"],
            task_name=case["task_id"],
            schema=case["schema"],
        )

        for run in ("first", "second"):
            output = write_task_lineage(result, tmp_path / case_dir.name / run)
            for name in ("lineage.json", "diagnostics.json"):
                assert (output / name).read_bytes() == _golden_bytes(
                    case_dir / name
                ), f"{case_dir.name}/{name}"
