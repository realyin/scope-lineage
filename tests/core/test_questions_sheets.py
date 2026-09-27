"""``questions sheet`` / ``grading-sheet``: what the answerer and the grader are given."""

from __future__ import annotations

from pathlib import Path

from scope_lineage.cli import main
from scope_lineage.questions import parse_answers

from .questions_demo import ANSWERS_MD, CONTRACT, CUSTOMER, write, write_set


def _sheet(tmp_path: Path, *extra: str) -> str:
    out = tmp_path / "sheet.md"
    assert main(["questions", "sheet", str(write_set(tmp_path)), "--out", str(out), *extra]) == 0
    return out.read_text(encoding="utf-8")


def test_the_sheet_holds_the_questions_and_nothing_the_grader_uses(tmp_path: Path) -> None:
    sheet = _sheet(tmp_path)

    for qid in ("Q01", "Q02", "Q03", "Q04"):
        assert f"\n## {qid}\n" in sheet
    assert "这张表一行是什么？" in sheet
    assert CUSTOMER in sheet and "concept:customer" in sheet
    for secret in ("cust_id + dt", "1 表示正常", "材料包 粒度节", "需要 owner 确认", "粒度"):
        assert secret not in sheet


def test_the_sheet_header_says_to_read_only_the_pages(tmp_path: Path) -> None:
    sheet = _sheet(tmp_path, "--pages", "pages/semantics")

    header = sheet.split("\n## ", 1)[0]
    assert "只读" in header
    assert "pages/semantics" in header
    assert "## <id>" in header
    assert "演示客户切片" in header


def test_the_sheet_takes_a_subset_by_table_or_id(tmp_path: Path) -> None:
    by_table = _sheet(tmp_path, "--only-table", CONTRACT)
    assert "## Q03" in by_table and "## Q01" not in by_table

    by_id = _sheet(tmp_path, "--ids", "Q04", "Q02")
    assert by_id.index("## Q02") < by_id.index("## Q04")
    assert "## Q01" not in by_id

    by_concept = _sheet(tmp_path, "--only-table", "concept:customer")
    assert "## Q04" in by_concept and "## Q03" not in by_concept


def test_an_unknown_id_or_table_is_refused(tmp_path: Path, capsys) -> None:
    path = str(write_set(tmp_path))
    out = str(tmp_path / "sheet.md")

    assert main(["questions", "sheet", path, "--ids", "Q99", "--out", out]) == 1
    assert "Q99" in capsys.readouterr().err
    assert main(["questions", "sheet", path, "--only-table", "demo.none", "--out", out]) == 1
    assert not Path(out).exists()


def test_an_invalid_set_is_refused(tmp_path: Path, capsys) -> None:
    path = write(tmp_path / "bad.yaml", "doc_format: question-set/1\nquestions: []\n")

    assert main(["questions", "sheet", str(path), "--out", str(tmp_path / "s.md")]) == 1
    assert "questions" in capsys.readouterr().err


# ------------------------------------------------------------------ answers


def test_answers_are_split_on_level_two_headings() -> None:
    parsed = parse_answers(ANSWERS_MD)

    assert list(parsed.answers) == ["Q01", "Q02", "Q03"]
    assert parsed.answers["Q01"].startswith("每个客户每天一行")
    assert "### 依据" in parsed.answers["Q01"]
    assert "## not-a-question" in parsed.answers["Q02"]
    assert parsed.answers["Q03"] == "不知道。"
    assert parsed.duplicates == []


def test_a_repeated_answer_heading_is_reported() -> None:
    parsed = parse_answers("## Q01\n一\n\n## Q01\n二\n")

    assert parsed.duplicates == ["Q01"]
    assert parsed.answers["Q01"] == "一"


def _grading(tmp_path: Path, *extra: str, answers: str = ANSWERS_MD) -> str:
    out = tmp_path / "grading.md"
    code = main([
        "questions", "grading-sheet", str(write_set(tmp_path)),
        "--answers", str(write(tmp_path / "answers.md", answers)),
        "--out", str(out), *extra,
    ])
    assert code == 0
    return out.read_text(encoding="utf-8")


def test_the_grading_sheet_puts_key_evidence_and_answer_side_by_side(tmp_path: Path) -> None:
    sheet = _grading(tmp_path)

    q02 = sheet.split("\n## Q02\n", 1)[1].split("\n## Q03\n", 1)[0]
    assert "cust_status 取值 1 表示什么？" in q02
    assert "1 表示正常。" in q02
    assert "列注释 cust_status" in q02
    assert "需要 owner 确认" in q02
    assert "2 的含义页面没写" in q02
    assert "码值" in q02
    q04 = sheet.split("\n## Q04\n", 1)[1]
    assert "概念页 数据清单" in q04
    assert "（未作答）" in q04


def test_the_grading_sheet_states_the_scoring_rules(tmp_path: Path) -> None:
    header = _grading(tmp_path).split("\n## Q01\n", 1)[0]

    assert "方向对但不完整" in header
    assert "question-grades/1" in header
    assert "待 owner 确认" in header and "扣一分" in header
    assert "key_wrong" in header


def test_the_grading_sheet_falls_back_to_the_default_scoring(tmp_path: Path) -> None:
    from .questions_demo import SET_YAML

    bare = SET_YAML.replace("  2: 正确完整\n  1: 方向对但不完整\n  0: 错误或没找到\n", "")
    write_set(tmp_path, bare.replace("scoring:\n", ""))
    out = tmp_path / "grading.md"
    answers = write(tmp_path / "answers.md", "## Q01\n一行一个客户\n")

    assert main([
        "questions", "grading-sheet", str(tmp_path / "questions.yaml"),
        "--answers", str(answers), "--out", str(out),
    ]) == 0
    assert "落到具体的列、码值或条件" in out.read_text(encoding="utf-8")


def test_missing_and_stray_answers_are_warned_about(tmp_path: Path, capsys) -> None:
    _grading(tmp_path, answers=ANSWERS_MD + "\n## Q77\n多出来的\n")

    err = capsys.readouterr().err
    assert "Q04" in err
    assert "Q77" in err


def test_the_grading_sheet_takes_a_subset(tmp_path: Path) -> None:
    sheet = _grading(tmp_path, "--ids", "Q03")

    assert "## Q03" in sheet and "## Q01" not in sheet
