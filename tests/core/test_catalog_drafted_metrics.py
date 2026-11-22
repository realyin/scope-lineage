"""6.3-b: a drafted metric counts toward the pages' drafted share.

``catalog validate`` counted metrics, but ``index.md`` (the whole document) and
``governance.md`` (one row per concept) left them out, so adding a drafted metric moved
neither page. The ontology-json/3 schema also left ``metrics`` out of ``required`` although
``build`` always writes it.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from scope_lineage.render.catalog_pages import render_catalog_pages

ONTOLOGY = Path(__file__).parent / "fixtures" / "catalog" / "ontology.json"
SCHEMA = Path(__file__).parents[2] / "scope_lineage" / "schemas" / "ontology-v3.schema.json"


def _document(*metrics: dict) -> dict:
    document = json.loads(ONTOLOGY.read_text(encoding="utf-8"))
    document = copy.deepcopy(document)
    document["metrics"] = list(metrics)
    return document


def _metric(status: str) -> dict:
    return {
        "id": f"metric:probe_{status}",
        "name": "probe",
        "on": "concept:disbursement",
        "aggregation": "count",
        "constraints": [],
        "dimensions": [],
        "status": status,
        "source": None,
        "evidence": [],
    }


def _share(text: str, label: str) -> tuple[int, int]:
    row = next(line for line in text.splitlines() if label in line)
    drafted, total = re.search(r"(\d+)/(\d+)", row).groups()
    return int(drafted), int(total)


def _governance_row(pages: dict, concept: str) -> tuple[int, int]:
    return _share(pages["governance.md"], concept)


def test_a_drafted_metric_counts_on_the_index_page() -> None:
    before = _share(render_catalog_pages(_document())["index.md"], "草拟对象占比")
    after = _share(render_catalog_pages(_document(_metric("drafted")))["index.md"], "草拟对象占比")
    assert after == (before[0] + 1, before[1] + 1)


def test_a_confirmed_metric_counts_only_in_the_total() -> None:
    before = _share(render_catalog_pages(_document())["index.md"], "草拟对象占比")
    after = _share(render_catalog_pages(_document(_metric("confirmed")))["index.md"], "草拟对象占比")
    assert after == (before[0], before[1] + 1)


def test_a_drafted_metric_counts_on_its_concept_s_governance_row() -> None:
    before = render_catalog_pages(_document())
    after = render_catalog_pages(_document(_metric("drafted")))
    name = "放款"
    drafted, total = _governance_row(before, name)
    assert _governance_row(after, name) == (drafted + 1, total + 1)


def test_another_concept_s_row_is_unchanged() -> None:
    """Sentinel: the metric belongs to the concept it is on, and to no other."""
    before = render_catalog_pages(_document())
    after = render_catalog_pages(_document(_metric("drafted")))
    assert _governance_row(after, "借据") == _governance_row(before, "借据")


def test_the_schema_requires_metrics() -> None:
    assert "metrics" in json.loads(SCHEMA.read_text(encoding="utf-8"))["required"]
