"""AMBIGUOUS root refs must mark the mapping chain incomplete, matching end_to_end.

An unqualified column that several sources could equally supply is published as an
AMBIGUOUS ref with candidates (LINEAGE-002). The end-to-end layer already reports
``trace_complete=false`` for such fields; the field_mapping_chains layer used to
claim ``trace_status=complete`` for the very same field when expression expansion
happened to resolve through sqlglot's guessed qualification — a guess published as
a fact, and a direct contradiction inside one document.
"""

from __future__ import annotations

from scope_lineage.contract import to_lineage_dict
from scope_lineage.scope.scope_builder import parse_scope_lineage


# The ambiguity needs three ingredients to survive parsing: a bare column, one
# derived-table source whose projection is known to contain it, and one joined
# physical table whose schema is unknown (so it cannot be ruled out).
AMBIGUOUS_EXPANSION_SQL = """
INSERT OVERWRITE TABLE mart.session_summary
SELECT o.session_id AS session_id,
       CONCAT(begin_date, ' ', begin_time) AS session_start_time
FROM (
  SELECT a.session_id, a.begin_date, a.begin_time
  FROM ods.session_events a
) o
LEFT JOIN ods.session_dim g ON o.session_id = g.session_id
"""

DISAMBIGUATING_SCHEMA = {
    "ods.session_events": ["session_id", "begin_date", "begin_time"],
    "ods.session_dim": ["session_id", "dim_name"],
}


def _document(sql: str, schema=None) -> dict:
    return to_lineage_dict(parse_scope_lineage(sql, "case_task", schema=schema))


def _chain_for(document: dict, target_field: str) -> dict:
    return next(
        chain
        for chain in document["field_mapping_chains"]
        if chain["target_field"] == target_field
    )


def _e2e_for(document: dict, column: str) -> dict:
    return next(
        entry
        for entry in document["end_to_end_lineage"]
        if entry["column"] == column
    )


def test_ambiguous_root_marks_chain_incomplete_even_when_expansion_resolved() -> None:
    document = _document(AMBIGUOUS_EXPANSION_SQL)
    chain = _chain_for(document, "session_start_time")
    assert chain["root_source_fields"] == [
        "AMBIGUOUS.begin_date",
        "AMBIGUOUS.begin_time",
    ]
    assert chain["trace_status"] == "incomplete"
    assert "ambiguous_unqualified:begin_date" in chain["missing_reasons"]
    assert "ambiguous_unqualified:begin_time" in chain["missing_reasons"]
    assert chain["chain_status"] == "partially_resolved"


def test_ambiguous_rooted_chains_agree_with_end_to_end_layer() -> None:
    document = _document(AMBIGUOUS_EXPANSION_SQL)
    ambiguous_chains = [
        chain
        for chain in document["field_mapping_chains"]
        if any(
            str(root).startswith("AMBIGUOUS.")
            for root in chain["root_source_fields"]
        )
    ]
    assert ambiguous_chains
    for chain in ambiguous_chains:
        assert chain["trace_status"] != "complete"
        entry = _e2e_for(document, chain["target_field"])
        assert entry["trace_complete"] is False


def test_schema_disambiguation_keeps_the_chain_complete() -> None:
    document = _document(AMBIGUOUS_EXPANSION_SQL, schema=DISAMBIGUATING_SCHEMA)
    chain = _chain_for(document, "session_start_time")
    assert chain["root_source_fields"] == [
        "ods.session_events.begin_date",
        "ods.session_events.begin_time",
    ]
    assert chain["trace_status"] == "complete"
    assert not any(
        str(reason).startswith("ambiguous_unqualified:")
        for reason in chain["missing_reasons"]
    )
    assert _e2e_for(document, "session_start_time")["trace_complete"] is True


def test_constant_and_system_roots_stay_complete_without_new_reasons() -> None:
    # These sources hit the same collector branch as AMBIGUOUS (no upstream output,
    # not an internal scope). The incompleteness mark must bite only on AMBIGUOUS.
    document = _document(
        """
        INSERT OVERWRITE TABLE mart.constants_case
        SELECT 'fixed' AS label,
               CURRENT_DATE() AS load_date,
               a.session_id AS session_id
        FROM ods.session_events a
        """
    )
    for field in ("label", "load_date"):
        chain = _chain_for(document, field)
        assert chain["trace_status"] == "complete"
        assert not any(
            str(reason).startswith("ambiguous_unqualified:")
            for reason in chain["missing_reasons"]
        )
