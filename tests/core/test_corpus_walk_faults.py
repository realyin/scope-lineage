"""One unreadable ``lineage.json`` must not end a corpus run.

``describe``, ``glossary``, ``tables`` and ``render`` share one input walk
(``cli._discover_lineage_documents`` / ``cli._load_contract_documents``). A corpus is a
directory somebody else's job wrote: a truncated file, a half-written file, a file that
holds a JSON array instead of an object. Before this test the walk called
``json.loads`` unguarded, so a single such file raised out of ``main`` and the other
tasks in the tree were never described -- the one input the reader cannot fix is also
the one that hides every input they could.

The two modes answer differently on purpose, matching what ``--lineage <missing path>``
already does: a directory skips and counts, a file the user named by name is an error
with exit code 2.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scope_lineage.cli import main
from scope_lineage.scope.scope_builder import parse_scope_lineage

from .statement_document import write_statement_documents


SIMPLE_SQL = "INSERT INTO mart.t SELECT id FROM ods.users"
SIMPLE_SCHEMA = {"ods.users": ["id"]}


def _write_artifacts(out_dir: Path) -> Path:
    write_statement_documents(
        parse_scope_lineage(SIMPLE_SQL, out_dir.name, schema=SIMPLE_SCHEMA), out_dir
    )
    return out_dir


def _corpus_with_faults(tmp_path: Path) -> Path:
    corpus = tmp_path / "corpus"
    _write_artifacts(corpus / "task_ok")
    truncated = corpus / "task_truncated"
    truncated.mkdir(parents=True)
    (truncated / "lineage.json").write_text('{"schema_version": "2.0"', encoding="utf-8")
    not_an_object = corpus / "task_array"
    not_an_object.mkdir(parents=True)
    (not_an_object / "lineage.json").write_text("[1, 2, 3]", encoding="utf-8")
    return corpus


@pytest.mark.parametrize(
    ("argv", "summary"),
    [
        (["describe"], "Described 1 task(s)"),
        (["render"], "Rendered 1 mapping document(s)"),
    ],
)
def test_corpus_skips_unreadable_documents_and_counts_them(
    tmp_path: Path, capsys, argv: list[str], summary: str
) -> None:
    corpus = _corpus_with_faults(tmp_path)

    assert main([*argv, "--lineage", str(corpus)]) == 0

    captured = capsys.readouterr()
    assert summary in captured.out
    assert "skipped_unreadable=2" in captured.out
    errors = [line for line in captured.err.splitlines() if line.strip()]
    assert len(errors) == 2
    assert all("not a readable JSON document" in line for line in errors)
    assert str(corpus / "task_truncated" / "lineage.json") in captured.err
    assert str(corpus / "task_array" / "lineage.json") in captured.err
    assert (corpus / "task_ok" / "semantic.json").exists() or (
        corpus / "task_ok" / "mapping.md"
    ).exists()


def test_corpus_walk_skips_unreadable_documents_for_glossary(
    tmp_path: Path, capsys
) -> None:
    corpus = _corpus_with_faults(tmp_path)

    assert main(["glossary", "--lineage", str(corpus), "--out", str(tmp_path / "d")]) == 0

    captured = capsys.readouterr()
    assert "skipped_unreadable=2" in captured.out
    assert captured.err.count("not a readable JSON document") == 2


def test_corpus_walk_skips_unreadable_documents_for_tables(
    tmp_path: Path, capsys
) -> None:
    corpus = _corpus_with_faults(tmp_path)

    assert main(["tables", "--lineage", str(corpus), "--out", str(tmp_path / "t")]) == 0

    captured = capsys.readouterr()
    assert "skipped_unreadable=2" in captured.out
    assert captured.err.count("not a readable JSON document") == 2


@pytest.mark.parametrize("command", ["describe", "render", "glossary", "tables"])
def test_named_unreadable_file_is_an_error(
    tmp_path: Path, capsys, command: str
) -> None:
    """The one file the user named: one line, exit 2, like a path that does not exist."""
    broken = tmp_path / "task" / "lineage.json"
    broken.parent.mkdir(parents=True)
    broken.write_text("{not json at all", encoding="utf-8")
    argv = [command, "--lineage", str(broken)]
    if command in ("glossary", "tables"):
        argv += ["--out", str(tmp_path / "out")]

    assert main(argv) == 2

    captured = capsys.readouterr()
    errors = [line for line in captured.err.splitlines() if line.strip()]
    assert len(errors) == 1
    assert str(broken) in errors[0]
    assert "not a readable JSON document" in errors[0]


def test_unreadable_sibling_diagnostics_does_not_end_the_run(
    tmp_path: Path, capsys
) -> None:
    """``diagnostics.json`` is read by the same walk and gets the same treatment."""
    task = _write_artifacts(tmp_path / "corpus" / "task_ok")
    (task / "diagnostics.json").write_text("{oops", encoding="utf-8")

    assert main(["describe", "--lineage", str(tmp_path / "corpus")]) == 0

    captured = capsys.readouterr()
    assert "Described 1 task(s)" in captured.out
    assert "skipped_unreadable=1" in captured.out
    assert str(task / "diagnostics.json") in captured.err
