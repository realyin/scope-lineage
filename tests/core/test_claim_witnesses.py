"""Semantic witnesses: every sound rule's claim, checked against SQLite on real rows (WP4).

Each case pairs one statement with the claim the tool makes about it and the property
that claim asserts on data. Over thirty seeded small-domain corpora, plus the hand-built
counterexample where one exists:

- a positive case must be claimed (so the witness is not vacuous) and must hold on every
  corpus;
- a negative case must NOT be claimed, and some corpus must break the property -- the
  proof that the tool is right to withhold it.

See ``claim_witness.py`` for what SQLite does and does not stand in for.
"""

from __future__ import annotations

from typing import Callable, NamedTuple, Sequence

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.glossary import apply_glossary, build_glossary
from scope_lineage.render.semantic_profile import build_semantic_profile, card_key_claim
from scope_lineage.render.table_cards import build_table_cards
from scope_lineage.scope.scope_builder import parse_scope_lineage

from .claim_witness import (
    SQLITE_SUPPORTS_WINDOWS,
    connect,
    datasets,
    query,
    schema_map,
    unique_by,
)

pytestmark = pytest.mark.skipif(
    not SQLITE_SUPPORTS_WINDOWS, reason="SQLite without window functions"
)

# Rows that break every uniqueness a ranking tie or a repeated key could fake.
TIES = {
    "ods.e": [(1, 10, 100, 1, 1), (1, 20, 100, 1, 1), (2, 30, 100, 2, 0)],
    "ods.base": [(0, 1, 1), (1, 2, 2)],
}


def _profile(sql: str, task: str = "witness", cards=None) -> dict:
    document = to_lineage_dict(parse_scope_lineage(sql, task, schema=schema_map()))
    return build_semantic_profile(document, table_cards=cards)


def _corpora(case_seed: int) -> list[dict]:
    return [TIES, *datasets(case_seed)]


# ---------------------------------------------------------------- output keys


class KeyCase(NamedTuple):
    rule: str
    select: str
    claimed: bool


KEY_CASES = [
    KeyCase("R-GROUPBY-KEY", "SELECT id, MAX(v) AS v FROM ods.e GROUP BY id", True),
    KeyCase(
        "R-GROUPBY-KEY",
        "SELECT id, ts, COUNT(*) AS n FROM ods.e GROUP BY id, ts",
        True,
    ),
    KeyCase("R-DISTINCT-KEY", "SELECT DISTINCT id, v FROM ods.e", True),
    KeyCase(
        "R-ROWNUM-FIRST",
        "SELECT id, v FROM (SELECT id, v, ROW_NUMBER() OVER "
        "(PARTITION BY id ORDER BY ts) AS rn FROM ods.e) r WHERE rn = 1",
        True,
    ),
    KeyCase(
        "R-RANK-FIRST",
        "SELECT id, v FROM (SELECT id, v, RANK() OVER "
        "(PARTITION BY id ORDER BY ts) AS rk FROM ods.e) r WHERE rk = 1",
        False,
    ),
    KeyCase(
        "R-RANK-FIRST",
        "SELECT id, v FROM (SELECT id, v, DENSE_RANK() OVER "
        "(PARTITION BY id ORDER BY ts) AS rk FROM ods.e) r WHERE rk = 1",
        False,
    ),
    KeyCase("R-EMPTY-GROUPING", "SELECT COUNT(*) AS n FROM ods.e", True),
    KeyCase(
        "R-PIN-DROP",
        "SELECT id, dt, MAX(v) AS v FROM ods.e WHERE dt = 1 GROUP BY id, dt",
        True,
    ),
    KeyCase(
        "R-JOIN-BEFORE-GROUPING",
        "SELECT e.id, SUM(e.v) AS s FROM ods.e e JOIN ods.base b ON e.id = b.id "
        "GROUP BY e.id",
        True,
    ),
    KeyCase(
        "R-JOIN-PRESERVE",
        "SELECT g.id, b.b FROM (SELECT id FROM ods.e GROUP BY id) g "
        "JOIN ods.base b ON g.id = b.id",
        False,
    ),
    KeyCase("no rule", "SELECT id, v FROM ods.e", False),
]


@pytest.mark.parametrize(
    "case", KEY_CASES, ids=[f"{case.rule}-{index}" for index, case in enumerate(KEY_CASES)]
)
def test_a_proven_output_key_holds_on_every_corpus(case: KeyCase) -> None:
    shape = _profile(f"INSERT OVERWRITE TABLE mart.t {case.select}")["output_shape"]
    claimed = shape["key_confidence"] == "proven"
    keys = list(shape["candidate_keys"])

    assert claimed is case.claimed, shape["key_confidence"]
    outcomes = []
    for corpus in _corpora(len(case.select)):
        columns, rows = query(connect(corpus), case.select)
        outcomes.append(unique_by(columns, rows, keys if claimed else columns[:1]))
    if claimed:
        assert all(outcomes)
    else:
        assert not all(outcomes), "no corpus breaks it: the negative case proves nothing"


# ------------------------------------------------------------------ JOIN fan-out


class FanOutCase(NamedTuple):
    rule: str
    right: str
    on: str
    safe: bool
    # The tool withholds a claim that would in fact hold: incomplete, not unsound. Kept
    # visible so the day it is made, this flag has to go.
    conservative: bool = False


FAN_OUT_CASES = [
    FanOutCase("R-GROUPBY-KEY", "SELECT id, MAX(v) AS v FROM ods.e GROUP BY id", "b.id = r.id", True),
    FanOutCase(
        "R-ROWNUM-FIRST",
        "SELECT id, v, ROW_NUMBER() OVER (PARTITION BY id ORDER BY ts) AS rn FROM ods.e",
        "b.id = r.id AND r.rn = 1",
        True,
    ),
    FanOutCase(
        "R-RANK-FIRST",
        "SELECT id, v, RANK() OVER (PARTITION BY id ORDER BY ts) AS rn FROM ods.e",
        "b.id = r.id AND r.rn = 1",
        False,
    ),
    FanOutCase(
        "R-GROUPBY-KEY",
        "SELECT id, ts, MAX(v) AS v FROM ods.e GROUP BY id, ts",
        "b.id = r.id",
        False,
    ),
    FanOutCase(
        "R-PIN-DROP",
        "SELECT id, dt, MAX(v) AS v FROM ods.e WHERE dt = 1 GROUP BY id, dt",
        "b.id = r.id",
        True,
    ),
    FanOutCase("R-EMPTY-GROUPING", "SELECT MAX(v) AS v FROM ods.e", "1 = 1", True),
]


@pytest.mark.parametrize(
    "case",
    FAN_OUT_CASES,
    ids=[f"{case.rule}-{index}" for index, case in enumerate(FAN_OUT_CASES)],
)
def test_a_safe_join_never_duplicates_a_base_row(case: FanOutCase) -> None:
    select = f"SELECT b.rid, r.v FROM ods.base b LEFT JOIN ({case.right}) r ON {case.on}"
    risks = _profile(f"INSERT OVERWRITE TABLE mart.t {select}")["output_shape"][
        "fan_out_risks"
    ]
    safe = bool(risks) and all(risk["status"] == "safe" for risk in risks)

    assert safe is case.safe, risks
    outcomes = [
        unique_by(*query(connect(corpus), select), ["rid"])
        for corpus in _corpora(len(select))
    ]
    if safe:
        assert all(outcomes)
    elif case.conservative:
        assert all(outcomes), "a conservative case must in fact hold"
    else:
        assert not all(outcomes), "no corpus duplicates a row: the negative proves nothing"


# ----------------------------------------------------- a key carried across tasks


class Producer(NamedTuple):
    """One write to ``mart.dim``: its SQL for the tool, its run history for SQLite."""

    sql: str
    runs: Sequence[str]


WHOLE = Producer(
    "CREATE TABLE mart.dim AS SELECT id, MAX(v) AS v, 1 AS dt FROM ods.e GROUP BY id",
    [
        "DELETE FROM mart.dim",
        "INSERT INTO mart.dim SELECT id, MAX(v), 1 FROM ods.e GROUP BY id",
    ],
)
APPEND = Producer(
    "INSERT INTO mart.dim SELECT id, MAX(v) AS v, 1 AS dt FROM ods.e GROUP BY id",
    ["INSERT INTO mart.dim SELECT id, MAX(v), 1 FROM ods.e GROUP BY id"] * 2,
)
PARTITIONED = Producer(
    "INSERT OVERWRITE TABLE mart.dim PARTITION (dt = '1') "
    "SELECT id, MAX(v) AS v FROM ods.e GROUP BY id",
    [
        statement
        for day in (1, 2)
        for statement in (
            f"DELETE FROM mart.dim WHERE dt = {day}",
            f"INSERT INTO mart.dim SELECT id, MAX(v), {day} FROM ods.e GROUP BY id",
        )
    ],
)
UNKEYED = Producer(
    "INSERT OVERWRITE TABLE mart.dim SELECT id, v, dt FROM ods.e",
    ["DELETE FROM mart.dim", "INSERT INTO mart.dim SELECT id, v, dt FROM ods.e"],
)

READ_ALL = "SELECT b.rid, d.v FROM ods.base b LEFT JOIN mart.dim d ON b.id = d.id"
READ_ONE_DAY = (
    "SELECT b.rid, d.v FROM ods.base b LEFT JOIN mart.dim d ON b.id = d.id WHERE d.dt = 1"
)


class CardCase(NamedTuple):
    name: str
    producers: Sequence[Producer]
    read: str
    safe: bool


CARD_CASES = [
    CardCase("R-REPLACE-STATE", [WHOLE], READ_ALL, True),
    CardCase("appending producer", [APPEND], READ_ALL, False),
    CardCase("R-PARTITION-STATE across days", [PARTITIONED], READ_ALL, False),
    CardCase("R-READ-PIN", [PARTITIONED], READ_ONE_DAY, True),
    CardCase("R-PRODUCERS-AGREE violated", [WHOLE, UNKEYED], READ_ALL, False),
]


@pytest.mark.parametrize("case", CARD_CASES, ids=[case.name for case in CARD_CASES])
def test_a_card_proven_join_never_duplicates_a_base_row(case: CardCase) -> None:
    profiles = [
        _profile(producer.sql, f"producer_{index}")
        for index, producer in enumerate(case.producers)
    ]
    cards = build_table_cards(profiles)
    risks = _profile(
        f"INSERT OVERWRITE TABLE mart.t {case.read}", "consumer", cards
    )["output_shape"]["fan_out_risks"]
    safe = bool(risks) and all(risk["status"] == "safe" for risk in risks)

    assert safe is case.safe, risks
    outcomes = []
    for corpus in _corpora(len(case.name)):
        db = connect(corpus)
        for producer in case.producers:
            for statement in producer.runs:
                db.execute(statement)
        outcomes.append(unique_by(*query(db, case.read), ["rid"]))
    if safe:
        assert all(outcomes)
    else:
        assert not all(outcomes), "no history duplicates a row: the negative proves nothing"


def test_the_card_claim_names_the_premise_the_witness_simulates() -> None:
    """The simulated histories contain every writer: ``A-WRITERS-CLOSED`` is what they
    assume, and the claim says so rather than leaving it implicit."""
    cards = build_table_cards([_profile(WHOLE.sql, "producer_0")])
    claim = card_key_claim(next(item for item in cards["tables"] if item["table"] == "mart.dim"))

    assert claim.assumptions == ("A-WRITERS-CLOSED",)


# ------------------------------------------------------------- closed value sets


FILTERED = "SELECT id FROM ods.e WHERE id IN (1, 2)"
UNFILTERED = "SELECT id FROM ods.e"


def _closed_domain(reader: str, readers_task: str) -> tuple[bool, set]:
    documents = [
        to_lineage_dict(
            parse_scope_lineage(
                f"INSERT OVERWRITE TABLE mart.{task} {sql}", task, schema=schema_map()
            )
        )
        for task, sql in (("filtered", FILTERED), ("unfiltered", UNFILTERED))
    ]
    glossary = build_glossary(documents, artifact_root="corpus")
    profile = apply_glossary(_profile(f"INSERT OVERWRITE TABLE mart.{readers_task} {reader}", readers_task), glossary)
    field = next(item for item in profile["fields"] if item["column"] == "id")
    domain = field.get("value_domain") or []
    closed = bool(domain) and all(item["closed_set"] for item in domain)
    return closed, {int(item["value"]) for item in domain}


@pytest.mark.parametrize(
    ("reader", "task", "closed"),
    [(FILTERED, "filtered", True), (UNFILTERED, "unfiltered", False)],
    ids=["R-IN-FILTER own statement", "R-IN-FILTER another statement"],
)
def test_a_closed_value_set_holds_for_every_row_written(
    reader: str, task: str, closed: bool
) -> None:
    claimed, values = _closed_domain(reader, task)

    assert claimed is closed
    outcomes = [
        {row[0] for row in query(connect(corpus), reader)[1]} <= values
        for corpus in _corpora(len(reader))
    ]
    if claimed:
        assert all(outcomes)
    else:
        assert not all(outcomes), "no corpus writes another value: the negative proves nothing"


# ------------------------------------------------------------- the harness itself


def test_the_witness_database_sees_a_tie_rank_keeps() -> None:
    _columns, rows = query(
        connect(TIES),
        "SELECT id FROM (SELECT id, RANK() OVER (PARTITION BY id ORDER BY ts) AS rk "
        "FROM ods.e) r WHERE rk = 1",
    )

    assert sorted(rows) == [(1,), (1,), (2,)]


def test_uniqueness_is_checked_on_the_named_keys() -> None:
    check: Callable = unique_by

    assert check(["a", "b"], [(1, 1), (1, 2)], ["b"])
    assert not check(["a", "b"], [(1, 1), (1, 2)], ["a"])
    assert check(["a"], [(1,)], [])
    assert not check(["a"], [(1,), (2,)], [])
