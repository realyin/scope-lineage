"""EXCEPT / INTERSECT are set operations too, and UNION's de-duplication is read correctly.

sqlglot models ``EXCEPT`` and ``INTERSECT`` as siblings of ``UNION`` under
``exp.SetOperation``; the builder only recognised ``exp.Union``, so both branches were
skipped and ROOT came out with zero columns, no edges and no gap (audit 1.1). Their
semantics also differ from UNION: only the left input supplies values; the right input
decides which left rows survive. The value lineage therefore follows the left input alone,
and the right input is reported as a ``set_operation_semantics_partial`` gap because its
row-membership effect is not modelled as a row condition.

UNION's de-duplication flag lives in ``args["distinct"]``; the builder read
``args["kind"]``, which is always ``None``, so every UNION was labelled ``UNION_ALL``
(audit 1.3). A flattened chain is labelled by the operator that produces its output: the
output is de-duplicated only when the outermost operator is. A de-duplicated inner chain
under a ``UNION ALL`` keeps its own nested set-operation scope instead of being flattened
into a label that would be wrong for one of the two.
"""

from __future__ import annotations

from scope_lineage.contract import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {
    "db.source_a": ["user_id", "dt"],
    "db.source_b": ["user_id", "dt"],
    "db.source_c": ["user_id", "dt"],
}

A = "SELECT user_id, dt FROM db.source_a"
B = "SELECT user_id, dt FROM db.source_b"
C = "SELECT user_id, dt FROM db.source_c"


def _lineage(sql: str) -> dict:
    return to_lineage_dict(parse_scope_lineage(sql, "t", schema=SCHEMA))


def _physical(lineage: dict, column: str) -> set[str]:
    for row in lineage["end_to_end_lineage"]:
        if row["column"] == column:
            return {source["table"] for source in row["physical_sources"]}
    raise AssertionError(f"no end-to-end row for {column}")


def _gaps(lineage: dict, gap_type: str) -> list[dict]:
    return [
        gap for gap in lineage["diagnostics"].get("lineage_fact_gaps") or []
        if gap["gap_type"] == gap_type
    ]


def _set_ops(lineage: dict) -> dict[str, str]:
    return {
        scope_id: scope["set_op"]
        for scope_id, scope in lineage["scopes"].items()
        if scope.get("set_op")
    }


# --- 3b: EXCEPT / INTERSECT ---------------------------------------------------------


def test_except_outputs_the_left_input_columns_with_left_only_values():
    lineage = _lineage(f"INSERT INTO db.target_tbl {A} EXCEPT {B}")

    assert [c["name"] for c in lineage["scopes"]["ROOT"]["columns"]] == ["user_id", "dt"]
    assert _physical(lineage, "user_id") == {"db.source_a"}
    assert _physical(lineage, "dt") == {"db.source_a"}
    assert _set_ops(lineage) == {"union:main": "EXCEPT"}


def test_intersect_outputs_the_left_input_columns_with_left_only_values():
    lineage = _lineage(f"INSERT INTO db.target_tbl {A} INTERSECT {B}")

    assert [c["name"] for c in lineage["scopes"]["ROOT"]["columns"]] == ["user_id", "dt"]
    assert _physical(lineage, "user_id") == {"db.source_a"}
    assert _set_ops(lineage) == {"union:main": "INTERSECT"}


def test_the_right_input_is_reported_as_an_unmodelled_row_membership_source():
    lineage = _lineage(f"INSERT INTO db.target_tbl {A} EXCEPT {B}")

    gaps = _gaps(lineage, "set_operation_semantics_partial")
    assert len(gaps) == 1
    evidence = gaps[0]["evidence_summary"]
    assert evidence["set_op"] == "EXCEPT"
    assert evidence["row_membership_branches"] == ["union:main:b02"]
    assert evidence["row_membership_tables"] == ["db.source_b"]
    # The right input still reaches the statement: the scope graph keeps its edge.
    assert "union:main:b02" in lineage["scopes"]["union:main"]["depends_on"]


def test_an_except_chain_keeps_only_the_first_input_as_the_value_source():
    lineage = _lineage(f"INSERT INTO db.target_tbl {A} EXCEPT {B} EXCEPT {C}")

    assert _physical(lineage, "user_id") == {"db.source_a"}
    evidence = _gaps(lineage, "set_operation_semantics_partial")[0]["evidence_summary"]
    assert evidence["row_membership_tables"] == ["db.source_b", "db.source_c"]


def test_a_union_on_the_left_of_except_still_supplies_both_branches_values():
    lineage = _lineage(f"INSERT INTO db.target_tbl {A} UNION ALL {B} EXCEPT {C}")

    assert _physical(lineage, "user_id") == {"db.source_a", "db.source_b"}
    ops = _set_ops(lineage)
    assert ops["union:main"] == "EXCEPT"
    assert ops["union:main:b01"] == "UNION_ALL"


def test_except_inside_a_cte_feeds_the_reader():
    lineage = _lineage(
        f"INSERT INTO db.target_tbl WITH k AS ({A} EXCEPT {B}) SELECT user_id, dt FROM k"
    )

    assert _physical(lineage, "user_id") == {"db.source_a"}
    assert _set_ops(lineage) == {"union:k": "EXCEPT"}


def _warning_types(lineage: dict) -> list[str]:
    return [warning["type"] for warning in lineage["diagnostics"].get("warnings") or []]


def test_except_against_the_same_table_is_not_a_duplicated_union_branch():
    # The set form of an anti-join; the UNION copy-paste warning does not apply.
    lineage = _lineage(
        "INSERT INTO db.target_tbl SELECT user_id, dt FROM db.source_a "
        "EXCEPT SELECT user_id, dt FROM db.source_a WHERE dt = '2026-01-01'"
    )

    assert "duplicate_table_in_union" not in _warning_types(lineage)


def test_union_all_of_the_same_table_still_warns():
    """Sentinel: the copy-paste warning still fires for UNION branches."""
    lineage = _lineage(
        "INSERT INTO db.target_tbl SELECT user_id, dt FROM db.source_a "
        "UNION ALL SELECT user_id, dt FROM db.source_a WHERE dt = '2026-01-01'"
    )

    assert "duplicate_table_in_union" in _warning_types(lineage)


def test_union_all_is_unchanged_and_reports_no_partial_gap():
    """Sentinel: the path EXCEPT now shares still merges every UNION ALL branch."""
    lineage = _lineage(f"INSERT INTO db.target_tbl {A} UNION ALL {B}")

    assert _physical(lineage, "user_id") == {"db.source_a", "db.source_b"}
    assert _set_ops(lineage) == {"union:main": "UNION_ALL"}
    assert _gaps(lineage, "set_operation_semantics_partial") == []


# --- 3g: UNION de-duplication label --------------------------------------------------


def test_a_distinct_union_is_labelled_union():
    lineage = _lineage(f"INSERT INTO db.target_tbl {A} UNION {B}")

    assert _set_ops(lineage) == {"union:main": "UNION"}
    alignment = lineage["scopes"]["union:main"]["union_branch_alignment"]
    assert alignment["set_op"] == "UNION"


def test_a_chain_ending_in_a_distinct_union_is_labelled_union_as_a_whole():
    # Union(Union(A, B, ALL), C, DISTINCT): the outer DISTINCT de-duplicates all three.
    lineage = _lineage(f"INSERT INTO db.target_tbl {A} UNION ALL {B} UNION {C}")

    assert _set_ops(lineage) == {"union:main": "UNION"}
    assert lineage["scopes"]["union:main"]["branches"] == [
        "union:main:b01", "union:main:b02", "union:main:b03",
    ]


def test_a_distinct_inner_chain_under_union_all_keeps_its_own_label():
    # Union(Union(A, B, DISTINCT), C, ALL): only A and B are de-duplicated.
    lineage = _lineage(f"INSERT INTO db.target_tbl {A} UNION {B} UNION ALL {C}")

    assert _set_ops(lineage) == {"union:main": "UNION_ALL", "union:main:b01": "UNION"}
    assert _physical(lineage, "user_id") == {"db.source_a", "db.source_b", "db.source_c"}


def test_a_union_all_chain_stays_flat_and_union_all():
    """Sentinel: a plain UNION ALL chain is still flattened into one scope."""
    lineage = _lineage(f"INSERT INTO db.target_tbl {A} UNION ALL {B} UNION ALL {C}")

    assert _set_ops(lineage) == {"union:main": "UNION_ALL"}
    assert len(lineage["scopes"]["union:main"]["branches"]) == 3
