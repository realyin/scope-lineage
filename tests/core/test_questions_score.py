"""``questions score``: totals, breakdowns, lost points and earlier rounds."""

from __future__ import annotations

import json
from pathlib import Path

from scope_lineage.cli import main

from .questions_demo import CONTRACT, CUSTOMER, grades, write_grades, write_set

ROUND_2 = {
    "Q01": (2, "none"),
    "Q02": (1, "page_missing", "没说取值 2 待确认"),
    "Q03": (0, "answerer", "页面写了条件，作答没找到"),
    "Q04": (2, "key_wrong", "参考答案漏了一张表"),
}
ROUND_1 = {"Q01": (1, "page_wrong"), "Q02": (1, "page_missing"), "Q03": (2, "none")}


def _score(tmp_path: Path, scores: dict, *extra: str, code: int = 0) -> Path:
    out = tmp_path / "score"
    argv = [
        "questions", "score",
        str(write_grades(tmp_path, "r2.json", grades("r2", scores))),
        "--set", str(write_set(tmp_path)), "--out", str(out), *extra,
    ]
    assert main(argv) == code
    return out


def _report(out: Path) -> dict:
    return json.loads((out / "score.json").read_text(encoding="utf-8"))


def test_total_and_percent(tmp_path: Path) -> None:
    report = _report(_score(tmp_path, ROUND_2))

    assert report["doc_format"] == "question-score/1"
    assert report["round"] == "r2"
    assert report["total"] == {
        "questions": 4, "graded": 4, "points": 5, "max": 8, "percent": 62.5,
    }
    assert report["ungraded"] == []


def test_breakdowns_by_type_table_and_gap(tmp_path: Path) -> None:
    report = _report(_score(tmp_path, ROUND_2))

    by_type = {row["key"]: (row["points"], row["max"]) for row in report["by_type"]}
    assert by_type == {"粒度": (2, 2), "码值": (1, 2), "取数": (0, 2), "选表": (2, 2)}
    by_table = {row["key"]: (row["points"], row["max"]) for row in report["by_table"]}
    assert by_table == {CUSTOMER: (3, 4), CONTRACT: (0, 2), "concept:customer": (2, 2)}
    by_gap = {row["gap"]: (row["count"], row["lost"]) for row in report["by_gap"]}
    assert by_gap == {"none": (1, 0), "page_missing": (1, 1), "answerer": (1, 2),
                      "key_wrong": (1, 0)}


def test_lost_points_and_wrong_keys_are_listed(tmp_path: Path) -> None:
    report = _report(_score(tmp_path, ROUND_2))

    assert [(row["id"], row["score"], row["gap"]) for row in report["lost"]] == [
        ("Q02", 1, "page_missing"), ("Q03", 0, "answerer"),
    ]
    assert report["lost"][1]["reason"] == "页面写了条件，作答没找到"
    assert [row["id"] for row in report["key_wrong"]] == ["Q04"]


def test_the_markdown_report(tmp_path: Path) -> None:
    md = (_score(tmp_path, ROUND_2) / "score.md").read_text(encoding="utf-8")

    assert "5 / 8" in md and "62.5%" in md
    assert "页面写了条件，作答没找到" in md
    assert "page_missing" in md
    assert "参考答案漏了一张表" in md


def test_ungraded_questions_are_reported_not_counted(tmp_path: Path, capsys) -> None:
    scores = {k: v for k, v in ROUND_2.items() if k != "Q04"}
    report = _report(_score(tmp_path, scores))

    assert report["ungraded"] == ["Q04"]
    assert report["total"]["max"] == 6
    assert "Q04" in capsys.readouterr().err


def test_a_graded_id_missing_from_the_set_is_refused(tmp_path: Path, capsys) -> None:
    out = _score(tmp_path, {**ROUND_2, "Q99": (2, "none")}, code=1)

    assert "Q99" in capsys.readouterr().err
    assert not (out / "score.json").exists()


def test_a_subset_scores_only_its_questions(tmp_path: Path) -> None:
    report = _report(_score(tmp_path, ROUND_2, "--only-table", CUSTOMER))

    assert report["total"]["questions"] == 2
    assert report["total"]["points"] == 3
    assert report["ungraded"] == []

    by_id = _report(_score(tmp_path, {"Q03": ROUND_2["Q03"]}, "--ids", "Q03"))
    assert by_id["total"] == {"questions": 1, "graded": 1, "points": 0, "max": 2,
                              "percent": 0.0}


def test_previous_rounds_become_comparison_columns(tmp_path: Path) -> None:
    previous = write_grades(tmp_path, "r1.json", grades("r1", ROUND_1))
    out = _score(tmp_path, ROUND_2, "--previous", str(previous))
    report = _report(out)

    assert [r["round"] for r in report["rounds"]] == ["r1", "r2"]
    assert report["rounds"][0]["total"]["points"] == 4
    assert report["rounds"][0]["total"]["max"] == 6
    by_type = {row["key"]: row["rounds"] for row in report["by_type"]}
    assert by_type["粒度"] == {"r1": 50.0, "r2": 100.0}
    assert by_type["选表"] == {"r1": None, "r2": 100.0}
    changes = {row["id"]: row["scores"] for row in report["changes"]}
    assert changes == {
        "Q01": {"r1": 1, "r2": 2}, "Q03": {"r1": 2, "r2": 0}, "Q04": {"r1": None, "r2": 2},
    }
    md = (out / "score.md").read_text(encoding="utf-8")
    assert "| r1 | 3 | 4 | 6 | 66.7% |" in md
    assert "| r2 | 4 | 5 | 8 | 62.5% |" in md


def test_duplicate_round_labels_fall_back_to_file_names(tmp_path: Path) -> None:
    previous = write_grades(tmp_path, "older.json", grades("r2", ROUND_1))
    report = _report(_score(tmp_path, ROUND_2, "--previous", str(previous)))

    assert [r["round"] for r in report["rounds"]] == ["older", "r2"]
