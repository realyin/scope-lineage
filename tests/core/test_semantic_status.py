"""``semantic status``: where each table of a run stands, and which tables a step still needs.

A run directory holds ``packets/<db.table>/packet.json``, ``docs/<db.table>.json``,
``reviews/<db.table>.md`` and ``pages/<db.table>.md``. The packets are the demo corpus's
(every table it writes, none with a document yet); the one document is the hand-written
example, valid against its packet, and each fixture changes exactly one thing about it
or about its review or page.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from scope_lineage.semantics.digests import document_digest
from scope_lineage.semantics.review_notes import parse_review

from .table_semantics_demo import DEMO_TABLE, demo_packets, example, read_json, run, write_json

STAGES = ["no_packet", "packet", "drafted", "valid", "reviewed", "fixed", "rendered"]


@pytest.fixture(scope="module")
def packets(tmp_path_factory) -> Path:
    return demo_packets(tmp_path_factory.mktemp("status"))


@pytest.fixture
def run_dir(tmp_path: Path, packets: Path) -> Path:
    directory = tmp_path / "run"
    shutil.copytree(packets, directory / "packets")
    return directory


@pytest.fixture
def valid_run(run_dir: Path, packets: Path) -> Path:
    """The run with the example written for the demo table: that table is ``valid``."""
    write_json(run_dir / "docs" / f"{DEMO_TABLE}.json", example(packets))
    return run_dir


def _doc(run_dir: Path) -> dict:
    return read_json(run_dir / "docs" / f"{DEMO_TABLE}.json")


def _review(run_dir: Path, digest: str | None, high=0, medium=0, low=0, body="") -> Path:
    path = run_dir / "reviews" / f"{DEMO_TABLE}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    front = (
        f"---\nreviewed_doc_digest: {digest}\nhigh: {high}\nmedium: {medium}\nlow: {low}\n---\n"
        if digest is not None else ""
    )
    path.write_text(front + "# 审读\n\n" + body + f"高 {high}、中 {medium}、低 {low}\n",
                    encoding="utf-8")
    return path


def _revise(run_dir: Path) -> None:
    """Change the document the way a fix does, keeping it valid."""
    document = _doc(run_dir)
    document["generator"]["prompt"] += "+review"
    write_json(run_dir / "docs" / f"{DEMO_TABLE}.json", document)


def _status(run_dir: Path, *extra: str) -> dict:
    out = run_dir.parent / "status.json"
    assert run("semantic", "status", run_dir, "--json", out, *extra) == 0
    return read_json(out)


def _entry(report: dict, table: str = DEMO_TABLE) -> dict:
    (entry,) = [item for item in report["tables"] if item["table"] == table]
    return entry


def _next(run_dir: Path, step: str, *extra: str) -> dict:
    out = run_dir.parent / "next.json"
    assert run("semantic", "status", run_dir, "--next", step, "--out", out, *extra) == 0
    return read_json(out)


# ------------------------------------------------------------------- stages


def test_a_packet_without_a_document_is_at_packet(run_dir: Path, packets: Path) -> None:
    report = _status(run_dir)
    tables = sorted(path.name for path in packets.iterdir() if (path / "packet.json").is_file())
    assert [entry["table"] for entry in report["tables"]] == tables
    assert {entry["stage"] for entry in report["tables"]} == {"packet"}
    assert report["summary"]["stages"]["packet"] == len(tables)
    assert list(report["summary"]["stages"]) == STAGES


def test_only_narrows_and_a_table_without_a_packet_is_at_no_packet(run_dir: Path) -> None:
    report = _status(run_dir, "--only", DEMO_TABLE, "demo_dwd.dwd_party_absent_df")
    assert [(e["table"], e["stage"]) for e in report["tables"]] == [
        ("demo_dwd.dwd_party_absent_df", "no_packet"),
        (DEMO_TABLE, "packet"),
    ]


def test_a_clean_document_is_valid_and_its_digest_is_reported(valid_run: Path) -> None:
    entry = _entry(_status(valid_run))
    assert entry["stage"] == "valid"
    assert entry["flags"] == []
    assert entry["doc_digest"] == document_digest(_doc(valid_run))
    assert entry["packet_digest"] == _doc(valid_run)["packet_digest"]


def test_a_document_with_failures_is_drafted_and_invalid(valid_run: Path) -> None:
    document = _doc(valid_run)
    document["columns"].pop()
    write_json(valid_run / "docs" / f"{DEMO_TABLE}.json", document)
    entry = _entry(_status(valid_run))
    assert entry["stage"] == "drafted"
    assert entry["flags"] == ["invalid"]
    assert entry["failures"] >= 1


def test_a_document_that_breaks_the_schema_is_drafted_and_invalid(valid_run: Path) -> None:
    document = _doc(valid_run)
    del document["summary"]
    write_json(valid_run / "docs" / f"{DEMO_TABLE}.json", document)
    entry = _entry(_status(valid_run))
    assert (entry["stage"], entry["flags"]) == ("drafted", ["invalid"])
    assert entry["schema_errors"] >= 1


def test_an_unreadable_document_is_drafted_and_invalid(valid_run: Path) -> None:
    (valid_run / "docs" / f"{DEMO_TABLE}.json").write_text("{not json", encoding="utf-8")
    entry = _entry(_status(valid_run))
    assert (entry["stage"], entry["flags"]) == ("drafted", ["invalid"])


def test_a_document_written_against_an_old_packet_is_packet_stale(valid_run: Path) -> None:
    document = _doc(valid_run)
    document["packet_digest"] = "0000000000000000"
    write_json(valid_run / "docs" / f"{DEMO_TABLE}.json", document)
    entry = _entry(_status(valid_run))
    assert (entry["stage"], entry["flags"]) == ("drafted", ["packet_stale"])
    assert entry["doc_packet_digest"] == "0000000000000000"


def test_a_review_with_findings_on_the_current_document_is_reviewed(valid_run: Path) -> None:
    _review(valid_run, document_digest(_doc(valid_run)), high=1, medium=2, low=3)
    entry = _entry(_status(valid_run))
    assert entry["stage"] == "reviewed"
    assert entry["review"] == {
        "reviewed_doc_digest": document_digest(_doc(valid_run)),
        "high": 1, "medium": 2, "low": 3,
    }


def test_a_review_without_high_or_medium_findings_is_fixed(valid_run: Path) -> None:
    _review(valid_run, document_digest(_doc(valid_run)), low=2)
    assert _entry(_status(valid_run))["stage"] == "fixed"


def test_a_revised_valid_document_after_findings_is_fixed(valid_run: Path) -> None:
    _review(valid_run, document_digest(_doc(valid_run)), high=1)
    _revise(valid_run)
    entry = _entry(_status(valid_run))
    assert (entry["stage"], entry["flags"]) == ("fixed", [])


def test_a_revision_that_fails_validation_goes_back_to_drafted(valid_run: Path) -> None:
    _review(valid_run, document_digest(_doc(valid_run)), medium=1)
    document = _doc(valid_run)
    document["columns"].pop()
    write_json(valid_run / "docs" / f"{DEMO_TABLE}.json", document)
    entry = _entry(_status(valid_run))
    assert (entry["stage"], entry["flags"]) == ("drafted", ["invalid"])


def test_a_document_changed_after_a_clean_review_is_review_stale(valid_run: Path) -> None:
    _review(valid_run, document_digest(_doc(valid_run)))
    _revise(valid_run)
    entry = _entry(_status(valid_run))
    assert (entry["stage"], entry["flags"]) == ("valid", ["review_stale"])


def test_a_review_without_front_matter_is_reviewed_and_unparsed(valid_run: Path) -> None:
    _review(valid_run, None, high=1)
    entry = _entry(_status(valid_run))
    assert (entry["stage"], entry["flags"]) == ("reviewed", ["review_unparsed"])
    assert entry["review"] is None


def test_a_page_newer_than_the_document_is_rendered(valid_run: Path) -> None:
    _review(valid_run, document_digest(_doc(valid_run)))
    page = valid_run / "pages" / f"{DEMO_TABLE}.md"
    page.parent.mkdir()
    page.write_text("# page\n", encoding="utf-8")
    doc = valid_run / "docs" / f"{DEMO_TABLE}.json"
    os.utime(doc, (1_000_000, 1_000_000))
    assert _entry(_status(valid_run))["stage"] == "rendered"
    os.utime(page, (500_000, 500_000))
    entry = _entry(_status(valid_run))
    assert (entry["stage"], entry["flags"]) == ("fixed", ["render_stale"])


def test_a_page_before_the_review_is_done_does_not_count(valid_run: Path) -> None:
    page = valid_run / "pages" / f"{DEMO_TABLE}.md"
    page.parent.mkdir()
    page.write_text("# page\n", encoding="utf-8")
    assert _entry(_status(valid_run))["stage"] == "valid"


def test_each_directory_can_be_moved(tmp_path: Path, packets: Path) -> None:
    shutil.copytree(packets, tmp_path / "p")
    write_json(tmp_path / "d" / f"{DEMO_TABLE}.json", example(packets))
    document = read_json(tmp_path / "d" / f"{DEMO_TABLE}.json")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (tmp_path / "r").mkdir()
    (tmp_path / "r" / f"{DEMO_TABLE}.md").write_text(
        f"---\nreviewed_doc_digest: {document_digest(document)}\nhigh: 0\nmedium: 0\n"
        "low: 0\n---\n", encoding="utf-8",
    )
    (tmp_path / "g").mkdir()
    (tmp_path / "g" / f"{DEMO_TABLE}.md").write_text("# page\n", encoding="utf-8")
    report = _status(
        run_dir, "--packets", tmp_path / "p", "--docs", tmp_path / "d",
        "--reviews", tmp_path / "r", "--pages", tmp_path / "g",
    )
    assert _entry(report)["stage"] == "rendered"


def test_the_toolchains_other_documents_beside_the_docs_are_not_tables(valid_run: Path) -> None:
    write_json(valid_run / "docs" / "confirmations.json",
               {"doc_format": "semantic-confirmations/1", "confirmations": []})
    report = _status(valid_run)
    assert "confirmations" not in {entry["table"] for entry in report["tables"]}


# ------------------------------------------------------------------- output


def test_the_text_summary_counts_stages_and_names_flagged_tables(
    valid_run: Path, capsys
) -> None:
    document = _doc(valid_run)
    document["packet_digest"] = "0000000000000000"
    write_json(valid_run / "docs" / f"{DEMO_TABLE}.json", document)
    capsys.readouterr()
    assert run("semantic", "status", valid_run) == 0
    out = capsys.readouterr().out
    assert "drafted 1" in out
    assert f"packet_stale: {DEMO_TABLE}" in out
    assert "no_packet 0" in out


def test_the_text_output_lists_every_table_with_its_stage_and_flags(
    valid_run: Path, capsys
) -> None:
    document = _doc(valid_run)
    document["packet_digest"] = "0000000000000000"
    write_json(valid_run / "docs" / f"{DEMO_TABLE}.json", document)
    report = _status(valid_run)
    capsys.readouterr()
    assert run("semantic", "status", valid_run) == 0
    first, *rest = capsys.readouterr().out.splitlines()

    assert first.startswith(f"Status of {len(report['tables'])} table(s): no_packet ")
    rows = {line.split()[0]: line.split()[1:] for line in rest if not line.split()[0].endswith(":")}
    assert set(rows) == {entry["table"] for entry in report["tables"]}
    assert rows[DEMO_TABLE] == ["drafted", "packet_stale"]
    assert all(rows[entry["table"]] == [entry["stage"]]
               for entry in report["tables"] if entry["table"] != DEMO_TABLE)
    assert rest[-1] == f"  packet_stale: {DEMO_TABLE}"


def test_json_dash_prints_the_report(valid_run: Path, capsys) -> None:
    capsys.readouterr()
    assert run("semantic", "status", valid_run, "--json", "-") == 0

    report = json.loads(capsys.readouterr().out)
    assert report["doc_format"] == "table-semantics-status/1"


def test_json_without_a_path_prints_the_report(valid_run: Path, capsys) -> None:
    capsys.readouterr()
    assert run("semantic", "status", valid_run, "--json") == 0

    report = json.loads(capsys.readouterr().out)
    assert report["doc_format"] == "table-semantics-status/1"


def test_json_without_a_path_and_next_without_out_is_a_usage_error(valid_run: Path) -> None:
    assert run("semantic", "status", valid_run, "--json", "--next", "draft") == 2


def test_json_with_a_path_still_writes_the_file_and_prints_the_summary(
    valid_run: Path, capsys
) -> None:
    out = valid_run.parent / "status.json"
    capsys.readouterr()
    assert run("semantic", "status", valid_run, "--json", out) == 0

    assert read_json(out)["doc_format"] == "table-semantics-status/1"
    assert DEMO_TABLE in capsys.readouterr().out


def test_a_missing_run_directory_is_a_usage_error(tmp_path: Path) -> None:
    assert run("semantic", "status", tmp_path / "absent") == 2


def test_two_documents_on_stdout_is_a_usage_error(valid_run: Path) -> None:
    assert run("semantic", "status", valid_run, "--json", "-", "--next", "draft") == 2


def test_the_digest_command_prints_the_document_digest(valid_run: Path, capsys) -> None:
    path = valid_run / "docs" / f"{DEMO_TABLE}.json"
    capsys.readouterr()
    assert run("semantic", "digest", path) == 0
    assert capsys.readouterr().out.split() == [document_digest(_doc(valid_run)), str(path)]


def test_the_document_digest_ignores_key_order_and_layout() -> None:
    document = example()
    reordered = dict(reversed(list(document.items())))
    assert document_digest(document) == document_digest(reordered)
    assert len(document_digest(document)) == 16
    changed = example()
    changed["steps"].append("x")
    assert document_digest(changed) != document_digest(document)


# ------------------------------------------------------------------- next


def test_next_draft_batches_every_table_without_a_valid_document(
    valid_run: Path, packets: Path
) -> None:
    report = _status(valid_run)
    others = sorted(e["table"] for e in report["tables"] if e["table"] != DEMO_TABLE)
    plan = _next(valid_run, "draft", "--batch-size", "3")
    assert plan["step"] == "draft"
    assert plan["batches"] == [others[i:i + 3] for i in range(0, len(others), 3)]
    document = _doc(valid_run)
    document["packet_digest"] = "0000000000000000"
    write_json(valid_run / "docs" / f"{DEMO_TABLE}.json", document)
    flat = [t for batch in _next(valid_run, "draft", "--batch-size", "3")["batches"] for t in batch]
    assert flat == sorted([*others, DEMO_TABLE])


def test_next_skips_tables_without_a_packet(run_dir: Path) -> None:
    plan = _next(run_dir, "draft", "--only", "demo_dwd.dwd_party_absent_df")
    assert plan["batches"] == []


def test_next_walks_one_table_through_review_fix_and_render(valid_run: Path) -> None:
    assert _next(valid_run, "review")["batches"] == [[DEMO_TABLE]]
    assert _next(valid_run, "fix")["batches"] == []
    _review(valid_run, document_digest(_doc(valid_run)), high=1)
    assert _next(valid_run, "review")["batches"] == []
    assert _next(valid_run, "fix")["batches"] == [[DEMO_TABLE]]
    assert _next(valid_run, "render")["batches"] == []
    _revise(valid_run)
    assert _next(valid_run, "fix")["batches"] == []
    assert _next(valid_run, "render")["batches"] == [[DEMO_TABLE]]
    page = valid_run / "pages" / f"{DEMO_TABLE}.md"
    page.parent.mkdir()
    page.write_text("# page\n", encoding="utf-8")
    assert _next(valid_run, "render")["batches"] == []


def test_a_stale_clean_review_is_reviewed_again(valid_run: Path) -> None:
    _review(valid_run, document_digest(_doc(valid_run)))
    _revise(valid_run)
    assert _next(valid_run, "review")["batches"] == [[DEMO_TABLE]]


def test_an_unparsed_review_is_not_dispatched(valid_run: Path) -> None:
    _review(valid_run, None, high=1)
    for step in ("review", "fix", "render"):
        assert _next(valid_run, step)["batches"] == []


def test_next_without_out_prints_the_plan(valid_run: Path, capsys) -> None:

    capsys.readouterr()
    assert run("semantic", "status", valid_run, "--next", "review") == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan == {"doc_format": "table-semantics-next/1", "step": "review",
                    "batches": [[DEMO_TABLE]]}


def test_the_plan_and_the_report_beside_the_docs_are_skipped_by_validate(
    valid_run: Path,
) -> None:
    _status(valid_run)
    shutil.copy(valid_run.parent / "status.json", valid_run / "docs" / "status.json")
    assert run("semantic", "validate", valid_run / "docs", "--packets",
               valid_run / "packets") == 0


# ------------------------------------------------------------------- front matter


def test_front_matter_is_read_with_quotes_and_crlf() -> None:
    text = '---\r\nreviewed_doc_digest: "abc"\r\nhigh: 1\r\nmedium: 0\r\nlow: 2\r\n---\r\n# x\r\n'
    assert parse_review(text) == {"reviewed_doc_digest": "abc", "high": 1, "medium": 0, "low": 2}


@pytest.mark.parametrize("text", [
    "# no front matter\n",
    "---\nreviewed_doc_digest: abc\nhigh: 1\nmedium: 0\n---\n",
    "---\nreviewed_doc_digest: abc\nhigh: one\nmedium: 0\nlow: 0\n---\n",
    "---\nreviewed_doc_digest: abc\nhigh: -1\nmedium: 0\nlow: 0\n---\n",
    "---\nreviewed_doc_digest: \nhigh: 1\nmedium: 0\nlow: 0\n---\n",
    "---\nreviewed_doc_digest: abc\nhigh: 1\nmedium: 0\nlow: 0\n",
])
def test_incomplete_front_matter_is_unparsed(text: str) -> None:
    assert parse_review(text) is None
