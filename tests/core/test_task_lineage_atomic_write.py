"""A task artifact pair is published as one directory generation."""

from __future__ import annotations

from pathlib import Path

import pytest

import scope_lineage.contract.task_lineage as task_lineage_contract
from scope_lineage import parse_task_lineage, write_task_lineage


def _result(source_table: str):
    return parse_task_lineage(
        f"INSERT INTO mart.t SELECT id FROM {source_table}",
        task_name="atomic_task",
        schema={source_table: ["id"]},
    )


def _pair_bytes(output: Path) -> dict[str, bytes]:
    return {
        name: (output / name).read_bytes()
        for name in ("lineage.json", "diagnostics.json")
    }


def _generation_remnants(output: Path) -> list[Path]:
    return sorted(output.parent.glob(f".{output.name}.*-*"))


@pytest.mark.parametrize("failed_name", ["lineage.json", "diagnostics.json"])
def test_a_staging_write_failure_keeps_the_previous_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_name: str,
) -> None:
    output = write_task_lineage(_result("ods.old"), tmp_path / "artifact")
    previous = _pair_bytes(output)
    real_write = task_lineage_contract._write_generation_file

    def fail_one_file(path: Path, content: str) -> None:
        if path.name == failed_name:
            raise OSError(f"injected {failed_name} write failure")
        real_write(path, content)

    monkeypatch.setattr(task_lineage_contract, "_write_generation_file", fail_one_file)

    with pytest.raises(OSError, match="injected"):
        write_task_lineage(_result("ods.new"), output)

    assert _pair_bytes(output) == previous
    assert _generation_remnants(output) == []


@pytest.mark.parametrize("failure_point", ["old_to_previous", "next_to_official"])
def test_a_directory_switch_failure_rolls_back_to_the_previous_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    output = write_task_lineage(_result("ods.old"), tmp_path / "artifact")
    previous = _pair_bytes(output)
    real_replace = task_lineage_contract._replace_path

    def fail_one_replace(source: Path, target: Path) -> None:
        old_to_previous = source == output and ".previous-" in target.name
        next_to_official = ".next-" in source.name and target == output
        if (failure_point == "old_to_previous" and old_to_previous) or (
            failure_point == "next_to_official" and next_to_official
        ):
            raise OSError(f"injected {failure_point} failure")
        real_replace(source, target)

    monkeypatch.setattr(task_lineage_contract, "_replace_path", fail_one_replace)

    with pytest.raises(OSError, match="injected"):
        write_task_lineage(_result("ods.new"), output)

    assert _pair_bytes(output) == previous
    assert _generation_remnants(output) == []


def test_serialization_failure_does_not_touch_the_previous_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = write_task_lineage(_result("ods.old"), tmp_path / "artifact")
    previous = _pair_bytes(output)

    def fail_serialization(*_args, **_kwargs):
        raise TypeError("injected serialization failure")

    monkeypatch.setattr(
        task_lineage_contract,
        "_serialize_task_documents",
        fail_serialization,
    )

    with pytest.raises(TypeError, match="injected"):
        write_task_lineage(_result("ods.new"), output)

    assert _pair_bytes(output) == previous
    assert _generation_remnants(output) == []


def test_validation_failure_does_not_touch_the_previous_pair(tmp_path: Path) -> None:
    output = write_task_lineage(_result("ods.old"), tmp_path / "artifact")
    previous = _pair_bytes(output)
    invalid = _result("ods.new")
    nested = invalid.statement_lineage["stmt:001"]
    nested["scope_graph"]["edges"][0]["from"] = "scope:missing"

    with pytest.raises(ValueError, match="Cross-reference validation failed"):
        write_task_lineage(invalid, output)

    assert _pair_bytes(output) == previous
    assert _generation_remnants(output) == []


def test_success_replaces_the_whole_owned_generation(tmp_path: Path) -> None:
    output = write_task_lineage(_result("ods.old"), tmp_path / "artifact")
    previous = _pair_bytes(output)
    (output / "mapping.md").write_text("stale mapping", encoding="utf-8")
    (output / "warnings.md").write_text("stale warnings", encoding="utf-8")

    write_task_lineage(_result("ods.new"), output)

    assert set(path.name for path in output.iterdir()) == {
        "lineage.json",
        "diagnostics.json",
    }
    assert _pair_bytes(output) != previous
    assert _generation_remnants(output) == []


def test_unknown_files_prevent_destructive_directory_replacement(tmp_path: Path) -> None:
    output = write_task_lineage(_result("ods.old"), tmp_path / "artifact")
    previous = _pair_bytes(output)
    (output / "notes.txt").write_text("keep me", encoding="utf-8")

    with pytest.raises(ValueError, match="not owned by the task writer"):
        write_task_lineage(_result("ods.new"), output)

    assert _pair_bytes(output) == previous
    assert (output / "notes.txt").read_text(encoding="utf-8") == "keep me"


def test_a_symlink_output_cannot_redirect_directory_replacement(tmp_path: Path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    sentinel = external / "keep.txt"
    sentinel.write_text("keep me", encoding="utf-8")
    output_link = tmp_path / "artifact"
    output_link.symlink_to(external, target_is_directory=True)

    with pytest.raises(ValueError, match="symbolic link"):
        write_task_lineage(_result("ods.new"), output_link)

    assert output_link.is_symlink()
    assert sentinel.read_text(encoding="utf-8") == "keep me"


def test_an_interrupted_switch_is_recovered_before_new_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = write_task_lineage(_result("ods.old"), tmp_path / "artifact")
    previous = _pair_bytes(output)
    interrupted_previous = output.parent / f".{output.name}.previous-{'a' * 32}"
    interrupted_next = output.parent / f".{output.name}.next-{'b' * 32}"
    output.replace(interrupted_previous)
    interrupted_next.mkdir()
    (interrupted_next / "lineage.json").write_text("partial", encoding="utf-8")

    def fail_serialization(*_args, **_kwargs):
        raise TypeError("stop after recovery")

    monkeypatch.setattr(
        task_lineage_contract,
        "_serialize_task_documents",
        fail_serialization,
    )

    with pytest.raises(TypeError, match="after recovery"):
        write_task_lineage(_result("ods.new"), output)

    assert _pair_bytes(output) == previous
    assert _generation_remnants(output) == []
