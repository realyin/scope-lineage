"""B2 / B3: which table decides the rows, and what one row probably is when it cannot.

Both rules were measured as wrong answers on one real statement, and both wrong answers
pointed a profile writer at the same lookup table.

**B2 (R7 driving path).** ROOT read a dimension table *and* left-joined a subquery chain
that read an event log, exploded it twice with ``LATERAL VIEW`` and filtered it. The
event log is where every output row comes from; the dimension only hangs names on those
rows. The profile gave all three inputs ``role_in_task: enrich`` -- the log table was
only ever reached through a join key pair, and the driving role was granted off R3's
grain walk, which the explode had already stopped -- and ``structural_summary`` opened
with "ROOT 直接读取 <dimension>". The driving path is therefore walked on its own, off the
contract's ``input_edges``: the FROM item, descended through, never a JOIN's right side,
and unstopped by a LATERAL VIEW, because an explode multiplies the driving table's rows
rather than replacing them.

**B3 (grain candidate).** The same statement published ``grain.basis: unknown`` with the
two LATERAL VIEWs named as the reason, and nothing else. "Unknown" is the honest answer
and it stays the answer -- but when the walk stopped at a *row-multiplying* step whose
upstream grain is itself known, the shape of the answer is provable: one upstream row per
exploded value. That is published beside the verdict as ``grain.candidate``, at
``confidence: hypothesis`` and marked ``[推断]`` in the markdown, so the writer copies a
hypothesis instead of inventing one.

Every negative case here is a statement that looks like one of the two and is not: a
grain the walk *did* decide, and an explode whose own upstream grain is unprovable.
"""

from __future__ import annotations

from scope_lineage.contract import to_lineage_dict
from scope_lineage.render.semantic_markdown import render_semantic_markdown
from scope_lineage.render.semantic_profile import build_semantic_profile
from scope_lineage.scope.scope_builder import parse_scope_lineage


SCHEMA = {
    "ods.event_log": ["unit_code", "payload", "dt"],
    "ods.dim_unit": ["unit_code", "unit_name"],
    "ods.dim_area": ["unit_code", "area_name"],
    "ods.main": ["unit_code", "amount", "dt"],
    "ods.side": ["unit_code", "flag", "dt"],
    "ods.other": ["unit_code", "flag", "dt"],
}

# The corpus statement B2 and B3 were measured on, with synthetic names: ROOT's FROM item
# is a subquery chain over the log table that explodes twice, and the two dimensions are
# left-joined onto it.
EXPLODED_CHAIN_SQL = (
    "INSERT INTO mart.t SELECT b.unit_code, b.item, b.tag, d.unit_name, g.area_name "
    "FROM (SELECT a.unit_code, a.item, tg.tag FROM "
    "(SELECT e.unit_code, it.item FROM ods.event_log e "
    "LATERAL VIEW EXPLODE(SPLIT(e.payload, ',')) it AS item WHERE e.dt = '20260101') a "
    "LATERAL VIEW EXPLODE(SPLIT(a.item, ';')) tg AS tag) b "
    "LEFT JOIN ods.dim_unit d ON b.unit_code = d.unit_code "
    "LEFT JOIN ods.dim_area g ON b.unit_code = g.unit_code"
)


def _profile(sql: str, task_id: str = "driving_case") -> dict:
    return build_semantic_profile(
        to_lineage_dict(parse_scope_lineage(sql, task_id, schema=SCHEMA))
    )


def _roles(profile: dict) -> dict[str, str | None]:
    return {item["table"]: item["role_in_task"] for item in profile["inputs"]}


def _all_roles(profile: dict) -> dict[str, list[str]]:
    return {item["table"]: item["roles"] for item in profile["inputs"]}


def _markdown(sql: str) -> str:
    return render_semantic_markdown(
        build_semantic_profile(
            to_lineage_dict(parse_scope_lineage(sql, "driving_case", schema=SCHEMA))
        ),
        sections=["shape"],
    )


# ------------------------------------------------------- B2: where the rows come from


def test_the_driving_table_is_read_through_the_exploding_subquery_chain() -> None:
    """The measured failure: every input was ``enrich`` and the log table drove them all."""
    profile = _profile(EXPLODED_CHAIN_SQL)

    assert _roles(profile) == {
        "ods.dim_area": "enrich",
        "ods.dim_unit": "enrich",
        "ods.event_log": "driving",
    }


def test_the_driving_table_carries_the_scope_path_it_was_reached_through() -> None:
    profile = _profile(EXPLODED_CHAIN_SQL)

    assert profile["task"]["driving_tables"] == [
        {
            "table": "ods.event_log",
            "via_scopes": ["subq:b", "subq:a"],
            "lateral_view_scopes": ["subq:b", "subq:a"],
        }
    ]


def test_the_structural_summary_names_the_row_source_before_the_dimensions() -> None:
    summary = _profile(EXPLODED_CHAIN_SQL)["task"]["structural_summary"]

    assert summary.startswith(
        "行来源 ods.event_log（经 subq:a → subq:b 两次 LATERAL VIEW 展开）；"
        "补充 ods.dim_area、ods.dim_unit；"
    )


def test_a_left_joined_table_is_enrichment_and_never_the_driving_one() -> None:
    profile = _profile(
        "INSERT INTO mart.t SELECT m.unit_code, m.amount, s.flag "
        "FROM ods.main m LEFT JOIN ods.side s ON m.unit_code = s.unit_code"
    )

    assert _roles(profile) == {"ods.main": "driving", "ods.side": "enrich"}


def test_an_inner_joined_partner_is_a_filter_partner_not_mere_enrichment() -> None:
    """An INNER JOIN's right side drops left rows that do not match, which ``enrich`` denies."""
    profile = _profile(
        "INSERT INTO mart.t SELECT m.unit_code, m.amount, s.flag "
        "FROM ods.main m INNER JOIN ods.side s ON m.unit_code = s.unit_code"
    )

    assert _roles(profile) == {"ods.main": "driving", "ods.side": "filter_partner"}
    assert "filter_partner" in _all_roles(profile)["ods.side"]


def test_a_right_join_swaps_which_side_drives() -> None:
    profile = _profile(
        "INSERT INTO mart.t SELECT m.unit_code, m.amount, s.flag "
        "FROM ods.main m RIGHT JOIN ods.side s ON m.unit_code = s.unit_code"
    )

    assert _roles(profile) == {"ods.main": "enrich", "ods.side": "driving"}


def test_a_full_join_leaves_both_sides_driving() -> None:
    """Neither side is optional, so the rows follow both -- as a UNION's rows do."""
    profile = _profile(
        "INSERT INTO mart.t SELECT m.unit_code, m.amount, s.flag "
        "FROM ods.main m FULL OUTER JOIN ods.side s ON m.unit_code = s.unit_code"
    )

    assert _roles(profile) == {"ods.main": "driving", "ods.side": "driving"}
    assert [item["table"] for item in profile["task"]["driving_tables"]] == [
        "ods.main",
        "ods.side",
    ]


def test_a_union_drives_from_every_branch() -> None:
    profile = _profile(
        "INSERT INTO mart.t SELECT u.unit_code, u.flag FROM "
        "(SELECT unit_code, flag FROM ods.side "
        "UNION ALL SELECT unit_code, flag FROM ods.other) u"
    )

    assert [item["table"] for item in profile["task"]["driving_tables"]] == [
        "ods.side",
        "ods.other",
    ]
    assert _all_roles(profile)["ods.side"][0] == "driving"
    assert _all_roles(profile)["ods.other"][0] == "driving"


def test_a_directly_read_table_needs_no_path_and_says_so() -> None:
    profile = _profile(
        "INSERT INTO mart.t SELECT unit_code, amount FROM ods.main WHERE dt = '20260101'"
    )

    assert profile["task"]["driving_tables"] == [
        {"table": "ods.main", "via_scopes": [], "lateral_view_scopes": []}
    ]
    assert profile["task"]["structural_summary"].startswith("行来源 ods.main；")


# ------------------------------------------ B3: a candidate when the grain is unknown


def test_a_row_multiplying_explode_publishes_a_grain_candidate() -> None:
    grain = _profile(EXPLODED_CHAIN_SQL)["output_shape"]["grain"]

    assert grain["basis"] == "unknown"
    assert grain["candidate"]["basis"] == "candidate"
    assert grain["candidate"]["confidence"] == "hypothesis"
    assert grain["candidate"]["row_source"] == "ods.event_log"
    assert [
        (key["scope_id"], key["name"]) for key in grain["candidate"]["keys"]
    ] == [("udtf:it", "item"), ("udtf:tg", "tag")]
    assert grain["candidate"]["evidence"] == ["subq:b", "subq:a"]


def test_the_candidate_reason_names_the_expansion_and_the_grain_it_expanded() -> None:
    candidate = _profile(EXPLODED_CHAIN_SQL)["output_shape"]["grain"]["candidate"]

    assert candidate["reason"] == (
        "subq:a → subq:b 的 LATERAL VIEW 使行数展开；"
        "展开前 ods.event_log 的粒度依据 driving_table_rows"
    )


def test_the_candidate_keys_carry_the_physical_column_the_explode_read() -> None:
    candidate = _profile(EXPLODED_CHAIN_SQL)["output_shape"]["grain"]["candidate"]

    assert candidate["keys"][0]["physical_sources"] == [
        {"table": "ods.event_log", "column": "payload"}
    ]


def test_an_upstream_grain_that_is_itself_unknown_gets_no_candidate() -> None:
    """A UNION under the explode leaves nothing to multiply, so nothing is offered."""
    grain = _profile(
        "INSERT INTO mart.t SELECT b.unit_code, b.item FROM "
        "(SELECT u.unit_code, it.item FROM "
        "(SELECT unit_code, payload FROM ods.event_log "
        "UNION ALL SELECT unit_code, payload FROM ods.event_log) u "
        "LATERAL VIEW EXPLODE(SPLIT(u.payload, ',')) it AS item) b"
    )["output_shape"]["grain"]

    assert grain["basis"] == "unknown"
    assert "candidate" not in grain


def test_a_grain_the_walk_decided_is_never_given_a_candidate() -> None:
    grain = _profile(
        "INSERT INTO mart.t SELECT m.unit_code, m.amount, s.flag "
        "FROM ods.main m LEFT JOIN ods.side s ON m.unit_code = s.unit_code"
    )["output_shape"]["grain"]

    assert grain["basis"] == "driving_table_rows"
    assert "candidate" not in grain


def test_the_markdown_offers_the_candidate_after_the_undecided_verdict() -> None:
    line = next(
        item
        for item in _markdown(EXPLODED_CHAIN_SQL).splitlines()
        if "粒度：" in item
    )

    assert "未能判定（basis=unknown" in line
    assert (
        "；候选：一行 = `ods.event_log` 的一行 × `udtf:it.item` × `udtf:tg.tag`（" in line
    )
    # The caveat closes the candidate clause; the line's own `（结构推断；…）` tag follows
    # it, as it does on every other line of this document.
    assert "的粒度依据 driving_table_rows）[推断]（结构推断；" in line


def test_an_undecided_grain_without_a_candidate_keeps_the_bare_verdict() -> None:
    line = next(
        item
        for item in _markdown(
            "INSERT INTO mart.t SELECT b.unit_code, b.item FROM "
            "(SELECT u.unit_code, it.item FROM "
            "(SELECT unit_code, payload FROM ods.event_log "
            "UNION ALL SELECT unit_code, payload FROM ods.event_log) u "
            "LATERAL VIEW EXPLODE(SPLIT(u.payload, ',')) it AS item) b"
        ).splitlines()
        if "粒度：" in item
    )

    assert "未能判定" in line
    assert "候选" not in line
