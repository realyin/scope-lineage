"""The catalog completeness check (``skills/scope-lineage/scripts/catalog_check.py``).

``catalog validate`` and the merge coverage report catch what is wrong -- a schema error, a
conflict, an unbound column. They pass a catalog that left work undone: a concept drafted
with no attribute at all, an event whose table points at a concept through a foreign
identifier that is not among its participants, and a name or description column bound to
the table's own concept although the code column beside it points at another concept. A
weaker drafter leaves exactly these behind and nothing in the runbook noticed. The check
reads a built ``ontology.json`` (runbook S10g) and lists them.

The tests run it as the runbook does -- a subprocess over a file -- on a made-up catalog
(``concept:task``, ``concept:queue``, ``demo_dwd.task_det``).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "skills" / "scope-lineage" / "scripts" / "catalog_check.py"


def _check(path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True, encoding="utf-8"
    )


def _attr(concept: str, name: str) -> dict:
    return {"id": f"attr:{concept}.{name}", "name": name}


def _ontology(concepts: list[dict], identifiers: list[dict], representations: list[dict]) -> dict:
    return {
        "doc_format": "ontology-json/3",
        "concepts": concepts,
        "identifiers": identifiers,
        "representations": representations,
    }


IDENTIFIERS = [
    {"id": "id:task_id", "identifies": "concept:task"},
    {"id": "id:queue_cd", "identifies": "concept:queue"},
    {"id": "id:cust_id", "identifies": "concept:customer"},
    {"id": "id:rec_id", "identifies": "concept:record"},
]


def _complete() -> dict:
    """A catalog with nothing left undone."""
    return _ontology(
        [
            {"id": "concept:customer", "kind": "entity", "attributes": [_attr("customer", "name")]},
            {"id": "concept:queue", "kind": "entity", "attributes": [_attr("queue", "desc")]},
            {"id": "concept:task", "kind": "entity", "attributes": [_attr("task", "amount")]},
            {
                "id": "concept:record",
                "kind": "event",
                "attributes": [_attr("record", "op_time")],
                "participants": [
                    {"role_name": "customer", "concept": "concept:customer"},
                    {"role_name": "task", "concept": "concept:task"},
                ],
            },
        ],
        IDENTIFIERS,
        [
            {
                "table": "demo_dwd.task_det",
                "concept": "concept:task",
                "bindings": [
                    {"column": "task_id", "to": "identifier", "ref": "id:task_id"},
                    {"column": "queue_cd", "to": "foreign_identifier", "ref": "id:queue_cd"},
                    {"column": "queue_desc", "to": "foreign_attribute", "ref": "attr:queue.desc"},
                    {"column": "amount", "to": "attribute", "ref": "attr:task.amount"},
                ],
            },
            {
                "table": "demo_dwd.record_det",
                "concept": "concept:record",
                "bindings": [
                    {"column": "rec_id", "to": "identifier", "ref": "id:rec_id"},
                    {"column": "cust_id", "to": "foreign_identifier", "ref": "id:cust_id"},
                    {"column": "task_id", "to": "foreign_identifier", "ref": "id:task_id"},
                    {"column": "op_time", "to": "attribute", "ref": "attr:record.op_time"},
                ],
            },
        ],
    )


def _save(tmp_path: Path, ontology: dict) -> Path:
    path = tmp_path / "ontology.json"
    path.write_text(json.dumps(ontology, ensure_ascii=False), encoding="utf-8")
    return path


def _concept(ontology: dict, concept_id: str) -> dict:
    return next(c for c in ontology["concepts"] if c["id"] == concept_id)


def _bindings(ontology: dict, table: str) -> list[dict]:
    return next(r for r in ontology["representations"] if r["table"] == table)["bindings"]


def test_a_complete_catalog_passes(tmp_path):
    result = _check(_save(tmp_path, _complete()))
    assert result.returncode == 0, result.stdout
    assert "0 finding(s)" in result.stdout


def test_a_concept_with_no_attribute_is_reported(tmp_path):
    ontology = _complete()
    _concept(ontology, "concept:queue")["attributes"] = []
    result = _check(_save(tmp_path, ontology))
    assert result.returncode == 1
    line = next(line for line in result.stdout.splitlines() if "empty_concept" in line)
    assert "concept:queue" in line


def test_an_event_missing_a_participant_its_table_points_at_is_reported(tmp_path):
    ontology = _complete()
    _concept(ontology, "concept:record")["participants"] = [{"role_name": "customer", "concept": "concept:customer"}]
    result = _check(_save(tmp_path, ontology))
    assert result.returncode == 1
    line = next(line for line in result.stdout.splitlines() if "missing_participant" in line)
    assert "concept:record" in line and "concept:task" in line and "demo_dwd.record_det.task_id" in line


def test_a_description_column_bound_to_the_wrong_concept_is_reported(tmp_path):
    ontology = _complete()
    desc = next(b for b in _bindings(ontology, "demo_dwd.task_det") if b["column"] == "queue_desc")
    desc.update({"to": "attribute", "ref": "attr:task.queue"})
    result = _check(_save(tmp_path, ontology))
    assert result.returncode == 1
    line = next(line for line in result.stdout.splitlines() if "attribute_beside_foreign_identifier" in line)
    assert "demo_dwd.task_det.queue_desc" in line and "concept:queue" in line and "queue_cd" in line


def test_an_attribute_that_only_shares_a_word_is_not_reported(tmp_path):
    # task_amount and queue_cd share no stem once the suffix is removed.
    ontology = _complete()
    _bindings(ontology, "demo_dwd.task_det").append({"column": "task_amount", "to": "attribute", "ref": "attr:task.amount"})
    result = _check(_save(tmp_path, ontology))
    assert result.returncode == 0, result.stdout


def test_a_foreign_identifier_to_the_events_own_concept_is_not_a_missing_participant(tmp_path):
    ontology = _complete()
    _bindings(ontology, "demo_dwd.record_det").append({"column": "parent_rec_id", "to": "foreign_identifier", "ref": "id:rec_id"})
    result = _check(_save(tmp_path, ontology))
    assert result.returncode == 0, result.stdout


def test_a_missing_file_exits_2(tmp_path):
    result = _check(tmp_path / "nowhere.json")
    assert result.returncode == 2
    assert "nowhere.json" in result.stderr


def test_a_file_that_is_not_an_ontology_exits_2(tmp_path):
    path = tmp_path / "other.json"
    path.write_text(json.dumps({"doc_format": "catalog-digest/1"}), encoding="utf-8")
    result = _check(path)
    assert result.returncode == 2
    assert "ontology-json" in result.stderr


@pytest.mark.parametrize("suffix", ["_desc", "_name"])
def test_both_name_and_description_suffixes_are_matched(tmp_path, suffix):
    ontology = _complete()
    _bindings(ontology, "demo_dwd.task_det").append({"column": f"queue{suffix}", "to": "attribute", "ref": "attr:task.q"})
    result = _check(_save(tmp_path, ontology))
    assert result.returncode == 1
    assert f"demo_dwd.task_det.queue{suffix}" in result.stdout
