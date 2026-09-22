"""N4: the review report on the summary line, and the two exports finished off.

Three things a run already knew and never said. The summary line reported the merges,
the splits and the conflicts of a reviewed round but not the two counts a reviewer acts
on -- what was applied and is still worth a second look (``warnings[]``) and what the
round quietly took off the board (``dissolved[]``) -- and a run that cut a review queue
never said where it put it. The exports carried the concept layer but not the two facts
that say how much of it is still a question: how many concepts are provisional, and
which stems a generic key rule refused. And a relation whose end is a table standing in
for a concept read, in an export, exactly like a relation the business has.

The corpus here is the one ``test_ontology_cli`` walks and the synthetic concept corpus
``test_ontology_export`` folds, both borrowed rather than copied: a second corpus that
drifts from the first is a second answer to the same question.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.cli import main
from scope_lineage.render.concepts import CONCEPT_OVERRIDES_DOC_FORMAT, TIER_PROVISIONAL
from scope_lineage.render.ontology_export import (
    EXPORT_FORMATS,
    render_export,
    render_linkml,
    render_shacl,
)
from scope_lineage.render.review_batches import BATCHES_DIR

from .test_ontology_cli import _corpus
from .test_ontology_export import _class_block, _concept_ids, _concept_ontology


STAMP = {"confirmed_by": "agent:concept-review", "date": "2026-09-23"}


# ------------------------------------------------------- the one summary line (N4.1)


def _reviewed(path: Path) -> Path:
    """One reviewed file that puts a table on a concept, dissolving its provisional one."""
    path.write_text(
        json.dumps(
            {
                "doc_format": CONCEPT_OVERRIDES_DOC_FORMAT,
                "concepts": {
                    "concept:country": {
                        "add_tables": {"ods.customer_base": "detail"},
                        **STAMP,
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_the_summary_reports_the_warnings_and_the_dissolved(tmp_path: Path, capsys) -> None:
    """``dissolved`` is a provisional concept a person took off the board. Say so."""
    corpus, out = _corpus(tmp_path / "corpus"), tmp_path / "out"
    reviewed = _reviewed(tmp_path / "concepts.overrides.json")

    code = main(
        [
            "ontology",
            "--lineage",
            str(corpus),
            "--out",
            str(out),
            "--concept-overrides",
            str(reviewed),
        ]
    )

    assert code == 0
    applied = json.loads((out / "ontology.json").read_text(encoding="utf-8"))[
        "concept_overrides_applied"
    ]
    assert len(applied["dissolved"]) == 1 and applied["warnings"] == []
    assert "0 conflict(s), warnings 0, dissolved 1" in capsys.readouterr().out


def test_the_review_counts_are_printed_at_zero_like_the_others(
    tmp_path: Path, capsys
) -> None:
    """A count nobody prints at zero is a count a reader cannot tell from absent."""
    corpus, out = _corpus(tmp_path / "corpus"), tmp_path / "out"
    empty = tmp_path / "empty.overrides.json"
    empty.write_text(
        json.dumps({"doc_format": CONCEPT_OVERRIDES_DOC_FORMAT, "concepts": {}}),
        encoding="utf-8",
    )

    code = main(
        [
            "ontology",
            "--lineage",
            str(corpus),
            "--out",
            str(out),
            "--concept-overrides",
            str(empty),
        ]
    )

    assert code == 0
    assert "0 conflict(s), warnings 0, dissolved 0" in capsys.readouterr().out


def test_the_summary_names_the_review_queue_it_cut(tmp_path: Path, capsys) -> None:
    corpus, out = _corpus(tmp_path / "corpus"), tmp_path / "out"

    code = main(
        ["ontology", "--lineage", str(corpus), "--out", str(out), "--review-batches", str(out)]
    )

    assert code == 0
    assert f"review batches: {out / BATCHES_DIR} (1 batch(es))" in capsys.readouterr().out


def test_a_run_that_cut_no_queue_says_nothing_about_one(tmp_path: Path, capsys) -> None:
    corpus, out = _corpus(tmp_path / "corpus"), tmp_path / "out"

    assert main(["ontology", "--lineage", str(corpus), "--out", str(out)]) == 0

    assert "review batches:" not in capsys.readouterr().out


# --------------------------------------------- what the exports were still missing


def _provisional_concept() -> dict:
    """M1's shape: one table standing in for a concept nobody has named yet."""
    return {
        "id": "concept:table:tmp_stage_party",
        "name": "stage party（合成）",
        "name_tier": "stem_only",
        "name_candidates": [],
        "kind": "entity",
        "kind_tier": "hypothesis",
        "kind_evidence": [],
        "origin": TIER_PROVISIONAL,
        "identity": {"stem": "stage", "columns_seen": ["stage_no"]},
        "tables": [
            {
                "table": "tmp.stage_party",
                "role": "primary",
                "membership_basis": TIER_PROVISIONAL,
                "key_columns": ["stage_no"],
                "grain": None,
            }
        ],
        "attributes": [],
        "tier": TIER_PROVISIONAL,
    }


def _retired_ontology() -> dict:
    """The synthetic concept corpus, plus a provisional concept and two retired stems."""
    ontology = _concept_ontology()
    ontology["concepts"].append(_provisional_concept())
    ontology["relations"].append(
        {
            "from": "concept:table:tmp_stage_party",
            "to": "concept:party",
            "type": "association",
            "cardinality": {"claim": "many_to_one", "tier": "implied", "basis": ["rel:009"]},
            "task_count": 1,
            "evidence": ["rel:009"],
        }
    )
    ontology["provisional_count"] = 1
    ontology["retired_stems"] = [
        {
            "stem": "audit",
            "tables": [
                {"table": "tmp.stage_party", "role": "primary", "key_columns": ["audit_no"]}
            ],
        },
        {
            "stem": "trace",
            "tables": [
                {"table": "ods.order_event", "role": "detail", "key_columns": ["trace_no"]},
                {"table": "mart.party_daily", "role": "summary", "key_columns": ["trace_no"]},
            ],
        },
    ]
    return ontology


@pytest.mark.parametrize("fmt", EXPORT_FORMATS)
def test_every_retired_stem_reaches_the_export_exactly_once(fmt: str) -> None:
    """K4c's answer-keeping list is governance, and an export that drops it says none."""
    ontology = _retired_ontology()

    text = render_export(ontology, fmt)

    for item in ontology["retired_stems"]:
        assert text.count(str(item["stem"])) == 1, item["stem"]


def test_the_linkml_lists_each_retired_stem_with_the_tables_it_keys() -> None:
    text = render_linkml(_retired_ontology())

    assert "  retired_stems:" in text
    assert '    - "audit: 1 tables"' in text
    assert '    - "trace: 2 tables"' in text


def test_the_turtle_hangs_each_retired_stem_off_the_ontology_node() -> None:
    turtle = render_shacl(_retired_ontology())

    node = turtle[turtle.index("sl:Ontology\n") :]
    assert node.count("sl:retiredStem [") == 2
    assert 'sl:stem "audit"' in node
    assert 'sl:tableCount "1"' in node and 'sl:tableCount "2"' in node


def test_the_provisional_count_is_a_schema_level_fact_in_both_exports() -> None:
    """How much of the concept layer is still a question belongs to the schema."""
    ontology = _retired_ontology()

    assert "  provisional_count: 1" in render_linkml(ontology)
    assert "    sl:provisionalCount 1" in render_shacl(ontology)


@pytest.mark.parametrize("fmt", EXPORT_FORMATS)
def test_a_concept_class_carries_the_impact_the_review_queue_ranks_by(fmt: str) -> None:
    """The same ranking the worksheets and the index use, so nobody reads a third one."""
    ontology = _retired_ontology()

    text = render_export(ontology, fmt)

    # concept:party is an end of all three relations, over 2 + 1 + 1 tasks.
    assert text.count('"3 relation(s), 4 task(s)"') == 1


@pytest.mark.parametrize("fmt", EXPORT_FORMATS)
def test_a_relation_whose_end_is_provisional_is_marked_in_the_export(fmt: str) -> None:
    """One class annotation and one relation slot: an edge onto a table is not a fact."""
    ontology = _retired_ontology()
    mark = "provisional: true" if fmt == "linkml" else "sl:provisional true"

    text = render_export(ontology, fmt)

    assert text.count(mark) == 2


def test_a_relation_between_two_settled_concepts_is_not_marked() -> None:
    text = render_linkml(_retired_ontology())
    ontology = _retired_ontology()

    block = _class_block(text, _concept_ids(ontology)["concept:order"])

    assert "participation" in block and "provisional" not in block


def test_the_linkml_still_loads_as_a_schema_with_the_new_annotations() -> None:
    """The structural checks the round trip has always made, over the wider export."""
    ontology = _retired_ontology()

    text = render_linkml(ontology)

    assert text.startswith("id: ") and "\nclasses:\n" in text
    for class_id in _concept_ids(ontology).values():
        assert _class_block(text, class_id).startswith(f"  {class_id}:")
    assert text.endswith("\n") and not text.endswith("\n\n")
