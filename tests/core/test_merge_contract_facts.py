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

import jsonschema
import pytest

from scope_lineage import parse_task_lineage
from scope_lineage.contract import to_lineage_dict
from scope_lineage.contract.task_lineage import to_task_lineage_dict
from scope_lineage.contract.validation import validate_lineage_document
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


# --- 2. merge_spec --------------------------------------------------------------------


def test_merge_spec_pairs_each_on_equality_target_with_source() -> None:
    spec = _document(CONDITIONED_MERGE)["merge_spec"]
    assert spec["key_pairs"] == [{"target": "k", "source": "k"}]


def test_a_pair_written_source_first_is_still_read_target_then_source() -> None:
    sql = CONDITIONED_MERGE.replace("ON target.k = source.k", "ON source.k = target.k")
    spec = _document(sql)["merge_spec"]
    assert spec["key_pairs"] == [{"target": "k", "source": "k"}]


def test_a_renamed_pair_keeps_both_names() -> None:
    sql = (
        "MERGE INTO dw.ev_tgt t USING ods.ev_src s ON t.k = s.v "
        "WHEN MATCHED THEN UPDATE SET t.w = s.w"
    )
    spec = _document(sql)["merge_spec"]
    assert spec["key_pairs"] == [{"target": "k", "source": "v"}]


def test_an_on_conjunct_that_is_not_a_column_pair_is_kept_as_written() -> None:
    spec = _document(CONDITIONED_MERGE)["merge_spec"]
    assert len(spec["other_on_conditions"]) == 1
    assert "'20260101'" in spec["other_on_conditions"][0]
    assert "dt" in spec["other_on_conditions"][0]


def test_the_whole_on_condition_is_published_verbatim() -> None:
    spec = _document(CONDITIONED_MERGE)["merge_spec"]
    assert "k" in spec["on"] and "'20260101'" in spec["on"]


def test_each_when_clause_keeps_its_kind_condition_and_action() -> None:
    whens = _document(CONDITIONED_MERGE)["merge_spec"]["whens"]
    assert [(w["index"], w["clause"], w["action"], w["star"]) for w in whens] == [
        (0, "matched", "update", False),
        (1, "not_matched", "insert", True),
        (2, "not_matched_by_source", "delete", False),
    ]
    assert "'20260101'" in whens[0]["condition"]
    assert whens[1]["condition"] is None
    assert whens[2]["condition"] is None


def test_update_set_star_is_marked_as_star() -> None:
    sql = (
        "MERGE INTO dw.ev_tgt t USING ods.ev_src s ON t.k = s.k "
        "WHEN MATCHED THEN UPDATE SET *"
    )
    whens = _document(sql)["merge_spec"]["whens"]
    assert [(w["action"], w["star"]) for w in whens] == [("update", True)]


def test_a_statement_that_is_not_a_merge_has_no_merge_spec() -> None:
    document = _document("INSERT OVERWRITE TABLE dw.ev_tgt SELECT k, v, w, dt FROM ods.ev_src")
    assert "merge_spec" not in document


def test_a_document_with_merge_spec_validates() -> None:
    validate_lineage_document(_document(CONDITIONED_MERGE))


def test_the_schema_describes_merge_spec_rather_than_merely_tolerating_it() -> None:
    document = _document(CONDITIONED_MERGE)
    document["merge_spec"]["whens"][0]["clause"] = "sometimes"
    with pytest.raises(jsonschema.ValidationError):
        validate_lineage_document(document)


def test_the_task_document_carries_merge_spec_on_the_statement() -> None:
    task = to_task_lineage_dict(parse_task_lineage(CONDITIONED_MERGE, "merge_facts", schema=SCHEMA))
    statements = list(task["statement_lineage"].values())
    assert statements[0]["merge_spec"]["key_pairs"] == [{"target": "k", "source": "k"}]
