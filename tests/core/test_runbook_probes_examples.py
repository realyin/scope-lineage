"""The worked examples of the runbook's query-writing template pass ``semantic probes check``.

T-probes (``skills/scope-lineage-ontology/references/templates/T-probes.md``) shows the
writing agent one query of each shape that can land as an observation. An example the
checker would refuse teaches every run to fail S9b, so the JSON block is taken from the
template as written and checked over the demo corpus. The examples write ``<问题原文>`` for
``asked`` and name a second question ``q2``: the test puts in the demo document's question
texts (adding ``q2`` as an open question when the document has only ``q1``), nothing else.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
from pathlib import Path

import pytest

from .table_semantics_demo import DEMO_TABLE, ROOT, demo_packets, example, run, write_json

TEMPLATE = ROOT / "skills" / "scope-lineage-ontology" / "references" / "templates" / "T-probes.md"


def _examples() -> dict:
    body = TEMPLATE.read_text(encoding="utf-8").split("----8<----", 2)[1]
    blocks = re.findall(r"```json\n(.*?)```", body, re.S)
    assert len(blocks) == 1, "T-probes should carry exactly one JSON example block"
    return json.loads(blocks[0])


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("run")
    packets = demo_packets(root)
    document = example(packets)
    questions = document["summary"].setdefault("questions", [])
    if not any(q.get("id") == "q2" for q in questions):
        questions.append({"id": "q2", "text": "gender_cd 还有哪些取值？", "status": "open"})
    write_json(root / "docs" / f"{DEMO_TABLE}.json", document)
    return root


def test_the_template_examples_pass_the_probes_check(run_dir, tmp_path):
    probes = _examples()
    document = json.loads((run_dir / "docs" / f"{DEMO_TABLE}.json").read_text(encoding="utf-8"))
    texts = {q["id"]: q["text"] for q in document["summary"]["questions"]}
    for item in probes["items"]:
        assert item["table"] == DEMO_TABLE and item["asked"] == "<问题原文>"
        item["asked"] = texts[item["question"]]
    path = write_json(tmp_path / "probes" / "question-probes.json", probes)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = run("semantic", "probes", "check", str(path), "--packets", str(run_dir / "packets"),
                   "--docs", str(run_dir / "docs"), "--json")
    report = json.loads(out.getvalue())
    failures = [(item["id"], f["check"], f["message"])
                for item in report["items"] for f in item["findings"] if f["level"] == "FAIL"]
    assert code == 0 and failures == [] and report["schema_errors"] == [], (failures, err.getvalue())
    assert report["summary"]["failures"] == 0
    lands = {item.get("lands") for item in probes["items"]}
    assert {"summary.row.observed", "column:gender_cd.observed_values"} <= lands
    assert any(str(target).startswith("input:") for target in lands)
