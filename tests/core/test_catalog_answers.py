"""``cli_catalog_answers``: the catalog's answer commands as functions.

The command line and anything that serves the same answers another way (an HTTP or MCP
server outside this package) call one set of functions, so a served answer is the one
``--json`` prints, byte for byte, and a refused input is refused with the same sentence
and the same exit code. Each case compares a function's answer with what ``main`` prints
for the same input on the demo ontology and the demo table-semantics document.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage import cli_catalog_answers as answers
from scope_lineage.cli import main

ROOT = Path(__file__).resolve().parents[2]
ONTOLOGY = Path(__file__).parent / "fixtures" / "catalog" / "ontology.json"
SEMANTICS = ROOT / "examples" / "table-semantics"
CUSTOMER = "demo_dwd.dwd_party_customer_info_df"
LOAN = "demo_dwd.dwd_lending_loan_df"
DATE = "2026-01-02"


@pytest.fixture(scope="module")
def document() -> dict:
    return answers.load_ontology(str(ONTOLOGY))


@pytest.fixture(scope="module")
def semantics() -> dict:
    return answers.load_semantics(str(SEMANTICS))


def _cli(capsys, *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_search_is_what_the_cli_prints(capsys, document, semantics) -> None:
    code, out, _ = _cli(
        capsys, "catalog", "search", str(ONTOLOGY), "客户", "--semantics", str(SEMANTICS),
        "--limit", "3", "--json",
    )
    answer = answers.search(document, "客户", semantics, limit=3)

    assert answer.json_text() + "\n" == out
    assert answer.exit_code == code == 0


def test_search_text_is_what_the_cli_prints(capsys, document) -> None:
    _, out, _ = _cli(capsys, "catalog", "search", str(ONTOLOGY), "客户", "--kind", "concept")

    assert answers.search(document, "客户", kinds=["concept"]).text() == out


def test_nothing_found_keeps_the_answer_and_exits_1(capsys, document) -> None:
    code, out, _ = _cli(capsys, "catalog", "query", str(ONTOLOGY), "table", "x.nothing", "--json")
    answer = answers.query(document, "table", "x.nothing")

    assert answer.json_text() + "\n" == out
    assert answer.exit_code == code == 1


def test_query_is_what_the_cli_prints(capsys, document) -> None:
    code, out, _ = _cli(capsys, "catalog", "query", str(ONTOLOGY), "table", LOAN, "--json")
    answer = answers.query(document, "table", LOAN)

    assert answer.json_text() + "\n" == out
    assert answer.exit_code == code == 0


def test_context_with_columns_of_one_table_is_what_the_cli_prints(
    capsys, document, semantics
) -> None:
    code, out, _ = _cli(
        capsys, "catalog", "context", str(ONTOLOGY), "--semantics", str(SEMANTICS),
        "--table", CUSTOMER, "--columns", "gender_cd, customer_id", "--focus", "--brief",
        "--concept", "customer", "--json",
    )
    answer = answers.context(
        document, semantics, tables=[CUSTOMER], columns_of_table=["gender_cd, customer_id"],
        concepts=["customer"], brief=True, focus=True,
    )

    assert answer.json_text() + "\n" == out
    assert answer.exit_code == code == 0


@pytest.mark.parametrize(
    ("argv", "kwargs"),
    [
        ([], {}),
        (["--columns", "a"], {"columns_of_table": ["a"]}),
        (["--table", CUSTOMER, "--focus"], {"tables": [CUSTOMER], "focus": True}),
    ],
)
def test_context_refuses_what_the_cli_refuses(capsys, document, argv, kwargs) -> None:
    code, _, err = _cli(capsys, "catalog", "context", str(ONTOLOGY), *argv)

    with pytest.raises(answers.CatalogAnswerError) as raised:
        answers.context(document, None, **kwargs)
    assert raised.value.exit_code == code == 2
    assert raised.value.message + "\n" == err


def test_check_sql_is_what_the_cli_prints(capsys, tmp_path, document) -> None:
    sql = f"SELECT gender_cd, count(*) FROM {CUSTOMER} GROUP BY gender_cd"
    path = tmp_path / "q.sql"
    path.write_text(sql, encoding="utf-8")
    code, out, _ = _cli(capsys, "catalog", "check-sql", str(ONTOLOGY), str(path), "--json")
    answer = answers.check_sql(document, sql)

    assert answer.json_text() + "\n" == out
    assert answer.exit_code == code


def test_check_sql_refuses_sql_that_does_not_parse(capsys, tmp_path, document) -> None:
    path = tmp_path / "q.sql"
    path.write_text("SELECT FROM (", encoding="utf-8")
    code, _, err = _cli(capsys, "catalog", "check-sql", str(ONTOLOGY), str(path))

    with pytest.raises(answers.CatalogAnswerError) as raised:
        answers.check_sql(document, "SELECT FROM (")
    assert raised.value.exit_code == code == 2
    assert raised.value.message + "\n" == err


def test_an_unreadable_ontology_is_refused_with_the_cli_sentence(capsys, tmp_path) -> None:
    missing = tmp_path / "none.json"
    code, _, err = _cli(capsys, "catalog", "query", str(missing), "table", LOAN)

    with pytest.raises(answers.CatalogAnswerError) as raised:
        answers.load_ontology(str(missing))
    assert (raised.value.exit_code, raised.value.message + "\n") == (code, err) == (2, err)


@pytest.mark.parametrize("content", ["{not json", "[1]", '{"doc_format": "other/1"}'])
def test_a_document_that_is_not_an_ontology_is_refused_like_the_cli(
    capsys, tmp_path, content
) -> None:
    path = tmp_path / "ontology.json"
    path.write_text(content, encoding="utf-8")
    code, _, err = _cli(capsys, "catalog", "query", str(path), "table", LOAN)

    with pytest.raises(answers.CatalogAnswerError) as raised:
        answers.load_ontology(str(path))
    assert raised.value.exit_code == code
    assert raised.value.message + "\n" == err


def test_a_missing_semantics_directory_is_refused_like_the_cli(capsys, tmp_path) -> None:
    missing = tmp_path / "none"
    code, _, err = _cli(
        capsys, "catalog", "search", str(ONTOLOGY), "x", "--semantics", str(missing)
    )

    with pytest.raises(answers.CatalogAnswerError) as raised:
        answers.load_semantics(str(missing))
    assert raised.value.exit_code == code == 2
    assert raised.value.message + "\n" == err


def test_no_semantics_directory_is_none() -> None:
    assert answers.load_semantics(None) is None


def test_pending_add_writes_what_the_cli_writes(tmp_path) -> None:
    by_cli, by_function = tmp_path / "cli.jsonl", tmp_path / "function.jsonl"
    options = dict(
        question="上月新增客户数", missing="注销的客户算不算", term="注销",
        tables=[CUSTOMER], columns=[f"{CUSTOMER}.gender_cd"], proposed="不算",
    )
    assert main([
        "catalog", "pending", "add", str(by_cli), "--date", DATE,
        "--question", options["question"], "--missing", options["missing"],
        "--term", options["term"], "--table", CUSTOMER, "--column", options["columns"][0],
        "--proposed", options["proposed"],
    ]) == 0

    lines = answers.pending_add(str(by_function), date=DATE, **options)

    assert by_function.read_bytes() == by_cli.read_bytes()
    assert lines == [json.loads(by_cli.read_text(encoding="utf-8"))]


def test_pending_add_from_sql_records_the_sql_name_it_is_given(tmp_path) -> None:
    sql = f"SELECT count(*) FROM {CUSTOMER} WHERE /* 待确认：注销的客户算不算 */ 1 = 1"
    path = tmp_path / "q.sql"
    path.write_text(sql, encoding="utf-8")
    by_cli, by_function = tmp_path / "cli.jsonl", tmp_path / "function.jsonl"
    assert main([
        "catalog", "pending", "add", str(by_cli), "--date", DATE, "--question", "q",
        "--from-sql", str(path),
    ]) == 0

    answers.pending_add(str(by_function), question="q", sql=sql, sql_name=str(path), date=DATE)

    assert by_function.read_bytes() == by_cli.read_bytes()


@pytest.mark.parametrize(
    ("argv", "kwargs"),
    [
        (["--missing", "m", "--from-sql", "x.sql"], {"missing": "m", "sql": "SELECT 1"}),
        (["--missing", "m", "--column", "a.b"], {"missing": "m", "columns": ["a.b"]}),
        (["--missing", "m", "--date", "2026-13-01"], {"missing": "m", "date": "2026-13-01"}),
    ],
)
def test_pending_add_refuses_what_the_cli_refuses(capsys, tmp_path, argv, kwargs) -> None:
    target = tmp_path / "p.jsonl"
    code, _, err = _cli(capsys, "catalog", "pending", "add", str(target), "--question", "q", *argv)

    with pytest.raises(answers.CatalogAnswerError) as raised:
        answers.pending_add(str(target), question="q", **kwargs)
    assert raised.value.exit_code == code == 2
    assert raised.value.message + "\n" == err
    assert not target.exists()


def test_pending_add_from_sql_without_a_placeholder_writes_nothing(capsys, tmp_path) -> None:
    target = tmp_path / "p.jsonl"
    with pytest.raises(answers.CatalogAnswerError) as raised:
        answers.pending_add(str(target), question="q", sql="SELECT 1", sql_name="q.sql")
    assert raised.value.exit_code == 1
    assert not target.exists()


def test_pending_list_is_what_the_cli_prints(capsys, tmp_path, document, semantics) -> None:
    pending = tmp_path / "p.jsonl"
    answers.pending_add(str(pending), question="q", missing="注销的客户算不算", date=DATE)
    with pending.open("a", encoding="utf-8") as handle:
        handle.write("not json\n")
    code, out, _ = _cli(
        capsys, "catalog", "pending", "list", str(pending), "--ontology", str(ONTOLOGY),
        "--semantics", str(SEMANTICS), "--json",
    )
    answer = answers.pending_list(str(pending), document, semantics)

    assert answer.json_text() + "\n" == out
    assert answer.exit_code == code == 1


def test_pending_list_of_an_unreadable_file_is_refused_like_the_cli(capsys, tmp_path) -> None:
    missing = tmp_path / "none.jsonl"
    code, _, err = _cli(capsys, "catalog", "pending", "list", str(missing))

    with pytest.raises(answers.CatalogAnswerError) as raised:
        answers.pending_list(str(missing))
    assert raised.value.exit_code == code == 2
    assert raised.value.message + "\n" == err
