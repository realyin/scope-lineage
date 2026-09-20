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

``--cache-from`` (Q7) makes the same claim across two corpora: a task another corpus
already derived is borrowed rather than recomputed, and the run still has to come out
byte for byte the way a full run over *this* corpus does. It is proved the same way.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scope_lineage.cli import main
from scope_lineage.corpus_cache import (
    CACHE_DIR_NAME,
    CACHE_DOC_FORMAT,
    INDEX_FILE_NAME,
    PAYLOAD_VERSION,
)
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
    # `describe` has no corpus-level merge: an unchanged task is skipped whole, and what
    # it caches are the documents it wrote, for another corpus to borrow (Q7).
    assert _fact_files(out) == 3

    for name in ("lineage.json", "diagnostics.json"):
        (corpus / "task_b" / name).unlink()

    assert _run(command, corpus, out, "--incremental") == 0
    assert "reused=2, recomputed=0, removed=1" in capsys.readouterr().out

    index = json.loads((out / INDEX_FILE_NAME).read_text(encoding="utf-8"))
    assert sorted(index["inputs"]) == ["task_a", "task_c"]
    assert _fact_files(out) == 2


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


@pytest.mark.parametrize("field", ("command", "doc_format", "payload_version"))
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


@pytest.mark.parametrize(
    "field", ("command", "doc_format", "payload_version", "options_sha256", "inputs")
)
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
    assert index["payload_version"] == PAYLOAD_VERSION
    assert sorted(index["inputs"]) == ["task_a", "task_b", "task_c"]
    entry = index["inputs"]["task_a"]
    assert len(entry["lineage_sha256"]) == 64
    assert len(entry["diagnostics_sha256"]) == 64
    assert len(index["options_sha256"]) == 64
    assert index["written"]


# ------------------------------------------------------- the trimmed payload


def _fact_payloads(out: Path) -> list[dict]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((out / CACHE_DIR_NAME).glob("*.json"))
    ]


@pytest.mark.parametrize("command", ("glossary", "tables", "ontology"))
def test_a_fact_file_declares_the_payload_it_holds(
    tmp_path: Path, capsys, command: str
) -> None:
    corpus = _corpus(tmp_path / "corpus")
    out = tmp_path / "out"

    assert _run(command, corpus, out, "--incremental") == 0
    capsys.readouterr()

    index = json.loads((out / INDEX_FILE_NAME).read_text(encoding="utf-8"))
    payloads = _fact_payloads(out)
    assert payloads
    for payload in payloads:
        assert payload["doc_format"] == CACHE_DOC_FORMAT == "corpus-cache/3"
        assert payload["payload_version"] == PAYLOAD_VERSION
        assert payload["command"] == command
        # Q7: a fact file carries what it was derived from, so another corpus can judge
        # it on its own -- the index beside it is not travelling with it.
        assert payload["options_sha256"] == index["options_sha256"]
        assert payload["inputs"] in index["inputs"].values()


@pytest.mark.parametrize(
    ("command", "dropped"),
    (
        ("glossary", ("stages", "confidence", "inputs", "task", "output_shape")),
        ("tables", ("stages", "confidence", "rules")),
        ("ontology", ("stages", "confidence")),
    ),
)
def test_a_fact_file_holds_only_the_fields_the_merge_reads(
    tmp_path: Path, capsys, command: str, dropped: tuple[str, ...]
) -> None:
    """P2. The payload used to be the whole semantic profile -- most of it keys no merge
    ever looks at. What is *kept* is guarded by the projection tests; what is dropped is
    the point of the exercise, so it is named here."""
    corpus = _corpus(tmp_path / "corpus")
    out = tmp_path / "out"

    assert _run(command, corpus, out, "--incremental") == 0
    capsys.readouterr()

    for payload in _fact_payloads(out):
        for profile in payload["facts"].values():
            assert profile, "a projected profile is not an empty one"
            for key in dropped:
                assert key not in profile, f"{command} still caches {key}"


def test_the_trimmed_payload_is_a_fraction_of_the_whole_profile(
    tmp_path: Path, capsys
) -> None:
    """The size claim, measured rather than asserted from a comment: the cards' payload
    is well under half of the profile it was cut from."""
    from scope_lineage.render.semantic_profile import build_semantic_profile

    corpus = _corpus(tmp_path / "corpus")
    out = tmp_path / "out"
    assert _run("tables", corpus, out, "--incremental") == 0
    capsys.readouterr()

    cached = sum(
        len(json.dumps(payload["facts"], ensure_ascii=False).encode("utf-8"))
        for payload in _fact_payloads(out)
    )
    whole = 0
    for lineage in sorted(corpus.rglob("lineage.json")):
        document = json.loads(lineage.read_text(encoding="utf-8"))
        diagnostics = json.loads(
            (lineage.parent / "diagnostics.json").read_text(encoding="utf-8")
        )
        profile = build_semantic_profile(document, diagnostics)
        whole += len(json.dumps(profile, ensure_ascii=False).encode("utf-8"))

    assert cached < whole * 0.4


# ------------------------------------------ borrowing another corpus's cache (Q7)


def _copy_corpus(corpus: Path, destination: Path) -> Path:
    """The same tasks under another root: byte for byte the corpus they were copied from,
    which is the case `--cache-from` exists for."""
    shutil.copytree(corpus, destination)
    return destination


@pytest.mark.parametrize("command", CORPUS_COMMANDS)
def test_a_second_corpus_borrows_the_tasks_it_shares_with_the_first(
    tmp_path: Path, capsys, command: str
) -> None:
    """The Q7 claim, proved the way the incremental one is: corpus B is corpus A with one
    task changed, and a run that borrows A's cache publishes what a full run over B does.

    `task_c` is in both corpora under one name with different contents -- the case a
    name-keyed cache would get wrong -- and it is the task that is recomputed.
    """
    corpus_a = _corpus(tmp_path / "corpus-a")
    out_a = tmp_path / "out-a"
    assert _run(command, corpus_a, out_a, "--incremental") == 0
    capsys.readouterr()

    corpus_b = _copy_corpus(corpus_a, tmp_path / "corpus-b")
    _change_one_task(corpus_b)
    out_b = tmp_path / "out-b"
    assert _run(command, corpus_b, out_b, "--incremental", "--cache-from", str(out_a)) == 0
    assert "reused=2 (borrowed=2), recomputed=1, removed=0" in capsys.readouterr().out

    full_out = tmp_path / "full"
    assert _run(command, corpus_b, full_out) == 0
    assert _published(out_b) == _published(full_out)


def test_an_unchanged_copy_of_a_corpus_borrows_every_task(tmp_path: Path, capsys) -> None:
    """The corpus path is not in the options digest: the same task derives the same facts
    wherever it was parsed. `--cache-from` also takes the `.cache` directory itself."""
    corpus_a = _corpus(tmp_path / "corpus-a")
    out_a = tmp_path / "out-a"
    assert _run("glossary", corpus_a, out_a, "--incremental") == 0
    capsys.readouterr()

    corpus_b = _copy_corpus(corpus_a, tmp_path / "corpus-b")
    out_b = tmp_path / "out-b"
    cache_a = out_a / CACHE_DIR_NAME
    assert _run("glossary", corpus_b, out_b, "--incremental", "--cache-from", str(cache_a)) == 0
    assert "reused=3 (borrowed=3), recomputed=0, removed=0" in capsys.readouterr().out

    full_out = tmp_path / "full"
    assert _run("glossary", corpus_b, full_out) == 0
    assert _published(out_b) == _published(full_out)


def test_a_borrowed_fact_becomes_this_corpus_s_own(tmp_path: Path, capsys) -> None:
    """The borrowed file is copied in, so the corpus it was borrowed from can go away."""
    corpus_a = _corpus(tmp_path / "corpus-a")
    out_a = tmp_path / "out-a"
    assert _run("tables", corpus_a, out_a, "--incremental") == 0
    corpus_b = _copy_corpus(corpus_a, tmp_path / "corpus-b")
    out_b = tmp_path / "out-b"
    assert _run("tables", corpus_b, out_b, "--incremental", "--cache-from", str(out_a)) == 0
    capsys.readouterr()
    assert _fact_files(out_b) == 3

    shutil.rmtree(out_a)
    assert _run("tables", corpus_b, out_b, "--incremental") == 0

    captured = capsys.readouterr().out
    assert "reused=3, recomputed=0, removed=0" in captured
    assert "borrowed" not in captured


def test_cache_from_implies_incremental(tmp_path: Path, capsys) -> None:
    """A run that names a cache to borrow from has already asked for one -- and it writes
    its own index and cache, or the next run over this corpus would borrow all over."""
    corpus_a = _corpus(tmp_path / "corpus-a")
    out_a = tmp_path / "out-a"
    assert _run("ontology", corpus_a, out_a, "--incremental") == 0
    corpus_b = _copy_corpus(corpus_a, tmp_path / "corpus-b")
    out_b = tmp_path / "out-b"
    capsys.readouterr()

    assert _run("ontology", corpus_b, out_b, "--cache-from", str(out_a)) == 0

    assert "reused=3 (borrowed=3), recomputed=0, removed=0" in capsys.readouterr().out
    assert (out_b / INDEX_FILE_NAME).is_file()
    assert _fact_files(out_b) == 3


def test_a_run_under_other_options_borrows_nothing(tmp_path: Path, capsys) -> None:
    """The options digest guards a borrowed file exactly as it guards the own index: the
    file says which options it was derived under, and this run's differ."""
    corpus_a = _corpus(tmp_path / "corpus-a")
    out_a = tmp_path / "out-a"
    assert _run("glossary", corpus_a, out_a, "--incremental") == 0
    overrides = tmp_path / "glossary.overrides.json"
    overrides.write_text(
        json.dumps({"terms": {"pay_status": {"text": "支付状态"}}}), encoding="utf-8"
    )
    corpus_b = _copy_corpus(corpus_a, tmp_path / "corpus-b")
    capsys.readouterr()

    assert (
        _run(
            "glossary",
            corpus_b,
            tmp_path / "out-b",
            "--incremental",
            "--cache-from",
            str(out_a),
            "--overrides",
            str(overrides),
        )
        == 0
    )

    assert "reused=0 (borrowed=0), recomputed=3, removed=0" in capsys.readouterr().out


def test_a_task_of_the_same_name_and_other_contents_is_described_again(
    tmp_path: Path, capsys
) -> None:
    """Fact files are keyed by task name, and two corpora may hold different tasks under
    one name. What makes a borrow safe is the fingerprint inside the file, not the name
    of the file -- so the document this corpus publishes is its own task's."""
    corpus_a = _corpus(tmp_path / "corpus-a")
    out_a = tmp_path / "out-a"
    assert _run("describe", corpus_a, out_a, "--incremental") == 0
    corpus_b = _copy_corpus(corpus_a, tmp_path / "corpus-b")
    _write_task(corpus_b, "task_a", CHANGED_TASK_C_SQL)
    out_b = tmp_path / "out-b"
    capsys.readouterr()

    assert _run("describe", corpus_b, out_b, "--cache-from", str(out_a)) == 0

    assert "reused=2 (borrowed=2), recomputed=1, removed=0" in capsys.readouterr().out
    described = (out_b / "task_a" / "semantic.json").read_bytes()
    assert described != (out_a / "task_a" / "semantic.json").read_bytes()
    full_out = tmp_path / "full"
    assert _run("describe", corpus_b, full_out) == 0
    assert _published(out_b) == _published(full_out)


def test_this_run_s_own_output_directory_is_not_a_second_cache(
    tmp_path: Path, capsys
) -> None:
    """A run's own cache is read through its index, once. Naming it as `--cache-from`
    does not add a weaker second way in -- and `borrowed` keeps meaning "from elsewhere"."""
    corpus = _corpus(tmp_path / "corpus")
    out = tmp_path / "out"
    assert _run("glossary", corpus, out, "--incremental") == 0
    capsys.readouterr()

    assert _run("glossary", corpus, out, "--incremental", "--cache-from", str(out)) == 0

    captured = capsys.readouterr().out
    assert "reused=3, recomputed=0, removed=0" in captured
    assert "borrowed" not in captured


@pytest.mark.parametrize("command", CORPUS_COMMANDS)
def test_no_cache_beats_cache_from(tmp_path: Path, capsys, command: str) -> None:
    corpus_a = _corpus(tmp_path / "corpus-a")
    out_a = tmp_path / "out-a"
    assert _run(command, corpus_a, out_a, "--incremental") == 0
    corpus_b = _copy_corpus(corpus_a, tmp_path / "corpus-b")
    out_b = tmp_path / "out-b"
    capsys.readouterr()

    assert _run(command, corpus_b, out_b, "--no-cache", "--cache-from", str(out_a)) == 0

    assert not (out_b / INDEX_FILE_NAME).exists()
    assert not (out_b / CACHE_DIR_NAME).exists()
    assert "reused=" not in capsys.readouterr().out


def test_a_borrowed_file_is_judged_on_its_own_header(tmp_path: Path, capsys) -> None:
    """The borrowed corpus's index is never read -- so every condition has to be in the
    file, and a file that fails one of them is not borrowed."""
    corpus_a = _corpus(tmp_path / "corpus-a")
    out_a = tmp_path / "out-a"
    assert _run("glossary", corpus_a, out_a, "--incremental") == 0
    for payload_path in (out_a / CACHE_DIR_NAME).glob("*.json"):
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        payload["doc_format"] = "something-else"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
    corpus_b = _copy_corpus(corpus_a, tmp_path / "corpus-b")
    capsys.readouterr()

    assert _run("glossary", corpus_b, tmp_path / "out-b", "--cache-from", str(out_a)) == 0

    assert "reused=0 (borrowed=0), recomputed=3, removed=0" in capsys.readouterr().out


def test_describe_re_describes_a_task_whose_borrowed_documents_are_unusable(
    tmp_path: Path, capsys
) -> None:
    """A cache file is a cache file: one that does not hold the documents this run
    publishes costs a re-describe, never an exception."""
    corpus_a = _corpus(tmp_path / "corpus-a")
    out_a = tmp_path / "out-a"
    assert _run("describe", corpus_a, out_a, "--incremental") == 0
    for payload_path in (out_a / CACHE_DIR_NAME).glob("*.json"):
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        payload["facts"] = {"documents": {"semantic.json": None}}
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
    corpus_b = _copy_corpus(corpus_a, tmp_path / "corpus-b")
    out_b = tmp_path / "out-b"
    capsys.readouterr()

    assert _run("describe", corpus_b, out_b, "--cache-from", str(out_a)) == 0

    assert "reused=0 (borrowed=0), recomputed=3, removed=0" in capsys.readouterr().out
    full_out = tmp_path / "full"
    assert _run("describe", corpus_b, full_out) == 0
    assert _published(out_b) == _published(full_out)
