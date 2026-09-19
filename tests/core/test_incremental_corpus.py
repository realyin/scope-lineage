"""The incremental mode of the four corpus commands (A5).

``glossary``/``tables``/``ontology``/``describe`` re-derive every task on every run. The
expensive half of that work is per document and depends on nothing but that document, so
it can be cached under a fingerprint of the files it was derived from -- while the
corpus-level merge keeps running over every task, which is what makes an incremental run
byte-identical to a full one.

That last sentence is the only claim worth testing, and it is tested the only way it can
be proved: run the command full, change one task, run it incrementally, and compare the
bytes against a fresh full run over the same changed corpus. The counters beside it say
*why* the run was faster -- a run that reused nothing would pass a bytes comparison too.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.cli import main
from scope_lineage.corpus_cache import CACHE_DIR_NAME, INDEX_FILE_NAME
from scope_lineage.scope.scope_builder import parse_scope_lineage

from .statement_document import write_statement_documents


SCHEMA = {
    "ods.app_order": ["order_id", "pay_status", "channel_code", "dt"],
    "ods.app_user": ["user_id", "user_status", "dt"],
    "mart.order_daily": ["order_id", "pay_status", "dt"],
}

TASK_SQL = {
    "task_a": (
        "INSERT OVERWRITE TABLE mart.order_daily PARTITION (dt = '20250101') "
        "SELECT order_id, pay_status FROM ods.app_order WHERE pay_status = 'PAID'"
    ),
    "task_b": (
        "INSERT OVERWRITE TABLE mart.user_daily "
        "SELECT user_id, user_status FROM ods.app_user WHERE user_status = 'ACTIVE'"
    ),
    "task_c": (
        "INSERT OVERWRITE TABLE mart.channel_rollup "
        "SELECT channel_code, count(1) AS order_count FROM ods.app_order "
        "WHERE dt = '20250101' GROUP BY channel_code"
    ),
}

CHANGED_TASK_C_SQL = (
    "INSERT OVERWRITE TABLE mart.channel_rollup "
    "SELECT channel_code, count(1) AS order_count FROM ods.app_order "
    "WHERE dt = '20250102' AND pay_status = 'REFUNDED' GROUP BY channel_code"
)

CORPUS_COMMANDS = ("glossary", "tables", "ontology", "describe")


def _write_task(root: Path, name: str, sql: str) -> Path:
    task_dir = root / name
    write_statement_documents(parse_scope_lineage(sql, name, schema=SCHEMA), task_dir)
    return task_dir


def _corpus(root: Path) -> Path:
    for name, sql in TASK_SQL.items():
        _write_task(root, name, sql)
    return root


def _change_one_task(corpus: Path) -> None:
    _write_task(corpus, "task_c", CHANGED_TASK_C_SQL)


def _run(command: str, corpus: Path, out: Path, *extra: str) -> int:
    return main([command, "--lineage", str(corpus), "--out", str(out), *extra])


def _fact_files(out: Path) -> int:
    return len(list((out / CACHE_DIR_NAME).glob("*.json")))


def _published(out: Path) -> dict[str, bytes]:
    """Every byte the command published, without its own index and fact cache."""
    published: dict[str, bytes] = {}
    for path in sorted(out.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(out)
        if relative.parts[0] in (INDEX_FILE_NAME, CACHE_DIR_NAME):
            continue
        published[relative.as_posix()] = path.read_bytes()
    return published


# ------------------------------------------------- the correctness guard


@pytest.mark.parametrize("command", ("glossary", "tables", "ontology"))
def test_an_incremental_run_is_byte_identical_to_a_full_one(
    tmp_path: Path, capsys, command: str
) -> None:
    corpus = _corpus(tmp_path / "corpus")
    incremental_out = tmp_path / "incremental"

    assert _run(command, corpus, incremental_out, "--incremental") == 0
    first = capsys.readouterr().out
    assert "reused=0, recomputed=3, removed=0" in first

    _change_one_task(corpus)
    assert _run(command, corpus, incremental_out, "--incremental") == 0
    assert "reused=2, recomputed=1, removed=0" in capsys.readouterr().out

    full_out = tmp_path / "full"
    assert _run(command, corpus, full_out) == 0

    assert _published(incremental_out) == _published(full_out)


def test_the_flags_the_other_corpus_features_added_still_compose(
    tmp_path: Path, capsys
) -> None:
    """`ontology --export` and `tables --samples` (A6) are options like any other: they
    steer the run, so they belong in the options digest -- and the documents they add
    must come out of an incremental run exactly as a full run writes them."""
    corpus = _corpus(tmp_path / "corpus")
    samples = tmp_path / "samples.csv"
    samples.write_text(
        "table,column,value,count\nods.app_order,pay_status,PAID,9\n", encoding="utf-8"
    )
    runs = (
        ("ontology", ("--export", "linkml")),
        ("tables", ("--samples", str(samples))),
    )

    for command, extra in runs:
        assert _run(command, corpus, tmp_path / f"incremental-{command}", "--incremental", *extra) == 0
    capsys.readouterr()
    _change_one_task(corpus)

    for command, extra in runs:
        incremental_out = tmp_path / f"incremental-{command}"
        assert _run(command, corpus, incremental_out, "--incremental", *extra) == 0
        assert "reused=2, recomputed=1, removed=0" in capsys.readouterr().out

        full_out = tmp_path / f"full-{command}"
        assert _run(command, corpus, full_out, *extra) == 0
        assert _published(incremental_out) == _published(full_out)

    assert (tmp_path / "incremental-ontology" / "ontology.linkml.yaml").is_file()


def test_a_different_samples_file_recomputes_every_task(tmp_path: Path, capsys) -> None:
    corpus = _corpus(tmp_path / "corpus")
    out = tmp_path / "cards"
    samples = tmp_path / "samples.csv"
    samples.write_text("table,column,value\nods.app_order,pay_status,PAID\n", encoding="utf-8")

    assert _run("tables", corpus, out, "--incremental", "--samples", str(samples)) == 0
    capsys.readouterr()

    samples.write_text(
        "table,column,value\nods.app_order,pay_status,REFUNDED\n", encoding="utf-8"
    )
    assert _run("tables", corpus, out, "--incremental", "--samples", str(samples)) == 0

    assert "reused=0, recomputed=3, removed=0" in capsys.readouterr().out


def test_describe_skips_the_tasks_whose_inputs_did_not_change(
    tmp_path: Path, capsys
) -> None:
    corpus = _corpus(tmp_path / "corpus")
    out = tmp_path / "described"

    assert _run("describe", corpus, out, "--incremental") == 0
    assert "reused=0, recomputed=3, removed=0" in capsys.readouterr().out
    first = _published(out)

    _change_one_task(corpus)
    assert _run("describe", corpus, out, "--incremental") == 0
    assert "reused=2, recomputed=1, removed=0" in capsys.readouterr().out

    full_out = tmp_path / "full"
    assert _run("describe", corpus, full_out) == 0
    assert _published(out) == _published(full_out)
    assert first != _published(out)


def test_describe_re_describes_a_task_whose_output_was_deleted(
    tmp_path: Path, capsys
) -> None:
    corpus = _corpus(tmp_path / "corpus")
    out = tmp_path / "described"
    assert _run("describe", corpus, out, "--incremental") == 0
    capsys.readouterr()

    (out / "task_b" / "semantic.md").unlink()

    assert _run("describe", corpus, out, "--incremental") == 0
    assert "reused=2, recomputed=1, removed=0" in capsys.readouterr().out
    assert (out / "task_b" / "semantic.md").is_file()


@pytest.mark.parametrize("command", CORPUS_COMMANDS)
def test_a_removed_task_is_dropped_from_the_index_and_the_cache(
    tmp_path: Path, capsys, command: str
) -> None:
    corpus = _corpus(tmp_path / "corpus")
    out = tmp_path / "out"
    assert _run(command, corpus, out, "--incremental") == 0
    capsys.readouterr()
    # `describe` has no corpus-level merge and so caches no facts: its own outputs are
    # the cache, and an unchanged task is skipped whole.
    expected_facts = 0 if command == "describe" else 3
    assert _fact_files(out) == expected_facts

    for name in ("lineage.json", "diagnostics.json"):
        (corpus / "task_b" / name).unlink()

    assert _run(command, corpus, out, "--incremental") == 0
    assert "reused=2, recomputed=0, removed=1" in capsys.readouterr().out

    index = json.loads((out / INDEX_FILE_NAME).read_text(encoding="utf-8"))
    assert sorted(index["inputs"]) == ["task_a", "task_c"]
    assert _fact_files(out) == max(expected_facts - 1, 0)


# ------------------------------------------------------ invalidation


def test_a_different_overrides_file_recomputes_every_task(tmp_path: Path, capsys) -> None:
    corpus = _corpus(tmp_path / "corpus")
    out = tmp_path / "dict"
    overrides = tmp_path / "glossary.overrides.json"
    overrides.write_text(json.dumps({"terms": {}}), encoding="utf-8")

    assert _run("glossary", corpus, out, "--incremental", "--overrides", str(overrides)) == 0
    capsys.readouterr()

    overrides.write_text(
        json.dumps({"terms": {"pay_status": {"text": "支付状态"}}}), encoding="utf-8"
    )
    assert _run("glossary", corpus, out, "--incremental", "--overrides", str(overrides)) == 0

    assert "reused=0, recomputed=3, removed=0" in capsys.readouterr().out


@pytest.mark.parametrize("field", ("command", "doc_format"))
def test_an_index_written_by_another_command_is_ignored(
    tmp_path: Path, capsys, field: str
) -> None:
    corpus = _corpus(tmp_path / "corpus")
    out = tmp_path / "dict"
    assert _run("glossary", corpus, out, "--incremental") == 0
    capsys.readouterr()

    index_path = out / INDEX_FILE_NAME
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index[field] = "something-else"
    index_path.write_text(json.dumps(index), encoding="utf-8")

    assert _run("glossary", corpus, out, "--incremental") == 0
    assert "reused=0, recomputed=3, removed=0" in capsys.readouterr().out


@pytest.mark.parametrize("field", ("command", "doc_format"))
def test_a_fact_file_written_by_another_command_is_ignored(
    tmp_path: Path, capsys, field: str
) -> None:
    corpus = _corpus(tmp_path / "corpus")
    out = tmp_path / "dict"
    assert _run("glossary", corpus, out, "--incremental") == 0
    capsys.readouterr()

    for path in (out / CACHE_DIR_NAME).glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload[field] = "something-else"
        path.write_text(json.dumps(payload), encoding="utf-8")

    assert _run("glossary", corpus, out, "--incremental") == 0
    assert "reused=0, recomputed=3, removed=0" in capsys.readouterr().out


# ------------------------------------------------------------- flags


def test_the_default_run_writes_no_index_and_no_cache(tmp_path: Path, capsys) -> None:
    corpus = _corpus(tmp_path / "corpus")
    out = tmp_path / "dict"

    assert _run("glossary", corpus, out) == 0

    assert not (out / INDEX_FILE_NAME).exists()
    assert not (out / CACHE_DIR_NAME).exists()
    assert "reused=" not in capsys.readouterr().out


@pytest.mark.parametrize("command", CORPUS_COMMANDS)
def test_no_cache_deletes_the_index_and_the_cache(
    tmp_path: Path, capsys, command: str
) -> None:
    corpus = _corpus(tmp_path / "corpus")
    out = tmp_path / "out"
    assert _run(command, corpus, out, "--incremental") == 0
    assert (out / INDEX_FILE_NAME).is_file()
    published = _published(out)
    capsys.readouterr()

    assert _run(command, corpus, out, "--no-cache") == 0

    assert not (out / INDEX_FILE_NAME).exists()
    assert not (out / CACHE_DIR_NAME).exists()
    assert _published(out) == published
    assert "reused=" not in capsys.readouterr().out


def test_describe_without_out_keeps_the_index_beside_the_artifacts(
    tmp_path: Path, capsys
) -> None:
    corpus = _corpus(tmp_path / "corpus")

    assert main(["describe", "--lineage", str(corpus), "--incremental"]) == 0
    capsys.readouterr()
    assert (corpus / INDEX_FILE_NAME).is_file()

    assert main(["describe", "--lineage", str(corpus), "--incremental"]) == 0

    assert "reused=3, recomputed=0, removed=0" in capsys.readouterr().out


def test_describe_with_a_metadata_patch_describes_every_task(
    tmp_path: Path, capsys
) -> None:
    corpus = _corpus(tmp_path / "corpus")
    out = tmp_path / "described"
    patch = tmp_path / "patch.json"
    patch.write_text(
        json.dumps(
            {
                "doc_format": "metadata-patch/1",
                "columns": {"ods.app_order.pay_status": {"comment": "支付状态（已确认）"}},
            }
        ),
        encoding="utf-8",
    )
    flags = ("--incremental", "--metadata-patch", str(patch))

    assert _run("describe", corpus, out, *flags) == 0
    capsys.readouterr()
    assert _run("describe", corpus, out, *flags) == 0

    # `patch_unmatched` answers a corpus-wide question, so no task may be skipped.
    captured = capsys.readouterr()
    assert "reused=0, recomputed=3, removed=0" in captured.out
    assert "the patch's unmatched report is corpus-wide" in captured.err


@pytest.mark.parametrize("command", CORPUS_COMMANDS)
def test_the_index_records_the_fingerprints_it_matched_on(
    tmp_path: Path, command: str
) -> None:
    corpus = _corpus(tmp_path / "corpus")
    out = tmp_path / "out"

    assert _run(command, corpus, out, "--incremental") == 0

    index = json.loads((out / INDEX_FILE_NAME).read_text(encoding="utf-8"))
    assert index["doc_format"] == "corpus-index/1"
    assert index["command"] == command
    assert sorted(index["inputs"]) == ["task_a", "task_b", "task_c"]
    entry = index["inputs"]["task_a"]
    assert len(entry["lineage_sha256"]) == 64
    assert len(entry["diagnostics_sha256"]) == 64
    assert len(index["options_sha256"]) == 64
    assert index["written"]
