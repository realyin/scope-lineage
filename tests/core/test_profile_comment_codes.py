"""A string literal compared with a column whose comment lists other codes (G7a).

``role = 'z9'`` where the column comment reads 「角色；a1-甲,b2-乙,c3-丙」: the literal is
not among the codes the comment lists, so either the comment is stale or the condition
may never hold. The profile now says so as ``literal_outside_comment_codes`` (warn), and
the packet carries it. Four guards keep it quiet where the comment cannot decide:

- the literal is one of the codes;
- the literal appears in the comment as a substring (a short code glued to its meaning,
  ``EXT外部``, is not read as a code by the shape reading; a long constant one such as
  ``XY_LONG外部`` is, and is listed);
- every ``【…】`` block is removed before the codes are read, so an annotation such as
  ``【updt:n】`` or a format note is never a code;
- a comment that is prose lists no codes at all.

Every fixture is synthetic.
"""

from __future__ import annotations

import json

from scope_lineage import build_semantic_profile
from scope_lineage.contract.lineage import to_lineage_dict
from scope_lineage.metadata.schema_metadata import load_schema
from scope_lineage.render.semantic_profile import FINDING_KINDS, FINDING_SEVERITY
from scope_lineage.scope.scope_builder import parse_scope_lineage
from scope_lineage.semantics.packet_notes import PACKET_FINDINGS

KIND = "literal_outside_comment_codes"


def _schema(comment: str) -> dict:
    return {
        "tables": [
            {
                "table_name": "ods.part",
                "schema": [
                    {"columnName": "k", "columnType": "string", "columnIndex": 0},
                    {"columnName": "role", "columnType": "string", "columnIndex": 1,
                     "columnComment": comment},
                ],
            },
            {
                "table_name": "dw.out",
                "schema": [{"columnName": "k", "columnType": "string", "columnIndex": 0}],
            },
        ]
    }


def _findings(comment: str, condition: str, tmp_path) -> list[dict]:
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(_schema(comment), ensure_ascii=False), encoding="utf-8")
    sql = f"INSERT OVERWRITE TABLE dw.out SELECT p.k FROM ods.part p WHERE {condition}"
    document = to_lineage_dict(parse_scope_lineage(sql, "t", schema=load_schema(str(path))))
    profile = build_semantic_profile(document)
    return [f for f in profile["confidence"]["findings"] if f["kind"] == KIND]


CODES = "角色；a1-甲,b2-乙,c3-丙"


def test_a_literal_outside_the_listed_codes_is_a_finding(tmp_path):
    (finding,) = _findings(CODES, "p.role = 'z9'", tmp_path)
    assert finding["severity"] == "warn"
    assert "'z9'" in finding["text"]
    assert "a1" in finding["text"] and "c3" in finding["text"]
    assert finding["evidence"]


def test_an_in_list_reports_only_the_literals_outside(tmp_path):
    (finding,) = _findings(CODES, "p.role IN ('a1', 'z9')", tmp_path)
    assert "'z9'" in finding["text"]
    assert "'a1'" not in finding["text"]


def test_a_listed_code_is_not_a_finding(tmp_path):
    assert _findings(CODES, "p.role = 'b2'", tmp_path) == []


def test_a_code_glued_to_its_meaning_is_found_as_a_substring(tmp_path):
    assert _findings("角色；a1-甲,b2-乙,XY_LONG外部", "p.role = 'XY_LONG'", tmp_path) == []


def test_a_short_code_glued_to_its_meaning_is_found_as_a_substring(tmp_path):
    assert _findings("角色；a1-甲,b2-乙,EXT外部", "p.role = 'EXT'", tmp_path) == []


def test_a_long_code_glued_to_its_meaning_is_listed(tmp_path):
    (finding,) = _findings("角色；a1-甲,b2-乙,XY_LONG_CODE外部", "p.role = 'z9'", tmp_path)
    assert "a1、b2、XY_LONG_CODE" in finding["text"]


def test_annotation_blocks_are_not_read_as_codes(tmp_path):
    assert _findings("状态【updt:n】【Sec:D】", "p.role = 'X'", tmp_path) == []


def test_a_format_annotation_block_is_removed_too(tmp_path):
    # Read as it stands, 【yyyy-MM-dd HH:mm:ss】 looks like two more codes beside a1.
    assert _findings("角色【yyyy-MM-dd HH:mm:ss】；a1-甲", "p.role = 'z9'", tmp_path) == []


def test_a_prose_comment_lists_no_codes(tmp_path):
    assert _findings("参与者的角色名称", "p.role = 'z9'", tmp_path) == []


def test_the_kind_is_registered_and_carried_by_the_packet():
    assert KIND in FINDING_KINDS
    assert FINDING_SEVERITY[KIND] == "warn"
    assert KIND in PACKET_FINDINGS
