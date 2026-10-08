"""``nullable_by_join`` decided per UNION branch, and the branch numbers its readers get (M2).

A mapping chain through a UNION lists every branch's steps in one ``ordered_steps``.
``_nullable_by_join`` used to walk that list as one straight line: a COALESCE in branch 1
was not "after" branch 2's nullable step, so the whole column was flagged (scope form),
and the physical-table form asked every branch's tables to sit on a nullable side, so a
column nullable in one branch only was missed. Now the chain is split at the UNION and
every branch is judged alone:

- ``nullable_by_join`` is true when **at least one** branch can be proven nullable;
- ``nullable_by_join_branches`` lists those branches when they are not all of them,
  numbered as ``merge.union_branches[].branch`` is (the UNION scope's inputs in order);
- the summary, a metric card's ``null_handling`` and a MERGE's matched-UPDATE facts all
  carry the branch numbers (``update_nullable_by_join`` keeps only columns every branch
  may blank, ``update_nullable_by_join_branches`` holds the rest);
- M2b: ``update_filled_on_miss`` names a matched-UPDATE column a branch fills with a
  literal right after the LEFT JOIN that may miss (``coalesce(j.x, '')``) -- an unmatched
  key overwrites the old value with that literal, the same risk as a NULL.

Every fixture is synthetic.
"""

from __future__ import annotations

import json

from scope_lineage import build_semantic_profile
from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.metadata.schema_metadata import load_schema
from scope_lineage.render import semantic_markdown
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {
    "dw.t_m": ["k", "x", "y"],
    "ods.s1": ["k", "y"],
    "ods.s2": ["k", "y"],
    "ods.j1": ["k", "x", "y"],
    "ods.j2": ["k", "x", "y"],
}


def _profile(sql: str, schema=SCHEMA) -> dict:
    return build_semantic_profile(to_lineage_dict(parse_scope_lineage(sql, "t", schema=schema)))


def _fields(profile: dict) -> dict[str, dict]:
    return {field["column"]: field for field in profile["fields"]}


def _merge(profile: dict) -> dict:
    return profile["output_shape"]["merge"]


SCOPE_FORM = """MERGE INTO dw.t_m AS tgt
USING (
  SELECT a.k, coalesce(j.x, '') AS x FROM ods.s1 a LEFT JOIN (SELECT k, x FROM ods.j1) j ON a.k = j.k
  UNION ALL
  SELECT b.k, j2.x AS x FROM ods.s2 b LEFT JOIN (SELECT k, x FROM ods.j2) j2 ON b.k = j2.k
) src
ON tgt.k = src.k
WHEN MATCHED THEN UPDATE SET tgt.x = src.x
WHEN NOT MATCHED THEN INSERT *"""

TABLE_FORM = """MERGE INTO dw.t_m AS tgt
USING (
  SELECT a.k, coalesce(j.x, '') AS x, j.y AS y FROM ods.s1 a LEFT JOIN ods.j1 j ON a.k = j.k
  UNION ALL
  SELECT b.k, j2.x AS x, b.y AS y FROM ods.s2 b LEFT JOIN ods.j2 j2 ON b.k = j2.k
) src
ON tgt.k = src.k
WHEN MATCHED THEN UPDATE SET tgt.x = src.x, tgt.y = src.y
WHEN NOT MATCHED THEN INSERT *"""

LINEAR = """MERGE INTO dw.t_m AS tgt
USING (SELECT a.k, coalesce(j.x, '') AS x, j.y AS y FROM ods.s1 a LEFT JOIN ods.j1 j ON a.k = j.k) src
ON tgt.k = src.k
WHEN MATCHED THEN UPDATE SET tgt.x = src.x, tgt.y = src.y
WHEN NOT MATCHED THEN INSERT *"""


# --- the field flag and its branches ----------------------------------------------


def test_scope_form_names_the_one_branch_that_may_be_null():
    profile = _profile(SCOPE_FORM)
    field = _fields(profile)["x"]
    assert field["nullable_by_join"] is True
    assert field["nullable_by_join_branches"] == [2]
    assert "（UNION 分支 2 关联未命中时为空）" in field["summary"]
    assert "（关联未命中时为空）" not in field["summary"]


def test_table_form_no_longer_misses_a_branch_that_may_be_null():
    fields = _fields(_profile(TABLE_FORM))
    assert fields["y"]["nullable_by_join"] is True
    assert fields["y"]["nullable_by_join_branches"] == [1]
    assert fields["x"]["nullable_by_join_branches"] == [2]


def test_every_branch_nullable_is_the_whole_column_without_branch_numbers():
    sql = """MERGE INTO dw.t_m AS tgt
USING (
  SELECT a.k, j.x AS x FROM ods.s1 a LEFT JOIN (SELECT k, x FROM ods.j1) j ON a.k = j.k
  UNION ALL
  SELECT b.k, j2.x AS x FROM ods.s2 b LEFT JOIN (SELECT k, x FROM ods.j2) j2 ON b.k = j2.k
) src
ON tgt.k = src.k
WHEN MATCHED THEN UPDATE SET tgt.x = src.x
WHEN NOT MATCHED THEN INSERT *"""
    profile = _profile(sql)
    field = _fields(profile)["x"]
    assert field["nullable_by_join"] is True
    assert "nullable_by_join_branches" not in field
    assert field["summary"].endswith("（关联未命中时为空）")
    assert _merge(profile)["update_nullable_by_join"] == ["x"]
    assert "update_nullable_by_join_branches" not in _merge(profile)


def test_the_branch_key_sits_right_after_the_flag():
    keys = list(_fields(_profile(SCOPE_FORM))["x"])
    assert keys.index("nullable_by_join_branches") == keys.index("nullable_by_join") + 1


def test_a_chain_without_a_union_is_unchanged():
    profile = _profile(LINEAR)
    fields = _fields(profile)
    assert fields["y"]["nullable_by_join"] is True
    assert "nullable_by_join_branches" not in fields["y"]
    assert "nullable_by_join" not in fields["x"]
    assert _merge(profile)["update_nullable_by_join"] == ["y"]


def test_branch_numbers_follow_the_union_scopes_inputs():
    profile = _profile(SCOPE_FORM)
    using = profile["output_shape"]["merge"]
    branches = {item["branch"]: item["scope"] for item in using.get("union_branches") or []}
    field = _fields(profile)["x"]
    assert field["nullable_by_join_branches"] == [2]
    assert set(branches) == {1, 2}


# --- a MERGE's matched UPDATE -------------------------------------------------------


def test_a_partly_nullable_update_column_moves_to_the_branch_list():
    merge = _merge(_profile(SCOPE_FORM))
    assert "update_nullable_by_join" not in merge
    assert merge["update_nullable_by_join_branches"] == {"x": [2]}


def test_the_table_form_lists_both_partly_nullable_columns():
    merge = _merge(_profile(TABLE_FORM))
    assert "update_nullable_by_join" not in merge
    assert merge["update_nullable_by_join_branches"] == {"x": [2], "y": [1]}


def test_a_branch_filling_the_missing_value_is_named_with_the_value():
    merge = _merge(_profile(SCOPE_FORM))
    assert merge["update_filled_on_miss"] == [{"column": "x", "value": "''", "branches": [1]}]


def test_a_fill_without_a_union_has_no_branch_numbers():
    merge = _merge(_profile(LINEAR))
    assert merge["update_filled_on_miss"] == [{"column": "x", "value": "''"}]


def test_a_fill_from_the_targets_own_column_is_not_a_fill_on_miss():
    sql = """MERGE INTO dw.t_m AS tgt
USING (SELECT a.k, j.x AS x FROM ods.s1 a LEFT JOIN ods.j1 j ON a.k = j.k) src
ON tgt.k = src.k
WHEN MATCHED THEN UPDATE SET tgt.x = coalesce(src.x, tgt.x)
WHEN NOT MATCHED THEN INSERT *"""
    merge = _merge(_profile(sql))
    assert "update_filled_on_miss" not in merge
    assert "update_nullable_by_join" not in merge


def test_the_merge_keys_new_entries_keep_their_order():
    merge = _merge(_profile(SCOPE_FORM))
    keys = list(merge)
    assert keys.index("whens") < keys.index("update_nullable_by_join_branches")
    assert keys.index("update_nullable_by_join_branches") < keys.index("update_filled_on_miss")


# --- a metric card ------------------------------------------------------------------

TYPED = {
    "tables": [
        {
            "table_name": name,
            "schema": [
                {"columnName": "k", "columnType": "string", "columnIndex": 0},
                {"columnName": "ts", "columnType": "timestamp", "columnIndex": 1},
            ],
        }
        for name in ("ods.s1", "ods.s2", "ods.j1", "dw.ev")
    ]
}

METRIC = """INSERT OVERWRITE TABLE dw.ev
SELECT u.k, u.ts FROM (
  SELECT a.k, j.ts AS ts FROM ods.s1 a LEFT JOIN (SELECT k, ts FROM ods.j1) j ON a.k = j.k
  UNION ALL
  SELECT b.k, b.ts AS ts FROM ods.s2 b
) u"""


def _typed_profile(sql: str, tmp_path) -> dict:
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(TYPED), encoding="utf-8")
    return _profile(sql, schema=load_schema(str(path)))


def test_a_metric_card_says_which_branch_may_leave_it_empty(tmp_path):
    profile = _typed_profile(METRIC, tmp_path)
    field = _fields(profile)["ts"]
    handling = field["metric_spec"]["null_handling"]
    assert handling["nullable_by_join"] is True
    assert handling["nullable_by_join_branches"] == [1]
    rendered = semantic_markdown.render_semantic_markdown(profile)
    assert "UNION 分支 1 关联未命中时为空" in rendered


def test_the_semantic_markdown_never_says_the_whole_column_for_one_branch(tmp_path):
    rendered = semantic_markdown.render_semantic_markdown(_typed_profile(METRIC, tmp_path))
    assert "（关联未命中时为空）" not in rendered


def test_a_union_nested_in_a_branch_is_split_in_turn():
    sql = """INSERT OVERWRITE TABLE dw.t_m
SELECT s.k, s.x, s.y FROM (
  SELECT a.k, a.y AS x, a.y FROM ods.s1 a
  UNION ALL
  SELECT u.k, u.x, u.y FROM (
    SELECT b.k, j.x AS x, b.y FROM ods.s2 b LEFT JOIN (SELECT k, x FROM ods.j1) j ON b.k = j.k
    UNION ALL
    SELECT c.k, c.x AS x, c.y FROM ods.j2 c
  ) u
) s"""
    field = _fields(_profile(sql))["x"]
    assert field["nullable_by_join"] is True
    assert field["nullable_by_join_branches"] == [2]
