"""Concept-level impact: ``query.py concept-impact`` answers "who breaks if this
business concept changes".

``impact`` and ``trace`` answer at the table/column level, which is the level the
artifacts record but not the level a business owner asks at. The ontology says which
tables *represent* a concept and which columns back each of its attributes; this
subcommand joins the two -- it reads ``ontology.json`` (``ontology-json/2``) for the
concept's representation tables, attributes and relations, then reuses the script's
existing corpus impact machinery to name the downstream tasks of every one of those
tables (or, with ``--attribute``, only of that attribute's source columns).

The corpus here is synthetic and built by the real CLI; the ontology is a hand-written
``ontology-json/2`` document written to the same temp dir, so the contract this pins is
the *document shape* the subcommand reads, not one build's output.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
QUERY = REPO / "skills" / "scope-lineage" / "scripts" / "query.py"

TASK_SQL = {
    "task_a": """
INSERT INTO cat.dwd.party_clean
SELECT p.party_id, p.party_name, p.region_code
FROM cat.ods.party p;
""",
    "task_b": """
INSERT INTO cat.dm.party_stats
SELECT c.party_id, count(1) AS party_rows
FROM cat.dwd.party_clean c
GROUP BY c.party_id;
""",
    "task_c": """
INSERT INTO cat.app.party_report
SELECT s.party_id, s.party_rows
FROM cat.dm.party_stats s;
""",
    "task_d": """
INSERT INTO cat.dwd.region_rollup
SELECT p.region_code, count(1) AS party_rows
FROM cat.ods.party p
GROUP BY p.region_code;
""",
}


def _concept(concept_id: str, name: str, **extra: object) -> dict:
    base: dict = {
        "id": concept_id,
        "name": name,
        "kind": "entity",
        "kind_tier": "implied",
        "identity": {"stem": name, "columns_seen": []},
        "tables": [],
        "attributes": [],
        "tier": "hypothesis",
    }
    base.update(extra)
    return base


ONTOLOGY = {
    "doc_format": "ontology-json/2",
    "concepts": [
        _concept(
            "concept:party",
            "party",
            tables=[
                {
                    "table": "cat.ods.party",
                    "role": "primary",
                    "membership_basis": "key:hypothesis",
                    "key_columns": ["party_id"],
                    "grain": None,
                },
                {
                    "table": "cat.dwd.party_clean",
                    "role": "secondary",
                    "membership_basis": "key:hypothesis",
                    "key_columns": ["party_id"],
                    "grain": None,
                },
            ],
            attributes=[
                {
                    "stem": "party",
                    "type": None,
                    "comment": None,
                    "sources": [{"table": "cat.ods.party", "column": "party_id"}],
                },
                {
                    "stem": "region",
                    "type": None,
                    "comment": None,
                    "sources": [{"table": "cat.ods.party", "column": "region_code"}],
                },
            ],
        ),
        _concept(
            "concept:partner",
            "partner",
            tables=[
                {
                    "table": "cat.ods.partner",
                    "role": "primary",
                    "membership_basis": "key:hypothesis",
                    "key_columns": ["partner_id"],
                    "grain": None,
                }
            ],
        ),
        _concept("concept:region", "region", kind="entity", tier="implied"),
    ],
    "relations": [
        {
            "id": "crel:001",
            "from": "concept:party",
            "to": "concept:region",
            "type": "association",
            "cardinality": {
                "claim": "many_to_one_assumed",
                "tier": "hypothesis",
                "basis": ["rel:001"],
            },
            "task_count": 1,
            "evidence": ["rel:001"],
        },
        {
            "id": "crel:002",
            "from": "concept:partner",
            "to": "concept:party",
            "type": "association",
            "cardinality": {
                "claim": "many_to_many_observed",
                "tier": "implied",
                "basis": ["rel:002"],
            },
            "task_count": 1,
            "evidence": ["rel:002"],
        },
    ],
    "table_relations": [
        {
            "id": "rel:001",
            "from": {"entity": "cat.ods.party", "columns": ["region_code"]},
            "to": {"entity": "cat.dim.region", "columns": ["region_code"]},
            "kind": "join_association",
            "concept_relation": "crel:001",
        },
        {
            "id": "rel:002",
            "from": {"entity": "cat.ods.partner", "columns": ["partner_id"]},
            "to": {"entity": "cat.ods.party", "columns": ["party_id"]},
            "kind": "join_association",
            "concept_relation": "crel:002",
        },
    ],
    "tables": [
        {"id": "cat.ods.party", "concepts": [{"id": "concept:party", "role": "primary"}]},
        {
            "id": "cat.dwd.party_clean",
            "concepts": [{"id": "concept:party", "role": "secondary"}],
        },
    ],
}


@pytest.fixture(scope="module")
def workspace(tmp_path_factory) -> tuple[Path, Path]:
    """(corpus dir, ontology.json) -- real artifacts, hand-written ontology."""
    from scope_lineage.cli import main

    root = tmp_path_factory.mktemp("concept-impact")
    corpus = root / "artifacts"
    for name, sql in TASK_SQL.items():
        sql_path = root / f"{name}.sql"
        sql_path.write_text(sql, encoding="utf-8")
        assert main(["parse", "--sql-file", str(sql_path), "--out", str(corpus)]) == 0
    ontology = root / "ontology.json"
    ontology.write_text(json.dumps(ONTOLOGY), encoding="utf-8")
    return corpus, ontology


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(QUERY), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _ok(workspace: tuple[Path, Path], *args: str) -> str:
    corpus, ontology = workspace
    result = _run(
        "concept-impact", *args, "--ontology", str(ontology), "--lineage", str(corpus)
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _fails(workspace: tuple[Path, Path], *args: str) -> subprocess.CompletedProcess:
    corpus, ontology = workspace
    result = _run(
        "concept-impact", *args, "--ontology", str(ontology), "--lineage", str(corpus)
    )
    assert result.returncode == 2, result.stdout
    return result


# ------------------------------------------------------------------ resolution


def test_a_concept_resolves_by_id_by_exact_name_and_by_unique_prefix(workspace) -> None:
    by_id = _ok(workspace, "concept:party")
    by_name = _ok(workspace, "party")
    by_prefix = _ok(workspace, "partn")

    assert "concept:party" in by_id
    assert by_id == by_name
    assert "concept:partner" in by_prefix


def test_an_ambiguous_prefix_lists_the_candidates_instead_of_guessing(workspace) -> None:
    result = _fails(workspace, "part")
    message = result.stdout + result.stderr

    assert "concept:party" in message and "concept:partner" in message
    assert "ambiguous" in message.lower()


def test_an_unknown_concept_is_one_sentence_not_a_traceback(workspace) -> None:
    result = _fails(workspace, "no_such_concept")
    message = result.stdout + result.stderr

    assert "no_such_concept" in message
    assert "Traceback" not in result.stderr
    assert len([line for line in message.splitlines() if line.strip()]) == 1


# ------------------------------------------------------- tables and relations


def test_the_representation_tables_are_listed_with_their_roles(workspace) -> None:
    out = _ok(workspace, "concept:party")

    assert "cat.ods.party" in out and "primary" in out
    assert "cat.dwd.party_clean" in out and "secondary" in out


def test_relations_are_listed_in_both_directions_with_type_cardinality_tier(
    workspace,
) -> None:
    out = _ok(workspace, "concept:party")

    assert "crel:001" in out and "crel:002" in out
    assert "concept:region" in out and "concept:partner" in out
    assert "association" in out
    assert "many_to_one_assumed" in out and "many_to_many_observed" in out
    assert "hypothesis" in out and "implied" in out


# -------------------------------------------------------------- downstream


def test_downstream_tasks_of_every_representation_table_are_deduplicated(
    workspace,
) -> None:
    out = _ok(workspace, "concept:party")

    # depth 1: the tasks that read either representation table
    assert "task_a" in out and "task_d" in out and "task_b" in out
    # one line per task, not one per lineage edge
    assert sum(line.count("task_a") for line in out.splitlines()) == 1
    # and each names the table it read
    assert "cat.ods.party" in out and "cat.dwd.party_clean" in out
    # one hop only by default
    assert "task_c" not in out


def test_depth_extends_the_walk_and_records_the_depth_each_task_was_found_at(
    workspace,
) -> None:
    out = _ok(workspace, "concept:party", "--depth", "2")

    assert "task_c" in out
    payload = json.loads(
        _ok(workspace, "concept:party", "--depth", "2", "--json")
    )
    depths = {row["task"]: row["depth"] for row in payload["downstream"]}
    assert depths["task_a"] == 1 and depths["task_b"] == 1 and depths["task_d"] == 1
    assert depths["task_c"] == 2


def test_an_attribute_narrows_downstream_to_the_tasks_reading_its_source_columns(
    workspace,
) -> None:
    out = _ok(workspace, "concept:party", "--attribute", "region")

    assert "region_code" in out
    assert "task_a" in out and "task_d" in out
    # task_b reads party_clean.party_id, never a region column
    assert "task_b" not in out


def test_an_attribute_also_narrows_the_relations_to_those_joining_on_it(
    workspace,
) -> None:
    out = _ok(workspace, "concept:party", "--attribute", "region")
    payload = json.loads(
        _ok(workspace, "concept:party", "--attribute", "region", "--json")
    )

    assert [relation["id"] for relation in payload["attribute"]["relations"]] == [
        "crel:001"
    ]
    assert "crel:001" in out


def test_an_unknown_attribute_is_one_sentence(workspace) -> None:
    result = _fails(workspace, "concept:party", "--attribute", "no_such_attribute")
    message = result.stdout + result.stderr

    assert "no_such_attribute" in message
    assert len([line for line in message.splitlines() if line.strip()]) == 1


# ------------------------------------------------------------ json and shape


def test_json_carries_the_same_answer_as_the_markdown(workspace) -> None:
    payload = json.loads(_ok(workspace, "concept:party", "--json"))

    assert set(payload) == {"concept", "tables", "relations", "downstream"}
    assert payload["concept"]["id"] == "concept:party"
    assert payload["concept"]["name"] == "party"
    assert [table["table"] for table in payload["tables"]] == [
        "cat.dwd.party_clean",
        "cat.ods.party",
    ]
    assert {table["role"] for table in payload["tables"]} == {"primary", "secondary"}
    assert [relation["id"] for relation in payload["relations"]] == [
        "crel:001",
        "crel:002",
    ]
    directions = {relation["id"]: relation["direction"] for relation in payload["relations"]}
    assert directions == {"crel:001": "out", "crel:002": "in"}
    assert sorted(row["task"] for row in payload["downstream"]) == [
        "task_a",
        "task_b",
        "task_d",
    ]
    assert all({"task", "table", "depth", "artifact"} <= set(row) for row in payload["downstream"])


def test_the_attribute_key_is_present_only_when_an_attribute_was_asked_for(
    workspace,
) -> None:
    plain = json.loads(_ok(workspace, "concept:party", "--json"))
    filtered = json.loads(
        _ok(workspace, "concept:party", "--attribute", "region", "--json")
    )

    assert "attribute" not in plain
    assert filtered["attribute"]["name"] == "region"
    assert filtered["attribute"]["sources"] == [
        {"table": "cat.ods.party", "column": "region_code"}
    ]


def test_output_is_deterministic_across_runs(workspace) -> None:
    first = _ok(workspace, "concept:party", "--depth", "2")
    second = _ok(workspace, "concept:party", "--depth", "2")
    first_json = _ok(workspace, "concept:party", "--depth", "2", "--json")
    second_json = _ok(workspace, "concept:party", "--depth", "2", "--json")

    assert first == second
    assert first_json == second_json


# ----------------------------------------------------------------- ontology errors


def test_a_missing_ontology_file_is_one_sentence(tmp_path: Path) -> None:
    result = _run(
        "concept-impact",
        "concept:party",
        "--ontology",
        str(tmp_path / "absent.json"),
        "--lineage",
        str(tmp_path),
    )

    assert result.returncode == 2
    assert "absent.json" in result.stdout + result.stderr
    assert "Traceback" not in result.stderr


def test_an_older_ontology_format_says_so_instead_of_half_answering(
    tmp_path: Path,
) -> None:
    legacy = dict(ONTOLOGY)
    legacy["doc_format"] = "ontology-json/1"
    path = tmp_path / "ontology.json"
    path.write_text(json.dumps(legacy), encoding="utf-8")

    result = _run(
        "concept-impact",
        "concept:party",
        "--ontology",
        str(path),
        "--lineage",
        str(tmp_path),
    )
    message = result.stdout + result.stderr

    assert result.returncode == 2
    assert "ontology-json/2" in message and "ontology-json/1" in message
    assert len([line for line in message.splitlines() if line.strip()]) == 1
