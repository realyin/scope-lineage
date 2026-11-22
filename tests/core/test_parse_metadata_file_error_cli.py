"""``parse`` reports an unusable metadata file as an input error, not a Traceback.

A ``--schema`` (or ``--target-ddl-metadata``) file that is empty after its BOM, is not
UTF-8, or is not JSON raises ``MetadataFileError``. The CLI let it escape, so the user got
a Python Traceback and exit code 1 -- the code ``parse`` uses for "ran, but a task failed".
It now prints the error's message on stderr and exits 2, like every other input error the
CLI rejects (a bad ``--metadata-patch``, an argparse error).
"""

from __future__ import annotations

import pytest

from scope_lineage.cli import main

BAD_FILES = {
    "bom_only": (b"\xef\xbb\xbf", "为空"),
    "not_utf8": (b'{"a": "\xff"}', "UTF-8"),
    "bad_json": (b'{"a":', "JSON"),
}


def _run(tmp_path, flag: str, content: bytes, capsys):
    sql = tmp_path / "t.sql"
    sql.write_text("INSERT OVERWRITE TABLE db.tgt SELECT id FROM db.src", encoding="utf-8")
    metadata = tmp_path / "metadata.json"
    metadata.write_bytes(content)
    code = main(["parse", "--sql-file", str(sql), "--out", str(tmp_path / "out"), flag, str(metadata)])
    return code, capsys.readouterr()


@pytest.mark.parametrize("kind", sorted(BAD_FILES))
def test_a_bad_schema_file_is_an_input_error(tmp_path, capsys, kind: str) -> None:
    content, headline = BAD_FILES[kind]

    code, printed = _run(tmp_path, "--schema", content, capsys)

    assert code == 2
    assert "Traceback" not in printed.err
    first = printed.err.splitlines()[0]
    assert headline in first and "metadata.json" in first
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("kind", sorted(BAD_FILES))
def test_a_bad_target_ddl_file_is_an_input_error(tmp_path, capsys, kind: str) -> None:
    content, _ = BAD_FILES[kind]

    code, printed = _run(tmp_path, "--target-ddl-metadata", content, capsys)

    assert code == 2
    assert "Traceback" not in printed.err
    assert printed.err.strip()


def test_a_missing_schema_file_is_an_input_error(tmp_path, capsys) -> None:
    sql = tmp_path / "t.sql"
    sql.write_text("SELECT 1", encoding="utf-8")

    code = main([
        "parse", "--sql-file", str(sql), "--out", str(tmp_path / "out"),
        "--schema", str(tmp_path / "absent.json"),
    ])

    assert code == 2
    assert "不存在" in capsys.readouterr().err


def test_sentinel_a_good_schema_file_still_parses(tmp_path, capsys) -> None:
    code, _ = _run(tmp_path, "--schema", b'{"db.src": ["id"]}', capsys)

    assert code == 0
