"""Cross-task tracing: query.py trace walks lineage through multiple task artifacts.

A single lineage.json stops at the task boundary: chain ends at the task's physical
sources, impact lists direct consumers only. `trace` joins tasks by table name across a
corpus of artifacts and walks N hops upstream and/or downstream. Re-parsing 1755 docs
(~19s) per query is not acceptable, so trace maintains a routing index file at the
corpus root and refreshes it incrementally by file fingerprint.

Fixture corpus: task_a (ods.orders -> dwd.orders_clean), task_b (dwd -> dm.order_stats),
task_c (dm -> app.order_report), all catalog-qualified, produced by the real CLI.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
QUERY = REPO / "skills" / "scope-lineage" / "scripts" / "query.py"

TASK_SQL = {
    "task_a": """
INSERT INTO cat.dwd.orders_clean
SELECT o.order_id, o.amount AS amt, o.status
FROM cat.ods.orders o;
""",
    "task_b": """
INSERT INTO cat.dm.order_stats
SELECT c.order_id, SUM(c.amt) AS total_amt
FROM cat.dwd.orders_clean c
GROUP BY c.order_id;
""",
    "task_c": """
INSERT INTO cat.app.order_report
SELECT s.order_id, s.total_amt AS report_amt
FROM cat.dm.order_stats s;
""",
}


def _build_corpus(root: Path, tasks: dict[str, str]) -> Path:
    from scope_lineage.cli import main

    out = root / "artifacts"
    for name, sql in tasks.items():
        sql_path = root / f"{name}.sql"
        sql_path.write_text(sql, encoding="utf-8")
        assert main(["parse", "--sql-file", str(sql_path), "--out", str(out)]) == 0
    return out


@pytest.fixture()
def corpus(tmp_path: Path) -> Path:
    return _build_corpus(tmp_path, TASK_SQL)


def _run(*args: str) -> tuple[str, str]:
    result = subprocess.run(
        [sys.executable, str(QUERY), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout, result.stderr


# ---------------------------------------------------------------- index lifecycle


def test_trace_builds_a_reusable_index_at_the_corpus_root(corpus: Path) -> None:
    index_path = corpus / ".scope-lineage-index.json"
    assert not index_path.exists()

    _, err_first = _run("trace", "cat.dm.order_stats.total_amt", str(corpus))
    assert index_path.is_file()
    assert "index: built (3 task docs)" in err_first

    _, err_second = _run("trace", "cat.dm.order_stats.total_amt", str(corpus))
    assert "index: reused (3 task docs)" in err_second


def test_trace_index_refreshes_changed_and_new_docs_only(corpus: Path) -> None:
    _run("trace", "cat.dm.order_stats.total_amt", str(corpus))

    # rewrite one doc (content change -> fingerprint change)
    doc_path = corpus / "task_a" / "lineage.json"
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    doc_path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    # and add a brand-new task doc
    _build_corpus(
        doc_path.parents[2],
        {
            "task_d": """
INSERT INTO cat.app.order_export
SELECT r.order_id FROM cat.app.order_report r;
"""
        },
    )

    out, err = _run(
        "trace", "cat.app.order_report.order_id", str(corpus), "--downstream", "1"
    )
    assert "index: updated (+1 ~1 -0, 4 task docs)" in err
    assert "cat.app.order_export.order_id" in out


def test_trace_index_survives_doc_deletion(corpus: Path) -> None:
    _run("trace", "cat.dm.order_stats.total_amt", str(corpus))
    (corpus / "task_c" / "lineage.json").unlink()

    out, err = _run(
        "trace", "cat.dm.order_stats.total_amt", str(corpus), "--downstream", "2"
    )
    assert "index: updated (+0 ~0 -1, 2 task docs)" in err
    assert "order_report" not in out


# ---------------------------------------------------------------- upstream


def test_trace_walks_upstream_across_tasks_to_the_physical_boundary(
    corpus: Path,
) -> None:
    out, _ = _run(
        "trace", "cat.dm.order_stats.total_amt", str(corpus), "--upstream", "3"
    )
    # hop 1: inside task_b, total_amt comes from dwd.orders_clean.amt
    assert "cat.dm.order_stats.total_amt <- cat.dwd.orders_clean.amt" in out
    # hop 2: task_a produced orders_clean.amt from ods.orders.amount
    assert "cat.dwd.orders_clean.amt <- cat.ods.orders.amount" in out
    # boundary: nothing in the corpus produces ods.orders
    assert "cat.ods.orders.amount: no producing task in corpus" in out


def test_trace_upstream_depth_is_respected(corpus: Path) -> None:
    out, _ = _run(
        "trace", "cat.dm.order_stats.total_amt", str(corpus), "--upstream", "1"
    )
    assert "cat.dm.order_stats.total_amt <- cat.dwd.orders_clean.amt" in out
    assert "cat.ods.orders.amount" not in out


# ---------------------------------------------------------------- downstream


def test_trace_walks_downstream_across_tasks(corpus: Path) -> None:
    out, _ = _run(
        "trace", "cat.dwd.orders_clean.amt", str(corpus), "--downstream", "3"
    )
    # hop 1: task_b consumes amt into dm.order_stats.total_amt
    assert "cat.dwd.orders_clean.amt -> cat.dm.order_stats.total_amt" in out
    # hop 2: task_c carries it into app.order_report.report_amt
    assert "cat.dm.order_stats.total_amt -> cat.app.order_report.report_amt" in out


def test_trace_downstream_depth_is_respected(corpus: Path) -> None:
    out, _ = _run(
        "trace", "cat.dwd.orders_clean.amt", str(corpus), "--downstream", "1"
    )
    assert "cat.dm.order_stats.total_amt" in out
    assert "order_report" not in out


def test_trace_defaults_to_one_hop_each_direction(corpus: Path) -> None:
    out, _ = _run("trace", "cat.dm.order_stats.total_amt", str(corpus))
    assert "== upstream ==" in out
    assert "== downstream ==" in out
    assert "cat.dwd.orders_clean.amt" in out


def test_trace_reports_unknown_start_point(corpus: Path) -> None:
    out, _ = _run("trace", "cat.dm.no_such_table.col", str(corpus))
    assert "not found" in out.lower()


# ---------------------------------------------------------------- cycles


CYCLE_SQL = {
    "task_x": """
INSERT INTO cat.dwd.table_a
SELECT b.k, b.v AS av FROM cat.dwd.table_b b;
""",
    "task_y": """
INSERT INTO cat.dwd.table_b
SELECT a.k, a.av AS v FROM cat.dwd.table_a a;
""",
}


def test_trace_terminates_on_cross_task_cycles(tmp_path: Path) -> None:
    corpus = _build_corpus(tmp_path, CYCLE_SQL)
    out, _ = _run("trace", "cat.dwd.table_a.av", str(corpus), "--upstream", "10")
    assert "cat.dwd.table_a.av <- cat.dwd.table_b.v" in out
    assert "cat.dwd.table_b.v <- cat.dwd.table_a.av" in out
    # the cycle is reported once per direction, then the walk stops
    assert "[hop 3]" not in out


# ---------------------------------------------------------------- name resolution


def test_trace_resolves_underqualified_table_names(corpus: Path) -> None:
    out, _ = _run("trace", "dm.order_stats.total_amt", str(corpus), "--upstream", "1")
    assert "resolved: dm.order_stats.total_amt -> cat.dm.order_stats.total_amt" in out
    assert "cat.dm.order_stats.total_amt <- cat.dwd.orders_clean.amt" in out


def test_chain_accepts_underqualified_table_names(corpus: Path) -> None:
    out, _ = _run("chain", "dm.order_stats.total_amt", str(corpus / "task_b"))
    assert "not found" not in out.lower()
    assert "chain -> total_amt" in out
    assert "cat.dwd.orders_clean" in out


def test_impact_accepts_underqualified_table_names(corpus: Path) -> None:
    out, _ = _run("impact", "dwd.orders_clean.amt", str(corpus))
    assert "no consumers found" not in out.lower()
    assert "total_amt" in out


MIXED_QUALIFICATION_SQL = {
    "task_writer": """
INSERT INTO cat.dwd.orders_clean
SELECT o.order_id, o.amount AS amt FROM cat.ods.orders o;
""",
    # reads the same table under its 2-part hive spelling
    "task_reader": """
INSERT INTO cat.dm.order_stats
SELECT c.order_id, SUM(c.amt) AS total_amt
FROM dwd.orders_clean c
GROUP BY c.order_id;
""",
}


def test_trace_joins_tables_recorded_under_mixed_qualification(tmp_path: Path) -> None:
    corpus = _build_corpus(tmp_path, MIXED_QUALIFICATION_SQL)
    up, _ = _run("trace", "cat.dm.order_stats.total_amt", str(corpus), "--upstream", "3")
    # hop 1 records the source as written in the reader's SQL
    assert "cat.dm.order_stats.total_amt <- dwd.orders_clean.amt" in up
    # hop 2 must join the 2-part spelling to the 3-part producer
    assert "dwd.orders_clean.amt <- cat.ods.orders.amount" in up

    down, _ = _run(
        "trace", "cat.dwd.orders_clean.amt", str(corpus), "--downstream", "1"
    )
    assert "cat.dm.order_stats.total_amt" in down
