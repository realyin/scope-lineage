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


# ---- semantic omissions: states, units, code columns, and rules the digest carries ----

def _check_with(path: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(path), *extra], capture_output=True, text=True, encoding="utf-8"
    )


def _lines(result: subprocess.CompletedProcess, kind: str) -> list[str]:
    return [line for line in result.stdout.splitlines() if line.startswith(kind + " ")]


DIGEST = {
    "doc_format": "catalog-digest/1",
    "tables": [
        {"table": "demo_dwd.task_det", "rules": [
            {"id": "r1", "kind": "filter", "text": "只读当日分区"},
            {"id": "r2", "kind": "dedup", "text": "每个 task_id 留最新一条"},
            {"id": "r3", "kind": "join", "text": "按 queue_cd 关联队列"},
            {"id": "r12", "kind": "derive", "text": "金额为空时写 0"},
        ]},
        {"table": "demo_dwd.record_det", "rules": []},
        {"table": "demo_dwd.no_rules_det"},
    ],
}


def _save_digest(tmp_path: Path, digest: dict = DIGEST) -> Path:
    path = tmp_path / "digest.json"
    path.write_text(json.dumps(digest, ensure_ascii=False), encoding="utf-8")
    return path


def test_a_state_attribute_with_codes_but_no_states_is_reported(tmp_path):
    ontology = _complete()
    task = _concept(ontology, "concept:task")
    task["attributes"].append({"id": "attr:task.status", "name": "状态", "category": "state", "code_set": "code:task_status"})
    task["attributes"].append({"id": "attr:task.phase", "name": "阶段", "category": "state"})   # no codes: nothing to draft
    result = _check(_save(tmp_path, ontology))
    assert result.returncode == 1
    lines = _lines(result, "state_without_states")
    assert len(lines) == 1 and "concept:task" in lines[0] and "attr:task.status" in lines[0]
    # ``states`` is one state machine (an object), as ``catalog build`` writes it
    task["states"] = {"attribute": "attr:task.status", "values": [{"value": "1", "name": "进行中"}], "transitions": []}
    assert _check(_save(tmp_path, ontology)).returncode == 0, _check(_save(tmp_path, ontology)).stdout


def test_one_state_machine_covers_the_concept_and_events_carry_none(tmp_path):
    ontology = _complete()
    task = _concept(ontology, "concept:task")
    task["attributes"] += [
        {"id": "attr:task.status", "name": "状态", "category": "state", "code_set": "code:task_status"},
        {"id": "attr:task.result", "name": "结果", "category": "state", "code_set": "code:task_result"},
    ]
    task["states"] = {"attribute": "attr:task.status", "values": [], "transitions": []}
    record = _concept(ontology, "concept:record")   # an event: the schema gives it no states
    record["attributes"].append({"id": "attr:record.outcome", "name": "结果", "category": "state", "code_set": "code:outcome"})
    result = _check(_save(tmp_path, ontology))
    assert result.returncode == 0, result.stdout


def test_a_measure_without_a_unit_is_reported(tmp_path):
    ontology = _complete()
    amount = _concept(ontology, "concept:task")["attributes"][0]
    amount["category"] = "measure"
    result = _check(_save(tmp_path, ontology))
    assert result.returncode == 1
    assert any("attr:task.amount" in line for line in _lines(result, "measure_without_unit"))
    amount["unit"] = "元"
    assert _check(_save(tmp_path, ontology)).returncode == 0


def test_a_code_column_naming_another_concept_bound_as_a_plain_attribute_is_reported(tmp_path):
    ontology = _complete()
    bindings = _bindings(ontology, "demo_dwd.task_det")
    bindings.append({"column": "cust_no", "to": "attribute", "ref": "attr:task.cust"})      # stem of id:cust_id's column
    bindings.append({"column": "queue_code", "to": "attribute", "ref": "attr:task.queue"})  # concept:queue's name
    bindings.append({"column": "batch_no", "to": "attribute", "ref": "attr:task.batch"})    # names no concept
    bindings.append({"column": "remark", "to": "attribute", "ref": "attr:task.remark"})
    # a coded value with its code set is not a pointer
    _concept(ontology, "concept:task")["attributes"].append({"id": "attr:task.kind", "name": "类型", "code_set": "code:kind"})
    bindings.append({"column": "kind_cd", "to": "attribute", "ref": "attr:task.kind"})
    result = _check(_save(tmp_path, ontology))
    assert result.returncode == 1
    lines = _lines(result, "code_attribute_without_relation")
    assert len(lines) == 2
    assert "demo_dwd.task_det.cust_no" in lines[0] and "concept:customer" in lines[0]
    assert "demo_dwd.task_det.queue_code" in lines[1] and "concept:queue" in lines[1]
    assert result.stdout.splitlines()[-1] == "2 finding(s)"
    # a code column that names no concept is listed for a look, and does not count
    assert "demo_dwd.task_det.batch_no" in result.stdout
    assert "demo_dwd.task_det.kind_cd" not in result.stdout


def test_without_a_digest_no_rule_is_checked(tmp_path):
    assert _check(_save(tmp_path, _complete())).returncode == 0


def test_a_filter_dedup_or_derive_rule_no_constraint_carries_is_reported(tmp_path):
    result = _check_with(_save(tmp_path, _complete()), "--digest", str(_save_digest(tmp_path)))
    assert result.returncode == 1
    found = sorted(line.split()[1] for line in _lines(result, "unabsorbed_rule"))
    assert found == ["demo_dwd.task_det#r1", "demo_dwd.task_det#r12", "demo_dwd.task_det#r2"]   # join: not asked
    assert result.stdout.splitlines()[-1] == "3 finding(s)"


def test_a_rule_is_absorbed_by_a_constraint_or_a_skip_line(tmp_path):
    ontology = _complete()
    ontology["constraints"] = [{"id": "con:task_latest", "kind": "unique", "on": "concept:task",
                                "rules": ["demo_dwd.task_det#r2"]}]
    changes = tmp_path / "catalog_changes.md"
    changes.write_text("# changes\n\n- demo_dwd.task_det#r1 skip: 只是分区读取，不是业务约束\n", encoding="utf-8")
    result = _check_with(_save(tmp_path, ontology), "--digest", str(_save_digest(tmp_path)), "--changes", str(changes))
    found = [line.split()[1] for line in _lines(result, "unabsorbed_rule")]
    assert found == ["demo_dwd.task_det#r12"]                  # r1 in changes does not cover r12
    changes.write_text("- demo_dwd.task_det#r12 skip: 回填值已写在属性定义里\n" + changes.read_text(encoding="utf-8"),
                       encoding="utf-8")
    result = _check_with(_save(tmp_path, ontology), "--digest", str(_save_digest(tmp_path)), "--changes", str(changes))
    assert result.returncode == 0, result.stdout


def test_a_missing_or_wrong_digest_or_changes_file_exits_2(tmp_path):
    ontology = _save(tmp_path, _complete())
    assert _check_with(ontology, "--digest", str(tmp_path / "none.json")).returncode == 2
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"doc_format": "ontology-json/3"}), encoding="utf-8")
    result = _check_with(ontology, "--digest", str(wrong))
    assert result.returncode == 2 and "catalog-digest" in result.stderr
    assert _check_with(ontology, "--digest", str(_save_digest(tmp_path)), "--changes", str(tmp_path / "none.md")).returncode == 2


def test_a_state_attribute_coded_through_its_binding_counts_and_a_skip_line_clears_it(tmp_path):
    ontology = _complete()
    _concept(ontology, "concept:task")["attributes"].append({"id": "attr:task.result", "name": "结果", "category": "state"})
    _bindings(ontology, "demo_dwd.task_det").append(
        {"column": "result_cd", "to": "attribute", "ref": "attr:task.result", "code_sets": ["code:result"]}
    )
    path = _save(tmp_path, ontology)
    result = _check(path)
    assert any("concept:task" in line for line in _lines(result, "state_without_states")), result.stdout
    changes = tmp_path / "catalog_changes.md"
    changes.write_text("- concept:task states skip: 结果列不是生命周期状态\n", encoding="utf-8")
    assert _check_with(path, "--changes", str(changes)).returncode == 0


def test_only_a_skip_line_clears_a_rule_and_a_quoted_concept_id_still_skips_states(tmp_path):
    ontology = _complete()
    _concept(ontology, "concept:task")["attributes"].append(
        {"id": "attr:task.status", "name": "状态", "category": "state", "code_set": "code:task_status"}
    )
    path = _save(tmp_path, ontology)
    changes = tmp_path / "catalog_changes.md"
    changes.write_text(
        "- 讨论过 demo_dwd.task_det#r1，还没定\n"
        "- `demo_dwd.task_det#r2` skip: 去重是表的写法\n"
        "- `demo_dwd.task_det#r12` skip: 回填已写进属性定义\n"
        "- `concept:task` states skip: 状态列只是标志\n",
        encoding="utf-8",
    )
    result = _check_with(path, "--digest", str(_save_digest(tmp_path)), "--changes", str(changes))
    assert [line.split()[1] for line in _lines(result, "unabsorbed_rule")] == ["demo_dwd.task_det#r1"]
    assert _lines(result, "state_without_states") == []


def test_an_empty_concept_with_no_table_of_its_own_is_cleared_by_an_empty_skip_line(tmp_path):
    ontology = _complete()
    _concept(ontology, "concept:queue")["attributes"] = []   # only ever a foreign identifier's target
    _bindings(ontology, "demo_dwd.task_det").remove(
        {"column": "queue_desc", "to": "foreign_attribute", "ref": "attr:queue.desc"}
    )
    path = _save(tmp_path, ontology)
    result = _check(path)
    line = _lines(result, "empty_concept")[0]
    assert "concept:queue empty skip:" in line                  # the hint names the skip line
    changes = tmp_path / "catalog_changes.md"
    changes.write_text("- `concept:queue` empty skip: 本批没有它的表，属性在别的表里\n", encoding="utf-8")
    assert _check_with(path, "--changes", str(changes)).returncode == 0


def test_an_empty_skip_line_does_not_clear_a_concept_that_has_its_own_table(tmp_path):
    ontology = _complete()
    _concept(ontology, "concept:task")["attributes"] = []
    path = _save(tmp_path, ontology)
    changes = tmp_path / "catalog_changes.md"
    changes.write_text("- concept:task empty skip: 不想建\n", encoding="utf-8")
    result = _check_with(path, "--changes", str(changes))
    line = _lines(result, "empty_concept")[0]
    assert "concept:task" in line and "demo_dwd.task_det" in line   # its table's columns are where attributes come from
    assert "empty skip" not in line


@pytest.mark.parametrize(
    ("metric", "missing"),
    [
        ({"aggregation": "sum", "unit": "元", "additivity": "additive"}, "measure"),
        ({"aggregation": "sum", "measure": "attr:task.amount", "additivity": "additive"}, "unit"),
        ({"aggregation": "avg", "measure": "attr:task.amount", "unit": "元"}, "additivity"),
    ],
)
def test_a_metric_missing_its_measure_unit_or_additivity_is_reported(tmp_path, metric, missing):
    ontology = _complete()
    ontology["metrics"] = [{"id": "metric:task_amount", "on": "concept:task", **metric}]
    result = _check(_save(tmp_path, ontology))
    assert result.returncode == 1
    line = _lines(result, "metric_incomplete")[0]
    assert "metric:task_amount" in line and missing in line


def test_a_count_metric_needs_no_measure(tmp_path):
    ontology = _complete()
    ontology["metrics"] = [
        {"id": "metric:task_count", "on": "concept:task", "aggregation": "count", "unit": "个", "additivity": "additive"},
        {"id": "metric:task_amount", "on": "concept:task", "aggregation": "sum", "measure": "attr:task.amount",
         "unit": "元", "additivity": "additive"},
    ]
    assert _check(_save(tmp_path, ontology)).returncode == 0
