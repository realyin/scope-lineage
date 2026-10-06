"""A join on a row set with no physical column still names its physical key.

Two claims about a lookup on a constant row set (an inline VALUES dictionary, a
``count(*)`` column, a constant column, ...):

1. **The join rule keeps the physical side's key.** The rule's ``fields`` are the
   physical endpoints of the key pairs. They were collected only inside the cross product
   of both sides, so when one side pierced to nothing the other side's key was dropped as
   well and the rule named no column at all. ``physical_key_pairs`` still lists only pairs
   with a physical column on both sides.
2. **A field read through such lookups publishes ``lookup_keys``.** Its value comes from a
   constant row set, so it has no physical source; the physical column that decides which
   row it reads is the join key on the left, found by walking left through every join
   whose sides pierce to nothing (``a.status = b.src``, then ``b.dst = c.code``).

Every fixture is synthetic.
"""

from __future__ import annotations

from scope_lineage import build_semantic_profile
from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {
    "src.t_a": ["id", "status", "n"],
    "src.t_b": ["id", "status", "label"],
    "dim.t_dict": ["code", "label"],
    "dw.t_out": ["id", "status_label"],
}

DICT_VALUES = (
    "WITH dict AS ("
    " SELECT * FROM VALUES ('k1', 'TypeA', '0', 'Zero'), ('k2', 'TypeA', '1', 'One'),"
    " ('k3', 'TypeB', '0', 'Nil') AS t(id, kind, code, label)) "
)
DICT_UNION = (
    "WITH dict AS ("
    " SELECT 'k1' AS id, 'TypeA' AS kind, '0' AS code, 'Zero' AS label"
    " UNION ALL SELECT 'k2', 'TypeA', '1', 'One'"
    " UNION ALL SELECT 'k3', 'TypeB', '0', 'Nil') "
)
READ_DICT = (
    "INSERT OVERWRITE TABLE dw.t_out "
    "SELECT a.id, g.label AS status_label FROM src.t_a a "
    "LEFT JOIN dict g ON a.status = g.code AND g.kind = 'TypeA'"
)
TWO_HOPS = """WITH mapping AS (
  SELECT * FROM VALUES ('S', '0', 'M0'), ('S', '1', 'M1') AS t(mtype, src, dst)),
dict AS (SELECT * FROM VALUES ('M0', 'Zero'), ('M1', 'One') AS t(code, label))
INSERT OVERWRITE TABLE dw.t_out
SELECT a.id, coalesce(c.label, '') AS status_label FROM src.t_a a
LEFT JOIN (SELECT * FROM mapping WHERE mtype = 'S') b ON a.status = b.src
LEFT JOIN dict c ON b.dst = c.code"""


def _profile(sql: str) -> dict:
    return build_semantic_profile(to_lineage_dict(parse_scope_lineage(sql, "t", schema=SCHEMA)))


def _join_rules(profile: dict) -> list[dict]:
    return [rule for rule in profile["rules"] if rule["kind"] == "join_condition"]


def _field(profile: dict, column: str) -> dict:
    return next(item for item in profile["fields"] if item["column"] == column)


def _endpoints(rule: dict) -> list[tuple[str, str]]:
    return [(item["table"], item["column"]) for item in rule["fields"]]


def test_a_join_on_an_inline_dictionary_keeps_its_physical_key():
    for head in (DICT_VALUES, DICT_UNION):
        (rule,) = _join_rules(_profile(head + READ_DICT))
        assert _endpoints(rule) == [("src.t_a", "status")]
        assert rule["physical_key_pairs"] == []


def test_the_stage_join_action_names_the_same_key():
    profile = _profile(DICT_VALUES + READ_DICT)
    (join,) = [
        action
        for stage in profile["stages"]
        for action in stage["actions"]
        if action["type"] == "join"
    ]
    assert [(item["table"], item["column"]) for item in join["fields"]] == [
        ("src.t_a", "status")
    ]


def test_a_join_on_a_grouped_count_keeps_its_physical_key_and_its_verdict():
    sql = (
        "INSERT OVERWRITE TABLE dw.t_out SELECT a.id, r.k AS status_label FROM src.t_a a "
        "LEFT JOIN (SELECT count(*) AS k FROM src.t_b GROUP BY status) r ON a.n = r.k"
    )
    profile = _profile(sql)
    (rule,) = _join_rules(profile)
    assert ("src.t_a", "n") in _endpoints(rule)
    risks = profile["output_shape"]["fan_out_risks"]
    assert [item["status"] for item in risks] == ["risk"]


def test_a_join_between_two_physical_tables_is_unchanged():
    sql = (
        "INSERT OVERWRITE TABLE dw.t_out SELECT a.id, d.label AS status_label "
        "FROM src.t_a a LEFT JOIN dim.t_dict d ON a.status = d.code"
    )
    profile = _profile(sql)
    (rule,) = _join_rules(profile)
    assert _endpoints(rule) == [("src.t_a", "status"), ("dim.t_dict", "code")]
    assert "lookup_keys" not in _field(profile, "status_label")


def test_a_field_read_from_a_dictionary_names_its_lookup_key():
    profile = _profile(DICT_VALUES + READ_DICT)
    assert _field(profile, "status_label")["lookup_keys"] == ["src.t_a.status"]
    assert "lookup_keys" not in _field(profile, "id")


def test_a_two_hop_lookup_walks_back_to_the_physical_key():
    profile = _profile(TWO_HOPS)
    assert _field(profile, "status_label")["lookup_keys"] == ["src.t_a.status"]
    # The second hop has no physical column on either side; it stays empty.
    second = next(rule for rule in _join_rules(profile) if "dst" in rule["expression"])
    assert second["fields"] == []
