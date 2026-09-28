"""The privacy guard must fail on every supported public surface."""

from __future__ import annotations

import io
import sys
import tarfile
from pathlib import Path

import pytest

from .private_surface_scan import (
    load_private_terms,
    main,
    scan_archives,
    scan_text,
)


def _private_measurement() -> str:
    context = "production corpus"

    quantity = "12" + "34 tasks"
    return f"Across a {context}, {quantity} changed."


def _local_path() -> str:
    return "/" + "Volumes/PrivateDrive/team/input.sql"


def test_private_corpus_measurements_are_rejected() -> None:
    findings = scan_text(_private_measurement(), source="body.md")

    assert {finding.rule for finding in findings} >= {
        "private-corpus-measurement",
        "asset-count",
    }


def _hyphenated_measurement() -> str:
    # The shape a real docstring used to slip past the guard: a hyphenated size and a
    # count whose noun is not one of the asset words.
    size = "4" + "7-field task"
    marks = "1" + "3" + "6 opaque-call marks"
    return f"One real {size} carried {marks}, and none were justified."


def test_hyphenated_sizes_in_corpus_context_are_rejected() -> None:
    findings = scan_text(_hyphenated_measurement(), source="module.py")

    assert "private-corpus-measurement" in {finding.rule for finding in findings}


def test_counts_of_any_noun_in_corpus_context_are_rejected() -> None:
    text = "In production the parser raised " + "2" + "3" + "1 warnings on one job."

    findings = scan_text(text, source="module.py")

    assert "private-corpus-measurement" in {finding.rule for finding in findings}


def test_the_size_of_one_asset_is_rejected_without_a_context_word() -> None:
    text = "The hand-written list missed them: one " + "4" + "7-column job carried many."

    findings = scan_text(text, source="module.py")

    assert "asset-size" in {finding.rule for finding in findings}


def test_versions_and_small_ordinals_in_corpus_context_are_allowed() -> None:
    findings = scan_text(
        "A real task document uses schema 2.0; see step 3 and Python 3.12.",
        source="module.py",
    )

    assert findings == []


def test_local_absolute_paths_are_rejected() -> None:
    findings = scan_text(_local_path(), source="body.md")

    assert [finding.rule for finding in findings] == ["local-absolute-path"]


def test_relative_claims_without_private_counts_are_allowed() -> None:
    findings = scan_text(
        "The change roughly halves a run and fewer statements need recovery.",
        source="body.md",
    )

    assert findings == []


def test_external_terms_file_keeps_private_names_out_of_the_repository(
    tmp_path: Path,
) -> None:
    private_name = "internal" + "_warehouse_table"
    terms_path = tmp_path / "terms.txt"
    terms_path.write_text(f"# local only\n{private_name}\n", encoding="utf-8")

    terms = load_private_terms(terms_path, required=True)
    findings = scan_text(f"mentions {private_name}", source="body.md", private_terms=terms)

    assert [finding.rule for finding in findings] == ["private-term"]


def test_release_mode_refuses_to_run_without_a_private_terms_file() -> None:
    with pytest.raises(ValueError, match="required for release"):
        load_private_terms(None, required=True)


def test_archive_members_are_scanned(tmp_path: Path) -> None:
    archive_path = tmp_path / "package.tar.gz"
    payload = _private_measurement().encode()
    with tarfile.open(archive_path, "w:gz") as archive:
        info = tarfile.TarInfo("package/CHANGELOG.md")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    findings = scan_archives([archive_path], private_terms=[])

    assert findings
    assert findings[0].source.endswith("!package/CHANGELOG.md")


def test_cli_returns_nonzero_for_an_injected_violation(tmp_path: Path) -> None:
    path = tmp_path / "release-body.md"
    path.write_text(_private_measurement(), encoding="utf-8")

    assert main(["text", str(path)]) == 1


def test_cli_scans_standard_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(_private_measurement()))

    assert main(["text", "-"]) == 1
