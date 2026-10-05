"""MERGE facts the statement contract publishes beyond its output columns.

Two claims, both about facts sqlglot's tree holds and the contract used to drop:

1. **An assignment's comment reaches ``outputs[].comments``.** A SELECT projection's
   comment is stamped on the columns it produces; a MERGE ``UPDATE SET`` assignment and an
   ``INSERT (...) VALUES (...)`` value are the MERGE equivalent and used to publish no
   comment at all -- the note survived only inside the rendered expression text.
2. **``merge_spec`` carries the ON and WHEN conditions.** Which target column each source
   column is merged on, and the condition each WHEN clause adds, are what decide whether a
   row is updated, inserted or left alone. The contract kept only flattened column lists
   (no pairing, no ON/WHEN attribution, no literals), so a reader had to go back to the SQL.

Every fixture is synthetic.
"""

from __future__ import annotations

from scope_lineage.contract import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {
    "dw.ev_tgt": ["k", "v", "w", "dt"],
    "ods.ev_src": ["k", "v", "w", "dt"],
}

COMMENTED_MERGE = """MERGE INTO dw.ev_tgt target
USING (SELECT k, v, w FROM ods.ev_src) source
ON target.k = source.k
WHEN MATCHED THEN UPDATE SET target.v = source.v / 1000 /* 备注 */, target.w = source.w -- 尾注
WHEN NOT MATCHED THEN INSERT (k, v, w) VALUES (source.k, source.v /* 插入注 */, source.w)
"""

CONDITIONED_MERGE = """MERGE INTO dw.ev_tgt target
USING (SELECT k, v, w, dt FROM ods.ev_src) source
ON target.k = source.k AND source.dt = '20260101'
WHEN MATCHED AND target.dt = '20260101' THEN UPDATE SET target.v = source.v
WHEN NOT MATCHED THEN INSERT *
WHEN NOT MATCHED BY SOURCE THEN DELETE
"""


def _document(sql: str, **kwargs) -> dict:
    return to_lineage_dict(parse_scope_lineage(sql, "merge_facts", schema=SCHEMA, **kwargs))


def _root_outputs(document: dict) -> dict[tuple[int, str], dict]:
    return {
        (item["merge_when_index"], item["name"]): item
        for item in document["scopes"]["ROOT"]["outputs"]
    }


# --- 1. assignment comments ---------------------------------------------------------


def test_an_update_set_assignment_comment_reaches_its_output() -> None:
    outputs = _root_outputs(_document(COMMENTED_MERGE))
    assert outputs[(0, "v")].get("comments") == ["备注"]


def test_a_trailing_line_comment_after_the_last_assignment_reaches_its_output() -> None:
    outputs = _root_outputs(_document(COMMENTED_MERGE))
    assert outputs[(0, "w")].get("comments") == ["尾注"]


def test_an_insert_values_comment_reaches_its_output() -> None:
    outputs = _root_outputs(_document(COMMENTED_MERGE))
    assert outputs[(1, "v")].get("comments") == ["插入注"]


def test_an_assignment_without_a_comment_still_omits_the_key() -> None:
    outputs = _root_outputs(_document(COMMENTED_MERGE))
    assert "comments" not in outputs[(1, "k")]
    assert "comments" not in outputs[(1, "w")]


def test_stripping_removes_the_assignment_comments_too() -> None:
    document = _document(COMMENTED_MERGE, strip_comments=True)
    assert all("comments" not in item for item in document["scopes"]["ROOT"]["outputs"])
