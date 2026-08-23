"""Which columns a window used to group and order, told apart from what it computed.

`transform` records the strongest expression kind on a source's path, not the role that source
plays. `_TRANSFORM_PRIORITY` ranks WINDOW and AGGREGATE above DIRECT and EXPRESSION, and
`_trace_column` passes that dominant kind down every source branch — so a column reaching an
output through a window comes back labelled WINDOW whether it was the value being computed or
one of the keys deciding the grouping. The two are indistinguishable by design.

The consequence is not lost lineage; `value_sources` is complete and correct. The consequence is
that a reader cannot tell them apart, and twice now a window partitioned by many columns has been
filed as a P0 "the lineage was smeared across the whole table" — both times against right answers
(WINDOW-ROLE-001).

`window_context_sources` carries the grouping and ordering keys as a separate optional array, the
way `row_membership_sources` and `value_condition_sources` have carried their own kinds of
indirect dependency since 0.1.0. `value_sources` is deliberately left byte-identical: it is the
complete dependency set, which is what change-impact analysis needs, and a column can legitimately
appear in both arrays.
"""

from __future__ import annotations

from scope_lineage import parse_scope_lineage, to_lineage_dict
from scope_lineage.scope.task_lineage import parse_task_lineage

SCHEMA = {"ods.o": ["id", "amt", "dt"], "mart.t": ["id", "s", "m"]}

WINDOW_SQL = (
    "INSERT INTO mart.t\n"
    "SELECT id, SUM(amt) OVER (PARTITION BY id ORDER BY dt) AS s FROM ods.o"
)


def _row(sql: str, column: str, schema=SCHEMA) -> dict:
    result = parse_task_lineage(sql, task_name="t", schema=schema)
    return next(
        item for item in result.end_to_end_lineage
        if item.get("table") == "mart.t" and item.get("column") == column
    )


def _context(row: dict) -> set[tuple[str, str, str]]:
    return {
        (c.get("table"), c.get("column"), c.get("role"))
        for c in row.get("window_context_sources") or []
    }


def _value_columns(row: dict) -> set[tuple[str, str]]:
    return {
        (s.get("table"), s.get("column"))
        for s in row.get("value_sources") or []
        if s.get("source_kind") == "physical_field"
    }


def test_a_windows_partition_and_order_keys_are_named_separately():
    row = _row(WINDOW_SQL, "s")

    assert _context(row) == {
        ("ods.o", "id", "partition"),
        ("ods.o", "dt", "order"),
    }


def test_the_value_argument_is_not_listed_as_context():
    """`amt` is what the window computes, not how it groups."""
    assert ("ods.o", "amt") not in {(t, c) for t, c, _r in _context(_row(WINDOW_SQL, "s"))}


def test_value_sources_still_carries_every_column_including_the_keys():
    """The complete dependency set is what change-impact analysis needs; it must not shrink."""
    assert _value_columns(_row(WINDOW_SQL, "s")) == {
        ("ods.o", "id"), ("ods.o", "amt"), ("ods.o", "dt"),
    }


def test_a_plain_group_by_has_no_window_context():
    """GROUP BY keys are not in value_sources either — there is nothing to separate."""
    sql = "INSERT INTO mart.t SELECT id, SUM(amt) AS m FROM ods.o GROUP BY id"

    assert _context(_row(sql, "m")) == set()


def test_an_expression_without_a_window_has_no_context():
    """Behaviour that must not change."""
    sql = "INSERT INTO mart.t SELECT id, CONCAT(amt, dt) AS s FROM ods.o"
    row = _row(sql, "s")

    assert not row.get("window_context_sources")
    assert _value_columns(row) == {("ods.o", "amt"), ("ods.o", "dt")}


def test_one_column_in_three_roles_stays_one_value_source():
    """The shape chosen precisely so the reported symptom — more rows — cannot get worse."""
    sql = (
        "INSERT INTO mart.t\n"
        "SELECT id, SUM(amt) OVER (PARTITION BY amt ORDER BY amt) AS s FROM ods.o"
    )
    row = _row(sql, "s")

    assert _value_columns(row) == {("ods.o", "amt")}
    assert _context(row) == {("ods.o", "amt", "partition"), ("ods.o", "amt", "order")}


def test_the_keys_survive_several_scopes_of_derivation():
    """The real shape: a window deep inside, its keys reached through two more scopes."""
    sql = (
        "INSERT INTO mart.t\n"
        "SELECT id, date_add(dt, rn) AS s FROM (\n"
        "  SELECT id, dt, row_number() OVER (PARTITION BY id ORDER BY dt) AS rn FROM ods.o\n"
        ") x"
    )
    row = _row(sql, "s")

    assert ("ods.o", "id", "partition") in _context(row)


def test_the_v1_document_carries_it_too():
    """lineage.json is what the CLI writes; leaving it out would change nothing for most users."""
    result = parse_scope_lineage(WINDOW_SQL, "t", schema=SCHEMA)
    document = to_lineage_dict(result)
    row = next(i for i in document["end_to_end_lineage"] if i["column"] == "s")

    assert {(c["table"], c["column"], c["role"]) for c in row["window_context_sources"]} == {
        ("ods.o", "id", "partition"),
        ("ods.o", "dt", "order"),
    }


def test_a_column_can_be_context_and_value_input_at_once():
    """`ORDER BY dt` and `date_add(dt, …)` are both true of the same column.

    So `value_sources - window_context_sources` is NOT the recipe for "what computes the value".
    Subtracting by column name would answer "nothing" when one field participates in both
    roles, which is a worse answer than the one being complained
    about. The array says which role a column played; it does not claim the column played only
    that role.
    """
    sql = (
        "INSERT INTO mart.t\n"
        "SELECT id, date_add(dt, rn) AS s FROM (\n"
        "  SELECT id, dt, row_number() OVER (PARTITION BY id ORDER BY dt) AS rn FROM ods.o\n"
        ") x"
    )
    row = _row(sql, "s")

    assert ("ods.o", "dt", "order") in _context(row), "dt orders the window"
    assert ("ods.o", "dt") in _value_columns(row), "and dt is also fed to date_add"
