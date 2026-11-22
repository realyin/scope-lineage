"""4.4-1 and 4.4-2: two ways a key-fold candidate used to fold or drop the wrong tables.

4.4-1. ``key_stem`` took ``id`` / ``no`` off the *front* of a key as well as the back, so
``id_card_no`` (an identity-card number) reduced to ``card`` and folded into one concept
with ``card_no`` (a bank card). A leading ``id`` / ``no`` is part of the name, not a key
marker; only a trailing one says "this is a key".

4.4-2. ``is_generic_stem`` intersected the Chinese two-character fragments of every
comment, and a comment written in English has none, so one English comment among three
retired the stem. Only the comments that contain Chinese take part; with none, the rule
does not apply.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.cli import main
from scope_lineage.render.concepts import is_generic_stem, key_column_name, key_stem


def _schema_file(path: Path, comments: dict[str, dict[str, str]]) -> Path:
    tables = [
        {
            "table_name": table,
            "schema": [
                {"columnName": column, "columnType": "string", "columnComment": comment}
                for column, comment in columns.items()
            ],
        }
        for table, columns in comments.items()
    ]
    path.write_text(json.dumps({"tables": tables}, ensure_ascii=False), encoding="utf-8")
    return path


def _ontology(tmp_path: Path, tasks: dict[str, str], schema: Path | None = None) -> dict:
    corpus, cards, out = tmp_path / "corpus", tmp_path / "cards", tmp_path / "out"
    for name, sql in tasks.items():
        sql_file = tmp_path / f"{name}.sql"
        sql_file.write_text(sql, encoding="utf-8")
        args = ["parse", "--sql-file", str(sql_file), "--out", str(corpus / name)]
        if schema is not None:
            args += ["--schema", str(schema)]
        assert main(args) == 0
    assert main(["tables", "--lineage", str(corpus), "--out", str(cards)]) == 0
    assert (
        main([
            "ontology", "--lineage", str(corpus), "--out", str(out),
            "--tables", str(cards / "tables.json"), "--format", "json",
        ])
        == 0
    )
    return json.loads((out / "ontology.json").read_text(encoding="utf-8"))


def _concept_tables(document: dict) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for concept in document.get("concepts") or []:
        tables = {str(member.get("table")) for member in concept.get("tables") or []}
        found[str(concept.get("id"))] = tables
    return found


# ------------------------------------------------------------------ 4.4-1


@pytest.mark.parametrize(
    ("column", "expected"),
    [
        ("id_card_no", "id_card"),
        ("no_tax_amt", "no_tax_amt"),
        ("id_cust", "id_cust"),
        # Sentinels: the trailing markers still come off, and the other leading ones too.
        ("card_no", "card"),
        ("cust_id", "cust"),
        ("code_branch", "branch"),
        ("id", "id"),
    ],
)
def test_a_leading_id_or_no_is_part_of_the_stem(column: str, expected: str) -> None:
    assert key_stem(column) == expected


def test_the_display_name_keeps_a_leading_id_too() -> None:
    assert key_column_name("id_card_no") == "id card"
    assert key_column_name("card_no") == "card"


def test_an_identity_card_and_a_bank_card_are_two_concepts(tmp_path: Path) -> None:
    document = _ontology(
        tmp_path,
        {
            "person_task": (
                "INSERT OVERWRITE TABLE dw.person "
                "SELECT id_card_no, max(name) AS name FROM src.p GROUP BY id_card_no"
            ),
            "card_task": (
                "INSERT OVERWRITE TABLE dw.bank_card "
                "SELECT card_no, max(bank) AS bank FROM src.c GROUP BY card_no"
            ),
        },
    )
    for concept_id, tables in _concept_tables(document).items():
        assert not {"dw.person", "dw.bank_card"} <= tables, concept_id


# ------------------------------------------------------------------ 4.4-2


def test_a_comment_without_chinese_takes_no_part_in_the_intersection() -> None:
    assert not is_generic_stem("customer", ["客户编号", "客户号", "Customer ID"])
    # With no Chinese comment at all, the rule has no evidence to read.
    assert not is_generic_stem("code", ["channel code", "province code", "status code"])


def test_three_unrelated_chinese_comments_still_retire_the_stem() -> None:
    """Sentinel: the evidence rule itself is unchanged."""
    assert is_generic_stem("code", ["渠道编码", "省份编码", "状态编码"])
    assert is_generic_stem("code", ["渠道编码", "省份编码", "状态编码", "Code"])


def _customer_tasks() -> dict[str, str]:
    return {
        f"c{n}_task": (
            f"INSERT OVERWRITE TABLE dw.c{n} "
            f"SELECT customer_id, max(v) AS v FROM src.s{n} GROUP BY customer_id"
        )
        for n in (1, 2, 3)
    }


@pytest.mark.parametrize(
    "comments",
    [
        ("客户编号", "客户号", "客户标识"),
        ("客户编号", "客户号", "Customer ID"),
    ],
)
def test_one_english_comment_does_not_retire_a_customer_key(
    tmp_path: Path, comments: tuple[str, str, str]
) -> None:
    schema = _schema_file(
        tmp_path / "schema.json",
        {
            f"dw.c{n}": {"customer_id": comment, "v": "值"}
            for n, comment in zip((1, 2, 3), comments)
        },
    )
    document = _ontology(tmp_path, _customer_tasks(), schema)
    assert "concept:customer" in _concept_tables(document)
    assert not document.get("retired_stems")
