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
    # rather than copied from the statement. `commented_task` is the third: the only
    # document shape that carries `task_meta`, which exists at task level and nowhere
    # else (WI-2.2). `set_preamble_task` is the fourth: a script whose header block is
    # written above a `SET` preamble, so the block belongs to no modelled statement and
    # has to be hoisted onto the first write and held once as `script_comments` (B1).
    assert [case.name for case in CASES] == [
        "commented_task",
        "delete_all",
        "merge_cte_source",
        "set_preamble_task",
    ]


def test_task_lineage_contract_matches_golden_bytes(tmp_path: Path) -> None:
    for case_dir in CASES:
        case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
        result = parse_task_lineage(
            case["sql"],
            task_name=case["task_id"],
            schema=case["schema"],
            # Only the cases that model a task JSON carry one; a `.sql` input has none,
            # and passing an empty object would publish a key the CLI never would.
            **({"task_meta": case["task_meta"]} if "task_meta" in case else {}),
        )

        for run in ("first", "second"):
            output = write_task_lineage(result, tmp_path / case_dir.name / run)
            for name in ("lineage.json", "diagnostics.json"):
                assert (output / name).read_bytes() == _golden_bytes(
                    case_dir / name
                ), f"{case_dir.name}/{name}"


def test_every_golden_statement_entry_validates_against_the_statement_schema() -> None:
    """The "1.0" schema survives the retired v1 artifact as the statement-document
    schema; every statement_lineage entry a task document embeds must satisfy it."""
    import json

    from scope_lineage.contract.validation import validate_lineage_document

    fixtures = Path(__file__).parent / "fixtures" / "task_lineage_contract"
    entries = 0
    for lineage_path in sorted(fixtures.glob("*/lineage.json")):
        document = json.loads(lineage_path.read_text(encoding="utf-8"))
        for entry in (document.get("statement_lineage") or {}).values():
            validate_lineage_document(entry)
            entries += 1
    assert entries, "no statement entries in the golden corpus -- fixture layout changed?"
