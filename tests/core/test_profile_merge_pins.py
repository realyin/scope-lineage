"""What a MERGE's matched branch pins on the target, and the USING side read from a
table its writer keys on more columns (M3, M4b).

1. **``merge.matched_target_pins``** (M3). ``WHEN MATCHED AND tgt.dt = '20260101'`` only
   updates the target rows of that one partition: same-key rows elsewhere are neither
   updated nor inserted again. The condition is parsed, and a top-level AND conjunct
   ``<target>.<column> = <literal or ${…}>`` pins that column. The target is named by
   its alias on ROOT's input edge, its full name or its short name. A range, a source
   column, an OR or a comparison with another column pins nothing; a column every
   matched branch does not pin to the same value is not published.
2. **``merge.using_writer_keys``** (M4b). A USING side that is a physical table's rows
   (``no_dedup``) can still hold one merge key twice when the statement writing that
   table keys its batch on more columns. The writer's batch keys are compared with the
   merge key's source columns, and the extra columns are named.

Every fixture is synthetic.
"""

from __future__ import annotations

from scope_lineage import build_semantic_profile
from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {
    "dw.m": ["k", "v", "dt"],
    "ods.src": ["k", "v", "dt"],
}


def _merge(when: str, target: str = "dw.m tgt") -> dict:
    sql = (
        f"MERGE INTO {target} USING (SELECT k, v, dt FROM ods.src) src ON tgt.k = src.k "
        f"{when} WHEN NOT MATCHED THEN INSERT *"
    )
    document = to_lineage_dict(parse_scope_lineage(sql, "t", schema=SCHEMA))
    return build_semantic_profile(document)["output_shape"]["merge"]


# --- M3 -------------------------------------------------------------------------------


def test_a_matched_condition_pinning_the_target_column_is_published():
    merge = _merge("WHEN MATCHED AND tgt.dt = '20260101' THEN UPDATE SET tgt.v = src.v")
    assert merge["matched_target_pins"] == {"dt": "'20260101'"}


def test_a_scheduler_parameter_pins_too_beside_another_conjunct():
    merge = _merge("WHEN MATCHED AND tgt.dt = '${bizdate}' AND tgt.v > 0 THEN UPDATE SET tgt.v = src.v")
    assert merge["matched_target_pins"] == {"dt": "'${bizdate}'"}


def test_the_target_named_by_its_short_name_pins():
    merge = _merge("WHEN MATCHED AND m.dt = '20260101' THEN UPDATE SET v = src.v", target="dw.m")
    assert merge["matched_target_pins"] == {"dt": "'20260101'"}


def test_a_range_pins_nothing():
    merge = _merge("WHEN MATCHED AND tgt.dt >= '20260101' THEN UPDATE SET tgt.v = src.v")
    assert "matched_target_pins" not in merge


def test_a_source_column_pins_nothing():
    merge = _merge("WHEN MATCHED AND src.dt = '20260101' THEN UPDATE SET tgt.v = src.v")
    assert "matched_target_pins" not in merge


def test_an_or_pins_nothing():
    merge = _merge(
        "WHEN MATCHED AND (tgt.dt = '20260101' OR tgt.v = 2) THEN UPDATE SET tgt.v = src.v"
    )
    assert "matched_target_pins" not in merge


def test_a_comparison_with_another_column_pins_nothing():
    merge = _merge("WHEN MATCHED AND tgt.dt = src.dt THEN UPDATE SET tgt.v = src.v")
    assert "matched_target_pins" not in merge


def test_a_second_matched_branch_without_the_pin_drops_it():
    merge = _merge(
        "WHEN MATCHED AND tgt.dt = '20260101' THEN UPDATE SET tgt.v = src.v "
        "WHEN MATCHED THEN DELETE"
    )
    assert "matched_target_pins" not in merge


def test_the_pins_sit_right_after_the_whens():
    keys = list(_merge("WHEN MATCHED AND tgt.dt = '20260101' THEN UPDATE SET tgt.v = src.v"))
    assert keys.index("matched_target_pins") == keys.index("whens") + 1
