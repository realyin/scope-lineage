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


def _review(run_dir: Path, digest: str | None, high=0, medium=0, low=0, body="",
            packet: str | None = None) -> Path:
    """The review of the demo table; ``packet`` is its ``reviewed_packet_digest`` (none: an
    old review, written before the key existed)."""
    path = run_dir / "reviews" / f"{DEMO_TABLE}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    keyed = f"reviewed_packet_digest: {packet}\n" if packet is not None else ""
    front = (
        f"---\nreviewed_doc_digest: {digest}\n{keyed}high: {high}\nmedium: {medium}\n"
        f"low: {low}\n---\n"
        if digest is not None else ""
    )
    path.write_text(front + "# 审读\n\n" + body + f"高 {high}、中 {medium}、低 {low}\n",
                    encoding="utf-8")
    return path


def _keyed_review(run_dir: Path, high=0, medium=0, low=0, body="") -> Path:
    """A review of the current document that names the packet it read (review@5)."""
    document = _doc(run_dir)
    return _review(run_dir, document_digest(document), high=high, medium=medium, low=low,
                   body=body, packet=document["packet_digest"])


def _revise(run_dir: Path) -> None:
    """Change the document the way a fix does, keeping it valid."""
    document = _doc(run_dir)
    document["generator"]["prompt"] += "+review"
    write_json(run_dir / "docs" / f"{DEMO_TABLE}.json", document)


def _rebuild_packet_and_rewrite(run_dir: Path, marker: bool = False) -> None:
    """The packet changes and the document is written again from scratch against it.

    The packet's digest stands for a rebuilt packet; the rewrite says something else in
    ``summary.what`` and, with ``marker``, keeps the ``+review`` a fix once added.
    """
    rebuilt = "aaaaaaaaaaaaaaaa"
    path = run_dir / "packets" / DEMO_TABLE / "packet.json"
    packet = read_json(path)
    packet["packet_digest"] = rebuilt
    write_json(path, packet)
    document = _doc(run_dir)
    document["packet_digest"] = rebuilt
    document["summary"]["what"] += "（重写）"
    if marker and not document["generator"]["prompt"].endswith("+review"):
        document["generator"]["prompt"] += "+review"
    write_json(run_dir / "docs" / f"{DEMO_TABLE}.json", document)


def _fixed(run_dir: Path, *extra: str) -> int:
    return run("semantic", "fixed", run_dir, "--only", DEMO_TABLE, *extra)


def _review_bytes(run_dir: Path) -> bytes:
    return (run_dir / "reviews" / f"{DEMO_TABLE}.md").read_bytes()


def _batches(run_dir: Path, step: str) -> list:
    return [table for batch in _next(run_dir, step)["batches"] for table in batch]


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
        "reviewed_packet_digest": None, "fixed_doc_digest": None,
        "high": 1, "medium": 2, "low": 3,
    }


def test_a_review_without_high_or_medium_findings_is_fixed(valid_run: Path) -> None:
    _review(valid_run, document_digest(_doc(valid_run)), low=2)
    assert _entry(_status(valid_run))["stage"] == "fixed"


def test_a_revised_valid_document_after_findings_is_fixed(valid_run: Path) -> None:
    _keyed_review(valid_run, high=1)
    _revise(valid_run)
    assert _fixed(valid_run) == 0
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
    assert report["doc_format"] == "table-semantics-status/2"


def test_json_without_a_path_prints_the_report(valid_run: Path, capsys) -> None:
    capsys.readouterr()
    assert run("semantic", "status", valid_run, "--json") == 0

    report = json.loads(capsys.readouterr().out)
    assert report["doc_format"] == "table-semantics-status/2"


def test_json_without_a_path_and_next_without_out_is_a_usage_error(valid_run: Path) -> None:
    assert run("semantic", "status", valid_run, "--json", "--next", "draft") == 2


def test_json_with_a_path_still_writes_the_file_and_prints_the_summary(
    valid_run: Path, capsys
) -> None:
    out = valid_run.parent / "status.json"
    capsys.readouterr()
    assert run("semantic", "status", valid_run, "--json", out) == 0

    assert read_json(out)["doc_format"] == "table-semantics-status/2"
    assert DEMO_TABLE in capsys.readouterr().out


def test_one_table_checked_in_an_isolated_docs_directory(valid_run: Path, capsys) -> None:
    """The fix prompt's step 5: ``--docs <dir> --only <table> --json -`` answers for that table."""
    document = _doc(valid_run)
    _keyed_review(valid_run, medium=1)
    _revise(valid_run)
    isolated = valid_run.parent / "val-demo"
    isolated.mkdir()
    shutil.copy(valid_run / "docs" / f"{DEMO_TABLE}.json", isolated / f"{DEMO_TABLE}.json")
    assert _fixed(valid_run) == 0
    capsys.readouterr()
    assert run("semantic", "status", valid_run, "--docs", isolated, "--only", DEMO_TABLE,
               "--json", "-") == 0

    (entry,) = json.loads(capsys.readouterr().out)["tables"]
    assert (entry["table"], entry["stage"]) == (DEMO_TABLE, "fixed")
    assert entry["doc_digest"] == document_digest(_doc(valid_run))
    assert entry["review"]["reviewed_doc_digest"] == document_digest(document)
    assert entry["review"]["fixed_doc_digest"] == document_digest(_doc(valid_run))


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
    _keyed_review(valid_run, high=1)
    assert _next(valid_run, "review")["batches"] == []
    assert _next(valid_run, "fix")["batches"] == [[DEMO_TABLE]]
    assert _next(valid_run, "render")["batches"] == []
    _revise(valid_run)
    assert _next(valid_run, "fix")["batches"] == [[DEMO_TABLE]]
    assert _fixed(valid_run) == 0
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
    assert parse_review(text) == {"reviewed_doc_digest": "abc", "reviewed_packet_digest": None,
                                  "fixed_doc_digest": None, "high": 1, "medium": 0, "low": 2}


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


def test_front_matter_reads_the_packet_key_and_the_fix_record() -> None:
    text = ("---\nreviewed_doc_digest: 0123456789abcdef\nreviewed_packet_digest: 89abcdef01234567\n"
            "high: 0\nmedium: 1\nlow: 0\nfixed_doc_digest: fedcba9876543210\n---\n# x\n")
    assert parse_review(text) == {
        "reviewed_doc_digest": "0123456789abcdef", "reviewed_packet_digest": "89abcdef01234567",
        "fixed_doc_digest": "fedcba9876543210", "high": 0, "medium": 1, "low": 0,
    }


@pytest.mark.parametrize("value", ["xyz", "", "fedcba987654321", "FEDCBA9876543210 x"])
def test_a_malformed_fix_record_is_no_fix_record(value: str) -> None:
    text = (f"---\nreviewed_doc_digest: abc\nhigh: 1\nmedium: 0\nlow: 0\n"
            f"fixed_doc_digest: {value}\n---\n")
    review = parse_review(text)
    assert review is not None
    assert review["fixed_doc_digest"] is None
    assert (review["reviewed_doc_digest"], review["high"]) == ("abc", 1)


# ------------------------------------------------------------------- reviews, revisions, rewrites


def test_the_report_names_every_flag(valid_run: Path) -> None:
    assert list(_status(valid_run)["summary"]["flags"]) == [
        "packet_stale", "invalid", "review_packet_stale", "review_stale", "fix_unconfirmed",
        "review_unparsed", "render_stale", "doc_misfiled",
    ]


def test_a_keyless_old_review_and_a_rewritten_document_is_not_dispatched_to_fix(
    valid_run: Path,
) -> None:
    """An old review (no packet key) asked for changes; the packet changed and the document
    was written again. Nothing says the review applies to the new document: review again."""
    _review(valid_run, document_digest(_doc(valid_run)), high=1)
    _rebuild_packet_and_rewrite(valid_run)
    entry = _entry(_status(valid_run))
    assert (entry["stage"], entry["flags"]) == ("valid", ["review_stale"])
    assert DEMO_TABLE not in _batches(valid_run, "fix")
    assert DEMO_TABLE in _batches(valid_run, "review")


def test_a_keyless_old_review_and_a_rewrite_that_kept_the_marker_is_not_dispatched_to_fix(
    valid_run: Path,
) -> None:
    """The same, with the rewrite still carrying a fix's ``+review``: the marker decides nothing."""
    _review(valid_run, document_digest(_doc(valid_run)), high=1, medium=2)
    _revise(valid_run)
    _rebuild_packet_and_rewrite(valid_run, marker=True)
    assert _doc(valid_run)["generator"]["prompt"].endswith("+review")
    entry = _entry(_status(valid_run))
    assert (entry["stage"], entry["flags"]) == ("valid", ["review_stale"])
    assert DEMO_TABLE not in _batches(valid_run, "fix")
    assert DEMO_TABLE in _batches(valid_run, "review")


def test_a_keyless_old_review_and_a_revised_document_is_reviewed_again(valid_run: Path) -> None:
    """Without the packet key a revision and a rewrite look the same: both go back to review."""
    _review(valid_run, document_digest(_doc(valid_run)), medium=1)
    _revise(valid_run)
    entry = _entry(_status(valid_run))
    assert (entry["stage"], entry["flags"]) == ("valid", ["review_stale"])
    assert DEMO_TABLE in _batches(valid_run, "review")


def test_a_keyed_review_of_another_packet_is_review_packet_stale(valid_run: Path) -> None:
    _keyed_review(valid_run, high=1)
    _rebuild_packet_and_rewrite(valid_run)
    entry = _entry(_status(valid_run))
    assert (entry["stage"], entry["flags"]) == ("valid", ["review_packet_stale"])
    assert DEMO_TABLE not in _batches(valid_run, "fix")
    assert DEMO_TABLE in _batches(valid_run, "review")


def test_a_mistyped_packet_key_is_not_fixed_and_not_dispatched_to_fix(valid_run: Path) -> None:
    """A packet key that matches no packet: the review cannot be tied to this one."""
    _review(valid_run, document_digest(_doc(valid_run)), high=1, packet="0123456789abcdef")
    _revise(valid_run)
    entry = _entry(_status(valid_run))
    assert (entry["stage"], entry["flags"]) == ("valid", ["review_packet_stale"])
    assert DEMO_TABLE not in _batches(valid_run, "fix")
    assert DEMO_TABLE in _batches(valid_run, "review")
    before = _review_bytes(valid_run)
    assert _fixed(valid_run) == 1
    assert _review_bytes(valid_run) == before


def test_an_interrupted_fix_of_a_keyed_review_is_fix_unconfirmed(valid_run: Path) -> None:
    """The fix changed the document but never recorded that it finished: fix it again."""
    _keyed_review(valid_run, high=1, medium=2)
    _revise(valid_run)
    entry = _entry(_status(valid_run))
    assert (entry["stage"], entry["flags"]) == ("reviewed", ["fix_unconfirmed"])
    assert _batches(valid_run, "fix") == [DEMO_TABLE]
    assert DEMO_TABLE not in _batches(valid_run, "review")


def test_a_fix_record_makes_the_revised_document_fixed(valid_run: Path) -> None:
    _keyed_review(valid_run, high=1)
    _revise(valid_run)
    assert _fixed(valid_run) == 0
    entry = _entry(_status(valid_run))
    assert (entry["stage"], entry["flags"]) == ("fixed", [])
    assert entry["review"]["fixed_doc_digest"] == entry["doc_digest"]
    assert _batches(valid_run, "render") == [DEMO_TABLE]


def test_fixing_the_lows_with_a_fix_record_is_fixed(valid_run: Path) -> None:
    """A review with low findings only, which the fix took up: recorded, it is fixed."""
    _keyed_review(valid_run, low=2)
    _revise(valid_run)
    entry = _entry(_status(valid_run))
    assert (entry["stage"], entry["flags"]) == ("valid", ["review_stale"])
    assert _fixed(valid_run) == 0
    entry = _entry(_status(valid_run))
    assert (entry["stage"], entry["flags"]) == ("fixed", [])
    assert entry["review"]["fixed_doc_digest"] == document_digest(_doc(valid_run))


def test_a_document_edited_after_its_fix_record_is_fix_unconfirmed(valid_run: Path) -> None:
    _keyed_review(valid_run, medium=1)
    _revise(valid_run)
    assert _fixed(valid_run) == 0
    _revise(valid_run)
    entry = _entry(_status(valid_run))
    assert (entry["stage"], entry["flags"]) == ("reviewed", ["fix_unconfirmed"])


def test_a_new_review_drops_the_fix_record(valid_run: Path) -> None:
    _keyed_review(valid_run, high=1)
    _revise(valid_run)
    assert _fixed(valid_run) == 0
    _keyed_review(valid_run, medium=1)
    entry = _entry(_status(valid_run))
    assert (entry["stage"], entry["flags"]) == ("reviewed", [])
    assert entry["review"]["fixed_doc_digest"] is None


def test_a_fixed_and_rendered_table_is_rendered(valid_run: Path) -> None:
    _keyed_review(valid_run, high=1)
    _revise(valid_run)
    assert _fixed(valid_run) == 0
    page = valid_run / "pages" / f"{DEMO_TABLE}.md"
    page.parent.mkdir()
    page.write_text("# page\n", encoding="utf-8")
    assert _entry(_status(valid_run))["stage"] == "rendered"


def test_a_prior_review_beside_the_reviews_is_not_a_table_nor_the_review(
    valid_run: Path,
) -> None:
    """``reviews/<t>.prior.md`` is the old review kept for the rewrite's first review."""
    _review(valid_run, document_digest(_doc(valid_run)), high=1)
    reviews = valid_run / "reviews"
    (reviews / f"{DEMO_TABLE}.md").rename(reviews / f"{DEMO_TABLE}.prior.md")
    report = _status(valid_run)
    assert all(not entry["table"].endswith(".prior") for entry in report["tables"])
    entry = _entry(report)
    assert (entry["stage"], entry["review"]) == ("valid", None)


# ------------------------------------------------------------------- semantic fixed


def test_semantic_fixed_writes_the_record_into_the_front_matter_only(valid_run: Path) -> None:
    path = _keyed_review(valid_run, high=1, body="## 高\n\n1. x\n")
    before = path.read_text(encoding="utf-8")
    _revise(valid_run)
    assert _fixed(valid_run) == 0
    after = path.read_text(encoding="utf-8")
    digest = document_digest(_doc(valid_run))
    lines = after.splitlines()
    end = lines.index("---", 1)
    assert f"fixed_doc_digest: {digest}" in lines[1:end]
    assert after.replace(f"fixed_doc_digest: {digest}\n", "") == before
    _revise(valid_run)
    assert _fixed(valid_run) == 0
    replaced = path.read_text(encoding="utf-8")
    assert replaced.count("fixed_doc_digest:") == 1
    assert f"fixed_doc_digest: {document_digest(_doc(valid_run))}" in replaced


def test_semantic_fixed_keeps_crlf_line_ends(valid_run: Path) -> None:
    document = _doc(valid_run)
    path = valid_run / "reviews" / f"{DEMO_TABLE}.md"
    path.parent.mkdir()
    path.write_bytes(
        (f"---\r\nreviewed_doc_digest: {document_digest(document)}\r\n"
         f"reviewed_packet_digest: {document['packet_digest']}\r\n"
         "high: 1\r\nmedium: 0\r\nlow: 0\r\n---\r\n# 审读\r\n").encode("utf-8")
    )
    _revise(valid_run)
    assert _fixed(valid_run) == 0
    text = path.read_bytes().decode("utf-8")
    assert f"fixed_doc_digest: {document_digest(_doc(valid_run))}\r\n---\r\n" in text
    assert "\n" not in text.replace("\r\n", "")
    assert _entry(_status(valid_run))["stage"] == "fixed"


def test_semantic_fixed_refuses_an_invalid_document(valid_run: Path) -> None:
    _keyed_review(valid_run, medium=1)
    document = _doc(valid_run)
    document["columns"].pop()
    write_json(valid_run / "docs" / f"{DEMO_TABLE}.json", document)
    before = _review_bytes(valid_run)
    assert _fixed(valid_run) == 1
    assert _review_bytes(valid_run) == before


def test_semantic_fixed_refuses_a_review_of_another_packet(valid_run: Path) -> None:
    _keyed_review(valid_run, high=1)
    _rebuild_packet_and_rewrite(valid_run)
    before = _review_bytes(valid_run)
    assert _fixed(valid_run) == 1
    assert _review_bytes(valid_run) == before
    assert _entry(_status(valid_run))["stage"] == "valid"


def test_semantic_fixed_refuses_a_keyless_review(valid_run: Path) -> None:
    _review(valid_run, document_digest(_doc(valid_run)), high=1)
    _revise(valid_run)
    before = _review_bytes(valid_run)
    assert _fixed(valid_run) == 1
    assert _review_bytes(valid_run) == before


def test_semantic_fixed_refuses_the_document_the_review_read(valid_run: Path) -> None:
    _keyed_review(valid_run, high=1)
    before = _review_bytes(valid_run)
    assert _fixed(valid_run) == 1
    assert _review_bytes(valid_run) == before


@pytest.mark.parametrize("case", ["no review", "no front matter", "no document"])
def test_semantic_fixed_refuses_without_a_review_or_a_document(
    valid_run: Path, case: str
) -> None:
    if case == "no front matter":
        _review(valid_run, None, high=1)
    elif case == "no document":
        _keyed_review(valid_run, high=1)
        (valid_run / "docs" / f"{DEMO_TABLE}.json").unlink()
    assert _fixed(valid_run) == 1


def test_semantic_fixed_needs_a_run_directory_and_a_table(tmp_path: Path) -> None:
    assert run("semantic", "fixed", tmp_path / "absent", "--only", DEMO_TABLE) == 2
    with pytest.raises(SystemExit):
        run("semantic", "fixed", tmp_path)


# ------------------------------------------------------------------- --only before <run>


def test_status_only_before_the_run_reads_as_the_run_first(valid_run: Path, capsys) -> None:
    assert run("semantic", "status", valid_run, "--only", DEMO_TABLE) == 0
    expected = capsys.readouterr().out
    assert run("semantic", "status", "--only", DEMO_TABLE, valid_run) == 0
    assert capsys.readouterr().out == expected
    assert run("semantic", "status", "--only", DEMO_TABLE, "--", valid_run) == 0
    assert capsys.readouterr().out == expected
    assert f"{DEMO_TABLE}  valid" in expected


def test_fixed_only_before_the_run_writes_the_record(valid_run: Path) -> None:
    _keyed_review(valid_run, high=1)
    _revise(valid_run)
    assert run("semantic", "fixed", "--only", DEMO_TABLE, valid_run) == 0
    assert _entry(_status(valid_run))["stage"] == "fixed"


@pytest.mark.parametrize("command", ["status", "fixed"])
def test_only_swallowing_a_word_that_is_no_run_is_an_error(
    valid_run: Path, capsys, command: str
) -> None:
    with pytest.raises(SystemExit) as raised:
        run("semantic", command, "--only", DEMO_TABLE, "run_typo")
    assert raised.value.code == 2
    err = capsys.readouterr().err
    assert "--only takes every word after it" in err
    assert "put run before --only" in err


# ------------------------------------------------------------------- doc_misfiled

OTHER_TABLE = "demo_dwd.dwd_lending_borrower_df"


def test_a_document_in_another_tables_file_flags_both_tables(valid_run: Path, capsys) -> None:
    """``docs/<b>.json`` holding table ``a`` beside ``docs/<a>.json``: ``b`` looks unwritten."""
    write_json(valid_run / "docs" / f"{OTHER_TABLE}.json", _doc(valid_run))
    report = _status(valid_run)
    other, demo = _entry(report, OTHER_TABLE), _entry(report, DEMO_TABLE)
    assert (other["stage"], other["flags"]) == ("packet", ["doc_misfiled"])
    assert demo["flags"] == ["doc_misfiled"]
    assert report["summary"]["flags"]["doc_misfiled"] == [OTHER_TABLE, DEMO_TABLE]
    assert run("semantic", "status", valid_run) == 0
    assert f"  doc_misfiled: {OTHER_TABLE}, {DEMO_TABLE}\n" in capsys.readouterr().out


def test_a_document_under_a_name_no_table_has_flags_its_table(valid_run: Path) -> None:
    (valid_run / "docs" / f"{DEMO_TABLE}.json").rename(valid_run / "docs" / "doc.json")
    entry = _entry(_status(valid_run))
    assert (entry["stage"], entry["flags"]) == ("valid", ["doc_misfiled"])
    assert all(e["table"] != "doc" for e in _status(valid_run)["tables"])


def test_a_document_whose_file_carries_a_catalog_prefix_is_not_misfiled(valid_run: Path) -> None:
    docs = valid_run / "docs"
    (docs / f"{DEMO_TABLE}.json").rename(docs / f"spark_catalog.{DEMO_TABLE}.json")
    report = _status(valid_run)
    assert _entry(report)["flags"] == []
    assert report["summary"]["flags"]["doc_misfiled"] == []


# ------------------------------------------------------------------- semantic confirm


def _confirm(run_dir: Path, *extra: str) -> int:
    from .table_semantics_demo import CONFIRMATIONS

    return run("semantic", "confirm", run_dir / "docs", "--confirmations", CONFIRMATIONS, *extra)


def _rendered(run_dir: Path) -> None:
    page = run_dir / "pages" / f"{DEMO_TABLE}.md"
    page.parent.mkdir(exist_ok=True)
    page.write_text("# page\n", encoding="utf-8")
    os.utime(run_dir / "docs" / f"{DEMO_TABLE}.json", (500_000, 500_000))
    assert _entry(_status(run_dir))["stage"] == "rendered"
    os.utime(page, (1_000_000, 1_000_000))


def test_confirming_a_rendered_table_keeps_it_fixed_and_asks_for_a_render(
    valid_run: Path, capsys
) -> None:
    """The owner's answers are not a revision for a fixer: the review's acceptance carries."""
    _keyed_review(valid_run)
    _rendered(valid_run)
    assert _confirm(valid_run) == 0
    digest = document_digest(_doc(valid_run))
    entry = _entry(_status(valid_run))
    assert (entry["stage"], entry["flags"]) == ("fixed", ["render_stale"])
    assert entry["review"]["fixed_doc_digest"] == digest
    assert DEMO_TABLE not in _batches(valid_run, "fix")
    assert _batches(valid_run, "render") == [DEMO_TABLE]
    assert f"fixed_doc_digest {digest}" in capsys.readouterr().out


def test_confirming_after_a_fix_record_moves_the_record(valid_run: Path) -> None:
    _keyed_review(valid_run, high=1)
    _revise(valid_run)
    assert _fixed(valid_run) == 0
    assert _confirm(valid_run) == 0
    entry = _entry(_status(valid_run))
    assert (entry["stage"], entry["flags"]) == ("fixed", [])
    assert entry["review"]["fixed_doc_digest"] == document_digest(_doc(valid_run))


def test_confirming_a_table_the_review_did_not_accept_leaves_the_review_alone(
    valid_run: Path,
) -> None:
    _keyed_review(valid_run, high=1)
    before = _review_bytes(valid_run)
    assert _confirm(valid_run) == 0
    assert _review_bytes(valid_run) == before
    entry = _entry(_status(valid_run))
    assert (entry["stage"], entry["flags"]) == ("reviewed", ["fix_unconfirmed"])


def test_confirming_into_out_leaves_the_review_alone(valid_run: Path) -> None:
    _keyed_review(valid_run)
    before = _review_bytes(valid_run)
    assert _confirm(valid_run, "--out", valid_run.parent / "confirmed") == 0
    assert _review_bytes(valid_run) == before
    assert _entry(_status(valid_run))["stage"] == "fixed"


def test_confirm_reads_the_reviews_from_a_moved_directory(valid_run: Path) -> None:
    _keyed_review(valid_run)
    moved = valid_run.parent / "elsewhere"
    (valid_run / "reviews").rename(moved)
    assert _confirm(valid_run, "--reviews", moved) == 0
    entry = _entry(_status(valid_run, "--reviews", moved))
    assert (entry["stage"], entry["flags"]) == ("fixed", [])
