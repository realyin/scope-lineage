"""``semantic render`` and ``catalog digest`` warn about documents not fit to publish.

Both commands render whatever document meets its schema; a document written against an
old packet (``packet_stale``) or failing a cross check (``invalid``) is still rendered,
but its table is named on stderr, so a run that mixes old and new material does not pass
unnoticed. The output and the exit code stay what they were. The packets are read from
``--packets``, or from ``packets/`` beside the documents (the run layout); ``semantic
render`` without packets reads the same flags from its ``--validation`` report.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from .table_semantics_demo import DEMO_TABLE, demo_packets, example, run, write_json


@pytest.fixture(scope="module")
def packets(tmp_path_factory) -> Path:
    return demo_packets(tmp_path_factory.mktemp("unfit"))


def _run_layout(tmp_path: Path, packets: Path, document: dict) -> Path:
    """``<run>/packets`` and ``<run>/docs`` holding ``document``; the docs directory."""
    shutil.copytree(packets, tmp_path / "run" / "packets")
    docs = tmp_path / "run" / "docs"
    write_json(docs / f"{DEMO_TABLE}.json", document)
    return docs


def _stale(packets: Path) -> dict:
    document = example(packets)
    document["packet_digest"] = "0000000000000000"
    return document


def _invalid(packets: Path) -> dict:
    document = example(packets)
    del document["columns"][1]
    return document


COMMANDS = {
    "render": lambda docs, out, *extra: run("semantic", "render", docs, "--out", out, *extra),
    "digest": lambda docs, out, *extra: run("catalog", "digest", docs, "--out", out, *extra),
}


@pytest.mark.parametrize("command", sorted(COMMANDS))
@pytest.mark.parametrize(("make", "flag"), [(_stale, "packet_stale"), (_invalid, "invalid")])
def test_a_stale_or_invalid_document_is_named_and_still_written(
    tmp_path: Path, packets: Path, capsys, command, make, flag
) -> None:
    docs = _run_layout(tmp_path, packets, make(packets))
    capsys.readouterr()
    assert COMMANDS[command](docs, tmp_path / "out") == 0
    err = capsys.readouterr().err
    (line,) = [line for line in err.splitlines() if line.startswith("warning:")]
    assert f"warning: {flag}" in line and DEMO_TABLE in line
    written = sorted(path.name for path in (tmp_path / "out").iterdir())
    assert written == (
        [f"{DEMO_TABLE}.md", "index.md"] if command == "render" else ["digest.json", "digest.md"]
    )


@pytest.mark.parametrize("command", sorted(COMMANDS))
def test_the_output_is_the_same_with_or_without_the_warning(
    tmp_path: Path, packets: Path, command
) -> None:
    docs = _run_layout(tmp_path, packets, _stale(packets))
    alone = tmp_path / "alone"
    write_json(alone / f"{DEMO_TABLE}.json", _stale(packets))
    assert COMMANDS[command](docs, tmp_path / "a") == 0
    assert COMMANDS[command](alone, tmp_path / "b") == 0
    for path in (tmp_path / "a").iterdir():
        assert path.read_bytes() == (tmp_path / "b" / path.name).read_bytes()


@pytest.mark.parametrize("command", sorted(COMMANDS))
def test_explicit_packets_are_read_from_anywhere(
    tmp_path: Path, packets: Path, capsys, command
) -> None:
    docs = tmp_path / "docs"
    write_json(docs / f"{DEMO_TABLE}.json", _stale(packets))
    capsys.readouterr()
    assert COMMANDS[command](docs, tmp_path / "out", "--packets", packets) == 0
    assert "warning: packet_stale" in capsys.readouterr().err


@pytest.mark.parametrize("command", sorted(COMMANDS))
def test_a_clean_document_draws_no_warning(tmp_path: Path, packets: Path, capsys, command) -> None:
    docs = _run_layout(tmp_path, packets, example(packets))
    capsys.readouterr()
    assert COMMANDS[command](docs, tmp_path / "out") == 0
    assert "warning:" not in capsys.readouterr().err


@pytest.mark.parametrize("command", sorted(COMMANDS))
def test_a_document_without_a_packet_is_named(
    tmp_path: Path, packets: Path, capsys, command
) -> None:
    document = example(packets)
    document["table"] = "demo_dwd.dwd_no_such_table"
    docs = _run_layout(tmp_path, packets, document)
    capsys.readouterr()
    assert COMMANDS[command](docs, tmp_path / "out") == 0
    assert "warning: no_packet" in capsys.readouterr().err


@pytest.mark.parametrize("command", sorted(COMMANDS))
def test_without_packets_the_reader_is_told_nothing_was_checked(
    tmp_path: Path, packets: Path, capsys, command
) -> None:
    docs = tmp_path / "docs"
    write_json(docs / f"{DEMO_TABLE}.json", _stale(packets))
    capsys.readouterr()
    assert COMMANDS[command](docs, tmp_path / "out") == 0
    err = capsys.readouterr().err
    assert "not checked against packets" in err
    assert "--packets" in err


def test_render_without_packets_reads_the_flags_from_its_report(
    tmp_path: Path, packets: Path, capsys
) -> None:
    docs = tmp_path / "docs"
    write_json(docs / f"{DEMO_TABLE}.json", _stale(packets))
    capsys.readouterr()
    run("semantic", "validate", docs, "--packets", packets, "--json")
    report = write_json(tmp_path / "report.json", json.loads(capsys.readouterr().out))
    assert run("semantic", "render", docs, "--out", tmp_path / "out", "--validation", report) == 0
    err = capsys.readouterr().err
    assert "warning: packet_stale" in err and DEMO_TABLE in err
    assert "not checked against packets" not in err


def test_a_packets_flag_that_is_no_directory_is_a_usage_error(
    tmp_path: Path, packets: Path
) -> None:
    docs = tmp_path / "docs"
    write_json(docs / f"{DEMO_TABLE}.json", example(packets))
    for command in COMMANDS.values():
        assert command(docs, tmp_path / "out", "--packets", tmp_path / "nope") == 2
