"""How often a table is written: one word from the task metadata, read the same everywhere.

The task metadata carries a cycle (``schedule_cycle``: what a reader wants, ``daily``) and a
cron (``schedule``: what actually runs). Some exports write the literal ``unknown`` as the
cycle; read as a value, it hid the cron behind it, so the evidence a build attaches said
``unknown`` for a table the cron says runs on the 5th of each month. ``refresh_cadence`` is
the one rule the evidence and the table card share: a missing or ``unknown`` cycle falls
through to the cron, and ``unknown`` stays only when there is no cron either.

The catalog's two readers then say what they have: the context pack's 刷新 line adds the
cycle note the table-semantics document wrote, and ``catalog query table`` prints the
representation's ``refresh`` as its own line.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scope_lineage.render.catalog_context import context_pack, render_context_text
from scope_lineage.render.catalog_evidence import _cycle
from scope_lineage.render.catalog_query import query_catalog, render_query_text
from scope_lineage.render.table_cards import _render_producers, refresh_cadence

from .table_semantics_demo import DEMO_TABLE, EXAMPLE

ONTOLOGY = Path(__file__).parent / "fixtures" / "catalog" / "ontology.json"
LOAN = "demo_dwd.dwd_lending_loan_df"
MONTHLY = "0 0 0 5,7 * ?"


@pytest.fixture(scope="module")
def document() -> dict:
    return json.loads(ONTOLOGY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def semantics() -> dict:
    return {DEMO_TABLE: json.loads(EXAMPLE.read_text(encoding="utf-8"))}


# ------------------------------------------------------------- the one rule


@pytest.mark.parametrize("cycle", ["unknown", "UNKNOWN", "Unknown", " unknown "])
def test_an_unknown_cycle_falls_through_to_the_cron(cycle: str) -> None:
    assert _cycle({"schedule_cycle": cycle, "schedule": MONTHLY}) == MONTHLY


def test_an_unknown_cycle_with_no_cron_stays_unknown() -> None:
    assert _cycle({"schedule_cycle": "unknown"}) == "unknown"
    assert _cycle({"schedule_cycle": "unknown", "schedule": ""}) == "unknown"


def test_a_real_cycle_is_kept_as_before() -> None:
    assert _cycle({"schedule_cycle": "daily", "schedule": "0 0 0 * * ?"}) == "daily"
    assert _cycle({"schedule_cycle": "DAY"}) == "DAY"


def test_no_cycle_reads_the_cron_and_nothing_reads_nothing() -> None:
    assert _cycle({"schedule": MONTHLY}) == MONTHLY
    assert _cycle({}) is None
    assert _cycle(None) is None


def test_the_table_card_reads_the_same_rule() -> None:
    def producer(refresh) -> dict:
        return {
            "task": "t", "statement_id": "stmt:001", "stmt_kind": "insert_overwrite",
            "partition": {"columns": [], "mode": None}, "refresh": refresh,
        }

    rows = _render_producers({"produced_by": [
        producer({"cycle": "unknown", "cron": MONTHLY}),
        producer({"cycle": "unknown", "cron": None}),
        producer({"cycle": "daily", "cron": "0 0 0 * * ?"}),
        producer(None),
    ]})[2:]
    assert [row.rsplit("|", 2)[1].strip() for row in rows] == [MONTHLY, "unknown", "daily", "未知"]
    assert refresh_cadence({"cycle": "unknown", "cron": MONTHLY}) == MONTHLY


# ------------------------------------------------------------- the readers


def test_the_pack_adds_the_cycle_the_table_semantics_wrote(document: dict, semantics: dict) -> None:
    text = render_context_text(context_pack(document, semantics, tables=[DEMO_TABLE]))
    cycle = semantics[DEMO_TABLE]["summary"]["refresh"]["cycle"]
    assert f"- 时间形态：snapshot；刷新：daily；表语义写的周期：{cycle}" in text


def test_without_a_semantics_cycle_the_refresh_line_is_unchanged(document: dict) -> None:
    text = render_context_text(context_pack(document, None, tables=[DEMO_TABLE]))
    assert "- 时间形态：snapshot；刷新：daily\n" in text


def test_query_table_prints_the_representations_refresh(document: dict) -> None:
    text = render_query_text(query_catalog(document, "table", LOAN))
    assert "  时间语义：快照；按单个 dt 分区取数\n  刷新：daily\n" in text


def test_query_table_prints_no_refresh_line_without_one(document: dict) -> None:
    changed = copy.deepcopy(document)
    for rep in changed["representations"]:
        rep.pop("refresh", None)
    text = render_query_text(query_catalog(changed, "table", LOAN))
    assert "刷新" not in text
