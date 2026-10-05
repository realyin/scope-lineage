"""A CASE / IF whose output nobody reads says so: ``consumed: false`` (#21-e).

``select a.raw as c from (select raw, if(raw is null, '', raw) as c from t) a`` computes
an IF the outer query never reads -- it takes the raw column under the same name. Copied
into a document, the IF reads as "NULL becomes an empty string", which the output never
sees. The rule is marked only when that is provable: the column has no downstream field,
no target column, and no scope reads it anywhere (a join key counts as a read), with no
``*`` reader in between. Every fixture is synthetic.
"""

from __future__ import annotations

from scope_lineage import build_semantic_profile
from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {"ods.x": ["k", "raw"], "ods.y": ["k", "c"], "dw.t": ["k", "c"]}


def _case_rule(sql: str) -> dict:
    profile = build_semantic_profile(
        to_lineage_dict(parse_scope_lineage(sql, "t", schema=SCHEMA))
    )
    (rule,) = [item for item in profile["rules"] if item["kind"] == "case_branch"]
    return rule


def test_an_if_the_outer_query_never_reads_is_marked_unconsumed():
    rule = _case_rule(
        "INSERT OVERWRITE TABLE dw.t SELECT a.k, a.raw AS c FROM ("
        "SELECT k, raw, if(raw IS NULL, '', raw) AS c FROM ods.x) a"
    )
    assert rule["consumed"] is False


def test_an_if_read_as_a_join_key_is_not_marked():
    rule = _case_rule(
        "INSERT OVERWRITE TABLE dw.t SELECT a.k, d.c FROM ("
        "SELECT k, raw, if(raw IS NULL, '', raw) AS c FROM ods.x) a "
        "JOIN ods.y d ON a.c = d.c"
    )
    assert "consumed" not in rule


def test_an_if_written_to_the_target_is_not_marked():
    rule = _case_rule(
        "INSERT OVERWRITE TABLE dw.t SELECT k, if(raw IS NULL, '', raw) AS c FROM ods.x"
    )
    assert "consumed" not in rule
