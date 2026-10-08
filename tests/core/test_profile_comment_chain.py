"""A field's ``sql_comments`` follow its own value up the chain, not its inputs' (G3).

``fields[].sql_comments`` collected the comment of every step on the mapping chain. A
step that *computes* the value -- ``if(coalesce(d, '') <> '', true, false)`` turns a
date into a flag -- has inputs that are another quantity, and their comments described
that quantity, not this column. The walk now starts from the chain's last step and goes
upstream only through steps that keep the value: a pass-through (direct projection,
UNION) or a cleaning IF / CASE / COALESCE whose every value position is the step's one
input column or a literal. A computing step's own comment is kept; its inputs' are not.
CAST and TRIM are not cleaning: a comment would rather be missing than misplaced.

Every fixture is synthetic.
"""

from __future__ import annotations

from scope_lineage import build_semantic_profile
from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {
    "demo.src": ["ts", "code", "a", "b", "n"],
    "demo.tgt": ["flag", "cleaned", "k", "picked", "cast_n"],
}

SQL = """insert overwrite table demo.tgt
select flag, cleaned, k, picked, cast_n
from (
  select if(coalesce(d, '') <> '', true, false) as flag
        ,if(c = '', null, c)                     as cleaned
        ,concat(a1, b1)                          as k
        ,case when c is null then 'none' else c end as picked
        ,cast(n1 as string)                      as cast_n
  from (
    select date_format(s.ts, 'yyyy-MM-dd') as d   -- note on d
          ,s.code                          as c   -- note on c
          ,s.a                             as a1  -- note on a
          ,s.b                             as b1
          ,s.n                             as n1  -- note on n
    from demo.src s
  ) x
) y
"""


def _comments() -> dict[str, list[str] | None]:
    document = to_lineage_dict(parse_scope_lineage(SQL, "t", schema=SCHEMA))
    profile = build_semantic_profile(document)
    return {field["column"]: field.get("sql_comments") for field in profile["fields"]}


def test_a_computed_flag_does_not_carry_its_inputs_comment():
    assert _comments()["flag"] is None


def test_a_cleaning_if_keeps_the_comment_of_the_value_it_cleans():
    assert _comments()["cleaned"] == ["note on c"]


def test_a_cleaning_case_keeps_the_comment_of_the_value_it_cleans():
    assert _comments()["picked"] == ["note on c"]


def test_a_concat_does_not_carry_an_inputs_comment():
    assert _comments()["k"] is None


def test_a_cast_is_not_cleaning_and_stops_the_walk():
    assert _comments()["cast_n"] is None


def test_a_comment_on_the_computing_step_itself_is_kept():
    sql = """insert overwrite table demo.tgt
select k, k as picked, k as cleaned, k as flag, k as cast_n
from (
  select concat(s.a, s.b) as k -- the joined key
  from demo.src s
) x
"""
    document = to_lineage_dict(parse_scope_lineage(sql, "t", schema=SCHEMA))
    fields = {f["column"]: f for f in build_semantic_profile(document)["fields"]}
    assert fields["k"].get("sql_comments") == ["the joined key"]
