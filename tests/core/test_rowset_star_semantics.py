"""Row-set star refs must not read as "uses every column".

``COUNT(*)`` depends on the input row set and reads no columns, but its SourceRefs
were plain ``column="*"`` — the same shape the unexpandable-``SELECT *`` fallback
uses to mean "all columns flow". Consumers could not tell the two apart: the
related-metadata layer kept every schema column as "used" (a wide table showed its
full width as used for a task reading a handful of fields), and end-to-end lineage published
``column='*'`` physical entries that contradicted the expression-resolution layer's
own ``row_count_aggregate``/``rowset`` classification. Source-free aggregate refs
now carry ``rowset=True`` ("no column read"), and every consumer routes on it.
"""

from __future__ import annotations


from scope_lineage import render_mapping_markdown, validate_contract_invariants
from scope_lineage.contract import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage


SCHEMA = {
    "ods.events": ["grp", "uid", "amt", "extra_a", "extra_b"],
    "ods.dims": ["grp", "name", "extra_c"],
}

COUNT_STAR_JOIN_SQL = """
INSERT INTO mart.stats
SELECT a.grp, COUNT(*) AS total_cnt, COUNT(DISTINCT a.uid) AS uid_cnt
FROM ods.events a JOIN ods.dims b ON a.grp = b.grp
GROUP BY a.grp
"""


def _document(sql: str, schema=SCHEMA) -> dict:
    return to_lineage_dict(parse_scope_lineage(sql, "case_task", schema=schema))


def _e2e(document: dict, column: str) -> dict:
    return next(e for e in document["end_to_end_lineage"] if e["column"] == column)


def _input_meta(document: dict, table: str) -> dict:
    return (document.get("related_metadata") or {}).get("input_tables", {}).get(table) or {}


def _star_physicals(entry: dict) -> list:
    return [s for s in entry.get("physical_sources") or [] if s.get("column") == "*"]


def test_count_star_no_longer_claims_every_column_used() -> None:
    document = _document(COUNT_STAR_JOIN_SQL)
    events = _input_meta(document, "ods.events")
    used = [item["name"] for item in events.get("column_details") or []]
    assert sorted(used) == ["grp", "uid"]
    assert events["table_column_count"] == 5
    dims = _input_meta(document, "ods.dims")
    assert [item["name"] for item in dims.get("column_details") or []] == ["grp"]
    assert dims["table_column_count"] == 3


def test_count_star_e2e_is_rowset_not_physical_star() -> None:
    document = _document(COUNT_STAR_JOIN_SQL)
    entry = _e2e(document, "total_cnt")
    assert _star_physicals(entry) == []
    assert entry["source_kind"] == "rowset"
    rowset = entry.get("rowset_sources") or []
    assert rowset
    for item in rowset:
        assert set(item) >= {"source_type", "scope", "field", "expression"}
    assert entry["trace_complete"] is True
    assert validate_contract_invariants(document) == []


def test_count_star_ref_is_marked_in_scopes_layer() -> None:
    document = _document(COUNT_STAR_JOIN_SQL)
    root = document["scopes"]["ROOT"]
    total = next(c for c in root["columns"] if c["name"] == "total_cnt")
    assert total["sources"]
    assert all(s.get("rowset") is True for s in total["sources"])
    uid = next(c for c in root["columns"] if c["name"] == "uid_cnt")
    assert all("rowset" not in s for s in uid["sources"])


def test_count_star_over_cte_is_equally_clean() -> None:
    document = _document(
        """
        INSERT INTO mart.stats
        WITH joined AS (
          SELECT a.grp, a.uid FROM ods.events a JOIN ods.dims b ON a.grp = b.grp
        )
        SELECT grp, COUNT(*) AS total_cnt FROM joined GROUP BY grp
        """
    )
    entry = _e2e(document, "total_cnt")
    assert _star_physicals(entry) == []
    assert entry["source_kind"] == "rowset"
    events = _input_meta(document, "ods.events")
    used = [item["name"] for item in events.get("column_details") or []]
    assert sorted(used) == ["grp", "uid"]


def test_select_star_fallback_keeps_all_columns_semantics() -> None:
    # unexpandable SELECT * (no schema): the star genuinely means "all columns flow"
    document = _document(
        "INSERT INTO mart.copy SELECT * FROM ods.mystery",
        schema=None,
    )
    root = document["scopes"]["ROOT"]
    star_sources = [
        s
        for c in root["columns"]
        for s in c.get("sources") or []
        if s.get("column") == "*"
    ]
    assert star_sources
    assert all("rowset" not in s for s in star_sources)
    meta = _input_meta(document, "ods.mystery")
    assert meta.get("column_details")


def test_count_one_matches_count_star_and_count_col_is_untouched() -> None:
    document = _document(
        """
        INSERT INTO mart.stats
        SELECT a.grp, COUNT(1) AS row_cnt, COUNT(a.uid) AS uid_cnt
        FROM ods.events a GROUP BY a.grp
        """
    )
    row_entry = _e2e(document, "row_cnt")
    assert _star_physicals(row_entry) == []
    assert row_entry["source_kind"] == "rowset"
    uid_entry = _e2e(document, "uid_cnt")
    assert [s["column"] for s in uid_entry["physical_sources"]] == ["uid"]


def test_literal_aggregates_stay_generated_not_rowset() -> None:
    # SUM(1)/MAX('x') satisfy the same "source-free aggregate" condition but the
    # resolution layer classifies them as generated; the fix must not overwrite that
    document = _document(
        """
        INSERT INTO mart.stats
        SELECT a.grp, SUM(1) AS ones_sum, MAX('x') AS fixed_max
        FROM ods.events a GROUP BY a.grp
        """
    )
    for column in ("ones_sum", "fixed_max"):
        entry = _e2e(document, column)
        assert _star_physicals(entry) == []
        assert entry["source_kind"] == "generated"
        assert not entry.get("rowset_sources")
    events = _input_meta(document, "ods.events")
    used = [item["name"] for item in events.get("column_details") or []]
    assert used == ["grp"]
    assert validate_contract_invariants(document) == []


def test_mixed_expression_combines_physical_and_rowset() -> None:
    document = _document(
        """
        INSERT INTO mart.stats
        WITH agg AS (
          SELECT a.grp, COUNT(*) AS cnt, SUM(a.amt) AS amt_sum
          FROM ods.events a GROUP BY a.grp
        )
        SELECT grp, cnt + amt_sum AS blended FROM agg
        """
    )
    entry = _e2e(document, "blended")
    assert _star_physicals(entry) == []
    physical = {s["column"] for s in entry.get("physical_sources") or []}
    assert "amt" in physical
    assert entry.get("rowset_sources")
    assert entry["source_kind"] == "mixed"


def test_window_row_number_does_not_regress() -> None:
    document = _document(
        """
        INSERT INTO mart.ranked
        SELECT a.uid, ROW_NUMBER() OVER (PARTITION BY a.grp ORDER BY a.amt) AS rn
        FROM ods.events a
        """
    )
    entry = _e2e(document, "rn")
    assert _star_physicals(entry) == []
    assert validate_contract_invariants(document) == []


def test_rowset_only_table_keeps_its_metadata_entry() -> None:
    document = _document(
        """
        INSERT INTO mart.stats
        SELECT COUNT(*) AS total_cnt FROM ods.dims
        """
    )
    dims = _input_meta(document, "ods.dims")
    assert dims != {}
    assert dims.get("column_details") == []
    assert dims["table_column_count"] == 3


def test_sources_section_renders_table_and_used_column_counts() -> None:
    document = _document(COUNT_STAR_JOIN_SQL)
    rendered = render_mapping_markdown(document)
    section = rendered[rendered.index("## 2."): rendered.index("## 3.")]
    assert "| 表 | 表列数（元数据） | 使用列数 | 元数据完整 |" in section
    assert "| ods.events | 5 | 2 | 是 |" in section
    assert "| ods.dims | 3 | 1 | 是 |" in section


def test_unknown_schema_star_table_renders_dash_for_used_columns() -> None:
    document = _document(
        "INSERT INTO mart.copy SELECT * FROM ods.mystery",
        schema=None,
    )
    rendered = render_mapping_markdown(document)
    section = rendered[rendered.index("## 2."): rendered.index("## 3.")]
    assert "| ods.mystery | — | — | 否 |" in section
