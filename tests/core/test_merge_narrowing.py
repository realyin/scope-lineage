"""Q6: a small corpus borrowing a very large card set pays for the corpus, not the set.

P7 let a corpus reach for another batch's table cards (``--tables``, repeatable, merged
first). It also made the cost of doing so the size of the *batch*: every card was merged,
held in memory, indexed by every spelling it carried, and scanned again for every table
name the corpus could not resolve exactly -- to answer questions about a handful of
tables. A corpus of five tables against a warehouse-wide batch paid for the warehouse.

The narrowing here is not a heuristic and not a sampling. ``same_table`` only ever holds
between names ending in the same unqualified segment, so the merge's grouping never
crosses a ``table_key`` bucket. Taking the *whole* bucket of every name the corpus wrote
therefore reproduces, for those buckets, exactly the groups the full merge would have
published -- including the bare name that stays ambiguous because two qualified tables
could be it, which a rule based on "cards that match a corpus name" would have quietly
resolved.

So the properties pinned here are equality first and cost second: the ontology built over
a narrowed merge is byte-identical to the one built over the full merge, the count of
tables that only lent evidence still counts the whole batch, and only then -- once those
hold -- the merged card list and the name index are the size of the corpus.
"""

from __future__ import annotations

import json
from pathlib import Path

from scope_lineage.cli import main
from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.ontology import (
    TIER_PROVEN,
    build_ontology,
    corpus_table_names,
)
from scope_lineage.render.ontology import (
    _name_index,
)
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.render.table_cards import (
    DOC_FORMAT,
    NARROWED_KEY,
    build_table_cards,
    considered_table_count,
    merge_table_cards,
    table_key,
)
from scope_lineage.scope.scope_builder import parse_scope_lineage

from .statement_document import write_statement_documents


#: A five-table corpus: two writes, one of them joining a table a foreign batch proved.
SCHEMA = {
    "ods.order_line": ["order_id", "sku_id", "qty", "dt"],
    "ods.sku_base": ["sku_id", "sku_name", "dt"],
    "mart.sku_daily": ["sku_id", "qty", "dt"],
    "mart.order_enriched": ["order_id", "sku_id", "sku_name"],
    "dim.calendar": ["dt", "week_id"],
}

ROLLUP_SQL = (
    "INSERT OVERWRITE TABLE mart.sku_daily PARTITION (dt = '20250101') "
    "SELECT l.sku_id, sum(l.qty) AS qty FROM ods.order_line l "
    "JOIN dim.calendar c ON l.dt = c.dt GROUP BY l.sku_id"
)

ENRICH_SQL = (
    "INSERT OVERWRITE TABLE mart.order_enriched "
    "SELECT l.order_id, l.sku_id, s.sku_name FROM ods.order_line l "
    "LEFT JOIN ods.sku_base s ON l.sku_id = s.sku_id"
)

CASES = (("rollup_task", ROLLUP_SQL), ("enrich_task", ENRICH_SQL))

#: How many synthetic cards the borrowed batch holds. Large enough that "O(the corpus)"
#: and "O(the batch)" cannot be confused for one another, small enough to stay a unit
#: test. Every name in it is invented here, in this file.
BATCH_SIZE = 2000


def _documents() -> list[dict]:
    return [
        to_lineage_dict(parse_scope_lineage(sql, task, schema=SCHEMA))
        for task, sql in CASES
    ]


def _profiles(documents) -> list[dict]:
    return [build_semantic_profile(document) for document in documents]


def _corpus_cards(documents) -> dict:
    return build_table_cards(_profiles(documents), artifact_root="corpus_here")


def _synthetic_card(table: str, *, aliases=(), keys=("row_id",)) -> dict:
    """One card of a batch nobody in this corpus walked: a producer and one column."""
    task = f"batch_task_{table.rpartition('.')[2]}"
    return {
        "table": table,
        "aliases": list(aliases),
        "comment": None,
        "domain": None,
        "project": None,
        "owner": None,
        "layer": None,
        "kind": "physical",
        "produced_by": [
            {
                "task": task,
                "statement_id": "stmt:001",
                "stmt_kind": "INSERT_OVERWRITE",
                "partition": {"columns": [], "mode": None, "spec": {}},
                "grain": {"basis": "group_by", "keys": list(keys)},
                "candidate_keys": list(keys),
                "key_confidence": "proven",
                "fields": [
                    {
                        "column": key,
                        "comment": None,
                        "summary": None,
                        "structural_role": "candidate_key",
                    }
                    for key in keys
                ],
                "refresh": None,
                "header_comments": [],
                "lineage_digest": None,
            }
        ],
        "consumed_by": [],
        "columns": [
            {
                "name": key,
                "type": None,
                "comment": None,
                "produced_summary": None,
                "consumer_usage_counts": {},
                "used_in_corpus": False,
            }
            for key in keys
        ],
        "coverage": {
            "column_comment_ratio": 0.0,
            "table_comment": False,
            "producers": 1,
            "consumers": 0,
            "columns_used": 0,
            "columns_declared": len(keys),
        },
        "findings": [],
    }


def _batch(cards, *, root: str = "batch_elsewhere", task_count: int = BATCH_SIZE) -> dict:
    return {
        "doc_format": DOC_FORMAT,
        "corpus": {
            "artifact_root": root,
            "task_count": task_count,
            "lineage_digests": {},
        },
        "tables": list(cards),
    }


def _wide_batch(extra=()) -> dict:
    """``BATCH_SIZE`` cards for tables this corpus never names, plus whatever was asked."""
    cards = [
        _synthetic_card(f"batch.synthetic_table_{index:04d}")
        for index in range(BATCH_SIZE)
    ]
    return _batch([*cards, *extra])


def _write_corpus(root: Path) -> Path:
    for task, sql in CASES:
        write_statement_documents(parse_scope_lineage(sql, task, schema=SCHEMA), root / task)
    return root


def _written(tmp_path: Path, name: str, document: dict) -> Path:
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _dumped(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------- the bucket rule


def test_the_bucket_key_is_the_unqualified_name() -> None:
    assert table_key("catalog.mart.sku_daily") == "sku_daily"
    assert table_key("mart.sku_daily") == "sku_daily"
    assert table_key("sku_daily") == "sku_daily"


# ------------------------------------------------------- the full merge is unchanged


def test_without_needed_the_merge_is_the_one_it_always_was() -> None:
    documents = _documents()
    batch = _wide_batch()

    merged = merge_table_cards(batch, _corpus_cards(documents))

    assert NARROWED_KEY not in merged
    assert len(merged["tables"]) == BATCH_SIZE + 5
    assert considered_table_count(merged) == len(merged["tables"])


def test_merging_one_document_is_still_the_identity() -> None:
    cards = _corpus_cards(_documents())

    assert merge_table_cards(cards) == cards


# ------------------------------------------------------------------- what comes in


def test_only_the_buckets_the_corpus_named_are_merged() -> None:
    documents = _documents()
    batch = _wide_batch([_synthetic_card("ods.sku_base", keys=("sku_id",))])

    merged = merge_table_cards(
        batch, _corpus_cards(documents), needed=corpus_table_names(documents)
    )

    assert {card["table"] for card in merged["tables"]} == set(SCHEMA)
    assert merged[NARROWED_KEY] == {"tables_considered": BATCH_SIZE + 5, "tables_merged": 5}


def test_a_card_is_kept_for_an_alias_in_a_wanted_bucket() -> None:
    documents = _documents()
    # The batch spells the borrowed table with a catalog the corpus never writes, and
    # records the corpus's own spelling as an alias.
    batch = _batch(
        [_synthetic_card("spark_catalog.mart.sku_daily", aliases=("mart.sku_daily",))]
    )

    merged = merge_table_cards(batch, needed=corpus_table_names(documents))

    assert [card["table"] for card in merged["tables"]] == ["spark_catalog.mart.sku_daily"]


def test_a_batch_table_the_corpus_never_names_is_left_out() -> None:
    documents = _documents()
    batch = _batch([_synthetic_card("batch.unrelated_table")])

    merged = merge_table_cards(batch, needed=corpus_table_names(documents))

    assert merged["tables"] == []
    assert merged[NARROWED_KEY]["tables_considered"] == 1


def test_a_bare_name_several_batch_tables_could_be_stays_ambiguous() -> None:
    """The whole bucket comes in, or the narrowing would answer a question the full
    merge refused: with only ``mart.sku_daily`` merged, the bare ``sku_daily`` card
    would have exactly one host and would fold into it."""
    documents = _documents()
    batch = _batch(
        [
            _synthetic_card("mart.sku_daily"),
            _synthetic_card("staging.sku_daily"),
            _synthetic_card("sku_daily"),
        ]
    )

    full = merge_table_cards(batch, _corpus_cards(documents))
    narrowed = merge_table_cards(
        batch, _corpus_cards(documents), needed=corpus_table_names(documents)
    )

    assert {card["table"] for card in narrowed["tables"]} >= {
        "mart.sku_daily",
        "staging.sku_daily",
        "sku_daily",
    }
    kept = {card["table"] for card in narrowed["tables"]}
    assert [card for card in full["tables"] if card["table"] in kept] == [
        card for card in narrowed["tables"] if card["table"] in kept
    ]


# ------------------------------------------------- the ontology is the same document


def test_the_ontology_is_byte_identical_to_the_full_merge() -> None:
    documents = _documents()
    profiles = _profiles(documents)
    batch = _wide_batch([_synthetic_card("ods.sku_base", keys=("sku_id",))])
    cards = _corpus_cards(documents)

    full = build_ontology(
        documents, profiles, tables=merge_table_cards(batch, cards), artifact_root="here"
    )
    narrowed = build_ontology(
        documents,
        profiles,
        tables=merge_table_cards(batch, cards, needed=corpus_table_names(documents)),
        artifact_root="here",
    )

    assert _dumped(narrowed) == _dumped(full)
    # Not a vacuous equality: the batch's card is what decides one of the relations.
    borrowed = next(
        item for item in narrowed["table_relations"] if item["to"]["entity"] == "ods.sku_base"
    )
    assert borrowed["cardinality"]["tier"] == TIER_PROVEN
    assert [item["corpus"] for item in borrowed["evidence"] if item.get("corpus")] == [
        "batch_elsewhere"
    ]


def test_the_external_evidence_count_still_counts_the_whole_batch() -> None:
    documents = _documents()
    profiles = _profiles(documents)
    batch = _wide_batch()
    cards = _corpus_cards(documents)

    narrowed = build_ontology(
        documents,
        profiles,
        tables=merge_table_cards(batch, cards, needed=corpus_table_names(documents)),
        artifact_root="here",
    )

    assert narrowed["corpus"]["external_evidence_tables"] == BATCH_SIZE
    assert len(narrowed["tables"]) == 5


# -------------------------------------------------------------------------- the cost


def test_the_merged_cards_and_the_name_index_are_the_size_of_the_corpus() -> None:
    documents = _documents()
    batch = _wide_batch()
    cards = _corpus_cards(documents)
    touched = len(SCHEMA)

    narrowed = merge_table_cards(batch, cards, needed=corpus_table_names(documents))

    # A count, not a timing: the batch may grow without bound and neither number moves.
    assert len(narrowed["tables"]) == touched
    assert len(_name_index(narrowed)) == touched
    assert len(_name_index(merge_table_cards(batch, cards))) == BATCH_SIZE + touched


# ---------------------------------------------------------------------- the two CLIs


def test_the_ontology_command_narrows_the_batch_it_was_given(tmp_path: Path) -> None:
    documents = _documents()
    corpus = _write_corpus(tmp_path / "corpus")
    own = tmp_path / "corpus-tables"
    assert main(["tables", "--lineage", str(corpus), "--out", str(own)]) == 0
    batch = _written(
        tmp_path, "batch", _wide_batch([_synthetic_card("ods.sku_base", keys=("sku_id",))])
    )
    out = tmp_path / "ontology"

    assert (
        main(
            [
                "ontology",
                "--lineage",
                str(corpus),
                "--tables",
                str(batch),
                "--tables",
                str(own / "tables.json"),
                "--out",
                str(out),
            ]
        )
        == 0
    )

    ontology = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    assert {entity["id"] for entity in ontology["tables"]} == set(SCHEMA)
    assert ontology["corpus"]["external_evidence_tables"] == BATCH_SIZE
    assert sorted(path.stem for path in (out / "tables").glob("*.md")) == sorted(SCHEMA)
    assert corpus_table_names(documents) >= set(SCHEMA)


def test_the_tables_merge_command_still_publishes_every_card(tmp_path: Path) -> None:
    """``tables --merge`` has no corpus to narrow for: its document is the complete one."""
    first = _written(tmp_path, "first", _wide_batch())
    second = _written(tmp_path, "second", _batch([_synthetic_card("other.lone_table")]))
    out = tmp_path / "merged"

    assert main(["tables", "--merge", str(first), "--merge", str(second), "--out", str(out)]) == 0

    merged = json.loads((out / "tables.json").read_text(encoding="utf-8"))
    assert len(merged["tables"]) == BATCH_SIZE + 1
    assert NARROWED_KEY not in merged
