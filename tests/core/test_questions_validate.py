"""``scope-lineage questions validate``: question-set/1 and question-grades/1 files."""

from __future__ import annotations

import json
from pathlib import Path

from scope_lineage.cli import main
from scope_lineage.questions import GRADES_FORMAT, SET_FORMAT, validate_document

from .questions_demo import SET_YAML, grades, write, write_grades, write_set


def _set_document() -> dict:
    import yaml

    from scope_lineage.catalog.loader import yaml_loader

    document = yaml.load(SET_YAML, Loader=yaml_loader())  # noqa: S506 - a SafeLoader
    document["scoring"] = {str(k): v for k, v in document["scoring"].items()}
    return document


def test_the_demo_set_has_no_errors() -> None:
    assert validate_document(_set_document()) == []


def test_formats_are_named() -> None:
    assert SET_FORMAT == "question-set/1"
    assert GRADES_FORMAT == "question-grades/1"


def test_duplicate_ids_are_errors() -> None:
    document = _set_document()
    document["questions"][2]["id"] = "Q01"

    errors = validate_document(document)

    assert [e["at"] for e in errors] == ["questions[2].id"]
    assert "Q01" in errors[0]["message"] and "questions[0]" in errors[0]["message"]


def test_a_blank_answer_key_is_an_error() -> None:
    document = _set_document()
    document["questions"][1]["answer_key"] = "   "

    errors = validate_document(document)

    assert [e["at"] for e in errors] == ["questions[1].answer_key"]


def test_a_missing_answer_key_is_a_schema_error() -> None:
    document = _set_document()
    del document["questions"][0]["answer_key"]

    errors = validate_document(document)

    assert errors and errors[0]["at"] == "questions[0]"
    assert "answer_key" in errors[0]["message"]


def test_scoring_keys_are_the_three_scores() -> None:
    document = _set_document()
    document["scoring"]["3"] = "满分以上"

    assert validate_document(document)


def test_an_unknown_doc_format_is_an_error() -> None:
    errors = validate_document({"doc_format": "question-set/9", "questions": []})

    assert errors and "doc_format" in errors[0]["message"]


def test_grades_score_and_gap_are_checked() -> None:
    document = grades("r1", {"Q01": (3, "none"), "Q02": (1, "page_gone")})

    errors = validate_document(document)

    assert [e["at"] for e in errors] == ["grades[0].score", "grades[1].gap"]


def test_grades_duplicate_ids_are_errors() -> None:
    document = grades("r1", {"Q01": (2, "none")})
    document["grades"].append(dict(document["grades"][0]))

    assert [e["at"] for e in validate_document(document)] == ["grades[1].id"]


# ------------------------------------------------------------------ CLI


def test_cli_validates_a_yaml_set(tmp_path: Path, capsys) -> None:
    assert main(["questions", "validate", str(write_set(tmp_path))]) == 0

    out = capsys.readouterr().out
    assert "question-set/1" in out
    assert "4 question(s)" in out
    assert "0 error(s)" in out


def test_cli_validates_a_json_set(tmp_path: Path) -> None:
    path = write(tmp_path / "set.json", json.dumps(_set_document(), ensure_ascii=False))

    assert main(["questions", "validate", str(path)]) == 0


def test_cli_exits_one_and_names_the_place(tmp_path: Path, capsys) -> None:
    path = write_set(tmp_path, SET_YAML.replace("id: Q03", "id: Q02"))

    assert main(["questions", "validate", str(path)]) == 1

    out = capsys.readouterr().out
    assert "questions[2].id" in out
    assert "1 error(s)" in out


def test_cli_validates_grades(tmp_path: Path, capsys) -> None:
    path = write_grades(tmp_path, "grades.json", grades("r1", {"Q01": (2, "none")}))

    assert main(["questions", "validate", str(path)]) == 0
    assert "question-grades/1" in capsys.readouterr().out


def test_cli_exits_two_on_unreadable_input(tmp_path: Path, capsys) -> None:
    assert main(["questions", "validate", str(tmp_path / "missing.yaml")]) == 2
    assert "missing.yaml" in capsys.readouterr().err

    broken = write(tmp_path / "broken.yaml", "questions: [\n")
    assert main(["questions", "validate", str(broken)]) == 2
