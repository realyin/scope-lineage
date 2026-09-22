"""``describe --ontology``: one task's profile read against the concept layer (N5).

The corpus ontology answers a question one statement cannot: 「这张表代表什么业务对象」.
Without it a task profile can only name tables; with it every table the statement touches
carries the concept it represents, the grain can be phrased in business words instead of
column names, and each output column can say which concept attribute it carries.

Two properties are pinned hardest, because both are about honesty rather than features:

- without ``--ontology`` the documents are **byte for byte** what they were before this
  layer existed -- 「没给本体」 and 「本体说这张表没有概念」 are different answers;
- a concept the review round has not settled travels with ``provisional: true`` wherever
  it appears, so a reader never mistakes a table standing in for itself for a business
  concept somebody confirmed.

Every table, column and comment below is synthetic. The corpus they stand in for is
never named.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import pytest

from scope_lineage.cli import main
from scope_lineage.contract import to_lineage_dict
from scope_lineage.metadata.schema_metadata import SchemaMap
from scope_lineage.render.ontology import build_ontology
from scope_lineage.render.semantic_markdown import render_semantic_markdown
from scope_lineage.render.semantic_profile import (
    ONTOLOGY_DOC_FORMAT,
    apply_ontology,
    build_semantic_profile,
)
from scope_lineage.render.table_cards import build_table_cards
from scope_lineage.scope.scope_builder import parse_scope_lineage

from .statement_document import write_statement_documents


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "examples"


# ------------------------------------------------------------------ synthetic corpus

COLUMNS = {
    "stg.message_raw": [
        ("msg_no", "string", "消息发送"),
        ("cust_no", "string", "客户"),
        ("send_time", "timestamp", "发送时间"),
        ("dt", "string", "日期"),
    ],
    "ods.message_send_di": [
        ("msg_no", "string", "消息发送"),
        ("cust_no", "string", "客户"),
        ("send_time", "timestamp", "发送时间"),
        ("dt", "string", "日期"),
    ],
    "ods.customer_base": [
        ("cust_no", "string", "客户"),
        ("cust_name", "string", "客户名称"),
        ("dt", "string", "日期"),
    ],
    "dwd.customer_df": [
        ("cust_no", "string", "客户"),
        ("cust_name", "string", "客户名称"),
        ("dt", "string", "日期"),
    ],
    "mart.customer_daily": [
        ("cust_no", "string", "客户"),
        ("dt", "string", "日期"),
        ("msg_cnt", "bigint", "消息条数"),
        ("cust_name", "string", "客户名称"),
    ],
    # Outside the corpus below on purpose: the table nothing models.
    "ods.unmodelled_source": [("k", "string", None), ("v", "string", None)],
}

#: The described statement: a daily fold of the message table onto the customer, joined
#: to the customer snapshot. Its target is keyed by 客户 × 日期, so the concept layer
#: reads it as another representation of 客户.
DAILY_SQL = (
    "INSERT OVERWRITE TABLE mart.customer_daily SELECT m.cust_no, m.dt, "
    "count(1) AS msg_cnt, max(c.cust_name) AS cust_name "
    "FROM ods.message_send_di m JOIN dwd.customer_df c ON m.cust_no = c.cust_no "
    "GROUP BY m.cust_no, m.dt"
)

CORPUS = (
    (
        "task_message_build",
        "INSERT OVERWRITE TABLE ods.message_send_di SELECT msg_no, max(cust_no) AS cust_no, "
        "max(send_time) AS send_time, max(dt) AS dt FROM stg.message_raw GROUP BY msg_no",
    ),
    (
        "task_customer",
        "INSERT OVERWRITE TABLE dwd.customer_df SELECT cust_no, max(cust_name) AS cust_name, "
        "max(dt) AS dt FROM ods.customer_base GROUP BY cust_no",
    ),
    ("task_customer_daily", DAILY_SQL),
)


def _schema() -> SchemaMap:
    return SchemaMap(
        {table: [name for name, _type, _comment in columns] for table, columns in COLUMNS.items()},
        column_details={
            table: [{"name": n, "type": t, "comment": c} for n, t, c in columns]
            for table, columns in COLUMNS.items()
        },
    )


def _document(sql: str, task_id: str) -> dict:
    return to_lineage_dict(parse_scope_lineage(sql, task_id, schema=_schema()))


def _ontology() -> dict:
    documents = [_document(sql, task) for task, sql in CORPUS]
    profiles = [build_semantic_profile(document) for document in documents]
    cards = build_table_cards(profiles, artifact_root="corpus")
    return build_ontology(documents, profiles, tables=cards, artifact_root="corpus")


def _profile(sql: str = DAILY_SQL, task_id: str = "task_customer_daily") -> dict:
    return build_semantic_profile(_document(sql, task_id))


def _described(sql: str = DAILY_SQL, task_id: str = "task_customer_daily") -> dict:
    return apply_ontology(_profile(sql, task_id), _ontology())


def _field(profile: dict, column: str) -> dict:
    return next(item for item in profile["fields"] if item["column"] == column)


def _input(profile: dict, table: str) -> dict:
    return next(item for item in profile["inputs"] if item["table"] == table)


# ------------------------------------------------------------------- task.concepts[]


def test_the_task_lists_a_concept_for_every_table_it_reads_or_writes() -> None:
    concepts = _described()["task"]["concepts"]

    assert [item["concept"] for item in concepts] == ["concept:cust", "concept:msg"]
    assert concepts[1] == {
        "concept": "concept:msg",
        "name": "消息发送",
        "kind": "event",
        "role": "summary",
        "membership_basis": "key:proven",
        "table": "ods.message_send_di",
        "direction": "read",
    }


def test_a_concept_this_statement_both_reads_and_writes_is_published_as_the_write() -> None:
    """One entry per concept, and the write is the stronger of the two facts.

    `dwd.customer_df` and `mart.customer_daily` are two representations of 客户; the
    statement reads one and writes the other. The read is still visible on its own
    input, so folding the pair onto the write loses nothing and stops the list from
    answering 「本语句和客户是什么关系」 twice with different words.
    """
    entry = _described()["task"]["concepts"][0]

    assert entry["direction"] == "write"
    assert entry["table"] == "mart.customer_daily"
    assert entry["role"] == "summary"


def test_the_written_target_names_the_concept_it_represents() -> None:
    assert _described()["task"]["output_concept"] == {
        "concept": "concept:cust",
        "name": "客户",
        "kind": "entity",
        "role": "summary",
    }


def test_a_provisional_concept_is_flagged_wherever_it_appears() -> None:
    """M1's 「这张表还没人说它是什么」 must not read as a settled business concept."""
    profile = _described(
        "INSERT OVERWRITE TABLE mart.raw_copy SELECT msg_no, cust_no, send_time, dt "
        "FROM stg.message_raw",
        "task_raw_copy",
    )
    entry = next(
        item
        for item in profile["task"]["concepts"]
        if item["concept"] == "concept:table:stg_message_raw"
    )

    assert entry["provisional"] is True
    assert entry["direction"] == "read"
    assert _input(profile, "stg.message_raw")["concept"]["provisional"] is True


def test_a_statement_the_ontology_does_not_model_gets_an_empty_list_not_a_guess() -> None:
    profile = _described(
        "INSERT OVERWRITE TABLE mart.unmodelled SELECT k, count(1) AS n "
        "FROM ods.unmodelled_source GROUP BY k",
        "task_unmodelled",
    )

    assert profile["task"]["concepts"] == []
    assert profile["task"]["output_concept"] is None
    assert _input(profile, "ods.unmodelled_source")["concept"] is None


# ------------------------------------------------------------------ inputs[].concept


def test_an_input_carries_the_concept_it_is_a_representation_of() -> None:
    profile = _described()

    assert _input(profile, "dwd.customer_df")["concept"] == {
        "concept": "concept:cust",
        "name": "客户",
        "kind": "entity",
        "role": "primary",
    }
    # `ods.message_send_di` is also a `reference` member of 客户; its *identity* is the
    # concept it is a copy of, never the one it merely points at.
    assert _input(profile, "ods.message_send_di")["concept"]["concept"] == "concept:msg"


# --------------------------------------------------------- fields[].concept_attribute


def test_a_field_reading_a_concept_attribute_names_the_attribute() -> None:
    assert _field(_described(), "cust_name")["concept_attribute"] == {
        "concept": "concept:cust",
        "name": "客户",
        "attribute": "cust_name",
    }


def test_a_field_reading_a_concepts_identity_key_says_it_is_the_key() -> None:
    field = _field(_described(), "cust_no")

    assert field["concept_attribute"] == {
        "concept": "concept:cust",
        "name": "客户",
        "attribute": "cust",
    }
    assert field["is_concept_key"] is True


def test_a_field_with_no_physical_source_carries_no_concept_attribute() -> None:
    """`count(1)` reads no column, so there is no attribute to attribute it to."""
    field = _field(_described(), "msg_cnt")

    assert "concept_attribute" not in field
    assert "is_concept_key" not in field


# ------------------------------------------------------ output_shape.grain.concept_text


def test_the_grain_is_phrased_in_concepts_when_every_key_is_one() -> None:
    grain = _described()["output_shape"]["grain"]

    assert grain["concept_text"] == "一行 = 一个客户 × 日期"
    # The structural answer is untouched: the concept phrasing is a reading of it.
    assert grain["basis"] == "group_by"
    assert [key["name"] for key in grain["keys"]] == ["cust_no", "dt"]


# ------------------------------------- the grain phrase over a wide, repetitive key set
#
# Four failures a corpus finds and a three-key example never does: a wide GROUP BY whose
# keys all carry the same business name, the same thing named once as a concept and once
# as that concept's own id column, a grain long enough to bury the line it sits on, and a
# grain the concept layer can barely place at all. Each is pinned against a real grain --
# the statement and its keys are parsed -- read against a hand-built concept layer, which
# is the only way to hold one variable still at a time.

WIDE_SCHEMA = {
    "ods.unit_a": ["unit_no", "dt"],
    "ods.unit_b": ["unit_no", "dt"],
    "ods.unit_c": ["unit_no", "dt"],
    "ods.wide_source": [f"k{index}" for index in range(1, 9)],
}

REPEAT_SQL = (
    "INSERT OVERWRITE TABLE mart.unit_daily SELECT a.unit_no AS unit_a_no, "
    "b.unit_no AS unit_b_no, c.unit_no AS unit_c_no, count(1) AS n "
    "FROM ods.unit_a a JOIN ods.unit_b b ON a.dt = b.dt "
    "JOIN ods.unit_c c ON a.dt = c.dt GROUP BY a.unit_no, b.unit_no, c.unit_no"
)
WIDE_SQL = (
    "INSERT OVERWRITE TABLE mart.wide_daily SELECT k1, k2, k3, k4, k5, k6, k7, k8, "
    "count(1) AS n FROM ods.wide_source GROUP BY k1, k2, k3, k4, k5, k6, k7, k8"
)
PARTIAL_SQL = (
    "INSERT OVERWRITE TABLE mart.partial_daily SELECT k1, k2, k3, k4, count(1) AS n "
    "FROM ods.wide_source GROUP BY k1, k2, k3, k4"
)

WIDE_COMMENTS = ("维度一", "维度二", "维度三", "维度四", "维度五", "维度六", "维度七", "维度八")


def _concept_entry(
    identifier: str,
    name: str,
    *,
    stem: str,
    tables: Sequence[tuple],
    attributes: Sequence[tuple],
    kind: str = "entity",
    tier: str = "implied",
) -> dict:
    """One `concepts[]` entry, shaped exactly as ``ontology.py`` publishes it."""
    return {
        "id": identifier,
        "name": name,
        "kind": kind,
        "identity": {"stem": stem, "columns_seen": []},
        "tables": [
            {
                "table": table,
                "role": role,
                "membership_basis": basis,
                "key_columns": list(key_columns),
                "grain": "group_by",
            }
            for table, role, basis, key_columns in tables
        ],
        "attributes": [
            {
                "stem": attribute_stem,
                "type": None,
                "comment": comment,
                "sources": [{"table": table, "column": column} for table, column in sources],
            }
            for attribute_stem, comment, sources in attributes
        ],
        "tier": tier,
    }


def _ontology_of(*concepts: dict) -> dict:
    return {"doc_format": ONTOLOGY_DOC_FORMAT, "concepts": list(concepts)}


def _wide_grain(sql: str, task_id: str, ontology: dict) -> dict:
    document = to_lineage_dict(parse_scope_lineage(sql, task_id, schema=WIDE_SCHEMA))
    applied = apply_ontology(build_semantic_profile(document), ontology)
    return applied["output_shape"]["grain"]


def _unit_carrier(identifier: str, table: str, *, key_columns: Sequence[str] = ()) -> dict:
    """A table carrying the 投放单元 id, as an attribute unless it is keyed by it."""
    return _concept_entry(
        identifier,
        "投放单元" if key_columns else f"载体{identifier[-1]}",
        stem="unit" if key_columns else f"carrier_{identifier[-1]}",
        tables=[(table, "primary", "key:proven" if key_columns else "provisional", key_columns)],
        attributes=[("unit", "投放单元id", [(table, "unit_no")])],
    )


def test_grain_keys_that_name_the_same_thing_are_named_once() -> None:
    """Three keys, one business name: 「… × 投放单元id × 投放单元id × 投放单元id」 said nothing
    three times. The count of keys is what the reader loses, so the tail says it."""
    grain = _wide_grain(
        REPEAT_SQL,
        "task_unit_daily",
        _ontology_of(
            _unit_carrier("concept:table:a", "ods.unit_a"),
            _unit_carrier("concept:table:b", "ods.unit_b"),
            _unit_carrier("concept:table:c", "ods.unit_c"),
        ),
    )

    assert grain["concept_text"] == "一行 = 投放单元id 等 3 列"


def test_the_concept_itself_wins_over_its_own_id_column() -> None:
    """`一个投放单元` and `投放单元id` are the same thing said twice, and only one of them
    is the concept. The other keys' id columns fold into it rather than repeating it."""
    grain = _wide_grain(
        REPEAT_SQL,
        "task_unit_daily",
        _ontology_of(
            _unit_carrier("concept:unit", "ods.unit_a", key_columns=["unit_no"]),
            _unit_carrier("concept:table:b", "ods.unit_b"),
            _unit_carrier("concept:table:c", "ods.unit_c"),
        ),
    )

    assert grain["concept_text"] == "一行 = 一个投放单元 等 3 列"


def test_a_wide_grain_is_capped_and_says_how_many_keys_it_left_out() -> None:
    grain = _wide_grain(
        WIDE_SQL,
        "task_wide_daily",
        _ontology_of(
            _concept_entry(
                "concept:wide",
                "宽表对象",
                stem="wide",
                tables=[("ods.wide_source", "primary", "provisional", [])],
                attributes=[
                    (f"k{index}", comment, [("ods.wide_source", f"k{index}")])
                    for index, comment in enumerate(WIDE_COMMENTS, start=1)
                ],
            )
        ),
    )

    assert grain["concept_text"] == (
        "一行 = 维度一 × 维度二 × 维度三 × 维度四 × 维度五 × 维度六 等 8 列"
    )


def test_a_grain_the_concept_layer_can_barely_place_is_left_unphrased() -> None:
    """One key of four is not a reading of the grain, it is a quarter of one."""
    grain = _wide_grain(
        PARTIAL_SQL,
        "task_partial_daily",
        _ontology_of(
            _concept_entry(
                "concept:wide",
                "宽表对象",
                stem="wide",
                tables=[("ods.wide_source", "primary", "provisional", [])],
                attributes=[("k1", "维度一", [("ods.wide_source", "k1")])],
            )
        ),
    )

    assert "concept_text" not in grain


def test_half_the_keys_placed_is_enough_to_phrase_the_grain() -> None:
    grain = _wide_grain(
        PARTIAL_SQL,
        "task_partial_daily",
        _ontology_of(
            _concept_entry(
                "concept:wide",
                "宽表对象",
                stem="wide",
                tables=[("ods.wide_source", "primary", "provisional", [])],
                attributes=[
                    ("k1", "维度一", [("ods.wide_source", "k1")]),
                    ("k2", "维度二", [("ods.wide_source", "k2")]),
                ],
            )
        ),
    )

    assert grain["concept_text"] == "一行 = 维度一 × 维度二 等 4 列"


def test_a_grain_key_outside_the_concept_layer_leaves_the_phrase_unwritten() -> None:
    grain = _described(
        "INSERT OVERWRITE TABLE mart.unmodelled SELECT k, count(1) AS n "
        "FROM ods.unmodelled_source GROUP BY k",
        "task_unmodelled",
    )["output_shape"]["grain"]

    assert "concept_text" not in grain


# ------------------------------------------------------------------------- semantic.md


def test_the_overview_lists_the_concepts_this_task_touches() -> None:
    markdown = render_semantic_markdown(_described())

    assert "- 涉及概念：客户（实体，写入：汇总）、消息发送（事件，汇总读取）" in markdown


def test_the_grain_line_uses_the_concept_phrasing() -> None:
    markdown = render_semantic_markdown(_described())

    assert "- 粒度：一行 = 一个客户 × 日期" in markdown


def test_the_field_table_gains_a_concept_column() -> None:
    markdown = render_semantic_markdown(_described())

    assert "| # | 字段 | 一句话语义 | 所属概念 |" in markdown
    assert "客户·键" in markdown
    assert "消息发送·dt" in markdown


def test_the_field_table_keeps_its_old_shape_without_an_ontology() -> None:
    markdown = render_semantic_markdown(_profile())

    assert "| # | 字段 | 一句话语义 |" in markdown
    assert "所属概念" not in markdown
    assert "涉及概念" not in markdown


# ---------------------------------------------------------------------- the two refusals


def test_an_older_ontology_document_is_refused_with_its_format_named() -> None:
    older = {**_ontology(), "doc_format": "ontology-json/1"}

    with pytest.raises(ValueError) as error:
        apply_ontology(_profile(), older)

    assert ONTOLOGY_DOC_FORMAT in str(error.value)
    assert "ontology-json/1" in str(error.value)


def test_without_an_ontology_the_documents_are_byte_for_byte_unchanged() -> None:
    profile = _profile()
    baseline = json.dumps(profile, ensure_ascii=False, sort_keys=False)
    markdown = render_semantic_markdown(profile)

    applied = apply_ontology(profile, None)

    assert json.dumps(applied, ensure_ascii=False, sort_keys=False) == baseline
    assert render_semantic_markdown(applied) == markdown


# ------------------------------------------------------------------------ the CLI, end to end


def _example_corpus(tmp_path: Path) -> Path:
    out = tmp_path / "artifacts"
    assert (
        main(
            [
                "parse",
                "--input-dir",
                str(EXAMPLES / "tasks"),
                "--schema",
                str(EXAMPLES / "metadata" / "schema_info.json"),
                "--schema-fallback",
                str(EXAMPLES / "metadata" / "subscription_account_snapshot" / "source_tables"),
                "--target-ddl-metadata",
                str(EXAMPLES / "metadata" / "target_tables"),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    return out


def test_describe_ontology_end_to_end_over_the_example_corpus(tmp_path: Path) -> None:
    artifacts = _example_corpus(tmp_path)
    ontology_dir = tmp_path / "ontology"
    assert main(["ontology", "--lineage", str(artifacts), "--out", str(ontology_dir)]) == 0

    described = tmp_path / "described"
    assert (
        main(
            [
                "describe",
                "--lineage",
                str(artifacts),
                "--out",
                str(described),
                "--ontology",
                str(ontology_dir / "ontology.json"),
            ]
        )
        == 0
    )

    profiles = sorted(described.rglob("semantic.json"))
    assert profiles
    documents = [json.loads(path.read_text(encoding="utf-8")) for path in profiles]
    statements = [
        statement for document in documents for statement in document["statements"]
    ]
    assert all("concepts" in statement["task"] for statement in statements)
    assert any(statement["task"]["concepts"] for statement in statements)
    assert any(
        item.get("concept") for statement in statements for item in statement["inputs"]
    )
    assert any(
        "涉及概念：" in path.read_text(encoding="utf-8")
        for path in described.rglob("semantic.md")
    )


def test_describe_refuses_an_ontology_of_the_wrong_format(tmp_path: Path, capsys) -> None:
    task_dir = tmp_path / "task_a"
    write_statement_documents(
        parse_scope_lineage(
            "INSERT INTO mart.t SELECT id FROM ods.users", "task_a", schema={"ods.users": ["id"]}
        ),
        task_dir,
    )
    older = tmp_path / "ontology.json"
    older.write_text(json.dumps({"doc_format": "ontology-json/1"}), encoding="utf-8")

    code = main(
        [
            "describe",
            "--lineage",
            str(task_dir / "lineage.json"),
            "--ontology",
            str(older),
        ]
    )

    assert code == 1
    assert ONTOLOGY_DOC_FORMAT in capsys.readouterr().err


def test_describe_without_the_flag_writes_what_it_always_wrote(tmp_path: Path) -> None:
    task_dir = tmp_path / "task_a"
    write_statement_documents(
        parse_scope_lineage(
            "INSERT INTO mart.t SELECT id FROM ods.users", "task_a", schema={"ods.users": ["id"]}
        ),
        task_dir,
    )

    assert main(["describe", "--lineage", str(task_dir / "lineage.json")]) == 0

    profile = json.loads((task_dir / "semantic.json").read_text(encoding="utf-8"))
    assert "concepts" not in profile["task"]
    assert "output_concept" not in profile["task"]
    assert all("concept" not in item for item in profile["inputs"])
