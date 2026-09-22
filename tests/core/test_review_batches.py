"""N1: a concept review that a person can actually finish, on a wide corpus.

One review round is capped at eight human questions and one overrides file. A wide
corpus publishes far more provisional concepts than that, so the round as it stood was
a pile nobody could get to the bottom of. Two halves answer it:

**N1a -- several overrides files, applied in order.** ``--concept-overrides`` repeats,
the files apply left to right, the later file wins a target key both of them name, and
the pair is reported in ``concept_overrides_applied.conflicts[]`` rather than resolved
in silence. Everything that does not collide accumulates, ``sources[]`` says which file
each surviving entry came from, and handing the same file twice changes nothing.

**N1b -- ``review-batches``.** The provisional concepts are cut into batches a reviewer
works one at a time: a markdown worksheet, a skeleton overrides file with one
``merge_into`` slot per concept, and an index that says in which order to read them.

Every table, column, concept, comment, domain and name in this file is synthetic. No
real corpus, table, domain or business name is reproduced here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scope_lineage.cli import main
from scope_lineage.render.concept_relations import (
    build_concept_relations,
    provisional_concept_ids,
)
from scope_lineage.render.concepts import (
    CONCEPT_OVERRIDES_DOC_FORMAT,
    apply_concept_overrides,
    build_concepts,
)
from scope_lineage.render.review_batches import (
    BATCH_BY,
    DEFAULT_BATCH_SIZE,
    BATCHES_DIR,
    NO_CANDIDATE_KEY,
    UNLABELLED_GROUP,
    batch_overrides_skeleton,
    build_review_batches,
    render_batch_index_markdown,
    render_batch_markdown,
    write_review_batches,
)
from scope_lineage.scope.scope_builder import parse_scope_lineage

from .statement_document import write_statement_documents
from .test_concept_relations import _cards, _entity, _relation


REPO_ROOT = Path(__file__).resolve().parents[2]
REVIEW_PROMPT = (
    REPO_ROOT / "skills" / "scope-lineage" / "references" / "concept-review-prompt.md"
)

STAMP = {"confirmed_by": "agent:concept-review", "date": "2026-09-23"}


# ------------------------------------------------------------- synthetic corpora


def _with_domain(entity: dict, *, domain=None, project=None) -> dict:
    """One entity with the metadata hints ``--by domain`` reads."""
    hints = dict(entity["naming_hints"])
    hints["domain"], hints["project"] = domain, project
    return {**entity, "naming_hints": hints}


def _built(entities, relations=(), overrides=None, files=None) -> dict:
    """The builder's own order: concepts, then the overrides, then the relation fold."""
    document = {
        "doc_format": "ontology-json/2",
        "tables": [dict(item) for item in entities],
        "table_relations": [dict(item) for item in relations],
    }
    document.update(build_concepts(document, _cards()))
    apply_concept_overrides(document, overrides if overrides is not None else {}, files=files)
    document.update(build_concept_relations(document))
    return document


def _applied(document) -> dict:
    return document["concept_overrides_applied"]


def _by_id(document) -> dict:
    return {str(concept["id"]): concept for concept in document["concepts"]}


def _overrides(**concepts) -> dict:
    return {"doc_format": CONCEPT_OVERRIDES_DOC_FORMAT, "concepts": dict(concepts)}


def _two_concept_corpus() -> list[dict]:
    """Two seeded concepts and one table a reviewer may move between them."""
    return [
        _entity("dim.alpha", keys=["alpha_code"], comment="阿尔法维表（合成）"),
        _entity("dim.beta", keys=["beta_code"], comment="贝塔维表（合成）"),
        _entity("ods.spare", keys=["id"], columns={"alpha_code": None}),
    ]


# A corpus wide enough to batch: three families, two domains, one seeded concept the
# provisional ones can be merged into.
WIDE_CORPUS = [
    _with_domain(_entity("dim.gamma", keys=["gamma_code"], comment="伽马维表（合成）"), domain="甲域"),
    _with_domain(_entity("ods.alpha_di", keys=["id"], columns={"gamma_code": None}), domain="甲域"),
    _with_domain(_entity("ods.alpha_df", keys=["id"], columns={"gamma_code": None}), domain="甲域"),
    _with_domain(_entity("ods.beta_di", keys=["row_key"]), domain="乙域"),
    _with_domain(
        _entity(
            "ods.delta",
            keys=["row_key"],
            columns={"row_key": "德尔塔流水主键（合成）"},
            comment="德尔塔台账（合成）",
        ),
        project="丙项目",
    ),
    _with_domain(_entity("ods.epsilon", keys=["row_key"])),
]

WIDE_RELATIONS = [
    _relation("rel:001", "ods.alpha_di", ["gamma_code"], "dim.gamma", ["gamma_code"]),
    _relation("rel:002", "ods.alpha_df", ["gamma_code"], "dim.gamma", ["gamma_code"]),
]


def _wide() -> dict:
    return _built(WIDE_CORPUS, WIDE_RELATIONS)


def _batch_concepts(batches: dict) -> list[str]:
    return [item for batch in batches["batches"] for item in batch["concepts"]]


# ---------------------------------------------- N1a: several files, applied in order


def test_a_later_file_wins_a_field_both_files_confirm() -> None:
    earlier = _overrides(**{"concept:alpha": {"name": "第一稿", **STAMP}})
    later = _overrides(**{"concept:alpha": {"name": "第二稿", **STAMP}})

    document = _built(
        _two_concept_corpus(), overrides=[earlier, later], files=["batch-01.json", "batch-02.json"]
    )

    assert _by_id(document)["concept:alpha"]["name"] == "第二稿"
    assert _applied(document)["conflicts"] == [
        {
            "key": "concept:alpha",
            "field": "name",
            "earlier": "batch-01.json",
            "later": "batch-02.json",
        }
    ]


def test_entries_that_do_not_collide_accumulate_across_files() -> None:
    earlier = _overrides(**{"concept:alpha": {"name": "阿尔法", **STAMP}})
    later = _overrides(**{"concept:beta": {"name": "贝塔", **STAMP}})

    document = _built(
        _two_concept_corpus(), overrides=[earlier, later], files=["batch-01.json", "batch-02.json"]
    )

    concepts = _by_id(document)
    assert concepts["concept:alpha"]["name"] == "阿尔法"
    assert concepts["concept:beta"]["name"] == "贝塔"
    assert _applied(document)["conflicts"] == []
    assert _applied(document)["concepts"] == 2


def test_two_fields_of_one_concept_accumulate_rather_than_replace_each_other() -> None:
    earlier = _overrides(**{"concept:alpha": {"name": "阿尔法", **STAMP}})
    later = _overrides(**{"concept:alpha": {"kind": "event", **STAMP}})

    concept = _by_id(
        _built(
            _two_concept_corpus(),
            overrides=[earlier, later],
            files=["batch-01.json", "batch-02.json"],
        )
    )["concept:alpha"]

    assert (concept["name"], concept["kind"]) == ("阿尔法", "event")
    assert (concept["name_tier"], concept["kind_tier"]) == ("confirmed", "confirmed")


def test_an_add_tables_collision_is_reported_per_table() -> None:
    earlier = _overrides(
        **{"concept:alpha": {"add_tables": {"ods.spare": "detail"}, **STAMP}}
    )
    later = _overrides(
        **{"concept:alpha": {"add_tables": {"ods.spare": "snapshot"}, **STAMP}}
    )

    document = _built(
        _two_concept_corpus(), overrides=[earlier, later], files=["a.json", "b.json"]
    )

    members = {
        str(item["table"]): item for item in _by_id(document)["concept:alpha"]["tables"]
    }
    assert members["ods.spare"]["role"] == "snapshot"
    assert _applied(document)["conflicts"] == [
        {
            "key": "concept:alpha",
            "field": "add_tables.ods.spare",
            "earlier": "a.json",
            "later": "b.json",
        }
    ]


def test_a_new_concept_named_by_two_files_conflicts_on_its_id() -> None:
    entry = {
        "id": "concept:spare",
        "name": "备用",
        "kind": "entity",
        "tables": {"ods.spare": "primary"},
        **STAMP,
    }
    earlier = {"doc_format": CONCEPT_OVERRIDES_DOC_FORMAT, "new_concepts": [entry]}
    later = {
        "doc_format": CONCEPT_OVERRIDES_DOC_FORMAT,
        "new_concepts": [{**entry, "name": "备用台账"}],
    }

    document = _built(
        _two_concept_corpus(), overrides=[earlier, later], files=["a.json", "b.json"]
    )

    assert _by_id(document)["concept:spare"]["name"] == "备用台账"
    assert _applied(document)["conflicts"] == [
        {"key": "concept:spare", "field": "new_concepts", "earlier": "a.json", "later": "b.json"}
    ]


def test_sources_name_every_file_with_the_entries_it_won() -> None:
    earlier = _overrides(
        **{
            "concept:alpha": {"name": "第一稿"},
            "concept:beta": {"name": "贝塔"},
        }
    )
    later = _overrides(**{"concept:alpha": {"name": "第二稿"}})

    document = _built(
        _two_concept_corpus(), overrides=[earlier, later], files=["a.json", "b.json"]
    )

    assert _applied(document)["sources"] == [
        {"file": "a.json", "applied": 1},
        {"file": "b.json", "applied": 1},
    ]


def test_the_same_file_twice_is_the_same_document_byte_for_byte() -> None:
    overrides = _overrides(
        **{
            "concept:alpha": {"name": "阿尔法", "add_tables": {"ods.spare": "detail"}, **STAMP},
            "concept:beta": {"kind": "event", **STAMP},
        }
    )

    once = _built(_two_concept_corpus(), overrides=[overrides], files=["a.json"])
    twice = _built(
        _two_concept_corpus(), overrides=[overrides, overrides], files=["a.json", "a.json"]
    )

    assert json.dumps(twice, ensure_ascii=False, sort_keys=True) == json.dumps(
        once, ensure_ascii=False, sort_keys=True
    )


def test_one_unnamed_document_still_applies_exactly_as_it_always_did() -> None:
    document = _built(
        _two_concept_corpus(),
        overrides=_overrides(**{"concept:alpha": {"name": "阿尔法", **STAMP}}),
    )

    assert _by_id(document)["concept:alpha"]["name"] == "阿尔法"
    assert _applied(document)["conflicts"] == []
    assert _applied(document)["sources"] == []


def test_the_report_keeps_the_keys_a_single_file_round_already_published() -> None:
    applied = _applied(_built(_two_concept_corpus()))

    assert set(applied) == {
        "concepts",
        "created",
        "tables_added",
        "roles_upgraded",
        "merges",
        "splits",
        "dissolved",
        "left",
        "unmatched",
        "warnings",
        "ignored_fields",
        "conflicts",
        "sources",
    }


# ------------------------------------------------------- N1b: the batches themselves


def test_every_provisional_concept_lands_in_exactly_one_batch() -> None:
    document = _wide()
    provisional = provisional_concept_ids(document["concepts"])

    listed = _batch_concepts(build_review_batches(document, by="family", batch_size=2))

    assert sorted(listed) == sorted(provisional)
    assert len(listed) == len(set(listed))


@pytest.mark.parametrize("by", BATCH_BY)
def test_no_batch_is_built_from_a_concept_the_corpus_already_folded(by: str) -> None:
    document = _wide()

    listed = set(_batch_concepts(build_review_batches(document, by=by, batch_size=2)))

    assert "concept:gamma" not in listed


def test_by_family_keeps_one_family_in_one_batch() -> None:
    batches = build_review_batches(_wide(), by="family", batch_size=2)["batches"]

    homes = {}
    for batch in batches:
        for group in batch["groups"]:
            homes.setdefault(group, set()).add(batch["id"])
    assert all(len(where) == 1 for where in homes.values()), homes
    assert "ods.alpha" in homes


def test_by_family_fills_up_to_the_batch_size() -> None:
    batches = build_review_batches(_wide(), by="family", batch_size=2)["batches"]

    assert all(batch["size"] <= 2 for batch in batches)
    assert [batch["id"] for batch in batches] == [
        f"batch-{index:02d}" for index in range(1, len(batches) + 1)
    ]


def test_a_family_larger_than_the_cap_stays_whole_in_its_own_batch() -> None:
    batches = build_review_batches(_wide(), by="family", batch_size=1)["batches"]

    alpha = [batch for batch in batches if "ods.alpha" in batch["groups"]]
    assert len(alpha) == 1
    assert alpha[0]["size"] == 2


def test_by_domain_groups_on_the_tables_naming_hints() -> None:
    batches = build_review_batches(_wide(), by="domain", batch_size=30)["batches"]

    groups = {group for batch in batches for group in batch["groups"]}
    assert {"甲域", "乙域", "丙项目"} <= groups


def test_by_domain_falls_back_to_the_project_then_to_one_unlabelled_group() -> None:
    batches = build_review_batches(_wide(), by="domain", batch_size=30)["batches"]

    home = {
        str(row["id"]): row["group"] for batch in batches for row in batch["rows"]
    }
    assert home["concept:table:ods_alpha_di"] == "甲域"
    assert home["concept:table:ods_beta_di"] == "乙域"
    assert home["concept:table:ods_delta"] == "丙项目"
    assert home["concept:table:ods_epsilon"] == UNLABELLED_GROUP


def test_by_size_is_a_plain_chunk_in_impact_order() -> None:
    batches = build_review_batches(_wide(), by="size", batch_size=2)

    ranked = [
        concept["impact"] for batch in batches["batches"] for concept in batch["rows"]
    ]
    assert ranked == sorted(ranked, reverse=True)
    assert [batch["size"] for batch in batches["batches"]][:-1] == [2] * (
        len(batches["batches"]) - 1
    )
    assert all(batch["groups"] == [] for batch in batches["batches"])


def test_the_impact_of_a_concept_is_read_off_the_relations_it_carries() -> None:
    rows = {
        row["id"]: row
        for batch in build_review_batches(_wide(), by="size")["batches"]
        for row in batch["rows"]
    }

    assert rows["concept:table:ods_alpha_di"]["impact"] >= 1
    assert rows["concept:table:ods_epsilon"]["impact"] == 0


def test_an_unknown_grouping_is_refused_rather_than_guessed() -> None:
    with pytest.raises(ValueError):
        build_review_batches(_wide(), by="owner")


def test_the_batches_are_deterministic() -> None:
    first = build_review_batches(_wide(), by="family", batch_size=2)
    second = build_review_batches(_wide(), by="family", batch_size=2)

    assert json.dumps(first, ensure_ascii=False) == json.dumps(second, ensure_ascii=False)


# ---------------------------------------------------- N1b: the three files it writes


def test_the_skeleton_holds_one_empty_merge_into_per_provisional_concept() -> None:
    document = _wide()
    batches = build_review_batches(document, by="family", batch_size=2)

    skeleton = batch_overrides_skeleton(batches["batches"][0], document)

    assert skeleton["doc_format"] == CONCEPT_OVERRIDES_DOC_FORMAT
    assert sorted(skeleton["concepts"]) == sorted(batches["batches"][0]["concepts"])
    assert all(entry["merge_into"] == "" for entry in skeleton["concepts"].values())


def test_the_skeleton_carries_the_batchs_open_item_groups_as_comment_lines() -> None:
    document = json.loads(
        (REPO_ROOT / "tests" / "core" / "fixtures" / "ontology" / "ontology.json").read_text(
            encoding="utf-8"
        )
    )
    batches = build_review_batches(document, by="size", batch_size=30)

    batch = batches["batches"][0]
    skeleton = batch_overrides_skeleton(batch, document)

    mine = {
        str(group["group_id"])
        for group in document["open_item_groups"]
        if str(group["concept"]) in set(batch["concepts"])
    }
    quoted = "\n".join(skeleton["comments"])
    assert mine
    assert all(group_id in quoted for group_id in mine)
    assert all(
        str(group["group_id"]) not in quoted
        for group in document["open_item_groups"]
        if str(group["group_id"]) not in mine
    )


def test_the_unfilled_skeleton_changes_nothing_when_it_is_applied() -> None:
    document = _wide()
    batches = build_review_batches(document, by="family", batch_size=2)
    skeleton = batch_overrides_skeleton(batches["batches"][0], document)

    plain = _built(WIDE_CORPUS, WIDE_RELATIONS)
    filled = _built(WIDE_CORPUS, WIDE_RELATIONS, overrides=[skeleton], files=["batch-01.json"])

    assert filled["concepts"] == plain["concepts"]
    assert _applied(filled)["unmatched"] == []
    assert _applied(filled)["ignored_fields"] == []
    assert _applied(filled)["concepts"] == 0
    # A blank slot is not an answer, so the file won nothing and nothing to conflict on.
    assert _applied(filled)["sources"] == [{"file": "batch-01.json", "applied": 0}]


def test_two_batches_that_both_left_a_slot_blank_have_not_disagreed() -> None:
    document = _wide()
    batches = build_review_batches(document, by="family", batch_size=2)["batches"]
    skeleton = batch_overrides_skeleton(batches[0], document)

    twice = _built(
        WIDE_CORPUS,
        WIDE_RELATIONS,
        overrides=[skeleton, {**skeleton, "comments": ["另一份"]}],
        files=["batch-01.json", "stray.json"],
    )

    assert _applied(twice)["conflicts"] == []


def test_a_filled_slot_beats_a_blank_one_whichever_file_is_first() -> None:
    document = _wide()
    batch = build_review_batches(document, by="family", batch_size=2)["batches"][0]
    skeleton = batch_overrides_skeleton(batch, document)
    identifier = batch["concepts"][0]
    answered = _overrides(**{identifier: {"merge_into": "concept:gamma", **STAMP}})

    folded = _built(
        WIDE_CORPUS,
        WIDE_RELATIONS,
        overrides=[answered, skeleton],
        files=["answered.json", "batch-01.json"],
    )

    assert _applied(folded)["merges"] == 1
    assert _applied(folded)["conflicts"] == []
    assert identifier not in {str(item["id"]) for item in folded["concepts"]}


def test_the_batch_worksheet_names_its_concepts_and_its_merge_targets() -> None:
    document = _wide()
    batch = build_review_batches(document, by="family", batch_size=2)["batches"][0]

    text = render_batch_markdown(batch, document)

    assert text.startswith("# ")
    for concept in batch["concepts"]:
        assert concept in text
    assert "concept:gamma" in text


def test_the_batch_worksheet_prints_the_evidence_a_decision_needs() -> None:
    document = _wide()
    batches = build_review_batches(document, by="family", batch_size=2)["batches"]
    batch = next(
        item for item in batches if "concept:table:ods_delta" in item["concepts"]
    )

    text = render_batch_markdown(batch, document)

    assert "德尔塔台账（合成）" in text
    assert "德尔塔流水主键（合成）" in text
    assert "`row_key`" in text


def test_a_table_nothing_keyed_says_so_rather_than_printing_a_blank() -> None:
    """The M1 case itself: no key is the reason, so the cell is where it belongs."""
    entities = [
        _entity("dim.gamma", keys=["gamma_code"], comment="伽马维表（合成）"),
        _entity("ods.keyless", columns={"note_text": None}),
    ]
    document = _built(entities)
    batch = build_review_batches(document, by="family")["batches"][0]

    assert "concept:table:ods_keyless" in batch["concepts"]
    assert NO_CANDIDATE_KEY in render_batch_markdown(batch, document)


def test_the_index_lists_every_batch_with_its_size_and_the_order_to_read_them() -> None:
    document = _wide()
    batches = build_review_batches(document, by="family", batch_size=2)

    text = render_batch_index_markdown(batches)

    for position, batch in enumerate(batches["batches"], start=1):
        assert batch["id"] in text
        assert f"| {position} |" in text
    assert str(len(batches["batches"])) in text


def test_writing_the_batches_puts_three_kinds_of_file_under_one_directory(
    tmp_path: Path,
) -> None:
    document = _wide()

    written = write_review_batches(document, tmp_path, by="family", batch_size=2)

    assert written[0] == f"{BATCHES_DIR}/index.md"
    assert f"{BATCHES_DIR}/batch-01.md" in written
    assert f"{BATCHES_DIR}/batch-01.overrides.json" in written
    assert all((tmp_path / name).is_file() for name in written)
    skeleton = json.loads(
        (tmp_path / BATCHES_DIR / "batch-01.overrides.json").read_text(encoding="utf-8")
    )
    assert skeleton["doc_format"] == CONCEPT_OVERRIDES_DOC_FORMAT


def test_writing_the_batches_twice_writes_the_same_bytes(tmp_path: Path) -> None:
    document = _wide()

    write_review_batches(document, tmp_path / "first", by="family", batch_size=2)
    write_review_batches(document, tmp_path / "second", by="family", batch_size=2)

    for path in sorted((tmp_path / "first").rglob("*")):
        if path.is_file():
            mirror = tmp_path / "second" / path.relative_to(tmp_path / "first")
            assert path.read_text(encoding="utf-8") == mirror.read_text(encoding="utf-8")


def test_the_default_batch_size_is_the_one_the_documents_quote() -> None:
    assert DEFAULT_BATCH_SIZE == 30
    assert BATCH_BY == ("family", "domain", "size")


# ------------------------------------------------------------------ the CLI, end to end


SCHEMA = {
    "ods.customer_base": ["customer_id", "country_code", "state", "dt"],
    "mart.customer_daily": ["customer_id", "country_code", "dt"],
}

PRODUCER_SQL = (
    "INSERT OVERWRITE TABLE mart.customer_daily PARTITION (dt = '20250101') "
    "SELECT customer_id, max(country_code) AS country_code FROM ods.customer_base "
    "WHERE state IN ('NEW', 'PAID') GROUP BY customer_id"
)

CONSUMER_SQL = (
    "INSERT OVERWRITE TABLE mart.customer_rollup "
    "SELECT b.country_code, count(1) AS n FROM ods.customer_base b "
    "LEFT JOIN mart.customer_daily d ON b.customer_id = d.customer_id "
    "WHERE d.dt = '20250101' GROUP BY b.country_code"
)


def _corpus(root: Path) -> Path:
    for name, sql in (("producer_task", PRODUCER_SQL), ("consumer_task", CONSUMER_SQL)):
        write_statement_documents(parse_scope_lineage(sql, name, schema=SCHEMA), root / name)
    return root


def test_the_cli_writes_the_batches_beside_the_ontology(tmp_path: Path, capsys) -> None:
    corpus = _corpus(tmp_path / "corpus")
    out, review = tmp_path / "out", tmp_path / "review"

    code = main(
        [
            "ontology",
            "--lineage",
            str(corpus),
            "--out",
            str(out),
            "--review-batches",
            str(review),
            "--review-batch-size",
            "2",
        ]
    )

    assert code == 0
    assert (review / BATCHES_DIR / "index.md").is_file()
    ontology = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    provisional = provisional_concept_ids(ontology["concepts"])
    written = sorted((review / BATCHES_DIR).glob("batch-*.overrides.json"))
    named = {
        key
        for path in written
        for key in json.loads(path.read_text(encoding="utf-8"))["concepts"]
    }
    assert named == set(provisional)
    assert "review batches" in capsys.readouterr().out


def test_the_cli_refuses_a_grouping_it_does_not_know(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "ontology",
                "--lineage",
                str(_corpus(tmp_path / "corpus")),
                "--out",
                str(tmp_path / "out"),
                "--review-batches",
                str(tmp_path / "review"),
                "--review-batches-by",
                "owner",
            ]
        )


def test_the_cli_takes_several_overrides_files_in_the_order_given(
    tmp_path: Path, capsys
) -> None:
    corpus = _corpus(tmp_path / "corpus")
    out = tmp_path / "out"
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    identifier = "concept:table:mart_customer_rollup"
    first.write_text(
        json.dumps(_overrides(**{identifier: {"name": "第一稿", **STAMP}}), ensure_ascii=False),
        encoding="utf-8",
    )
    second.write_text(
        json.dumps(_overrides(**{identifier: {"name": "第二稿", **STAMP}}), ensure_ascii=False),
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
            str(first),
            "--concept-overrides",
            str(second),
        ]
    )

    assert code == 0
    ontology = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    applied = ontology["concept_overrides_applied"]
    assert [item["file"] for item in applied["sources"]] == [str(first), str(second)]
    assert applied["conflicts"] == [
        {"key": identifier, "field": "name", "earlier": str(first), "later": str(second)}
    ]
    assert "1 conflict(s)" in capsys.readouterr().out


# ------------------------------------------------------------------------ the prompt


def test_the_prompt_tells_the_reviewer_how_to_work_one_batch_at_a_time() -> None:
    text = REVIEW_PROMPT.read_text(encoding="utf-8")

    assert "## 分批工作" in text
    assert "review-batches" in text
    assert "batch-NN.overrides.json" in text
