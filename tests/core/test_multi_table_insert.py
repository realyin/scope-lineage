"""Hive's FROM-first multi-table insert is split into one INSERT per target.

``FROM src INSERT OVERWRITE TABLE t1 SELECT ... INSERT OVERWRITE TABLE t2 SELECT ...``
is not supported by sqlglot: the lenient parse dropped every INSERT clause and left
``SELECT * FROM src``, reported as an unsupported SELECT with no word about the targets
(audit 1.2). Each branch reads the shared FROM clause once, so the statement is rewritten
before parsing into ``INSERT ... SELECT <projection> FROM <shared FROM> <branch clauses>``
per target, with a ``multi_table_insert_split`` warning disclosing the rewrite. Statement
ids and the table state graph follow the split statements.

A branch that writes a table the shared FROM also reads cannot be split: Hive reads the
source once, while sequential INSERTs would read the first branch's output. That shape
gets a ``multi_table_insert_unsupported`` gap naming every target instead.
"""

from __future__ import annotations

from scope_lineage import parse_task_lineage, to_task_lineage_dict
from scope_lineage.scope.multi_insert import split_multi_table_inserts

SCHEMA = {"ods.src": ["a", "b", "k"], "ods.dim": ["k", "name"]}

TWO_TARGETS = (
    "FROM ods.src s\n"
    "INSERT OVERWRITE TABLE dw.t1 SELECT s.a\n"
    "INSERT OVERWRITE TABLE dw.t2 SELECT s.b"
)


def _task(sql: str) -> dict:
    return to_task_lineage_dict(parse_task_lineage(sql, "t", schema=SCHEMA))


def _sources(task: dict, table: str, column: str) -> set[tuple[str, str]]:
    for row in task["end_to_end_lineage"]:
        if row["table"] == table and row["column"] == column:
            return {
                (s["table"], s["column"])
                for s in row["value_sources"]
                if s["source_kind"] == "physical_field"
            }
    raise AssertionError(f"no lineage for {table}.{column}")


def _warning_types(task: dict) -> list[str]:
    return [w["type"] for w in task["diagnostics"]["warnings"]]


def _gaps(task: dict, gap_type: str) -> list[dict]:
    return [g for g in task["diagnostics"]["lineage_fact_gaps"] if g["gap_type"] == gap_type]


def test_each_target_of_a_multi_table_insert_gets_its_own_lineage():
    task = _task(TWO_TARGETS)

    assert [s["target_table"] for s in task["statement_sequence"]] == ["dw.t1", "dw.t2"]
    assert all(s["model_status"] == "modeled" for s in task["statement_sequence"])
    assert _sources(task, "dw.t1", "a") == {("ods.src", "a")}
    assert _sources(task, "dw.t2", "b") == {("ods.src", "b")}
    assert task["syntax_status"] == "strict_ok"
    assert "multi_table_insert_split" in _warning_types(task)
    assert "unsupported_statement" not in _warning_types(task)


def test_a_single_target_from_first_insert_is_modelled():
    task = _task("FROM ods.src s INSERT OVERWRITE TABLE dw.t1 SELECT s.a")

    assert _sources(task, "dw.t1", "a") == {("ods.src", "a")}


def test_each_branch_keeps_its_own_where_and_group_by_and_the_shared_join():
    task = _task(
        "FROM ods.src s JOIN ods.dim d ON s.k = d.k\n"
        "INSERT OVERWRITE TABLE dw.t1 PARTITION (dt = '2026-01-01') SELECT s.a, d.name WHERE s.b > 1\n"
        "INSERT INTO TABLE dw.t2 SELECT d.name, COUNT(1) AS n GROUP BY d.name"
    )

    assert _sources(task, "dw.t1", "name") == {("ods.dim", "name")}
    assert _sources(task, "dw.t2", "name") == {("ods.dim", "name")}
    first, second = (s["normalized_sql"] for s in task["statement_sequence"])
    assert "s.b > 1" in first and "s.b > 1" not in second
    assert "GROUP BY" in second and "GROUP BY" not in first


def test_a_trailing_comment_in_a_branch_does_not_swallow_the_shared_from():
    task = _task(
        "FROM ods.src s -- the shared source\n"
        "INSERT OVERWRITE TABLE dw.t1 PARTITION (dt = '${bizdate}')\n"
        "SELECT s.a -- first target\n"
        "WHERE s.b > 1\n"
        "INSERT OVERWRITE TABLE dw.t2 SELECT s.b -- second target"
    )

    assert _sources(task, "dw.t1", "a") == {("ods.src", "a")}
    assert _sources(task, "dw.t2", "b") == {("ods.src", "b")}


def test_statement_ids_and_states_follow_the_split():
    task = _task(TWO_TARGETS + ";\nINSERT OVERWRITE TABLE dw.t3 SELECT a FROM dw.t1")

    ids = [(s["statement_id"], s["target_table"]) for s in task["statement_sequence"]]
    assert ids == [("stmt:001", "dw.t1"), ("stmt:002", "dw.t2"), ("stmt:003", "dw.t3")]
    t3 = next(s for s in task["statement_sequence"] if s["target_table"] == "dw.t3")
    edges = task["table_state_graph"]["edges"]
    t1_writer = next(e for e in edges if e["to"] == "state:dw.t1:001")
    assert t1_writer["statement_id"] == "stmt:001"
    assert t3["model_status"] == "modeled"
    t3_row = next(r for r in task["end_to_end_lineage"] if r["table"] == "dw.t3")
    read = [s for s in t3_row["value_sources"] if s["source_kind"] == "physical_field"]
    assert [(s["table"], s["source_state"]) for s in read] == [("dw.t1", "state:dw.t1:001")]


def test_a_target_the_shared_from_also_reads_is_reported_not_split():
    task = _task(
        "FROM dw.t1 s\n"
        "INSERT OVERWRITE TABLE dw.t1 SELECT s.a\n"
        "INSERT OVERWRITE TABLE dw.t2 SELECT s.b"
    )

    gaps = _gaps(task, "multi_table_insert_unsupported")
    assert len(gaps) == 1
    assert gaps[0]["targets"] == ["dw.t1", "dw.t2"]
    assert gaps[0]["root_impact"] is True
    assert "multi_table_insert_split" not in _warning_types(task)


def test_line_numbers_of_later_statements_do_not_move():
    sql = TWO_TARGETS + ";\nSELECT 1;\nINSERT INTO dw.t3 SELECT a FROM ods.src"
    rewritten, splits = split_multi_table_inserts(sql)

    assert len(splits) == 1 and splits[0].targets == ["dw.t1", "dw.t2"]
    assert rewritten.count("\n") == sql.count("\n")
    assert rewritten.splitlines()[-1] == sql.splitlines()[-1]


def test_an_ordinary_script_is_left_byte_identical():
    """Sentinel: no FROM-first statement, no rewrite -- including FROM inside a string."""
    sql = (
        "INSERT OVERWRITE TABLE dw.t1 SELECT 'FROM x INSERT INTO y SELECT 1' AS a FROM ods.src;\n"
        "-- FROM ods.src INSERT INTO dw.t9 SELECT 1\n"
        "INSERT INTO dw.t2 SELECT b FROM ods.src"
    )
    rewritten, splits = split_multi_table_inserts(sql)

    assert rewritten == sql
    assert splits == []
