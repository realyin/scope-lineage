"""A key pair whose right side is not a bare column proves nothing unique (audit WP2g).

``ON t.region = substr(u.user_id, 1, 2)`` is an equality between two columns, and the
engine records it as a ``join_key_pairs`` entry -- it does join the two relations on
those columns, and dropping the pair would mark every ``substr(a.x,1,6) =
substr(b.x,1,6)`` JOIN ``partial`` with a ``join_keys_not_split`` warning. But many
right rows share one prefix, so "the right side is unique by ``user_id``" says nothing
about how many rows match one left row. Each side of a pair now carries ``bare``; the
uniqueness rules (the fan-out verdict and the ontology's table relations) only read
pairs whose right side is a bare column. A contract written before the field existed is
read by parsing the pair's own ``expression``; one that does not parse counts as not
bare.

Every fixture is synthetic.
"""

from __future__ import annotations

import copy

import pytest

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.ontology import build_ontology
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.render.table_cards import build_table_cards
from scope_lineage.scope.scope_builder import parse_scope_lineage

SCHEMA = {
    "ods.trades": ["id", "buyer_id", "seller_id", "region", "code"],
    "ods.dim_user": ["user_id", "user_name", "code"],
    "src.users": ["user_id", "user_name", "code"],
}

GROUPED = "(SELECT user_id, max(user_name) AS user_name FROM ods.dim_user GROUP BY user_id) u"

NOT_BARE = {
    "substr_right": "t.region = substr(u.user_id, 1, 2)",
    "equality_compared": "(t.buyer_id = u.user_id) = FALSE",
    "if_inequality": "IF(t.buyer_id <> u.user_id, 1, 0) = 1",
}
BARE = {
    "both_bare": "t.buyer_id = u.user_id",
    "left_wrapped": "trim(t.buyer_id) = u.user_id",
    "reversed": "u.user_id = t.buyer_id",
}


def _sql(on: str, right: str = GROUPED) -> str:
    return (
        "INSERT OVERWRITE TABLE dw.t_out SELECT t.id, u.user_name FROM ods.trades t "
        f"LEFT JOIN {right} ON {on}"
    )


def _document(sql: str, task: str = "t") -> dict:
    return to_lineage_dict(parse_scope_lineage(sql, task, schema=SCHEMA))


def _join_detail(document: dict) -> dict:
    return next(
        block["join_relation_detail"]
        for block in document["scopes"]["ROOT"]["logic_blocks"]
        if block.get("join_relation_detail")
    )


def _status(document: dict) -> str:
    risks = build_semantic_profile(document)["output_shape"]["fan_out_risks"]
    assert len(risks) == 1, risks
    return risks[0]["status"]


def _without_bare(document: dict) -> dict:
    old = copy.deepcopy(document)
    for pair in _join_detail(old)["join_key_pairs"]:
        for side in ("left", "right"):
            pair[side].pop("bare", None)
    return old


# --------------------------------------------------------------------- contract


@pytest.mark.parametrize("on", NOT_BARE.values(), ids=NOT_BARE.keys())
def test_a_wrapped_right_side_keeps_its_pair_marked_not_bare(on: str) -> None:
    detail = _join_detail(_document(_sql(on)))
    assert len(detail["join_key_pairs"]) == 1
    assert detail["join_key_pairs"][0]["right"]["bare"] is False
    assert detail["trace_status"] == "complete"


def test_each_side_says_whether_it_is_a_bare_column() -> None:
    sides = {
        name: tuple(
            _join_detail(_document(_sql(on)))["join_key_pairs"][0][side]["bare"]
            for side in ("left", "right")
        )
        for name, on in {**BARE, "substr_right": NOT_BARE["substr_right"]}.items()
    }
    assert sides == {
        "both_bare": (True, True),
        "left_wrapped": (False, True),
        "reversed": (True, True),
        "substr_right": (True, False),
    }


def test_sentinel_a_prefix_join_stays_complete_and_raises_no_warning() -> None:
    on = "substr(t.code, 1, 6) = substr(u.code, 1, 6)"
    result = parse_scope_lineage(_sql(on, "ods.dim_user u"), "t", schema=SCHEMA)
    document = to_lineage_dict(result)
    detail = _join_detail(document)
    assert detail["trace_status"] == "complete"
    assert [(p["left"]["bare"], p["right"]["bare"]) for p in detail["join_key_pairs"]] == [
        (False, False)
    ]
    assert "join_keys_not_split" not in str(document.get("warnings"))
    assert "missing_join_key_pairs" not in detail["missing_reasons"]


# ---------------------------------------------------------------------- fan-out


@pytest.mark.parametrize("on", NOT_BARE.values(), ids=NOT_BARE.keys())
def test_a_wrapped_right_key_does_not_prove_the_join_safe(on: str) -> None:
    assert _status(_document(_sql(on))) != "safe"


@pytest.mark.parametrize("on", NOT_BARE.values(), ids=NOT_BARE.keys())
def test_a_contract_without_the_field_reads_the_same(on: str) -> None:
    assert _status(_without_bare(_document(_sql(on)))) != "safe"


@pytest.mark.parametrize("on", BARE.values(), ids=BARE.keys())
def test_sentinel_a_bare_right_key_still_proves_the_join_safe(on: str) -> None:
    document = _document(_sql(on))
    assert _status(document) == "safe"
    assert _status(_without_bare(document)) == "safe"


def test_an_unparseable_expression_counts_as_not_bare() -> None:
    document = _without_bare(_document(_sql(BARE["both_bare"])))
    _join_detail(document)["join_key_pairs"][0]["expression"] = "((("
    assert _status(document) != "safe"


# --------------------------------------------------------------------- ontology

PRODUCER = (
    "INSERT OVERWRITE TABLE ods.dim_user SELECT user_id, max(user_name) AS user_name, "
    "max(code) AS code FROM src.users GROUP BY user_id"
)


def _relations(on: str, strip: bool = False) -> list[dict]:
    consumer = _document(_sql(on, "ods.dim_user u"), "consumer")
    if strip:
        consumer = _without_bare(consumer)
    documents = [_document(PRODUCER, "producer"), consumer]
    profiles = [build_semantic_profile(document) for document in documents]
    cards = build_table_cards(profiles)
    ontology = build_ontology(documents, profiles, tables=cards, artifact_root="corpus")
    return list(ontology["table_relations"])


def _proven_many_to_one(relations: list[dict]) -> list[dict]:
    return [
        item
        for item in relations
        if (item.get("cardinality") or {}).get("claim") == "many_to_one"
        and (item.get("cardinality") or {}).get("tier") == "proven"
    ]


@pytest.mark.parametrize("strip", [False, True], ids=["with_field", "old_format"])
@pytest.mark.parametrize("on", NOT_BARE.values(), ids=NOT_BARE.keys())
def test_a_wrapped_right_key_makes_no_proven_relation(on: str, strip: bool) -> None:
    assert _proven_many_to_one(_relations(on, strip)) == []


def test_sentinel_a_bare_key_still_makes_a_proven_relation() -> None:
    assert len(_proven_many_to_one(_relations(BARE["both_bare"]))) == 1
